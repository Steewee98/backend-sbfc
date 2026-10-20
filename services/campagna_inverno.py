"""Campagna email inverno 2026-27: 12 email brevi (3 al mese, nov-feb) a chi ha
scaricato le schede con il consenso marketing.

I testi stanno in campagna_inverno.json (scritti da Argon, approvati da Stefano il
20 ottobre 2026) e non si toccano qui. Ogni email ha una data (ora di Roma): dal
mattino di quel giorno il giro delle campagne (routes/lead_strumenti.processa_coda)
mette in coda i destinatari e li spedisce scaglionati come la campagna del manuale.

Chi riceve l'email n:
- consenso marketing, non disiscritto;
- non è ancora nella sequenza automatica (stato «attiva»): niente due email a settimana;
- non ha già comprato quello che l'email vende (campo «escludi»).
"""
import html
import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'campagna_inverno.json')
ROMA = ZoneInfo('Europe/Rome')
FIRMA = 'https://www.sbfoodconsulting.com/assets/img/firma-simone.png'
# oltre questi giorni dalla data prevista un'email non ancora partita non parte più
# (es. il servizio è stato fermo): meglio saltarla che mandare «domenica è San Valentino» a marzo
FINESTRA_GIORNI = 3

with open(_FILE, encoding='utf-8') as f:
    EMAILS = json.load(f)
PER_NUMERO = {e['n']: e for e in EMAILS}


def nome_campagna(n):
    return 'inverno-%02d' % n


def numero_da_campagna(campagna):
    if not (campagna or '').startswith('inverno-'):
        return None
    try:
        return int(campagna.split('-', 1)[1])
    except ValueError:
        return None


def oggi_roma(adesso_utc=None):
    adesso_utc = adesso_utc or datetime.utcnow()
    return adesso_utc.replace(tzinfo=ZoneInfo('UTC')).astimezone(ROMA).date()


def dovute(adesso_utc=None):
    """Email la cui data è arrivata (e non è passata da più di FINESTRA_GIORNI)."""
    oggi = oggi_roma(adesso_utc)
    out = []
    for e in EMAILS:
        d = datetime.strptime(e['data'], '%Y-%m-%d').date()
        if d <= oggi <= d + timedelta(days=FINESTRA_GIORNI):
            out.append(e)
    return out


# ─── Destinatari ─────────────────────────────────────────────────────

def ha_gia(email, escludi):
    """L'email vende qualcosa che questa persona ha già?"""
    if not escludi:
        return False
    from models import db, Pagamento, OrdineNfc
    email = (email or '').strip().lower()
    if escludi == 'placca':
        return db.session.query(OrdineNfc.id).filter(
            db.func.lower(OrdineNfc.email) == email,
            OrdineNfc.stato.in_(('pagato', 'in_lavorazione', 'spedito', 'consegnato'))).first() is not None
    prodotti = {'manuale': ['manager-ristorazione'],
                'corso-completo': ['corso-completo']}.get(escludi)
    if prodotti is None and escludi.startswith('modulo-'):
        prodotti = [escludi, 'corso-completo']
    if not prodotti:
        return False
    return db.session.query(Pagamento.id).filter(
        db.func.lower(Pagamento.email) == email,
        Pagamento.prodotto.in_(prodotti)).first() is not None


def destinatari(e):
    """Chi riceve l'email e, calcolato al momento in cui si mette in coda."""
    from models import db, EmailSequenza
    from routes.lead_strumenti import _email_uniche_consenso
    in_sequenza = {(r[0] or '').strip().lower() for r in db.session.query(EmailSequenza.email)
                   .filter(EmailSequenza.stato == 'attiva').all()}
    return [m for m in _email_uniche_consenso()
            if m not in in_sequenza and not ha_gia(m, e.get('escludi'))]


# ─── Composizione ────────────────────────────────────────────────────

def _h(s):
    return html.escape(s or '', quote=True)


