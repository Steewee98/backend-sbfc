from flask import Blueprint, request, jsonify
from models import db
from datetime import datetime, timedelta
from collections import defaultdict
import os
import time
import logging

logger = logging.getLogger(__name__)

checklist_bp = Blueprint('checklist', __name__)


class RisultatoChecklist(db.Model):
    __tablename__ = 'risultati_checklist'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200))
    email = db.Column(db.String(200))
    session_id = db.Column(db.String(64))
    punteggio_totale = db.Column(db.Integer)
    punteggio_food_cost = db.Column(db.Integer)
    punteggio_personale = db.Column(db.Integer)
    punteggio_menu = db.Column(db.Integer)
    punteggio_comunicazione = db.Column(db.Integer)
    punteggio_numeri = db.Column(db.Integer)
    risposte = db.Column(db.JSON)
    email_inviata = db.Column(db.Boolean, default=False)
    tipo_email = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EventoChecklist(db.Model):
    __tablename__ = 'eventi_checklist'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), nullable=False)
    evento = db.Column(db.String(30), nullable=False)
    dettaglio = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_agent = db.Column(db.String(500))
    referrer = db.Column(db.String(500))


# --- Rate limiter ---
_rate_limit = defaultdict(list)
RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW = 60

EVENTI_VALIDI = {'vista', 'iniziata', 'domanda', 'completata', 'email_lasciata', 'pdf_scaricato'}


