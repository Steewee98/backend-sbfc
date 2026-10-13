"""Progetti di Simone: la nota si salva sempre, la proposta del modello si ricontrolla
(numeri inesistenti ignorati, doppioni scartati, stato fuori elenco ignorato), le cose
da fare si spuntano, una nota sbagliata si toglie con le sue voci.

    SBFC_NO_BG=1 venv/bin/python -m unittest tests.test_progetti -v
"""
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1',
                  ANTHROPIC_API_KEY='finta')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from services import progetti_ai  # noqa: E402

H = {'X-Admin-Token': 'test-token'}


def risposta(**k):
    base = {'fatti': [], 'da_fare': [], 'completate': [], 'urgenti': [], 'punto': '', 'stato': None}
    base.update(k)
    return base


class TestProgetti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = app.test_client()
        with app.app_context():
            db.create_all()

    def nuovo(self, nome='Bistrot di prova'):
        r = self.c.post('/api/progetti', json={'nome': nome}, headers=H)
        self.assertEqual(r.status_code, 201)
        return r.get_json()['id']

    def nota(self, pid, testo, out):
        with mock.patch.object(progetti_ai, 'chiama', return_value=out) as m:
            r = self.c.post(f'/api/progetti/{pid}/note', json={'testo': testo}, headers=H)
        self.assertEqual(r.status_code, 201)
        return r.get_json(), m

    def test_serve_la_chiave(self):
        self.assertEqual(self.c.get('/api/progetti').status_code, 401)
        self.assertEqual(self.c.get('/api/progetti', headers={'X-Admin-Token': 'no'}).status_code, 401)

    def test_nota_diventa_voci(self):
        pid = self.nuovo()
        j, m = self.nota(pid, 'Ho mandato il preventivo, entro venerdì devo chiamare il fornitore del forno',
                         risposta(fatti=['Mandato il preventivo'],
                                  da_fare=[{'testo': 'Chiamare il fornitore del forno', 'urgente': True,
                                            'scadenza': '2026-10-16'}],
                                  punto='Preventivo mandato, si aspetta il forno.', stato='in_lavorazione'))
        p = j['progetto']
        self.assertIsNone(j['avviso'])
        self.assertEqual(p['stato'], 'in_lavorazione')
        self.assertEqual(p['punto'], 'Preventivo mandato, si aspetta il forno.')
        self.assertEqual([v['testo'] for v in p['fatte']], ['Mandato il preventivo'])
        self.assertEqual(p['aperte'][0]['scadenza'], '2026-10-16')
        self.assertEqual(p['urgenti'], 1)
        self.assertIsNotNone(p['aggiornato_il'])
        # al modello arrivano nota e progetto
        self.assertIn('Bistrot di prova', m.call_args[0][0])
        self.assertIn('fornitore del forno', m.call_args[0][0])

    def test_completate_e_controlli(self):
        pid = self.nuovo('Locale B')
        j, _ = self.nota(pid, 'devo fare il menù e le foto',
                         risposta(da_fare=[{'testo': 'Fare il menù', 'urgente': False, 'scadenza': None},
                                           {'testo': 'Fare le foto', 'urgente': False, 'scadenza': 'boh'}],
                                  punto='Si parte.'))
        aperte = {v['testo']: v['id'] for v in j['progetto']['aperte']}
        self.assertIsNone(j['progetto']['aperte'][1]['scadenza'])   # data non valida scartata
        j, m = self.nota(pid, 'menù fatto, le foto sono urgenti',
                         risposta(fatti=['Fatto il menù'], completate=[aperte['Fare il menù'], 99999],
                                  urgenti=[aperte['Fare le foto']],
                                  da_fare=[{'testo': 'fare le foto', 'urgente': True, 'scadenza': None}],
                                  punto='', stato='inventato'))
        p = j['progetto']
        self.assertIn(f"{aperte['Fare il menù']}. Fare il menù", m.call_args[0][0])
        self.assertEqual([v['testo'] for v in p['aperte']], ['Fare le foto'])    # doppione non aggiunto
        self.assertTrue(p['aperte'][0]['urgente'])
        self.assertEqual(p['stato'], 'aperto')         # stato fuori elenco ignorato
        self.assertEqual(p['punto'], 'Si parte.')       # punto vuoto: resta quello di prima
        self.assertIn('Fare il menù', [v['testo'] for v in p['fatte']])

    def test_nota_salvata_se_ai_non_risponde(self):
        pid = self.nuovo('Locale C')
        with mock.patch.object(progetti_ai, 'chiama', side_effect=RuntimeError('rete giù')):
            r = self.c.post(f'/api/progetti/{pid}/note', json={'testo': 'chiamato il cliente'}, headers=H)
        j = r.get_json()
        self.assertEqual(r.status_code, 201)
        self.assertIn('Nota salvata', j['avviso'])
        self.assertEqual(j['progetto']['da_elaborare'], 1)
        nid = j['progetto']['note'][0]['id']
        with mock.patch.object(progetti_ai, 'chiama', return_value=risposta(fatti=['Chiamato il cliente'], punto='ok')):
            r = self.c.post(f'/api/progetti/note/{nid}/rielabora', headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['progetto']['da_elaborare'], 0)
        self.assertEqual(r.get_json()['progetto']['fatte'][0]['testo'], 'Chiamato il cliente')

    def test_spunta_e_voci_a_mano(self):
        pid = self.nuovo('Locale D')
        p = self.c.post(f'/api/progetti/{pid}/voci', json={'testo': 'Mandare il listino', 'urgente': True},
                        headers=H).get_json()
        vid = p['aperte'][0]['id']
        p = self.c.patch(f'/api/progetti/voci/{vid}', json={'fatta': True}, headers=H).get_json()
        self.assertEqual(p['aperte'], [])
        self.assertEqual(p['fatte'][0]['testo'], 'Mandare il listino')
        p = self.c.patch(f'/api/progetti/voci/{vid}', json={'fatta': False}, headers=H).get_json()
        self.assertEqual(len(p['aperte']), 1)

    def test_elimina_nota_toglie_le_sue_voci(self):
        pid = self.nuovo('Locale E')
        j, _ = self.nota(pid, 'nota sbagliata', risposta(fatti=['Cosa sbagliata'], punto='x'))
        nid = j['progetto']['note'][0]['id']
        p = self.c.delete(f'/api/progetti/note/{nid}', headers=H).get_json()
        self.assertEqual(p['fatte'], [])
        self.assertEqual(p['note'], [])

    def test_nota_vuota(self):
        pid = self.nuovo('Vuoto')
        self.assertEqual(self.c.post(f'/api/progetti/{pid}/note', json={'testo': ' '}, headers=H).status_code, 400)

    def test_elenco_e_stato(self):
        pid = self.nuovo('Locale F')
        self.assertEqual(self.c.patch(f'/api/progetti/{pid}', json={'stato': 'boh'}, headers=H).status_code, 400)
        self.c.patch(f'/api/progetti/{pid}', json={'stato': 'in_attesa'}, headers=H)
        el = self.c.get('/api/progetti', headers=H).get_json()
        self.assertIn('Locale F', [p['nome'] for p in el])

    def test_importa_senza_doppioni(self):
        dati = {'progetti': [{'nome': 'Locale G', 'stato': 'in_lavorazione', 'punto': 'A buon punto.',
                              'voci': [{'tipo': 'fatto', 'testo': 'Consegnato il logo', 'data': '2026-10-05'},
                                       {'tipo': 'da_fare', 'testo': 'Stampare', 'urgente': True}]}]}
        r = self.c.post('/api/progetti/importa', json=dati, headers=H).get_json()
        self.assertEqual(r, {'creati': 1, 'voci': 2})
        r = self.c.post('/api/progetti/importa', json=dati, headers=H).get_json()
        self.assertEqual(r, {'creati': 0, 'voci': 0})
        pid = [p['id'] for p in self.c.get('/api/progetti', headers=H).get_json() if p['nome'] == 'Locale G'][0]
        p = self.c.get(f'/api/progetti/{pid}', headers=H).get_json()
        self.assertEqual(p['fatte'][0]['creata_il'][:10], '2026-10-05')
        self.assertEqual(p['urgenti'], 1)
        self.assertEqual(p['stato'], 'in_lavorazione')

    def test_messaggio_al_modello(self):
        s = progetti_ai.componi('X', 'aperto', None, [(3, 'Chiamare', True, date(2026, 10, 16))], 'nota', date(2026, 10, 13))
        self.assertIn('martedì', s)
        self.assertIn('3. Chiamare [urgente] [entro 2026-10-16]', s)


if __name__ == '__main__':
    unittest.main()
