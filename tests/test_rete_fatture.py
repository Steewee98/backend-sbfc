"""Test del passo 2 della Rete SB: fatture di acquisto e articoli.

    SBFC_NO_BG=1 venv/bin/python -m unittest discover -s tests -v

Database SQLite temporaneo, nessun servizio esterno.
"""
import base64
import io
import os
import sys
import tempfile
import unittest
import zipfile

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from services.fatturapa import leggi_file, leggi_xml, normalizza, suggerisci_fattore, FatturaNonLeggibile  # noqa: E402

H = {'X-Admin-Token': 'test-token'}


def fattura_xml(numero='FT-101', data='2026-09-10', tipo='TD01', righe=None):
    righe = righe or [
        ('1', 'FIORDILATTE JULIENNE 3KG LOTTO 7781 SCAD 30/09/26', 'PZ', '4.00', '36.00'),
        ('2', 'FARINA 00 W300', 'KG', '25.00', '20.00'),
        ('3', 'SPESE DI TRASPORTO', None, None, '8.00'),
    ]
    linee = ''.join(
        f'<DettaglioLinee><NumeroLinea>{n}</NumeroLinea><Descrizione>{d}</Descrizione>'
        + (f'<Quantita>{q}</Quantita><UnitaMisura>{u}</UnitaMisura>' if q else '')
        + f'<PrezzoUnitario>1.00</PrezzoUnitario><PrezzoTotale>{t}</PrezzoTotale><AliquotaIVA>4.00</AliquotaIVA></DettaglioLinee>'
        for n, d, u, q, t in righe)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
 <FatturaElettronicaHeader>
  <CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>01234567890</IdCodice></IdFiscaleIVA>
   <Anagrafica><Denominazione>Caseificio Esempio srl</Denominazione></Anagrafica></DatiAnagrafici></CedentePrestatore>
  <CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>09876543210</IdCodice></IdFiscaleIVA></DatiAnagrafici></CessionarioCommittente>
 </FatturaElettronicaHeader>
 <FatturaElettronicaBody>
  <DatiGenerali><DatiGeneraliDocumento><TipoDocumento>{tipo}</TipoDocumento><Divisa>EUR</Divisa><Data>{data}</Data><Numero>{numero}</Numero></DatiGeneraliDocumento></DatiGenerali>
  <DatiBeniServizi>{linee}<DatiRiepilogo><AliquotaIVA>4.00</AliquotaIVA><ImponibileImporto>64.00</ImponibileImporto><Imposta>2.56</Imposta></DatiRiepilogo></DatiBeniServizi>
 </FatturaElettronicaBody>