def _check_rate_limit(ip):
    now = time.time()
    _rate_limit[ip] = [t for t in _rate_limit[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit[ip].append(now)
    return True


# --- Tracking ---

@checklist_bp.route('/api/checklist/evento', methods=['POST'])
def traccia_evento():
    ip = request.remote_addr or 'unknown'
    if not _check_rate_limit(ip):
        return jsonify({'error': 'Too many requests'}), 429

    data = request.json or {}
    session_id = (data.get('session_id') or '').strip()
    evento = (data.get('evento') or '').strip()
    dettaglio = data.get('dettaglio')

    if not session_id or len(session_id) > 64:
        return jsonify({'error': 'Invalid session_id'}), 400
    if evento not in EVENTI_VALIDI:
        return jsonify({'error': 'Invalid evento'}), 400
    if dettaglio is not None:
        try:
            dettaglio = int(dettaglio)
            if dettaglio < 1 or dettaglio > 20:
                dettaglio = None
        except (ValueError, TypeError):
            dettaglio = None

    ev = EventoChecklist(
        session_id=session_id,
        evento=evento,
        dettaglio=dettaglio,
        user_agent=(request.headers.get('User-Agent', '') or '')[:500],
        referrer=(data.get('referrer') or '')[:500]
    )
    db.session.add(ev)
    db.session.commit()
    return jsonify({'ok': True}), 201


# --- Save result ---

@checklist_bp.route('/api/checklist', methods=['POST'])
def salva_checklist():
    data = request.json

    risultato = RisultatoChecklist(
        nome=data.get('nome') or None,
        email=data.get('email') or None,
        session_id=data.get('session_id') or None,
        punteggio_totale=data.get('punteggio_totale'),
        punteggio_food_cost=data.get('punteggio_food_cost'),
        punteggio_personale=data.get('punteggio_personale'),
        punteggio_menu=data.get('punteggio_menu'),
        punteggio_comunicazione=data.get('punteggio_comunicazione'),
        punteggio_numeri=data.get('punteggio_numeri'),
        risposte=data.get('risposte', [])
    )
    db.session.add(risultato)
    db.session.commit()

    nome = data.get('nome', '')
    email = data.get('email', '')

    if email:
        _invia_emails(risultato, nome, email)

    return jsonify({'success': True, 'id': risultato.id}), 201


# --- Email submission (post-quiz, optional) ---

@checklist_bp.route('/api/checklist/email', methods=['POST'])
def aggiorna_email_checklist():
    data = request.json or {}
    session_id = (data.get('session_id') or '').strip()
    nome = (data.get('nome') or '').strip()
    email = (data.get('email') or '').strip()

    if not session_id:
        return jsonify({'error': 'session_id richiesto'}), 400
    if not email or '@' not in email:
        return jsonify({'error': 'Email non valida'}), 400

    risultato = RisultatoChecklist.query.filter_by(session_id=session_id)\
        .order_by(RisultatoChecklist.created_at.desc()).first()

    if not risultato:
        return jsonify({'error': 'Risultato non trovato'}), 404

    risultato.nome = nome or risultato.nome
    risultato.email = email
    db.session.commit()

    _invia_emails(risultato, nome or 'Ristoratore', email)

    return jsonify({'success': True}), 200


def _invia_emails(risultato, nome, email):
    punteggio = risultato.punteggio_totale or 0
    score_data = {
        'punteggio_food_cost': risultato.punteggio_food_cost,
        'punteggio_personale': risultato.punteggio_personale,
        'punteggio_menu': risultato.punteggio_menu,
        'punteggio_comunicazione': risultato.punteggio_comunicazione,
        'punteggio_numeri': risultato.punteggio_numeri,
    }

    # Notifica a Simone
    try:
        from utils.email import invia_email
        invia_email(
            'info@sbfoodconsulting.com',
            'Simone',
            f'Nuova checklist — {nome} ({punteggio}/20)',
            f"""<h3>Nuova checklist completata</h3>
            <p><strong>Nome:</strong> {nome}</p>
            <p><strong>Email:</strong> {email}</p>
            <p><strong>Punteggio:</strong> {punteggio}/20</p>
            <p><strong>Food Cost:</strong> {risultato.punteggio_food_cost}/4</p>
            <p><strong>Personale:</strong> {risultato.punteggio_personale}/4</p>
            <p><strong>Menu:</strong> {risultato.punteggio_menu}/4</p>
            <p><strong>Comunicazione:</strong> {risultato.punteggio_comunicazione}/4</p>
            <p><strong>Numeri:</strong> {risultato.punteggio_numeri}/4</p>
            <a href="https://www.sbfoodconsulting.com/admin.html">Apri gestionale &rarr;</a>"""
        )
    except Exception as e:
        logger.error(f"Email notifica non inviata: {e}")

    # Email categorizzata all'utente
    try:
        from utils.email import invia_email
        from utils.templates_checklist import (
            email_checklist_critico,
            email_checklist_medio,
            email_checklist_buono
        )

        if punteggio <= 8:
            tipo = 'critico'
            oggetto = "Il tuo locale ha bisogno di un intervento — SB Food Consulting"
            corpo = email_checklist_critico(nome, punteggio, score_data)
        elif punteggio <= 14:
            tipo = 'medio'
            oggetto = "Abbiamo trovato le aree critiche del tuo locale — SB Food Consulting"
            corpo = email_checklist_medio(nome, punteggio, score_data)
        else:
            tipo = 'buono'
            oggetto = "Il tuo locale ha basi solide — ecco il prossimo passo"
            corpo = email_checklist_buono(nome, punteggio, score_data)

        if invia_email(email, nome, oggetto, corpo):
            risultato.email_inviata = True
            risultato.tipo_email = tipo
            db.session.commit()
            logger.info(f"Email checklist '{tipo}' inviata a {email}")
        else:
            logger.error(f"Email checklist fallita per {email} — invia_email returned False")

    except Exception as e:
        logger.error(f"Email checklist non inviata: {e}", exc_info=True)


# --- Admin endpoints ---

def _build_checklist_email(r):
    from utils.templates_checklist import (
        email_checklist_critico, email_checklist_medio, email_checklist_buono
    )
    data = {
        'punteggio_food_cost': r.punteggio_food_cost,
        'punteggio_personale': r.punteggio_personale,
        'punteggio_menu': r.punteggio_menu,
        'punteggio_comunicazione': r.punteggio_comunicazione,
        'punteggio_numeri': r.punteggio_numeri,
    }
    p = r.punteggio_totale or 0
    if p <= 8:
        tipo = 'critico'
        oggetto = "Il tuo locale ha bisogno di un intervento — SB Food Consulting"
        corpo = email_checklist_critico(r.nome or 'Ristoratore', p, data)
    elif p <= 14:
        tipo = 'medio'
        oggetto = "Abbiamo trovato le aree critiche del tuo locale — SB Food Consulting"
        corpo = email_checklist_medio(r.nome or 'Ristoratore', p, data)
    else:
        tipo = 'buono'
        oggetto = "Il tuo locale ha basi solide — ecco il prossimo passo"
        corpo = email_checklist_buono(r.nome or 'Ristoratore', p, data)
    return tipo, oggetto, corpo


@checklist_bp.route('/api/checklist/<int:id>/invia-email', methods=['POST'])
def invia_email_checklist(id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    r = RisultatoChecklist.query.get_or_404(id)
    if not r.email:
        return jsonify({'error': 'Nessuna email associata'}), 400

    tipo, oggetto, corpo = _build_checklist_email(r)

    from utils.email import invia_email
    if invia_email(r.email, r.nome or 'Ristoratore', oggetto, corpo):
        r.email_inviata = True
        r.tipo_email = tipo
        db.session.commit()
        return jsonify({'success': True, 'tipo_email': tipo})
    return jsonify({'error': 'Invio fallito'}), 500


@checklist_bp.route('/api/checklist/<int:id>/email-preview', methods=['GET'])
def preview_email_checklist(id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    r = RisultatoChecklist.query.get_or_404(id)
    tipo, oggetto, corpo = _build_checklist_email(r)
    return corpo, 200, {'Content-Type': 'text/html; charset=utf-8'}


@checklist_bp.route('/api/checklist', methods=['GET'])
def get_checklist():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    risultati = RisultatoChecklist.query\
        .order_by(RisultatoChecklist.created_at.desc())\
        .all()

    return jsonify([{
        'id': r.id,
        'nome': r.nome,
        'email': r.email,
        'session_id': r.session_id,
        'punteggio_totale': r.punteggio_totale,
        'punteggio_food_cost': r.punteggio_food_cost,
        'punteggio_personale': r.punteggio_personale,
        'punteggio_menu': r.punteggio_menu,
        'punteggio_comunicazione': r.punteggio_comunicazione,
        'punteggio_numeri': r.punteggio_numeri,
        'risposte': r.risposte,
        'email_inviata': r.email_inviata or False,
        'tipo_email': r.tipo_email,
        'created_at': r.created_at.isoformat()
    } for r in risultati])


# --- Funnel analytics ---

@checklist_bp.route('/api/checklist/funnel', methods=['GET'])
def get_funnel():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    giorni = request.args.get('giorni', 14, type=int)
    if giorni < 1 or giorni > 365:
        giorni = 14

    da = datetime.utcnow() - timedelta(days=giorni)
    eventi = EventoChecklist.query.filter(EventoChecklist.timestamp >= da).all()

    sessioni = defaultdict(list)
    for ev in eventi:
        sessioni[ev.session_id].append(ev)

    viste = 0
    iniziate = 0
    completate = 0
    email_lasciate = 0
    pdf_scaricati = 0
    abbandoni_5 = 0
    abbandoni_10 = 0
    abbandoni_15 = 0
    mobile = 0
    desktop = 0

    for sid, evts in sessioni.items():
        eventi_set = {e.evento for e in evts}
        ua = evts[0].user_agent or ''
        is_mobile = any(kw in ua.lower() for kw in ['mobile', 'android', 'iphone', 'ipad'])

        if 'vista' in eventi_set:
            viste += 1
            if is_mobile:
                mobile += 1
            else:
                desktop += 1
        if 'iniziata' in eventi_set:
            iniziate += 1
        if 'completata' in eventi_set:
            completate += 1
        if 'email_lasciata' in eventi_set:
            email_lasciate += 1
        if 'pdf_scaricato' in eventi_set:
            pdf_scaricati += 1

        if 'completata' not in eventi_set:
            max_domanda = 0
            for e in evts:
                if e.evento == 'domanda' and e.dettaglio:
                    max_domanda = max(max_domanda, e.dettaglio)
            if max_domanda >= 15:
                abbandoni_15 += 1
            elif max_domanda >= 10:
                abbandoni_10 += 1
            elif max_domanda >= 5:
                abbandoni_5 += 1

    return jsonify({
        'giorni': giorni,
        'viste': viste,
        'iniziate': iniziate,
        'completate': completate,
        'email_lasciate': email_lasciate,
        'pdf_scaricati': pdf_scaricati,
        'abbandoni': {
            'domanda_5': abbandoni_5,
            'domanda_10': abbandoni_10,
            'domanda_15': abbandoni_15
        },
        'dispositivi': {
            'mobile': mobile,
            'desktop': desktop
        }
    })
