"""Smart table: il configuratore del sito (smart-table.html) manda qui le scelte del
cliente. Il prezzo lo ricalcola SEMPRE il server con questo listino (mai quello del
browser), poi:
- se c'è un costo iniziale → ordine + Stripe Checkout; dopo il pagamento il webhook
  (routes/pagamenti → gestisci_pagamento_smart) segna l'ordine pagato, crea la richiesta
  nel gestionale e, se c'è una placca recensioni fisica, il suo OrdineNfc (tap e PDF);
- se ci sono solo voci senza prezzo → solo la richiesta.
Con il menù il pagamento è un abbonamento Stripe (deciso da Stefano il 20 ott 2026): oggi
costo iniziale + primo mese del canone (19 €), poi rinnovo automatico ogni mese.

Listino deciso da Stefano (20 ott 2026): tavolo 12 € neutra / 18 € personalizzata,
placca recensioni 35 / 59 € + 25 € ogni copia, preparazione del menù 49 € (menù digitale
già esistente) / 99 € (solo carta) / su preventivo (nessun menù), ricerca dei link 15 €.
Testi delle email: Argon, in smart_table_testi.json.
"""
import html
import json
import logging
import os
import re
from datetime import datetime

from models import db

logger = logging.getLogger(__name__)

PREZZI = {'tavolo_neutra': 1200, 'tavolo_pers': 1800, 'mese': 1900, 'placca_base': 3500,
          'placca_pers': 5900, 'copia': 2500, 'prep_dig': 4900, 'prep_carta': 9900, 'link': 1500}
TAVOLI_MAX, PLACCHE_MAX = 80, 10
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'smart_table_testi.json'), encoding='utf-8') as _f:
    TESTI = json.load(_f)


class OrdineSmartTable(db.Model):
    __tablename__ = 'ordini_smart_table'
    id = db.Column(db.Integer, primary_key=True)
    stato = db.Column(db.String(20), default='in_attesa')   # in_attesa · pagato
    email = db.Column(db.String(200), nullable=False)
    nome = db.Column(db.String(200))
    nome_locale = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    note = db.Column(db.Text)
    config = db.Column(db.JSON, default=dict)
    righe = db.Column(db.JSON, default=list)
    importo = db.Column(db.Float, default=0)          # costo iniziale pagato, in euro
    mese = db.Column(db.Float, default=0)             # canone mensile (abbonamento Stripe)
    abbonamento_id = db.Column(db.String(200))       # subscription Stripe, se c'è il canone
    allegati = db.Column(db.JSON, default=dict)
    spedizione = db.Column(db.JSON)
    stripe_id = db.Column(db.String(200))
    richiesta_id = db.Column(db.Integer)
    ordine_nfc_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pagato_at = db.Column(db.DateTime)


# ─── Configurazione → righe e totali ─────────────────────────────────

_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def _int(v, mn, mx, default):
    try:
        return max(mn, min(mx, int(v)))
    except (TypeError, ValueError):
        return default


def _txt(v, n=80):
    return str(v or '').strip()[:n]


def pulisci(raw):
    """La configurazione mandata dal browser, ridotta ai soli valori ammessi."""
    c = raw if isinstance(raw, dict) else {}
    sel = c.get('sel') or {}
    m, r = c.get('m') or {}, c.get('r') or {}
    hexok = lambda v, d: v if isinstance(v, str) and _HEX.match(v) else d
    links = c.get('links') or {}
    return {
        'sel': {k: bool(sel.get(k)) for k in ('menu', 'recensioni', 'wifi', 'social')},
        'm': {'tavoli': _int(m.get('tavoli'), 1, TAVOLI_MAX, 10),
              'fmt': m.get('fmt') if m.get('fmt') in ('bianco', 'nero', 'stampa') else 'bianco',
              'pers': bool(m.get('pers')), 'tipo': _txt(m.get('tipo'), 24), 'nome': _txt(m.get('nome'), 40),
              'colore': hexok(m.get('colore'), '#c2412a'), 'colore_nome': _txt(m.get('colore_nome'), 30)},
        'r': {'placche': _int(r.get('placche'), 1, PLACCHE_MAX, 1), 'stampa': bool(r.get('stampa')),
              'pers': bool(r.get('pers')), 'variante': r.get('variante') if r.get('variante') in ('scura', 'chiara') else 'scura',
              'nome': _txt(r.get('nome'), 40), 'bg': hexok(r.get('bg'), '#2b2d31'), 'bg_nome': _txt(r.get('bg_nome'), 30),
              'ac': hexok(r.get('ac'), '#c4622d'), 'ac_nome': _txt(r.get('ac_nome'), 30)},
        'oggi': c.get('oggi') if c.get('oggi') in ('dig', 'carta', 'no') else None,
        'link': c.get('link') if c.get('link') in ('si', 'no') else None,
        'links': {k: _txt(links.get(k), 300) for k in ('google', 'tripadvisor', 'thefork', 'instagram', 'prenotazioni')},
        'menu_link': _txt(c.get('menu_link'), 300),
        'wifi': {'rete': _txt((c.get('wifi') or {}).get('rete'), 100), 'password': _txt((c.get('wifi') or {}).get('password'), 100)},
    }


