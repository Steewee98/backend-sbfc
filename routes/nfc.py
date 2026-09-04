"""Shop Placca NFC recensioni — ordine, checkout Stripe, micro-pagina del tap, admin.

Flusso:
  1. POST /api/nfc/ordine (multipart) → crea OrdineNfc 'in_attesa' + sessione Stripe → {url}
  2. Stripe → webhook (routes/pagamenti.py) → gestisci_pagamento_nfc() → 'pagato' + email
  3. Il tag NFC punta a sbfoodconsulting.com/tap.html?p=<slug> → GET /api/nfc/p/<slug>
  4. Admin: lista/aggiorna ordini, scarica allegati (logo/foto/menu).
"""
import os
import re
import base64
import secrets
import logging
from datetime import datetime
from functools import wraps

import stripe
from flask import Blueprint, request, jsonify, Response
from models import db, OrdineNfc, Pagamento

logger = logging.getLogger(__name__)
nfc_bp = Blueprint('nfc', __name__)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# ─── Catalogo (prezzi in centesimi) ───────────────────────
# Unica fonte di verità dei prezzi: il frontend li mostra ma il totale lo fa Stripe da qui.
TIERS = {
    'base': {
        'nome': 'Placca NFC recensioni — Base',
        'descrizione': 'Grafica SB Food (chiara o scura), link recensioni già programmati.',
        'prezzo': 3500,
    },
    'personalizzata': {
        'nome': 'Placca NFC recensioni — Personalizzata',
        'descrizione': 'Logo, colori, testo e foto del locale sulla placca.',
        'prezzo': 5900,
    },
    'personalizzata-menu': {
        'nome': 'Placca NFC recensioni — Personalizzata + Menù',
        'descrizione': 'Placca personalizzata + menù digitale raggiungibile dal tap.',
        'prezzo': 7900,
    },
}
PREZZO_COPIA_EXTRA = 2500   # ogni placca oltre la prima (stessa grafica)
QUANTITA_MAX = 10
MAX_FILE_BYTES = 4 * 1024 * 1024
MIME_IMMAGINI = {'image/png', 'image/jpeg', 'image/webp', 'image/svg+xml'}
MIME_MENU = MIME_IMMAGINI | {'application/pdf'}

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'https://www.sbfoodconsulting.com')
# URL pubblico di QUESTO backend (dietro il proxy Railway request.host_url può uscire in http)
BACKEND_PUBLIC_URL = os.environ.get('BACKEND_PUBLIC_URL', 'https://web-production-f3794.up.railway.app')
ADMIN_EMAIL = 'info@stefanodemartis.com'


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.headers.get('X-Admin-Token') != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


def calcola_totale(tier, quantita):
    """Prima placca al prezzo del tier, le altre a PREZZO_COPIA_EXTRA. In centesimi."""
    return TIERS[tier]['prezzo'] + PREZZO_COPIA_EXTRA * (quantita - 1)


def _slugify(testo):
    s = re.sub(r'[^a-z0-9]+', '-', (testo or '').lower()).strip('-')[:40]
    return (s or 'locale') + '-' + secrets.token_hex(2)


def _url_valida(u):
    return bool(u) and re.match(r'^https?://[^\s]+$', u.strip()) is not None


def _pulisci_url(u):
    u = (u or '').strip()
    if u and not u.lower().startswith(('http://', 'https://')):
        u = 'https://' + u
    return u[:600]


def _hex(colore, default):
    c = (colore or '').strip()
    return c if re.match(r'^#[0-9a-fA-F]{6}$', c) else default


def _leggi_file(campo, mime_ok):
    """Ritorna dict {'nome','mime','dati'} o None. Solleva ValueError se non valido."""
    f = request.files.get(campo)
    if not f or not f.filename:
        return None
    dati = f.read()
    if len(dati) > MAX_FILE_BYTES:
        raise ValueError(f'Il file "{f.filename}" supera i 4 MB.')
    mime = (f.mimetype or '').lower()
    if mime not in mime_ok:
        raise ValueError(f'Formato non supportato per "{f.filename}" ({mime}).')
    return {'nome': f.filename[:120], 'mime': mime,
            'dati': base64.b64encode(dati).decode('ascii')}


