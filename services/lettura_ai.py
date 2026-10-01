"""Lettura con Claude dei documenti d'acquisto che non sono fatture elettroniche:
PDF (copie di cortesia, scansioni), foto di fatture e di bolle di consegna scritte a mano.

Entra un file, esce una lista di documenti nello stesso formato di services.fatturapa
(fornitore, numero, data, righe…) più le etichette che servono al consulente:
che documento è, di che fornitore, cosa ricontrollare. Un PDF può contenerne più
d'uno (una scansione di tutto il mese): si restituisce un documento per ognuno.

Il modello risponde con uno strumento a schema fisso, così la risposta è sempre JSON
valido; i numeri si ricontrollano qui (somme, date) e i dubbi finiscono in `controlla`.
"""
import base64
import io
import logging
import os
import re
from datetime import date, timedelta

from services.fatturapa import FatturaNonLeggibile, chiave_riga, normalizza

logger = logging.getLogger(__name__)

MODELLO = os.environ.get('RETE_MODELLO_LETTURA', 'claude-sonnet-5')
LATO_MAX = 2000                 # px: oltre non si legge meglio, si paga di più
MAX_PDF = 20 * 1024 * 1024
IMMAGINI = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif')

CATEGORIE = ['caffè e bar', 'pane e pasticceria', 'latte e latticini', 'salumi e formaggi', 'carne', 'pesce',
             'frutta e verdura', 'secco e dispensa', 'surgelati', 'vini e alcolici', 'bevande', 'pulizia e igiene',
             'imballi e monouso', 'servizi', 'altro']

SISTEMA = """Leggi documenti d'acquisto di un ristorante italiano (fatture, note di credito, documenti di trasporto/bolle di consegna, scontrini di cash & carry) e registrali con lo strumento `registra`.

Regole:
- Un documento per ogni documento distinto nel file: una scansione può contenerne più d'uno. Le pagine dello stesso documento sono un documento solo.
- Riporta i numeri come sono scritti, senza inventare. Un campo che non si legge resta null e lo segnali in `dubbi`.
- `prezzo_unitario` e `totale` di riga sono senza IVA. Se la fattura mostra solo prezzi IVA inclusa, scorporala e dillo in `dubbi`.
- Sconti di riga: il `totale` è quello già scontato.
- Le bolle (DDT) spesso non hanno prezzi: lascia null. Le quantità scritte a mano vanno lette con attenzione; se una cifra è ambigua, dillo in `dubbi`.
- `note_consegna` solo per problemi della consegna scritti sul documento (manca, rotto, ammaccato, reso, quantità diversa). Firme, visti e «ok» non sono note: lascia null.
- `dubbi` solo per cose che il consulente deve verificare: una cifra o una data poco leggibile, conti che non tornano, un documento intestato a un altro locale. Non segnalare quello che è normale: bolle senza prezzi, partita IVA del fornitore assente. Ignora del tutto diciture come «documento di prova» o «dati inventati», partite IVA a zero e intestatari di esempio: tratta il documento come vero e non scriverne nei dubbi.
- `cibo` vuol dire «entra nel food & beverage cost»: true per tutto quello che si mangia o si beve, bevande, vini, alcolici, caffè e acqua compresi. false solo per detersivi, carta, imballi, stoviglie, trasporto, servizi.
- Le date in formato AAAA-MM-GG. Gli anni a due cifre sono del 2000.
- Le righe di spese (trasporto, contributi) hanno quantità null.
- Se il file non è un documento d'acquisto, restituisci un documento di tipo `altro` e spiega in `dubbi` cosa è."""

