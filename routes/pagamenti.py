import os
import logging
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from models import db, Pagamento

logger = logging.getLogger(__name__)

pagamenti_bp = Blueprint('pagamenti', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Admin endpoints ─────────────────────────────────────

@pagamenti_bp.route('/api/pagamenti', methods=['POST'])
@admin_required
def crea_pagamento():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dati mancanti'}), 400

    required = ['nome', 'email', 'prodotto', 'importo']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Campo {field} obbligatorio'}), 400

    pagamento = Pagamento(
        nome=data['nome'],
        email=data['email'],
        prodotto=data['prodotto'],
        importo=float(data['importo']),
        stato=data.get('stato', 'completato'),
        stripe_id=data.get('stripe_id'),
    )
    db.session.add(pagamento)
    db.session.commit()

    return jsonify(pagamento.to_dict()), 201


@pagamenti_bp.route('/api/pagamenti', methods=['GET'])
@admin_required
def lista_pagamenti():
    query = Pagamento.query

    periodo = request.args.get('periodo')
    if periodo:
        days = {'7d': 7, '30d': 30, '90d': 90}.get(periodo)
        if days:
            since = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Pagamento.created_at >= since)

    pagamenti = query.order_by(Pagamento.created_at.desc()).all()
    return jsonify([p.to_dict() for p in pagamenti])
