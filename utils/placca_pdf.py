"""PDF di stampa della Placca NFC — A6 (105×148 mm) + 3 mm di abbondanza.

Disegnato con ReportLab (vettoriale, font incorporati): WeasyPrint sul server
non ha le librerie di sistema Nix, mentre ReportLab gira già per le ricevute.

Versione Base: grafica SB Food, chiara o scura, con la texture di fondo.
Versioni personalizzate: colori, testo, logo e foto scelti dal cliente.
"""
import io
import os
import math
import logging

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(BASE_DIR, 'assets', 'fonts')
BG_DIR = os.path.join(BASE_DIR, 'assets', 'placche')

W, H = 105 * mm, 148 * mm          # formato finito
BLEED = 3 * mm                      # abbondanza per il taglio
PW, PH = W + 2 * BLEED, H + 2 * BLEED

SERIF, SERIF_IT, SANS = 'PlaccaSerif', 'PlaccaSerifIt', 'PlaccaSans'
_font_ok = None


def _registra_font():
    global _font_ok
    if _font_ok is not None:
        return _font_ok
    try:
        pdfmetrics.registerFont(TTFont(SERIF, os.path.join(FONT_DIR, 'Playfair-SemiBold.ttf')))
        pdfmetrics.registerFont(TTFont(SERIF_IT, os.path.join(FONT_DIR, 'Playfair-Italic.ttf')))
        pdfmetrics.registerFont(TTFont(SANS, os.path.join(FONT_DIR, 'Inter-SemiBold.ttf')))
        _font_ok = True
    except Exception as e:
        logger.warning('Font della placca non caricati (%s): uso i font base', e)
        _font_ok = False
    return _font_ok


def _f(serif=True, italic=False):
    """Nome del font da usare, con ripiego sui font standard del PDF."""
    if _registra_font():
        return SERIF_IT if italic else (SERIF if serif else SANS)
    if not serif:
        return 'Helvetica-Bold'
    return 'Times-Italic' if italic else 'Times-Bold'


def _luminanza(hex_col):
    try:
        h = (hex_col or '').lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255
    except Exception:
        return 0.0


def _colore(hex_col, default='#2b2d31'):
    try:
        return HexColor(hex_col)
    except Exception:
        return HexColor(default)


def _immagine_da_allegato(allegato):
    import base64
    if not allegato or not allegato.get('dati'):
        return None
    try:
        return ImageReader(io.BytesIO(base64.b64decode(allegato['dati'])))
    except Exception as e:
        logger.warning('Allegato non leggibile per il PDF: %s', e)
        return None


def _testo_spaziato(c, testo, y, font, size, spazio, colore):
    """Testo centrato con spaziatura fra le lettere. Ritorna la larghezza occupata."""
    larg = c.stringWidth(testo, font, size) + spazio * max(0, len(testo) - 1)
    # la spaziatura fra le lettere fa parte dello stato del PDF: va isolata,
    # altrimenti resta attiva sul testo disegnato dopo e lo allarga.
    c.saveState()
    t = c.beginText(PW / 2 - larg / 2, y)
    t.setFont(font, size)
    t.setCharSpace(spazio)
    t.setFillColor(colore)
    t.textOut(testo)
    c.drawText(t)
    c.restoreState()
    return larg


def _testo_centrato(c, testo, y, font, size, colore, leading=None,
                    larghezza=80 * mm, spazio=0.2):
    """Righe centrate con a capo automatico. Ritorna la y dell'ultima riga."""
    def largh(t):
        return c.stringWidth(t, font, size) + spazio * max(0, len(t) - 1)

    leading = leading or size * 1.22
    parole, righe, riga = testo.split(), [], ''
    for p in parole:
        prova = (riga + ' ' + p).strip()
        if largh(prova) <= larghezza:
            riga = prova
        else:
            if riga:
                righe.append(riga)
            riga = p
    if riga:
        righe.append(riga)
    for r in righe:
        _testo_spaziato(c, r, y, font, size, spazio, colore)
        y -= leading
    return y + leading


