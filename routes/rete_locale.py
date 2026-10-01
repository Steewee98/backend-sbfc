"""Rete SB, fase 2 — l'app del locale e le persone che ci lavorano.

Due porte:
  /api/rete/locali/<id>/...   per la console (chiave admin): persone, PIN, turni, chiusure, codice dell'app;
  /api/app/...                per l'app del locale, sul sito:
      - dal tag del locale, sulla cassa o in vista (/app/?l=<codice>): lo staff sceglie il nome, mette il PIN
        e timbra inizio o fine turno; chi chiude segna la chiusura;
      - il titolare entra con email e password e legge «Il quadro».

Il codice del locale non si indovina, ma non è una password: senza PIN non si
timbra niente, e il quadro vuole l'accesso del titolare.
"""
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, LocaleRete, PersonaLocale, TurnoRete, ChiusuraRete
from routes.rete import admin_required, _testo
from routes.rete_dati import _num
from routes.admin_auth import _ip
from services.quadro import quadro, andamento, giorno_di_lavoro, ora_locale

rete_locale_bp = Blueprint('rete_locale', __name__)

RUOLI = ('titolare', 'responsabile', 'staff')
TURNO_MAX = timedelta(hours=14)        # un turno aperto da più ore è una fine dimenticata
DOPPIO = timedelta(seconds=60)         # due timbrature della stessa persona più vicine sono lo stesso tocco
VOCI_CHIUSURA = ('celle', 'gas', 'luci', 'cassa', 'porte')
SITO = 'https://www.sbfoodconsulting.com'

# freno ai PIN sbagliati: 10 errori in 15 minuti per locale e indirizzo
_errori = defaultdict(deque)


def _frenato(chiave):
    q, ora = _errori[chiave], time.time()
    while q and ora - q[0] > 900:
        q.popleft()
    return len(q) >= 10


def _firma():
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='app-locale')


def _iso_roma(dt):
    return ora_locale(dt).isoformat(timespec='minutes') if dt else None


def _codice(l):
    if not l.codice:
        l.codice = secrets.token_urlsafe(9)[:12]
        db.session.commit()
    return l.codice


# ═══ console: persone, turni, chiusure ═══

@rete_locale_bp.route('/api/rete/locali/<int:lid>/persone', methods=['GET'])
@admin_required
def persone(lid):
    LocaleRete.query.get_or_404(lid)
    q = PersonaLocale.query.filter_by(locale_id=lid).order_by(PersonaLocale.attiva.desc(), PersonaLocale.nome)
    return jsonify([p.to_dict() for p in q.all()])