# ─── 1. Ordine + checkout ─────────────────────────────────

@nfc_bp.route('/api/nfc/catalogo', methods=['GET'])
def catalogo():
    return jsonify({
        'tiers': {k: {'nome': v['nome'], 'descrizione': v['descrizione'], 'prezzo': v['prezzo']}
                  for k, v in TIERS.items()},
        'copia_extra': PREZZO_COPIA_EXTRA,
        'quantita_max': QUANTITA_MAX,
    })


@nfc_bp.route('/api/nfc/ordine', methods=['POST'])
def crea_ordine():
    form = request.form
    tier = form.get('tier', '')
    if tier not in TIERS:
        return jsonify({'error': 'Versione non valida'}), 400

    try:
        quantita = int(form.get('quantita', 1))
    except ValueError:
        quantita = 1
    quantita = max(1, min(QUANTITA_MAX, quantita))

    nome_locale = (form.get('nome_locale') or '').strip()[:200]
    email = (form.get('email') or '').strip().lower()[:200]
    if not nome_locale:
        return jsonify({'error': 'Inserisci il nome del locale'}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Inserisci una email valida'}), 400

    links = {k: _pulisci_url(form.get(k)) for k in ('link_google', 'link_tripadvisor', 'link_thefork')}
    links_validi = {k: v for k, v in links.items() if _url_valida(v)}
    if not links_validi:
        return jsonify({'error': 'Inserisci almeno un link recensioni (Google, TripAdvisor o TheFork)'}), 400

    variante = form.get('variante') if form.get('variante') in ('chiara', 'scura') else 'scura'
    personalizzata = tier != 'base'

    try:
        allegati = {}
        if personalizzata:
            logo = _leggi_file('logo', MIME_IMMAGINI)
            if logo:
                allegati['logo'] = logo
            foto = _leggi_file('foto', MIME_IMMAGINI)
            if foto:
                allegati['foto'] = foto
        menu_link = ''
        if tier == 'personalizzata-menu':
            menu = _leggi_file('menu', MIME_MENU)
            if menu:
                allegati['menu'] = menu
            menu_link = _pulisci_url(form.get('menu_link'))
            if not menu and not _url_valida(menu_link):
                return jsonify({'error': 'Carica il menù (PDF o immagine) oppure inserisci il link al menù'}), 400
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    ordine = OrdineNfc(
        slug=_slugify(nome_locale),
        tier=tier, quantita=quantita,
        variante=variante if not personalizzata else None,
        nome_locale=nome_locale,
        referente=(form.get('referente') or '').strip()[:200],
        email=email,
        telefono=(form.get('telefono') or '').strip()[:50],
        link_google=links_validi.get('link_google'),
        link_tripadvisor=links_validi.get('link_tripadvisor'),
        link_thefork=links_validi.get('link_thefork'),
        colore_primario=_hex(form.get('colore_primario'), '#c4622d') if personalizzata else None,
        colore_sfondo=_hex(form.get('colore_sfondo'), '#2b2d31') if personalizzata else None,
        testo_placca=(form.get('testo_placca') or '').strip()[:200] if personalizzata else None,
        menu_link=menu_link or None,
        note=(form.get('note') or '').strip()[:2000] or None,
        allegati=allegati,
        importo=calcola_totale(tier, quantita) / 100,
        stato='in_attesa',
    )
    db.session.add(ordine)
    db.session.commit()

    cfg = TIERS[tier]
    line_items = [{
        'price_data': {
            'currency': 'eur',
            'product_data': {
                'name': cfg['nome'],
                'description': f'{cfg["descrizione"]} Locale: {nome_locale}',
            },
            'unit_amount': cfg['prezzo'],
        },
        'quantity': 1,
    }]
    if quantita > 1:
        line_items.append({
            'price_data': {
                'currency': 'eur',
                'product_data': {
                    'name': 'Placca aggiuntiva (stessa grafica)',
                    'description': f'Copie extra per {nome_locale}',
                },
                'unit_amount': PREZZO_COPIA_EXTRA,
            },
            'quantity': quantita - 1,
        })

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            allow_promotion_codes=True,
            customer_email=email,
            billing_address_collection='required',
            shipping_address_collection={'allowed_countries': ['IT', 'SM', 'VA', 'CH']},
            phone_number_collection={'enabled': True},
            success_url=f'{FRONTEND_URL}/placca-nfc-grazie.html?ordine={ordine.slug}',
            cancel_url=f'{FRONTEND_URL}/placca-nfc.html?pagamento=annullato#acquista',
            metadata={'tipo': 'nfc', 'ordine_id': str(ordine.id), 'slug': ordine.slug,
                      'prodotto_id': f'placca-nfc-{tier}'},
        )
        ordine.stripe_id = session.id
        db.session.commit()
        return jsonify({'url': session.url, 'slug': ordine.slug})
    except Exception as e:
        logger.error('Stripe checkout NFC error: %s', e, exc_info=True)
        return jsonify({'error': 'Errore nella creazione del pagamento'}), 500


