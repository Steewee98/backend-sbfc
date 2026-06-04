from flask import Blueprint, request, jsonify
from models import db, Prenotazione
from utils.whatsapp import invia_whatsapp
from datetime import datetime, timedelta
from dateutil import parser as dateparser
import os
import secrets
import traceback

prenotazioni_bp = Blueprint('prenotazioni', __name__)

BACKEND_URL = os.environ.get(
    'BACKEND_URL', 'https://web-production-f3794.up.railway.app')


# --- Webhook Calendly ---
@prenotazioni_bp.route('/api/webhooks/calendly', methods=['POST'])
def calendly_webhook():
    """Riceve eventi da Calendly (invitee.created / invitee.canceled)."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data'}), 400

    event_type = data.get('event')
    payload = data.get('payload', {})

    if event_type == 'invitee.created':
        invitee = payload
        nome = invitee.get('name', 'Contatto')
        email = invitee.get('email', '')

        # Calendly mette il telefono in questions_and_answers o text_reminder_number
        telefono = ''
        for qa in invitee.get('questions_and_answers', []):
            if any(k in qa.get('question', '').lower()
                   for k in ['phone', 'telefono', 'numero', 'cellulare']):
                telefono = qa.get('answer', '')
                break
        if not telefono:
            telefono = invitee.get('text_reminder_number', '')

        # Data appuntamento
        scheduled = payload.get('scheduled_event', {})
        start_time = scheduled.get('start_time', '')
        if not start_time:
            # Formato alternativo
            start_time = payload.get('event', {}).get('start_time', '')

        if not start_time:
            return jsonify({'error': 'No start_time'}), 400

        try:
            data_appuntamento = dateparser.parse(start_time)
        except Exception:
            return jsonify({'error': 'Invalid start_time'}), 400

        event_uri = scheduled.get('uri', '') or \
                    payload.get('event', {}).get('uri', '')

        # Controlla duplicati
        if event_uri:
            esistente = Prenotazione.query.filter_by(
                calendly_event_id=event_uri).first()
            if esistente:
                return jsonify({'ok': True, 'msg': 'already exists'})

        token = secrets.token_urlsafe(32)

        pren = Prenotazione(
            nome=nome,
            email=email,
            telefono=telefono,
            data_appuntamento=data_appuntamento,
            calendly_event_id=event_uri,
            stato='pending',
            token_conferma=token
        )
        db.session.add(pren)
        db.session.commit()

        # WhatsApp immediato di conferma prenotazione
        if telefono:
            try:
                nome_breve = nome.split()[0]
                msg = f"""Buongiorno {nome_breve},

la sua chiamata con Simone Braghetta è confermata per il {data_appuntamento.strftime('%d/%m/%Y alle %H:%M')}.

Le invierò un promemoria prima dell'appuntamento.

A presto,
Simone Braghetta
SB Food Consulting"""
                invia_whatsapp(telefono, msg,
                    nome=nome_breve, tipo='conferma_prenotazione')
            except Exception as e:
                print(f"WA conferma prenotazione error: {e}")

        return jsonify({'ok': True, 'id': pren.id}), 201

    elif event_type == 'invitee.canceled':
        event_uri = payload.get('scheduled_event', {}).get('uri', '')
        if event_uri:
            pren = Prenotazione.query.filter_by(
                calendly_event_id=event_uri).first()
            if pren:
                pren.stato = 'cancellato'
                db.session.commit()

        return jsonify({'ok': True, 'msg': 'canceled'})

    return jsonify({'ok': True})


# --- Conferma appuntamento via link ---
@prenotazioni_bp.route('/api/conferma/<token>', methods=['GET'])
def conferma_appuntamento(token):
    pren = Prenotazione.query.filter_by(token_conferma=token).first()
    if not pren:
        return '<h2>Link non valido.</h2>', 404

    if pren.confermato:
        return f"""<html><body style="font-family:Arial;text-align:center;padding:60px">
        <h2>Già confermato!</h2>
        <p>La chiamata con Simone del {pren.data_appuntamento.strftime('%d/%m/%Y alle %H:%M')} è già stata confermata.</p>
        </body></html>"""

    pren.confermato = True
    pren.stato = 'confermato'
    db.session.commit()

    # Notifica Simone
    try:
        invia_whatsapp(
            os.environ.get('SIMONE_PHONE', '+393382636677'),
            f"Confermata la call del {pren.data_appuntamento.strftime('%d/%m/%Y %H:%M')} con {pren.nome}",
            nome='Sistema', tipo='conferma_notifica')
    except Exception:
        pass

    return f"""<html><body style="font-family:Arial;text-align:center;padding:60px;background:#f5f2ee">
    <div style="max-width:500px;margin:auto;background:#fff;padding:40px;border-radius:8px">
    <h2 style="color:#37393f">Confermato!</h2>
    <p style="color:#5a5a5a;font-size:16px">La chiamata con Simone Braghetta del
    <strong>{pren.data_appuntamento.strftime('%d/%m/%Y alle %H:%M')}</strong>
    è confermata.</p>
    <p style="color:#c4622d;font-weight:bold">A presto!</p>
    </div></body></html>"""


# --- Logica reminder (chiamata dal background thread) ---
def _check_reminders():
    """Controlla prenotazioni e invia reminder se necessario."""
    now = datetime.utcnow()
    prenotazioni = Prenotazione.query.filter(
        Prenotazione.stato.in_(['pending', 'reminder_2d']),
        Prenotazione.data_appuntamento > now
    ).all()

    for pren in prenotazioni:
        delta = pren.data_appuntamento - now
        nome_breve = pren.nome.split()[0] if pren.nome else 'Contatto'
        data_str = pren.data_appuntamento.strftime('%d/%m/%Y alle %H:%M')
        link_conferma = f"{BACKEND_URL}/api/conferma/{pren.token_conferma}"

        # Reminder 2 giorni prima
        if not pren.reminder_2d_inviato and delta <= timedelta(days=2):
            if pren.telefono:
                try:
                    msg = f"""Buongiorno {nome_breve},

