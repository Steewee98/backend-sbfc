"""I tre portali sono collegati: ogni cosa che il consulente fa in Managing
si vede in Monitoring (la direzione) e in Owner (il titolare).

Per ogni azione si legge cosa vedono gli altri due prima e dopo, con i loro
accessi veri: la direzione con email e password (sola lettura), il titolare
dall'app. Lo staff timbra e chiude dal tag, e anche questo deve arrivare.
"""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ.update(DATABASE_URL=f'sqlite:///{_db.name}', ADMIN_TOKEN='test-token', SBFC_NO_BG='1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from models import db  # noqa: E402
from services.quadro import giorno_di_lavoro  # noqa: E402

ADMIN = {'X-Admin-Token': 'test-token'}


def fattura_xml(numero, giorno, righe):
    linee = ''.join(f'<DettaglioLinee><NumeroLinea>{i + 1}</NumeroLinea><Descrizione>{d}</Descrizione><Quantita>{q}</Quantita>'
                    f'<UnitaMisura>{u}</UnitaMisura><PrezzoUnitario>1.00</PrezzoUnitario><PrezzoTotale>{t}</PrezzoTotale>'
                    f'<AliquotaIVA>4.00</AliquotaIVA></DettaglioLinee>' for i, (d, u, q, t) in enumerate(righe))
    tot = sum(float(t) for *_, t in righe)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
 <FatturaElettronicaHeader><CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>01234567890</IdCodice></IdFiscaleIVA>
   <Anagrafica><Denominazione>Latteria Esempio</Denominazione></Anagrafica></DatiAnagrafici></CedentePrestatore></FatturaElettronicaHeader>
 <FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa>
  <Data>{giorno}</Data><Numero>{numero}</Numero></DatiGeneraliDocumento></DatiGenerali>
  <DatiBeniServizi>{linee}<DatiRiepilogo><AliquotaIVA>4.00</AliquotaIVA><ImponibileImporto>{tot:.2f}</ImponibileImporto></DatiRiepilogo></DatiBeniServizi>
 </FatturaElettronicaBody></p:FatturaElettronica>'''.encode()


class TreePortali(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        c = cls.c = app.test_client()
        with app.app_context():
            db.drop_all(); db.create_all()
        cls.lid = c.post('/api/rete/locali', json={'nome': 'Mera Bistrot'}, headers=ADMIN).get_json()['id']
        cls.base = f'/api/rete/locali/{cls.lid}'
        for nome, email, pw, ruolo in (('Anna', 'anna@sb.prova', 'consulente-2026', 'consulente'),
                                       ('Simone', 'simone@sb.prova', 'direzione-2026', 'direzione')):
            r = c.post('/api/rete/consulenti', headers=ADMIN, json={'nome': nome, 'email': email, 'password': pw, 'ruolo': ruolo})
            assert r.status_code == 201, r.get_json()
        entra = lambda e, p: {'X-Admin-Token': c.post('/api/rete/login', json={'email': e, 'password': p}).get_json()['token']}
        cls.M = entra('anna@sb.prova', 'consulente-2026')        # Managing
        cls.D = entra('simone@sb.prova', 'direzione-2026')       # Monitoring
        c.post(cls.base + '/persone', headers=cls.M, json={'nome': 'Paola', 'ruolo': 'titolare',
                                                           'email': 'paola@mera.prova', 'password': 'quadro2026'})
        tok = c.post('/api/app/login', json={'email': 'paola@mera.prova', 'password': 'quadro2026'}).get_json()['token']
        cls.O = {'Authorization': 'Bearer ' + tok}                # Owner
        cls.codice = c.get(cls.base + '/app', headers=cls.M).get_json()['codice']
        cls.ieri = giorno_di_lavoro() - timedelta(days=1)

    # cosa vede ognuno dei due portali in sola lettura
    def monitoring(self):
        rie = next(x for x in self.c.get('/api/rete/riepilogo', headers=self.D).get_json() if x['id'] == self.lid)
        q = self.c.get(self.base + '/quadro', headers=self.D).get_json()
        a = self.c.get(self.base + '/andamento', headers=self.D).get_json()
        return rie, q, a

    def owner(self):
        r = self.c.get('/api/app/quadro', headers=self.O)
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_01_persona_aggiunta_si_vede(self):
        r = self.c.post(self.base + '/persone', headers=self.M, json={'nome': 'Giovanni', 'pin': '4321', 'costo_orario': 18})
        self.assertEqual(r.status_code, 201)
        type(self).gio = r.get_json()['id']
        _, q, _ = self.monitoring()
        self.assertIn('Giovanni', [p['nome'] for p in q['squadra']])
        self.assertIn('Giovanni', [p['nome'] for p in self.owner()['squadra']])

    def test_02_persona_rinominata_si_vede(self):
        self.c.patch(f'{self.base}/persone/{self.gio}', headers=self.M, json={'nome': 'Giovanni R.'})
        self.assertIn('Giovanni R.', [p['nome'] for p in self.monitoring()[1]['squadra']])
        self.assertIn('Giovanni R.', [p['nome'] for p in self.owner()['squadra']])

    def test_02b_turno_previsto_fa_il_costo_prima(self):
        # lun-ven 18-23 (5 h), sabato spezzato 12-15 e 19-01 (3 + 6 h, passa la mezzanotte): 34 ore, 612 € a settimana
        orario = [{'g': g, 'da': '18:00', 'a': '23:00'} for g in range(5)] + [{'g': 5, 'da': '12:00', 'a': '15:00'}, {'g': 5, 'da': '19:00', 'a': '01:00'}]
        r = self.c.patch(f'{self.base}/persone/{self.gio}', headers=self.M, json={'orario': orario})
        self.assertEqual(r.status_code, 200, r.get_json())
        p = r.get_json()['previsto']
        self.assertEqual((p['ore_settimana'], p['costo_settimana']), (34.0, 612.0))
        self.assertGreater(p['costo_mese'], 612 * 4 - 1)
        # lo vedono subito Monitoring e il titolare, prima di qualsiasi timbratura
        for q in (self.monitoring()[1], self.owner()):
            self.assertEqual(q['personale']['prossima']['euro'], 612.0)
            self.assertEqual(next(x for x in q['squadra'] if x['nome'] == 'Giovanni R.')['ore_previste'], 34.0)
        d = self.c.get(self.base + '/dossier', headers=self.D).get_json()
        self.assertEqual(d['personale']['sera_prevista'], [1, 1, 1, 1, 1, 1, 0])
        self.assertEqual(next(i for i in d['indicatori'] if i['id'] == 'prev')['valore'], None)   # ancora nessuna timbratura
        # un orario scritto male non passa
        for sbagliato in ([{'g': 7, 'da': '18:00', 'a': '23:00'}], [{'g': 1, 'da': '25:00', 'a': '23:00'}], [{'g': 1, 'da': '10:00', 'a': '10:00'}]):
            self.assertEqual(self.c.patch(f'{self.base}/persone/{self.gio}', headers=self.M, json={'orario': sbagliato}).status_code, 400)

    def test_02c_mansione_reparto_contratto(self):
        voci = self.c.get('/api/rete/squadra/voci', headers=self.M).get_json()
        self.assertEqual(voci['mansioni']['Pizzaiolo'], 'pizzeria')
        r = self.c.patch(f'{self.base}/persone/{self.gio}', headers=self.M, json={
            'mansione': 'Pizzaiolo', 'contratto': 'Indeterminato part-time', 'ore_contratto': 30,
            'telefono': '333 000 0000', 'assunto_il': '2026-03-01', 'note': 'Fa anche le pizze fritte'})
        self.assertEqual(r.status_code, 200, r.get_json())
        p = r.get_json()
        self.assertEqual((p['mansione'], p['reparto'], p['ore_contratto'], p['assunto_il']), ('Pizzaiolo', 'pizzeria', 30.0, '2026-03-01'))
        # un cameriere in più, con la mansione che porta la sala
        self.c.post(self.base + '/persone', headers=self.M, json={'nome': 'Luca', 'mansione': 'Cameriere', 'costo_orario': 12,
                                                                  'orario': [{'g': 4, 'da': '19:00', 'a': '23:00'}]})
        d = self.c.get(self.base + '/dossier', headers=self.D).get_json()['personale']
        rep = {x['id']: x for x in d['reparti']}
        self.assertEqual((rep['pizzeria']['costo_previsto'], rep['sala']['costo_previsto']), (612.0, 48.0))
        misure = next(i for i in self.c.get(self.base + '/dossier', headers=self.D).get_json()['indicatori'] if i['id'] == 'pers')['misure']
        self.assertTrue(any(m['titolo'].startswith('Turno previsto oltre') for m in misure))   # 34 ore previste su 30 da contratto
        self.assertTrue(any(m['titolo'].startswith('Il costo del personale per reparto') for m in misure))
        self.assertIn('Pizzaiolo', [x['mansione'] for x in self.owner()['squadra']])
        # voci che non esistono non passano
        for sbagliato in ({'contratto': 'Boh'}, {'reparto': 'giardino'}, {'ore_contratto': 200}, {'assunto_il': 'ieri'}):
            self.assertEqual(self.c.patch(f'{self.base}/persone/{self.gio}', headers=self.M, json=sbagliato).status_code, 400)
        # Luca non serve ai passi dopo
        luca = next(x for x in self.c.get(self.base + '/persone', headers=self.M).get_json() if x['nome'] == 'Luca')
        self.c.delete(f"{self.base}/persone/{luca['id']}", headers=self.M)

    def test_02d_personale_senza_cassa(self):
        ind = lambda: {i['id']: i for i in self.c.get(self.base + '/indicatori', headers=self.D).get_json()['indicatori']}
        # niente cassa e niente timbrature: l'anello non inventa una percentuale, ma dice quanto costa il turno previsto
        i = ind()
        self.assertIsNone(i['pers']['valore'])
        self.assertEqual(i['pers']['mostra'], '612 € previsti')
        self.assertIn('612 €', i['persp']['manca'])
        # con l'incasso medio dichiarato all'incontro la percentuale prevista si accende
        self.c.patch(self.base + '/dossier', headers=self.M, json={'campi': {'numeri.incasso': 8000}})
        i = ind()
        self.assertEqual(i['persp']['valore'], 36.4)          # 612 € su 8.000 € al mese senza IVA (1.679 € a settimana)
        self.assertIn('dichiarato', i['persp']['fonte'])

    def test_03_timbra_dal_tag_si_vede(self):
        r = self.c.post(f'/api/app/{self.codice}/timbra', json={'persona_id': self.gio, 'pin': '4321'})
        self.assertEqual(r.get_json()['azione'], 'inizio')
        self.assertIn('Giovanni R.', self.monitoring()[1]['in_servizio'])
        o = self.owner()
        self.assertIn('Giovanni R.', o['in_servizio'])
        self.assertTrue(next(p for p in o['squadra'] if p['nome'] == 'Giovanni R.')['in_servizio'])

    def test_04_turno_corretto_dal_consulente_fa_ore_e_costo(self):
        t = self.c.get(self.base + '/turni', headers=self.M).get_json()
        turno = (t.get('turni') if isinstance(t, dict) else t)[0]
        g = self.ieri.isoformat()
        r = self.c.patch(f"{self.base}/turni/{turno['id']}", headers=self.M, json={'inizio': g + 'T17:00', 'fine': g + 'T23:00'})
        self.assertEqual(r.status_code, 200, r.get_json())
        _, q, a = self.monitoring()
        self.assertEqual(q['personale']['ore'], 6.0)
        self.assertEqual(self.owner()['personale']['ore'], 6.0)
        self.assertEqual(next(p for p in self.owner()['squadra'] if p['nome'] == 'Giovanni R.')['ore'], 6.0)
        self.assertEqual(a['settimane'][-1]['ore'], 6.0)

    def test_05_chiusura_dal_tag_si_vede_subito(self):
        self.c.post(f'/api/app/{self.codice}/chiusura', json={'persona_id': self.gio, 'pin': '4321',
                    'voci': {'celle': True, 'gas': True, 'luci': True, 'cassa': True, 'porte': False}})
        for q in (self.monitoring()[1], self.owner()):
            self.assertEqual(q['chiusure']['stasera']['stato'], 'controlla')
            self.assertEqual(q['chiusure']['stasera']['manca'], ['porte'])
            self.assertEqual(q['chiusure']['stasera']['chi'], 'Giovanni R.')

    def test_06_cassa_caricata_fa_incasso(self):
        g = self.ieri.strftime('%d/%m/%Y')
        report = f'data;piatto;qta;incasso\n{g};MARGHERITA;40;360,00\n{g};TIRAMISU;10;60,00\n'.encode()
        r = self.c.post(self.base + '/vendite', headers=self.M, content_type='multipart/form-data', data={
            'file': (io.BytesIO(report), 'cassa.csv'), 'colonne': '{"data": 0, "voce": 1, "quantita": 2, "incasso": 3}'})
        self.assertEqual(r.status_code, 200, r.get_json())
        rie, q, a = self.monitoring()
        o = self.owner()
        self.assertEqual(q['incasso']['euro'], 420.0)
        self.assertEqual(o['incasso']['euro'], 420.0)
        self.assertEqual(rie['settimana']['incasso'], 420.0)
        self.assertEqual(q['lavoro']['ultima_vendita'], self.ieri.isoformat())
        self.assertEqual(o['lavoro']['ultima_vendita'], self.ieri.isoformat())
        self.assertIsNotNone(o['personale']['percento'])          # ora il costo del personale ha un incasso su cui stare
        # l'analisi delle vendite riconosce i piatti: nome pulito, ricetta proposta, niente da abbinare a mano
        self.assertTrue(any(p['nome'] == 'Margherita' for p in o['andamento']['piatti']))
        self.assertEqual(rie['voci_da_abbinare'], 0)
        self.assertEqual(rie['ricette'], 2)                       # Margherita e Tiramisù, proposte automatiche

    def test_07_fattura_caricata_fa_acquisti(self):
        xml = fattura_xml('FT-9', self.ieri.isoformat(), [('FIORDILATTE 3KG', 'PZ', '4.00', '36.00'), ('FARINA 00', 'KG', '25.00', '20.00')])
        r = self.c.post(self.base + '/fatture', headers=self.M, content_type='multipart/form-data',
                        data={'file': (io.BytesIO(xml), 'ft9.xml')})
        self.assertEqual(len(r.get_json()['importate']), 1)
        rie, q, _ = self.monitoring()
        o = self.owner()
        for w in (q['lavoro'], o['lavoro']):
            self.assertEqual(w['acquisti'], 56.0)
            self.assertEqual(w['fatture'], 1)
            self.assertEqual(w['da_collegare'], 2)
        self.assertEqual(rie['da_collegare'], 2)

    def test_08_prodotto_collegato_diventa_articolo(self):
        prima = self.monitoring()[1]['lavoro']['articoli']        # ci sono già quelli creati dalle ricette proposte
        chiave = self.c.get(self.base + '/da-collegare', headers=self.M).get_json()[0]['chiave']
        r = self.c.post(self.base + '/collega', headers=self.M, json={'chiave': chiave, 'fattore': 3,
                                                                     'articolo': {'nome': 'Fiordilatte', 'unita': 'kg'}})
        type(self).fior = r.get_json()['articolo']['id']
        rie, q, _ = self.monitoring()
        self.assertEqual(rie['da_collegare'], 1)
        # la scheda dell'ingrediente: in che ricette entra e quanto, l'ultima consegna con fornitore e prezzo
        sc = self.c.get(f'{self.base}/articoli/{self.fior}/scheda', headers=self.M).get_json()
        self.assertEqual([(x['nome'], x['per_porzione']) for x in sc['ricette']], [('Margherita', 0.12)])
        u = sc['ultima_consegna']
        self.assertEqual((u['fornitore'], u['documento'], u['quantita'], u['prezzo_unitario']), ('Latteria Esempio', 'fattura', 12.0, 3.0))
        self.assertAlmostEqual(sc['consumo_giorno'], 40 * 0.12 / 1, places=3)      # 40 margherite ieri, un giorno di cassa
        self.assertEqual(self.c.get(f'{self.base}/articoli/999999/scheda', headers=self.M).status_code, 404)
        # il fiordilatte della fattura prende il posto di quello stimato dal catalogo, che resta senza ricette ed esce
        self.assertEqual(q['lavoro']['articoli'], prima)
        self.assertEqual(self.owner()['lavoro']['articoli'], prima)
        nomi = [a['nome'] for a in self.c.get(self.base + '/articoli', headers=self.M).get_json()]
        self.assertIn('Fiordilatte', nomi)
        self.assertNotIn('Mozzarella fiordilatte', nomi)
        # la Margherita proposta ora usa il fiordilatte della fattura, col prezzo vero, non più quello stimato
        marg = next(r for r in self.c.get(self.base + '/ricette', headers=self.M).get_json() if r['nome'] == 'Margherita')
        self.assertIn(self.fior, [x['articolo_id'] for x in marg['righe']])

    def test_08b_la_fattura_muove_il_magazzino(self):
        mag = self.c.get(self.base + '/dossier', headers=self.D).get_json()['magazzino']
        fior = next(r for r in mag['giacenze']['righe'] if r['nome'] == 'Fiordilatte')
        # 4 pezzi da 3 kg a 3 €/kg entrati; le 40 margherite vendute ieri ne hanno usati 4,8 kg (0,12 a pizza)
        self.assertEqual((fior['entrate'], fior['stima'], fior['valore']), (12.0, 7.2, 21.6))
        self.assertEqual(mag['da_collegare']['prodotti'], 1)                                     # la farina aspetta
        self.assertEqual(mag['entrate'][0]['articolo'], 'Fiordilatte')
        # un'altra fattura dello stesso prodotto si collega da sola e fa salire la giacenza
        xml = fattura_xml('FT-10', self.ieri.isoformat(), [('FIORDILATTE 3KG', 'PZ', '2.00', '18.00')])
        self.c.post(self.base + '/fatture', headers=self.M, content_type='multipart/form-data', data={'file': (io.BytesIO(xml), 'ft10.xml')})
        mag = self.c.get(self.base + '/dossier', headers=self.D).get_json()['magazzino']
        self.assertEqual(next(r for r in mag['giacenze']['righe'] if r['nome'] == 'Fiordilatte')['stima'], 13.2)
        # un fattore sbagliato si vede: 1 pezzo = 0,001 kg fa un prezzo impossibile
        chiave = self.c.get(self.base + '/da-collegare', headers=self.M).get_json()[0]['chiave']
        self.c.post(self.base + '/collega', headers=self.M, json={'chiave': chiave, 'fattore': 0.001, 'articolo': {'nome': 'Farina', 'unita': 'kg'}})
        mag = self.c.get(self.base + '/dossier', headers=self.D).get_json()['magazzino']
        self.assertEqual([p['nome'] for p in mag['prezzi_strani']], ['Farina'])
        self.c.post(self.base + '/collega', headers=self.M, json={'chiave': chiave, 'fattore': 1, 'articolo_id': next(
            a['id'] for a in self.c.get(self.base + '/articoli', headers=self.M).get_json() if a['nome'] == 'Farina')})
        mag = self.c.get(self.base + '/dossier', headers=self.D).get_json()['magazzino']
        self.assertEqual(mag['prezzi_strani'], [])
        self.assertEqual(next(r for r in mag['giacenze']['righe'] if r['nome'] == 'Farina')['stima'], 15.0)   # 25 − 40 × 0,25

    def test_09_ricetta_nel_ricettario(self):
        self.c.post(self.base + '/ricette', headers=self.M, json={'nome': 'Margherita', 'prezzo': 9, 'righe': [
            {'articolo_id': self.fior, 'quantita': 0.12}]})
        rie, q, _ = self.monitoring()
        self.assertEqual(rie['ricette'], 2)                       # la sua Margherita prende il posto della proposta, non si raddoppia
        self.assertEqual(self.owner()['lavoro']['ricette'], 2)
        marg = next(r for r in self.c.get(self.base + '/ricette', headers=self.M).get_json() if r['nome'] == 'Margherita')
        self.assertEqual((marg['automatica'], marg['prezzo'], len(marg['righe'])), (False, 9, 1))

    def test_10_scarto_registrato(self):
        self.c.post(self.base + '/movimenti', headers=self.M, json={'articolo_id': self.fior, 'tipo': 'scarto',
                                                                    'quantita': 1, 'giorno': self.ieri.isoformat()})
        self.assertEqual(self.monitoring()[1]['lavoro']['scarti'], 1)
        o = self.owner()['lavoro']
        self.assertEqual(o['scarti'], 1)
        self.assertEqual(o['scarti_euro'], 3.0)                   # 1 kg a 36/12 = 3 €/kg

    def test_11_inventario_aperto_e_chiuso(self):
        i = self.c.post(self.base + '/inventari', headers=self.M, json={'giorno': self.ieri.isoformat()}).get_json()['id']
        self.assertEqual(self.owner()['lavoro']['inventario_aperto'], self.ieri.isoformat())
        self.c.patch(f'{self.base}/inventari/{i}', headers=self.M, json={'righe': {str(self.fior): 5}, 'chiuso': True})
        rie, q, _ = self.monitoring()
        self.assertEqual(rie['ultimo_inventario'], self.ieri.isoformat())
        o = self.owner()['lavoro']
        self.assertEqual(o['inventari'], 1)
        self.assertIsNone(o['inventario_aperto'])

    def test_12_obiettivo_cambiato(self):
        self.c.patch(self.base + '/impostazioni', headers=self.M, json={'obiettivo': 27})
        self.assertEqual(self.monitoring()[2]['obiettivo'], 27)
        self.assertEqual(self.owner()['andamento']['obiettivo'], 27)

    def test_12b_indicatori_in_monitoring(self):
        r = self.c.get(self.base + '/indicatori', headers=self.D)
        self.assertEqual(r.status_code, 200)
        ind = {i['id']: i for i in r.get_json()['indicatori']}
        self.assertEqual(ind['acq']['valore'], 19.4)            # 74 € di acquisti su 420 € di incasso (381,82 senza IVA)
        self.assertEqual(ind['eora']['valore'], 63.6)           # 381,82 € in 6 ore
        self.assertEqual(ind['pers']['valore'], 28.3)           # 6 ore × 18 €
        self.assertEqual(ind['spr']['valore'], 4.1)             # 3 € di scarti su 74 €
        self.assertEqual(ind['spr']['stato'], 'fuori')          # atteso 2,5% ± 1
        self.assertEqual(ind['cons']['valore'], 0)
        self.assertIsNone(ind['food']['valore'])
        self.assertIn('inventari', ind['food']['manca'])
        self.assertEqual(ind['ric']['valore'], 100.0)           # margherita e tiramisù abbinati dall'analisi delle vendite
        # il consulente cambia l'atteso dello spreco: Monitoring lo vede subito
        self.c.patch(self.base + '/impostazioni', headers=self.M, json={'parametri': {'spr': {'atteso': 6, 'toll': 1}}})
        ind = {i['id']: i for i in self.c.get(self.base + '/indicatori', headers=self.D).get_json()['indicatori']}
        self.assertEqual((ind['spr']['atteso'], ind['spr']['stato']), (6, 'buono'))
        rie = next(x for x in self.c.get('/api/rete/riepilogo', headers=self.D).get_json() if x['id'] == self.lid)
        self.assertIn('fuori', rie['indicatori']['conta'])

    def test_12c_dossier_riempito_da_managing(self):
        r = self.c.patch(self.base + '/dossier', headers=self.M, json={
            'campi': {'locale.coperti': 48, 'locale.indirizzo': 'Via di Prova 1', 'dossier.pacchetto': 'Mantenimento',
                      'dossier.canone': 450, 'dossier.prossima_visita': '2026-10-15', 'dossier.titolare': 'Paola Mera',
                      'numeri.cassa_marca': 'SumUp'},
            'dotazione': {'sonde': {'stato': 'da sistemare', 'nota': 'Due celle, sonde ordinate'}},
            'indicatori': {'spr': {'nota': 'Il pane avanza il lunedì', 'mossa': 'Mezzo impasto il lunedì'}}})
        self.assertEqual(r.status_code, 200, r.get_json())
        e = self.c.post(self.base + '/storia', headers=self.M, json={'giorno': self.ieri.isoformat(), 'tipo': 'visita',
                                                                    'testo': 'Prima visita: inventario e ricettario', 'chiave': True})
        self.assertEqual(e.status_code, 201)
        # Monitoring legge tutto dal dossier
        d = self.c.get(self.base + '/dossier', headers=self.D).get_json()
        loc = d['locale']
        self.assertEqual((loc['coperti'], loc['pacchetto'], loc['canone'], loc['cassa']), (48, 'Mantenimento', 450, 'SumUp'))
        self.assertEqual((loc['titolare'], loc['prossima_visita'], loc['ultima_visita']), ('Paola Mera', '2026-10-15', self.ieri.isoformat()))
        son = next(x for x in d['dotazione'] if x['id'] == 'sonde')
        self.assertEqual((son['stato'], son['descrizione'], son['automatico']), ('da sistemare', 'Due celle, sonde ordinate', False))
        cassa = next(x for x in d['dotazione'] if x['id'] == 'cassa')
        self.assertEqual(cassa['stato'], 'attivo')                          # le vendite ci sono: si vede dai dati
        spr = next(i for i in d['indicatori'] if i['id'] == 'spr')
        self.assertEqual((spr['nota'], spr['mossa']), ('Il pane avanza il lunedì', 'Mezzo impasto il lunedì'))
        self.assertTrue(any(e['testo'].startswith('Prima visita') for e in d['storia']))
        self.assertTrue(any(e['auto'] and e['tipo'] == 'Ingresso nella rete' for e in d['storia']))
        self.assertTrue(d['personale']['persone'])
        self.assertIn('pers', {i['id'] for i in d['indicatori'] if i['misure']})
        # la direzione non modifica niente
        self.assertEqual(self.c.patch(self.base + '/dossier', headers=self.D, json={'campi': {'locale.coperti': 1}}).status_code, 403)
        self.assertEqual(self.c.post(self.base + '/storia', headers=self.D, json={'testo': 'x'}).status_code, 403)
        # un campo sconosciuto non passa
        self.assertEqual(self.c.patch(self.base + '/dossier', headers=self.M, json={'campi': {'locale.nome': 'x'}}).status_code, 400)

    def test_13_persona_tolta_sparisce(self):
        self.c.delete(f'{self.base}/persone/{self.gio}', headers=self.M)   # ha dei turni: si disattiva
        self.assertNotIn('Giovanni R.', [p['nome'] for p in self.monitoring()[1]['squadra']])
        o = self.owner()
        self.assertNotIn('Giovanni R.', [p['nome'] for p in o['squadra']])
        self.assertEqual(o['personale']['ore'], 6.0)              # le sue ore restano nel costo del personale

    def test_15_report_di_periodo_sumup(self):
        """Il report prodotti di SumUp: nessuna data, il periodo nel nome del file, tutte le colonne.
        Su un locale nuovo, così la cassa giorno per giorno dei test sopra non c'entra."""
        import json
        c, M = self.c, self.M
        lid = c.post('/api/rete/locali', json={'nome': 'Bistrot SumUp'}, headers=ADMIN).get_json()['id']
        base = f'/api/rete/locali/{lid}'
        c.post(base + '/persone', headers=M, json={'nome': 'Rita', 'ruolo': 'titolare', 'email': 'rita@sumup.prova', 'password': 'quadro2026'})
        O = {'Authorization': 'Bearer ' + c.post('/api/app/login', json={'email': 'rita@sumup.prova', 'password': 'quadro2026'}).get_json()['token']}
        testa = '"Product";"Currency";"Unit of measure";"Quantity";"Purchase Price excl Tax";"Discounts";"Sales incl Tax";"Sales excl Tax";"Tax Amount";"Gross Margin"\r\n'
        csv_ = (testa + '"Carbonara";"EUR";"";"100";"3,00";"10,00";"1100,00";"1000,00";"100,00";"700,00"\r\n'
                '"Carbonara";"EUR";"";"-2";"0,00";"0,00";"-22,00";"-20,00";"-2,00";"-20,00"\r\n'
                '"Spritz";"EUR";"";"50";"0,00";"0,00";"366,00";"300,00";"66,00";"300,00"\r\n').encode()
        nome = 'product-sales-report-2026-01-01_2026-03-31.csv'

        def carica(dati, n=nome, **extra):
            return c.post(base + '/vendite', headers=M, content_type='multipart/form-data',
                          data={'file': (io.BytesIO(dati), n), **extra})

        a = c.post(base + '/vendite/anteprima', headers=M, content_type='multipart/form-data',
                   data={'file': (io.BytesIO(csv_), nome)}).get_json()
        self.assertEqual(a['periodo'], {'dal': '2026-01-01', 'al': '2026-03-31'})
        col = a['proposta']
        self.assertEqual({k: a['intestazioni'][v] for k, v in col.items()}, {
            'voce': 'Product', 'quantita': 'Quantity', 'costo': 'Purchase Price excl Tax', 'sconti': 'Discounts',
            'incasso': 'Sales incl Tax', 'netto': 'Sales excl Tax', 'iva': 'Tax Amount', 'margine': 'Gross Margin'})

        r = carica(csv_, colonne=json.dumps(col))
        self.assertEqual(r.status_code, 200, r.get_json())
        x = r.get_json()
        self.assertTrue(x['periodo'])
        rep = x['report']
        self.assertEqual((rep['dal'], rep['al'], rep['giorni'], rep['voci']), ('2026-01-01', '2026-03-31', 90, 2))
        self.assertEqual((rep['quantita'], rep['incasso'], rep['netto'], rep['iva'], rep['sconti']), (148.0, 1444.0, 1280.0, 164.0, 10.0))
        self.assertEqual((rep['resi_quantita'], rep['resi_incasso']), (2.0, 22.0))
        self.assertEqual(rep['voci_con_costo'], 1)                      # lo Spritz non ha il prezzo d'acquisto in cassa
        self.assertEqual(x['voci_da_abbinare'], 0)                      # carbonara e spritz li riconosce l'analisi
        self.assertEqual(x['analisi']['quota_con_ricetta'], 100.0)

        # lo stesso periodo ricaricato sostituisce; uno che si accavalla si ferma
        self.assertEqual(carica(csv_, colonne=json.dumps(col)).get_json()['sostituito'], True)
        self.assertEqual(len(c.get(base + '/vendite/report', headers=M).get_json()), 1)
        r = carica(csv_, 'product-sales-report-2026-03-01_2026-04-30.csv', colonne=json.dumps(col))
        self.assertEqual(r.status_code, 409)
        self.assertIn('accavalla', r.get_json()['error'])
        # e un giorno singolo dentro il periodo pure: si conterebbe due volte
        r = carica(b'data;piatto;qta;incasso\n15/02/2026;CARBONARA;3;33\n', 'cassa.csv',
                   colonne='{"data": 0, "voce": 1, "quantita": 2, "incasso": 3}')
        self.assertEqual(r.status_code, 409)

        # Managing: le voci da abbinare comprendono quelle del report
        self.assertEqual({v['nome'] for v in c.get(base + '/voci', headers=M).get_json()}, {'Tonnarelli alla carbonara', 'Aperol spritz'})
        # Monitoring: sconti e storni, la cassa aggiornata al 31 marzo, le tabelle del report sotto l'incasso
        ind = {i['id']: i for i in c.get(base + '/indicatori', headers=self.D).get_json()['indicatori']}
        self.assertEqual(ind['sconti']['valore'], 0.7)                 # 10 € su 1454 € di venduto
        self.assertEqual(ind['storni']['valore'], 1.5)                 # 22 € su 1466 €
        self.assertIn('ultimo report', ind['sconti']['fonte'])
        self.assertEqual(ind['ric']['valore'], 100.0)                  # tutto abbinato dall'analisi delle vendite
        dos = c.get(base + '/dossier', headers=self.D).get_json()
        mis = {i['id']: i['misure'] for i in dos['indicatori']}
        titoli = [m['titolo'] for m in mis['inc']]
        self.assertIn('Report di cassa caricati', titoli)
        aliq = next(m for m in mis['inc'] if m['titolo'].startswith('Incasso per aliquota IVA'))
        self.assertEqual({r[0] for r in aliq['righe']}, {'10%', '22%'})
        self.assertTrue(any(t.startswith('Margine scritto in cassa') for t in titoli))
        self.assertEqual(mis['storni'][0]['righe'][0][0], 'Tonnarelli alla carbonara')
        rie = next(x for x in c.get('/api/rete/riepilogo', headers=self.D).get_json() if x['id'] == lid)
        self.assertEqual(rie['voci_da_abbinare'], 0)
        q = c.get(base + '/quadro', headers=self.D).get_json()
        self.assertEqual(q['lavoro']['ultima_vendita'], '2026-03-31')
        # Owner: cosa si vende, dicendo di quale periodo, e la cassa aggiornata
        o = c.get('/api/app/quadro', headers=O).get_json()
        self.assertEqual([p['nome'] for p in o['andamento']['piatti']], ['Tonnarelli alla carbonara', 'Aperol spritz'])
        self.assertIn('31 mar', o['andamento']['piatti_quando'])
        self.assertEqual(o['lavoro']['ultima_vendita'], '2026-03-31')
        # niente cassa recente: l'incasso non resta vuoto, è la media a settimana del report (1444 € in 90 giorni)
        self.assertEqual((ind['inc']['nome'], ind['inc']['valore']), ('Incasso medio a settimana', 112.0))
        self.assertIn('1 gen al 31 mar', ind['inc']['fonte'])
        self.assertIn('fatture', ind['acq']['manca'])                 # fatture e report di periodi diversi: niente numero finto
        self.assertEqual(o['incasso']['periodo']['sett_incasso'], 112.31)
        self.assertIn('1.444 €', o['frase'])

        # un report di una settimana intera fa l'incasso di quella settimana, in tutti e tre i portali
        fine = self.ieri
        inizio = fine - timedelta(days=6)
        r = carica(csv_, f'product-sales-report-{inizio}_{fine}.csv', colonne=json.dumps(col))
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(c.get(base + '/quadro', headers=self.D).get_json()['incasso']['euro'], 1444.0)
        o = c.get('/api/app/quadro', headers=O).get_json()
        self.assertEqual((o['incasso']['euro'], o['incasso']['periodo']), (1444.0, None))   # c'è la settimana vera: niente media
        rie = next(x for x in c.get('/api/rete/riepilogo', headers=self.D).get_json() if x['id'] == lid)
        self.assertEqual(rie['settimana']['incasso'], 1444.0)

        # tolto il report, sparisce dappertutto
        self.assertEqual(c.delete(f'{base}/vendite/report/1', headers=self.D).status_code, 403)   # Monitoring non toglie niente
        for rp in c.get(base + '/vendite/report', headers=M).get_json():
            self.assertEqual(c.delete(f'{base}/vendite/report/{rp["id"]}', headers=M).status_code, 200)
        self.assertEqual(c.get(base + '/quadro', headers=self.D).get_json()['incasso']['euro'], 0.0)
        self.assertIsNone(c.get('/api/app/quadro', headers=O).get_json()['lavoro']['ultima_vendita'])
        self.assertEqual(c.get(base + '/voci', headers=M).get_json(), [])

    def test_16_analisi_delle_vendite(self):
        """Il report si analizza da solo: doppioni uniti, categorie, ricette proposte, food cost delle ricette
        in Monitoring e nel quadro del titolare, anche senza inventari. Le scelte del consulente restano sue."""
        import json
        c, M = self.c, self.M
        lid = c.post('/api/rete/locali', json={'nome': 'Bar analisi'}, headers=ADMIN).get_json()['id']
        base = f'/api/rete/locali/{lid}'
        c.post(base + '/persone', headers=M, json={'nome': 'Ugo', 'ruolo': 'titolare', 'email': 'ugo@bar.prova', 'password': 'quadro2026'})
        O = {'Authorization': 'Bearer ' + c.post('/api/app/login', json={'email': 'ugo@bar.prova', 'password': 'quadro2026'}).get_json()['token']}
        righe = [('Caffe', 1000, 1300), ('Caffè', 900, 990), ('CAFFÈ', 100, 130), ('Moretti', 50, 200), ('MORETII', 10, 40),
                 ('Corona', 40, 160), ('Corona zero', 10, 40), ('Cappuccino', 300, 480), ('Varie', 20, 100), ('Coperto', 200, 300)]
        testa = '"Product";"Quantity";"Sales incl Tax";"Sales excl Tax";"Tax Amount"\n'
        csv_ = (testa + ''.join(f'"{n}";"{q}";"{e:.2f}";"{e / 1.1:.2f}";"{e - e / 1.1:.2f}"\n'.replace('.', ',') for n, q, e in righe)).encode()
        col = {'voce': 0, 'quantita': 1, 'incasso': 2, 'netto': 3, 'iva': 4}
        r = c.post(base + '/vendite', headers=M, content_type='multipart/form-data', data={
            'file': (io.BytesIO(csv_), 'product-sales-report-2026-01-01_2026-03-31.csv'), 'colonne': json.dumps(col)})
        self.assertEqual(r.status_code, 200, r.get_json())
        an = r.get_json()['analisi']
        voci = {v['nome']: v for v in c.get(base + '/voci', headers=M).get_json()}
        # i tre caffè sono uno, le due Moretti pure; Corona zero no (è un'altra birra)
        self.assertEqual(sorted(voci['Caffè']['uniti']), ['CAFFÈ', 'Caffe', 'Caffè'])
        self.assertEqual(voci['Caffè']['quantita'], 2000)
        self.assertEqual(voci['Moretti']['quantita'], 60)
        self.assertIn('Corona zero', voci)
        self.assertEqual((voci['Caffè']['categoria'], voci['Moretti']['categoria'], voci['Coperto']['ignorata']), ('Caffetteria', 'Birre', True))
        self.assertTrue(voci['Varie']['da_fare'])                       # voce generica: la chiarisce il consulente col locale
        self.assertTrue(any(x['voce'] == 'Varie' for x in an['da_chiarire']))
        # le ricette proposte: grammature del catalogo, ingredienti col prezzo stimato
        ric = {x['nome']: x for x in c.get(base + '/ricette', headers=M).get_json()}
        self.assertTrue(ric['Caffè']['automatica'])
        self.assertTrue(ric['Caffè']['in_vendita'])                    # corrisponde a un prodotto venduto: non è una «proposta»
        self.assertAlmostEqual(ric['Caffè']['costo'], 0.14, places=2)   # 7 g a 20 €/kg
        self.assertEqual(ric['Caffè']['prezzi_stimati'], ['Caffè in grani'])
        # Monitoring: food cost delle ricette senza inventari, con la stima detta; Owner lo vede uguale
        ind = {i['id']: i for i in c.get(base + '/indicatori', headers=self.D).get_json()['indicatori']}
        self.assertIsNotNone(ind['teo']['valore'])
        self.assertIn('stimati', ind['teo']['fonte'])
        self.assertGreater(ind['ric']['valore'], 90)
        mis = {i['id']: i['misure'] for i in c.get(base + '/dossier', headers=self.D).get_json()['indicatori']}
        self.assertTrue(any(m['titolo'].startswith('Incasso per categoria') for m in mis['inc']))
        self.assertTrue(any(m['titolo'].startswith('Food cost delle ricette sulle vendite') for m in mis['teo']))
        o = c.get('/api/app/quadro', headers=O).get_json()
        self.assertEqual(o['food_cost_ricette']['valore'], ind['teo']['valore'])
        self.assertEqual(o['andamento']['piatti'][0]['nome'], 'Caffè')
        # l'inventario segue il ricettario: si contano gli ingredienti delle ricette; tolta una ricetta,
        # gli ingredienti che servivano solo a lei escono (il latte del cappuccino), quelli condivisi restano (il caffè)
        arts = {a['nome']: a for a in c.get(base + '/articoli', headers=M).get_json()}
        self.assertEqual((arts['Caffè in grani']['in_ricette'], arts['Caffè in grani']['da_contare']), (2, True))
        self.assertEqual(arts['Latte intero']['in_ricette'], 1)
        # la scorta minima: consumo medio al giorno dalle vendite × ricette, per i giorni di scorta (3 di partenza).
        # Caffè: (2000 caffè × 7 g + 300 cappuccini × 7 g) in 90 giorni = 0,1789 kg al giorno → 0,537 kg per 3 giorni
        self.assertAlmostEqual(arts['Caffè in grani']['consumo_giorno'], 16.1 / 90, places=3)
        self.assertAlmostEqual(arts['Caffè in grani']['scorta_minima'], 16.1 / 90 * 3, places=2)
        c.patch(base + '/impostazioni', headers=M, json={'giorni_scorta': 7})
        arts = {a['nome']: a for a in c.get(base + '/articoli', headers=M).get_json()}
        self.assertAlmostEqual(arts['Caffè in grani']['scorta_minima'], 16.1 / 90 * 7, places=2)
        self.assertEqual(c.patch(base + '/impostazioni', headers=M, json={'giorni_scorta': 0}).status_code, 400)
        r = c.delete(f'{base}/ricette/{ric["Cappuccino"]["id"]}', headers=M).get_json()
        self.assertEqual(r['articoli_tolti'], 1)
        arts = {a['nome']: a for a in c.get(base + '/articoli', headers=M).get_json()}
        self.assertNotIn('Latte intero', arts)
        self.assertEqual(arts['Caffè in grani']['in_ricette'], 1)
        # il consulente corregge la ricetta del caffè: diventa sua e la prossima analisi non la tocca
        c.patch(f'{base}/ricette/{ric["Caffè"]["id"]}', headers=M, json={'righe': [{'articolo_id': ric['Caffè']['righe'][0]['articolo_id'], 'quantita': 0.008}]})
        c.post(base + '/vendite/analisi', headers=M, json={})
        caffe = next(x for x in c.get(base + '/ricette', headers=M).get_json() if x['nome'] == 'Caffè')
        self.assertEqual((caffe['automatica'], caffe['righe'][0]['quantita']), (False, 0.008))
        # e un abbinamento fatto a mano resta: «Varie» fuori dal food cost
        c.post(base + '/voci', headers=M, json={'voce': voci['Varie']['voce'], 'ignora': True})
        c.post(base + '/vendite/analisi', headers=M, json={})
        self.assertTrue(next(v for v in c.get(base + '/voci', headers=M).get_json() if v['nome'] == 'Varie')['ignorata'])
        self.assertEqual(c.post(base + '/vendite/analisi', headers=self.D, json={}).status_code, 403)   # Monitoring non rifà niente

    def test_17_domande_ai_dati_e_dati_mancanti(self):
        """La barra delle domande in Monitoring: risponde solo dal fascicolo del locale; senza chiave o credito lo dice.
        E i quadranti vuoti dicono quale dato manca, non «manca il dato»."""
        from unittest import mock
        c = self.c
        lid = c.post('/api/rete/locali', json={'nome': 'Locale domande'}, headers=ADMIN).get_json()['id']
        base = f'/api/rete/locali/{lid}'
        ind = {i['id']: i for i in c.get(base + '/indicatori', headers=self.D).get_json()['indicatori']}
        self.assertEqual(ind['food']['manca_breve'], '2 inventari chiusi')
        self.assertEqual(ind['inc']['manca_breve'], 'la cassa')
        self.assertEqual(ind['teo']['manca_breve'], 'il ricettario')
        self.assertEqual(ind['acq']['manca_breve'], 'le fatture dei fornitori')
        self.assertIsNone(ind['chk']['manca_breve'])                     # ha un valore: niente da dire
        csv_ = '"Product";"Quantity";"Sales incl Tax"\n"Caffè";"100";"120,00"\n'.encode()
        c.post(base + '/vendite', headers=self.M, content_type='multipart/form-data', data={
            'file': (io.BytesIO(csv_), 'product-sales-report-2026-02-01_2026-02-28.csv'), 'colonne': '{"voce": 0, "quantita": 1, "incasso": 2}'})

        self.assertEqual(c.get(base + '/domanda?q=', headers=self.D).status_code, 400)
        self.assertEqual(c.get(base + '/domanda?q=' + 'x' * 501, headers=self.D).status_code, 400)
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            r = c.get(base + '/domanda?q=quanto ho incassato', headers=self.D)
        self.assertEqual(r.status_code, 503)
        self.assertIn('chiave', r.get_json()['error'])

        visto = {}

        class Finto:
            def __init__(self, **kw):
                self.beta = self
                self.messages = self

            def create(self, **kw):
                visto.update(kw)
                blocco = mock.Mock(type='text', text='A febbraio hai incassato 120 € di caffè.')
                return mock.Mock(content=[blocco], stop_reason='end_turn', model=kw['model'],
                                 usage=mock.Mock(input_tokens=1000, cache_read_input_tokens=0, output_tokens=20))
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'finta'}), mock.patch('anthropic.Anthropic', Finto):
            r = c.get(base + '/domanda?q=quanto ho incassato di caffè?', headers=self.D)   # la direzione può chiedere
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn('120 €', r.get_json()['risposta'])
        sistema = visto['system'][0]['text'] + visto['system'][1]['text']
        self.assertIn('Usa solo il fascicolo', sistema)
        self.assertIn('Caffè | Caffetteria | 100 | 120.00 €', sistema)                  # i dati veri del locale
        self.assertIn('dal 2026-02-01 al 2026-02-28', sistema)
        self.assertEqual(visto['system'][1]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(visto['messages'], [{'role': 'user', 'content': 'quanto ho incassato di caffè?'}])

        import anthropic
        class SenzaCredito(Finto):
            def create(self, **kw):
                raise anthropic.BadRequestError('Your credit balance is too low', response=mock.Mock(status_code=400), body=None)
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'finta'}), mock.patch('anthropic.Anthropic', SenzaCredito):
            r = c.get(base + '/domanda?q=quanto ho incassato', headers=self.D)
        self.assertEqual(r.status_code, 503)
        self.assertIn('credito', r.get_json()['error'])

    def test_14_monitoring_non_modifica(self):
        for metodo, url, corpo in (('post', '/persone', {'nome': 'X', 'pin': '1111'}), ('post', '/ricette', {'nome': 'X'}),
                                   ('patch', '/impostazioni', {'obiettivo': 40}), ('post', '/inventari', {})):
            r = getattr(self.c, metodo)(self.base + url, headers=self.D, json=corpo)
            self.assertEqual(r.status_code, 403, f'{metodo} {url}')


if __name__ == '__main__':
    unittest.main()
