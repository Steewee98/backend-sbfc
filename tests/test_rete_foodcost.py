"""Test dei passi 3-6 della Rete SB: ricettario, vendite, inventari, diagnosi.

Un caso fatto a mano di cui conosciamo i numeri giusti:
  fiordilatte: 5 kg a inizio, comprati 60 kg a 3,20 (prima costava 3,00), 2 kg buttati,
               7 kg a fine → usati 58 kg; le 400 margherite ne giustificano 48 → 8 kg oltre ricetta.
  farina:      10 + 50 − 8 = 52 kg usati, le margherite ne giustificano 60 → 8 kg in meno.
"""
import io
import os
import sys
import tempfile
import unittest

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from models import db  # noqa: E402
from services.cassa import leggi_tabella, proponi_colonne, _numero  # noqa: E402
from test_rete_fatture import fattura_xml  # noqa: E402

H = {'X-Admin-Token': 'test-token'}

REPORT = """Report vendite per articolo - Pizzeria pilota
Data;Descrizione;Q.tà;Totale €
02/09/2026;MARGHERITA;150;1.200,00
05/09/2026;Margherita ;250;2.000,00
05/09/2026;COPERTO;100;200,00
05/09/2026;COCA COLA;30;90,00
;TOTALE;530;3.490,00
""".encode('cp1252')


class Cassa(unittest.TestCase):

    def test_csv_con_titolo_sopra(self):
        intest, righe = leggi_tabella('report.csv', REPORT)
        self.assertEqual(intest, ['Data', 'Descrizione', 'Q.tà', 'Totale €'])
        self.assertEqual(proponi_colonne(intest), {'voce': 1, 'quantita': 2, 'incasso': 3, 'data': 0})
        self.assertEqual(len(righe), 5)

    def test_colonne_in_piu(self):
        """Il report prodotti di SumUp in inglese e in italiano, e due trappole: «Scontrino» non sono
        gli sconti, «Totale IVA inclusa» non è l'IVA."""
        en = ['Product', 'Currency', 'Unit of measure', 'Quantity', 'Purchase Price excl Tax', 'Discounts',
              'Sales incl Tax', 'Sales excl Tax', 'Tax Amount', 'Gross Margin']
        self.assertEqual(proponi_colonne(en), {'voce': 0, 'quantita': 3, 'costo': 4, 'sconti': 5, 'incasso': 6,
                                               'netto': 7, 'iva': 8, 'margine': 9})
        it = ['Prodotto', 'Valuta', 'Unità di misura', 'Quantità', 'Prezzo di acquisto IVA esclusa', 'Sconti',
              'Vendite IVA inclusa', 'Vendite IVA esclusa', 'Importo IVA', 'Margine lordo']
        self.assertEqual(proponi_colonne(it), {'voce': 0, 'quantita': 3, 'costo': 4, 'sconti': 5, 'incasso': 6,
                                               'netto': 7, 'iva': 8, 'margine': 9})
        self.assertEqual(proponi_colonne(['Data', 'Scontrino', 'Descrizione', 'Qtà', 'Totale IVA inclusa']),
                         {'data': 0, 'voce': 2, 'quantita': 3, 'incasso': 4})

    def test_periodo_nel_nome(self):
        from datetime import date
        from services.cassa import periodo_dal_nome
        self.assertEqual(periodo_dal_nome('product-sales-report-2026-01-01_2026-09-22 (1).csv'),
                         (date(2026, 1, 1), date(2026, 9, 22)))
        self.assertIsNone(periodo_dal_nome('report.csv'))
        self.assertIsNone(periodo_dal_nome('report-2026-09-22_2026-01-01.csv'))     # al contrario non vale

    def test_numeri_italiani(self):
        for s, v in (('1.200,00', 1200.0), ('1,5', 1.5), ('1,234.50', 1234.5), ('€ 12', 12.0), ('abc', None)):
            self.assertEqual(_numero(s), v)

    def test_excel(self):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(['Prodotto', 'Venduti', 'Incasso'])
        ws.append(['Diavola', 12, 108.0])
        buf = io.BytesIO(); wb.save(buf)
        intest, righe = leggi_tabella('vendite.xlsx', buf.getvalue())
        self.assertEqual(proponi_colonne(intest), {'voce': 0, 'quantita': 1, 'incasso': 2})
        self.assertEqual(righe[0], ['Diavola', 12, 108.0])