</p:FatturaElettronica>'''.encode()


def firma(dati):
    """Una busta .p7m vera (CMS SignedData con il contenuto dentro), come quelle dello SdI."""
    from datetime import datetime, timedelta
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import pkcs7
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Fornitore di prova')])
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(k.public_key())
            .serial_number(1).not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2027, 1, 1))
            .sign(k, hashes.SHA256()))
    return (pkcs7.PKCS7SignatureBuilder().set_data(dati).add_signer(cert, k, hashes.SHA256())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary]))


class Lettore(unittest.TestCase):

    def test_xml(self):
        (f,) = leggi_xml(fattura_xml())
        self.assertEqual((f['fornitore'], f['piva'], f['numero'], str(f['data'])),
                         ('Caseificio Esempio srl', '01234567890', 'FT-101', '2026-09-10'))
        self.assertEqual(len(f['righe']), 3)
        self.assertEqual(f['righe'][0]['quantita'], 4.0)
        self.assertIsNone(f['righe'][2]['quantita'])
        self.assertEqual(f['imponibile'], 64.0)
        self.assertEqual(f['segno'], 1)

    def test_lotti_e_scadenze_non_cambiano_la_chiave(self):
        self.assertEqual(normalizza('FIORDILATTE JULIENNE 3KG LOTTO 7781 SCAD 30/09/26'),
                         normalizza('Fiordilatte julienne 3kg lotto A12 scad. 14/10/2026'))

    def test_p7m_der_e_base64(self):
        busta = firma(fattura_xml())
        for dati in (busta, base64.encodebytes(busta)):
            ((nome, f),) = leggi_file('IT01234567890_abc.xml.p7m', dati)
            self.assertNotIsInstance(f, FatturaNonLeggibile)
            self.assertEqual(f['numero'], 'FT-101')

    def test_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('a/IT1_1.xml', fattura_xml('A1'))
            z.writestr('a/IT1_2.xml.p7m', firma(fattura_xml('A2')))
            z.writestr('__MACOSX/._IT1_1.xml', b'x')
            z.writestr('leggimi.txt', b'niente')
        out = leggi_file('fatture.zip', buf.getvalue())
        self.assertEqual(sorted(f['numero'] for _, f in out), ['A1', 'A2'])

    def test_file_sbagliati(self):
        for dati in (b'ciao', b'<a/>', b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'):
            ((_, f),) = leggi_file('x.xml', dati)
            self.assertIsInstance(f, FatturaNonLeggibile)

    def test_nota_di_credito(self):
        (f,) = leggi_xml(fattura_xml(tipo='TD04'))
        self.assertEqual(f['segno'], -1)

    def test_fattore_suggerito(self):
        self.assertEqual(suggerisci_fattore('FIORDILATTE JULIENNE 3KG', 'PZ', 'kg'), 3.0)
        self.assertEqual(suggerisci_fattore('POMODORI PELATI 6X2,5KG', 'CT', 'kg'), 15.0)
        # un cartone da 60 cornetti da 60 g: 3,6 kg, oppure 60 pezzi
        self.assertEqual(suggerisci_fattore('CORNETTI VUOTI SURG. 60G CT60', 'CT', 'kg'), 3.6)
        self.assertEqual(suggerisci_fattore('CORNETTI VUOTI SURG. 60G CT60', 'CT', 'pz'), 60.0)
        self.assertEqual(suggerisci_fattore('PANNA 500 ML', 'PZ', 'l'), 0.5)
        self.assertEqual(suggerisci_fattore('FARINA 00', 'KG', 'kg'), 1.0)
        self.assertIsNone(suggerisci_fattore('BASILICO', 'MAZZO', 'kg'))


class Api(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        cls.lid = cls.c.post('/api/rete/locali', json={'nome': 'Pizzeria pilota'}, headers=H).get_json()['id']

    def carica(self, *files):
        data = {'file': [(io.BytesIO(d), n) for n, d in files]}
        return self.c.post(f'/api/rete/locali/{self.lid}/fatture', data=data, headers=H,
                           content_type='multipart/form-data')

    def test_1_senza_chiave(self):
        self.assertEqual(self.c.get(f'/api/rete/locali/{self.lid}/fatture').status_code, 401)

    def test_2_carica_e_doppioni(self):
        r = self.carica(('f1.xml', fattura_xml('FT-101', '2026-09-10'))).get_json()
        self.assertEqual(len(r['importate']), 1)
        self.assertEqual(r['da_collegare'], 2)          # il trasporto non ha quantità
        r = self.carica(('f1-copia.xml', fattura_xml('FT-101', '2026-09-10')),
                        ('rotto.xml', b'<niente')).get_json()
        self.assertEqual((len(r['importate']), len(r['doppie']), len(r['errori'])), (0, 1, 1))

    def test_3_collega_e_prezzo(self):
        gruppi = self.c.get(f'/api/rete/locali/{self.lid}/da-collegare', headers=H).get_json()
        self.assertEqual(gruppi[0]['totale'], 36.0)    # il più pesante in euro per primo
        self.assertEqual(gruppi[0]['fattore_kg'], 3.0)
        r = self.c.post(f'/api/rete/locali/{self.lid}/collega', headers=H, json={
            'chiave': gruppi[0]['chiave'], 'fattore': 3, 'articolo': {'nome': 'Fiordilatte', 'unita': 'kg'}})
        art = r.get_json()['articolo']
        self.assertEqual(art['prezzo'], 3.0)           # 36 € / (4 pezzi × 3 kg)
        type(self).fiordilatte = art['id']

    def test_4_la_seconda_fattura_si_collega_da_sola(self):
        nuova = fattura_xml('FT-140', '2026-09-24', righe=[
            ('1', 'FIORDILATTE JULIENNE 3KG LOTTO 8123 SCAD 12/10/26', 'PZ', '5.00', '48.00')])
        r = self.carica(('f2.xml', nuova)).get_json()
        self.assertEqual(r['da_collegare'], 0)
        arts = {a['id']: a for a in self.c.get(f'/api/rete/locali/{self.lid}/articoli', headers=H).get_json()}
        self.assertEqual(arts[self.fiordilatte]['prezzo'], 3.2)   # 48 / 15 kg, la fattura più recente
        self.assertEqual(arts[self.fiordilatte]['prezzo_data'], '2026-09-24')

    def test_5_la_nota_di_credito_non_cambia_il_prezzo(self):
        nc = fattura_xml('NC-3', '2026-09-26', tipo='TD04', righe=[
            ('1', 'FIORDILATTE JULIENNE 3KG LOTTO 8123', 'PZ', '1.00', '5.00')])
        self.carica(('nc.xml', nc))
        arts = {a['id']: a for a in self.c.get(f'/api/rete/locali/{self.lid}/articoli', headers=H).get_json()}
        self.assertEqual(arts[self.fiordilatte]['prezzo'], 3.2)

    def test_6_ignora_le_righe_non_cibo(self):
        gruppi = self.c.get(f'/api/rete/locali/{self.lid}/da-collegare', headers=H).get_json()
        farina = [g for g in gruppi if 'FARINA' in g['descrizione']][0]
        self.c.post(f'/api/rete/locali/{self.lid}/collega', headers=H, json={'chiave': farina['chiave'], 'ignora': True})
        gruppi = self.c.get(f'/api/rete/locali/{self.lid}/da-collegare', headers=H).get_json()
        self.assertFalse([g for g in gruppi if 'FARINA' in g['descrizione']])

    def test_7_altro_locale_non_vede_niente(self):
        altro = self.c.post('/api/rete/locali', json={'nome': 'Altro'}, headers=H).get_json()['id']
        self.assertEqual(self.c.get(f'/api/rete/locali/{altro}/fatture', headers=H).get_json(), [])
        r = self.c.patch(f'/api/rete/locali/{altro}/articoli/{self.fiordilatte}', headers=H, json={'nome': 'x'})
        self.assertEqual(r.status_code, 404)

    def test_8_elimina_fattura_ricalcola_il_prezzo(self):
        fs = self.c.get(f'/api/rete/locali/{self.lid}/fatture', headers=H).get_json()
        ft140 = [f for f in fs if f['numero'] == 'FT-140'][0]
        self.c.delete(f'/api/rete/locali/{self.lid}/fatture/{ft140["id"]}', headers=H)
        arts = {a['id']: a for a in self.c.get(f'/api/rete/locali/{self.lid}/articoli', headers=H).get_json()}
        self.assertEqual(arts[self.fiordilatte]['prezzo'], 3.0)


if __name__ == '__main__':
    unittest.main()
