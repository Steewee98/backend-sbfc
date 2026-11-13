"""Agente vendite: i tre indirizzi del motore e la pagina del titolare.

    SBFC_NO_BG=1 venv/bin/python -m unittest tests.test_agente -v
"""
import os
import sys
import tempfile
import unittest

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='admin-tok',
                  SBFOOD_AGENTE_TOKEN='agente-tok', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from routes.agente import AgenteChat, AgenteInArrivo, AgenteStato  # noqa: E402

AG = {'Authorization': 'Bearer agente-tok'}
AD = {'X-Admin-Token': 'admin-tok'}


class TestAgente(unittest.TestCase):
    def setUp(self):
        # gli altri file di prova cambiano ADMIN_TOKEN quando vengono importati: qui si rimettono i nostri
        os.environ.update(ADMIN_TOKEN='admin-tok', SBFOOD_AGENTE_TOKEN='agente-tok')
        self.c = app.test_client()
        with app.app_context():
            db.create_all()
            for m in (AgenteChat, AgenteInArrivo, AgenteStato):
                m.query.delete()
            db.session.commit()

    # ── permessi: ogni token apre solo la sua parte ──
    def test_senza_token_o_col_token_sbagliato_401(self):
        for metodo, url in (('get', '/api/agente/in-arrivo'), ('post', '/api/agente/stato'),
                            ('post', '/api/agente/letti')):
            for h in ({}, {'Authorization': 'Bearer no'}, {'Authorization': 'agente-tok'}, AD):
                self.assertEqual(getattr(self.c, metodo)(url, json={}, headers=h).status_code, 401, (url, h))

    def test_il_token_agente_non_apre_il_gestionale(self):
        self.assertEqual(self.c.get('/api/admin/agente', headers=AG).status_code, 401)
        self.assertEqual(self.c.post('/api/admin/agente/azione', json={'tipo': 'pausa'}, headers=AG).status_code, 401)

    def test_senza_variabile_sul_server_nessuno_entra(self):
        vecchio = os.environ.pop('SBFOOD_AGENTE_TOKEN')
        try:
            self.assertEqual(self.c.get('/api/agente/in-arrivo', headers={'Authorization': 'Bearer '}).status_code, 401)
        finally:
            os.environ['SBFOOD_AGENTE_TOKEN'] = vecchio

    # ── giro completo ──
    def test_giro_completo(self):
        r = self.c.post('/api/admin/agente/azione', json={'tipo': 'messaggio', 'testo': '  Come va?  '}, headers=AD)
        self.assertEqual(r.status_code, 200)
        self.c.post('/api/admin/agente/azione', json={'tipo': 'spesa', 'spesa_id': '3', 'scelta': 'ok'}, headers=AD)
        self.c.post('/api/admin/agente/azione', json={'tipo': 'pausa'}, headers=AD)

        voci = self.c.get('/api/agente/in-arrivo', headers=AG).get_json()['in_arrivo']
        self.assertEqual([v['tipo'] for v in voci], ['messaggio', 'spesa', 'pausa'])
        self.assertEqual(voci[0]['testo'], 'Come va?')
        self.assertEqual((voci[1]['spesa_id'], voci[1]['scelta']), (3, 'ok'))
        self.assertTrue(all(v['id'] and v['at'] for v in voci))

        stato = {'modalita': 'prova', 'numeri': {'vendite_totali': 0}, 'imbuto': [['contattati', 4]]}
        r = self.c.post('/api/agente/stato', json={'stato': stato, 'messaggi': ['Tutto bene.', '', 5]}, headers=AG)
        self.assertEqual(r.status_code, 200)
        r = self.c.post('/api/agente/letti', json={'ids': [voci[0]['id'], voci[1]['id']]}, headers=AG)
        self.assertEqual(r.get_json()['segnati'], 2)

        self.assertEqual([v['tipo'] for v in self.c.get('/api/agente/in-arrivo', headers=AG).get_json()['in_arrivo']],
                         ['pausa'])
        vista = self.c.get('/api/admin/agente', headers=AD).get_json()
        self.assertEqual(vista['stato'], stato)
        self.assertEqual([(m['autore'], m['testo']) for m in vista['chat']],
                         [('titolare', 'Come va?'), ('agente', 'Tutto bene.')])
        self.assertEqual([a['tipo'] for a in vista['in_attesa']], ['pausa'])

    def test_letti_due_volte_non_cambia_niente(self):
        self.c.post('/api/admin/agente/azione', json={'tipo': 'riprendi'}, headers=AD)
        i = self.c.get('/api/agente/in-arrivo', headers=AG).get_json()['in_arrivo'][0]['id']
        self.assertEqual(self.c.post('/api/agente/letti', json={'ids': [i]}, headers=AG).get_json()['segnati'], 1)
        self.assertEqual(self.c.post('/api/agente/letti', json={'ids': [i, 'inesistente']}, headers=AG).get_json()['segnati'], 0)

    # ── input sbagliati ──
    def test_azioni_non_valide_rifiutate(self):
        for corpo in ({}, {'tipo': 'vendita'}, {'tipo': 'vendita', 'email': 'no', 'prodotto': 'corso'},
                      {'tipo': 'vendita', 'email': 'a@b.it', 'prodotto': 'placca'}, {'tipo': 'basi'}, {'tipo': 'messaggio', 'testo': '   '},
                      {'tipo': 'spesa', 'spesa_id': 'x', 'scelta': 'ok'}, {'tipo': 'spesa', 'spesa_id': 1, 'scelta': 'forse'}):
            self.assertEqual(self.c.post('/api/admin/agente/azione', json=corpo, headers=AD).status_code, 400, corpo)
        self.assertEqual(self.c.get('/api/agente/in-arrivo', headers=AG).get_json()['in_arrivo'], [])

    def test_stato_non_valido_rifiutato(self):
        for corpo in ([1], {'stato': 'testo'}, {'messaggi': 'uno'}):
            self.assertEqual(self.c.post('/api/agente/stato', json=corpo, headers=AG).status_code, 400, corpo)
        enorme = {'stato': {'x': 'a' * 300_000}}
        self.assertEqual(self.c.post('/api/agente/stato', json=enorme, headers=AG).status_code, 413)
        self.assertEqual(self.c.post('/api/agente/letti', json={'ids': 'abc'}, headers=AG).status_code, 400)

    def test_vendita(self):
        r = self.c.post('/api/admin/agente/azione', json={'tipo': 'vendita', 'email': ' Mario@Trattoria.IT ', 'prodotto': 'smart-table'}, headers=AD)
        self.assertEqual(r.status_code, 200)
        v = self.c.get('/api/agente/in-arrivo', headers=AG).get_json()['in_arrivo'][0]
        self.assertEqual((v['tipo'], v['email'], v['prodotto']), ('vendita', 'mario@trattoria.it', 'smart-table'))

    def test_messaggio_lungo_tagliato(self):
        self.c.post('/api/admin/agente/azione', json={'tipo': 'messaggio', 'testo': 'x' * 9000}, headers=AD)
        v = self.c.get('/api/agente/in-arrivo', headers=AG).get_json()['in_arrivo'][0]
        self.assertEqual(len(v['testo']), 4000)


if __name__ == '__main__':
    unittest.main()
