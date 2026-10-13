"""Progetti di Simone: una pagina per progetto con ultime cose fatte, cose urgenti
da fare e data dell'ultimo aggiornamento. Si aggiorna a voce da progetti.html sul sito:
la nota trascritta arriva qui, services/progetti_ai la trasforma in voci, qui si
ricontrolla e si salva. Stessa chiave del gestionale (X-Admin-Token).

La nota si salva sempre per prima: se la lettura AI non riesce resta «da elaborare»
e si può riprovare, così quello che Simone ha detto non si perde.
"""
import hmac
import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from models import NotaProgetto, Progetto, VoceProgetto, db
from services import progetti_ai

logger = logging.getLogger(__name__)
progetti_bp = Blueprint('progetti', __name__)

STATI = progetti_ai.STATI
MAX_NOTA = 6000
MAX_VOCE = 300
FATTI_MOSTRATI = 12
NOTE_MOSTRATE = 8


def _admin():
    """Entra la chiave del gestionale oppure PROGETTI_TOKEN, la chiave del link personale
    di Simone (progetti.html?k=…): apre solo questi progetti, non il resto del gestionale."""
    data = (request.headers.get('X-Admin-Token') or '').encode()
    chiavi = [os.environ.get('ADMIN_TOKEN'), os.environ.get('PROGETTI_TOKEN')]
    return any(c and len(c) >= 20 and hmac.compare_digest(data, c.encode()) for c in chiavi)


def _no():
    return jsonify({'error': 'Non autorizzato'}), 401


def _iso(d):
    return d.isoformat() if d else None


def _aperte(pid):
    return (VoceProgetto.query.filter_by(progetto_id=pid, tipo='da_fare', chiusa_il=None)
            .order_by(VoceProgetto.urgente.desc(), VoceProgetto.scadenza.is_(None),
                      VoceProgetto.scadenza, VoceProgetto.created_at).all())


def _voce(v):
    return {'id': v.id, 'tipo': v.tipo, 'testo': v.testo, 'urgente': bool(v.urgente),
            'scadenza': _iso(v.scadenza), 'chiusa_il': _iso(v.chiusa_il), 'creata_il': _iso(v.created_at)}


def _riassunto(p):
    aperte = _aperte(p.id)
    urgenti = [v for v in aperte if v.urgente]
    return {'id': p.id, 'nome': p.nome, 'stato': p.stato, 'punto': p.punto,
            'aggiornato_il': _iso(p.aggiornato_il), 'da_fare': len(aperte), 'urgenti': len(urgenti),
            'n_fatte': VoceProgetto.query.filter(VoceProgetto.progetto_id == p.id, db.or_(
                VoceProgetto.tipo == 'fatto', VoceProgetto.chiusa_il.isnot(None))).count(),
            'prossima': (urgenti or aperte)[0].testo if aperte else None,
            'urgenti_lista': [{'testo': v.testo, 'scadenza': _iso(v.scadenza)} for v in urgenti[:3]],
            'da_elaborare': NotaProgetto.query.filter_by(progetto_id=p.id, elaborata=False).count()}


def _dettaglio(p):
    # «fatto» = voci fatte dette nelle note + cose da fare spuntate, le più recenti prima
    fatti = VoceProgetto.query.filter_by(progetto_id=p.id, tipo='fatto').order_by(
        VoceProgetto.created_at.desc()).limit(FATTI_MOSTRATI).all()
    spuntate = VoceProgetto.query.filter(VoceProgetto.progetto_id == p.id, VoceProgetto.tipo == 'da_fare',
                                         VoceProgetto.chiusa_il.isnot(None)).order_by(
        VoceProgetto.chiusa_il.desc()).limit(FATTI_MOSTRATI).all()
    fatte = sorted([(v.created_at, _voce(v)) for v in fatti] + [(v.chiusa_il, _voce(v)) for v in spuntate],
                   key=lambda x: x[0], reverse=True)[:FATTI_MOSTRATI]
    note = NotaProgetto.query.filter_by(progetto_id=p.id).order_by(
        NotaProgetto.created_at.desc()).limit(NOTE_MOSTRATE).all()
    d = _riassunto(p)
    d.update({'aperte': [_voce(v) for v in _aperte(p.id)], 'fatte': [x[1] for x in fatte],
              'note': [{'id': n.id, 'testo': n.testo, 'elaborata': bool(n.elaborata),
                        'creata_il': _iso(n.created_at)} for n in note]})
    return d


