import os
import json
import string
import secrets
import logging
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from models import db, Pagamento, Studente

logger = logging.getLogger(__name__)

pagamenti_bp = Blueprint('pagamenti', __name__)

# Catalogo prodotti Academy
PRODOTTI = {
    'modulo_1': {
        'nome': 'Modulo 01 — Hai davvero il controllo del tuo ristorante?',
        'prezzo': 1990,
        'moduli': [1],
    },
    'modulo_2': {
        'nome': 'Modulo 02 — Stai pagando per i risultati giusti?',
        'prezzo': 1990,
        'moduli': [2],
    },
    'modulo_3': {
        'nome': 'Modulo 03 — Cosa ti blocca dal crescere?',
        'prezzo': 1990,
        'moduli': [3],
    },
    'modulo_4': {
        'nome': "Modulo 04 — L'Arte di Accogliere nel Food",
        'prezzo': 1990,
        'moduli': [4],
    },
    'modulo_5': {
        'nome': 'Modulo 05 — Come prepararsi al lancio del tuo locale',
        'prezzo': 1990,
        'moduli': [5],
    },
    'corso_completo': {
        'nome': 'SB Food Academy — Corso Completo',
        'prezzo': 9490,
        'moduli': [1, 2, 3, 4, 5],
    },
}


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

@pagamenti_bp.route('/api/pagamenti/checkout', methods=['POST'])
def crea_checkout():
    import stripe
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

    data = request.get_json()
    if not data or not data.get('prodotto'):
        return jsonify({'error': 'Prodotto mancante'}), 400

    prodotto_id = data['prodotto']
    if prodotto_id not in PRODOTTI:
        return jsonify({'error': 'Prodotto non valido'}), 400

    prodotto = PRODOTTI[prodotto_id]
    frontend_url = os.environ.get('FRONTEND_URL', 'https://sito-sbfc-production.up.railway.app')

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': prodotto['nome'],
                        'description': 'SB Food Academy',
                    },
                    'unit_amount': prodotto['prezzo'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{frontend_url}/academy.html?pagamento=successo',
            cancel_url=f'{frontend_url}/academy.html?pagamento=annullato',
            metadata={
                'prodotto_id': prodotto_id,
                'moduli': json.dumps(prodotto['moduli']),
            },
        )
        return jsonify({'url': session.url})
    except Exception as e:
        logger.error(f'Stripe checkout error: {e}')
        return jsonify({'error': 'Errore nella creazione del pagamento'}), 500


# ─── Stripe Webhook ──────────────────────────────────────

@pagamenti_bp.route('/api/webhook/stripe', methods=['POST'])
def stripe_webhook():
    import stripe
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

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
        event = json.loads(payload)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        _gestisci_pagamento(session)

    return jsonify({'received': True})


def _gestisci_pagamento(session):
    """Gestisce un pagamento Stripe completato."""
    email = session.get('customer_details', {}).get('email', '')
    nome = session.get('customer_details', {}).get('name', '')
    metadata = session.get('metadata', {})
    prodotto_id = metadata.get('prodotto_id', '')
    moduli = json.loads(metadata.get('moduli', '[]'))
    importo = session.get('amount_total', 0) / 100

    # Salva pagamento
    pagamento = Pagamento(
        nome=nome or email,
        email=email,
        prodotto=PRODOTTI.get(prodotto_id, {}).get('nome', prodotto_id),
        importo=importo,
        stato='completato',
        stripe_id=session.get('id', ''),
    )
    db.session.add(pagamento)

    # Crea o aggiorna studente
    studente = Studente.query.filter_by(email=email).first()
    password_generata = None

    if studente:
        existing = set(studente.moduli_acquistati or [])
        existing.update(moduli)
        studente.moduli_acquistati = sorted(list(existing))
    else:
        password_generata = genera_password()
        studente = Studente(
            nome=nome or email.split('@')[0],
            email=email,
            password_hash=generate_password_hash(password_generata),
            moduli_acquistati=moduli,
        )
        db.session.add(studente)

    db.session.commit()

    # Invia email con credenziali per nuovi studenti
    if password_generata:
        try:
            from services.email_service import invia_email_credenziali
            invia_email_credenziali(studente.nome, email, password_generata, moduli)
        except Exception as e:
            logger.error(f'Error sending credentials email: {e}')

    logger.info(f'Payment completed: {email} - {prodotto_id} - EUR {importo}')


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
