import os
import logging
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Contatto
from utils.email import invia_email
from utils.templates import email_benvenuto_contatto
from utils.whatsapp import invia_whatsapp

logger = logging.getLogger(__name__)

contatti_bp = Blueprint('contatti', __name__)

STATI_VALIDI = ['nuovo', 'contattato', 'trattativa', 'chiuso_vinto', 'chiuso_perso']


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


@contatti_bp.route('/api/contatti', methods=['POST'])
def crea_contatto():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dati mancanti'}), 400

    required = ['nome', 'email']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Campo {field} obbligatorio'}), 400

    contatto = Contatto(
        nome=data['nome'],
        cognome=data['cognome'],
        email=data['email'],
        telefono=data.get('telefono', ''),
        tipo_locale=data.get('tipo_locale', ''),
        messaggio=data.get('messaggio', ''),
    )
    db.session.add(contatto)
    db.session.commit()

    nome = data['nome']
    cognome = data['cognome']
    email = data['email']
    telefono = data.get('telefono', '')
    tipo_locale = data.get('tipo_locale', '')
    messaggio = data.get('messaggio', '')

    if tipo_locale == 'Lead magnet checklist':
        corpo = f"""
        <table width="100%" cellpadding="0"
        cellspacing="0" style="background:#f5f2ee;
        font-family:Arial,sans-serif">
        <tr><td align="center" style="padding:40px 20px">
        <table width="600" cellpadding="0" cellspacing="0"
        style="max-width:600px;width:100%">

        <tr><td style="background:#37393f;padding:32px 40px;
        text-align:center;border-radius:6px 6px 0 0">
            <p style="color:#c4622d;font-size:11px;
            letter-spacing:3px;margin:0 0 8px;
            text-transform:uppercase;font-weight:600">
            SB Food Consulting</p>
            <h1 style="color:#fff;font-family:Georgia,serif;
            font-size:24px;margin:0;font-weight:400">
            Ecco la tua checklist gratuita.</h1>
        </td></tr>

        <tr><td style="background:#fff;padding:40px;
        border-radius:0 0 6px 6px">
            <p style="color:#5a5a5a;font-size:15px;
            line-height:1.8;margin:0 0 24px">
            Ciao {nome},<br><br>
            grazie per aver scaricato
            <strong>La Checklist del Ristoratore
            Consapevole</strong>.<br><br>
            Trovi il PDF allegato a questa email.
            Prenditi 10 minuti per rispondere
            con onestà a tutte le domande —
            i risultati potrebbero sorprenderti.</p>

            <table cellpadding="0" cellspacing="0"
            style="margin:0 auto 32px">
            <tr><td style="background:#c4622d;
            border-radius:4px">
                <a href="https://www.sbfoodconsulting.com/assets/pdf/checklist-ristoratore.pdf"
                style="display:block;padding:16px 32px;
                color:#fff;text-decoration:none;
                font-size:15px;font-weight:bold">
                ↓ Scarica la checklist PDF</a>
            </td></tr></table>

            <hr style="border:none;border-top:
            1px solid #edeae5;margin:0 0 24px">

            <p style="color:#c4622d;font-size:11px;
            font-weight:bold;letter-spacing:2px;
            text-transform:uppercase;margin:0 0 12px">
            Vuoi approfondire?</p>

            <p style="color:#5a5a5a;font-size:14px;
            line-height:1.8;margin:0 0 24px">
            Ogni area della checklist corrisponde
            a un modulo di SB Food Academy —
            il percorso formativo costruito su
            30 anni di lavoro nei ristoranti italiani.</p>

            <table cellpadding="0" cellspacing="0"
            style="margin:0 auto">
            <tr><td style="border:2px solid #37393f;
            border-radius:4px">
                <a href="https://www.sbfoodconsulting.com/academy.html"
                style="display:block;padding:14px 28px;
                color:#37393f;text-decoration:none;
                font-size:14px;font-weight:bold">
                Scopri SB Food Academy →</a>
            </td></tr></table>
        </td></tr>

        <tr><td style="padding:24px;text-align:center">
            <p style="color:#a0a0a0;font-size:12px;margin:0">
            SB Food Consulting — Roma, Italia<br>
            info@sbfoodconsulting.com</p>
        </td></tr>

        </table>
        </td></tr></table>
        """
        try:
            invia_email(
                email, nome,
                "La tua checklist gratuita — SB Food Consulting",
                corpo
            )
            # Notifica a Simone
            invia_email(
                "info@stefanodemartis.com",
                "Simone",
                f"Nuovo lead magnet — {nome} ({email})",
                f"""<h3>Nuovo download checklist</h3>
                <p><strong>Nome:</strong> {nome}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><a href="https://www.sbfoodconsulting.com/admin.html">
                Apri gestionale →</a></p>"""
            )
        except Exception as e:
            print(f"Email lead magnet non inviata: {e}")

        if telefono:
            try:
                messaggio_wa = f"""Buongiorno {nome},

grazie per averci contattato tramite SB Food Consulting.

Sono Simone Braghetta. Ho ricevuto la sua richiesta e la contatterò personalmente entro 24 ore.

Nel frattempo può prenotare una chiamata gratuita di 30 minuti direttamente qui:
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone Braghetta
SB Food Consulting"""
                invia_whatsapp(telefono, messaggio_wa, nome=nome, tipo='form_contatti')
            except Exception as e:
                print(f"WhatsApp non inviato: {e}")
    else:
        # Email benvenuto normale
        try:
            corpo_cliente = email_benvenuto_contatto(nome)
            invia_email(email, nome,
                "Grazie per averci contattato — SB Food Consulting",
                corpo_cliente)

            # Notifica a Simone
            invia_email(
                "info@stefanodemartis.com",
                "Simone Braghetta",
                f"Nuovo contatto dal sito — {nome} {cognome}",
                f"""
                <h3>Nuovo contatto ricevuto</h3>
                <p><strong>Nome:</strong> {nome} {cognome}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Telefono:</strong> {telefono}</p>
                <p><strong>Tipo locale:</strong> {tipo_locale}</p>
                <p><strong>Messaggio:</strong><br>{messaggio}</p>
                <p><a href="https://www.sbfoodconsulting.com/admin.html">
                Apri il gestionale &rarr;</a></p>
                """
            )
        except Exception as e:
            logger.error(f"Email non inviata: {e}")

        if telefono:
            try:
                messaggio_wa = f"""Buongiorno {nome},

grazie per averci contattato tramite SB Food Consulting.

Sono Simone Braghetta. Ho ricevuto la sua richiesta e la contatterò personalmente entro 24 ore.

Nel frattempo può prenotare una chiamata gratuita di 30 minuti direttamente qui:
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone Braghetta
SB Food Consulting"""
                invia_whatsapp(telefono, messaggio_wa, nome=nome, tipo='form_contatti')
            except Exception as e:
                print(f"WhatsApp non inviato: {e}")

    return jsonify({'success': True, 'id': contatto.id}), 201