le ricordo la chiamata con Simone Braghetta prevista per il {data_str}.

Per confermare la sua partecipazione, clicchi qui:
{link_conferma}

Se non può più partecipare, ci faccia sapere rispondendo a questo messaggio.

Grazie,
SB Food Consulting"""
                    invia_whatsapp(pren.telefono, msg,
                        nome=nome_breve, tipo='reminder_2d')
                except Exception as e:
                    print(f"[REMINDER] 2d error: {e}")

            pren.reminder_2d_inviato = True
            pren.stato = 'reminder_2d'
            db.session.commit()

        # Reminder 2 ore prima
        if not pren.reminder_2h_inviato and delta <= timedelta(hours=2):
            if pren.telefono:
                if pren.confermato:
                    msg = f"""Buongiorno {nome_breve},

tra poco la chiamata con Simone Braghetta ({data_str}).

Tutto confermato, a tra poco!

SB Food Consulting"""
                else:
                    msg = f"""Buongiorno {nome_breve},

la chiamata con Simone Braghetta è tra 2 ore ({data_str}).

Non abbiamo ancora ricevuto la sua conferma. Confermi cliccando qui:
{link_conferma}

Senza conferma la chiamata potrebbe non essere effettuata.

SB Food Consulting"""
                try:
                    invia_whatsapp(pren.telefono, msg,
                        nome=nome_breve, tipo='reminder_2h')
                except Exception as e:
                    print(f"[REMINDER] 2h error: {e}")

            pren.reminder_2h_inviato = True
            pren.stato = 'reminder_2h' if not pren.confermato \
                         else 'confermato'
            db.session.commit()

    # Segna come non_confermato le prenotazioni passate senza conferma
    scadute = Prenotazione.query.filter(
        Prenotazione.data_appuntamento <= now,
        Prenotazione.confermato == False,
        Prenotazione.stato != 'non_confermato',
        Prenotazione.stato != 'cancellato'
    ).all()
    for pren in scadute:
        pren.stato = 'non_confermato'
        db.session.commit()


# --- Endpoint admin per vedere le prenotazioni ---
@prenotazioni_bp.route('/api/prenotazioni', methods=['GET'])
def lista_prenotazioni():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    prenotazioni = Prenotazione.query.order_by(
        Prenotazione.data_appuntamento.desc()).all()
    return jsonify([p.to_dict() for p in prenotazioni])


# --- Endpoint per aggiungere prenotazione manuale ---
@prenotazioni_bp.route('/api/prenotazioni', methods=['POST'])
def crea_prenotazione():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or not data.get('nome') or not data.get('data_appuntamento'):
        return jsonify({'error': 'nome e data_appuntamento obbligatori'}), 400

    tok = secrets.token_urlsafe(32)
    pren = Prenotazione(
        nome=data['nome'],
        email=data.get('email', ''),
        telefono=data.get('telefono', ''),
        data_appuntamento=datetime.fromisoformat(data['data_appuntamento']),
        stato='pending',
        token_conferma=tok
    )
    db.session.add(pren)
    db.session.commit()

    return jsonify(pren.to_dict()), 201
