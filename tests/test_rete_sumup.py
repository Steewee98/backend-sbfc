"""Test del collegamento con la cassa SumUp: l'API è finta, i conti no."""
import os
import sys
import tempfile
import unittest

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from services import sumup  # noqa: E402

H = {'X-Admin-Token': 'test-token'}
TRANS = {
    't1': {'id': 't1', 'timestamp': '2026-09-24T21:30:00Z', 'amount': 20.0,      # 23:30 a Roma: è il 24
           'products': [{'name': 'Spritz', 'quantity': 2, 'total_with_vat': 14.0}, {'name': 'Tagliere', 'quantity': 1, 'total_with_vat': 6.0}]},
    't2': {'id': 't2', 'timestamp': '2026-09-24T22:30:00Z', 'amount': 7.0,       # 00:30 a Roma: è già il 25
           'products': [{'name': 'Spritz', 'quantity': 1, 'price_with_vat': 7.0}]},
    't3': {'id': 't3', 'timestamp': '2026-09-25T10:00:00Z', 'amount': 3.5, 'products': []},
}


def finta(chiave, percorso, params=None):
    if chiave != 'sup_sk_buona_123':
        raise sumup.ErroreSumUp('SumUp rifiuta la chiave')
    if percorso == '/v0.1/me':
        return {'merchant_profile': {'merchant_code': 'MERA01', 'company_name': 'Mera Bistrot srl'}}
    if percorso.endswith('/history'):
        if 'oldest_ref' in (params or {}):
            return {'items': [{'id': 't3'}], 'links': []}
        return {'items': [{'id': 't1'}, {'id': 't2'}], 'links': [{'rel': 'next', 'href': 'limit=100&oldest_ref=t2'}]}
    return TRANS[params['id']]


class SumUp(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        sumup._get = finta
        cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        cls.lid = cls.c.post('/api/rete/locali', json={'nome': 'Mera Bistrot'}, headers=H).get_json()['id']
        cls.base = f'/api/rete/locali/{cls.lid}'

    def test_1_chiave_sbagliata(self):
        r = self.c.post(self.base + '/sumup', headers=H, json={'chiave': 'sup_sk_sbagliata'})
        self.assertEqual(r.status_code, 400)

    def test_2_collega_e_la_chiave_non_esce(self):
        r = self.c.post(self.base + '/sumup', headers=H, json={'chiave': 'sup_sk_buona_123'}).get_json()
        self.assertEqual(r['nome'], 'Mera Bistrot srl')
        l = self.c.get(self.base, headers=H).get_json()
        self.assertEqual(l['impostazioni']['sumup']['esercente'], 'MERA01')
        self.assertNotIn('chiave', l['impostazioni']['sumup'])
        with app.app_context():
            from models import LocaleRete
            salvata = db.session.get(LocaleRete, self.lid).impostazioni['sumup']['chiave']
        self.assertNotIn('buona', salvata)                       # cifrata
        self.assertEqual(sumup.decifra(salvata), 'sup_sk_buona_123')

    def test_3_scarica_giorni_di_roma_e_pagine(self):
        r = self.c.post(self.base + '/sumup/scarica', headers=H, json={'dal': '2026-09-24', 'al': '2026-09-25'}).get_json()
        self.assertEqual(r['transazioni'], 3)                    # due pagine lette
        voci = {(v['voce']): v for v in self.c.get(self.base + '/voci', headers=H).get_json()}
        self.assertEqual(voci['APEROL SPRITZ']['quantita'], 3)
        self.assertEqual(voci['APEROL SPRITZ']['incasso'], 21.0)
        self.assertIn('IMPORTO LIBERO SENZA PRODOTTO', voci)
        giorni = {g['giorno']: g for g in self.c.get(self.base + '/vendite', headers=H).get_json()}
        self.assertEqual(giorni['2026-09-24']['incasso'], 20.0)  # la transazione di mezzanotte e mezza va al 25
        self.assertEqual(giorni['2026-09-25']['incasso'], 10.5)

    def test_4_riscaricare_non_raddoppia(self):
        self.c.post(self.base + '/sumup/scarica', headers=H, json={'dal': '2026-09-24', 'al': '2026-09-25'})
        voci = {(v['voce']): v for v in self.c.get(self.base + '/voci', headers=H).get_json()}
        self.assertEqual(voci['APEROL SPRITZ']['quantita'], 3)

    def test_5_troppi_giorni(self):
        r = self.c.post(self.base + '/sumup/scarica', headers=H, json={'dal': '2026-01-01', 'al': '2026-09-25'})
        self.assertEqual(r.status_code, 400)


if __name__ == '__main__':
    unittest.main()