class Diagnosi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        lid = cls.lid = c.post('/api/rete/locali', json={'nome': 'Pizzeria pilota'}, headers=H).get_json()['id']
        base = f'/api/rete/locali/{lid}'
        cls.base = base

        def carica(xml):
            return c.post(base + '/fatture', data={'file': [(io.BytesIO(xml), 'f.xml')]}, headers=H,
                          content_type='multipart/form-data').get_json()
        # prima del periodo: fiordilatte a 3,00 €/kg, farina a 0,80
        carica(fattura_xml('FT-1', '2026-08-28', righe=[('1', 'FIORDILATTE JULIENNE 3KG', 'PZ', '10.00', '90.00'),
                                                        ('2', 'FARINA 00 W300', 'KG', '25.00', '20.00')]))
        gruppi = {g['descrizione']: g for g in c.get(base + '/da-collegare', headers=H).get_json()}
        cls.fior = c.post(base + '/collega', headers=H, json={'chiave': gruppi['FIORDILATTE JULIENNE 3KG']['chiave'], 'fattore': 3,
                                                               'articolo': {'nome': 'Fiordilatte', 'unita': 'kg'}}).get_json()['articolo']['id']
        cls.farina = c.post(base + '/collega', headers=H, json={'chiave': gruppi['FARINA 00 W300']['chiave'], 'fattore': 1,
                                                                 'articolo': {'nome': 'Farina 00', 'unita': 'kg'}}).get_json()['articolo']['id']
        # inventario d'inizio, 1 settembre
        cls.inv_a = c.post(base + '/inventari', headers=H, json={'giorno': '2026-09-01'}).get_json()['id']
        c.patch(f'{base}/inventari/{cls.inv_a}', headers=H, json={'righe': {cls.fior: 5, cls.farina: 10}, 'chiuso': True})
        # nel periodo: il fiordilatte sale a 3,20
        carica(fattura_xml('FT-2', '2026-09-10', righe=[('1', 'FIORDILATTE JULIENNE 3KG', 'PZ', '20.00', '192.00'),
                                                        ('2', 'FARINA 00 W300', 'KG', '50.00', '40.00')]))
        c.post(base + '/movimenti', headers=H, json={'articolo_id': cls.fior, 'tipo': 'scarto', 'quantita': 2, 'giorno': '2026-09-12'})
        # la ricetta
        cls.marg = c.post(base + '/ricette', headers=H, json={'nome': 'Margherita', 'prezzo': 8, 'resa': 1, 'righe': [
            {'articolo_id': cls.fior, 'quantita': 0.12}, {'articolo_id': cls.farina, 'quantita': 0.15}]}).get_json()
        # le vendite
        c.post(base + '/vendite', headers=H, content_type='multipart/form-data', data={
            'file': (io.BytesIO(REPORT), 'report.csv'),
            'colonne': '{"voce": 1, "quantita": 2, "incasso": 3, "data": 0}'})
        c.post(base + '/voci', headers=H, json={'voce': 'MARGHERITA', 'ricetta_id': cls.marg['id']})
        c.post(base + '/voci', headers=H, json={'voce': 'COPERTO', 'ignora': True})
        # inventario di fine, 15 settembre
        cls.inv_b = c.post(base + '/inventari', headers=H, json={'giorno': '2026-09-15'}).get_json()['id']
        c.patch(f'{base}/inventari/{cls.inv_b}', headers=H, json={'righe': {cls.fior: 7, cls.farina: 8}, 'chiuso': True})

    def test_costo_del_piatto(self):
        # ai prezzi di oggi: 0,12 × 3,20 + 0,15 × 0,80 = 0,504 €; su 8 € IVA 10% compresa = 6,9%
        self.assertAlmostEqual(self.marg['costo'], 0.504, places=3)
        self.assertEqual(self.marg['food_cost'], 6.9)

    def test_le_voci_si_sommano_e_i_totali_si_saltano(self):
        voci = {v['voce']: v for v in self.c.get(self.base + '/voci', headers=H).get_json()}
        self.assertEqual(voci['MARGHERITA']['quantita'], 400)
        self.assertNotIn('TOTALE', voci)
        # l'analisi delle vendite riconosce la bibita: categoria e ricetta del catalogo (una lattina), nome pulito
        coca = voci['COCA COLA']
        self.assertEqual((coca['nome'], coca['categoria'], coca['da_fare'], coca['automatico']), ('Coca cola', 'Bevande', False, True))
        # «MARGHERITA» e «Margherita » sono la stessa voce scritta in due modi: si vede che sono unite
        self.assertEqual(voci['MARGHERITA']['uniti'], ['MARGHERITA', 'Margherita'])
        self.assertTrue(voci['COPERTO']['ignorata'])

    def test_reimportare_non_raddoppia(self):
        self.c.post(self.base + '/vendite', headers=H, content_type='multipart/form-data', data={
            'file': (io.BytesIO(REPORT), 'report.csv'), 'colonne': '{"voce": 1, "quantita": 2, "incasso": 3, "data": 0}'})
        voci = {v['voce']: v for v in self.c.get(self.base + '/voci', headers=H).get_json()}
        self.assertEqual(voci['MARGHERITA']['quantita'], 400)

    def test_diagnosi(self):
        d = self.c.get(self.base + '/diagnosi', headers=H).get_json()
        art = {a['nome']: a for a in d['articoli']}
        f = art['Fiordilatte']
        self.assertEqual((f['reale'], f['teorico'], f['scarti']), (58, 48, 2))
        self.assertEqual((f['prezzo_prima'], f['prezzo_periodo']), (3.0, 3.2))
        self.assertAlmostEqual(f['consumo'], 25.6, places=2)     # 8 kg × 3,20
        self.assertAlmostEqual(f['prezzo'], 9.6, places=2)       # 48 kg × 0,20
        self.assertAlmostEqual(f['scarto'], 6.4, places=2)       # 2 kg × 3,20
        self.assertEqual(f['oltre_pct'], 16.7)
        self.assertAlmostEqual(art['Farina 00']['consumo'], -6.4, places=2)
        self.assertAlmostEqual(d['ricavi_netti'], 3200 / 1.1, places=1)
        self.assertEqual(d['voci']['consumo']['punti'], 0.66)    # (25,6 − 6,4) / 2909,09
        self.assertEqual(d['voci']['prezzo']['punti'], 0.33)
        self.assertEqual(d['voci']['scarto']['punti'], 0.22)
        self.assertEqual(d['food_cost_reale'], 7.81)             # 227,20 / 2909,09
        self.assertEqual(d['food_cost_teorico'], 6.6)            # 192,00 / 2909,09
        self.assertIn('0,66 punti', d['frase'])
        self.assertIn('consumo oltre ricetta', d['frase'])
        # la bibita ha la ricetta del catalogo ma non ancora il prezzo di una fattura: fuori dal calcolo, e lo dice
        self.assertTrue(any('Bibita in lattina' in a and 'senza il prezzo di una fattura' in a for a in d['avvisi']))

    def test_la_scomposizione_torna(self):
        d = self.c.get(self.base + '/diagnosi', headers=H).get_json()
        somma = d['costo_teorico'] + sum(v['euro'] for v in d['voci'].values())
        self.assertAlmostEqual(somma, d['costo_reale'], places=1)

    def test_riepilogo_della_rete(self):
        r = {l['nome']: l for l in self.c.get('/api/rete/riepilogo', headers=H).get_json()}
        p = r['Pizzeria pilota']
        self.assertEqual(p['diagnosi']['food_cost_reale'], 7.81)
        self.assertEqual(p['semaforo'], 'attesa')                # consumo oltre ricetta 0,66 punti
        self.assertEqual(p['voci_da_abbinare'], 0)               # la COCA COLA l'ha abbinata l'analisi delle vendite
        self.assertEqual(p['ultimo_inventario'], '2026-09-15')

    def test_senza_due_inventari_niente_diagnosi(self):
        altro = self.c.post('/api/rete/locali', json={'nome': 'Vuoto'}, headers=H).get_json()['id']
        self.assertEqual(self.c.get(f'/api/rete/locali/{altro}/diagnosi', headers=H).status_code, 400)


if __name__ == '__main__':
    unittest.main()


class Riepilogo(unittest.TestCase):

    def test_semaforo(self):
        from routes.rete_foodcost import semaforo
        base = {'obiettivo': 22, 'voci': {'consumo': {'punti': 0.1}}}
        self.assertEqual(semaforo(None), 'vuoto')
        self.assertEqual(semaforo({**base, 'food_cost_reale': 20}), 'buono')
        self.assertEqual(semaforo({**base, 'food_cost_reale': 23}), 'attesa')
        self.assertEqual(semaforo({**base, 'food_cost_reale': 25}), 'fuori')
        self.assertEqual(semaforo({**base, 'food_cost_reale': 18, 'voci': {'consumo': {'punti': 1.2}}}), 'fuori')
