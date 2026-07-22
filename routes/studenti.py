import os
import string
import secrets
import logging
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Studente

logger = logging.getLogger(__name__)

studenti_bp = Blueprint('studenti', __name__)


def _genera_password(n=10):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


@studenti_bp.route('/api/studenti', methods=['POST'])
@admin_required
def crea_studente():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dati mancanti'}), 400

    required = ['nome', 'email', 'password']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Campo {field} obbligatorio'}), 400

    if Studente.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email già registrata'}), 409

    studente = Studente(
        nome=data['nome'],
        email=data['email'],
        password_hash=generate_password_hash(data['password']),
        moduli_acquistati=data.get('moduli_acquistati', []),
    )
    db.session.add(studente)
    db.session.commit()

    return jsonify(studente.to_dict()), 201


@studenti_bp.route('/api/studenti', methods=['GET'])
@admin_required
def lista_studenti():
    studenti = Studente.query.order_by(Studente.data_iscrizione.desc()).all()
    return jsonify([s.to_dict() for s in studenti])


@studenti_bp.route('/api/studenti/login', methods=['POST'])
def login_studente():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email e password obbligatori'}), 400

    studente = Studente.query.filter_by(email=data['email'], attivo=True).first()
    if not studente or not check_password_hash(studente.password_hash, data['password']):
        return jsonify({'error': 'Credenziali non valide'}), 401

    studente.ultimo_accesso = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'nome': studente.nome,
        'moduli': studente.moduli_acquistati or [],
    })


@studenti_bp.route('/api/studenti/reset-credenziali', methods=['POST'])
@admin_required
def reset_credenziali():
    """Rigenera la password di uno studente e gli re-invia le credenziali via Resend.
    Serve quando l'invio automatico al pagamento (Brevo) è fallito: la password
    originale è hashata e non recuperabile, quindi se ne genera una nuova.
    Body: {"email":"..."} oppure {"id":2}. Opzionale {"password":"..."} per fissarla.
    Restituisce anche la password in chiaro (canale admin) come fallback."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    sid = data.get('id')

    if sid:
        studente = Studente.query.get(sid)
    elif email:
        studente = Studente.query.filter_by(email=email).first()
    else:
        return jsonify({'error': 'Fornire "email" oppure "id"'}), 400

    if not studente:
        return jsonify({'error': 'Studente non trovato'}), 404

    nuova_password = (data.get('password') or '').strip() or _genera_password()
    studente.password_hash = generate_password_hash(nuova_password)
    studente.attivo = True
    db.session.commit()

    nome = (studente.nome or '').split()[0] if studente.nome else 'Studente'
    moduli = studente.moduli_acquistati or []

    email_inviata = False
    if os.environ.get('RESEND_API_KEY'):
        try:
            from services.email_service import invia_email_credenziali
            invia_email_credenziali(nome, studente.email, nuova_password, moduli)
            email_inviata = True
        except Exception as e:
            logger.error('Errore re-invio credenziali a %s: %s', studente.email, e)

    print('[STUDENTI] reset credenziali id=%s email=%s inviata=%s'
          % (studente.id, studente.email, email_inviata), flush=True)

    return jsonify({
        'success': True,
        'studente': studente.to_dict(),
        'password': nuova_password,
        'email_inviata': email_inviata,
    }), 200


@studenti_bp.route('/api/studenti/<int:id>', methods=['PATCH'])
@admin_required
def aggiorna_studente(id):
    studente = Studente.query.get_or_404(id)
    data = request.get_json()

    if 'moduli_acquistati' in data:
        studente.moduli_acquistati = data['moduli_acquistati']

    if 'attivo' in data:
        studente.attivo = data['attivo']

    db.session.commit()
    return jsonify(studente.to_dict())
