"""Lead strumenti — download dei 7 PDF dell'Academy in cambio dell'email.

Flusso: il sito raccoglie email + consenso marketing e chiama questo endpoint
per SALVARE il lead. Nessuna mail transazionale, nessun invio del PDF via email:
il download parte direttamente nel browser lato client.
"""
import os
import re
import csv
import time
import hashlib
import logging
import requests
from io import StringIO
from collections import defaultdict
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, Response

from models import db, LeadStrumento

logger = logging.getLogger(__name__)

lead_strumenti_bp = Blueprint('lead_strumenti', __name__)

# I PDF vivono sul sito statico, ma Railway (edge) NON applica l'header
# Content-Disposition di nginx: su iOS il PDF si apre in anteprima invece di
# scaricarsi. Il backend invece riesce a mandare l'header, quindi serviamo i
# download da qui forzando l'attachment (proxy verso il sito statico, con cache).
_STATIC_PDF_BASE = os.environ.get('STATIC_PDF_BASE', 'https://www.sbfoodconsulting.com/assets/pdf/risorse')
_pdf_cache = {}

# Slug validi dei 7 strumenti (coerenti con le pagine /strumenti/<slug>)
STRUMENTI_VALIDI = {
    'checklist-apertura-chiusura',
    'scheda-food-cost',
    'scheda-ricetta',
    'checklist-pre-servizio',
    'quiz-numeri',
    'autovalutazione-team',
    'manuale-operativo',
}

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Rate limit leggero per IP
_rate = defaultdict(list)
_RATE_MAX = 20
_RATE_WIN = 60


def _ok_rate(ip):
    now = time.time()
    _rate[ip] = [t for t in _rate[ip] if now - t < _RATE_WIN]
    if len(_rate[ip]) >= _RATE_MAX:
        return False
    _rate[ip].append(now)
    return True


def _ip_hash(ip):
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    return hashlib.sha256((ip or '').encode()).hexdigest()[:16]


def _dispositivo(ua):
    if 'Mobile' in ua or 'Android' in ua:
        return 'mobile'
    if 'Tablet' in ua or 'iPad' in ua:
        return 'tablet'
    return 'desktop'


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if not token or token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


@lead_strumenti_bp.route('/api/strumenti/<slug>/pdf', methods=['GET'])
def download_pdf(slug):
    """Serve il PDF di uno strumento come download (Content-Disposition: attachment).
    tipo=vuoto (default) -> modello · tipo=esempio -> esempio compilato."""
    slug = (slug or '').strip().lower()
    if slug not in STRUMENTI_VALIDI:
        return jsonify({'error': 'Strumento non valido'}), 404

    tipo = (request.args.get('tipo') or 'vuoto').lower()
    fname = slug + ('-esempio.pdf' if tipo == 'esempio' else '.pdf')

    data = _pdf_cache.get(fname)
    if data is None:
        try:
            r = requests.get(_STATIC_PDF_BASE + '/' + fname, timeout=15)
            if r.status_code != 200 or not r.content:
                return jsonify({'error': 'PDF non trovato'}), 404
            data = r.content
            _pdf_cache[fname] = data
        except Exception:
            return jsonify({'error': 'PDF non disponibile'}), 502

    # attachment (default) = Safari/desktop scaricano il file.
    # inline=1 = per i browser in-app (Instagram/Facebook) che non hanno il
    # gestore download: mostrano il PDF, poi l'utente fa Condividi -> Salva su File.
    disp = 'inline' if request.args.get('inline') == '1' else 'attachment'
    resp = Response(data, mimetype='application/pdf')
    resp.headers['Content-Disposition'] = '%s; filename="%s"' % (disp, fname)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@lead_strumenti_bp.route('/api/lead-strumenti', methods=['POST'])
