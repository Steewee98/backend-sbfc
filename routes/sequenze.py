"""Sequenza nurture automatica — scheduling degli invii + reporting.

Modello: EmailSequenza (una riga per email/persona).
- Iscrizione: enrolla_sequenza() — chiamata alla creazione di un lead (per persona,
  non per download → niente doppioni). Prima email dopo 7 giorni.
- Processore: processa_sequenze() — gira ogni giorno (thread in app.py), invia le
  sequenze dovute (prossimo_invio_at <= adesso), avanza lo step e sposta la data
  di 7 giorni. Salta gli step che vendono un prodotto già acquistato (exit-on-purchase).
- Ogni invio è loggato su EmailInvio (services.email_service.invia_nurture) → compare
  nel gestionale (sezione Email: chi, quale mail, consegna/apertura/click).

Endpoint (admin, header X-Admin-Token):
  GET  /api/sequenze                 lista iscrizioni + stato
  GET  /api/sequenze/stats           conteggi per stato/step
  POST /api/sequenze/processa        {"limit":N}  esegue subito il processore
  POST /api/sequenze/enrolla-backlog {"limit":N,"offset":M,"quando":"subito|settimana"}
  POST /api/sequenze/disiscrivi      {"email":"..."}  disiscrive manualmente
Pubblico:
  GET  /api/unsubscribe?e=&t=        disiscrizione one-click dal link nelle email
"""
import os
import time
import logging
from functools import wraps
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, Response

from models import db, EmailSequenza, LeadStrumento, Studente, Pagamento
from services.email_service import invia_nurture, unsub_token

logger = logging.getLogger(__name__)
sequenze_bp = Blueprint('sequenze', __name__)

NUM_STEP = 6
CADENZA_GIORNI = 7


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if not token or token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Iscrizione ────────────────────────────────────────────────────────

def enrolla_sequenza(email, segmento='numeri', ritardo_giorni=CADENZA_GIORNI):
    """Iscrive un'email alla sequenza se non è già presente (una sola volta per
    persona). Ritorna la sequenza creata, oppure None se già iscritta / email vuota."""
    email = (email or '').lower().strip()
    if not email or '@' not in email:
        return None
    if EmailSequenza.query.filter_by(email=email).first():
        return None  # già iscritta → NON ri-iscrivere (niente doppioni)
    seq = EmailSequenza(
        email=email, segmento=segmento or 'numeri', step=0, stato='attiva',
        prossimo_invio_at=datetime.utcnow() + timedelta(days=ritardo_giorni))
    db.session.add(seq)
    db.session.commit()
    return seq


# ─── Exit-on-purchase ──────────────────────────────────────────────────

def _possiede(email):
    """(ha_academy, ha_cruscotto) per l'email indicata."""
    email = (email or '').lower().strip()
    ha_academy = db.session.query(Studente.id).filter(
        Studente.email == email).first() is not None
    ha_cruscotto = db.session.query(Pagamento.id).filter(
        Pagamento.email == email,
        Pagamento.prodotto == 'cruscotto-imprenditore').first() is not None
    return ha_academy, ha_cruscotto


def _step_vende_posseduto(step, ha_academy, ha_cruscotto):
    """Lo step vende un prodotto già acquistato? (3=Cruscotto, 4=modulo, 5=corso)."""
    if step == 3 and ha_cruscotto:
        return True
    if step in (4, 5) and ha_academy:
        return True
    return False


# ─── Processore ────────────────────────────────────────────────────────

def processa_sequenze(limit=None, solo_email=None):
    """Invia le email nurture dovute. Ritorna un riepilogo. Idempotente: invia solo
    le sequenze con prossimo_invio_at <= adesso e avanza la data, quindi può girare
    più volte al giorno senza duplicare."""
    now = datetime.utcnow()
    q = EmailSequenza.query.filter(
        EmailSequenza.stato == 'attiva',
        EmailSequenza.prossimo_invio_at.isnot(None),
        EmailSequenza.prossimo_invio_at <= now)
    if solo_email:
        q = q.filter(EmailSequenza.email == solo_email.lower().strip())
    q = q.order_by(EmailSequenza.prossimo_invio_at.asc())
    if limit:
        q = q.limit(int(limit))
    seqs = q.all()

    inviate = completate = falliti = 0
    for seq in seqs:
        ha_a, ha_c = _possiede(seq.email)
        if ha_a and ha_c:  # ha già tutto: niente da vendere
            seq.stato = 'completata'
            db.session.commit()
            completate += 1
            continue

        # prossimo step utile, saltando quelli che vendono prodotti già posseduti
        prossimo = seq.step + 1
        while prossimo <= NUM_STEP and _step_vende_posseduto(prossimo, ha_a, ha_c):
            seq.step = prossimo
            prossimo += 1
        if prossimo > NUM_STEP:
            seq.stato = 'completata'
            db.session.commit()
            completate += 1
            continue

        resend_id = invia_nurture(prossimo, seq.email)
        if resend_id:
            seq.step = prossimo
            seq.last_sent_at = now
            seq.prossimo_invio_at = now + timedelta(days=CADENZA_GIORNI)
            if seq.step >= NUM_STEP:
                seq.stato = 'completata'
                completate += 1
            db.session.commit()
            inviate += 1
        else:
            # invio fallito: riprova domani, non avanzare lo step
            seq.prossimo_invio_at = now + timedelta(days=1)
            db.session.commit()
            falliti += 1
        time.sleep(0.6)  # throttling deliverability

    return {'candidate': len(seqs), 'inviate': inviate,
            'completate': completate, 'falliti': falliti}


# ─── Endpoint admin ────────────────────────────────────────────────────

