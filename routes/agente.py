"""Agente vendite di SB Food — il collegamento con il gestionale.

L'agente gira sul Mac di Stefano (motore della fucina, gestionale.py) e parla con il sito
attraverso tre indirizzi, protetti dal suo token (variabile SBFOOD_AGENTE_TOKEN, header
`Authorization: Bearer <token>`), diverso da ADMIN_TOKEN: l'agente non vede il resto del gestionale.

  POST /api/agente/stato       {stato?, messaggi?}  lo stato da mostrare + i messaggi dell'agente
  GET  /api/agente/in-arrivo   → {in_arrivo: [{id, tipo, at, ...}]}  scelte del titolare non ancora lette
  POST /api/agente/letti       {ids}  le segna come lette dopo averle applicate

Il titolare, dal gestionale (X-Admin-Token):
  GET  /api/admin/agente         stato, chat, voci in attesa
  POST /api/admin/agente/azione  {tipo: messaggio|pausa|riprendi|spesa, ...}

Tipi accettati: solo quelli che il motore sa applicare (agente_vendite.ascolta_gestionale).
Un tipo sconosciuto il motore lo segna come letto senza applicarlo: andrebbe perso, quindi qui si rifiuta.
"""
import hmac
import json
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request

from models import db

agente_bp = Blueprint('agente', __name__)

TIPI = ('messaggio', 'pausa', 'riprendi', 'spesa')
MAX_STATO = 200_000        # byte di JSON dello stato
MAX_MESSAGGIO = 4000       # caratteri di un messaggio
MAX_MESSAGGI = 20          # messaggi dell'agente per chiamata (come il motore)
CHAT_MOSTRATA = 100


class AgenteStato(db.Model):
    __tablename__ = 'agente_stato'
    id = db.Column(db.String(40), primary_key=True)          # 'sbfood'
    stato = db.Column(db.Text)                               # JSON della fotografia del motore
    aggiornato_at = db.Column(db.DateTime)


class AgenteChat(db.Model):
    __tablename__ = 'agente_chat'
    id = db.Column(db.Integer, primary_key=True)
    autore = db.Column(db.String(10), nullable=False)        # agente | titolare
    testo = db.Column(db.Text, nullable=False)
    at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class AgenteInArrivo(db.Model):
    __tablename__ = 'agente_in_arrivo'
    id = db.Column(db.String(40), primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)
    dati = db.Column(db.Text)                                # JSON dei campi in più (testo, spesa_id, scelta)
    at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    letto_at = db.Column(db.DateTime, index=True)


def _iso(d):
    return d.isoformat(timespec='seconds') + 'Z' if d else None


def agente_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        atteso = os.environ.get('SBFOOD_AGENTE_TOKEN', '')
        h = request.headers.get('Authorization', '')
        dato = h[7:] if h.startswith('Bearer ') else ''
        if not atteso or not dato or not hmac.compare_digest(dato, atteso):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        atteso = os.environ.get('ADMIN_TOKEN', '')
        dato = request.headers.get('X-Admin-Token', '')
        if not atteso or not dato or not hmac.compare_digest(dato, atteso):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Indirizzi dell'agente ───────────────────────────────────────────

@agente_bp.route('/api/agente/stato', methods=['POST'])
@agente_required
def ricevi_stato():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({'error': 'Serve un oggetto JSON'}), 400
    stato, messaggi = d.get('stato'), d.get('messaggi')
    if stato is not None:
        if not isinstance(stato, dict):
            return jsonify({'error': 'stato deve essere un oggetto'}), 400
        testo = json.dumps(stato, ensure_ascii=False)
        if len(testo.encode()) > MAX_STATO:
            return jsonify({'error': 'stato troppo grande'}), 413
        riga = db.session.get(AgenteStato, 'sbfood') or AgenteStato(id='sbfood')
        riga.stato, riga.aggiornato_at = testo, datetime.utcnow()
        db.session.add(riga)
    if messaggi is not None:
        if not isinstance(messaggi, list):
            return jsonify({'error': 'messaggi deve essere una lista'}), 400
        for m in messaggi[:MAX_MESSAGGI]:
            if isinstance(m, str) and m.strip():
                db.session.add(AgenteChat(autore='agente', testo=m.strip()[:MAX_MESSAGGIO]))
    db.session.commit()
    return jsonify({'ok': True})


