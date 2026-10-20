"""Smart table: prezzo ricalcolato dal server, pagamento prima di tutto, dopo il
pagamento richiesta nel gestionale + ordine NFC della placca recensioni.

    SBFC_NO_BG=1 venv/bin/python -m unittest tests.test_smart_table -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, RichiestaNfc, OrdineNfc, Pagamento  # noqa: E402
from services import smart_table as st  # noqa: E402
from routes import nfc  # noqa: E402

BASE = {'sel': {'menu': True, 'recensioni': True},
        'm': {'tavoli': 10, 'fmt': 'nero', 'pers': True, 'tipo': 'Osteria', 'nome': 'Ventitré', 'colore': '#b08a3e', 'colore_nome': 'Oro'},
        'r': {'placche': 1, 'stampa': False, 'pers': False, 'variante': 'chiara'},
        'oggi': 'carta', 'link': 'no', 'links': {}}


class TestCalcolo(unittest.TestCase):
    def test_esempio_della_pagina(self):
        c = st.calcola(st.pulisci(BASE))
        self.assertEqual(c['subito'], 18000 + 9900 + 3500 + 1500)   # 329 €
        self.assertEqual(c['mese'], 1900)
        self.assertFalse(c['da_definire'])
        self.assertTrue(c['spedire'])

    def test_il_browser_non_decide_il_prezzo(self):
        x = dict(BASE, m=dict(BASE['m'], tavoli=99999, fmt='oro'), subito=1, prezzo=1)
        c = st.calcola(st.pulisci(x))
        self.assertEqual(c['subito'], 80 * 1800 + 9900 + 3500 + 1500)   # tavoli limitati, plexiglas bianco di default

    def test_file_da_stampare_e_preventivo(self):
        c = st.calcola(st.pulisci({'sel': {'menu': True}, 'm': {'fmt': 'stampa'}, 'oggi': 'dig'}))
        self.assertEqual(c['subito'], 4900)
        self.assertEqual(c['oggi'], 4900 + 1900)
        self.assertFalse(c['spedire'])
        c = st.calcola(st.pulisci({'sel': {'social': True}, 'link': 'si'}))
        self.assertEqual(c['subito'], 0)
        self.assertEqual(c['oggi'], 0)
        self.assertTrue(c['da_definire'])
        # solo placca recensioni: niente canone, pagamento semplice
        c = st.calcola(st.pulisci({'sel': {'recensioni': True}, 'link': 'si'}))
        self.assertEqual((c['subito'], c['mese'], c['oggi']), (3500, 0, 3500))

    def test_email_senza_codici_esadecimali_a_vista(self):
        conf = st.pulisci(BASE)
        h = st.email_html(conf, st.calcola(conf), 'Mario', True)
        self.assertIn('Buongiorno Mario', h)
        self.assertIn('Oro', h)
        self.assertIn('348 €', h)
        self.assertNotIn('>#b08a3e', h)


class TestOrdine(unittest.TestCase):
    def setUp(self):
        with app.app_context():
            db.drop_all(); db.create_all()
        self.c = app.test_client()

    def _invia(self, conf, **extra):
        data = {'config': json.dumps(conf), 'email': 'mario@x.it', 'nome': 'Mario', 'nome_locale': 'Ventitré', **extra}
        return self.c.post('/api/smart-table/ordine', data=data, content_type='multipart/form-data')

    def test_senza_prezzo_solo_richiesta(self):
        with mock.patch('utils.email.invia_email', return_value=True) as e:
            r = self._invia({'sel': {'social': True}, 'link': 'si', 'links': {'instagram': 'https://instagram.com/x'}})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json['pagamento'])
        with app.app_context():
            self.assertEqual(RichiestaNfc.query.count(), 1)
        self.assertEqual(e.call_count, 2)

    def test_con_prezzo_si_paga_prima(self):
        visti = []
        with mock.patch.object(nfc.stripe.checkout.Session, 'create', side_effect=lambda **k: visti.append(k) or mock.Mock(url='https://stripe.test/s', id='cs_1')):
            r = self._invia(BASE, logo=(io.BytesIO(b'\x89PNG fake'), 'logo.png', 'image/png'))
        self.assertEqual(r.status_code, 200, r.json)
        self.assertTrue(r.json['pagamento'])
        self.assertEqual(r.json['url'], 'https://stripe.test/s')
        self.assertEqual(sum(x['price_data']['unit_amount'] for x in visti[0]['line_items']), 32900 + 1900)
        self.assertEqual(visti[0]['mode'], 'subscription')
        self.assertEqual([x['price_data'].get('recurring') for x in visti[0]['line_items'] if x['price_data'].get('recurring')], [{'interval': 'month'}])
        self.assertEqual(visti[0]['metadata']['tipo'], 'smart')
        self.assertIn('shipping_address_collection', visti[0])
        with app.app_context():
            self.assertEqual(RichiestaNfc.query.count(), 0)   # la richiesta nasce solo a pagamento fatto
            oid = st.OrdineSmartTable.query.one().id
        # webhook
        sess = mock.Mock(id='cs_1', amount_total=34800, subscription='sub_1', metadata={'tipo': 'smart', 'ordine_id': str(oid)},
                         customer_details=mock.Mock(phone='+39 333'), shipping_details=None, collected_information=None)
        with app.app_context(), mock.patch('utils.email.invia_email', return_value=True) as e:
            st.gestisci_pagamento_smart(sess)
            st.gestisci_pagamento_smart(sess)   # idempotente
            o = st.OrdineSmartTable.query.get(oid)
            self.assertEqual(o.stato, 'pagato')
            self.assertEqual(Pagamento.query.filter_by(prodotto='smart-table').count(), 1)
            ric = RichiestaNfc.query.one()
            self.assertIn('[PAGATO 348 €]', ric.messaggio)
            self.assertEqual(o.abbonamento_id, 'sub_1')
            on = OrdineNfc.query.one()
            self.assertEqual((on.tier, on.variante, on.stato), ('base', 'chiara', 'pagato'))
            self.assertEqual(e.call_count, 2)


if __name__ == '__main__':
    unittest.main()