# ─── 2. Webhook (chiamato da routes/pagamenti.py) ─────────

def gestisci_pagamento_nfc(session):
    """checkout.session.completed con metadata.tipo == 'nfc'."""
    meta = session.metadata
    ordine_id = meta.get('ordine_id') if hasattr(meta, 'get') else getattr(meta, 'ordine_id', None)
    ordine = OrdineNfc.query.get(int(ordine_id)) if ordine_id else None
    if not ordine:
        logger.error('Webhook NFC: ordine %s non trovato', ordine_id)
        return
    if ordine.stato != 'in_attesa':
        logger.info('Webhook NFC: ordine %s già in stato %s, skip', ordine.id, ordine.stato)
        return

    cd = session.customer_details
    email = ((cd.email if cd else None) or session.customer_email or ordine.email or '').lower()
    nome = (cd.name if cd else '') or ordine.referente or ''
    telefono = (cd.phone if cd else None) or ordine.telefono

    sped = None
    try:
        sd = getattr(session, 'shipping_details', None) or getattr(session, 'collected_information', None)
        if sd and getattr(sd, 'shipping_details', None):
            sd = sd.shipping_details
        if sd and getattr(sd, 'address', None):
            a = sd.address
            sped = {'nome': getattr(sd, 'name', '') or nome,
                    'via': a.line1, 'via2': a.line2, 'cap': a.postal_code,
                    'citta': a.city, 'provincia': a.state, 'paese': a.country}
    except Exception as e:
        logger.warning('Webhook NFC: spedizione non letta: %s', e)

    ordine.stato = 'pagato'
    ordine.pagato_at = datetime.utcnow()
    ordine.email = email or ordine.email
    ordine.referente = ordine.referente or nome
    ordine.telefono = telefono
    ordine.spedizione = sped
    ordine.stripe_id = session.id
    ordine.importo = (session.amount_total or 0) / 100 or ordine.importo

    db.session.add(Pagamento(
        nome=nome or ordine.nome_locale, email=ordine.email,
        prodotto=f'placca-nfc-{ordine.tier}', importo=ordine.importo,
        stato='completato', stripe_id=session.id))
    db.session.commit()

    _email_conferma(ordine, nome)


def _riga(label, valore):
    return f'<p style="margin:4px 0"><strong>{label}:</strong> {valore}</p>' if valore else ''


