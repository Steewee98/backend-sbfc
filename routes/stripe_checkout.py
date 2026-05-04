from flask import Blueprint, request, jsonify
import stripe
import os
from models import db, Studente, Pagamento
from datetime import datetime
from werkzeug.security import generate_password_hash
import secrets
import string

stripe_bp = Blueprint('stripe', __name__)
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

PRODOTTI = {
    'modulo-1': {
        'nome': 'Modulo 1 — Hai davvero il controllo del tuo ristorante?',
        'prezzo': 1990,
        'moduli': [1]
    },
    'modulo-2': {
        'nome': 'Modulo 2 — Stai pagando per i risultati giusti?',
        'prezzo': 1990,
        'moduli': [2]
    },
    'modulo-3': {
        'nome': 'Modulo 3 — Cosa ti blocca dal crescere?',
        'prezzo': 1990,
        'moduli': [3]
    },
    'modulo-4': {
        'nome': "Modulo 4 — L'Arte di Accogliere nel Food",
        'prezzo': 1990,
        'moduli': [4]
    },
    'modulo-5': {
        'nome': 'Modulo 5 — Come prepararsi al lancio del tuo locale',
        'prezzo': 1990,
        'moduli': [5]
    },
    'corso-completo': {
        'nome': 'SB Food Academy — Corso Completo',
        'prezzo': 9490,
        'moduli': [1, 2, 3, 4, 5]
    }
}


@stripe_bp.route('/api/checkout', methods=['POST'])
def crea_checkout():
    data = request.json
    prodotto_id = data.get('prodotto')

    if prodotto_id not in PRODOTTI:
        return jsonify({'error': 'Prodotto non trovato'}), 400

    prodotto = PRODOTTI[prodotto_id]
    frontend_url = os.environ.get(
        'FRONTEND_URL',
        'https://www.sbfoodconsulting.com'
    )

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': prodotto['nome'],
                        'description': 'SB Food Academy — '
                                       'sbfoodconsulting.com'
                    },
                    'unit_amount': prodotto['prezzo'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{frontend_url}/academy.html"
                        f"?pagamento=successo&prodotto={prodotto_id}",
            cancel_url=f"{frontend_url}/academy.html"
                       f"?pagamento=annullato",
            metadata={
                'prodotto_id': prodotto_id,
                'moduli': ','.join(map(str, prodotto['moduli']))
            },
            billing_address_collection='required',
            customer_email=data.get('email')
        )
        return jsonify({'url': session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stripe_bp.route('/api/webhook/stripe', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        else:
            event = stripe.Event.construct_from(
                request.json, stripe.api_key
            )
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']

        email = session.get('customer_details', {}).get('email', '')
        nome_completo = session.get(
            'customer_details', {}).get('name', '')
        nome = nome_completo.split()[0] if nome_completo else ''
        cognome = ' '.join(nome_completo.split()[1:]) \
                  if len(nome_completo.split()) > 1 else ''
        moduli = [int(m) for m in
                  session['metadata']['moduli'].split(',')]
        prodotto_nome = session['metadata']['prodotto_id']
        importo = session['amount_total'] / 100

        if email:
            studente = Studente.query.filter_by(
                email=email.lower()).first()
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
                    nome=nome or email.split('@')[0],
                    email=email.lower(),
                    password_hash=generate_password_hash(
                        password_temp),
                    moduli_acquistati=moduli,
                )
                db.session.add(studente)

            pagamento = Pagamento(
                nome=nome_completo or email,
                email=email.lower(),
                prodotto=prodotto_nome,
                importo=importo,
                stato='completato',
                stripe_id=session['id']
            )
            db.session.add(pagamento)
            db.session.commit()

            # Invia email con credenziali
            try:
                from utils.email import invia_email
                from utils.templates import email_benvenuto_academy
                corpo = email_benvenuto_academy(
                    nome, email, moduli, password_temp)
                invia_email(
                    email, nome,
                    "Benvenuto in SB Food Academy — "
                    "Accesso al corso",
                    corpo
                )
                # Notifica a Simone
                invia_email(
                    "info@stefanodemartis.com",
                    "Simone",
                    f"Nuovo acquisto Academy — {nome_completo}",
                    f"""<h3>Nuovo acquisto!</h3>
                    <p><strong>Cliente:</strong>
                    {nome_completo}</p>
                    <p><strong>Email:</strong> {email}</p>
                    <p><strong>Prodotto:</strong>
                    {prodotto_nome}</p>
                    <p><strong>Importo:</strong>
                    {importo}&euro;</p>"""
                )
            except Exception as e:
                print(f"Email non inviata: {e}")

    return jsonify({'success': True})
