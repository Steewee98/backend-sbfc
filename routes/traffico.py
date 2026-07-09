"""Tracking per-visitatore (solo con consenso cookie lato sito).

Client invia eventi (pageview, click, scroll, tempo, identificazione) con un
visitor_id persistente. L'admin ricostruisce il percorso di ogni visitatore.
"""
import os
import time
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, send_file

from models import db, EventoTraffico
from utils.percorsi_pdf import genera_percorsi_pdf
from routes.tracking import BOT_KEYWORDS, _track_visit

traffico_bp = Blueprint('traffico', __name__)

TIPI_VALIDI = {'pageview', 'click', 'scroll', 'tempo', 'identificazione',
               'scheda_download', 'scheda_vista'}

# Eventi relativi alle schede operative scaricabili (Academy → Risorse)
SCHEDE_TIPI = {'scheda_download', 'scheda_vista'}

# Rate limit leggero per IP
_rate = defaultdict(list)
_RATE_MAX = 120
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


@traffico_bp.route('/api/traffico/track', methods=['POST'])
def track_evento():
    ua = request.headers.get('User-Agent', '')
    if any(kw in ua.lower() for kw in BOT_KEYWORDS) or len(ua) < 20:
        return jsonify({'ok': True, 'skipped': 'bot'}), 200

    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if not _ok_rate(ip or 'x'):
        return jsonify({'error': 'rate'}), 429

    data = request.get_json(force=True, silent=True) or {}
    tipo = (data.get('tipo') or '').strip()
    if tipo not in TIPI_VALIDI:
        return jsonify({'error': 'tipo non valido'}), 400

    visitor_id = (data.get('visitor_id') or '').strip()[:64]
    session_id = (data.get('session_id') or '').strip()[:64]
    pagina = (data.get('pagina') or '')[:300]
    valore = (str(data.get('valore')) if data.get('valore') is not None
              else '')[:300]
    referrer = (data.get('referrer') or '')[:500]
    if not visitor_id:
        return jsonify({'error': 'visitor_id mancante'}), 400

    ev = EventoTraffico(
        visitor_id=visitor_id,
        session_id=session_id,
        tipo=tipo,
        pagina=pagina,
        valore=valore,
        referrer=referrer,
        dispositivo=_dispositivo(ua),
        ip_hash=_ip_hash(ip),
    )
    db.session.add(ev)
    db.session.commit()

    # Per i pageview alimenta anche le statistiche aggregate legacy (Visita)
    if tipo == 'pageview':
        try:
            _track_visit(pagina or '/', referrer, ua, ip)
        except Exception:
            db.session.rollback()

    return jsonify({'ok': True}), 200


@traffico_bp.route('/api/traffico/identifica', methods=['POST'])
def identifica():
    """Lega un visitor_id a un'identità quando l'utente lascia i dati."""
    data = request.get_json(force=True, silent=True) or {}
    visitor_id = (data.get('visitor_id') or '').strip()[:64]
    email = (data.get('email') or '').strip()
    nome = (data.get('nome') or '').strip()
    if not visitor_id or not email:
        return jsonify({'error': 'visitor_id ed email richiesti'}), 400

    etichetta = (f"{nome} <{email}>" if nome else email)[:300]
    ev = EventoTraffico(
        visitor_id=visitor_id,
        session_id=(data.get('session_id') or '')[:64],
        tipo='identificazione',
        pagina=(data.get('pagina') or '')[:300],
        valore=etichetta,
        dispositivo=_dispositivo(request.headers.get('User-Agent', '')),
        ip_hash=_ip_hash(request.headers.get('X-Forwarded-For',
                                              request.remote_addr)),
    )
    db.session.add(ev)
    db.session.commit()
    return jsonify({'ok': True}), 200


def _fonte(referrer):
    r = (referrer or '').lower()
    if not r:
        return 'Diretto'
    if 'facebook' in r or 'fb.' in r or 'instagram' in r or 'l.instagram' in r:
        return 'Meta (FB/IG)'
    if 'google' in r:
        return 'Google'
    if 'sbfoodconsulting' in r:
        return 'Interno'
    try:
        dominio = r.split('//')[-1].split('/')[0]
        return dominio or 'Altro'
    except Exception:
        return 'Altro'