def _applica(p, d):
    if 'nome' in d:
        nome = _testo(d['nome'], 80)
        if not nome:
            return 'Serve il nome'
        p.nome = nome
    if 'ruolo' in d:
        if d['ruolo'] not in RUOLI:
            return 'Ruolo non valido'
        p.ruolo = d['ruolo']
    if 'email' in d:
        e = (d['email'] or '').strip().lower()[:200] or None
        if e and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
            return 'Email non valida'
        if e and PersonaLocale.query.filter(PersonaLocale.email == e, PersonaLocale.id != p.id).first():
            return 'Questa email è già usata da un\'altra persona'
        p.email = e
    if 'costo_orario' in d:
        p.costo_orario = _num(d['costo_orario'], minimo=0) if d['costo_orario'] not in (None, '') else None
    if 'attiva' in d:
        p.attiva = bool(d['attiva'])
    from services.squadra import MANSIONI, REPARTI, CONTRATTI
    if 'mansione' in d:
        m = _testo(d['mansione'], 40)
        p.mansione = m
        # la mansione porta il suo reparto, a meno che non se ne scelga un altro
        if m in MANSIONI and not d.get('reparto'):
            p.reparto = MANSIONI[m]
    if d.get('reparto') not in (None, ''):
        if d['reparto'] not in REPARTI:
            return 'Reparto non valido'
        p.reparto = d['reparto']
    elif 'reparto' in d and 'mansione' not in d:
        p.reparto = None
    if 'contratto' in d:
        if d['contratto'] not in (None, '') and d['contratto'] not in CONTRATTI:
            return 'Contratto non valido'
        p.contratto = d['contratto'] or None
    if 'ore_contratto' in d:
        v = _num(d['ore_contratto'], minimo=0) if d['ore_contratto'] not in (None, '') else None
        if d['ore_contratto'] not in (None, '') and (v is None or v > 80):
            return 'Ore da contratto non valide'
        p.ore_contratto = v
    if 'telefono' in d:
        p.telefono = _testo(d['telefono'], 30)
    if 'note' in d:
        p.note = _testo(d['note'], 300)
    if 'assunto_il' in d:
        from datetime import date as _date
        try:
            p.assunto_il = _date.fromisoformat(str(d['assunto_il'])[:10]) if d['assunto_il'] else None
        except ValueError:
            return 'Data di assunzione non valida'
    if 'orario' in d:
        from services.previsto import valida
        o = valida(d['orario'])
        if isinstance(o, str):
            return o
        p.orario = o
    if d.get('pin'):
        if not re.fullmatch(r'\d{4,6}', str(d['pin'])):
            return 'Il PIN è di 4-6 cifre'
        p.pin_hash = generate_password_hash(str(d['pin']))
    if d.get('password'):
        if len(str(d['password'])) < 8:
            return 'La password deve avere almeno 8 caratteri'
        p.password_hash = generate_password_hash(str(d['password']))
    return None


@rete_locale_bp.route('/api/rete/squadra/voci', methods=['GET'])
@admin_required
def voci_squadra():
    """Le liste per la scheda della persona: mansioni con il loro reparto, reparti, contratti."""
    from services.squadra import MANSIONI, REPARTI, CONTRATTI
    return jsonify({'mansioni': MANSIONI, 'reparti': REPARTI, 'contratti': CONTRATTI})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/persone', methods=['POST'])
@admin_required
def crea_persona(lid):
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    p = PersonaLocale(locale_id=lid, nome='?')
    err = _applica(p, {'nome': d.get('nome'), 'ruolo': d.get('ruolo') or 'staff', **{k: v for k, v in d.items() if k not in ('nome', 'ruolo')}})
    if err:
        return jsonify({'error': err}), 400
    db.session.add(p)
    db.session.commit()
    return jsonify(p.to_dict()), 201


@rete_locale_bp.route('/api/rete/locali/<int:lid>/persone/<int:pid>', methods=['PATCH'])
@admin_required
def modifica_persona(lid, pid):
    p = db.session.get(PersonaLocale, pid)
    if not p or p.locale_id != lid:
        return jsonify({'error': 'Persona non trovata'}), 404
    err = _applica(p, request.get_json(silent=True) or {})
    if err:
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify(p.to_dict())


@rete_locale_bp.route('/api/rete/locali/<int:lid>/persone/<int:pid>', methods=['DELETE'])
@admin_required
def elimina_persona(lid, pid):
    """Chi ha dei turni non si cancella (servono al costo del personale): si disattiva."""
    p = db.session.get(PersonaLocale, pid)
    if not p or p.locale_id != lid:
        return jsonify({'error': 'Persona non trovata'}), 404
    if TurnoRete.query.filter_by(persona_id=p.id).first():
        p.attiva = False
    else:
        db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/app', methods=['GET'])
@admin_required
def indirizzi_app(lid):
    l = LocaleRete.query.get_or_404(lid)
    c = _codice(l)
    return jsonify({'codice': c, 'tag': f'{SITO}/app/?l={c}', 'quadro': f'{SITO}/app/quadro.html'})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/app/nuovo-codice', methods=['POST'])
@admin_required
def nuovo_codice(lid):
    """Se il link del tag gira dove non deve: nuovo codice, il vecchio tag smette di funzionare."""
    l = LocaleRete.query.get_or_404(lid)
    l.codice = None
    db.session.commit()
    return indirizzi_app(lid)


