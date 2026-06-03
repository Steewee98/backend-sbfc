from flask import Blueprint, request, jsonify
from models import MessaggioWhatsapp
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
