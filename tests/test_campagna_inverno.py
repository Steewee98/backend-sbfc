"""Campagna inverno 2026-27: testi integri, destinatari giusti, partenza solo nel
giorno previsto e una volta sola, salto di chi ha già comprato o si è disiscritto.

    SBFC_NO_BG=1 venv/bin/python -m unittest tests.test_campagna_inverno -v
"""
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, LeadStrumento, Pagamento, EmailSequenza, CodaCampagna, OrdineNfc  # noqa: E402
from services import campagna_inverno as ci  # noqa: E402
from routes import lead_strumenti as ls  # noqa: E402


def utc(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M')


class TestTesti(unittest.TestCase):
    def test_dodici_email_complete(self):
        self.assertEqual([e['n'] for e in ci.EMAILS], list(range(1, 13)))
        date = [e['data'] for e in ci.EMAILS]
        self.assertEqual(date, sorted(date))
        for e in ci.EMAILS:
            with self.subTest(n=e['n']):
                self.assertTrue(e['oggetto'] and e['titolo'] and e['pulsante'] and e['paragrafi'])
                self.assertEqual(len(e['punti']), 3)
                self.assertIn('utm_campaign=inverno-%02d' % e['n'], e['link'])
                self.assertTrue(e['link'].startswith('https://www.sbfoodconsulting.com/'))
                testo = ' '.join(e['paragrafi'] + e['punti'] + [e['titolo'], e['riquadro'], e['oggetto']])
                self.assertNotIn('—', testo)                      # niente trattino lungo
                self.assertIsNone(re.search(r"\b(tu|ti|tuo|tua)\b", testo.lower()), testo)
                self.assertLessEqual(len(' '.join(e['paragrafi']).split()), 95)

    def test_html_senza_segnaposto_e_con_disiscrizione(self):
        for e in ci.EMAILS:
            h = ci.componi_html(e, 'https://x/unsub?e=a')
            self.assertIn('https://x/unsub?e=a', h)
            self.assertIn(e['immagine'], h)
            self.assertNotIn('{', h.split('<body', 1)[1])
            self.assertIn('Gentile collega,', ci.componi_testo(e, 'u'))

    def test_san_valentino_domenica(self):
        self.assertEqual(datetime(2027, 2, 14).strftime('%A'), 'Sunday')
        self.assertIn('domenica 14 febbraio', ci.PER_NUMERO[11]['paragrafi'][0])


class TestInvio(unittest.TestCase):
    def setUp(self):
        with app.app_context():
            db.drop_all(); db.create_all()
            for m in ['a@x.it', 'b@x.it', 'via@x.it', 'seq@x.it', 'man@x.it', 'plac@x.it', 'mod3@x.it']:
                db.session.add(LeadStrumento(email=m, strumento='scheda-food-cost', consenso_marketing=True))
            db.session.add(LeadStrumento(email='nocons@x.it', strumento='quiz-numeri', consenso_marketing=False))
            db.session.add(EmailSequenza(email='via@x.it', segmento='numeri', step=3, stato='disiscritta'))
            db.session.add(EmailSequenza(email='seq@x.it', segmento='numeri', step=2, stato='attiva'))
            db.session.add(EmailSequenza(email='a@x.it', segmento='numeri', step=7, stato='completata'))
            db.session.add(Pagamento(nome='M', email='Man@x.it', prodotto='manager-ristorazione', importo=12))
            db.session.add(Pagamento(nome='M3', email='mod3@x.it', prodotto='modulo-3', importo=19.9))
            db.session.add(OrdineNfc(**self._ordine('plac@x.it')))
            db.session.commit()

    def _ordine(self, email):
        cols = {c.name for c in OrdineNfc.__table__.columns}
        base = {'email': email, 'stato': 'pagato', 'tier': 'base'}
        for c in OrdineNfc.__table__.columns:
            if c.name not in base and not c.nullable and c.default is None and not c.primary_key:
                base[c.name] = 'x'
        return {k: v for k, v in base.items() if k in cols}

    def test_destinatari(self):
        with app.app_context():
            self.assertEqual(sorted(ci.destinatari(ci.PER_NUMERO[1])), ['a@x.it', 'b@x.it', 'man@x.it', 'mod3@x.it'])
            self.assertNotIn('man@x.it', ci.destinatari(ci.PER_NUMERO[3]))
            self.assertNotIn('mod3@x.it', ci.destinatari(ci.PER_NUMERO[8]))
            self.assertIn('mod3@x.it', ci.destinatari(ci.PER_NUMERO[10]))

    def test_parte_solo_il_giorno_giusto_e_una_volta(self):
        inviati = []
        with app.app_context(), mock.patch.object(ci, 'invia_inverno_a', side_effect=lambda m, n, **k: inviati.append((n, m)) or 'id'), \
                mock.patch.object(ls.time, 'sleep'):
            self.assertEqual(ls.processa_coda(adesso=utc('2026-11-02 09:00')), {})
            r = ls.processa_coda(adesso=utc('2026-11-03 08:00'))
            self.assertEqual(r, {'inverno-01': 4})
            # il giorno dopo non riaccoda e non rimanda
            self.assertEqual(ls.processa_coda(adesso=utc('2026-11-04 08:00')), {})
            self.assertEqual(CodaCampagna.query.filter_by(campagna='inverno-01').count(), 4)
            # fuori dalla finestra (servizio fermo) l'email non parte più
            self.assertEqual(ls.processa_coda(adesso=utc('2026-11-20 08:00')), {})
            self.assertFalse(CodaCampagna.query.filter_by(campagna='inverno-02').count())
        self.assertEqual({n for n, _ in inviati}, {1})

    def test_tetto_giornaliero_e_disiscritto_dopo(self):
        with app.app_context(), mock.patch.object(ci, 'invia_inverno_a', return_value='id'), mock.patch.object(ls.time, 'sleep'):
            self.assertEqual(ls.processa_coda(per_giorno=2, adesso=utc('2026-11-03 08:00')), {'inverno-01': 2})
            seq = EmailSequenza(email='mod3@x.it', segmento='numeri', step=7, stato='disiscritta')
            db.session.add(seq); db.session.commit()
            ls.processa_coda(per_giorno=2, adesso=utc('2026-11-04 08:00'))
            stati = {r.email: r.stato for r in CodaCampagna.query.filter_by(campagna='inverno-01')}
            self.assertEqual(stati['mod3@x.it'], 'saltata')

    def test_prova_dal_gestionale(self):
        c = app.test_client()
        with mock.patch.object(ci, 'invia_inverno_a', return_value='id') as f:
            r = c.post('/api/lead-strumenti/campagna', headers={'X-Admin-Token': 'test-token'},
                       json={'mode': 'test', 'campagna': 'inverno-05', 'to': 'prova@x.it'})
        self.assertEqual(r.status_code, 200)
        f.assert_called_once_with('prova@x.it', 5, oggetto_prefisso='[Prova] ')
        r = c.get('/api/lead-strumenti/campagna/inverno', headers={'X-Admin-Token': 'test-token'})
        self.assertEqual(len(r.json['email']), 12)


if __name__ == '__main__':
    unittest.main()
