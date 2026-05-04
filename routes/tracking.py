from flask import Blueprint, request, jsonify
from models import db, Visita
from datetime import datetime, timedelta
from sqlalchemy import func
import hashlib
import os

tracking_bp = Blueprint('tracking', __name__)


@tracking_bp.route('/api/track', methods=['POST'])
def track_visita():
    data = request.json
    pagina = data.get('pagina', '/')
    referrer = data.get('referrer', '')

    # Hash dell'IP per privacy
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]

    # Rileva dispositivo da user agent
    ua = request.headers.get('User-Agent', '')
    if 'Mobile' in ua or 'Android' in ua:
        dispositivo = 'mobile'
    elif 'Tablet' in ua or 'iPad' in ua:
        dispositivo = 'tablet'
    else:
        dispositivo = 'desktop'

    visita = Visita(
        pagina=pagina,
        ip_hash=ip_hash,
        user_agent=ua[:500],
        referrer=referrer[:500],
        dispositivo=dispositivo
    )
    db.session.add(visita)
    db.session.commit()

    return jsonify({'success': True}), 200


@tracking_bp.route('/api/analytics', methods=['GET'])
def get_analytics():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    periodo = request.args.get('periodo', '30d')

    if periodo == '7d':
        data_inizio = datetime.utcnow() - timedelta(days=7)
    elif periodo == '90d':
        data_inizio = datetime.utcnow() - timedelta(days=90)
    else:
        data_inizio = datetime.utcnow() - timedelta(days=30)

    # Visite totali
    visite_totali = Visita.query.filter(
        Visita.created_at >= data_inizio).count()

    # Visitatori unici (per ip_hash)
    visitatori_unici = db.session.query(
        func.count(func.distinct(Visita.ip_hash))
    ).filter(Visita.created_at >= data_inizio).scalar()

    # Pagine piu visitate
    pagine_top = db.session.query(
        Visita.pagina,
        func.count(Visita.id).label('visite')
    ).filter(
        Visita.created_at >= data_inizio
    ).group_by(Visita.pagina).order_by(
        func.count(Visita.id).desc()
    ).limit(10).all()

    # Dispositivi
    dispositivi = db.session.query(
        Visita.dispositivo,
        func.count(Visita.id).label('count')
    ).filter(
        Visita.created_at >= data_inizio
    ).group_by(Visita.dispositivo).all()

    # Sorgenti di traffico
    sorgenti = db.session.query(
        Visita.referrer,
        func.count(Visita.id).label('count')
    ).filter(
        Visita.created_at >= data_inizio,
        Visita.referrer != ''
    ).group_by(Visita.referrer).order_by(
        func.count(Visita.id).desc()
    ).limit(10).all()

    # Visite per giorno
    visite_giornaliere = db.session.query(
        func.date(Visita.created_at).label('data'),
        func.count(Visita.id).label('visite')
    ).filter(
        Visita.created_at >= data_inizio
    ).group_by(
        func.date(Visita.created_at)
    ).order_by(func.date(Visita.created_at)).all()

    # Confronto con periodo precedente
    data_prec = data_inizio - (datetime.utcnow() - data_inizio)
    visite_precedenti = Visita.query.filter(
        Visita.created_at >= data_prec,
        Visita.created_at < data_inizio
    ).count()

    trend = 0
    if visite_precedenti > 0:
        trend = round(((visite_totali - visite_precedenti)
                      / visite_precedenti) * 100)

    return jsonify({
        'visite_totali': visite_totali,
        'visitatori_unici': visitatori_unici,
        'trend': trend,
        'pagine_top': [
            {'pagina': p.pagina, 'visite': p.visite}
            for p in pagine_top
        ],
        'dispositivi': [
            {'tipo': d.dispositivo, 'count': d.count}
            for d in dispositivi
        ],
        'sorgenti': [
            {'referrer': s.referrer or 'Diretto',
             'count': s.count}
            for s in sorgenti
        ],
        'visite_giornaliere': [
            {'data': str(v.data), 'visite': v.visite}
            for v in visite_giornaliere
        ]
    })


@tracking_bp.route('/api/analytics/realtime', methods=['GET'])
def get_realtime():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    # Visitatori ultimi 2 minuti
    due_minuti_fa = datetime.utcnow() - timedelta(minutes=2)

    visitatori_attivi = db.session.query(
        func.count(func.distinct(Visita.ip_hash))
    ).filter(
        Visita.created_at >= due_minuti_fa
    ).scalar()

    # Pagine visitate negli ultimi 2 minuti
    pagine_attive = db.session.query(
        Visita.pagina,
        func.count(Visita.id).label('visite')
    ).filter(
        Visita.created_at >= due_minuti_fa
    ).group_by(Visita.pagina).order_by(
        func.count(Visita.id).desc()
    ).all()

    # Ultima visita
    ultima_visita = Visita.query.order_by(
        Visita.created_at.desc()
    ).first()

    return jsonify({
        'visitatori_attivi': visitatori_attivi,
        'pagine_attive': [
            {'pagina': p.pagina, 'visite': p.visite}
            for p in pagine_attive
        ],
        'ultima_visita': ultima_visita.created_at.isoformat()
                        if ultima_visita else None
    })
