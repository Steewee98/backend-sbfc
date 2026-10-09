"""Manuale «Il manager della ristorazione»: prezzo 15 € ai nuovi e 12 € a chi è già nei lead
delle schede, PDF tenuto nel database e scaricabile solo dal link firmato di chi ha pagato,
campagna email senza i disiscritti.

    SBFC_NO_BG=1 venv/bin/python -m unittest tests.test_manuale -v
"""
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, LeadStrumento, Pagamento, EmailSequenza  # noqa: E402
from routes import pagamenti  # noqa: E402
from routes.lead_strumenti import _email_uniche_consenso  # noqa: E402

H = {'X-Admin-Token': 'test-token'}
PDF = b'%PDF-1.4 manuale di prova'
P = pagamenti.PRODOTTI['manager-ristorazione']


class TestManuale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = app.test_client()
        with app.app_context():
            db.create_all()
            db.session.add(LeadStrumento(email='Lettore@Esempio.it', strumento='scheda-food-cost', consenso_marketing=True))
            db.session.add(LeadStrumento(email='via@esempio.it', strumento='quiz-numeri', consenso_marketing=True))
            db.session.add(LeadStrumento(email='senza@esempio.it', strumento='quiz-numeri', consenso_marketing=False))
            if not EmailSequenza.query.filter_by(email='via@esempio.it').first():
                db.session.add(EmailSequenza(email='via@esempio.it', segmento='numeri', step=2, stato='disiscritta'))
            db.session.commit()

    def test_prezzo_nuovo_e_lead(self):
        with app.app_context():
            self.assertEqual(pagamenti.prezzo_per(P, 'nuovo@esempio.it'), 1500)
            self.assertEqual(pagamenti.prezzo_per(P, ' lettore@esempio.IT '), 1200)
            self.assertEqual(pagamenti.prezzo_per(P, None), 1500)
            # gli altri prodotti non cambiano
            self.assertEqual(pagamenti.prezzo_per(pagamenti.PRODOTTI['cruscotto-imprenditore'], 'lettore@esempio.it'), 2500)

    def test_checkout_manda_a_stripe_il_prezzo_giusto(self):
        visti = []
        def finto(**k):
            visti.append(k)
            return mock.Mock(url='https://stripe.test/x')
        with mock.patch.object(pagamenti.stripe.checkout.Session, 'create', side_effect=finto):
            r1 = self.c.post('/api/checkout', json={'prodotto': 'manager-ristorazione', 'email': 'lettore@esempio.it'})
            r2 = self.c.post('/api/checkout', json={'prodotto': 'manager-ristorazione', 'email': 'nuovo@esempio.it'})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.json['url'], 'https://stripe.test/x')
        self.assertEqual(visti[0]['line_items'][0]['price_data']['unit_amount'], 1200)
        self.assertEqual(visti[1]['line_items'][0]['price_data']['unit_amount'], 1500)
        self.assertEqual(visti[0]['customer_email'], 'lettore@esempio.it')
        self.assertTrue(visti[0]['success_url'].endswith('/academy.html?acquisto=manuale#formazione'))

    def test_download_solo_con_firma_e_pagamento(self):
        r = self.c.post('/api/admin/file/manager-ristorazione',
                        data={'file': (io.BytesIO(PDF), 'il-manager-della-ristorazione.pdf', 'application/pdf')},
                        content_type='multipart/form-data')
        self.assertEqual(r.status_code, 401)
        r = self.c.post('/api/admin/file/manager-ristorazione', headers=H,
                        data={'file': (io.BytesIO(PDF), 'il-manager-della-ristorazione.pdf', 'application/pdf')},
                        content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200)
        with app.app_context():
            link = pagamenti.link_download('manager-ristorazione', 'Compratore@Esempio.it')
        percorso = link.split('.app', 1)[1]
        self.assertEqual(self.c.get(percorso).status_code, 403)          # non ha ancora pagato
        self.assertEqual(self.c.get(percorso.replace('t=', 't=x')).status_code, 403)  # firma sbagliata
        with app.app_context():
            db.session.add(Pagamento(nome='C', email='compratore@esempio.it', prodotto='manager-ristorazione',
                                     importo=15, stato='completato', stripe_id='cs_1'))
            db.session.commit()
        r = self.c.get(percorso)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, PDF)
        self.assertIn('attachment', r.headers['Content-Disposition'])
        # il link di un altro non apre il file
        with app.app_context():
            altro = pagamenti.link_download('manager-ristorazione', 'lettore@esempio.it').split('.app', 1)[1]
        self.assertEqual(self.c.get(altro).status_code, 403)

    def test_consegna_usa_il_link_firmato(self):
        mandate = []
        with app.app_context(), mock.patch('utils.email.invia_email', side_effect=lambda *a: mandate.append(a) or True):
            pagamenti._consegna_pdf('Ada', 'ada@esempio.it', P, 12.0, 'cs_2')
        self.assertIn('/api/download/manager-ristorazione?e=ada%40esempio.it&t=', mandate[0][3])
        self.assertNotIn('assets/pdf', mandate[0][3])
        self.assertIn('Il manager della ristorazione', mandate[1][2])

    def test_campagna_senza_disiscritti_ne_senza_consenso(self):
        with app.app_context():
            self.assertEqual(_email_uniche_consenso(), ['lettore@esempio.it'])
        r = self.c.post('/api/lead-strumenti/campagna', headers=H, json={'mode': 'test', 'to': 'prova@esempio.it', 'campagna': 'manuale'})
        self.assertIn(r.status_code, (200, 503))   # 503 = niente chiave Resend nei test: non invia


