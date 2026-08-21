"""Statistiche email — riceve gli eventi di Resend via webhook e li aggrega
per il gestionale (inviate, consegnate, aperte, click, rimbalzi, reclami).

Endpoint:
  POST /api/webhook/resend       (pubblico, firma Svix verificata se configurata)
  GET  /api/email/stats          (admin) aggregati + tassi
  GET  /api/email/eventi         (admin) ultimi invii con stato

Le aperture/click funzionano solo se su Resend sono attivi "Open tracking" e
"Click tracking" per il dominio. NB: l'open tracking sovrastima (Apple Mail
Privacy Protection apre in automatico) — è indicativo, non assoluto.
"""
import os
import hmac
import base64
import hashlib
import logging
from functools import wraps
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from models import db, EmailInvio

logger = logging.getLogger(__name__)

email_stats_bp = Blueprint('email_stats', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if not token or token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Mappe eventi / categorie ──────────────────────────────────────────

# Evento Resend -> campo timestamp da valorizzare sulla riga EmailInvio
EVENTO_CAMPO = {
    'email.sent': 'sent_at',
    'email.delivered': 'delivered_at',
    'email.opened': 'opened_at',
    'email.clicked': 'clicked_at',
    'email.bounced': 'bounced_at',
    'email.complained': 'complained_at',
}

# Categorizzazione per subject (fallback se i tag non arrivano nel payload)
def _tipo_da_subject(subject):
    s = (subject or '').lower()
    # transazionali cliente
    if 'scheda è pronta' in s or "scheda e' pronta" in s or 'vantaggi riservati' in s:
        return 'grazie_download'
    if 'benvenuto in sb food academy' in s or 'accesso al corso' in s or 'credenziali sb food academy' in s:
        return 'credenziali'
    if 'checklist gratuita' in s:
        return 'lead_checklist'
    if 'grazie per averci contattato' in s:
        return 'benvenuto'
    if 'bisogno di un intervento' in s or 'aree critiche' in s or 'basi solide' in s:
        return 'checklist_esito'
    if 'la tua guida' in s or 'cruscotto' in s:
        return 'cruscotto'
    # campagne broadcast
    if 'nuove schede' in s or 'riscontro' in s or 'riscopri' in s:
        return 'campagna'
    # notifiche interne (verso lo staff)
    if (s.startswith('nuovo acquisto') or s.startswith('nuovo contatto')
            or s.startswith('nuovo lead') or s.startswith('nuova checklist')
            or 'watchdog' in s or 'report' in s):
        return 'notifica_interna'
    return 'altro'


def _tipo_da_tags(data):
    """Resend può restituire i tag nel payload come dict {name:value} o come lista."""
    tags = data.get('tags')
    if isinstance(tags, dict):
        return tags.get('categoria') or tags.get('tipo')
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict) and t.get('name') in ('categoria', 'tipo'):
                return t.get('value')
    return None


def _parse_ts(value):
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


# ─── Verifica firma webhook (Svix, come usa Resend) ────────────────────

def _verifica_firma(secret, headers, body_bytes):
    svix_id = headers.get('svix-id') or headers.get('webhook-id')
    svix_ts = headers.get('svix-timestamp') or headers.get('webhook-timestamp')
    svix_sig = headers.get('svix-signature') or headers.get('webhook-signature')
    if not (svix_id and svix_ts and svix_sig):
        return False
    key = secret[len('whsec_'):] if secret.startswith('whsec_') else secret
    try:
        key_bytes = base64.b64decode(key)
    except Exception:
        key_bytes = secret.encode()
    signed = svix_id.encode() + b'.' + svix_ts.encode() + b'.' + body_bytes
    expected = base64.b64encode(hmac.new(key_bytes, signed, hashlib.sha256).digest()).decode()
    for sig in svix_sig.split(' '):
        candidate = sig.split(',', 1)[1] if ',' in sig else sig
        if hmac.compare_digest(candidate, expected):
            return True
    return False


