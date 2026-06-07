from flask import Blueprint, request, jsonify
from models import db, MessaggioWhatsapp
import os

whatsapp_logs_bp = Blueprint('whatsapp_logs', __name__)


@whatsapp_logs_bp.route('/api/whatsapp', methods=['GET'])
def get_whatsapp_logs():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    logs = MessaggioWhatsapp.query\
        .order_by(MessaggioWhatsapp.created_at.desc())\
        .all()

    return jsonify([{
        'id': l.id,
        'nome': l.nome,
        'telefono': l.telefono,
        'messaggio': l.messaggio,
        'stato': l.stato,
        'tipo': l.tipo,
        'created_at': l.created_at.isoformat()
    } for l in logs])


@whatsapp_logs_bp.route('/api/whatsapp/<int:id>', methods=['PATCH'])
def update_whatsapp_log(id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    log = MessaggioWhatsapp.query.get_or_404(id)
    data = request.get_json()

    if 'stato' in data:
        log.stato = data['stato']

    db.session.commit()
    return jsonify({'success': True, 'id': log.id, 'stato': log.stato})