@traffico_bp.route('/api/traffico/visitatori', methods=['GET'])
def visitatori():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    giorni = request.args.get('giorni', 30, type=int)
    if giorni < 1 or giorni > 365:
        giorni = 30
    da = datetime.utcnow() - timedelta(days=giorni)

    eventi = EventoTraffico.query.filter(
        EventoTraffico.created_at >= da
    ).order_by(EventoTraffico.created_at.asc()).all()

    vis = defaultdict(list)
    for e in eventi:
        vis[e.visitor_id].append(e)

    out = []
    for vid, evs in vis.items():
        primo = evs[0]
        ultimo = evs[-1]
        pageviews = [e for e in evs if e.tipo == 'pageview']
        pagine = []
        for e in pageviews:
            if e.pagina and (not pagine or pagine[-1] != e.pagina):
                pagine.append(e.pagina)
        ident = None
        for e in evs:
            if e.tipo == 'identificazione' and e.valore:
                ident = e.valore
        out.append({
            'visitor_id': vid,
            'prima_visita': primo.created_at.isoformat(),
            'ultima_attivita': ultimo.created_at.isoformat(),
            'dispositivo': primo.dispositivo,
            'fonte': _fonte(primo.referrer),
            'pageviews': len(pageviews),
            'pagine_distinte': len(set(p.pagina for p in pageviews)),
            'eventi': len(evs),
            'identita': ident,
            'convertito': ident is not None,
        })

    out.sort(key=lambda x: x['ultima_attivita'], reverse=True)

    riepilogo = {
        'visitatori': len(out),
        'convertiti': sum(1 for v in out if v['convertito']),
        'eventi_totali': len(eventi),
        'pageviews_totali': sum(v['pageviews'] for v in out),
    }
    return jsonify({'giorni': giorni, 'riepilogo': riepilogo,
                    'visitatori': out[:500]})


@traffico_bp.route('/api/traffico/visitatore/<vid>', methods=['GET'])
def visitatore(vid):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    evs = EventoTraffico.query.filter_by(visitor_id=vid).order_by(
        EventoTraffico.created_at.asc()).all()
    if not evs:
        return jsonify({'error': 'Visitatore non trovato'}), 404

    ident = None
    for e in evs:
        if e.tipo == 'identificazione' and e.valore:
            ident = e.valore

    return jsonify({
        'visitor_id': vid,
        'identita': ident,
        'dispositivo': evs[0].dispositivo,
        'fonte': _fonte(evs[0].referrer),
        'eventi': [e.to_dict() for e in evs],
    })


def _nome_scheda(slug):
    """Da 'scheda-food-cost' / 'assets/pdf/risorse/scheda-food-cost.pdf'
    a 'Scheda Food Cost' (nome leggibile per il gestionale)."""
    if not slug:
        return 'Scheda'
    s = slug.split('/')[-1].replace('.pdf', '')
    s = s.replace('-esempio', '').replace('-', ' ').strip()
    return s.title() if s else 'Scheda'


@traffico_bp.route('/api/traffico/schede', methods=['GET'])
def schede():
    """Chi ha visto e scaricato le schede operative (Academy → Risorse).
    Aggrega gli eventi scheda_vista / scheda_download e risolve l'identità
    del visitatore quando disponibile."""
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    giorni = request.args.get('giorni', 30, type=int)
    if giorni < 1 or giorni > 365:
        giorni = 30
    da = datetime.utcnow() - timedelta(days=giorni)

    eventi = EventoTraffico.query.filter(
        EventoTraffico.tipo.in_(list(SCHEDE_TIPI)),
        EventoTraffico.created_at >= da,
    ).order_by(EventoTraffico.created_at.desc()).all()

    # Identità per visitor_id (ultima identificazione nota, anche fuori finestra)
    vids = list({e.visitor_id for e in eventi if e.visitor_id})
    identita = {}
    if vids:
        ids = EventoTraffico.query.filter(
            EventoTraffico.tipo == 'identificazione',
            EventoTraffico.visitor_id.in_(vids),
        ).order_by(EventoTraffico.created_at.asc()).all()
        for e in ids:
            if e.valore:
                identita[e.visitor_id] = e.valore

    per_scheda = {}
    accessi = []
    dl_visitatori = set()
    for e in eventi:
        slug = (e.valore or '').strip()
        s = per_scheda.setdefault(slug, {
            'slug': slug, 'nome': _nome_scheda(slug),
            'viste': 0, 'download': 0, 'download_unici': set(),
        })
        if e.tipo == 'scheda_download':
            s['download'] += 1
            if e.visitor_id:
                s['download_unici'].add(e.visitor_id)
                dl_visitatori.add(e.visitor_id)
            azione = 'download'
        else:
            s['viste'] += 1
            azione = 'vista'
        accessi.append({
            'scheda': _nome_scheda(slug),
            'slug': slug,
            'azione': azione,
            'identita': identita.get(e.visitor_id),
            'visitor_id': e.visitor_id,
            'dispositivo': e.dispositivo,
            'fonte': _fonte(e.referrer),
            'quando': e.created_at.isoformat(),
        })

    schede_out = [{
        'slug': s['slug'], 'nome': s['nome'],
        'viste': s['viste'], 'download': s['download'],
        'download_unici': len(s['download_unici']),
    } for s in per_scheda.values()]
    schede_out.sort(key=lambda x: (x['download'], x['viste']), reverse=True)

    riepilogo = {
        'download_totali': sum(s['download'] for s in schede_out),
        'viste_totali': sum(s['viste'] for s in schede_out),
        'schede_attive': len(schede_out),
        'visitatori_download': len(dl_visitatori),
    }
    return jsonify({'giorni': giorni, 'riepilogo': riepilogo,
                    'schede': schede_out, 'accessi': accessi[:500]})