def _icona_tap(c, cx, cy, larghezza, colore):
    """Telefono con le onde NFC, in vettoriale."""
    s = larghezza / 100.0          # il disegno originale è su una griglia 100×92
    c.saveState()
    c.setStrokeColor(colore)
    c.setFillColor(colore)
    c.setLineWidth(4 * s)
    c.setLineCap(1)
    c.setLineJoin(1)
    x0 = cx - larghezza / 2
    y0 = cy - (92 * s) / 2

    def px(x, y):                  # dal sistema SVG (y in giù) a quello PDF (y in su)
        return x0 + x * s, y0 + (92 - y) * s

    bx, by = px(20, 84)
    c.roundRect(bx, by, 42 * s, 60 * s, 8 * s, stroke=1, fill=0)
    ax, ay = px(34, 32); bx2, by2 = px(48, 32)
    c.line(ax, ay, bx2, by2)
    hx, hy = px(41, 78)
    c.circle(hx, hy, 2.6 * s, stroke=0, fill=1)

    ox, oy = px(62, 28)            # centro delle onde: angolo alto-destra del telefono
    for raggio in (9, 17, 25):
        p = c.beginPath()
        r = raggio * s
        for i in range(25):
            ang = math.radians(-38 + (76 * i / 24))
            x, y = ox + r * math.cos(ang), oy + r * math.sin(ang)
            p.moveTo(x, y) if i == 0 else p.lineTo(x, y)
        c.drawPath(p, stroke=1, fill=0)
    c.restoreState()


def _arco_svg(c, path, cx, cy, r, a0, a1, conv, passi=48, muovi=True):
    """Campiona un arco in coordinate SVG (y verso il basso) e lo converte in PDF."""
    for i in range(passi + 1):
        a = math.radians(a0 + (a1 - a0) * i / passi)
        x, y = conv(cx + r * math.cos(a), cy + r * math.sin(a))
        if i == 0 and muovi:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)


def _icona_google(c, x, cy, altezza, colore):
    """Cerchio aperto + raggio orizzontale, come nella placca stampata."""
    s = altezza / 24.0
    conv = lambda sx, sy: (x - altezza / 2 + sx * s, cy + altezza / 2 - sy * s)
    c.setLineWidth(2.6 * s)
    p = c.beginPath()
    _arco_svg(c, p, 12, 12, 9, 0, 314, conv)
    c.drawPath(p, stroke=1, fill=0)
    x1, y1 = conv(21, 12)
    x2, y2 = conv(12.4, 12)
    c.line(x1, y1, x2, y2)


def _icona_tripadvisor(c, x, cy, altezza, colore):
    """Due occhi con pupilla, sorriso e sopracciglia."""
    s = altezza / 26.0
    larg = 44 * s
    conv = lambda sx, sy: (x - larg / 2 + sx * s, cy + altezza / 2 - sy * s)
    c.setLineWidth(2.4 * s)
    for cx in (13, 31):
        p = c.beginPath()
        _arco_svg(c, p, cx, 13, 8.5, 0, 360, conv)
        c.drawPath(p, stroke=1, fill=0)
        px, py = conv(cx, 13)
        c.circle(px, py, 2.8 * s, stroke=0, fill=1)
    p = c.beginPath()                                   # sorriso
    for pt in ((18.5, 19), (22, 22.5), (25.5, 19)):
        xx, yy = conv(*pt)
        p.moveTo(xx, yy) if pt[0] == 18.5 else p.lineTo(xx, yy)
    c.drawPath(p, stroke=1, fill=0)
    for x0, y0, x1c, y1c, x2c, y2c, x3, y3 in ((6, 6, 9, 3, 12, 3, 14, 5),
                                               (38, 6, 35, 3, 32, 3, 30, 5)):
        p = c.beginPath()
        p.moveTo(*conv(x0, y0))
        p.curveTo(*conv(x1c, y1c), *conv(x2c, y2c), *conv(x3, y3))
        c.drawPath(p, stroke=1, fill=0)


def _icona_thefork(c, x, cy, altezza, colore):
    """Forchetta a tre rebbi con il gambo lungo."""
    s = altezza / 24.0
    conv = lambda sx, sy: (x - altezza / 2 + sx * s, cy + altezza / 2 - sy * s)
    c.setLineWidth(2.2 * s)
    for rebbio in (8, 12, 16):
        c.line(*conv(rebbio, 3), *conv(rebbio, 9))
    p = c.beginPath()                                    # curva che unisce i rebbi
    p.moveTo(*conv(8, 9))
    p.curveTo(*conv(8, 13), *conv(16, 13), *conv(16, 9))
    c.drawPath(p, stroke=1, fill=0)
    c.line(*conv(12, 9), *conv(12, 21))