def _email_conferma(ordine, nome):
    try:
        from utils.email import invia_email
        tier = TIERS[ordine.tier]
        tap_url = f'{FRONTEND_URL}/tap.html?p={ordine.slug}'
        personalizzata = ordine.tier != 'base'
        prossimo = ('Entro 2 giorni lavorativi ti mandiamo l\'anteprima grafica della placca da approvare; '
                    'dopo il tuo ok stampiamo, programmiamo il tag e spediamo.'
                    if personalizzata else
                    'Programmiamo il tag con i tuoi link e spediamo entro 5 giorni lavorativi. '
                    'La placca arriva pronta: la appoggi sul tavolo o alla cassa e funziona.')
        links = ''.join(_riga(l, u) for l, u in (
            ('Google', ordine.link_google), ('TripAdvisor', ordine.link_tripadvisor),
            ('TheFork', ordine.link_thefork), ('Menù', ordine.menu_link)))
        sped = ordine.spedizione or {}
        indirizzo = ', '.join(x for x in (sped.get('via'), sped.get('cap'), sped.get('citta'),
                                          sped.get('provincia')) if x) if sped else ''
        corpo = f"""
        <p>Ciao {nome or ''},</p>
        <p>grazie: il tuo ordine per <strong>{tier['nome']}</strong> ({ordine.quantita} pz)
        per <strong>{ordine.nome_locale}</strong> è confermato.</p>
        <p>{prossimo}</p>
        <div style="background:#f5f2ee;padding:14px 18px;border-left:3px solid #c4622d;margin:18px 0">
          <p style="margin:0 0 6px"><strong>Cosa aprirà il tap</strong></p>
          {links}
          <p style="margin:8px 0 0;font-size:13px;color:#666">Pagina del tap: <a href="{tap_url}">{tap_url}</a>
          — puoi già provarla dal telefono.</p>
        </div>
        {_riga('Spedizione a', indirizzo)}
        <p>Se vuoi cambiare un link o un dettaglio, rispondi a questa email: lo sistemiamo noi.</p>
        <p>A presto,<br>SB Food Consulting</p>
        """
        invia_email(ordine.email, nome or ordine.nome_locale,
                    f'Ordine confermato — Placca NFC per {ordine.nome_locale}', corpo)

        alle = ', '.join(f'{k} ({v.get("nome")})' for k, v in (ordine.allegati or {}).items()) or '—'
        invia_email(
            ADMIN_EMAIL, 'Simone',
            f'Nuovo ordine Placca NFC — {ordine.nome_locale} ({ordine.importo:.0f}€)',
            f"""<h3>Nuovo ordine Placca NFC</h3>
            {_riga('Locale', ordine.nome_locale)}
            {_riga('Versione', tier['nome'] + (' · ' + ordine.variante if ordine.variante else ''))}
            {_riga('Quantità', ordine.quantita)}
            {_riga('Referente', nome)}{_riga('Email', ordine.email)}{_riga('Telefono', ordine.telefono)}
            {_riga('Spedizione', indirizzo)}
            {links}
            {_riga('Colori', f'{ordine.colore_primario} su {ordine.colore_sfondo}' if ordine.colore_primario else '')}
            {_riga('Testo placca', ordine.testo_placca)}
            {_riga('Allegati', alle)}
            {_riga('Note', ordine.note)}
            {_riga('Importo', f'{ordine.importo:.2f}€')}
            {_riga('Stripe', ordine.stripe_id)}
            <p><a href="{FRONTEND_URL}/admin.html">Apri gestionale → sezione Placche NFC</a></p>""")
    except Exception as e:
        logger.error('Email ordine NFC %s: %s', ordine.id, e, exc_info=True)


# ─── 3. Micro-pagina del tap ──────────────────────────────