STRUMENTO = {
    'name': 'registra',
    'description': 'Registra i documenti d\'acquisto trovati nel file.',
    'input_schema': {
        'type': 'object',
        'properties': {'documenti': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'tipo': {'type': 'string', 'enum': ['fattura', 'nota_credito', 'ddt', 'scontrino', 'altro']},
                'fornitore': {'type': ['string', 'null']},
                'piva_fornitore': {'type': ['string', 'null'], 'description': 'solo le cifre della partita IVA del fornitore'},
                'numero': {'type': ['string', 'null']},
                'data': {'type': ['string', 'null'], 'description': 'AAAA-MM-GG'},
                'destinatario': {'type': ['string', 'null']},
                'categoria': {'type': 'string', 'enum': CATEGORIE},
                'imponibile': {'type': ['number', 'null'], 'description': 'totale senza IVA del documento'},
                'totale_documento': {'type': ['number', 'null']},
                'riferimenti': {'type': ['string', 'null'], 'description': 'DDT o fatture citati, es. «DDT 3380 del 01/09»'},
                'righe': {'type': 'array', 'items': {'type': 'object', 'properties': {
                    'codice': {'type': ['string', 'null']},
                    'descrizione': {'type': 'string'},
                    'quantita': {'type': ['number', 'null']},
                    'unita': {'type': ['string', 'null']},
                    'prezzo_unitario': {'type': ['number', 'null']},
                    'totale': {'type': ['number', 'null']},
                    'iva': {'type': ['number', 'null']},
                    'cibo': {'type': 'boolean', 'description': 'true per cibo e bevande; false per non consumabili'},
                }, 'required': ['descrizione', 'quantita', 'totale', 'cibo']}},
                'note_consegna': {'type': ['string', 'null']},
                'leggibilita': {'type': 'string', 'enum': ['buona', 'discreta', 'scarsa']},
                'dubbi': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['tipo', 'fornitore', 'numero', 'data', 'categoria', 'righe', 'leggibilita', 'dubbi'],
        }}},
        'required': ['documenti'],
    },
}

TIPO = {'fattura': ('TD01', 1), 'nota_credito': ('TD04', -1), 'ddt': ('DDT', 0), 'scontrino': ('SCO', 1)}


def tipo_file(nome, dati):
    """'pdf' | 'immagine' | None, dai primi byte più che dal nome."""
    n = (nome or '').lower()
    if dati[:5] == b'%PDF-':
        return 'pdf'
    if dati[:3] == b'\xff\xd8\xff' or dati[:8] == b'\x89PNG\r\n\x1a\n' or dati[:4] == b'RIFF' or dati[:4] == b'GIF8':
        return 'immagine'
    if n.endswith(IMMAGINI) or dati[4:12] in (b'ftypheic', b'ftypheix', b'ftypmif1'):
        return 'immagine'
    return None


def xml_dentro_pdf(dati):
    """Molte copie di cortesia hanno la FatturaPA allegata dentro il PDF: se c'è, si usa quella."""
    import zlib
    m = re.search(rb'<\?xml[^>]*>\s*<[^>]*FatturaElettronica[\s\S]*?FatturaElettronica>', dati)
    if m:
        return m.group(0)
    for s in re.finditer(rb'stream\r?\n([\s\S]*?)\r?\nendstream', dati):
        try:
            x = zlib.decompress(s.group(1))
        except zlib.error:
            continue
        if b'FatturaElettronica' in x[:4000]:
            m = re.search(rb'<\?xml[\s\S]*FatturaElettronica>', x)
            if m:
                return m.group(0)
    return None


def _immagine(dati):
    """Raddrizza (EXIF), rimpicciolisce e passa in JPEG: le foto del telefono pesano 4-8 MB."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(dati))
        im = ImageOps.exif_transpose(im).convert('RGB')
    except Exception:
        raise FatturaNonLeggibile('Immagine non leggibile: salvala come JPG e riprova')
    im.thumbnail((LATO_MAX, LATO_MAX))
    out = io.BytesIO()
    im.save(out, 'JPEG', quality=85)
    return out.getvalue()


def chiama(contenuto):
    """Una chiamata al modello; in un punto solo, così i test la sostituiscono."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=90, max_retries=2)
    r = client.messages.create(
        model=MODELLO, max_tokens=8000, system=SISTEMA, tools=[STRUMENTO],
        tool_choice={'type': 'tool', 'name': 'registra'},
        messages=[{'role': 'user', 'content': contenuto}])
    for b in r.content:
        if b.type == 'tool_use':
            logger.info('Lettura AI: %s token in, %s out', r.usage.input_tokens, r.usage.output_tokens)
            return b.input
    raise FatturaNonLeggibile('Il documento non è stato letto: riprova')


