"""Rete SB — i locali seguiti con la console.

Per ora: la scheda dell'incontro iniziale col ristoratore. Il consulente la
compila (anche da iPad, durante la riunione) e la console salva mentre scrive.
Poi qui arriveranno ricettario, scarichi, inventari, timbrature e diagnosi.

Tutte le API sono protette dalla chiave admin (X-Admin-Token), la stessa del
gestionale: la console è un repo pubblico e non contiene dati.
"""
import os
import re
import base64
import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, Response
from models import db, LocaleRete

logger = logging.getLogger(__name__)
rete_bp = Blueprint('rete', __name__)

STATI = ('incontro', 'avvio', 'attivo', 'sospeso')
SEZIONI = ('locale', 'persone', 'numeri', 'cucina', 'formalita', 'obiettivi')
MAX_FILE = 6 * 1024 * 1024
MIME_OK = {'application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/heic',
           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
           'application/vnd.ms-excel', 'text/csv'}


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if request.headers.get('X-Admin-Token') != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*a, **kw)
    return w


def _testo(v, n=200):
    return (str(v).strip()[:n]) if v is not None else None


@rete_bp.route('/api/rete/locali', methods=['GET'])
@admin_required
def lista():
    q = LocaleRete.query.order_by(LocaleRete.updated_at.desc())
    return jsonify([l.to_dict() for l in q.all()])


@rete_bp.route('/api/rete/locali', methods=['POST'])
@admin_required
def crea():
    d = request.get_json(silent=True) or {}
    nome = _testo(d.get('nome'))
    if not nome:
        return jsonify({'error': 'Serve almeno il nome del locale'}), 400
    l = LocaleRete(nome=nome, tipo=_testo(d.get('tipo'), 40), citta=_testo(d.get('citta'), 120),
                   consulente=_testo(d.get('consulente'), 120), scheda={}, allegati={})
    db.session.add(l)
    db.session.commit()
    return jsonify(l.to_dict(completa=True)), 201


@rete_bp.route('/api/rete/locali/<int:lid>', methods=['GET'])
@admin_required
def leggi(lid):
    return jsonify(LocaleRete.query.get_or_404(lid).to_dict(completa=True))


@rete_bp.route('/api/rete/locali/<int:lid>', methods=['PATCH'])
@admin_required
def aggiorna(lid):
    """Salvataggio mentre si scrive: arrivano solo le sezioni cambiate,
    ognuna sostituita per intero (niente fusioni a metà di una tabella)."""
    l = LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    for k in ('nome', 'tipo', 'citta', 'consulente'):
        if k in d:
            v = _testo(d[k], 200)
            if k == 'nome' and not v:
                return jsonify({'error': 'Il nome del locale non può restare vuoto'}), 400
            setattr(l, k, v)
    if 'stato' in d:
        if d['stato'] not in STATI:
            return jsonify({'error': 'Stato non valido'}), 400
        l.stato = d['stato']
    if isinstance(d.get('scheda'), dict):
        scheda = dict(l.scheda or {})
        for sez, val in d['scheda'].items():
            if sez in SEZIONI and isinstance(val, dict):
                scheda[sez] = val
        l.scheda = scheda   # riassegnare: il JSON non traccia le mutazioni
    l.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(l.to_dict(completa=True))


@rete_bp.route('/api/rete/locali/<int:lid>', methods=['DELETE'])
@admin_required
def elimina(lid):
    l = LocaleRete.query.get_or_404(lid)
    db.session.delete(l)
    db.session.commit()
    return jsonify({'ok': True})


@rete_bp.route('/api/rete/locali/<int:lid>/allegati/<chiave>', methods=['POST'])
@admin_required
def carica_allegato(lid, chiave):
    if not re.match(r'^[a-z0-9_-]{2,40}$', chiave):
        return jsonify({'error': 'Nome allegato non valido'}), 400
    l = LocaleRete.query.get_or_404(lid)
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Nessun file'}), 400
    dati = f.read()
    if len(dati) > MAX_FILE:
        return jsonify({'error': 'Il file supera i 6 MB'}), 400
    mime = (f.mimetype or '').lower()
    if mime not in MIME_OK:
        return jsonify({'error': f'Formato non supportato ({mime})'}), 400
    alle = dict(l.allegati or {})
    alle[chiave] = {'nome': f.filename[:160], 'mime': mime, 'caricato': datetime.utcnow().isoformat(),
                    'dati': base64.b64encode(dati).decode('ascii')}
    l.allegati = alle
    l.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(l.to_dict())


@rete_bp.route('/api/rete/locali/<int:lid>/allegati/<chiave>', methods=['GET'])
@admin_required
def scarica_allegato(lid, chiave):
    a = (LocaleRete.query.get_or_404(lid).allegati or {}).get(chiave)
    if not a:
        return jsonify({'error': 'File non presente'}), 404
    return Response(base64.b64decode(a['dati']), mimetype=a['mime'], headers={
        'Content-Disposition': f'attachment; filename="{a.get("nome") or chiave}"'})


@rete_bp.route('/api/rete/locali/<int:lid>/allegati/<chiave>', methods=['DELETE'])
@admin_required
def elimina_allegato(lid, chiave):
    l = LocaleRete.query.get_or_404(lid)
    alle = dict(l.allegati or {})
    alle.pop(chiave, None)
    l.allegati = alle
    db.session.commit()
    return jsonify(l.to_dict())
