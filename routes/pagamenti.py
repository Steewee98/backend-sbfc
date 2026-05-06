import os
import string
import secrets
import logging
import stripe
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from models import db, Pagamento, Studente

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
                    'unit_amount': prodotto['prezzo'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{frontend_url}/academy.html?pagamento=successo&prodotto={prodotto_id}',
            cancel_url=f'{frontend_url}/academy.html?pagamento=annullato',
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
                nome=nome,
                cognome=cognome,
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

        # Invia email
        try:
            from utils.email import invia_email
            from utils.templates import email_benvenuto_academy
            corpo = email_benvenuto_academy(
                nome, email, moduli, password_temp)
            invia_email(
                email, nome,
                "Benvenuto in SB Food Academy — Accesso al corso",
                corpo
            )
            invia_email(
                "info@stefanodemartis.com",
                "Simone",
                f"Nuovo acquisto Academy — {nome_completo}",
                f"""<h3>Nuovo acquisto!</h3>
                <p><strong>Cliente:</strong> {nome_completo}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Prodotto:</strong> {prodotto_id}</p>
                <p><strong>Moduli:</strong> {moduli}</p>
                <p><strong>Importo:</strong> {importo}€</p>
                <a href="https://www.sbfoodconsulting.com/admin.html">
                Apri gestionale →</a>"""
            )
            print("Email inviate con successo")
        except Exception as e:
            print(f"Errore email: {e}")

    except Exception as e:
        print(f"Errore _gestisci_pagamento: {e}")
        import traceback
        traceback.print_exc()


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
