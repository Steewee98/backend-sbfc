import os
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Studente

studenti_bp = Blueprint('studenti', __name__)


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
