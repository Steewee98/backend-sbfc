"""Lettura dei report di vendita delle casse (CSV o Excel), qualunque marca.

Ogni cassa esporta a modo suo, ma il contenuto è sempre una tabella con
il nome del piatto, quante volte è stato venduto e spesso l'incasso e la
data. Il consulente abbina le colonne una volta; il locale se le ricorda.

Le casse più complete danno anche incasso senza IVA, IVA, sconti, prezzo
d'acquisto e margine (il «product sales report» di SumUp): si leggono tutte.
Un report senza la colonna della data copre un periodo intero, che SumUp
scrive nel nome del file (product-sales-report-2026-01-01_2026-09-22.csv).
"""
import csv
import io
import re
import unicodedata
from datetime import date, datetime

MAX_RIGHE = 50000

# in quest'ordine: i campi più precisi scelgono per primi, così «Tax Amount» non diventa
# l'incasso e «Purchase Price excl Tax» non diventa l'incasso senza IVA
PAROLE = {
    'voce': ('descrizione', 'prodotto', 'product', 'articolo', 'piatto', 'voce', 'nome', 'item', 'reparto'),
    'quantita': ('quantità', 'quantita', 'qta', 'q.tà', 'qtà', 'pezzi', 'venduti', 'n.', 'numero', 'qty', 'quantity'),
    'costo': ('purchase price', 'prezzo di acquisto', 'prezzo d\'acquisto', 'prezzo acquisto', 'costo'),
    'margine': ('gross margin', 'margin', 'margine'),
    'sconti': ('discount', 'sconti', 'sconto'),       # non «scont»: c'è la colonna «Scontrino»
    'iva': ('tax amount', 'importo iva', 'imposta', 'iva'),
    'netto': ('sales excl', 'excl tax', 'iva esclusa', 'senza iva', 'imponibile', 'netto'),
    'incasso': ('sales incl', 'incl tax', 'iva inclusa', 'iva compresa', 'totale', 'importo', 'incasso', 'valore',
                'fatturato', 'venduto €', 'vendite', 'total', 'amount', 'sales'),
    'data': ('data', 'giorno', 'date'),
}
# parole che escludono una colonna da quel campo («Totale IVA inclusa» non è l'IVA)
NON = {'iva': ('incl', 'compres', 'esclus', 'excl', 'senza', 'totale', 'vendit', 'sales')}
# i campi in più, oltre a voce, quantità, incasso e data
EXTRA = ('netto', 'iva', 'sconti', 'costo', 'margine')


class ReportNonLeggibile(ValueError):
    pass


def leggi_tabella(nome, dati):
    """→ (intestazioni, righe). Prima riga non vuota = intestazioni."""
    nome = (nome or '').lower()
    if nome.endswith(('.xlsx', '.xlsm')) or dati[:2] == b'PK':
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            righe = [list(r) for r, _ in zip(ws.iter_rows(values_only=True), range(MAX_RIGHE))]
        except Exception:
            raise ReportNonLeggibile('File Excel non leggibile: prova a salvarlo come CSV')
    elif nome.endswith('.xls'):
        raise ReportNonLeggibile('Il vecchio formato .xls non si legge: salvalo come .xlsx o CSV')
    else:
        testo = None
        for cod in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                testo = dati.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialetto = csv.Sniffer().sniff(testo[:4000], delimiters=';,\t|')
        except csv.Error:
            class dialetto(csv.excel):          # una sottoclasse: csv.excel non va modificato
                delimiter = ';' if testo[:4000].count(';') > testo[:4000].count(',') else ','
        righe = [r for r, _ in zip(csv.reader(io.StringIO(testo), dialetto), range(MAX_RIGHE))]
    righe = [r for r in righe if any(str(c or '').strip() for c in r)]
    if len(righe) < 2:
        raise ReportNonLeggibile('Il file non ha righe di vendita')
    # l'intestazione è la prima riga con almeno due celle di testo (alcune casse mettono un titolo sopra)
    for i, r in enumerate(righe[:15]):
        if sum(1 for c in r if isinstance(c, str) and c.strip() and not _numero(c)) >= 2:
            intest = [str(c or '').strip() for c in r]
            return intest, righe[i + 1:]
    raise ReportNonLeggibile('Non trovo la riga con i nomi delle colonne')