def crea_lead():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if not _ok_rate(ip or 'x'):
        return jsonify({'error': 'Troppe richieste, riprova tra poco'}), 429

    data = request.get_json(force=True, silent=True) or {}

    email = (data.get('email') or '').strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 200:
        return jsonify({'error': 'Inserisci un indirizzo email valido'}), 400

    strumento = (data.get('strumento') or '').strip().lower()
    if strumento not in STRUMENTI_VALIDI:
        return jsonify({'error': 'Strumento non valido'}), 400

    # Il consenso marketing è obbligatorio: senza, l'email non è riutilizzabile
    consenso = bool(data.get('consenso_marketing'))
    if not consenso:
        return jsonify({'error': 'Il consenso è necessario per procedere'}), 400

    ua = request.headers.get('User-Agent', '')[:500]

    lead = LeadStrumento(
        email=email,
        strumento=strumento,
        consenso_marketing=True,
        consenso_at=datetime.utcnow(),
        referrer=(data.get('referrer') or '')[:500] or None,
        utm_source=(data.get('utm_source') or '')[:200] or None,
        utm_medium=(data.get('utm_medium') or '')[:200] or None,
        utm_campaign=(data.get('utm_campaign') or '')[:200] or None,
        dispositivo=_dispositivo(ua),
        ip_hash=_ip_hash(ip),
        user_agent=ua or None,
    )
    db.session.add(lead)
    db.session.commit()

    # Log server-side: il salvataggio è fire-and-forget lato client (sendBeacon),
    # quindi questo è il modo per verificare in produzione che i lead arrivino davvero.
    fonte = lead.utm_campaign or lead.utm_source or lead.referrer or '-'
    msg = ('[LEAD-STRUMENTI] nuovo lead #%s | %s | strumento=%s | disp=%s | fonte=%s'
           % (lead.id, email, strumento, lead.dispositivo, fonte))
    print(msg, flush=True)
    logger.info(msg)

    return jsonify({'success': True, 'id': lead.id}), 201


@lead_strumenti_bp.route('/api/lead-strumenti', methods=['GET'])
@admin_required
def lista_lead():
    limite = min(int(request.args.get('limit', 500) or 500), 5000)
    q = LeadStrumento.query.order_by(LeadStrumento.created_at.desc()).limit(limite).all()
    return jsonify([l.to_dict() for l in q]), 200


@lead_strumenti_bp.route('/api/lead-strumenti/<int:lead_id>', methods=['DELETE'])
@admin_required
def elimina_lead(lead_id):
    lead = LeadStrumento.query.get(lead_id)
    if not lead:
        return jsonify({'error': 'Lead non trovato'}), 404
    db.session.delete(lead)
    db.session.commit()
    print('[LEAD-STRUMENTI] eliminato lead #%s (%s)' % (lead_id, lead.email), flush=True)
    return jsonify({'success': True}), 200


@lead_strumenti_bp.route('/api/lead-strumenti/stats', methods=['GET'])
@admin_required
def stats_lead():
    totale = LeadStrumento.query.count()
    per_strumento = (
        db.session.query(LeadStrumento.strumento, db.func.count(LeadStrumento.id))
        .group_by(LeadStrumento.strumento)
        .all()
    )
    # Email uniche (una persona può scaricare più strumenti)
    uniche = db.session.query(db.func.count(db.distinct(LeadStrumento.email))).scalar()
    return jsonify({
        'totale': totale,
        'email_uniche': uniche or 0,
        'per_strumento': {s: c for s, c in per_strumento},
    }), 200


@lead_strumenti_bp.route('/api/lead-strumenti/export.csv', methods=['GET'])
@admin_required
def export_csv():
    leads = LeadStrumento.query.order_by(LeadStrumento.created_at.desc()).all()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'id', 'email', 'strumento', 'consenso_marketing', 'consenso_at',
        'referrer', 'utm_source', 'utm_medium', 'utm_campaign',
        'dispositivo', 'created_at'
    ])
    for l in leads:
        writer.writerow([
            l.id, l.email, l.strumento,
            'si' if l.consenso_marketing else 'no',
            l.consenso_at.isoformat() if l.consenso_at else '',
            l.referrer or '', l.utm_source or '', l.utm_medium or '', l.utm_campaign or '',
            l.dispositivo or '',
            l.created_at.isoformat() if l.created_at else '',
        ])
    output.seek(0)
    nome = 'lead-strumenti-' + datetime.utcnow().strftime('%Y%m%d') + '.csv'
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=' + nome},
    )