def _icone_portali(c, tipi, cy, colore, badge=None):
    """Riga dei portali (con l'eventuale badge del menù), come nell'anteprima."""
    if not tipi:
        return
    ALT = {'google': 6.2 * mm, 'tripadvisor': 5 * mm, 'thefork': 6.8 * mm}
    LARG = {'google': 6.2 * mm, 'tripadvisor': 8.5 * mm, 'thefork': 6.8 * mm}
    gap = 6 * mm
    larg_badge = 0
    if badge:
        larg_badge = (c.stringWidth(badge, _f(False), 5) + 1.6 * max(0, len(badge) - 1)) + 4 * mm
    totale = sum(LARG[t] for t in tipi) + gap * (len(tipi) - 1) + (gap + larg_badge if badge else 0)
    x = PW / 2 - totale / 2
    c.saveState()
    c.setStrokeColor(colore)
    c.setFillColor(colore)
    c.setLineCap(1)
    c.setLineJoin(1)
    for t in tipi:
        centro = x + LARG[t] / 2
        if t == 'google':
            _icona_google(c, centro, cy, ALT[t], colore)
        elif t == 'tripadvisor':
            _icona_tripadvisor(c, centro, cy, ALT[t], colore)
        else:
            _icona_thefork(c, centro, cy, ALT[t], colore)
        x += LARG[t] + gap
    if badge:
        c.setLineWidth(0.4)
        c.rect(x, cy - 2.2 * mm, larg_badge, 4.4 * mm, stroke=1, fill=0)
        t = c.beginText(x + 2 * mm, cy - 0.6 * mm)
        t.setFont(_f(False), 5)
        t.setCharSpace(1.6)
        t.setFillColor(colore)
        t.textOut(badge)
        c.drawText(t)
    c.restoreState()


def _firma(c, testo, y, colore):
    """Nome fra due trattini, come la firma della placca stampata."""
    font, size, spazio = _f(False), 6.8, 2.4
    c.saveState()
    testo = (testo or '').upper()
    larg = _testo_spaziato(c, testo, y, font, size, spazio, colore)
    c.setStrokeColor(colore)
    c.setStrokeAlpha(0.7)
    c.setLineWidth(0.5)
    ymid = y + size * 0.32
    c.line(PW / 2 - larg / 2 - 3 * mm - 7 * mm, ymid, PW / 2 - larg / 2 - 3 * mm, ymid)
    c.line(PW / 2 + larg / 2 + 3 * mm, ymid, PW / 2 + larg / 2 + 3 * mm + 7 * mm, ymid)
    c.restoreState()


def _sfondo_base(chiara):
    f = os.path.join(BG_DIR, 'bg-chiara.jpg' if chiara else 'bg-scura.jpg')
    if os.path.exists(f):
        try:
            return ImageReader(f)
        except Exception:
            return None
    return None


def _velo_gradiente(c, colori, stop=(0.0, 0.45, 1.0), bande=140):
    """Sfumatura verticale semitrasparente sopra l'immagine di fondo.

    ReportLab ignora l'alpha nei gradienti, quindi la sfumatura è composta da
    bande sottili: a 140 bande su 154 mm il passaggio è continuo alla vista.
    """
    def interpola(t):
        for i in range(len(stop) - 1):
            if t <= stop[i + 1] or i == len(stop) - 2:
                a, b = colori[i], colori[i + 1]
                k = 0 if stop[i + 1] == stop[i] else (t - stop[i]) / (stop[i + 1] - stop[i])
                k = min(max(k, 0), 1)
                return Color(a.red + (b.red - a.red) * k,
                             a.green + (b.green - a.green) * k,
                             a.blue + (b.blue - a.blue) * k,
                             a.alpha + (b.alpha - a.alpha) * k)
        return colori[-1]

    c.saveState()
    h = PH / bande
    for i in range(bande):
        t = (i + 0.5) / bande                 # 0 = alto, 1 = basso, come nel CSS
        col = interpola(t)
        c.setFillColor(col)
        c.setFillAlpha(col.alpha)
        c.rect(0, PH - (i + 1) * h, PW, h + 0.4, stroke=0, fill=1)
    c.setFillAlpha(1)
    c.restoreState()