def leggi(nome, dati):
    """Un PDF o una foto → i documenti grezzi come li ha letti il modello."""
    if not os.environ.get('ANTHROPIC_API_KEY'):
        raise FatturaNonLeggibile('Lettura di PDF e foto non attiva su questo server')
    t = tipo_file(nome, dati)
    if t == 'pdf':
        if len(dati) > MAX_PDF:
            raise FatturaNonLeggibile('PDF troppo grande (massimo 20 MB)')
        blocco = {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf',
                                                 'data': base64.b64encode(dati).decode()}}
    elif t == 'immagine':
        blocco = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                              'data': base64.b64encode(_immagine(dati)).decode()}}
    else:
        raise FatturaNonLeggibile('Tipo di file non riconosciuto: servono XML, p7m, ZIP, PDF o foto')
    try:
        out = chiama([blocco, {'type': 'text', 'text': f'File: {nome}'}])
    except FatturaNonLeggibile:
        raise
    except Exception as e:
        logger.error('Lettura AI fallita per %s: %s', nome, e)
        raise FatturaNonLeggibile('Lettura non riuscita adesso: riprova tra poco')
    return out.get('documenti') or []


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def converti(doc, fonte, oggi=None):
    """Un documento letto dal modello → il formato di fatturapa, più le etichette.
    Restituisce FatturaNonLeggibile se non è un documento d'acquisto usabile."""
    oggi = oggi or date.today()
    if doc.get('tipo') not in TIPO:
        return FatturaNonLeggibile('Non sembra un documento d\'acquisto' + (': ' + doc['dubbi'][0] if doc.get('dubbi') else ''))
    tipo, segno = TIPO[doc['tipo']]
    controlla = [d for d in (doc.get('dubbi') or []) if d][:6]
    d = _data(doc.get('data'))
    if not d:
        return FatturaNonLeggibile('Data del documento non leggibile')
    if d > oggi + timedelta(days=3) or d < oggi - timedelta(days=800):
        controlla.append(f'data insolita: {d.strftime("%d/%m/%Y")}')
    fornitore = (doc.get('fornitore') or '').strip()[:200] or 'Fornitore non letto'
    piva = re.sub(r'\D', '', doc.get('piva_fornitore') or '')[-11:] or None
    numero = (doc.get('numero') or '').strip()[:60]
    if not numero:
        numero = 's.n.'
        controlla.append('numero del documento non letto')

    righe = []
    for i, r in enumerate(doc.get('righe') or []):
        q, pu, tot = _num(r.get('quantita')), _num(r.get('prezzo_unitario')), _num(r.get('totale'))
        if tot is None and q is not None and pu is not None:
            tot = round(q * pu, 2)
        descr = (r.get('descrizione') or '').strip()[:500]
        if not descr:
            continue
        righe.append({'n': i + 1, 'codice': (r.get('codice') or '').strip()[:60] or None, 'descrizione': descr,
                      'quantita': q, 'unita': (r.get('unita') or '').strip()[:20] or None, 'totale': tot,
                      'cibo': r.get('cibo') is not False})
    if not righe:
        return FatturaNonLeggibile('Nessuna riga leggibile nel documento')

    somma = round(sum(r['totale'] or 0 for r in righe), 2)
    imponibile = _num(doc.get('imponibile'))
    if tipo != 'DDT' and imponibile is not None and somma and abs(somma - imponibile) > max(0.05, imponibile * 0.01):
        controlla.append(f'le righe sommano {somma:.2f} €, il totale imponibile è {imponibile:.2f} €'.replace('.', ','))
    if tipo != 'DDT' and any(r['quantita'] and r['totale'] is None for r in righe):
        controlla.append('righe senza importo')
    etichette = {'fonte': fonte, 'documento': doc['tipo'], 'categoria': doc.get('categoria') or 'altro',
                 'leggibilita': doc.get('leggibilita') or 'discreta', 'destinatario': doc.get('destinatario'),
                 'riferimenti': doc.get('riferimenti'), 'note': (doc.get('note_consegna') or '').strip() or None,
                 'controlla': controlla}
    return {'fornitore': fornitore, 'piva': piva, 'numero': numero, 'data': d, 'tipo': tipo, 'segno': segno,
            'imponibile': round(imponibile if imponibile is not None else somma, 2) if tipo != 'DDT' else None,
            'righe': righe, 'etichette': etichette, 'chiave_nome': normalizza(fornitore)}


def chiavi_righe(fattura):
    """La chiave degli alias con la P.IVA vera (o quella ritrovata dal nome del fornitore)."""
    for r in fattura['righe']:
        r['chiave'] = chiave_riga(fattura['piva'] or ('NOME:' + fattura['chiave_nome'][:40]), r['codice'], r['descrizione'])
