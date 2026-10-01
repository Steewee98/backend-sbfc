"""Lettura delle fatture elettroniche italiane (FatturaPA, tracciato 1.2.x).

Entra un file come lo scarica il ristoratore dal cassetto fiscale o dal
programma del commercialista: XML semplice, XML firmato (.p7m, anche in
base64) o uno ZIP che ne contiene tanti. Esce, per ogni fattura, fornitore,
numero, data e le righe con quantità e prezzo.

Niente dipendenze: la busta .p7m si apre con un piccolo lettore DER/BER
(sui server Railway non è garantito il comando openssl) e l'XML si legge con
la libreria standard, che dalla 3.7 non espande le entità esterne.
"""
import base64
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

MAX_XML = 5 * 1024 * 1024          # una fattura vera sta sotto i 200 KB
MAX_FILE_ZIP = 200                  # fatture per ZIP


class FatturaNonLeggibile(ValueError):
    pass


# ── la busta firmata (.p7m): CMS SignedData, il contenuto è l'XML ──

def _tlv(b, i):
    """Un elemento BER a partire da i: (tag, costruito, inizio_valore, fine_valore, fine)."""
    tag = b[i]; i += 1
    if tag & 0x1f == 0x1f:                      # tag su più byte
        while b[i] & 0x80:
            i += 1
        i += 1
    cost = bool(tag & 0x20)
    ln = b[i]; i += 1
    if ln == 0x80:                              # lunghezza indefinita: fino a 00 00
        j = i
        while not (b[j] == 0 and b[j + 1] == 0):
            j = _tlv(b, j)[4]
        return tag, cost, i, j, j + 2
    if ln & 0x80:
        n = ln & 0x7f
        ln = int.from_bytes(b[i:i + n], 'big'); i += n
    return tag, cost, i, i + ln, i + ln


def _figli(b, ini, fine):
    out, i = [], ini
    while i < fine:
        t = _tlv(b, i)
        out.append(t)
        i = t[4]
    return out


def _ottetti(b, t):
    """Il contenuto di un OCTET STRING, anche spezzato in pezzi (BER costruito)."""
    tag, cost, ini, fine, _ = t
    if not cost:
        return b[ini:fine]
    return b''.join(_ottetti(b, f) for f in _figli(b, ini, fine))


def apri_p7m(dati):
    if dati[:3] in (b'MII', b'MIA') or dati[:4] == b'MIAG':
        try:
            dati = base64.b64decode(dati, validate=False)
        except Exception:
            pass
    try:
        ci = _tlv(dati, 0)                                   # ContentInfo
        _, sd_wrap = _figli(dati, ci[2], ci[3])[:2]          # OID, [0]
        sd = _figli(dati, sd_wrap[2], sd_wrap[3])[0]         # SignedData
        encap = _figli(dati, sd[2], sd[3])[2]                # version, digestAlgs, encapContentInfo
        econt = _figli(dati, encap[2], encap[3])[1]          # eContentType, [0]
        return _ottetti(dati, _figli(dati, econt[2], econt[3])[0])
    except Exception:
        # ultima spiaggia: l'XML è quasi sempre leggibile in chiaro dentro la busta
        m = re.search(rb'<\?xml.*?FatturaElettronica>', dati, re.S)
        if m:
            return m.group(0)
        raise FatturaNonLeggibile('File firmato (.p7m) non leggibile: carica la versione XML')


# ── l'XML ──

def _loc(tag):
    return tag.rsplit('}', 1)[-1]


def _trova(el, percorso):
    """Primo discendente lungo un percorso di nomi, ignorando i namespace."""
    cur = [el]
    for nome in percorso.split('/'):
        cur = [c for p in cur for c in p if _loc(c.tag) == nome]
        if not cur:
            return None
    return cur[0]


def _testo(el, percorso, n=None):
    x = _trova(el, percorso)
    t = (x.text or '').strip() if x is not None else ''
    return t[:n] if n else t


def _num(s):
    try:
        return float(s.replace(',', '.')) if s else None
    except ValueError:
        return None


def normalizza(descrizione):
    """Toglie da una descrizione quello che cambia da una consegna all'altra
    (lotti, scadenze, date), così la stessa merce ha sempre la stessa chiave."""
    d = (descrizione or '').upper()
    d = re.sub(r'\b(LOTTO|LOT|L\.|SCAD\.?|SCADENZA|TMC|DDT|RIF\.?)\s*[:.]?\s*[\w/.\-]+', ' ', d)
    d = re.sub(r'\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b', ' ', d)
    d = re.sub(r'[^\w,.%]+', ' ', d)
    return re.sub(r'\s+', ' ', d).strip()[:250]


def chiave_riga(piva, codice, descrizione):
    base = (codice or '').strip().upper() or normalizza(descrizione)
    return f"{(piva or '').strip().upper()}|{base}"[:320]


