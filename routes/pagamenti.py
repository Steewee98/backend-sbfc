import os
import string
import secrets
import hmac
import hashlib
import logging
import stripe
from urllib.parse import quote
from functools import wraps
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from models import db, Pagamento, Studente, FilePrivato, LeadStrumento

logger = logging.getLogger(__name__)

pagamenti_bp = Blueprint('pagamenti', __name__)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Catalogo prodotti Academy
PRODOTTI = {
    'modulo-1': {
        'nome': 'Modulo 01 — Hai davvero il controllo del tuo ristorante?',
        'prezzo': 1990,
        'moduli': [1],
    },
    'modulo-2': {
        'nome': 'Modulo 02 — Stai pagando per i risultati giusti?',
        'prezzo': 1990,
        'moduli': [2],
    },
    'modulo-3': {
        'nome': 'Modulo 03 — Cosa ti blocca dal crescere?',
        'prezzo': 1990,
        'moduli': [3],
    },
    'modulo-4': {
        'nome': "Modulo 04 — L'Arte di Accogliere nel Food",
        'prezzo': 1990,
        'moduli': [4],
    },
    'modulo-5': {
        'nome': 'Modulo 05 — Come prepararsi al lancio del tuo locale',
        'prezzo': 1990,
        'moduli': [5],
    },
    'corso-completo': {
        'nome': 'SB Food Academy — Corso Completo',
        'prezzo': 9490,
        'moduli': [1, 2, 3, 4, 5],
    },
    # Prodotto PDF a sé (SB Consulting, non Academy): niente moduli/studente,
    # consegna del file via email dopo il pagamento.
    'cruscotto-imprenditore': {
        'nome': "Il Cruscotto dell'Imprenditore — Guida (PDF)",
        'prezzo': 2500,
        'moduli': [],
        'tipo': 'pdf',
        'download_url': 'https://www.sbfoodconsulting.com/assets/pdf/cruscotto/cruscotto-5982dfb162f67bdb.pdf',
    },
    # Manuale di formazione (Academy → #formazione). Il PDF NON sta nei repository
    # (pubblici): è in FilePrivato e si scarica dal link firmato dell'email.
    # Prezzo: 15 € ai nuovi, 12 € a chi ha già lasciato l'email per una scheda.
    'manager-ristorazione': {
        'nome': 'Il manager della ristorazione — Manuale (PDF)',
        'prezzo': 1500,
        'prezzo_lead': 1200,
        'moduli': [],
        'tipo': 'pdf',
        'file_privato': 'manager-ristorazione',
        'success_path': '/academy.html?acquisto=manuale#formazione',
        'cancel_path': '/academy.html#formazione',
    },
}


def _e_lead(email):
    """Ha già lasciato l'email per scaricare una scheda?"""
    email = (email or '').strip().lower()
    if not email:
        return False
    return db.session.query(LeadStrumento.id).filter(
        db.func.lower(LeadStrumento.email) == email).first() is not None


def prezzo_per(prodotto, email):
    """Prezzo in centesimi per quell'email (prezzo_lead se è già nei lead)."""
    if prodotto.get('prezzo_lead') and _e_lead(email):
        return prodotto['prezzo_lead']
    return prodotto['prezzo']


def _firma_download(slug, email):
    secret = os.environ.get('SECRET_KEY', 'dev-fallback-key').encode()
    msg = ('download:%s:%s' % (slug, (email or '').strip().lower())).encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:24]


def link_download(slug, email):
    dom = os.environ.get('RAILWAY_PUBLIC_DOMAIN') or 'web-production-f3794.up.railway.app'
    return 'https://%s/api/download/%s?e=%s&t=%s' % (
        dom, slug, quote((email or '').strip().lower()), _firma_download(slug, email))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