@sequenze_bp.route('/api/sequenze', methods=['GET'])
@admin_required
def lista_sequenze():
    try:
        limite = min(int(request.args.get('limit', 500) or 500), 2000)
    except (TypeError, ValueError):
        limite = 500
    stato = (request.args.get('stato') or '').strip().lower() or None
    q = EmailSequenza.query
    if stato:
        q = q.filter(EmailSequenza.stato == stato)
    righe = q.order_by(EmailSequenza.prossimo_invio_at.asc().nullslast()).limit(limite).all()
    return jsonify({'totale': q.count(), 'sequenze': [s.to_dict() for s in righe]}), 200


@sequenze_bp.route('/api/sequenze/stats', methods=['GET'])
@admin_required
def stats_sequenze():
    per_stato = dict(db.session.query(
        EmailSequenza.stato, db.func.count(EmailSequenza.id)
    ).group_by(EmailSequenza.stato).all())
    per_step = dict(db.session.query(
        EmailSequenza.step, db.func.count(EmailSequenza.id)
    ).filter(EmailSequenza.stato == 'attiva').group_by(EmailSequenza.step).all())
    now = datetime.utcnow()
    dovute_oggi = EmailSequenza.query.filter(
        EmailSequenza.stato == 'attiva',
        EmailSequenza.prossimo_invio_at <= now).count()
    return jsonify({
        'per_stato': {k: v for k, v in per_stato.items()},
        'per_step_attive': {str(k): v for k, v in per_step.items()},
        'dovute_ora': dovute_oggi,
        'totale': EmailSequenza.query.count(),
    }), 200


@sequenze_bp.route('/api/sequenze/processa', methods=['POST'])
@admin_required
def api_processa():
    data = request.get_json(silent=True) or {}
    limit = data.get('limit')
    solo = (data.get('email') or '').strip().lower() or None
    r = processa_sequenze(limit=limit, solo_email=solo)
    return jsonify({'success': True, **r}), 200


@sequenze_bp.route('/api/sequenze/enrolla-backlog', methods=['POST'])
@admin_required
def api_enrolla_backlog():
    """Iscrive i lead esistenti (con consenso) non ancora in sequenza.
    Body: {"limit":N,"offset":M,"quando":"subito"|"settimana"}.
    'subito' = prima email al prossimo giro del processore (canary);
    'settimana' = prima email tra 7 giorni."""
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data['limit']) if data.get('limit') is not None else None
        offset = max(int(data.get('offset', 0) or 0), 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'limit/offset non validi'}), 400
    quando = (data.get('quando') or 'settimana').strip().lower()
    ritardo = 0 if quando == 'subito' else CADENZA_GIORNI

    # email uniche con consenso, ordinate (deterministico), non già iscritte
    rows = (db.session.query(LeadStrumento.email)
            .filter(LeadStrumento.consenso_marketing.is_(True))
            .distinct().all())
    candidate = sorted({(r[0] or '').strip().lower() for r in rows if r[0]})
    gia = {e for (e,) in db.session.query(EmailSequenza.email).all()}
    candidate = [e for e in candidate if e not in gia]
    selezionati = candidate[offset:offset + limit] if limit is not None else candidate[offset:]

    creati = 0
    for email in selezionati:
        if enrolla_sequenza(email, segmento='numeri', ritardo_giorni=ritardo):
            creati += 1
    return jsonify({
        'success': True, 'iscritti': creati,
        'quando': quando, 'residui_non_iscritti': max(len(candidate) - offset - creati, 0),
        'gia_iscritti_totali': len(gia) + creati,
    }), 200


@sequenze_bp.route('/api/sequenze/disiscrivi', methods=['POST'])
@admin_required
def api_disiscrivi():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    seq = EmailSequenza.query.filter_by(email=email).first()
    if not seq:
        return jsonify({'error': 'Email non in sequenza'}), 404
    seq.stato = 'disiscritta'
    db.session.commit()
    return jsonify({'success': True, 'email': email, 'stato': 'disiscritta'}), 200


# ─── Disiscrizione one-click (pubblica, dal link nelle email) ──────────

_UNSUB_HTML = """<!DOCTYPE html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Iscrizione annullata</title></head>
<body style="margin:0;font-family:Arial,sans-serif;background:#eae6df;color:#37393f">
<div style="max-width:520px;margin:12vh auto;background:#fff;border-radius:8px;padding:44px 40px;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.08)">
<p style="color:#c4622d;letter-spacing:3px;text-transform:uppercase;font-size:12px;font-weight:bold;margin:0 0 14px">SB Food Consulting</p>
<h1 style="font-family:Georgia,serif;font-weight:normal;font-size:24px;margin:0 0 12px">%(titolo)s</h1>
<p style="color:#6b6560;line-height:1.7;font-size:15px;margin:0">%(testo)s</p>
</div></body></html>"""


@sequenze_bp.route('/api/unsubscribe', methods=['GET'])
def unsubscribe():
    email = (request.args.get('e') or '').strip().lower()
    token = (request.args.get('t') or '').strip()
    ok = email and token and token == unsub_token(email)
    if not ok:
        html = _UNSUB_HTML % {
            'titolo': 'Link non valido',
            'testo': 'Il link di disiscrizione non è valido o è scaduto. '
                     'Può scrivere a info@sbfoodconsulting.com per essere rimosso.'}
        return Response(html, mimetype='text/html', status=400)
    seq = EmailSequenza.query.filter_by(email=email).first()
    if seq and seq.stato != 'disiscritta':
        seq.stato = 'disiscritta'
        db.session.commit()
    html = _UNSUB_HTML % {
        'titolo': 'Iscrizione annullata',
        'testo': 'Non riceverà più le nostre email. Ci dispiace vederla andare — '
                 'se cambia idea ci trova su sbfoodconsulting.com.'}
    return Response(html, mimetype='text/html', status=200)