@rete_locale_bp.route('/api/rete/locali/<int:lid>/turni', methods=['GET'])
@admin_required
def turni(lid):
    LocaleRete.query.get_or_404(lid)
    giorni = min(int(request.args.get('giorni') or 14), 92)
    da = datetime.utcnow() - timedelta(days=giorni)
    nomi = {p.id: p.nome for p in PersonaLocale.query.filter_by(locale_id=lid).all()}
    adesso = datetime.utcnow()
    out = []
    for t in (TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.inizio >= da)
              .order_by(TurnoRete.inizio.desc()).all()):
        dimenticato = t.fine is None and adesso - t.inizio > TURNO_MAX
        out.append({'id': t.id, 'persona_id': t.persona_id, 'nome': nomi.get(t.persona_id, '?'),
                    'inizio': _iso_roma(t.inizio), 'fine': _iso_roma(t.fine),
                    'ore': round(t.ore(), 2) if t.fine else None, 'aperto': t.fine is None,
                    'dimenticato': dimenticato, 'corretto': t.corretto})
    chiusure = [{'giorno': c.giorno.isoformat(), 'ora': _iso_roma(c.ora), 'nome': nomi.get(c.persona_id), 'voci': c.voci}
                for c in ChiusuraRete.query.filter(ChiusuraRete.locale_id == lid,
                                                   ChiusuraRete.giorno >= (da.date())).order_by(ChiusuraRete.giorno.desc())]
    return jsonify({'turni': out, 'chiusure': chiusure})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/turni/<int:tid>', methods=['PATCH'])
