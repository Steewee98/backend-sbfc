import os
import logging
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Contatto
from services.email_service import invia_email_benvenuto

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

    required = ['nome', 'cognome', 'email']
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

    # Invio email benvenuto (non blocca la risposta API)
    try:
        invia_email_benvenuto(nome=data['nome'], destinatario=data['email'])
    except Exception as e:
        logger.error(f"Errore invio email benvenuto: {e}")

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