def _fmt_dt(dt):
    try:
        return dt.strftime('%d/%m %H:%M')
    except Exception:
        return ''


def _disp_label(d):
    return {'mobile': 'Mobile', 'tablet': 'Tablet',
            'desktop': 'Desktop'}.get(d, (d or '—').capitalize())


def _descrivi_evento(e):
    """Testo leggibile di un evento per la timeline del PDF."""
    t = e.tipo
    if t == 'pageview':
        return f"Pagina {e.pagina or '/'}"
    if t == 'click':
        return f"Click: {e.valore or ''}"
    if t == 'scroll':
        return f"Scroll {e.valore or ''}%"
    if t == 'tempo':
        return f"Tempo {e.valore or ''}s su {e.pagina or ''}"
    if t == 'identificazione':
        return f"Identificato: {e.valore or ''}"
    if t == 'scheda_download':
        return f"Scheda scaricata: {_nome_scheda(e.valore or '')}"
    if t == 'scheda_vista':
        return f"Esempio scheda visto: {_nome_scheda(e.valore or '')}"
    return t or 'evento'


@traffico_bp.route('/api/traffico/percorsi.pdf', methods=['GET'])
def percorsi_pdf():
    """Esporta in PDF tutti i percorsi dei visitatori del periodo."""
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    giorni = request.args.get('giorni', 30, type=int)
    if giorni < 1 or giorni > 365:
        giorni = 30
    da = datetime.utcnow() - timedelta(days=giorni)

    eventi = EventoTraffico.query.filter(
        EventoTraffico.created_at >= da
    ).order_by(EventoTraffico.created_at.asc()).all()

    vis = defaultdict(list)
    for e in eventi:
        vis[e.visitor_id].append(e)

    MAX_EVENTI = 80  # per visitatore, per evitare PDF enormi
    visitatori = []
    for vid, evs in vis.items():
        pageviews = [e for e in evs if e.tipo == 'pageview']
        ident = None
        for e in evs:
            if e.tipo == 'identificazione' and e.valore:
                ident = e.valore
        righe = [{
            'tipo': e.tipo,
            'testo': _descrivi_evento(e),
            'quando': _fmt_dt(e.created_at),
        } for e in evs[:MAX_EVENTI]]
        if len(evs) > MAX_EVENTI:
            righe.append({'tipo': '', 'quando': '',
                          'testo': f'… e altri {len(evs) - MAX_EVENTI} eventi'})
        visitatori.append({
            'identita': ident,
            'dispositivo': _disp_label(evs[0].dispositivo),
            'fonte': _fonte(evs[0].referrer),
            'prima_visita': _fmt_dt(evs[0].created_at),
            'ultima_attivita': _fmt_dt(evs[-1].created_at),
            '_ultima_dt': evs[-1].created_at,
            'pageviews': len(pageviews),
            'eventi_totali': len(evs),
            'eventi': righe,
        })

    visitatori.sort(key=lambda x: x['_ultima_dt'], reverse=True)
    visitatori = visitatori[:300]

    riepilogo = {
        'visitatori': len(vis),
        'convertiti': sum(1 for v in visitatori if v['identita']),
        'pageviews_totali': sum(v['pageviews'] for v in visitatori),
        'eventi_totali': len(eventi),
    }

    generato_il = datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')
    pdf = genera_percorsi_pdf(visitatori, giorni, generato_il, riepilogo)
    nome_file = f'percorsi-visitatori-{giorni}g.pdf'
    return send_file(pdf, mimetype='application/pdf',
                     as_attachment=True, download_name=nome_file)