@nfc_bp.route('/api/nfc/p/<slug>', methods=['GET'])
def pagina_tap(slug):
    ordine = OrdineNfc.query.filter_by(slug=slug).first()
    if not ordine or ordine.stato == 'annullato':
        return jsonify({'error': 'Placca non trovata'}), 404
    if request.args.get('conta') == '1':
        ordine.tap_count = (ordine.tap_count or 0) + 1
        db.session.commit()
    links = []
    for tipo, url in (('google', ordine.link_google), ('tripadvisor', ordine.link_tripadvisor),
                      ('thefork', ordine.link_thefork)):
        if url:
            links.append({'tipo': tipo, 'url': url})
    menu_url = None
    if ordine.tier == 'personalizzata-menu':
        if (ordine.allegati or {}).get('menu'):
            menu_url = f'{BACKEND_PUBLIC_URL}/api/nfc/menu/{ordine.slug}'
        elif ordine.menu_link:
            menu_url = ordine.menu_link
    logo_url = None
    if (ordine.allegati or {}).get('logo'):
        logo_url = f'{BACKEND_PUBLIC_URL}/api/nfc/logo/{ordine.slug}'
    return jsonify({
        'nome_locale': ordine.nome_locale,
        'links': links,
        'menu_url': menu_url,
        'logo_url': logo_url,
        'colore_primario': ordine.colore_primario or '#c4622d',
        'colore_sfondo': ordine.colore_sfondo or '#2b2d31',
        'testo': ordine.testo_placca or None,
    })


def _servi_allegato(ordine, chiave):
    a = (ordine.allegati or {}).get(chiave)
    if not a:
        return jsonify({'error': 'File non presente'}), 404
    dati = base64.b64decode(a['dati'])
    return Response(dati, mimetype=a['mime'], headers={
        'Content-Disposition': f'inline; filename="{a.get("nome") or chiave}"',
        'Cache-Control': 'public, max-age=3600',
    })


@nfc_bp.route('/api/nfc/menu/<slug>', methods=['GET'])
def menu_pubblico(slug):
    ordine = OrdineNfc.query.filter_by(slug=slug).first_or_404()
    return _servi_allegato(ordine, 'menu')


@nfc_bp.route('/api/nfc/logo/<slug>', methods=['GET'])
def logo_pubblico(slug):
    ordine = OrdineNfc.query.filter_by(slug=slug).first_or_404()
    return _servi_allegato(ordine, 'logo')


# ─── 4. Admin ─────────────────────────────────────────────

@nfc_bp.route('/api/nfc/ordini', methods=['GET'])
@admin_required
def lista_ordini():
    q = OrdineNfc.query
    stato = request.args.get('stato')
    if stato:
        q = q.filter_by(stato=stato)
    else:
        q = q.filter(OrdineNfc.stato != 'in_attesa')  # gli abbandonati non intasano la lista
    if request.args.get('tutti') == '1':
        q = OrdineNfc.query
    return jsonify([o.to_dict() for o in q.order_by(OrdineNfc.created_at.desc()).all()])


CAMPI_MODIFICABILI = ('stato', 'link_google', 'link_tripadvisor', 'link_thefork',
                      'menu_link', 'note', 'testo_placca', 'telefono', 'referente')


@nfc_bp.route('/api/nfc/ordini/<int:oid>', methods=['PATCH'])
@admin_required
def aggiorna_ordine(oid):
    ordine = OrdineNfc.query.get_or_404(oid)
    data = request.get_json() or {}
    for k in CAMPI_MODIFICABILI:
        if k in data:
            v = data[k]
            if k.startswith('link_') or k == 'menu_link':
                v = _pulisci_url(v) or None
            setattr(ordine, k, v)
    db.session.commit()
    return jsonify(ordine.to_dict())


@nfc_bp.route('/api/nfc/ordini/<int:oid>', methods=['DELETE'])
@admin_required
def elimina_ordine(oid):
    ordine = OrdineNfc.query.get_or_404(oid)
    db.session.delete(ordine)
    db.session.commit()
    return jsonify({'ok': True})


@nfc_bp.route('/api/nfc/ordini/<int:oid>/allegato/<chiave>', methods=['GET'])
@admin_required
def scarica_allegato(oid, chiave):
    ordine = OrdineNfc.query.get_or_404(oid)
    a = (ordine.allegati or {}).get(chiave)
    if not a:
        return jsonify({'error': 'File non presente'}), 404
    return Response(base64.b64decode(a['dati']), mimetype=a['mime'], headers={
        'Content-Disposition': f'attachment; filename="{a.get("nome") or chiave}"'})
