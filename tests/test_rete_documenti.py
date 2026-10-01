"""Documenti d'acquisto che non sono XML: PDF e foto letti da Claude, anche mischiati
in uno ZIP con le fatture elettroniche. Il modello è sostituito da risposte fisse:
qui si prova tutto quello che succede prima e dopo la lettura.

    SBFC_NO_BG=1 venv/bin/python -m unittest tests.test_rete_documenti -v
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1',
                  RETE_LETTURA_SUBITO='1', ANTHROPIC_API_KEY='finta')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db, FatturaRete, RigaFattura  # noqa: E402
from services import lettura_ai  # noqa: E402
from services.lettura_ai import converti, tipo_file, xml_dentro_pdf  # noqa: E402
from tests.test_rete_fatture import fattura_xml  # noqa: E402

H = {'X-Admin-Token': 'test-token'}
PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n'


def jpg(tinta=0):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (3000, 2000), (240, 235 - tinta * 20, 220)).save(out, 'JPEG')
    return out.getvalue()


def doc(**k):
    base = {'tipo': 'fattura', 'fornitore': 'Salumeria Fratelli Neri snc', 'piva_fornitore': None, 'numero': '778/2026',
            'data': '2026-09-08', 'categoria': 'salumi e formaggi', 'imponibile': 51.84, 'leggibilita': 'buona', 'dubbi': [],
            'righe': [{'descrizione': 'Prosciutto crudo affettato conf. 500 g', 'quantita': 2, 'unita': 'PZ', 'prezzo_unitario': 11.2,
                       'totale': 22.4, 'cibo': True},
                      {'descrizione': 'Pecorino romano DOP', 'quantita': 1.6, 'unita': 'KG', 'prezzo_unitario': 16.8, 'totale': 26.88, 'cibo': True},
                      {'descrizione': 'Carta per affettati', 'quantita': 1, 'unita': 'PZ', 'prezzo_unitario': 2.56, 'totale': 2.56, 'cibo': False}]}
    base.update(k)
    return base


# cosa «legge» il modello per ogni file, per nome
RISPOSTE = {}


def finta_chiama(contenuto):
    nome = contenuto[-1]['text'].removeprefix('File: ')
    tipo = contenuto[0]['type']
    assert tipo in ('document', 'image')
    if tipo == 'image':
        from PIL import Image
        import base64
        im = Image.open(io.BytesIO(base64.b64decode(contenuto[0]['source']['data'])))
        assert max(im.size) <= lettura_ai.LATO_MAX, 'la foto va rimpicciolita prima di mandarla'
    r = RISPOSTE[nome]
    if isinstance(r, Exception):
        raise r
    return {'documenti': r}


class Documenti(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        lettura_ai.chiama = finta_chiama
        cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        cls.lid = cls.c.post('/api/rete/locali', json={'nome': 'Mera Bistrot'}, headers=H).get_json()['id']
        cls.base = f'/api/rete/locali/{cls.lid}'

    def carica(self, *files):
        r = self.c.post(self.base + '/fatture', headers=H, content_type='multipart/form-data',
                        data={'file': [(io.BytesIO(d), n) for n, d in files]})
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        if 'lettura' in d:     # in prova la lettura è già finita: si legge l'esito completo
            d = self.c.get(f"{self.base}/letture/{d['lettura']['id']}", headers=H).get_json()
            self.assertTrue(d['finita'])
        return d

    # ── pezzi singoli ──

    def test_riconosce_i_file(self):
        self.assertEqual(tipo_file('x.bin', PDF), 'pdf')
        self.assertEqual(tipo_file('senza-estensione', jpg()), 'immagine')
        self.assertIsNone(tipo_file('LEGGIMI.txt', b'ciao'))

    def test_xml_allegato_nel_pdf(self):
        pdf = PDF + b'<</Type/EmbeddedFile>>stream\n' + fattura_xml() + b'\nendstream'
        self.assertIn(b'FatturaElettronica', xml_dentro_pdf(pdf))
        self.assertIsNone(xml_dentro_pdf(PDF))

    def test_converti_controlla_i_conti(self):
        fa = converti(doc(imponibile=60), 'pdf', oggi=date(2026, 9, 29))
        self.assertTrue(any('sommano' in c for c in fa['etichette']['controlla']))
        self.assertFalse(fa['righe'][2]['cibo'])
        self.assertEqual(converti(doc(), 'pdf', oggi=date(2026, 9, 29))['etichette']['controlla'], [])
        self.assertIsInstance(converti(doc(tipo='altro', dubbi=['è un menù']), 'foto'), lettura_ai.FatturaNonLeggibile)
        self.assertIsInstance(converti(doc(data=None), 'foto'), lettura_ai.FatturaNonLeggibile)
        ddt = converti(doc(tipo='ddt', imponibile=None, righe=[{'descrizione': 'Limoni', 'quantita': 5, 'unita': 'kg', 'totale': None, 'cibo': True}]),
                       'foto', oggi=date(2026, 9, 29))
        self.assertEqual((ddt['tipo'], ddt['segno'], ddt['imponibile']), ('DDT', 0, None))

    # ── il giro completo ──

    def test_zip_mischiato(self):
        RISPOSTE.update({
            'fattura-salumeria-778.pdf': [doc()],
            'fattura-salumeria-778-foto.jpg': [doc(numero='778/26', dubbi=['foto un po\' sfocata'])],   # la stessa, fotografata
            'bolla-ortofrutta-2231.jpg': [doc(tipo='ddt', fornitore='Ortofrutta Mercato Esempio', numero='2231', data='2026-09-09',
                                              categoria='frutta e verdura', imponibile=None, note_consegna='1 cassa ammaccata',
                                              righe=[{'descrizione': 'Arance da spremuta', 'quantita': 20, 'unita': 'kg', 'totale': None, 'cibo': True}])],
            'scansione-mese.pdf': [doc(fornitore='Forno San Lorenzo', numero='F-0931', data='2026-09-04', categoria='pane e pasticceria', imponibile=12,
                                       righe=[{'descrizione': 'Pane casereccio', 'quantita': 4, 'unita': 'KG', 'prezzo_unitario': 3, 'totale': 12, 'cibo': True}]),
                                   doc(tipo='nota_credito', fornitore='Latteria Valle Verde', numero='NC-112', data='2026-09-22',
                                       categoria='latte e latticini', imponibile=7.08,
                                       righe=[{'descrizione': 'Reso latte 1 l', 'quantita': 6, 'unita': 'PZ', 'totale': 7.08, 'cibo': True}])],
            'menu-del-giorno.jpg': [doc(tipo='altro', dubbi=['è il menù del giorno, non un acquisto'])],
            'rovinata.pdf': lettura_ai.FatturaNonLeggibile('Lettura non riuscita adesso: riprova tra poco'),
        })
        z = io.BytesIO()
        with zipfile.ZipFile(z, 'w') as zz:
            zz.writestr('marzo/fattura-caseificio.xml', fattura_xml())
            zz.writestr('marzo/fattura-salumeria-778.pdf', PDF + b'%salumeria')
            zz.writestr('marzo/fattura-salumeria-778-foto.jpg', jpg(1))
            zz.writestr('marzo/bolla-ortofrutta-2231.jpg', jpg(2))
            zz.writestr('marzo/scansione-mese.pdf', PDF + b'%mese')
            zz.writestr('marzo/menu-del-giorno.jpg', jpg(3))
            zz.writestr('marzo/rovinata.pdf', PDF + b'%rovinata')
            zz.writestr('marzo/LEGGIMI.txt', b'da ignorare')
            zz.writestr('__MACOSX/marzo/._fattura.pdf', b'x')
        r = self.carica(('tutto-settembre.zip', z.getvalue()))

        self.assertEqual(r['totale'], 6)                                 # l'XML si legge da sé, il .txt si salta
        importate = {f['numero']: f for f in r['importate']}
        self.assertEqual(set(importate), {'FT-101', '778/2026', '2231', 'F-0931', 'NC-112'})
        self.assertEqual(importate['FT-101']['etichette']['fonte'], 'xml')
        self.assertEqual(importate['2231']['etichette']['documento'], 'ddt')
        self.assertEqual(importate['2231']['etichette']['note'], '1 cassa ammaccata')
        self.assertEqual(importate['NC-112']['segno'], -1)
        # la foto della stessa fattura è riconosciuta come doppione anche col numero scritto diverso
        self.assertEqual([d['file'] for d in r['doppie']], ['fattura-salumeria-778-foto.jpg'])
        errori = {e['file']: e['errore'] for e in r['errori']}
        self.assertIn('menù', errori['menu-del-giorno.jpg'])
        self.assertIn('riprova', errori['rovinata.pdf'])
        self.assertTrue(any(d['numero'] == '2231' and d['note'] for d in r['da_controllare']))

        with app.app_context():
            sal = FatturaRete.query.filter_by(numero='778/2026').one()
            self.assertEqual(sal.etichette['categoria'], 'salumi e formaggi')
            carta = RigaFattura.query.filter_by(fattura_id=sal.id, descrizione='Carta per affettati').one()
            self.assertTrue(carta.ignorata)                                # non è cibo: fuori dal food cost
            self.assertTrue(sal.righe[0].chiave.startswith('NOME:'))      # senza P.IVA gli alias si agganciano al nome

        # la bolla non conta negli acquisti, la nota di credito sì (in negativo)
        q = self.c.get(self.base + '/quadro', headers=H).get_json()
        self.assertIsNotNone(q['lavoro'])
        # i prodotti da collegare non comprendono la carta
        voci = [g['descrizione'] for g in self.c.get(self.base + '/da-collegare', headers=H).get_json()]
        self.assertNotIn('Carta per affettati', voci)
        self.assertNotIn('Arance da spremuta', voci)       # le righe delle bolle non si collegano: niente prezzi

        # ricaricare lo stesso ZIP non duplica niente e non rimanda a Claude i file già letti
        letti = []
        vera = lettura_ai.chiama
        lettura_ai.chiama = lambda c: letti.append(c[-1]['text']) or vera(c)
        try:
            r2 = self.carica(('tutto-settembre.zip', z.getvalue()))
        finally:
            lettura_ai.chiama = vera
        self.assertEqual(r2['importate'], [])
        # si rileggono solo quelli che la prima volta non erano entrati (il menù, il file rovinato, la foto doppione)
        self.assertEqual(sorted(letti), ['File: fattura-salumeria-778-foto.jpg', 'File: menu-del-giorno.jpg', 'File: rovinata.pdf'])

    def test_xml_dopo_il_pdf_prende_il_posto(self):
        # prima arriva il PDF (senza P.IVA), poi dal cassetto fiscale l'XML della stessa fattura
        RISPOSTE['caseificio-copia.pdf'] = [doc(fornitore='Caseificio Esempio', numero='FT-500', data='2026-09-10', imponibile=64,
                                                categoria='latte e latticini',
                                                righe=[{'descrizione': 'Fiordilatte 3 kg', 'quantita': 4, 'unita': 'PZ', 'totale': 36, 'cibo': True},
                                                       {'descrizione': 'Farina 00', 'quantita': 25, 'unita': 'KG', 'totale': 20, 'cibo': True},
                                                       {'descrizione': 'Trasporto', 'quantita': None, 'unita': None, 'totale': 8, 'cibo': False}])]
        self.assertEqual(len(self.carica(('caseificio-copia.pdf', PDF + b'%caseificio'))['importate']), 1)
        r = self.carica(('FT-500.xml', fattura_xml(numero='FT/500')))
        self.assertEqual(len(r['importate']), 1)
        self.assertEqual(r['sostituite'][0]['prima'], 'caseificio-copia.pdf')
        with app.app_context():
            rimaste = FatturaRete.query.filter(FatturaRete.locale_id == self.lid, FatturaRete.data == date(2026, 9, 10),
                                               FatturaRete.numero.in_(['FT-500', 'FT/500'])).all()
            self.assertEqual([(f.numero, f.etichette['fonte']) for f in rimaste], [('FT/500', 'xml')])
        # e il PDF ricaricato dopo l'XML è un doppione
        RISPOSTE['caseificio-copia-2.pdf'] = RISPOSTE['caseificio-copia.pdf']
        self.assertEqual(len(self.carica(('caseificio-copia-2.pdf', PDF + b'%caseificio2'))['doppie']), 1)

    def test_stesso_numero_scritto_diverso(self):
        from routes.rete_dati import _stesso_numero
        for a, b in (('112/26', '112-26'), ('778/2026', '2026/778'), ('PL-88', '88'), ('F-0931', 'F0931')):
            self.assertTrue(_stesso_numero(a, b), (a, b))
        for a, b in (('112/26', '131/26'), ('F-0931', 'F-1002'), ('1/26', '2/26')):
            self.assertFalse(_stesso_numero(a, b), (a, b))

    def test_confermare_e_correggere(self):
        RISPOSTE['da-guardare.jpg'] = [doc(fornitore='Macelleria Esempio', numero='M-7', data='2026-09-15', categoria='carne', imponibile=40,
                                           dubbi=['quantità della prima riga poco leggibile'],
                                           righe=[{'descrizione': 'Guanciale', 'quantita': 8, 'unita': 'KG', 'totale': 40, 'cibo': True}])]
        r = self.carica(('da-guardare.jpg', jpg(9)))
        fid = r['da_controllare'][0]['id']
        f = self.c.get(f'{self.base}/fatture/{fid}', headers=H).get_json()
        rid = f['dettaglio'][0]['id']
        # la quantità era 3, non 8: si corregge e l'imponibile segue
        x = self.c.patch(f'{self.base}/fatture/{fid}/righe/{rid}', headers=H, json={'quantita': 3, 'totale': 45}).get_json()
        self.assertEqual((x['quantita'], x['totale']), (3, 45))
        f = self.c.patch(f'{self.base}/fatture/{fid}', headers=H, json={'visto': True, 'numero': 'M-7/26'}).get_json()
        self.assertEqual((f['numero'], f['imponibile']), ('M-7/26', 45))
        self.assertIn('visto', f['etichette'])
        # confermato: non è più tra i documenti da guardare
        ind = {i['id']: i for i in self.c.get(self.base + '/indicatori', headers=H).get_json()['indicatori']}
        with app.app_context():
            aperti = [z for z in FatturaRete.query.filter_by(locale_id=self.lid).all()
                      if ((z.etichette or {}).get('controlla') or (z.etichette or {}).get('note')) and not (z.etichette or {}).get('visto')]
        self.assertEqual(ind['doc']['valore'], len(aperti))
        self.assertNotIn(fid, [z.id for z in aperti])

    def test_file_non_documento_si_salta(self):
        r = self.carica(('LEGGIMI.txt', b'istruzioni per la prova'))
        self.assertEqual((r['saltati'], r['errori']), (['LEGGIMI.txt'], []))

    def test_senza_chiave_lo_dice(self):
        k = os.environ.pop('ANTHROPIC_API_KEY')
        try:
            RISPOSTE['x.pdf'] = [doc()]
            r = self.carica(('x.pdf', PDF))
            self.assertIn('non attiva', r['errori'][0]['errore'])
        finally:
            os.environ['ANTHROPIC_API_KEY'] = k

    def test_lettura_di_altro_locale(self):
        self.assertEqual(self.c.get(self.base + '/letture/nessuna', headers=H).status_code, 404)


if __name__ == '__main__':
    unittest.main()