@admin_required
def correggi_turno(lid, tid):
    """{fine: 'AAAA-MM-GGTHH:MM'} in ora di Roma: per chiudere un turno dimenticato."""
    from services.quadro import ROMA
    from datetime import timezone
    t = db.session.get(TurnoRete, tid)
    if not t or t.locale_id != lid:
        return jsonify({'error': 'Turno non trovato'}), 404
    d = request.get_json(silent=True) or {}
    for campo in ('inizio', 'fine'):
        if campo in d:
            try:
                v = datetime.fromisoformat(d[campo]).replace(tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                return jsonify({'error': 'Ora non valida'}), 400
            setattr(t, campo, v)
    if t.fine and t.fine <= t.inizio:
        return jsonify({'error': 'La fine deve venire dopo l\'inizio'}), 400
    t.corretto = True
    db.session.commit()
    return jsonify({'ok': True})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/andamento', methods=['GET'])
@admin_required
def andamento_locale(lid):
    return jsonify(andamento(LocaleRete.query.get_or_404(lid), settimane=min(int(request.args.get('settimane') or 8), 26)))


@rete_locale_bp.route('/api/rete/locali/<int:lid>/indicatori', methods=['GET'])
@admin_required
def indicatori_locale(lid):
    """I quadranti di Monitoring: ogni indicatore col suo atteso, lo stato, la fonte e la mossa."""
    from services.indicatori import indicatori
    return jsonify(indicatori(LocaleRete.query.get_or_404(lid)))


# ═══ il dossier: le sette schede di Monitoring e i campi che le riempiono ═══

@rete_locale_bp.route('/api/rete/locali/<int:lid>/dossier', methods=['GET'])
@admin_required
def dossier_locale(lid):
    from services.dossier import dossier
    return jsonify(dossier(LocaleRete.query.get_or_404(lid)))


@rete_locale_bp.route('/api/rete/locali/<int:lid>/domanda', methods=['GET'])
@admin_required
def domanda_ai_dati(lid):
    """?q=la domanda. Risponde solo con i dati del locale (services/domande.py). È una lettura: la può fare anche la direzione."""
    from services.domande import chiedi, DomandaNonRiuscita
    l = LocaleRete.query.get_or_404(lid)
    try:
        return jsonify(chiedi(l, request.args.get('q')))
    except DomandaNonRiuscita as e:
        return jsonify({'error': str(e)}), e.stato


@rete_locale_bp.route('/api/rete/locali/<int:lid>/dossier', methods=['PATCH'])
@admin_required
def salva_dossier(lid):
    """{campi: {'locale.coperti': 74, 'dossier.pacchetto': 'Mantenimento', …},
        dotazione: {'sonde': {stato, nota} | null}, indicatori: {'pers': {nota, mossa} | null}}
    Si salva campo per campo: due consulenti su sezioni diverse non si cancellano a vicenda."""
    from datetime import date as _date
    from services.dossier import CAMPI, STRUMENTI
    l = LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    scheda = {k: dict(v) if isinstance(v, dict) else v for k, v in (l.scheda or {}).items()}
    dos = dict(scheda.get('dossier') or {})
    for percorso, v in (d.get('campi') or {}).items():
        tipo = CAMPI.get(percorso)
        if not tipo:
            return jsonify({'error': f'Campo sconosciuto: {percorso}'}), 400
        if v in (None, ''):
            v = None
        elif tipo == 'numero':
            v = _num(v, minimo=0)
            if v is None:
                return jsonify({'error': f'Serve un numero: {percorso}'}), 400
        elif tipo == 'data':
            try:
                v = _date.fromisoformat(str(v)[:10]).isoformat()
            except ValueError:
                return jsonify({'error': f'Data non valida: {percorso}'}), 400
        elif isinstance(tipo, tuple):
            if v not in tipo:
                return jsonify({'error': f'Valore non valido: {percorso}'}), 400
        else:
            v = _testo(v, 300)
        sez, k = percorso.split('.', 1)
        if sez == 'dossier':
            dos[k] = v
        else:
            scheda[sez] = {**(scheda.get(sez) or {}), k: v}
    for chiave, ammessi in (('dotazione', STRUMENTI), ('indicatori', None)):
        blocco = dict(dos.get(chiave) or {})
        for k, v in (d.get(chiave) or {}).items():
            if (ammessi is not None and k not in ammessi) or len(k) > 30:
                return jsonify({'error': f'Voce sconosciuta: {k}'}), 400
            if not v:
                blocco.pop(k, None)
                continue
            if chiave == 'dotazione':
                if v.get('stato') not in (None, '', 'attivo', 'da sistemare', 'assente'):
                    return jsonify({'error': 'Stato non valido'}), 400
                pulito = {'stato': v.get('stato') or None, 'nota': _testo(v.get('nota'), 300)}
            else:
                pulito = {'nota': _testo(v.get('nota'), 1000), 'mossa': _testo(v.get('mossa'), 500)}
            pulito = {a: b for a, b in pulito.items() if b}
            if pulito:
                blocco[k] = pulito
            else:
                blocco.pop(k, None)
        dos[chiave] = blocco
    scheda['dossier'] = dos
    l.scheda = scheda
    l.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'dossier': dos})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/storia', methods=['GET'])
@admin_required
def storia_locale(lid):
    from services.dossier import storia
    return jsonify(storia(LocaleRete.query.get_or_404(lid)))


@rete_locale_bp.route('/api/rete/locali/<int:lid>/storia', methods=['POST'])
@admin_required
def aggiungi_evento(lid):
    """{giorno, tipo: visita|chiamata|decisione|nota, testo, chiave}"""
    from datetime import date as _date
    from models import EventoRete
    from routes.rete import consulente_da_token
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    testo = _testo(d.get('testo'), 2000)
    tipo = d.get('tipo') or 'nota'
    if not testo:
        return jsonify({'error': 'Scrivi cosa è successo'}), 400
    if tipo not in ('visita', 'chiamata', 'decisione', 'nota'):
        return jsonify({'error': 'Tipo non valido'}), 400
    try:
        g = _date.fromisoformat(str(d.get('giorno'))[:10]) if d.get('giorno') else giorno_di_lavoro()
    except ValueError:
        return jsonify({'error': 'Data non valida'}), 400
    c = consulente_da_token(request.headers.get('X-Admin-Token'))
    e = EventoRete(locale_id=lid, giorno=g, tipo=tipo, testo=testo, chiave=bool(d.get('chiave')), autore=c.nome if c else 'SB')
    db.session.add(e)
    db.session.commit()
    return jsonify(e.to_dict()), 201