def leggi_xml(xml_bytes):
    """Una FatturaElettronica → lista di fatture (una per ogni corpo: i lotti ne hanno più d'uno)."""
    if len(xml_bytes) > MAX_XML:
        raise FatturaNonLeggibile('File troppo grande per essere una fattura')
    if b'<!ENTITY' in xml_bytes[:4096]:
        raise FatturaNonLeggibile('XML non ammesso')
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise FatturaNonLeggibile('Non è un XML valido')
    if _loc(root.tag) != 'FatturaElettronica':
        raise FatturaNonLeggibile('Non è una fattura elettronica (FatturaPA)')

    head = _trova(root, 'FatturaElettronicaHeader')
    ced = _trova(head, 'CedentePrestatore/DatiAnagrafici') if head is not None else None
    if ced is None:
        raise FatturaNonLeggibile('Manca il fornitore (CedentePrestatore)')
    piva = _testo(ced, 'IdFiscaleIVA/IdCodice', 30) or _testo(ced, 'CodiceFiscale', 30)
    nome = (_testo(ced, 'Anagrafica/Denominazione', 200)
            or ' '.join(x for x in (_testo(ced, 'Anagrafica/Nome'), _testo(ced, 'Anagrafica/Cognome')) if x)[:200])
    cliente_piva = _testo(head, 'CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA/IdCodice', 30)

    fatture = []
    for body in (c for c in root if _loc(c.tag) == 'FatturaElettronicaBody'):
        gen = _trova(body, 'DatiGenerali/DatiGeneraliDocumento')
        if gen is None:
            continue
        tipo = _testo(gen, 'TipoDocumento', 6)
        try:
            data = date.fromisoformat(_testo(gen, 'Data')[:10])
        except ValueError:
            raise FatturaNonLeggibile('Data della fattura non valida')
        numero = _testo(gen, 'Numero', 60)
        righe = []
        beni = _trova(body, 'DatiBeniServizi')
        for i, r in enumerate(c for c in (beni if beni is not None else []) if _loc(c.tag) == 'DettaglioLinee'):
            codice = _testo(r, 'CodiceArticolo/CodiceValore', 60)
            descr = _testo(r, 'Descrizione', 500)
            righe.append({
                'n': int(_testo(r, 'NumeroLinea') or i + 1),
                'codice': codice or None,
                'descrizione': descr,
                'chiave': chiave_riga(piva, codice, descr),
                'quantita': _num(_testo(r, 'Quantita')),
                'unita': _testo(r, 'UnitaMisura', 20) or None,
                'totale': _num(_testo(r, 'PrezzoTotale')),
            })
        imponibile = sum(_num(_testo(x, 'ImponibileImporto')) or 0
                         for x in (beni if beni is not None else []) if _loc(x.tag) == 'DatiRiepilogo')
        fatture.append({'fornitore': nome, 'piva': piva, 'cliente_piva': cliente_piva, 'numero': numero,
                        'data': data, 'tipo': tipo, 'segno': -1 if tipo in ('TD04', 'TD08') else 1,
                        'imponibile': round(imponibile, 2), 'righe': righe})
    if not fatture:
        raise FatturaNonLeggibile('Nessun documento dentro il file')
    return fatture


def leggi_file(nome, dati):
    """Un file caricato → [(nome_file, fattura | FatturaNonLeggibile)]. Gli ZIP si aprono."""
    nome_l = (nome or '').lower()
    if nome_l.endswith('.zip') or dati[:2] == b'PK':
        out = []
        try:
            z = zipfile.ZipFile(io.BytesIO(dati))
        except zipfile.BadZipFile:
            return [(nome, FatturaNonLeggibile('ZIP rovinato'))]
        voci = [i for i in z.infolist() if not i.is_dir() and re.search(r'\.(xml|p7m)$', i.filename, re.I)
                and not i.filename.split('/')[-1].startswith('._')]
        for info in voci[:MAX_FILE_ZIP]:
            if info.file_size > MAX_XML * 2:
                out.append((info.filename, FatturaNonLeggibile('File troppo grande')))
                continue
            out.extend(leggi_file(info.filename.split('/')[-1], z.read(info)))
        return out
    try:
        xml = apri_p7m(dati) if (nome_l.endswith('.p7m') or dati[:1] == b'\x30') else dati
        return [(nome, f) for f in leggi_xml(xml)]
    except FatturaNonLeggibile as e:
        return [(nome, e)]


# ── quanto dell'articolo c'è in una riga ──

_MISURA = re.compile(r'(?:(\d+)\s*[X×]\s*)?(\d+(?:[.,]\d+)?)\s*(KG|KG\.|G|GR|GR\.|L|LT|LT\.|ML|CL)\b')


def suggerisci_fattore(descrizione, unita_riga, unita_articolo):
    """Una proposta, che il consulente conferma: quante unità dell'articolo
    (kg, l, pz) ci sono in una unità della riga. None se non si capisce."""
    ur = (unita_riga or '').upper().rstrip('.')
    ua = (unita_articolo or 'kg').lower()
    if ua == 'kg' and ur in ('KG', 'KGM', 'KGS', 'CHILI'):
        return 1.0
    if ua == 'l' and ur in ('L', 'LT', 'LTR', 'LITRI'):
        return 1.0
    if ua == 'pz' and ur in ('PZ', 'NR', 'N', 'NUM', 'PEZZI', 'C62'):
        return 1.0
    d = (descrizione or '').upper()
    # la riga è un cartone o una confezione: quanti pezzi dentro («CT60», «CF 12», «X6»)
    conf = None
    if ur in ('CT', 'CF', 'CONF', 'CRT', 'CASSA', 'SC', 'BOX', 'COLLO', 'CS'):
        c = re.search(r'\b(?:CT|CF|CONF|CRT|CS|X)\s*(\d{1,4})\b', d)
        conf = int(c.group(1)) if c else None
        if ua == 'pz' and conf:
            return float(conf)
    m = _MISURA.search(d)
    if not m:
        return None
    pezzi = int(m.group(1)) if m.group(1) else (conf or 1)
    val = float(m.group(2).replace(',', '.'))
    um = m.group(3).rstrip('.')
    if ua == 'kg' and um in ('KG', 'G', 'GR'):
        return round(pezzi * (val if um == 'KG' else val / 1000), 4)
    if ua == 'l' and um in ('L', 'LT', 'ML', 'CL'):
        return round(pezzi * {'L': val, 'LT': val, 'ML': val / 1000, 'CL': val / 100}[um], 4)
    return None