def proponi_colonne(intest):
    """Indovina quale colonna è cosa, dai nomi. Il consulente conferma."""
    out, usate = {}, set()
    for campo, parole in PAROLE.items():
        for i, h in enumerate(intest):
            hl = h.lower()
            if i not in usate and any(p == hl or p in hl for p in parole) and not any(n in hl for n in NON.get(campo, ())):
                out[campo] = i
                usate.add(i)
                break
    return out


def _numero(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r'[€\s]', '', str(v))
    if not re.fullmatch(r'-?[\d.,]+', s):
        return None
    if ',' in s and '.' in s:          # 1.234,50 oppure 1,234.50
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    elif s.count('.') > 1:
        s = s.replace('.', '')
    try:
        return float(s)
    except ValueError:
        return None


def _data(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or '').strip()[:10]
    for f in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d.%m.%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def normalizza_voce(v):
    """La chiave della voce: maiuscole, senza accenti, punteggiatura ed emoji, spazi semplici.
    «Caffè», «Caffe», «CAFFE'» e «caffè » sono la stessa voce; «0.5» e «0,5» pure («0 5»)."""
    s = ''.join(c for c in unicodedata.normalize('NFKD', str(v or '')) if not unicodedata.combining(c))
    s = re.sub(r'[^0-9A-Za-z]+', ' ', s)          # apostrofi tipografici, barre, emoji: uno spazio
    return re.sub(r'\s+', ' ', s).strip().upper()[:200]


def periodo_dal_nome(nome):
    """Il periodo scritto nel nome del file (SumUp: …-2026-01-01_2026-09-22.csv) → (dal, al) oppure None."""
    m = re.search(r'(\d{4}-\d{2}-\d{2})\D{1,3}(\d{4}-\d{2}-\d{2})', nome or '')
    if not m:
        return None
    try:
        dal, al = (datetime.strptime(x, '%Y-%m-%d').date() for x in m.groups())
    except ValueError:
        return None
    return (dal, al) if dal <= al else None


def estrai_vendite(righe, colonne, giorno_fisso=None):
    """→ {(giorno, voce): {quantita, incasso, netto, iva, sconti, costo, margine, resi_quantita, resi_incasso,
    originale}} sommando i doppioni. Le righe di totale e quelle senza quantità si saltano.
    Una riga con la quantità negativa è uno storno o un reso: si toglie dal venduto e si conta anche a parte."""
    iv, iq, ii, idt = (colonne.get(k) for k in ('voce', 'quantita', 'incasso', 'data'))
    if iv is None or iq is None:
        raise ReportNonLeggibile('Servono almeno le colonne del piatto e della quantità')
    if idt is None and not giorno_fisso:
        raise ReportNonLeggibile('Manca la data: scegli la colonna o il giorno del report')
    out, saltate = {}, 0
    for r in righe:
        cella = lambda i: r[i] if i is not None and i < len(r) else None
        voce = normalizza_voce(cella(iv))
        q = _numero(cella(iq))
        g = giorno_fisso or _data(cella(idt))
        if not voce or q is None or g is None or re.match(r'^(TOTALE|TOTAL|SUBTOTALE|TOT\.)', voce):
            saltate += 1
            continue
        k = (g, voce)
        x = out.setdefault(k, {'quantita': 0.0, 'incasso': None, **{e: None for e in EXTRA},
                               'resi_quantita': 0.0, 'resi_incasso': 0.0, '_nomi': {}})
        n = re.sub(r'\s+', ' ', str(cella(iv)).strip())[:200]
        x['_nomi'][n] = x['_nomi'].get(n, 0) + abs(q)
        x['quantita'] += q
        inc = _numero(cella(ii))
        if inc is not None:
            x['incasso'] = (x['incasso'] or 0) + inc
        for e in EXTRA:
            n = _numero(cella(colonne.get(e)))
            if n is not None:
                x[e] = (x[e] or 0) + n
        if q < 0:
            x['resi_quantita'] -= q
            x['resi_incasso'] -= min(inc or 0, 0)
    for x in out.values():                    # il nome scritto più spesso, e tutti i modi in cui la cassa lo scrive
        nomi = x.pop('_nomi')
        x['originale'] = max(nomi, key=nomi.get)
        x['nomi'] = ' · '.join(sorted(nomi))[:400] if len(nomi) > 1 else None
    return out, saltate
