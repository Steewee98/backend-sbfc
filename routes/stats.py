import os
from functools import wraps
from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, Contatto, Studente, Pagamento
from routes.checklist import RisultatoChecklist

stats_bp = Blueprint('stats', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


@stats_bp.route('/api/stats', methods=['GET'])
@admin_required
def get_stats():
    now = datetime.utcnow()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if now.month == 1:
        last_month_start = now.replace(year=now.year - 1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        last_month_start = now.replace(month=now.month - 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    contatti_questo_mese = Contatto.query.filter(
        Contatto.created_at >= this_month_start
    ).count()

    contatti_mese_scorso = Contatto.query.filter(
        Contatto.created_at >= last_month_start,
        Contatto.created_at < this_month_start,
    ).count()

    studenti_attivi = Studente.query.filter_by(attivo=True).count()

    incasso_questo_mese = db.session.query(
        db.func.coalesce(db.func.sum(Pagamento.importo), 0)
    ).filter(
        Pagamento.created_at >= this_month_start,
        Pagamento.stato == 'completato',
    ).scalar()

    nuovi_contatti = Contatto.query.order_by(
        Contatto.created_at.desc()
    ).limit(5).all()

    pagamenti_recenti = Pagamento.query.order_by(
        Pagamento.created_at.desc()
    ).limit(5).all()

    return jsonify({
        'contatti_questo_mese': contatti_questo_mese,
        'contatti_mese_scorso': contatti_mese_scorso,
        'studenti_attivi': studenti_attivi,
        'incasso_questo_mese': float(incasso_questo_mese),
        'nuovi_contatti': [c.to_dict() for c in nuovi_contatti],
        'pagamenti_recenti': [p.to_dict() for p in pagamenti_recenti],
        'checklist_completate': RisultatoChecklist.query.count(),
    })