def genera_pdf(ordine):
    """Ritorna i byte del PDF pronto per il tipografo."""
    _registra_font()
    alle = ordine.allegati or {}
    base = ordine.tier == 'base'

    if base:
        chiara = (ordine.variante or 'scura') == 'chiara'
        sfondo = HexColor('#f5f2ee' if chiara else '#2b2d31')
        inchiostro = HexColor('#2b2d31' if chiara else '#f5f2ee')
        accento = HexColor('#c4622d')
        texture, foto = _sfondo_base(chiara), None
        # stessi tre passaggi del linear-gradient(180deg, ...) del file di stampa
        velo = ([Color(249/255, 246/255, 241/255, .28), Color(246/255, 242/255, 236/255, .24),
                 Color(243/255, 238/255, 231/255, .45)] if chiara else
                [Color(28/255, 29/255, 33/255, .30), Color(24/255, 25/255, 29/255, .26),
                 Color(20/255, 21/255, 25/255, .48)])
        titolo = 'Avvicina il telefono per lasciare una recensione'
        nome = 'SB Food Consulting'
        logo = None
        portali = ['google', 'tripadvisor', 'thefork']
    else:
        sfondo = _colore(ordine.colore_sfondo, '#2b2d31')
        accento = _colore(ordine.colore_primario, '#c4622d')
        chiaro = _luminanza(ordine.colore_sfondo or '#2b2d31') > 0.6
        inchiostro = HexColor('#2b2d31' if chiaro else '#f5f2ee')
        texture = None
        foto = _immagine_da_allegato(alle.get('foto'))
        velo = [Color(sfondo.red, sfondo.green, sfondo.blue, a) for a in (.74, .78, .86)]
        titolo = ordine.testo_placca or 'Avvicina il telefono per lasciare una recensione'
        nome = ordine.nome_locale or ''
        logo = _immagine_da_allegato(alle.get('logo'))
        portali = [t for t, u in (('google', ordine.link_google),
                                  ('tripadvisor', ordine.link_tripadvisor),
                                  ('thefork', ordine.link_thefork)) if u] or ['google']

    buf = io.BytesIO()
    # initialFontName evita che il PDF dichiari Helvetica senza mai usarla:
    # un font non incorporato fa scattare i controlli di preflight in tipografia.
    try:
        c = canvas.Canvas(buf, pagesize=(PW, PH), initialFontName=_f(True), initialFontSize=10)
    except TypeError:
        c = canvas.Canvas(buf, pagesize=(PW, PH))
    c.setTitle(f'Placca NFC — {ordine.nome_locale}')

    # fondo al vivo (copre anche l'abbondanza)
    c.setFillColor(sfondo)
    c.rect(0, 0, PW, PH, stroke=0, fill=1)
    immagine = texture or foto
    if immagine:
        try:
            # "cover": riempie tutto il formato senza deformare, ritagliando l'eccesso
            iw, ih = immagine.getSize()
            scala = max(PW / iw, PH / ih)
            dw, dh = iw * scala, ih * scala
            c.saveState()
            path = c.beginPath()
            path.rect(0, 0, PW, PH)
            c.clipPath(path, stroke=0, fill=0)
            c.drawImage(immagine, (PW - dw) / 2, (PH - dh) / 2, dw, dh, mask='auto')
            c.restoreState()
            _velo_gradiente(c, velo)
        except Exception as e:
            logger.warning('Immagine di fondo non applicata: %s', e)

    # cornice: 6,5 mm dai lati e dal fondo, 7 mm dall'alto — quote del file di stampa,
    # misurate dal bordo del foglio (abbondanza inclusa), non dal formato finito
    c.setStrokeColor(accento)
    c.setLineWidth(0.5)
    c.rect(6.5 * mm, 6.5 * mm, PW - 13 * mm, PH - 13.5 * mm, stroke=1, fill=0)

    # riga di benvenuto
    c.saveState()
    c.setFillAlpha(0.9)
    _testo_spaziato(c, 'È stato un piacere averti con noi', PH - BLEED - 15.05 * mm,
                    _f(True, True), 10.5, 0.2, inchiostro)
    c.restoreState()

    # blocco centrale: icona, etichetta, titolo, ringraziamento
    _icona_tap(c, PW / 2, PH - BLEED - 35.9 * mm, 24 * mm, accento)
    _testo_spaziato(c, 'APPOGGIA QUI', PH - BLEED - 51.85 * mm, _f(False), 5, 2.0, accento)

    size = 23 if len(titolo) <= 52 else (19 if len(titolo) <= 78 else 16)
    y = _testo_centrato(c, titolo, PH - BLEED - 66.6 * mm, _f(True), size, inchiostro,
                        leading=size * 1.2, larghezza=80 * mm)
    # il ringraziamento non deve mai scendere sul piede, anche con titoli lunghi
    minimo = BLEED + 31 * mm
    _testo_spaziato(c, 'Grazie per il tuo feedback!', max(y - 19.0 * mm, minimo),
                    _f(True, True), 12.5, 0.2, accento)

    # piede: logo, portali (con l'eventuale badge menù), firma fra i trattini
    _firma(c, nome, BLEED + 15.4 * mm, accento)

    badge = 'MENÙ' if ordine.tier == 'personalizzata-menu' else None
    _icone_portali(c, portali, BLEED + 26.05 * mm, accento, badge=badge)
    y_sopra = BLEED + 32 * mm

    if logo:
        try:
            lw, lh = logo.getSize()
            scala = min(40 * mm / lw, 12 * mm / lh)
            c.drawImage(logo, PW / 2 - (lw * scala) / 2, y_sopra,
                        lw * scala, lh * scala, mask='auto')
        except Exception as e:
            logger.warning('Logo non inserito nel PDF: %s', e)

    c.showPage()
    c.save()
    return buf.getvalue()