def _testo(s, lim=MAX_VOCE):
    s = ' '.join(str(s or '').split())
    return s[:lim] if s else ''


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _applica(p, nota, out, adesso):
    """Ricontrolla la proposta del modello e la salva. Restituisce quante voci ha toccato."""
    aperte = {v.id: v for v in _aperte(p.id)}
    n = 0
    for t in (out.get('fatti') or [])[:20]:
        t = _testo(t)
        if t:
            db.session.add(VoceProgetto(progetto_id=p.id, nota_id=nota.id, tipo='fatto', testo=t, created_at=adesso))
            n += 1
    esistenti = {v.testo.lower() for v in aperte.values()}
    for x in (out.get('da_fare') or [])[:20]:
        if not isinstance(x, dict):
            continue
        t = _testo(x.get('testo'))
        if not t or t.lower() in esistenti:
            continue
        esistenti.add(t.lower())
        db.session.add(VoceProgetto(progetto_id=p.id, nota_id=nota.id, tipo='da_fare', testo=t,
                                    urgente=bool(x.get('urgente')), scadenza=_data(x.get('scadenza')),
                                    created_at=adesso))
        n += 1
    for i in out.get('completate') or []:
        v = aperte.get(i) if isinstance(i, int) else None
        if v:
            v.chiusa_il = adesso
            n += 1
    for i in out.get('urgenti') or []:
        v = aperte.get(i) if isinstance(i, int) else None
        if v and not v.chiusa_il:
            v.urgente = True
            n += 1
    punto = _testo(out.get('punto'), 600)
    if punto and punto.strip('().').lower() not in ('nessun aggiornamento finora', 'niente ancora'):
        p.punto = punto
    if out.get('stato') in STATI:
        p.stato = out['stato']
    nota.elaborata = True
    p.aggiornato_il = adesso
    return n


def _elabora(p, nota):
    aperte = [(v.id, v.testo, bool(v.urgente), v.scadenza) for v in _aperte(p.id)]
    out = progetti_ai.elabora(p.nome, p.stato, p.punto, aperte, nota.testo, datetime.now(ZoneInfo('Europe/Rome')).date())
    return _applica(p, nota, out, datetime.utcnow())


# ── progetti ──

@progetti_bp.route('/api/progetti', methods=['GET'])
def elenco():
    if not _admin():
        return _no()
    ps = Progetto.query.all()
    ordine = {s: i for i, s in enumerate(['in_lavorazione', 'aperto', 'in_attesa', 'chiuso'])}
    ps.sort(key=lambda p: (ordine.get(p.stato, 9), p.aggiornato_il is None,
                         -(p.aggiornato_il or p.created_at).timestamp()))
    return jsonify([_riassunto(p) for p in ps])


@progetti_bp.route('/api/progetti', methods=['POST'])
def crea():
    if not _admin():
        return _no()
    d = request.get_json(silent=True) or {}
    nome = _testo(d.get('nome'), 160)
    if not nome:
        return jsonify({'error': 'Scrivi il nome del progetto'}), 400
    stato = d.get('stato') if d.get('stato') in STATI else 'aperto'
    p = Progetto(nome=nome, stato=stato, aggiornato_il=datetime.utcnow())
    db.session.add(p)
    db.session.commit()
    return jsonify(_dettaglio(p)), 201


@progetti_bp.route('/api/progetti/<int:pid>', methods=['GET'])
def dettaglio(pid):
    if not _admin():
        return _no()
    return jsonify(_dettaglio(Progetto.query.get_or_404(pid)))