def genera_password(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


# ─── Stripe Checkout ─────────────────────────────────────

@pagamenti_bp.route('/api/checkout', methods=['POST'])
def crea_checkout():
    data = request.get_json()
    if not data or not data.get('prodotto'):
        return jsonify({'error': 'Prodotto mancante'}), 400

    prodotto_id = data['prodotto']
    if prodotto_id not in PRODOTTI:
        return jsonify({'error': 'Prodotto non valido'}), 400

    prodotto = PRODOTTI[prodotto_id]
    frontend_url = os.environ.get('FRONTEND_URL', 'https://www.sbfoodconsulting.com')

    # I prodotti PDF (Cruscotto) tornano alla loro pagina di ringraziamento;
    # i corsi Academy restano su academy.html.
    if prodotto.get('success_path'):
        success_url = frontend_url + prodotto['success_path']
        cancel_url = frontend_url + prodotto.get('cancel_path', '/')
    elif prodotto.get('tipo') == 'pdf':
        success_url = f'{frontend_url}/cruscotto-grazie?pagamento=successo'
        cancel_url = f'{frontend_url}/cruscotto-imprenditore?pagamento=annullato'
    else:
        success_url = f'{frontend_url}/academy.html?pagamento=successo&prodotto={prodotto_id}'
        cancel_url = f'{frontend_url}/academy.html?pagamento=annullato'

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': prodotto['nome'],
                        'description': 'SB Food Academy — sbfoodconsulting.com',
                    },
                    'unit_amount': prezzo_per(prodotto, data.get('email')),
                },
                'quantity': 1,
            }],
            mode='payment',
            # Abilita il campo "codice sconto" nel checkout (es. SCHEDE10 -10%).
            # Il coupon/promo code va creato una volta nella dashboard Stripe.
            allow_promotion_codes=True,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'prodotto_id': prodotto_id,
                'moduli': ','.join(map(str, prodotto['moduli'])),
            },
            billing_address_collection='required',
            customer_email=data.get('email'),
        )
        return jsonify({'url': session.url})
    except Exception as e:
        logger.error(f'Stripe checkout error: {e}')
        return jsonify({'error': 'Errore nella creazione del pagamento'}), 500


# ─── Stripe Webhook ──────────────────────────────────────