@agente_bp.route('/api/agente/in-arrivo', methods=['GET'])
@agente_required
def in_arrivo():
    righe = (AgenteInArrivo.query.filter(AgenteInArrivo.letto_at.is_(None))
             .order_by(AgenteInArrivo.at.asc()).limit(100).all())
    voci = []
    for r in righe:
        try:
            extra = json.loads(r.dati or '{}')
        except ValueError:
            extra = {}
        voci.append({**extra, 'id': r.id, 'tipo': r.tipo, 'at': _iso(r.at)})
    return jsonify({'in_arrivo': voci})


@agente_bp.route('/api/agente/letti', methods=['POST'])
@agente_required
def letti():
    d = request.get_json(silent=True) or {}
    ids = d.get('ids') if isinstance(d, dict) else None
    if not isinstance(ids, list):
        return jsonify({'error': 'Serve {ids: [...]}'}), 400
    ids = [str(i) for i in ids if isinstance(i, (str, int))][:200]
    n = 0
    if ids:
        n = (AgenteInArrivo.query.filter(AgenteInArrivo.id.in_(ids), AgenteInArrivo.letto_at.is_(None))
             .update({'letto_at': datetime.utcnow()}, synchronize_session=False))
        db.session.commit()
    return jsonify({'ok': True, 'segnati': n})


# ─── Pagina del titolare ─────────────────────────────────────────────

@agente_bp.route('/api/admin/agente', methods=['GET'])
@admin_required
def vista_admin():
    riga = db.session.get(AgenteStato, 'sbfood')
    try:
        stato = json.loads(riga.stato) if riga and riga.stato else None
    except ValueError:
        stato = None
    chat = AgenteChat.query.order_by(AgenteChat.at.desc(), AgenteChat.id.desc()).limit(CHAT_MOSTRATA).all()
    attesa = (AgenteInArrivo.query.filter(AgenteInArrivo.letto_at.is_(None))
              .order_by(AgenteInArrivo.at.asc()).all())
    return jsonify({
        'stato': stato,
        'aggiornato_at': _iso(riga.aggiornato_at) if riga else None,
        'chat': [{'autore': c.autore, 'testo': c.testo, 'at': _iso(c.at)} for c in reversed(chat)],
        'in_attesa': [{'id': a.id, 'tipo': a.tipo, 'at': _iso(a.at)} for a in attesa],
    })


@agente_bp.route('/api/admin/agente/azione', methods=['POST'])
@admin_required
def azione_admin():
    d = request.get_json(silent=True)
    if not isinstance(d, dict) or d.get('tipo') not in TIPI:
        return jsonify({'error': 'tipo deve essere uno fra: ' + ', '.join(TIPI)}), 400
    tipo, extra = d['tipo'], {}
    if tipo == 'messaggio':
        testo = str(d.get('testo') or '').strip()
        if not testo:
            return jsonify({'error': 'Il messaggio è vuoto'}), 400
        extra['testo'] = testo[:MAX_MESSAGGIO]
        db.session.add(AgenteChat(autore='titolare', testo=extra['testo']))
    elif tipo == 'spesa':
        try:
            extra['spesa_id'] = int(d.get('spesa_id'))
        except (TypeError, ValueError):
            return jsonify({'error': 'spesa_id non valido'}), 400
        if d.get('scelta') not in ('ok', 'no'):
            return jsonify({'error': 'scelta deve essere ok o no'}), 400
        extra['scelta'] = d['scelta']
    voce = AgenteInArrivo(id=uuid.uuid4().hex, tipo=tipo, dati=json.dumps(extra, ensure_ascii=False))
    db.session.add(voce)
    db.session.commit()
    return jsonify({'ok': True, 'id': voce.id})
