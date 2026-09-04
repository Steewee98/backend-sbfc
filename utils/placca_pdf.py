"""Genera il PDF di stampa della Placca NFC (A6 105x148 mm + 3 mm di abbondanza).

Il file è pensato per il tipografo: formato esatto, fondo al vivo, nessun
segno di taglio da rimuovere a mano. Per la versione Base riproduce la
grafica SB Food (chiara o scura); per le personalizzate usa i colori, il
testo, il logo e la foto scelti dal cliente.
"""
import base64
import logging

logger = logging.getLogger(__name__)

FRONTEND = 'https://www.sbfoodconsulting.com'

ICONA_TAP = '''<svg viewBox="0 0 100 92" fill="none" stroke="currentColor" stroke-width="4"
  stroke-linecap="round" stroke-linejoin="round">
  <rect x="20" y="24" width="42" height="60" rx="8"/>
  <line x1="34" y1="32" x2="48" y2="32"/>
  <circle cx="41" cy="78" r="2.6" fill="currentColor" stroke="none"/>
  <path d="M64.8 22.4 A 9 9 0 0 1 68.3 33.4"/>
  <path d="M69.0 15.6 A 17 17 0 0 1 75.8 36.4"/>
  <path d="M73.3 8.8 A 25 25 0 0 1 83.2 39.4"/>
</svg>'''

PORTALI = {
    'google': '''<svg class="p-google" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2.6" stroke-linecap="round"><path d="M21 12 A9 9 0 1 1 18.2 5.6"/>
        <path d="M21 12 L12.4 12"/></svg>''',
    'tripadvisor': '''<svg class="p-trip" viewBox="0 0 44 26" fill="none" stroke="currentColor" stroke-width="2.4">
        <circle cx="13" cy="13" r="8.5"/><circle cx="31" cy="13" r="8.5"/>
        <circle cx="13" cy="13" r="2.8" fill="currentColor" stroke="none"/>
        <circle cx="31" cy="13" r="2.8" fill="currentColor" stroke="none"/>
        <path d="M18.5 19 L22 22.5 L25.5 19" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M6 6 C9 3 12 3 14 5" stroke-linecap="round"/>
        <path d="M38 6 C35 3 32 3 30 5" stroke-linecap="round"/></svg>''',
    'thefork': '''<svg class="p-fork" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M8 3 V9"/><path d="M12 3 V9"/><path d="M16 3 V9"/>
        <path d="M8 9 C8 13 16 13 16 9"/><path d="M12 9 V21"/></svg>''',
}


def _luminanza(hex_col):
    try:
        h = hex_col.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255
    except Exception:
        return 0.0


def _data_uri(allegato):
    if not allegato or not allegato.get('dati'):
        return None
    return f"data:{allegato.get('mime', 'image/png')};base64,{allegato['dati']}"