@pagamenti_bp.route('/api/webhook/stripe', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except Exception as e:
            logger.error(f'Webhook verification error: {e}')
            return jsonify({'error': 'Webhook verification failed'}), 400
    else:
        event = stripe.Event.construct_from(request.json, stripe.api_key)

    print(f"Webhook ricevuto - tipo: {event['type']}")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        _gestisci_pagamento(session)

    return jsonify({'received': True})


def _gestisci_pagamento(session):
    """Gestisce un pagamento Stripe completato."""
    # Ordini Placca NFC: flusso separato (routes/nfc.py), riconosciuto dal metadata tipo=nfc
    try:
        meta = session.metadata
        tipo = meta.get('tipo', '') if hasattr(meta, 'get') else getattr(meta, 'tipo', '')
        if tipo == 'nfc':
            from routes.nfc import gestisci_pagamento_nfc
            gestisci_pagamento_nfc(session)
            return
    except Exception as e:
        logger.error('Errore webhook NFC: %s', e, exc_info=True)
        return
    try:
        # Accesso corretto agli oggetti Stripe
        customer_details = session.customer_details

        if customer_details:
            email = (customer_details.email or '').lower().strip()
            nome_completo = customer_details.name or ''
        else:
            email = (session.customer_email or '').lower().strip()
            nome_completo = ''

        nome = nome_completo.split()[0] if nome_completo else ''
        cognome = ' '.join(nome_completo.split()[1:]) \
                  if len(nome_completo.split()) > 1 else ''

        # Metadata
        metadata = session.metadata
        moduli_str = metadata.get('moduli', '') \
                     if hasattr(metadata, 'get') \
                     else getattr(metadata, 'moduli', '')
        prodotto_id = metadata.get('prodotto_id', '') \
                      if hasattr(metadata, 'get') \
                      else getattr(metadata, 'prodotto_id', '')

        moduli = [int(m) for m in moduli_str.split(',')
                  if m.strip().isdigit()]
        importo = (session.amount_total or 0) / 100

        print(f"Email: {email}")
        print(f"Nome: {nome_completo}")
        print(f"Moduli: {moduli}")
        print(f"Importo: {importo}")

        # Prodotti PDF (Cruscotto): niente studente/moduli — consegna il file via email
        prodotto_cfg = PRODOTTI.get(prodotto_id, {})
        if prodotto_cfg.get('tipo') == 'pdf':
            if not email:
                print("Email mancante — skip pdf")
                return
            pagamento = Pagamento(
                nome=nome_completo, email=email, prodotto=prodotto_id,
                importo=importo, stato='completato', stripe_id=session.id)
            db.session.add(pagamento)
            db.session.commit()
            _consegna_pdf(nome, email, prodotto_cfg, importo, session.id)
            return

        if not email or not moduli:
            print("Email o moduli mancanti — skip")
            return

        # Cerca o crea studente
        studente = Studente.query.filter_by(email=email).first()
        password_temp = None

        if studente:
            esistenti = studente.moduli_acquistati or []
            studente.moduli_acquistati = list(
                set(esistenti + moduli))
        else:
            password_temp = ''.join(secrets.choice(
                string.ascii_letters + string.digits
            ) for _ in range(10))
            studente = Studente(
                nome=nome_completo,
                email=email,
                password_hash=generate_password_hash(password_temp),
                moduli_acquistati=moduli,
                attivo=True
            )
            db.session.add(studente)

        # Registra pagamento
        pagamento = Pagamento(
            nome=nome_completo,
            email=email,
            prodotto=prodotto_id,
            importo=importo,
            stato='completato',
            stripe_id=session.id
        )
        db.session.add(pagamento)
        db.session.commit()

        # Invia email (via Resend). L'errore NON deve essere silenzioso: se le
        # credenziali non partono, lo studente resta senza accesso (vedi caso Maria).
        try:
            from utils.email import invia_email
            from utils.templates import email_benvenuto_academy
            corpo = email_benvenuto_academy(
                nome, email, moduli, password_temp,
                prodotto_nome=prodotto_id,
                importo=importo,
                stripe_id=session.id
            )
            ok_cred = invia_email(
                email, nome,
                "Benvenuto in SB Food Academy — Accesso al corso",
                corpo
            )
            if not ok_cred:
                logger.error(
                    "CREDENZIALI NON INVIATE a %s (%s) — re-inviarle con "
                    "POST /api/studenti/reset-credenziali", email, prodotto_id)

            avviso = '' if ok_cred else (
                '<p style="color:#b00"><strong>ATTENZIONE:</strong> invio credenziali '
                'al cliente FALLITO. Rigenerale con reset-credenziali.</p>')
            invia_email(
                "info@stefanodemartis.com",
                "Simone",
                f"Nuovo acquisto Academy — {nome_completo}"
                + ('' if ok_cred else ' [CREDENZIALI KO]'),
                f"""<h3>Nuovo acquisto!</h3>
                {avviso}
                <p><strong>Cliente:</strong> {nome_completo}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Prodotto:</strong> {prodotto_id}</p>
                <p><strong>Moduli:</strong> {moduli}</p>
                <p><strong>Importo:</strong> {importo}€</p>
                <a href="https://www.sbfoodconsulting.com/admin.html">
                Apri gestionale →</a>"""
            )
            logger.info("Email acquisto processate per %s (credenziali ok=%s)", email, ok_cred)
        except Exception as e:
            logger.error("Errore invio email acquisto per %s: %s", email, e, exc_info=True)

    except Exception as e:
        print(f"Errore _gestisci_pagamento: {e}")
        import traceback
        traceback.print_exc()


def _consegna_pdf(nome, email, prodotto_cfg, importo, stripe_id):
    """Consegna un prodotto PDF (es. Cruscotto): email col link al cliente + avviso admin."""
    try:
        from utils.email import invia_email
        nome_p = prodotto_cfg.get('nome', 'La tua guida')
        if prodotto_cfg.get('file_privato'):
            link = link_download(prodotto_cfg['file_privato'], email)
        else:
            link = prodotto_cfg.get(
                'download_url', 'https://www.sbfoodconsulting.com/cruscotto-grazie')
        corpo = f"""
        <p>Ciao {nome or ''},</p>
        <p>grazie per l'acquisto di <strong>{nome_p}</strong>.</p>
        <p>Scarica la tua guida in PDF da qui:</p>
        <p><a href="{link}" style="background:#c0552d;color:#fff;padding:12px 22px;
           border-radius:8px;text-decoration:none;display:inline-block">
           Scarica la guida (PDF)</a></p>
        <p style="font-size:13px;color:#666">Se il pulsante non funziona, copia questo
           indirizzo nel browser:<br>{link}</p>
        <p>Buon lavoro,<br>SB Consulting</p>
        """
        invia_email(email, nome or 'Cliente', f"{nome_p} — la tua guida", corpo)

        invia_email(
            "info@stefanodemartis.com", "Simone",
            f"Nuovo acquisto — {nome_p} — {email} ({importo}€)",
            f"""<h3>Nuovo acquisto: {nome_p}</h3>
            <p><strong>Cliente:</strong> {nome or '—'}</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Prodotto:</strong> {nome_p}</p>
            <p><strong>Importo:</strong> {importo}€</p>
            <p><strong>Stripe:</strong> {stripe_id}</p>""")
        logger.info("PDF consegnato via email a %s", email)
    except Exception as e:
        logger.error("Errore consegna PDF a %s: %s", email, e, exc_info=True)


# ─── File privati (manuali venduti) ──────────────────────

@pagamenti_bp.route('/api/download/<slug>', methods=['GET'])
def scarica_file_privato(slug):
    """Link firmato dell'email di consegna: vale solo per chi ha pagato quel prodotto."""
    email = (request.args.get('e') or '').strip().lower()
    firma = request.args.get('t') or ''
    if not email or not hmac.compare_digest(firma, _firma_download(slug, email)):
        return jsonify({'error': 'Link non valido'}), 403
    prodotti = [pid for pid, p in PRODOTTI.items() if p.get('file_privato') == slug]
    pagato = prodotti and db.session.query(Pagamento.id).filter(
        db.func.lower(Pagamento.email) == email,
        Pagamento.prodotto.in_(prodotti),
        Pagamento.stato == 'completato').first()
    if not pagato:
        return jsonify({'error': 'Nessun acquisto per questo indirizzo'}), 403
    f = FilePrivato.query.filter_by(slug=slug).first()
    if not f:
        logger.error('File privato mancante: %s', slug)
        return jsonify({'error': 'File non disponibile, scrivici a info@sbfoodconsulting.com'}), 404
    from io import BytesIO
    return send_file(BytesIO(f.dati), mimetype=f.mime or 'application/pdf',
                     as_attachment=True, download_name=f.nome_file)


@pagamenti_bp.route('/api/admin/file/<slug>', methods=['POST'])
def carica_file_privato(slug):
    """Carica o sostituisce un file privato (multipart, campo «file»). Solo admin."""
    if request.headers.get('X-Admin-Token') != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Non autorizzato'}), 401
    up = request.files.get('file')
    if not up:
        return jsonify({'error': 'File mancante'}), 400
    dati = up.read()
    if not dati or len(dati) > 20 * 1024 * 1024:
        return jsonify({'error': 'File vuoto o oltre 20 MB'}), 400
    f = FilePrivato.query.filter_by(slug=slug).first() or FilePrivato(slug=slug)
    f.nome_file = up.filename or (slug + '.pdf')
    f.mime = up.mimetype or 'application/pdf'
    f.dati = dati
    db.session.add(f)
    db.session.commit()
    return jsonify({'ok': True, 'slug': slug, 'byte': len(dati)}), 200


# ─── Admin endpoints ─────────────────────────────────────

@pagamenti_bp.route('/api/pagamenti', methods=['POST'])
@admin_required
def crea_pagamento():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dati mancanti'}), 400

    required = ['nome', 'email', 'prodotto', 'importo']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Campo {field} obbligatorio'}), 400

    pagamento = Pagamento(
        nome=data['nome'],
        email=data['email'],
        prodotto=data['prodotto'],
        importo=float(data['importo']),
        stato=data.get('stato', 'completato'),
        stripe_id=data.get('stripe_id'),
    )
    db.session.add(pagamento)
    db.session.commit()

    return jsonify(pagamento.to_dict()), 201


@pagamenti_bp.route('/api/pagamenti', methods=['GET'])
@admin_required
def lista_pagamenti():
    query = Pagamento.query

    periodo = request.args.get('periodo')
    if periodo:
        days = {'7d': 7, '30d': 30, '90d': 90}.get(periodo)
        if days:
            since = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Pagamento.created_at >= since)

    pagamenti = query.order_by(Pagamento.created_at.desc()).all()
    return jsonify([p.to_dict() for p in pagamenti])


