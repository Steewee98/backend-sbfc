import requests as http_requests
from flask import Blueprint, request, jsonify
from models import db, Prenotazione, Contatto
from utils.whatsapp import invia_whatsapp
from datetime import datetime, timedelta
from dateutil import parser as dateparser
import os
import secrets

prenotazioni_bp = Blueprint('prenotazioni', __name__)

BACKEND_URL = os.environ.get(
    'BACKEND_URL', 'https://web-production-f3794.up.railway.app')
CALENDLY_TOKEN = os.environ.get('CALENDLY_TOKEN', '')
CALENDLY_USER = os.environ.get(
    'CALENDLY_USER',
    'https://api.calendly.com/users/85e30fc0-9d3a-4d9e-b6a5-55e378b4a696')


# --- Sync Calendly (polling) ---
def _sync_calendly():
    """Legge eventi Calendly via API e importa nuove prenotazioni."""
    token = CALENDLY_TOKEN
    if not token:
        return 0

    headers = {'Authorization': f'Bearer {token}'}

    # Prendi eventi futuri attivi
    now = datetime.utcnow()
    params = {
        'user': CALENDLY_USER,
        'min_start_time': (now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'status': 'active',
        'count': 50
    }
    res = http_requests.get(
        'https://api.calendly.com/scheduled_events',
        headers=headers, params=params, timeout=15)

    if res.status_code != 200:
        print(f"[CALENDLY] API error: {res.status_code}")
        return 0

    events = res.json().get('collection', [])
    nuovi = 0

    for event in events:
        event_uri = event.get('uri', '')

        # Già importato?
        if Prenotazione.query.filter_by(
                calendly_event_id=event_uri).first():
            continue

        start_time = event.get('start_time', '')
        if not start_time:
            continue

        data_appuntamento = dateparser.parse(start_time)

        # Prendi invitee per nome, email, telefono
        inv_res = http_requests.get(
            f"{event_uri}/invitees",
            headers=headers, timeout=15)

        nome = 'Contatto'
        email = ''
        telefono = ''

        if inv_res.status_code == 200:
            invitees = inv_res.json().get('collection', [])
            if invitees:
                inv = invitees[0]
                nome = inv.get('name', 'Contatto').strip()
                email = inv.get('email', '')

                # Telefono da questions_and_answers
                for qa in inv.get('questions_and_answers', []):
                    q = qa.get('question', '').lower()
                    if any(k in q for k in ['phone', 'telefono',
                                            'numero', 'cellulare']):
                        telefono = qa.get('answer', '')
                        break
                if not telefono:
                    telefono = inv.get('text_reminder_number') or ''

        # Se non abbiamo il telefono, cercalo nei contatti
        if not telefono and email:
            contatto = Contatto.query.filter_by(email=email).first()
            if contatto and contatto.telefono:
                telefono = contatto.telefono

        if not telefono and nome:
            nome_parts = nome.split()
            # Cerca per ogni parte del nome (match esatto o contenuto)
            for parte in nome_parts:
                if len(parte) < 3:
                    continue
                pat = f'%{parte.lower()}%'
                contatto = Contatto.query.filter(
                    db.or_(
                        db.func.lower(Contatto.nome).like(pat),
                        db.func.lower(Contatto.cognome).like(pat)
                    ),
                    Contatto.telefono != '',
                    Contatto.telefono.isnot(None)
                ).first()
                if contatto:
                    telefono = contatto.telefono
                    break

        tok = secrets.token_urlsafe(32)
        pren = Prenotazione(
            nome=nome,
            email=email,
            telefono=telefono,
            data_appuntamento=data_appuntamento,
            calendly_event_id=event_uri,
            stato='pending',
            token_conferma=tok
        )
        db.session.add(pren)
        db.session.commit()
        nuovi += 1

        # WhatsApp immediato di conferma
        if telefono:
            try:
                nome_breve = nome.split()[0]
                # Converti a ora italiana (UTC+2)
                ora_ita = data_appuntamento + timedelta(hours=2)
                msg = f"""Buongiorno {nome_breve},

la sua chiamata con Simone Braghetta e' confermata per il {ora_ita.strftime('%d/%m/%Y alle %H:%M')}.

Le invieremo un promemoria prima dell'appuntamento.

A presto,
Simone Braghetta
SB Food Consulting"""
                invia_whatsapp(telefono, msg,
                    nome=nome_breve, tipo='conferma_prenotazione')
            except Exception as e:
                print(f"[CALENDLY] WA error: {e}")

        print(f"[CALENDLY] Nuova prenotazione: {nome} — {data_appuntamento}")

    return nuovi


# --- Conferma appuntamento via link ---
@prenotazioni_bp.route('/api/conferma/<token>', methods=['GET'])
def conferma_appuntamento(token):
    pren = Prenotazione.query.filter_by(token_conferma=token).first()
    if not pren:
        return '<h2>Link non valido.</h2>', 404

    if pren.confermato:
        ora_ita = pren.data_appuntamento + timedelta(hours=2)
        return f"""<html><body style="font-family:Arial;text-align:center;padding:60px">
        <h2>Gia' confermato!</h2>
        <p>La chiamata con Simone del {ora_ita.strftime('%d/%m/%Y alle %H:%M')} e' gia' stata confermata.</p>
        </body></html>"""

    pren.confermato = True
    pren.stato = 'confermato'
    db.session.commit()

    # Notifica Simone
    try:
        ora_ita = pren.data_appuntamento + timedelta(hours=2)
        invia_whatsapp(
            os.environ.get('SIMONE_PHONE', '+393382636677'),
            f"Confermata la call del {ora_ita.strftime('%d/%m/%Y %H:%M')} con {pren.nome}",
            nome='Sistema', tipo='conferma_notifica')
    except Exception:
        pass

    ora_ita = pren.data_appuntamento + timedelta(hours=2)
    return f"""<html><body style="font-family:Arial;text-align:center;padding:60px;background:#f5f2ee">
    <div style="max-width:500px;margin:auto;background:#fff;padding:40px;border-radius:8px">
    <h2 style="color:#37393f">Confermato!</h2>
    <p style="color:#5a5a5a;font-size:16px">La chiamata con Simone Braghetta del
    <strong>{ora_ita.strftime('%d/%m/%Y alle %H:%M')}</strong>
    e' confermata.</p>
    <p style="color:#c4622d;font-weight:bold">A presto!</p>
    </div></body></html>"""


# --- Logica reminder (chiamata dal background thread) ---
def _check_reminders():
    """Controlla prenotazioni e invia reminder se necessario."""
    # Prima sincronizza da Calendly
    try:
        nuovi = _sync_calendly()
        if nuovi > 0:
            print(f"[CALENDLY] {nuovi} nuove prenotazioni importate")
    except Exception as e:
        print(f"[CALENDLY] Sync error: {e}")

    now = datetime.utcnow()
    prenotazioni = Prenotazione.query.filter(
        Prenotazione.stato.in_(['pending', 'reminder_2d', 'confermato']),
        Prenotazione.data_appuntamento > now
    ).all()

    for pren in prenotazioni:
        delta = pren.data_appuntamento - now
        nome_breve = pren.nome.split()[0] if pren.nome else 'Contatto'
        ora_ita = pren.data_appuntamento + timedelta(hours=2)
        data_str = ora_ita.strftime('%d/%m/%Y alle %H:%M')
        link_conferma = f"{BACKEND_URL}/api/conferma/{pren.token_conferma}"

        # Reminder 2 giorni prima
        if not pren.reminder_2d_inviato and delta <= timedelta(days=2):
            if pren.telefono:
                try:
                    msg = f"""Buongiorno {nome_breve},

le ricordo la chiamata con Simone Braghetta prevista per il {data_str}.

Per confermare la sua partecipazione, clicchi qui:
{link_conferma}

Se non puo' piu' partecipare, ci faccia sapere rispondendo a questo messaggio.

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

la chiamata con Simone Braghetta e' tra 2 ore ({data_str}).

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


# --- Endpoint admin ---
@prenotazioni_bp.route('/api/prenotazioni', methods=['GET'])
def lista_prenotazioni():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    prenotazioni = Prenotazione.query.order_by(
        Prenotazione.data_appuntamento.desc()).all()
    return jsonify([p.to_dict() for p in prenotazioni])


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
        data_appuntamento=dateparser.parse(data['data_appuntamento']),
        stato='pending',
        token_conferma=tok
    )
    db.session.add(pren)
    db.session.commit()

    return jsonify(pren.to_dict()), 201


@prenotazioni_bp.route('/api/prenotazioni/<int:pren_id>', methods=['PATCH'])
def aggiorna_prenotazione(pren_id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    pren = Prenotazione.query.get(pren_id)
    if not pren:
        return jsonify({'error': 'Prenotazione non trovata'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dati mancanti'}), 400

    if 'confermato' in data:
        pren.confermato = data['confermato']
        if data['confermato']:
            pren.stato = 'confermato'

    if 'stato' in data:
        pren.stato = data['stato']

    if 'telefono' in data:
        pren.telefono = data['telefono']

    if 'nome' in data:
        pren.nome = data['nome']

    if 'reminder_2d_inviato' in data:
        pren.reminder_2d_inviato = data['reminder_2d_inviato']

    if 'reminder_2h_inviato' in data:
        pren.reminder_2h_inviato = data['reminder_2h_inviato']

    db.session.commit()
    return jsonify(pren.to_dict())