@contatti_bp.route('/api/contatti', methods=['GET'])
@admin_required
def lista_contatti():
    query = Contatto.query

    stato = request.args.get('stato')
    if stato:
        query = query.filter_by(stato=stato)

    tipo = request.args.get('tipo_locale')
    if tipo:
        query = query.filter_by(tipo_locale=tipo)

    contatti = query.order_by(Contatto.created_at.desc()).all()
    return jsonify([c.to_dict() for c in contatti])


@contatti_bp.route('/api/test-email', methods=['GET'])
@admin_required
def test_email():
    """Endpoint debug — testa invio email via Resend."""
    import resend as _resend

    api_key = os.environ.get('RESEND_API_KEY', '')
    mail_from = os.environ.get('MAIL_FROM', '')

    result = {
        'resend_api_key_set': bool(api_key),
        'resend_api_key_preview': api_key[:8] + '***' if api_key else None,
        'mail_from': mail_from,
    }

    if not api_key:
        result['error'] = 'RESEND_API_KEY mancante'
        return jsonify(result), 400

    try:
        _resend.api_key = api_key
        params: _resend.Emails.SendParams = {
            "from": mail_from or "SB Food Consulting <onboarding@resend.dev>",
            "to": ["delivered@resend.dev"],
            "subject": "Test email — SB Food Consulting",
            "text": "Test invio email da Railway.",
        }
        email = _resend.Emails.send(params)
        result['status'] = 'OK'
        result['email_id'] = email['id']
    except Exception as e:
        result['status'] = 'FAILED'
        result['error'] = str(e)

    return jsonify(result)


@contatti_bp.route('/api/contatti/<int:id>', methods=['PATCH'])
@admin_required
def aggiorna_contatto(id):
    contatto = Contatto.query.get_or_404(id)
    data = request.get_json()

    if 'stato' in data:
        if data['stato'] not in STATI_VALIDI:
            return jsonify({'error': f'Stato non valido. Valori: {STATI_VALIDI}'}), 400
        contatto.stato = data['stato']

    contatto.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify(contatto.to_dict())