def _esc(t):
    return (str(t or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def costruisci_html(ordine):
    base = ordine.tier == 'base'
    alle = ordine.allegati or {}

    if base:
        chiara = (ordine.variante or 'scura') == 'chiara'
        sfondo = '#f5f2ee' if chiara else '#2b2d31'
        inchiostro = '#2b2d31' if chiara else '#f5f2ee'
        accento = '#c4622d'
        texture = f"{FRONTEND}/assets/nfc/print/bg-{'chiara' if chiara else 'scura'}.jpg"
        velo = ('linear-gradient(180deg, rgba(249,246,241,.28) 0%, rgba(243,238,231,.45) 100%)'
                if chiara else
                'linear-gradient(180deg, rgba(43,45,49,.55) 0%, rgba(43,45,49,.72) 100%)')
        fondo_css = f"background: {velo}, url('{texture}') center/cover no-repeat, {sfondo};"
        titolo = 'Avvicina il telefono per lasciare una recensione'
        nome_sotto = 'SB Food Consulting'
        logo_uri = None
        portali_attivi = ['google', 'tripadvisor', 'thefork']
    else:
        sfondo = ordine.colore_sfondo or '#2b2d31'
        accento = ordine.colore_primario or '#c4622d'
        inchiostro = '#2b2d31' if _luminanza(sfondo) > 0.6 else '#f5f2ee'
        foto_uri = _data_uri(alle.get('foto'))
        if foto_uri:
            velo = f'linear-gradient({sfondo}cc, {sfondo}cc)'
            fondo_css = f"background: {velo}, url('{foto_uri}') center/cover no-repeat, {sfondo};"
        else:
            fondo_css = f'background: {sfondo};'
        titolo = ordine.testo_placca or 'Avvicina il telefono per lasciare una recensione'
        nome_sotto = ordine.nome_locale
        logo_uri = _data_uri(alle.get('logo'))
        portali_attivi = [t for t, u in (('google', ordine.link_google),
                                         ('tripadvisor', ordine.link_tripadvisor),
                                         ('thefork', ordine.link_thefork)) if u]
        if not portali_attivi:
            portali_attivi = ['google']

    portali_html = ''.join(PORTALI[p] for p in portali_attivi)
    logo_html = f'<img class="logo" src="{logo_uri}">' if logo_uri else ''
    menu_html = ('<div class="menu-badge">Men&ugrave; digitale</div>'
                 if ordine.tier == 'personalizzata-menu' else '')

    return f'''<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8">
<style>
  @page {{ size: 111mm 154mm; margin: 0; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Playfair Display', Georgia, 'Times New Roman', serif;
          -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .placca {{ position: relative; width: 111mm; height: 154mm;
             color: {inchiostro}; overflow: hidden; {fondo_css} }}
  /* area di sicurezza: 3 mm di abbondanza su ogni lato */
  .frame {{ position: absolute; top: 10mm; left: 9.5mm; right: 9.5mm; bottom: 9.5mm;
            border: 0.5pt solid {accento}; }}
  .safe {{ position: absolute; top: 3mm; left: 3mm; width: 105mm; height: 148mm;
           padding: 14mm 12mm 13mm; display: flex; flex-direction: column;
           align-items: center; justify-content: space-between; text-align: center; }}
  .welcome {{ font-style: italic; font-size: 10.5pt; opacity: .8; }}
  .middle {{ flex: 1; display: flex; flex-direction: column;
             align-items: center; justify-content: center; }}
  .tapicon {{ width: 24mm; color: {accento}; }}
  .tapicon svg {{ display: block; width: 100%; height: auto; }}
  .taphere {{ font-family: Helvetica, Arial, sans-serif; font-weight: 600; font-size: 5pt;
              letter-spacing: 2pt; text-transform: uppercase; color: {accento};
              margin-top: 2.5mm; }}
  .headline {{ font-weight: 600; font-size: 22pt; line-height: 1.2;
               margin-top: 9mm; max-width: 80mm; }}
  .thanks {{ font-style: italic; font-size: 12.5pt; color: {accento}; margin-top: 10mm; }}
  .brand {{ display: flex; flex-direction: column; align-items: center; }}
  .logo {{ max-height: 14mm; max-width: 45mm; margin-bottom: 4mm; }}
  .portals {{ color: {accento}; margin-bottom: 3.5mm; }}
  .portals svg {{ display: inline-block; vertical-align: middle; margin: 0 3mm; }}
  .p-google {{ height: 6.2mm; }} .p-trip {{ height: 5mm; }} .p-fork {{ height: 6.8mm; }}
  .menu-badge {{ font-family: Helvetica, Arial, sans-serif; font-size: 5pt;
                 letter-spacing: 1.6pt; text-transform: uppercase; color: {accento};
                 border: 0.5pt solid {accento}; padding: 1mm 2.5mm; margin-bottom: 3.5mm; }}
  .name {{ font-family: Helvetica, Arial, sans-serif; font-size: 7pt;
           letter-spacing: 2.4pt; text-transform: uppercase; opacity: .85; }}
</style></head>
<body>
  <div class="placca">
    <div class="frame"></div>
    <div class="safe">
      <div class="welcome">&Egrave; stato un piacere averti con noi</div>
      <div class="middle">
        <div class="tapicon">{ICONA_TAP}</div>
        <div class="taphere">Appoggia qui</div>
        <div class="headline">{_esc(titolo)}</div>
        <div class="thanks">Grazie per il tuo feedback!</div>
      </div>
      <div class="brand">
        {logo_html}
        <div class="portals">{portali_html}</div>
        {menu_html}
        <div class="name">{_esc(nome_sotto)}</div>
      </div>
    </div>
  </div>
</body></html>'''


def genera_pdf(ordine):
    """Ritorna i byte del PDF, oppure solleva RuntimeError se WeasyPrint manca."""
    try:
        from weasyprint import HTML as WeasyHTML
    except Exception as e:
        raise RuntimeError(f'WeasyPrint non disponibile: {e}')
    html = costruisci_html(ordine)
    return WeasyHTML(string=html, base_url=FRONTEND).write_pdf()