@rete_locale_bp.route('/api/rete/locali/<int:lid>/storia/<int:eid>', methods=['DELETE'])
@admin_required
def togli_evento(lid, eid):
    from models import EventoRete
    e = db.session.get(EventoRete, eid)
    if not e or e.locale_id != lid:
        return jsonify({'error': 'Evento non trovato'}), 404
    db.session.delete(e)
    db.session.commit()
    return jsonify({'ok': True})


@rete_locale_bp.route('/api/rete/locali/<int:lid>/quadro', methods=['GET'])
@admin_required
def quadro_console(lid):
    """Lo stesso quadro che vede il titolare, per il consulente."""
    return jsonify(quadro(LocaleRete.query.get_or_404(lid)))


# ═══ app del locale: il tag sulla cassa ═══

def _locale_da_codice(codice):
    return LocaleRete.query.filter_by(codice=codice).first() if codice and len(codice) <= 16 else None


@rete_locale_bp.route('/api/app/<codice>', methods=['GET'])
def app_locale(codice):
    l = _locale_da_codice(codice)
    if not l:
        return jsonify({'error': 'Locale non trovato: il tag potrebbe essere vecchio'}), 404
    adesso = datetime.utcnow()
    aperti = {t.persona_id for t in TurnoRete.query.filter(TurnoRete.locale_id == l.id, TurnoRete.fine.is_(None),
                                                           TurnoRete.inizio > adesso - TURNO_MAX).all()}
    persone = (PersonaLocale.query.filter(PersonaLocale.locale_id == l.id, PersonaLocale.attiva.is_(True),
                                          PersonaLocale.pin_hash.isnot(None)).order_by(PersonaLocale.nome).all())
    giorno = giorno_di_lavoro()
    return jsonify({'locale': l.nome, 'giorno': giorno.isoformat(),
                    'chiuso_oggi': bool(ChiusuraRete.query.filter_by(locale_id=l.id, giorno=giorno).first()),
                    # solo il nome: chi è in servizio si vede, il resto no
                    'persone': [{'id': p.id, 'nome': p.nome, 'in_servizio': p.id in aperti} for p in persone]})


def _persona_col_pin(l, d):
    chiave = f'{l.id}|{_ip()}'
    if _frenato(chiave):
        return None, (jsonify({'error': 'Troppi PIN sbagliati: riprova fra un quarto d\'ora'}), 429)
    p = db.session.get(PersonaLocale, int(d.get('persona_id') or 0))
    if not p or p.locale_id != l.id or not p.attiva or not p.pin_hash or not check_password_hash(p.pin_hash, str(d.get('pin') or '')):
        _errori[chiave].append(time.time())
        return None, (jsonify({'error': 'PIN sbagliato'}), 401)
    return p, None


@rete_locale_bp.route('/api/app/<codice>/timbra', methods=['POST'])
def timbra(codice):
    """{persona_id, pin}: se la persona è in servizio chiude il turno, altrimenti lo apre."""
    l = _locale_da_codice(codice)
    if not l:
        return jsonify({'error': 'Locale non trovato'}), 404
    p, err = _persona_col_pin(l, request.get_json(silent=True) or {})
    if err:
        return err
    adesso = datetime.utcnow()
    aperto = (TurnoRete.query.filter(TurnoRete.persona_id == p.id, TurnoRete.fine.is_(None),
                                     TurnoRete.inizio > adesso - TURNO_MAX).order_by(TurnoRete.inizio.desc()).first())
    # un doppio tocco (o una richiesta ripetuta dopo un timeout) entro un minuto non cambia niente:
    # si risponde con quello che è già successo, invece di aprire e chiudere subito il turno
    if aperto and adesso - aperto.inizio < DOPPIO:
        return jsonify({'azione': 'inizio', 'nome': p.nome, 'ora': _iso_roma(aperto.inizio), 'ripetuta': True})
    if not aperto:
        ultimo = (TurnoRete.query.filter(TurnoRete.persona_id == p.id, TurnoRete.fine.isnot(None))
                  .order_by(TurnoRete.fine.desc()).first())
        if ultimo and adesso - ultimo.fine < DOPPIO:
            return jsonify({'azione': 'fine', 'nome': p.nome, 'ora': _iso_roma(ultimo.fine), 'ore': round(ultimo.ore(), 2), 'ripetuta': True})
    if aperto:
        aperto.fine = adesso
        db.session.commit()
        return jsonify({'azione': 'fine', 'nome': p.nome, 'ora': _iso_roma(adesso), 'ore': round(aperto.ore(), 2)})
    t = TurnoRete(locale_id=l.id, persona_id=p.id, inizio=adesso)
    db.session.add(t)
    db.session.commit()
    return jsonify({'azione': 'inizio', 'nome': p.nome, 'ora': _iso_roma(adesso)})


