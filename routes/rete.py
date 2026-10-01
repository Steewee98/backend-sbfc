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


def consulente_da_token(tok):
    """Il token personale di un consulente (dato da /api/rete/login) → il consulente, se ancora attivo."""
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    from models import ConsulenteRete
    try:
        dati = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='console-rete').loads(tok, max_age=14 * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return None
    c = db.session.get(ConsulenteRete, dati.get('c'))
    # la password cambiata invalida i token vecchi: il token porta un pezzo dell'hash
    return c if c and c.attivo and dati.get('h') == c.password_hash[-12:] else None


def admin_required(f):
    """Le API della rete: la chiave admin di sempre, oppure l'accesso personale di un consulente.
    In `g.chi` resta chi sta lavorando."""
    @wraps(f)
    def w(*a, **kw):
        from flask import g
        tok = request.headers.get('X-Admin-Token') or ''
        admin = os.environ.get('ADMIN_TOKEN')
        if admin and tok == admin:
            g.chi, g.admin, g.ruolo = 'admin', True, 'admin'
        else:
            c = consulente_da_token(tok) if tok else None
            if not c:
                return jsonify({'error': 'Non autorizzato'}), 401
            # la direzione monitora: legge tutto, non cambia niente (il controllo è qui, non solo nella pagina)
            if c.ruolo == 'direzione' and request.method not in ('GET', 'HEAD', 'OPTIONS'):
                return jsonify({'error': 'Il portale della direzione è in sola lettura: le modifiche le fanno i consulenti'}), 403
            g.chi, g.admin, g.ruolo = c.nome, False, c.ruolo
        return f(*a, **kw)
    return w


def solo_admin(f):
    """Per le cose che decide solo chi ha la chiave admin (Simone): gli accessi dei consulenti."""
    @wraps(f)
    def w(*a, **kw):
        if not os.environ.get('ADMIN_TOKEN') or request.headers.get('X-Admin-Token') != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Solo l\'amministratore può farlo'}), 403
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


# ── accessi personali dei consulenti ──

from models import ConsulenteRete  # noqa: E402
from werkzeug.security import generate_password_hash, check_password_hash  # noqa: E402


@rete_bp.route('/api/rete/login', methods=['POST'])
def login_consulente():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    from routes.admin_auth import _ip, _bloccato, _errori
    import time
    ip = _ip()
    if _bloccato(ip):
        return jsonify({'error': 'Troppi tentativi sbagliati. Riprova fra un quarto d\'ora.'}), 429
    d = request.get_json(silent=True) or {}
    email = (d.get('email') or '').strip().lower()
    c = ConsulenteRete.query.filter_by(email=email, attivo=True).first() if email else None
    if not c or not check_password_hash(c.password_hash, str(d.get('password') or '')):
        _errori[ip].append(time.time())
        return jsonify({'error': 'Credenziali non valide'}), 401
    c.ultimo_accesso = datetime.utcnow()
    db.session.commit()
    tok = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='console-rete').dumps({'c': c.id, 'h': c.password_hash[-12:]})
    return jsonify({'token': tok, 'nome': c.nome, 'ruolo': c.ruolo})


@rete_bp.route('/api/rete/consulenti', methods=['GET'])
@solo_admin
def consulenti():
    return jsonify([c.to_dict() for c in ConsulenteRete.query.order_by(ConsulenteRete.nome).all()])


def _dati_consulente(c, d, nuovo):
    if 'nome' in d or nuovo:
        nome = _testo(d.get('nome'), 120)
        if not nome:
            return 'Serve il nome'
        c.nome = nome
    if 'email' in d or nuovo:
        e = (d.get('email') or '').strip().lower()[:200]
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
            return 'Email non valida'
        if ConsulenteRete.query.filter(ConsulenteRete.email == e, ConsulenteRete.id != (c.id or 0)).first():
            return 'Email già usata'
        c.email = e
    if d.get('password') or nuovo:
        if len(str(d.get('password') or '')) < 10:
            return 'La password deve avere almeno 10 caratteri'
        c.password_hash = generate_password_hash(str(d['password']))
    if 'attivo' in d:
        c.attivo = bool(d['attivo'])
    if 'ruolo' in d or nuovo:
        ruolo = d.get('ruolo') or 'consulente'
        if ruolo not in ('consulente', 'direzione'):
            return 'Ruolo non valido'
        c.ruolo = ruolo
    return None


@rete_bp.route('/api/rete/consulenti', methods=['POST'])
@solo_admin
def crea_consulente():
    c = ConsulenteRete()
    err = _dati_consulente(c, request.get_json(silent=True) or {}, True)
    if err:
        return jsonify({'error': err}), 400
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict()), 201


@rete_bp.route('/api/rete/consulenti/<int:cid>', methods=['PATCH'])
@solo_admin
def modifica_consulente(cid):
    c = ConsulenteRete.query.get_or_404(cid)
    err = _dati_consulente(c, request.get_json(silent=True) or {}, False)
    if err:
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify(c.to_dict())