class TestCoda(unittest.TestCase):
    """La campagna parte a scaglioni: non più di N al giorno, finché la lista non finisce."""

    def test_cinquanta_al_giorno_fino_alla_fine(self):
        from datetime import datetime, timedelta
        from models import CodaCampagna
        from routes import lead_strumenti as ls
        with app.app_context():
            emails = ['p%03d@esempio.it' % i for i in range(120)] + ['via@esempio.it']
            self.assertEqual(ls.accoda_campagna('manuale', emails), 121)
            self.assertEqual(ls.accoda_campagna('manuale', emails), 0)   # niente doppioni
            mandate = []
            g1 = datetime(2026, 10, 9, 8, 0)
            with mock.patch('services.email_service.invia_manuale_a', side_effect=lambda e: mandate.append(e) or 'id'), \
                    mock.patch.object(ls.time, 'sleep'):
                self.assertEqual(ls.processa_coda(50, g1), {'manuale': 50})
                self.assertEqual(ls.processa_coda(50, g1 + timedelta(hours=3)), {})   # stesso giorno: quota finita
                self.assertEqual(ls.processa_coda(50, g1 + timedelta(days=1)), {'manuale': 50})
                self.assertEqual(ls.processa_coda(50, g1 + timedelta(days=2)), {'manuale': 20})
                self.assertEqual(ls.processa_coda(50, g1 + timedelta(days=3)), {})
            self.assertEqual(len(mandate), 120)
            self.assertEqual(len(set(mandate)), 120)
            self.assertNotIn('via@esempio.it', mandate)   # disiscritto: saltato
            stati = dict(db.session.query(CodaCampagna.stato, db.func.count(CodaCampagna.id))
                         .group_by(CodaCampagna.stato).all())
            self.assertEqual(stati, {'inviata': 120, 'saltata': 1})

    def test_endpoint_programmata(self):
        r = self.client.post('/api/lead-strumenti/campagna', headers=H, json={'mode': 'programmata', 'campagna': 'manuale'})
        self.assertEqual(r.status_code, 400)   # senza conferma
        r = self.client.post('/api/lead-strumenti/campagna', headers=H,
                             json={'mode': 'programmata', 'campagna': 'manuale', 'conferma': 'INVIA'})
        self.assertEqual(r.status_code, 202)
        r = self.client.get('/api/lead-strumenti/campagna/coda?campagna=manuale', headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['per_giorno'], 50)

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        with app.app_context():
            db.create_all()
            if not EmailSequenza.query.filter_by(email='via@esempio.it').first():
                db.session.add(EmailSequenza(email='via@esempio.it', segmento='numeri', step=2, stato='disiscritta'))
                db.session.commit()


if __name__ == '__main__':
    unittest.main()
