"""Test degli accessi personali dei consulenti alla console della rete."""
import os
import sys
import tempfile
import unittest

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from routes import admin_auth  # noqa: E402

H = {'X-Admin-Token': 'test-token'}


class Consulenti(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        cls.anna = cls.c.post('/api/rete/consulenti', headers=H, json={'nome': 'Anna', 'email': 'anna@sb.it', 'password': 'lunga-abbastanza'}).get_json()

    def setUp(self):
        admin_auth._errori.clear()

    def entra(self, pw='lunga-abbastanza'):
        return self.c.post('/api/rete/login', json={'email': 'ANNA@sb.it ', 'password': pw})

    def test_1_login_e_lavoro_sulla_rete(self):
        tok = self.entra().get_json()['token']
        r = self.c.post('/api/rete/locali', headers={'X-Admin-Token': tok}, json={'nome': 'Mera Bistrot'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.get('/api/rete/riepilogo', headers={'X-Admin-Token': tok}).status_code, 200)

    def test_2_il_consulente_non_gestisce_gli_accessi_ne_il_gestionale(self):
        tok = self.entra().get_json()['token']
        self.assertEqual(self.c.get('/api/rete/consulenti', headers={'X-Admin-Token': tok}).status_code, 403)
        self.assertEqual(self.c.post('/api/rete/consulenti', headers={'X-Admin-Token': tok},
                                     json={'nome': 'X', 'email': 'x@x.it', 'password': '1234567890'}).status_code, 403)
        # le API del gestionale vogliono sempre la chiave admin
        self.assertIn(self.c.get('/api/nfc/richieste', headers={'X-Admin-Token': tok}).status_code, (401, 403))

    def test_3_password_sbagliata_e_validazioni(self):
        self.assertEqual(self.entra('no').status_code, 401)
        r = self.c.post('/api/rete/consulenti', headers=H, json={'nome': 'B', 'email': 'anna@sb.it', 'password': 'lunga-abbastanza'})
        self.assertEqual(r.status_code, 400)
        r = self.c.post('/api/rete/consulenti', headers=H, json={'nome': 'B', 'email': 'b@sb.it', 'password': 'corta'})
        self.assertEqual(r.status_code, 400)

    def test_4_cambio_password_e_disattivazione_tolgono_l_accesso(self):
        tok = self.entra().get_json()['token']
        self.c.patch(f"/api/rete/consulenti/{self.anna['id']}", headers=H, json={'password': 'nuova-password-1'})
        self.assertEqual(self.c.get('/api/rete/locali', headers={'X-Admin-Token': tok}).status_code, 401)
        tok = self.entra('nuova-password-1').get_json()['token']
        self.c.patch(f"/api/rete/consulenti/{self.anna['id']}", headers=H, json={'attivo': False})
        self.assertEqual(self.c.get('/api/rete/locali', headers={'X-Admin-Token': tok}).status_code, 401)
        self.assertEqual(self.entra('nuova-password-1').status_code, 401)


if __name__ == '__main__':
    unittest.main()


class Direzione(unittest.TestCase):
    """Simone guarda tutto ma non modifica: il blocco è nel server."""

    def test_sola_lettura(self):
        c = app.test_client()
        admin_auth._errori.clear()
        c.post('/api/rete/consulenti', headers=H, json={'nome': 'Simone', 'email': 'simone@sb.it', 'password': 'direzione-123', 'ruolo': 'direzione'})
        r = c.post('/api/rete/login', json={'email': 'simone@sb.it', 'password': 'direzione-123'}).get_json()
        self.assertEqual(r['ruolo'], 'direzione')
        T = {'X-Admin-Token': r['token']}
        self.assertEqual(c.get('/api/rete/riepilogo', headers=T).status_code, 200)
        lid = c.post('/api/rete/locali', headers=H, json={'nome': 'Per Simone'}).get_json()['id']
        self.assertEqual(c.get(f'/api/rete/locali/{lid}/andamento', headers=T).status_code, 200)
        for m, p, j in (('post', '/api/rete/locali', {'nome': 'X'}), ('patch', f'/api/rete/locali/{lid}', {'nome': 'Y'}),
                        ('delete', f'/api/rete/locali/{lid}', None), ('post', f'/api/rete/locali/{lid}/ricette', {'nome': 'Z'})):
            self.assertEqual(getattr(c, m)(p, headers=T, json=j).status_code, 403, p)
        self.assertEqual(c.post('/api/rete/consulenti', headers=H, json={'nome': 'X', 'email': 'x@sb.it', 'password': '1234567890', 'ruolo': 'capo'}).status_code, 400)