def componi_html(e, unsub):
    par = ''.join(
        '<p style="margin:0 0 14px;color:#55514c;font-size:15.5px;line-height:1.7">%s</p>' % _h(p)
        for p in e['paragrafi'])
    punti = ''.join(
        '<tr><td width="30" valign="top" style="padding:7px 0"><div style="width:20px;height:20px;border-radius:10px;'
        'background-color:#c4622d;color:#ffffff;font-size:12px;line-height:20px;text-align:center;font-weight:bold">&#10003;</div></td>'
        '<td style="padding:7px 0;color:#37393f;font-size:15px;line-height:1.45">%s</td></tr>' % _h(p)
        for p in e['punti'])
    riquadro = ''
    if e.get('riquadro'):
        riquadro = ('<tr><td style="padding:6px 40px 0"><table role="presentation" width="100%%" cellpadding="0" cellspacing="0">'
                    '<tr><td style="background-color:#f7efe8;border-left:3px solid #c4622d;padding:14px 18px;color:#3a3c41;'
                    'font-size:14px;line-height:1.55">%s</td></tr></table></td></tr>') % _h(e['riquadro'])
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="x-apple-disable-message-reformatting"><title>{_h(e['titolo'])}</title></head>
<body style="margin:0;padding:0;background-color:#eae6df;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#eae6df;font-size:1px;line-height:1px">{_h(e['anteprima'])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eae6df;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:6px;overflow:hidden">
<tr><td style="padding:0;font-size:0;line-height:0"><a href="{_h(e['link'])}"><img src="{_h(e['immagine'])}" width="600" alt="{_h(e['kicker'])}" style="display:block;width:100%;max-width:600px;height:auto;border:0"></a></td></tr>
<tr><td style="padding:28px 40px 0">
  <p style="margin:0 0 8px;color:#c4622d;font-size:11.5px;letter-spacing:3px;text-transform:uppercase;font-weight:bold">{_h(e['kicker'])}</p>
  <h1 style="margin:0 0 16px;color:#26282c;font-family:Georgia,'Times New Roman',serif;font-size:26px;line-height:1.2;font-weight:normal">{_h(e['titolo'])}</h1>
  <p style="margin:0 0 14px;color:#37393f;font-size:15.5px;line-height:1.6">Gentile collega,</p>
  {par}
</td></tr>
<tr><td style="padding:2px 40px 12px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #ebe5de;padding-top:8px">{punti}</table></td></tr>
{riquadro}
<tr><td align="center" style="padding:24px 40px 26px">
  <table role="presentation" cellpadding="0" cellspacing="0"><tr><td align="center" bgcolor="#c4622d" style="border-radius:26px">
    <a href="{_h(e['link'])}" style="display:inline-block;background-color:#c4622d;color:#ffffff;text-decoration:none;padding:15px 34px;font-size:15.5px;font-weight:bold;border-radius:26px">{_h(e['pulsante'])} &rarr;</a>
  </td></tr></table>
</td></tr>
<tr><td style="padding:0 40px 30px;color:#37393f;font-size:14.5px;line-height:1.6">
  Cordiali saluti,<br><img src="{FIRMA}" alt="" height="44" style="display:block;height:44px;width:auto;border:0;margin:6px 0 2px">
  <strong>Simone Braghetta</strong><br><span style="color:#6b6560">Fondatore, SB Food Consulting</span>
</td></tr>
<tr><td style="background-color:#2b2d32;padding:22px 40px;text-align:center">
  <p style="margin:0 0 6px;color:#f5f2ee;font-size:12.5px;font-weight:bold;letter-spacing:1px">SB FOOD CONSULTING</p>
  <p style="margin:0;color:#a09b94;font-size:12px;line-height:1.6">Roma, Italia &middot; info@sbfoodconsulting.com</p>
  <p style="margin:12px 0 0;color:#8f8a82;font-size:11px;line-height:1.6">Ha ricevuto questa comunicazione in quanto iscritto ai contenuti di SB Food Consulting.<br>
  <a href="{_h(unsub)}" style="color:#8f8a82;text-decoration:underline">Annulla l'iscrizione</a></p>
</td></tr>
</table></td></tr></table></body></html>"""


def componi_testo(e, unsub):
    righe = ['Gentile collega,', ''] + [p + '\n' for p in e['paragrafi']]
    righe += ['- ' + p for p in e['punti']] + ['']
    if e.get('riquadro'):
        righe += [e['riquadro'], '']
    righe += ['%s: %s' % (e['pulsante'], e['link']), '',
              'Cordiali saluti,', 'Simone Braghetta', 'Fondatore, SB Food Consulting', '',
              '---', "Annulla l'iscrizione: %s" % unsub]
    return '\n'.join(righe)


# ─── Invio ───────────────────────────────────────────────────────────

def invia_inverno_a(email, n, oggetto_prefisso=''):
    """Manda l'email n a UNA persona e la registra su EmailInvio. Ritorna il
    resend_id o None. Va chiamata dentro un application context."""
    import resend
    from services.email_service import unsub_url, log_email_invio, _mail_from
    e = PER_NUMERO.get(n)
    if not e:
        return None
    if not resend.api_key:
        resend.api_key = os.environ.get('RESEND_API_KEY')
    if not resend.api_key:
        return None
    u = unsub_url(email)
    oggetto = oggetto_prefisso + e['oggetto']
    try:
        res = resend.Emails.send({
            "from": _mail_from(),
            "to": [email],
            "subject": oggetto,
            "html": componi_html(e, u),
            "text": componi_testo(e, u),
            "headers": {"List-Unsubscribe": "<%s>" % u,
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
            "tags": [{"name": "categoria", "value": nome_campagna(n)}],
        })
        rid = res.get('id') if isinstance(res, dict) else getattr(res, 'id', None)
        log_email_invio(rid, email, oggetto, 'campagna_' + nome_campagna(n).replace('-', '_'))
        return rid or 'inviata'
    except Exception as ex:
        logger.error("Errore invio %s a %s: %s", nome_campagna(n), email, ex)
        return None