@progetti_bp.route('/api/progetti/<int:pid>', methods=['PATCH'])
def modifica(pid):
    if not _admin():
        return _no()
    p = Progetto.query.get_or_404(pid)
    d = request.get_json(silent=True) or {}
    if 'nome' in d:
        nome = _testo(d['nome'], 160)
        if not nome:
            return jsonify({'error': 'Il nome non può essere vuoto'}), 400
        p.nome = nome
    if 'stato' in d:
        if d['stato'] not in STATI:
            return jsonify({'error': 'Stato non valido'}), 400
        p.stato = d['stato']
    if 'punto' in d:
        p.punto = _testo(d['punto'], 600) or None
    p.aggiornato_il = datetime.utcnow()
    db.session.commit()
    return jsonify(_dettaglio(p))


@progetti_bp.route('/api/progetti/<int:pid>', methods=['DELETE'])
def elimina(pid):
    if not _admin():
        return _no()
    p = Progetto.query.get_or_404(pid)
    VoceProgetto.query.filter_by(progetto_id=pid).delete()
    NotaProgetto.query.filter_by(progetto_id=pid).delete()
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


# ── note dettate ──

@progetti_bp.route('/api/progetti/<int:pid>/note', methods=['POST'])
def nuova_nota(pid):
    if not _admin():
        return _no()
    p = Progetto.query.get_or_404(pid)
    testo = str((request.get_json(silent=True) or {}).get('testo') or '').strip()[:MAX_NOTA]
    if len(testo) < 3:
        return jsonify({'error': 'La nota è vuota'}), 400
    nota = NotaProgetto(progetto_id=p.id, testo=testo)
    db.session.add(nota)
    p.aggiornato_il = datetime.utcnow()
    db.session.commit()   # prima la nota: se l'AI non risponde, non si perde
    avviso = None
    try:
        _elabora(p, nota)
        db.session.commit()
    except progetti_ai.NotaNonElaborata as e:
        db.session.rollback()
        avviso = f'Nota salvata, ma non ancora trasformata in cose da fare ({e}). Riprova tra poco.'
    return jsonify({'progetto': _dettaglio(p), 'avviso': avviso}), 201


@progetti_bp.route('/api/progetti/note/<int:nid>/rielabora', methods=['POST'])
def rielabora(nid):
    if not _admin():
        return _no()
    nota = NotaProgetto.query.get_or_404(nid)
    p = Progetto.query.get_or_404(nota.progetto_id)
    if nota.elaborata:
        return jsonify({'progetto': _dettaglio(p), 'avviso': None})
    try:
        _elabora(p, nota)
        db.session.commit()
    except progetti_ai.NotaNonElaborata as e:
        db.session.rollback()
        return jsonify({'error': f'Non riuscito: {e}'}), 503
    return jsonify({'progetto': _dettaglio(p), 'avviso': None})


@progetti_bp.route('/api/progetti/note/<int:nid>', methods=['DELETE'])
def elimina_nota(nid):
    """Toglie una nota sbagliata e le voci che aveva creato (le spunte fatte restano)."""
    if not _admin():
        return _no()
    nota = NotaProgetto.query.get_or_404(nid)
    p = Progetto.query.get_or_404(nota.progetto_id)
    VoceProgetto.query.filter_by(nota_id=nid).delete()
    db.session.delete(nota)
    db.session.commit()
    return jsonify(_dettaglio(p))


# ── voci a mano ──

@progetti_bp.route('/api/progetti/<int:pid>/voci', methods=['POST'])
def nuova_voce(pid):
    if not _admin():
        return _no()
    p = Progetto.query.get_or_404(pid)
    d = request.get_json(silent=True) or {}
    testo = _testo(d.get('testo'))
    tipo = d.get('tipo') if d.get('tipo') in ('fatto', 'da_fare') else 'da_fare'
    if not testo:
        return jsonify({'error': 'Scrivi cosa'}), 400
    db.session.add(VoceProgetto(progetto_id=p.id, tipo=tipo, testo=testo, urgente=bool(d.get('urgente')),
                                scadenza=_data(d.get('scadenza'))))
    p.aggiornato_il = datetime.utcnow()
    db.session.commit()
    return jsonify(_dettaglio(p)), 201