@email_stats_bp.route('/api/webhook/resend', methods=['POST'])
def resend_webhook():
    body = request.get_data()
    secret = os.environ.get('RESEND_WEBHOOK_SECRET')
    if secret:
        if not _verifica_firma(secret, request.headers, body):
            logger.warning('[RESEND-WEBHOOK] firma non valida, evento rifiutato')
            return jsonify({'error': 'firma non valida'}), 401
    # else: nessun secret configurato -> accetta comunque (utile in dev)

    payload = request.get_json(force=True, silent=True) or {}
    evt = payload.get('type')
    data = payload.get('data', {}) or {}
    email_id = data.get('email_id') or data.get('id')
    if not evt or not email_id:
        return jsonify({'received': True}), 200  # ack ma niente da fare

    to = data.get('to')
    dest = to[0] if isinstance(to, list) and to else (to if isinstance(to, str) else None)
    subject = data.get('subject')
    ts = _parse_ts(payload.get('created_at') or data.get('created_at'))
    tipo = _tipo_da_tags(data) or _tipo_da_subject(subject)

    try:
        riga = EmailInvio.query.filter_by(resend_id=email_id).first()
        if not riga:
            riga = EmailInvio(resend_id=email_id, destinatario=dest, subject=subject, tipo=tipo)
            db.session.add(riga)
        # completa eventuali campi mancanti (se il primo evento visto non è 'sent')
        if dest and not riga.destinatario:
            riga.destinatario = dest
        if subject and not riga.subject:
            riga.subject = subject
        if tipo and (not riga.tipo or riga.tipo == 'altro'):
            riga.tipo = tipo

        campo = EVENTO_CAMPO.get(evt)
        if campo and getattr(riga, campo) is None:
            setattr(riga, campo, ts)
        riga.last_event = evt.replace('email.', '')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error('[RESEND-WEBHOOK] errore salvataggio evento %s per %s: %s', evt, email_id, e)
        # ack comunque: non vogliamo che Resend ritenti all'infinito

    return jsonify({'received': True}), 200


@email_stats_bp.route('/api/email/stats', methods=['GET'])
@admin_required
def email_stats():
    try:
        giorni = int(request.args.get('giorni', 30) or 30)
    except (TypeError, ValueError):
        giorni = 30
    tipo = (request.args.get('tipo') or '').strip().lower() or None

    q = EmailInvio.query
    if giorni > 0:
        cutoff = datetime.utcnow() - timedelta(days=giorni)
        q = q.filter(EmailInvio.created_at >= cutoff)
    if tipo:
        q = q.filter(EmailInvio.tipo == tipo)

    def _agg(query):
        inviati = query.count()
        consegnati = query.filter(EmailInvio.delivered_at.isnot(None)).count()
        aperti = query.filter(EmailInvio.opened_at.isnot(None)).count()
        click = query.filter(EmailInvio.clicked_at.isnot(None)).count()
        rimbalzi = query.filter(EmailInvio.bounced_at.isnot(None)).count()
        reclami = query.filter(EmailInvio.complained_at.isnot(None)).count()
        pct = lambda n, d: round(100.0 * n / d, 1) if d else 0.0
        return {
            'inviati': inviati,
            'consegnati': consegnati,
            'aperti': aperti,
            'click': click,
            'rimbalzi': rimbalzi,
            'reclami': reclami,
            'tasso_consegna': pct(consegnati, inviati),
            'tasso_apertura': pct(aperti, consegnati),
            'tasso_click': pct(click, consegnati),
        }

    risultato = _agg(q)

    # Breakdown per tipo (solo se non è già filtrato su un tipo)
    per_tipo = {}
    if not tipo:
        righe = db.session.query(EmailInvio.tipo, db.func.count(EmailInvio.id))
        if giorni > 0:
            righe = righe.filter(EmailInvio.created_at >= (datetime.utcnow() - timedelta(days=giorni)))
        for t, _c in righe.group_by(EmailInvio.tipo).all():
            per_tipo[t or 'altro'] = _agg(q.filter(EmailInvio.tipo == t))

    risultato['giorni'] = giorni
    risultato['per_tipo'] = per_tipo
    return jsonify(risultato), 200


@email_stats_bp.route('/api/email/eventi', methods=['GET'])
@admin_required
def email_eventi():
    try:
        limite = min(int(request.args.get('limit', 100) or 100), 1000)
    except (TypeError, ValueError):
        limite = 100
    tipo = (request.args.get('tipo') or '').strip().lower() or None
    q = EmailInvio.query
    if tipo:
        q = q.filter(EmailInvio.tipo == tipo)
    righe = q.order_by(EmailInvio.created_at.desc()).limit(limite).all()
    return jsonify([r.to_dict() for r in righe]), 200
