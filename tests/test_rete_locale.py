"""Test della fase 2 della Rete SB: persone, timbrature, chiusura, titolare, quadro, avvisi."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, TurnoRete, VenditaRete  # noqa: E402
from routes import rete_locale  # noqa: E402
from services.quadro import quadro, giorno_di_lavoro  # noqa: E402

H = {'X-Admin-Token': 'test-token'}


class Locale(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        cls.lid = c.post('/api/rete/locali', json={'nome': 'Mera Bistrot'}, headers=H).get_json()['id']
        cls.base = f'/api/rete/locali/{cls.lid}'
        cls.giulia = c.post(cls.base + '/persone', headers=H, json={'nome': 'Giulia', 'pin': '1234', 'costo_orario': 12}).get_json()
        cls.marco = c.post(cls.base + '/persone', headers=H, json={'nome': 'Marco', 'pin': '5678', 'costo_orario': 10}).get_json()
        cls.tit = c.post(cls.base + '/persone', headers=H, json={'nome': 'Paola', 'ruolo': 'titolare',
                                                                 'email': 'Paola@Mera.it', 'password': 'segreta123'}).get_json()
        cls.cod = c.get(cls.base + '/app', headers=H).get_json()['codice']

    def setUp(self):
        rete_locale._errori.clear()

    def test_1_validazioni(self):
        for corpo, msg in (({'nome': ''}, 'nome'), ({'nome': 'X', 'pin': '12'}, 'PIN'),
                           ({'nome': 'X', 'ruolo': 'capo'}, 'Ruolo'), ({'nome': 'X', 'email': 'paola@mera.it'}, 'già usata')):
            r = self.c.post(self.base + '/persone', headers=H, json=corpo)
            self.assertEqual(r.status_code, 400)
            self.assertIn(msg, r.get_json()['error'])

    def test_2_il_tag_mostra_solo_i_nomi(self):
        r = self.c.get(f'/api/app/{self.cod}').get_json()
        self.assertEqual(r['locale'], 'Mera Bistrot')
        self.assertEqual([p['nome'] for p in r['persone']], ['Giulia', 'Marco'])     # la titolare non timbra: niente PIN
        self.assertEqual(set(r['persone'][0]), {'id', 'nome', 'in_servizio'})
        self.assertEqual(self.c.get('/api/app/sbagliato').status_code, 404)

    def test_3_timbra_inizio_e_fine(self):
        r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.giulia['id'], 'pin': '1234'}).get_json()
        self.assertEqual(r['azione'], 'inizio')
        self.assertTrue([p for p in self.c.get(f'/api/app/{self.cod}').get_json()['persone'] if p['nome'] == 'Giulia'][0]['in_servizio'])
        # il doppio tocco non chiude il turno appena aperto
        r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.giulia['id'], 'pin': '1234'}).get_json()
        self.assertEqual((r['azione'], r.get('ripetuta')), ('inizio', True))
        with app.app_context():
            t = TurnoRete.query.filter_by(persona_id=self.giulia['id'], fine=None).first()
            t.inizio -= timedelta(hours=5); db.session.commit()
        r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.giulia['id'], 'pin': '1234'}).get_json()
        self.assertEqual(r['azione'], 'fine')
        r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.giulia['id'], 'pin': '1234'}).get_json()
        self.assertEqual((r['azione'], r.get('ripetuta')), ('fine', True))     # e nemmeno lo riapre

    def test_4_pin_sbagliato_e_freno(self):
        for _ in range(10):
            r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.marco['id'], 'pin': '0000'})
            self.assertEqual(r.status_code, 401)
        r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.marco['id'], 'pin': '5678'})
        self.assertEqual(r.status_code, 429)                      # anche quello giusto aspetta

    def test_5_pin_di_un_altro_locale(self):
        altro = self.c.post('/api/rete/locali', json={'nome': 'Altro'}, headers=H).get_json()['id']
        cod2 = self.c.get(f'/api/rete/locali/{altro}/app', headers=H).get_json()['codice']
        r = self.c.post(f'/api/app/{cod2}/timbra', json={'persona_id': self.giulia['id'], 'pin': '1234'})
        self.assertEqual(r.status_code, 401)

    def test_6_turno_dimenticato_non_si_chiude_il_giorno_dopo(self):
        with app.app_context():
            db.session.add(TurnoRete(locale_id=self.lid, persona_id=self.marco['id'], inizio=datetime.utcnow() - timedelta(hours=20)))
            db.session.commit()
        r = self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.marco['id'], 'pin': '5678'}).get_json()
        self.assertEqual(r['azione'], 'inizio')                   # il vecchio resta aperto, da sistemare
        t = self.c.get(self.base + '/turni', headers=H).get_json()['turni']
        self.assertTrue(any(x['dimenticato'] for x in t))
        self.c.post(f'/api/app/{self.cod}/timbra', json={'persona_id': self.marco['id'], 'pin': '5678'})

    def test_7_chiusura(self):
        r = self.c.post(f'/api/app/{self.cod}/chiusura', json={'persona_id': self.marco['id'], 'pin': '5678',
                                                              'voci': {'celle': True, 'gas': True, 'luci': True, 'cassa': False, 'porte': True, 'nota': 'cassa da contare'}}).get_json()
        self.assertEqual(r['mancano'], ['cassa'])
        self.assertTrue(self.c.get(f'/api/app/{self.cod}').get_json()['chiuso_oggi'])

    def test_8_titolare_e_quadro(self):
        self.assertEqual(self.c.post('/api/app/login', json={'email': 'paola@mera.it', 'password': 'no'}).status_code, 401)
        self.assertEqual(self.c.post('/api/app/login', json={'email': 'x', 'password': 'y'}).status_code, 401)
        tok = self.c.post('/api/app/login', json={'email': ' PAOLA@mera.it', 'password': 'segreta123'}).get_json()['token']
        q = self.c.get('/api/app/quadro', headers={'Authorization': 'Bearer ' + tok}).get_json()
        self.assertEqual((q['locale'], q['chi']), ('Mera Bistrot', 'Paola'))
        self.assertEqual(self.c.get('/api/app/quadro', headers={'Authorization': 'Bearer falso'}).status_code, 401)

    def test_9_costo_del_personale(self):
        """7 giorni: 1.100 € di incasso IVA compresa (1.000 senza), 30 ore a 12 € = 360 € → 36%."""
        oggi = giorno_di_lavoro()
        with app.app_context():
            for i in range(1, 8):
                db.session.add(VenditaRete(locale_id=self.lid, giorno=oggi - timedelta(days=i), voce='X', quantita=1, incasso=1100 / 7))
            g = oggi - timedelta(days=3)
            ini = datetime(g.year, g.month, g.day, 8)       # 10 di Roma d'estate, 9 d'inverno: sempre quel giorno
            for k in range(3):
                db.session.add(TurnoRete(locale_id=self.lid, persona_id=self.giulia['id'], inizio=ini + timedelta(minutes=k),
                                         fine=ini + timedelta(hours=10, minutes=k)))
            db.session.commit()
            from models import LocaleRete
            q = quadro(db.session.get(LocaleRete, self.lid), oggi)
        self.assertAlmostEqual(q['incasso']['euro'], 1100, places=1)
        self.assertEqual(q['personale']['ore'], 30.0)
        self.assertEqual(q['personale']['percento'], 36.0)

    def test_z_avvisi(self):
        r = self.c.get('/api/rete/avvisi', headers=H).get_json()
        mera = [x for x in r if x['locale'] == 'Mera Bistrot'][0]
        self.assertIn('paola@mera.it', mera['a'])
        self.assertTrue(any('manca la fine' in m for m in mera['messaggi']))   # il turno dimenticato


if __name__ == '__main__':
    unittest.main()


class Andamento(unittest.TestCase):

    def test_serie_per_i_grafici(self):
        c = app.test_client()
        lid = c.post('/api/rete/locali', json={'nome': 'Grafici'}, headers=H).get_json()['id']
        oggi = giorno_di_lavoro()
        with app.app_context():
            for i in range(1, 15):
                db.session.add(VenditaRete(locale_id=lid, giorno=oggi - timedelta(days=i), voce='MARGHERITA', quantita=10, incasso=100 + i))
            db.session.commit()
        a = c.get(f'/api/rete/locali/{lid}/andamento', headers=H).get_json()
        self.assertEqual(len(a['settimane']), 8)
        self.assertEqual(a['settimane'][-1]['al'], (oggi - timedelta(days=1)).isoformat())   # l'ultima finisce ieri
        self.assertAlmostEqual(a['settimane'][-1]['incasso'], sum(100 + i for i in range(1, 8)))
        self.assertEqual(len(a['giorni_settimana']), 7)
        self.assertEqual(a['piatti'][0], {'nome': 'MARGHERITA', 'quantita': 70, 'incasso': round(sum(100 + i for i in range(1, 8)), 2)})