@rete_locale_bp.route('/api/app/<codice>/chiusura', methods=['POST'])
def chiusura(codice):
    """{persona_id, pin, voci: {celle, gas, luci, cassa, porte: bool, nota}}"""
    l = _locale_da_codice(codice)
    if not l:
        return jsonify({'error': 'Locale non trovato'}), 404
    d = request.get_json(silent=True) or {}
    p, err = _persona_col_pin(l, d)
    if err:
        return err
    v = d.get('voci') or {}
    voci = {k: bool(v.get(k)) for k in VOCI_CHIUSURA}
    voci['nota'] = _testo(v.get('nota'), 500) or ''
    giorno = giorno_di_lavoro()
    c = ChiusuraRete.query.filter_by(locale_id=l.id, giorno=giorno).first() or ChiusuraRete(locale_id=l.id, giorno=giorno)
    c.persona_id, c.ora, c.voci = p.id, datetime.utcnow(), voci
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'giorno': giorno.isoformat(), 'mancano': [k for k in VOCI_CHIUSURA if not voci[k]]})


# ═══ app del locale: il titolare ═══

@rete_locale_bp.route('/api/app/login', methods=['POST'])
def login_titolare():
    ip = _ip()
    if _frenato('login|' + ip):
        return jsonify({'error': 'Troppi tentativi sbagliati: riprova fra un quarto d\'ora'}), 429
    d = request.get_json(silent=True) or {}
    email = (d.get('email') or '').strip().lower()
    p = PersonaLocale.query.filter_by(email=email, attiva=True).first() if email else None
    ok = bool(p and p.password_hash and p.ruolo in ('titolare', 'responsabile')
              and check_password_hash(p.password_hash, str(d.get('password') or '')))
    if not ok:
        _errori['login|' + ip].append(time.time())
        return jsonify({'error': 'Email o password non validi'}), 401
    token = _firma().dumps({'p': p.id})
    return jsonify({'token': token, 'nome': p.nome})


@rete_locale_bp.route('/api/app/quadro', methods=['GET'])
def quadro_titolare():
    tok = (request.headers.get('Authorization') or '').removeprefix('Bearer ').strip()
    try:
        dati = _firma().loads(tok, max_age=30 * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return jsonify({'error': 'Accesso scaduto: entra di nuovo'}), 401
    p = db.session.get(PersonaLocale, dati.get('p'))
    if not p or not p.attiva or p.ruolo not in ('titolare', 'responsabile'):
        return jsonify({'error': 'Accesso non più valido'}), 401
    l = db.session.get(LocaleRete, p.locale_id)
    q = quadro(l)
    q['chi'] = p.nome
    q['andamento'] = andamento(l)
    return jsonify(q)


# ═══ avvisi ═══

@rete_locale_bp.route('/api/rete/avvisi', methods=['GET'])
@admin_required
def anteprima_avvisi():
    """Cosa partirebbe domattina, senza mandare niente."""
    from services.avvisi import giro
    return jsonify(giro(invia=False))


@rete_locale_bp.route('/api/rete/avvisi', methods=['POST'])
@admin_required
def manda_avvisi():
    from services.avvisi import giro
    return jsonify(giro(invia=True))