# ─── Ricevuta PDF ───────────────────────────────────────

@pagamenti_bp.route('/api/ricevuta/<stripe_id>',
                    methods=['GET'])
def scarica_ricevuta(stripe_id):
    token = request.headers.get('X-Admin-Token')
    # Permetti accesso con token admin O con email
    email_param = request.args.get('email', '')

    pagamento = Pagamento.query.filter_by(
        stripe_id=stripe_id).first()

    if not pagamento:
        return jsonify({'error': 'Ricevuta non trovata'}), 404

    # Verifica accesso
    if token != os.environ.get('ADMIN_TOKEN'):
        if not email_param or \
           email_param.lower() != pagamento.email.lower():
            return jsonify({'error': 'Non autorizzato'}), 401

    # Recupera moduli dallo studente
    studente = Studente.query.filter_by(
        email=pagamento.email).first()
    moduli = studente.moduli_acquistati if studente else []

    from utils.ricevuta import genera_ricevuta_pdf
    buffer = genera_ricevuta_pdf(
        nome=pagamento.nome,
        email=pagamento.email,
        moduli=moduli,
        prodotto_nome=pagamento.prodotto,
        importo=pagamento.importo,
        stripe_id=stripe_id
    )

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'ricevuta-sbfood-{stripe_id[:8]}.pdf'
    )