def calcola(c):
    """Righe (voce, dettaglio, centesimi o None, testo del prezzo), costo iniziale, canone,
    se resta qualcosa da definire e se c'è qualcosa da spedire."""
    P, s, m, r = PREZZI, c['sel'], c['m'], c['r']
    righe, subito, mese, da_definire, spedire = [], 0, 0, False, False
    eur = lambda cent: ('%d' % (cent // 100) if cent % 100 == 0 else ('%.2f' % (cent / 100)).replace('.', ',')) + ' €'

    def riga(voce, dettaglio, cent=None, testo=None):
        righe.append({'voce': voce, 'dettaglio': dettaglio, 'cent': cent, 'testo': testo or (eur(cent) if cent is not None else '')})

    if s['menu']:
        mese += P['mese']
        graf = 'personalizzata' if m['pers'] else 'grafica neutra'
        if m['fmt'] == 'stampa':
            riga('Menù digitale', '%d %s da stampare, %s' % (m['tavoli'], 'foglio' if m['tavoli'] == 1 else 'fogli', graf), testo='file da stampare')
        else:
            u = P['tavolo_pers'] if m['pers'] else P['tavolo_neutra']
            subito += u * m['tavoli']; spedire = True
            riga('Placche del menù', '%d × %s, plexiglas %s, %s' % (m['tavoli'], eur(u), m['fmt'], graf), u * m['tavoli'])
        if c['oggi'] == 'dig':
            subito += P['prep_dig']; riga('Sviluppo design, menù e software', 'partendo dal menù digitale attuale', P['prep_dig'])
        elif c['oggi'] == 'carta':
            subito += P['prep_carta']; riga('Sviluppo design, menù e software', 'partendo dal menù di carta', P['prep_carta'])
        else:
            da_definire = True; riga('Sviluppo design, menù e software', 'menù da creare', testo='su preventivo')
    if s['recensioni']:
        if r['stampa']:
            da_definire = True; riga('Placca recensioni', 'file da stampare', testo='su preventivo')
        else:
            t = (P['placca_pers'] if r['pers'] else P['placca_base']) + P['copia'] * (r['placche'] - 1)
            subito += t; spedire = True
            riga('Placca recensioni', '%d %s, %s' % (r['placche'], 'placca' if r['placche'] == 1 else 'placche',
                                                     'personalizzata' if r['pers'] else 'grafica neutra ' + r['variante']), t)
    if s['wifi']:
        if s['menu']:
            riga('Wi-Fi', 'compreso nel menù digitale', 0)
        else:
            da_definire = True; riga('Placchetta Wi-Fi', '', testo='su preventivo')
    if s['social']:
        da_definire = True; riga('Instagram e prenotazioni', '', testo='su preventivo')
    if (s['recensioni'] or s['social']) and c['link'] == 'no':
        subito += P['link']; riga('Ricerca e controllo dei link', 'li cerchiamo noi', P['link'])
    return {'righe': righe, 'subito': subito, 'mese': mese, 'da_definire': da_definire, 'spedire': spedire,
            'oggi': subito + mese if subito > 0 else 0,
            'eur_subito': eur(subito), 'eur_mese': eur(mese) if mese else '', 'eur_oggi': eur(subito + mese if subito > 0 else 0)}


def testo_semplice(c, calc, contatti):
    """Versione in testo per il gestionale (campo messaggio della richiesta)."""
    out = ['Smart table']
    out += ['- %s%s: %s' % (x['voce'], ' (' + x['dettaglio'] + ')' if x['dettaglio'] else '', x['testo']) for x in calc['righe']]
    out.append('Costo iniziale: %s%s' % (calc['eur_subito'], ' + voci su preventivo' if calc['da_definire'] else ''))
    if calc['mese']:
        out.append('Canone menù: %s/mese (abbonamento Stripe, primo mese pagato con il costo iniziale)' % calc['eur_mese'])
    m, r = c['m'], c['r']
    if c['sel']['menu'] and m['pers']:
        out.append('Placca menù: «%s», colore %s %s' % (' '.join(x for x in (m['tipo'], m['nome']) if x), m['colore_nome'], m['colore']))
    if c['sel']['recensioni'] and r['pers']:
        out.append('Placca recensioni: «%s», sfondo %s %s, accento %s %s' % (r['nome'], r['bg_nome'], r['bg'], r['ac_nome'], r['ac']))
    if c['menu_link']:
        out.append('Menù attuale: ' + c['menu_link'])
    ln = ', '.join('%s %s' % (k, v) for k, v in c['links'].items() if v)
    if c['link'] == 'no':
        out.append('Link: da cercare noi')
    elif ln:
        out.append('Link: ' + ln)
    if c['sel']['wifi'] and c['wifi']['rete']:
        out.append('Wi-Fi: %s / %s' % (c['wifi']['rete'], c['wifi']['password']))
    if contatti.get('note'):
        out.append('Note: ' + contatti['note'])
    return '\n'.join(out)


# ─── Email (stile delle email di SB Food) ─────────────────────────────

def _h(s):
    return html.escape(str(s or ''), quote=True)


def _pallino(hexc, nome):
    if not hexc:
        return ''
    return ('<span style="display:inline-block;width:12px;height:12px;border-radius:6px;background:%s;'
            'border:1px solid #d8d2ca;vertical-align:-1px;margin-right:6px"></span>%s') % (_h(hexc), _h(nome or 'personalizzato'))


def email_html(c, calc, nome, pagato, frontend='https://www.sbfoodconsulting.com'):
    k = 'A_' if pagato else 'B_'
    t = lambda x: TESTI[k + x]
    intro = _h(t('INTRO')).replace('{nome}', _h(nome or ''))
    if intro.startswith('Buongiorno ,'):
        intro = 'Buongiorno,' + intro[len('Buongiorno ,'):]
    riga_html = lambda voce, det, val, chiaro=False: (
        '<tr><td style="padding:12px 0;border-bottom:1px solid #ebe5de;color:#2b2d31;font-size:14.5px;line-height:1.4">'
        '<strong style="font-weight:600">%s</strong>%s</td>'
        '<td align="right" style="padding:12px 0 12px 16px;border-bottom:1px solid #ebe5de;color:%s;font-size:14.5px;white-space:nowrap;vertical-align:top">%s</td></tr>'
    ) % (_h(voce), ('<br><span style="color:#8a847c;font-size:12.5px">%s</span>' % det) if det else '',
         '#8a847c' if chiaro else '#2b2d31', _h(val))
    righe = ''.join(riga_html(x['voce'], _h(x['dettaglio']), x['testo'], x['cent'] is None) for x in calc['righe'])
    m, r = c['m'], c['r']
    if c['sel']['menu'] and m['pers']:
        righe += riga_html('Placca del menù, i Suoi dati', '«%s» · colore %s' % (_h(' '.join(x for x in (m['tipo'], m['nome']) if x) or '-'), _pallino(m['colore'], m['colore_nome'])), '', True)
    if c['sel']['recensioni'] and r['pers']:
        righe += riga_html('Placca recensioni, i Suoi dati', '«%s» · sfondo %s · accento %s' % (_h(r['nome'] or '-'), _pallino(r['bg'], r['bg_nome']), _pallino(r['ac'], r['ac_nome'])), '', True)
    if calc['mese']:
        righe += riga_html('Canone del menù digitale', 'primo mese, poi %s al mese' % _h(calc['eur_mese']), calc['eur_mese'])
    tot_label = 'Pagato oggi' if pagato else 'Costo iniziale indicativo'
    tot = ('<tr><td style="padding:16px 0 4px;color:#2b2d31;font-size:15px;font-weight:bold">%s</td>'
           '<td align="right" style="padding:16px 0 4px;color:#2b2d31;font-family:Georgia,serif;font-size:22px">%s</td></tr>') % (
        tot_label, _h(calc['eur_oggi'] + (' + preventivo' if calc['da_definire'] and not pagato else '')))
    if calc['mese']:
        tot += ('<tr><td colspan="2" style="padding:2px 0 0;color:#8a847c;font-size:12.5px">%s</td></tr>' % _h(TESTI['NOTA_MESE_ABBON']))
    passi = ''
    if pagato:
        passi = ('<tr><td style="padding:8px 40px 4px"><p style="margin:0 0 10px;color:#c4622d;font-size:11.5px;letter-spacing:3px;text-transform:uppercase;font-weight:bold">%s</p>'
                 % _h(t('PASSI_TITOLO')))
        for i, p in enumerate((t('PASSO1'), t('PASSO2'), t('PASSO3')), 1):
            passi += ('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="margin:0 0 10px"><tr>'
                      '<td width="34" valign="top"><div style="width:24px;height:24px;border-radius:12px;background:#37393f;color:#fff;font-size:12px;line-height:24px;text-align:center;font-weight:bold">%d</div></td>'
                      '<td style="color:#55514c;font-size:14.5px;line-height:1.55">%s</td></tr></table>') % (i, _h(p))
        passi += '</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="x-apple-disable-message-reformatting"><title>{_h(t('TITOLO'))}</title></head>
<body style="margin:0;padding:0;background-color:#eae6df;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:#eae6df;font-size:1px;line-height:1px">{_h(t('ANTEPRIMA'))}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eae6df;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:6px;overflow:hidden">
<tr><td style="background-color:#37393f;padding:30px 40px 28px">
  <p style="margin:0 0 10px;color:#c4622d;font-size:11.5px;letter-spacing:3px;text-transform:uppercase;font-weight:bold">SB Food Consulting &middot; Smart table</p>
  <h1 style="margin:0;color:#f5f2ee;font-family:Georgia,'Times New Roman',serif;font-size:28px;line-height:1.2;font-weight:normal">{_h(t('TITOLO'))}</h1>
</td></tr>
<tr><td style="padding:0;font-size:0;line-height:0"><img src="{frontend}/assets/email/smart-table.jpg" width="600" alt="" style="display:block;width:100%;max-width:600px;height:auto;border:0"></td></tr>
<tr><td style="padding:28px 40px 6px"><p style="margin:0;color:#37393f;font-size:15.5px;line-height:1.65">{intro}</p></td></tr>
<tr><td style="padding:14px 40px 10px">
  <p style="margin:0 0 6px;color:#c4622d;font-size:11.5px;letter-spacing:3px;text-transform:uppercase;font-weight:bold">{_h(t('TABELLA_TITOLO') if pagato else TESTI['A_TABELLA_TITOLO'])}</p>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{righe}{tot}</table>
</td></tr>
{passi}
<tr><td style="padding:14px 40px 30px;color:#37393f;font-size:14.5px;line-height:1.6">{_h(t('CHIUSURA'))}</td></tr>
<tr><td style="background-color:#2b2d32;padding:22px 40px;text-align:center">
  <p style="margin:0 0 6px;color:#f5f2ee;font-size:12.5px;font-weight:bold;letter-spacing:1px">SB FOOD CONSULTING</p>
  <p style="margin:0;color:#a09b94;font-size:12px;line-height:1.6">Roma, Italia &middot; info@sbfoodconsulting.com</p>
</td></tr>
</table></td></tr></table></body></html>"""


def oggetto(pagato):
    return TESTI['A_OGGETTO' if pagato else 'B_OGGETTO']


def invia_email_cliente(c, calc, email, nome, pagato):
    try:
        from utils.email import invia_email
        invia_email(email, nome or '', oggetto(pagato), email_html(c, calc, nome, pagato))
    except Exception as e:
        logger.error('Email Smart table a %s: %s', email, e, exc_info=True)


def invia_email_admin(c, calc, ordine_o_dati, pagato, admin, frontend):
    try:
        from utils.email import invia_email
        d = ordine_o_dati
        testa = ('<p style="font-size:15px"><strong>%s</strong> · %s · %s%s</p>' % (
            'PAGATO ' + calc['eur_oggi'] if pagato else 'Richiesta senza pagamento',
            _h(d.get('nome_locale') or '-'), _h(d.get('email')), (' · ' + _h(d.get('telefono'))) if d.get('telefono') else ''))
        invia_email(admin, 'Simone', 'Smart table %s, %s' % ('pagato ' + calc['eur_oggi'] if pagato else 'richiesta', d.get('nome_locale') or d.get('email')),
                    testa + email_html(c, calc, d.get('nome'), pagato).split('<body', 1)[1].split('>', 1)[1].rsplit('</body>', 1)[0]
                    + '<pre style="white-space:pre-wrap;font-size:13px;background:#f5f2ee;padding:14px">%s</pre>' % _h(testo_semplice(c, calc, d))
                    + '<p><a href="%s/admin.html">Apri il gestionale, sezione Placche NFC, Richieste</a></p>' % frontend)
    except Exception as e:
        logger.error('Email admin Smart table: %s', e, exc_info=True)


# ─── Dopo il pagamento ────────────────────────────────────────────────

def gestisci_pagamento_smart(session):
    """checkout.session.completed con metadata.tipo == 'smart'. Idempotente."""
    from models import Pagamento, RichiestaNfc, OrdineNfc
    from routes.nfc import FRONTEND_URL, ADMIN_EMAIL, _slugify, _url_valida, _pulisci_url
    meta = session.metadata
    oid = meta.get('ordine_id') if hasattr(meta, 'get') else getattr(meta, 'ordine_id', None)
    o = OrdineSmartTable.query.get(int(oid)) if oid else None
    if not o:
        logger.error('Webhook Smart table: ordine %s non trovato', oid)
        return
    if o.stato != 'in_attesa':
        return
    cd = getattr(session, 'customer_details', None)
    o.stato, o.pagato_at, o.stripe_id = 'pagato', datetime.utcnow(), session.id
    o.abbonamento_id = getattr(session, 'subscription', None) if isinstance(getattr(session, 'subscription', None), str) else o.abbonamento_id
    o.importo = (getattr(session, 'amount_total', 0) or 0) / 100 or o.importo
    o.telefono = o.telefono or (getattr(cd, 'phone', None) if cd else None)
    sped = None
    try:
        sd = getattr(session, 'shipping_details', None) or getattr(session, 'collected_information', None)
        if sd and getattr(sd, 'shipping_details', None):
            sd = sd.shipping_details
        if sd and getattr(sd, 'address', None):
            a = sd.address
            sped = {'nome': getattr(sd, 'name', '') or o.nome, 'via': a.line1, 'via2': a.line2, 'cap': a.postal_code,
                    'citta': a.city, 'provincia': a.state, 'paese': a.country}
    except Exception as e:
        logger.warning('Webhook Smart table: spedizione non letta: %s', e)
    o.spedizione = sped
    c, calc = o.config, calcola(o.config)
    db.session.add(Pagamento(nome=o.nome or o.nome_locale or o.email, email=o.email, prodotto='smart-table',
                             importo=o.importo, stato='completato', stripe_id=session.id))
    ric = RichiestaNfc(allegati=o.allegati or {}, nome=o.nome, nome_locale=o.nome_locale, email=o.email,
                       telefono=o.telefono, quantita=None,
                       messaggio=('[Menù digitale] ' if c['sel']['menu'] else '') + '[PAGATO %s] ' % calc['eur_oggi'] + testo_semplice(c, calc, {'note': o.note}))
    db.session.add(ric)
    db.session.flush()
    o.richiesta_id = ric.id
    # la placca recensioni fisica nasce come ordine NFC vero: tap, PDF di stampa, gestionale
    if c['sel']['recensioni'] and not c['r']['stampa']:
        r = c['r']
        links = {k: _pulisci_url(c['links'].get(k)) for k in ('google', 'tripadvisor', 'thefork')}
        links = {k: v for k, v in links.items() if _url_valida(v)}
        on = OrdineNfc(slug=_slugify(r['nome'] or o.nome_locale or 'locale'), tier='personalizzata' if r['pers'] else 'base',
                       quantita=r['placche'], variante=None if r['pers'] else r['variante'],
                       nome_locale=r['nome'] or o.nome_locale or '-', referente=o.nome, email=o.email, telefono=o.telefono,
                       link_google=links.get('google'), link_tripadvisor=links.get('tripadvisor'), link_thefork=links.get('thefork'),
                       colore_primario=r['ac'] if r['pers'] else None, colore_sfondo=r['bg'] if r['pers'] else None,
                       note='Dal configuratore Smart table (ordine %d)' % o.id + ('' if links else ', link da cercare'),
                       allegati={k: v for k, v in (o.allegati or {}).items() if k == 'logo'}, articoli={},
                       importo=next((x['cent'] / 100 for x in calc['righe'] if x['voce'] == 'Placca recensioni' and x['cent']), 0),
                       stato='pagato', pagato_at=datetime.utcnow(), stripe_id=session.id, spedizione=sped)
        db.session.add(on)
        db.session.flush()
        o.ordine_nfc_id = on.id
    db.session.commit()
    invia_email_cliente(c, calc, o.email, o.nome, True)
    invia_email_admin(c, calc, {'nome': o.nome, 'nome_locale': o.nome_locale, 'email': o.email, 'telefono': o.telefono, 'note': o.note},
                      True, ADMIN_EMAIL, FRONTEND_URL)