@progetti_bp.route('/api/progetti/voci/<int:vid>', methods=['PATCH'])
def modifica_voce(vid):
    if not _admin():
        return _no()
    v = VoceProgetto.query.get_or_404(vid)
    p = Progetto.query.get_or_404(v.progetto_id)
    d = request.get_json(silent=True) or {}
    if 'fatta' in d and v.tipo == 'da_fare':
        v.chiusa_il = datetime.utcnow() if d['fatta'] else None
    if 'urgente' in d:
        v.urgente = bool(d['urgente'])
    if 'testo' in d:
        t = _testo(d['testo'])
        if not t:
            return jsonify({'error': 'Il testo non può essere vuoto'}), 400
        v.testo = t
    p.aggiornato_il = datetime.utcnow()
    db.session.commit()
    return jsonify(_dettaglio(p))


@progetti_bp.route('/api/progetti/voci/<int:vid>', methods=['DELETE'])
def elimina_voce(vid):
    if not _admin():
        return _no()
    v = VoceProgetto.query.get_or_404(vid)
    p = Progetto.query.get_or_404(v.progetto_id)
    db.session.delete(v)
    db.session.commit()
    return jsonify(_dettaglio(p))


# ── importazione (prima popolazione, o recupero da un'altra fonte) ──

@progetti_bp.route('/api/progetti/importa', methods=['POST'])
def importa():
    """Carica progetti già noti con le loro voci e date. Un progetto con lo stesso nome
    non si duplica: si completa (punto, stato) e si aggiungono solo le voci che non ha.
    Formato: {"progetti": [{"nome", "stato", "punto", "voci": [{"tipo", "testo", "urgente",
    "scadenza", "data"}]}]}; le date in AAAA-MM-GG."""
    if not _admin():
        return _no()
    dati = (request.get_json(silent=True) or {}).get('progetti')
    if not isinstance(dati, list):
        return jsonify({'error': 'Serve una lista «progetti»'}), 400
    creati = voci_nuove = 0
    for d in dati[:200]:
        if not isinstance(d, dict):
            continue
        nome = _testo(d.get('nome'), 160)
        if not nome:
            continue
        p = Progetto.query.filter(db.func.lower(Progetto.nome) == nome.lower()).first()
        if not p:
            p = Progetto(nome=nome, stato='aperto')
            db.session.add(p)
            db.session.flush()
            creati += 1
        if d.get('stato') in STATI:
            p.stato = d['stato']
        if _testo(d.get('punto'), 600):
            p.punto = _testo(d['punto'], 600)
        esistenti = {(v.tipo, v.testo.lower()) for v in VoceProgetto.query.filter_by(progetto_id=p.id)}
        ultima = None
        for v in (d.get('voci') or [])[:100]:
            if not isinstance(v, dict):
                continue
            t, tipo = _testo(v.get('testo')), v.get('tipo') if v.get('tipo') in ('fatto', 'da_fare') else 'da_fare'
            if not t or (tipo, t.lower()) in esistenti:
                continue
            giorno = _data(v.get('data'))
            quando = datetime(giorno.year, giorno.month, giorno.day, 12) if giorno else datetime.utcnow()
            db.session.add(VoceProgetto(progetto_id=p.id, tipo=tipo, testo=t, urgente=bool(v.get('urgente')),
                                        scadenza=_data(v.get('scadenza')), created_at=quando))
            esistenti.add((tipo, t.lower()))
            voci_nuove += 1
            if giorno:   # solo le voci datate dicono quando il progetto si è mosso
                ultima = max(ultima, quando) if ultima else quando
        # «aggiornato» = la data più recente che si conosce; un progetto senza notizie resta «mai aggiornato»
        date_note = [x for x in (p.aggiornato_il, ultima) if x]
        if date_note:
            p.aggiornato_il = max(date_note)
        elif p.punto:
            p.aggiornato_il = datetime.utcnow()
    db.session.commit()
    return jsonify({'creati': creati, 'voci': voci_nuove})
