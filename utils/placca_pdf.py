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


def _testo_centrato(c, testo, y, font, size, colore, leading=None, larghezza=80 * mm):
    """Scrive righe centrate mandando a capo sulla larghezza data. Ritorna la y finale."""
    c.setFont(font, size)
    c.setFillColor(colore)
    leading = leading or size * 1.22
    parole, righe, riga = testo.split(), [], ''
    for p in parole:
        prova = (riga + ' ' + p).strip()
        if c.stringWidth(prova, font, size) <= larghezza:
            riga = prova
        else:
            if riga:
                righe.append(riga)
            riga = p
    if riga:
        righe.append(riga)
    for r in righe:
        c.drawCentredString(PW / 2, y, r)
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


def _icone_portali(c, tipi, cy, colore):
    """Google, TripAdvisor e TheFork: segni sintetici coerenti con la placca."""
    if not tipi:
        return
    passo = 13 * mm
    x = PW / 2 - passo * (len(tipi) - 1) / 2
    c.saveState()
    c.setStrokeColor(colore)
    c.setFillColor(colore)
    c.setLineCap(1)
    for t in tipi:
        if t == 'google':
            c.setLineWidth(0.9 * mm)
            p = c.beginPath()
            for i in range(41):                     # cerchio aperto
                ang = math.radians(-20 + (330 * i / 40))
                r = 2.9 * mm
                xx, yy = x + r * math.cos(ang), cy + r * math.sin(ang)
                p.moveTo(xx, yy) if i == 0 else p.lineTo(xx, yy)
            c.drawPath(p, stroke=1, fill=0)
            c.line(x, cy, x + 2.9 * mm, cy)
        elif t == 'tripadvisor':
            c.setLineWidth(0.8 * mm)
            for dx in (-2.6 * mm, 2.6 * mm):
                c.circle(x + dx, cy, 2.5 * mm, stroke=1, fill=0)
                c.circle(x + dx, cy, 0.8 * mm, stroke=0, fill=1)
        else:                                        # thefork
            c.setLineWidth(0.7 * mm)
            for dx in (-1.4 * mm, 0, 1.4 * mm):
                c.line(x + dx, cy + 3.2 * mm, x + dx, cy + 0.6 * mm)
            c.line(x - 1.4 * mm, cy + 0.6 * mm, x + 1.4 * mm, cy + 0.6 * mm)
            c.line(x, cy + 0.6 * mm, x, cy - 3.4 * mm)
        x += passo
    c.restoreState()


def _sfondo_base(chiara):
    f = os.path.join(BG_DIR, 'bg-chiara.jpg' if chiara else 'bg-scura.jpg')
    if os.path.exists(f):
        try:
            return ImageReader(f)
        except Exception:
            return None
    return None


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
        velo = Color(1, 1, 1, 0.28) if chiara else Color(0.169, 0.176, 0.192, 0.55)
        titolo = 'Avvicina il telefono per lasciare una recensione'
        nome = 'SB FOOD CONSULTING'
        logo = None
        portali = ['google', 'tripadvisor', 'thefork']
    else:
        sfondo = _colore(ordine.colore_sfondo, '#2b2d31')
        accento = _colore(ordine.colore_primario, '#c4622d')
        chiaro = _luminanza(ordine.colore_sfondo or '#2b2d31') > 0.6
        inchiostro = HexColor('#2b2d31' if chiaro else '#f5f2ee')
        texture = None
        foto = _immagine_da_allegato(alle.get('foto'))
        velo = Color(sfondo.red, sfondo.green, sfondo.blue, 0.80)
        titolo = ordine.testo_placca or 'Avvicina il telefono per lasciare una recensione'
        nome = (ordine.nome_locale or '').upper()
        logo = _immagine_da_allegato(alle.get('logo'))
        portali = [t for t, u in (('google', ordine.link_google),
                                  ('tripadvisor', ordine.link_tripadvisor),
                                  ('thefork', ordine.link_thefork)) if u] or ['google']

    buf = io.BytesIO()
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
            c.setFillColor(velo)
            c.rect(0, 0, PW, PH, stroke=0, fill=1)
        except Exception as e:
            logger.warning('Immagine di fondo non applicata: %s', e)

    # cornice sottile dentro l'area di sicurezza
    c.setStrokeColor(accento)
    c.setLineWidth(0.5)
    c.rect(BLEED + 6.5 * mm, BLEED + 6.5 * mm, W - 13 * mm, H - 14 * mm, stroke=1, fill=0)

    # riga di benvenuto
    c.setFont(_f(True, True), 10.5)
    c.setFillColor(inchiostro)
    c.setFillAlpha(0.8)
    c.drawCentredString(PW / 2, PH - BLEED - 16 * mm, 'È stato un piacere averti con noi')
    c.setFillAlpha(1)

    # blocco centrale: icona, etichetta, titolo, ringraziamento
    _icona_tap(c, PW / 2, PH - BLEED - 47 * mm, 24 * mm, accento)
    c.setFont(_f(False), 5)
    c.setFillColor(accento)
    c.drawCentredString(PW / 2, PH - BLEED - 63 * mm, 'A P P O G G I A   Q U I')

    size = 23 if len(titolo) <= 52 else (19 if len(titolo) <= 78 else 16)
    y = _testo_centrato(c, titolo, PH - BLEED - 78 * mm, _f(True), size, inchiostro,
                        leading=size * 1.2, larghezza=80 * mm)
    # il ringraziamento non deve mai scendere sul piede, anche con titoli lunghi
    minimo = BLEED + (44 * mm if ordine.tier == 'personalizzata-menu' else 38 * mm)
    c.setFont(_f(True, True), 12.5)
    c.setFillColor(accento)
    c.drawCentredString(PW / 2, max(y - 14 * mm, minimo), 'Grazie per il tuo feedback!')

    # piede: logo, portali, badge menù, nome
    y_piede = BLEED + 13 * mm
    c.setFont(_f(False), 7)
    c.setFillColor(inchiostro)
    c.setFillAlpha(0.85)
    c.drawCentredString(PW / 2, y_piede, ' '.join(nome[:46]))
    c.setFillAlpha(1)

    y_sopra = y_piede + 8 * mm
    if ordine.tier == 'personalizzata-menu':
        c.setFont(_f(False), 5)
        c.setFillColor(accento)
        etichetta = 'M E N Ù   D I G I T A L E'
        larg = c.stringWidth(etichetta, _f(False), 5) + 5 * mm
        c.setStrokeColor(accento)
        c.setLineWidth(0.4)
        c.rect(PW / 2 - larg / 2, y_sopra - 1.4 * mm, larg, 4.6 * mm, stroke=1, fill=0)
        c.drawCentredString(PW / 2, y_sopra, etichetta)
        y_sopra += 9 * mm

    _icone_portali(c, portali, y_sopra + 2 * mm, accento)
    y_sopra += 10 * mm

    if logo:
        try:
            lw, lh = logo.getSize()
            scala = min(40 * mm / lw, 14 * mm / lh)
            c.drawImage(logo, PW / 2 - (lw * scala) / 2, y_sopra,
                        lw * scala, lh * scala, mask='auto')
        except Exception as e:
            logger.warning('Logo non inserito nel PDF: %s', e)

    c.showPage()
    c.save()
    return buf.getvalue()
