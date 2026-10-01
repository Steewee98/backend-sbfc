"""Rete SB, fase 1 — ricettario, vendite, scarichi, inventari e diagnosi.

Passo 3: ricettario (piatti, grammature, costo del piatto dai prezzi delle fatture).
Passo 4: vendite dal report della cassa, qualunque marca (CSV o Excel): giorno per giorno,
         oppure un report di periodo senza date (SumUp) che resta un blocco (services/vendite.py).
Passo 5: scarti, carichi senza fattura e inventari (anche dal tag NFC sullo scaffale).
Passo 6: la diagnosi del food cost tra due inventari (services/foodcost.py).

Chiave admin come il resto della rete.
"""
import json
import logging
import os
import threading
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, current_app, request, jsonify

from models import (db, LocaleRete, ArticoloRete, RicettaRete, RigaRicetta, AliasVendita, VenditaRete,
                    MovimentoRete, InventarioRete, RigaInventario, ReportCassa, VenditaPeriodo)
from routes.rete import admin_required, _testo
from routes.rete_dati import _num, _articolo_del_locale
from services.cassa import (leggi_tabella, proponi_colonne, estrai_vendite, normalizza_voce, periodo_dal_nome,
                            ReportNonLeggibile, EXTRA)
from services import vendite as V
from services.foodcost import costo_ricetta, costo_ricetta_dettaglio, diagnosi
from services.analisi_vendite import analizza, pulisci_articoli
from services import sumup

rete_fc_bp = Blueprint('rete_foodcost', __name__)
logger = logging.getLogger(__name__)
MAX_REPORT = 10 * 1024 * 1024


def _giorno(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _del_locale(modello, lid, oid):
    o = db.session.get(modello, oid)
    return o if o and o.locale_id == lid else None


# ── impostazioni del locale per il food cost ──

@rete_fc_bp.route('/api/rete/locali/<int:lid>/impostazioni', methods=['PATCH'])
@admin_required
def impostazioni(lid):
    l = LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    imp = dict(l.impostazioni or {})
    # giorni_scorta: per quanti giorni di menù deve bastare la merce (la scorta minima dell'inventario)
    for k, lo, hi in (('obiettivo', 5, 80), ('iva', 0, 25), ('giorni_scorta', 1, 30)):
        if k in d:
            v = _num(d[k])
            if v is None or not lo <= v <= hi:
                return jsonify({'error': f'Valore non valido per {k}'}), 400
            imp[k] = v
    if 'parametri' in d:
        # gli attesi degli indicatori per questo locale: {id: {atteso, toll}}
        par = dict(imp.get('parametri') or {})
        for k, v in (d['parametri'] or {}).items():
            if v is None:
                par.pop(k, None)
                continue
            a, t = _num((v or {}).get('atteso')), _num((v or {}).get('toll'), minimo=0)
            if a is None or t is None or len(k) > 20:
                return jsonify({'error': f'Atteso e tolleranza non validi per {k}'}), 400
            par[k] = {'atteso': a, 'toll': t}
        imp['parametri'] = par
    l.impostazioni = imp
    db.session.commit()
    return jsonify(imp)


# ── ricettario ──

def _ricette_vendute(lid):
    """Le ricette abbinate a un prodotto che compare nelle vendite caricate: sono piatti veri del locale."""
    voci = V.voci(lid)
    return {a.ricetta_id for a in AliasVendita.query.filter(AliasVendita.locale_id == lid, AliasVendita.ricetta_id.isnot(None)).all()
            if a.voce in voci}


def _ricetta_dict(r, iva=10, vendute=None):
    c = costo_ricetta_dettaglio(r, stime=True)
    costo, mancano = c['costo'], c['mancano']
    netto = r.prezzo / (1 + iva / 100) if r.prezzo else None
    return {'id': r.id, 'nome': r.nome, 'categoria': r.categoria, 'prezzo': r.prezzo, 'resa': r.resa,
            'righe': [{'id': x.id, 'articolo_id': x.articolo_id, 'quantita': x.quantita} for x in r.righe],
            'costo': costo, 'mancano_prezzi': mancano, 'prezzi_stimati': c['stimati'],
            'automatica': bool(r.automatica), 'nota': r.nota,
            # una ricetta automatica è «proposta» solo se non corrisponde a niente di venduto
            'in_vendita': (r.id in vendute) if vendute is not None else None,
            'food_cost': round(costo / netto * 100, 1) if costo is not None and netto else None}


def _iva(lid):
    return float((db.session.get(LocaleRete, lid).impostazioni or {}).get('iva', 10))


def _salva_righe(lid, ricetta, righe):
    nuove = []
    for x in righe or []:
        a = _articolo_del_locale(lid, int(x.get('articolo_id') or 0))
        q = _num(x.get('quantita'), minimo=0)
        if not a or not q:
            continue
        nuove.append(RigaRicetta(articolo_id=a.id, quantita=q))
    ricetta.righe = nuove


@rete_fc_bp.route('/api/rete/locali/<int:lid>/ricette', methods=['GET'])
@admin_required
def ricette(lid):
    LocaleRete.query.get_or_404(lid)
    q = RicettaRete.query.filter_by(locale_id=lid).order_by(RicettaRete.categoria, RicettaRete.nome)
    iva, vendute = _iva(lid), _ricette_vendute(lid)
    return jsonify([_ricetta_dict(r, iva, vendute) for r in q.all()])


@rete_fc_bp.route('/api/rete/locali/<int:lid>/ricette', methods=['POST'])
@admin_required
def crea_ricetta(lid):
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    nome = _testo(d.get('nome'), 160)
    if not nome:
        return jsonify({'error': 'Serve il nome del piatto'}), 400
    # se c'è già la proposta automatica con questo nome, la ricetta del consulente prende il suo posto
    r = next((x for x in RicettaRete.query.filter_by(locale_id=lid, automatica=True).all() if x.nome.lower() == nome.lower()), None)
    if r:
        r.nome, r.automatica, r.nota = nome, False, None
        r.categoria = _testo(d.get('categoria'), 60) or r.categoria
        r.prezzo = _num(d.get('prezzo'), minimo=0) if d.get('prezzo') is not None else r.prezzo
        r.resa = _num(d.get('resa'), minimo=0.01) or 1
    else:
        r = RicettaRete(locale_id=lid, nome=nome, categoria=_testo(d.get('categoria'), 60),
                        prezzo=_num(d.get('prezzo'), minimo=0), resa=_num(d.get('resa'), minimo=0.01) or 1)
    _salva_righe(lid, r, d.get('righe'))
    db.session.add(r)
    db.session.commit()
    return jsonify(_ricetta_dict(r, _iva(lid))), 201


@rete_fc_bp.route('/api/rete/locali/<int:lid>/ricette/<int:rid>', methods=['PATCH'])
@admin_required
def modifica_ricetta(lid, rid):
    r = _del_locale(RicettaRete, lid, rid)
    if not r:
        return jsonify({'error': 'Ricetta non trovata'}), 404
    d = request.get_json(silent=True) or {}
    if 'nome' in d:
        nome = _testo(d['nome'], 160)
        if not nome:
            return jsonify({'error': 'Il nome non può restare vuoto'}), 400
        r.nome = nome
    if 'categoria' in d:
        r.categoria = _testo(d['categoria'], 60)
    if 'prezzo' in d:
        r.prezzo = _num(d['prezzo'], minimo=0)
    if 'resa' in d:
        r.resa = _num(d['resa'], minimo=0.01) or 1
    if 'righe' in d:
        _salva_righe(lid, r, d['righe'])
    r.automatica = False                 # toccata dal consulente: l'analisi delle vendite non la riscrive più
    db.session.commit()
    pulisci_articoli(lid)                # un ingrediente tolto da questa ricetta, se non serve altrove, esce dall'inventario
    return jsonify(_ricetta_dict(r, _iva(lid)))


@rete_fc_bp.route('/api/rete/locali/<int:lid>/ricette/<int:rid>', methods=['DELETE'])
@admin_required
def elimina_ricetta(lid, rid):
    r = _del_locale(RicettaRete, lid, rid)
    if not r:
        return jsonify({'error': 'Ricetta non trovata'}), 404
    AliasVendita.query.filter_by(ricetta_id=r.id).delete()
    db.session.delete(r)
    db.session.commit()
    # gli ingredienti che servivano solo a questa ricetta escono anche dall'inventario
    return jsonify({'ok': True, 'articoli_tolti': pulisci_articoli(lid)})


# ── vendite dalla cassa ──

def _file_report():
    f = request.files.get('file')
    if not f or not f.filename:
        return None, None, (jsonify({'error': 'Nessun file'}), 400)
    dati = f.read()
    if len(dati) > MAX_REPORT:
        return None, None, (jsonify({'error': 'Il report supera i 10 MB'}), 413)
    return f.filename, dati, None


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite/anteprima', methods=['POST'])
@admin_required
def anteprima_vendite(lid):
    """Le colonne del report e le prime righe, con una proposta di abbinamento.
    Se il locale ha già un abbinamento per queste stesse colonne, si propone quello."""
    l = LocaleRete.query.get_or_404(lid)
    nome, dati, err = _file_report()
    if err:
        return err
    try:
        intest, righe = leggi_tabella(nome, dati)
    except ReportNonLeggibile as e:
        return jsonify({'error': str(e)}), 400
    salvate = (l.impostazioni or {}).get('colonne_cassa') or {}
    proposta = salvate.get('colonne') if salvate.get('intestazioni') == intest else proponi_colonne(intest)
    esempio = [[('' if c is None else str(c))[:60] for c in r[:len(intest)]] for r in righe[:6]]
    per = periodo_dal_nome(nome)
    return jsonify({'intestazioni': intest, 'righe': esempio, 'totale_righe': len(righe), 'proposta': proposta,
                    'periodo': {'dal': per[0].isoformat(), 'al': per[1].isoformat()} if per else None})


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite', methods=['POST'])
@admin_required
def importa_vendite(lid):
    """file + colonne (JSON {voce, quantita, incasso?, data?, netto?, iva?, sconti?, costo?, margine?}) e,
    se il report non ha la colonna della data, il periodo che copre: dal + al (oppure giorno, per un giorno solo).
    Un giorno solo si salva giorno per giorno; più giorni restano un blocco di periodo.
    Reimportare lo stesso giorno o lo stesso periodo sostituisce, così un report rifatto non si somma."""
    l = LocaleRete.query.get_or_404(lid)
    nome, dati, err = _file_report()
    if err:
        return err
    try:
        colonne = {k: int(v) for k, v in json.loads(request.form.get('colonne') or '{}').items() if v is not None and v != ''}
    except (ValueError, TypeError):
        return jsonify({'error': 'Abbinamento delle colonne non valido'}), 400
    f = request.form
    dal = _giorno(f.get('dal') or f.get('giorno')) if (f.get('dal') or f.get('giorno')) else None
    al = _giorno(f.get('al')) if f.get('al') else dal
    if colonne.get('data') is None and not dal:
        per = periodo_dal_nome(nome)
        dal, al = per if per else (None, None)
    if dal and al and dal > al:
        return jsonify({'error': 'Il periodo va dal giorno più vecchio al più recente'}), 400
    periodo = colonne.get('data') is None and dal and al and dal < al
    try:
        intest, righe = leggi_tabella(nome, dati)
        vendite, saltate = estrai_vendite(righe, colonne, None if colonne.get('data') is not None else dal)
    except ReportNonLeggibile as e:
        return jsonify({'error': str(e)}), 400
    if not vendite:
        return jsonify({'error': 'Nessuna riga di vendita riconosciuta con queste colonne'}), 400

    if periodo:
        # stesso periodo esatto: si sostituisce; un periodo che si accavalla con altro: si ferma
        stesso = ReportCassa.query.filter_by(locale_id=lid, dal=dal, al=al).first()
        perche = V.sovrapposti(lid, dal, al, tranne=stesso.id if stesso else None)
        if perche:
            return jsonify({'error': f'Non carico il periodo dal {dal.strftime("%d/%m/%Y")} al {al.strftime("%d/%m/%Y")}: '
                                     f'{perche}. Le stesse vendite si conterebbero due volte.'}), 409
    else:
        r = V.blocco_su_giorni(lid, {g for g, _ in vendite})
        if r:
            return jsonify({'error': f'Questi giorni sono già dentro il report dal {r.dal.strftime("%d/%m/%Y")} '
                                     f'al {r.al.strftime("%d/%m/%Y")}: toglilo prima, se no le vendite si contano due volte.'}), 409

    imp = dict(l.impostazioni or {})
    imp['colonne_cassa'] = {'intestazioni': intest, 'colonne': colonne}
    l.impostazioni = imp
    if periodo:
        if stesso:
            db.session.delete(stesso)
            db.session.flush()
        rep = ReportCassa(locale_id=lid, dal=dal, al=al, nome_file=(nome or '')[:200])
        db.session.add(rep)
        for (_, voce), x in vendite.items():
            rep.righe.append(VenditaPeriodo(locale_id=lid, dal=dal, al=al, voce=voce, voce_originale=x['originale'], nomi=x.get('nomi'),
                                            **{k: x.get(k) for k in V.CAMPI}))
        db.session.commit()
        analisi = _analizza_dopo(l)
        return jsonify({'periodo': True, 'report': V.riassunto(rep), 'righe': len(vendite),
                        'giorni': (al - dal).days + 1, 'dal': dal.isoformat(), 'al': al.isoformat(),
                        'sostituito': bool(stesso), 'saltate': saltate, 'analisi': analisi,
                        'voci_da_abbinare': _da_abbinare(lid)})
    esito = _salva_vendite(lid, vendite)
    esito['saltate'] = saltate
    esito['analisi'] = _analizza_dopo(l)
    esito['voci_da_abbinare'] = _da_abbinare(lid)
    return jsonify(esito)


def _da_abbinare(lid):
    """Le voci (già unite) senza una ricetta e non messe fuori dal food cost."""
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    return sum(1 for v in V.voci(lid) if not (alias.get(v) and (alias[v].ricetta_id or alias[v].ignorata)))


def _analizza_dopo(l):
    """Dopo ogni cassa caricata o tolta: l'analisi col catalogo subito (unioni, categorie, ricette);
    quello che il catalogo non conosce lo guarda Claude in sottofondo, se c'è la chiave."""
    try:
        r = analizza(l, ai=False)
    except Exception:
        logger.exception('Analisi delle vendite del locale %s', l.id)
        db.session.rollback()
        return None
    if r['non_riconosciute'] and os.environ.get('ANTHROPIC_API_KEY'):
        app, lid = current_app._get_current_object(), l.id

        def con_ai():
            with app.app_context():
                try:
                    analizza(db.session.get(LocaleRete, lid), ai=True)
                except Exception:
                    logger.exception('Analisi delle vendite con Claude, locale %s', lid)
        threading.Thread(target=con_ai, daemon=True, name=f'analisi-{lid}').start()
    return r


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite/analisi', methods=['GET'])
@admin_required
def analisi_vendite(lid):
    """L'ultima analisi delle vendite: voci unite, categorie, ricette proposte, cosa resta da chiarire."""
    l = LocaleRete.query.get_or_404(lid)
    return jsonify((l.impostazioni or {}).get('analisi_vendite'))


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite/analisi', methods=['POST'])
@admin_required
def rifai_analisi(lid):
    """{ai?}: rifà l'analisi adesso; con ai anche le voci che il catalogo non conosce (qualche centesimo)."""
    l = LocaleRete.query.get_or_404(lid)
    ai = bool((request.get_json(silent=True) or {}).get('ai'))
    return jsonify(analizza(l, ai=ai))


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite/report', methods=['GET'])
@admin_required
def report_di_periodo(lid):
    """I report di periodo caricati, coi loro totali, dal più recente."""
    LocaleRete.query.get_or_404(lid)
    return jsonify([V.riassunto(r) for r in ReportCassa.query.filter_by(locale_id=lid)
                    .order_by(ReportCassa.al.desc(), ReportCassa.dal.desc()).all()])


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite/report/<int:rid>', methods=['DELETE'])
@admin_required
def togli_report(lid, rid):
    r = _del_locale(ReportCassa, lid, rid)
    if not r:
        return jsonify({'error': 'Report non trovato'}), 404
    db.session.delete(r)          # le righe vanno via con lui (cascade dell'ORM: SQLite non lo fa da solo)
    db.session.commit()
    _analizza_dopo(db.session.get(LocaleRete, lid))
    return jsonify({'ok': True})


def _salva_vendite(lid, vendite, giorni_interi=()):
    """{(giorno, voce normalizzata): {quantita, incasso, netto…, originale}} → tabella vendite.
    Stesso giorno e stessa voce: si sostituisce. `giorni_interi`: giorni riletti per intero
    dalla cassa, dove le voci che non ci sono più si tolgono."""
    giorni_toccati = {g for g, _ in vendite} | set(giorni_interi)
    esistenti = {(v.giorno, v.voce): v for v in VenditaRete.query.filter(
        VenditaRete.locale_id == lid, VenditaRete.giorno.in_(giorni_toccati)).all()} if giorni_toccati else {}
    for (g, voce), x in vendite.items():
        v = esistenti.pop((g, voce), None)
        if not v:
            v = VenditaRete(locale_id=lid, giorno=g, voce=voce)
            db.session.add(v)
        v.voce_originale, v.quantita, v.incasso, v.nomi = x['originale'], x['quantita'], x['incasso'], x.get('nomi')
        for k in EXTRA + ('resi_quantita', 'resi_incasso'):
            setattr(v, k, x.get(k))
    for (g, _), v in esistenti.items():
        if g in giorni_interi:
            db.session.delete(v)
    db.session.commit()
    giorni = sorted({g for g, _ in vendite})
    noti = {a.voce for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    return {'righe': len(vendite), 'giorni': len(giorni),
            'dal': giorni[0].isoformat() if giorni else None, 'al': giorni[-1].isoformat() if giorni else None,
            'voci_da_abbinare': len({voce for _, voce in vendite} - noti)}


@rete_fc_bp.route('/api/rete/locali/<int:lid>/vendite', methods=['GET'])
@admin_required
def vendite_per_giorno(lid):
    LocaleRete.query.get_or_404(lid)
    per = defaultdict(lambda: {'pezzi': 0.0, 'incasso': 0.0, 'voci': 0})
    for v in VenditaRete.query.filter_by(locale_id=lid).all():
        x = per[v.giorno.isoformat()]
        x['pezzi'] += v.quantita
        x['incasso'] += v.incasso or 0
        x['voci'] += 1
    return jsonify([{'giorno': g, **{k: round(v, 2) if isinstance(v, float) else v for k, v in x.items()}}
                    for g, x in sorted(per.items(), reverse=True)])


@rete_fc_bp.route('/api/rete/locali/<int:lid>/voci', methods=['GET'])
@admin_required
def voci(lid):
    """Tutte le voci della cassa con il loro abbinamento; quelle da fare per prime, le più vendute in cima."""
    LocaleRete.query.get_or_404(lid)
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    tot = defaultdict(lambda: {'quantita': 0.0, 'incasso': 0.0, 'originale': None, 'cassa': set()})
    for v in V.vendite(lid):
        x = tot[v.voce]
        x['quantita'] += v.quantita
        x['incasso'] += v.incasso or 0
        x['originale'] = x['originale'] or v.voce_originale
        x['cassa'] |= v.nomi_cassa                   # come la cassa scrive questa voce: per mostrare cosa è stato unito
    out = []
    for voce, x in tot.items():
        a = alias.get(voce)
        out.append({'voce': voce, 'nome': x['originale'] or voce, 'quantita': round(x['quantita'], 2),
                    'incasso': round(x['incasso'], 2), 'ricetta_id': a.ricetta_id if a else None,
                    'ignorata': bool(a and a.ignorata), 'categoria': a.categoria if a else None,
                    'automatico': bool(a and a.automatico),
                    'uniti': sorted(x['cassa']) if len(x['cassa']) > 1 else [],
                    'da_fare': not (a and (a.ricetta_id or a.ignorata))})
    out.sort(key=lambda x: (not x['da_fare'], -x['incasso'], -x['quantita']))
    return jsonify(out)


@rete_fc_bp.route('/api/rete/locali/<int:lid>/voci', methods=['POST'])
@admin_required
def abbina_voce(lid):
    """{voce, ricetta_id} oppure {voce, ignora: true} (coperto, bevande, caffè)."""
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    voce = normalizza_voce(d.get('voce'))
    if not voce:
        return jsonify({'error': 'Voce mancante'}), 400
    a = AliasVendita.query.filter_by(locale_id=lid, voce=voce).first() or AliasVendita(locale_id=lid, voce=voce)
    if d.get('ignora'):
        a.ricetta_id, a.ignorata = None, True
    else:
        r = _del_locale(RicettaRete, lid, int(d.get('ricetta_id') or 0))
        if not r:
            return jsonify({'error': 'Ricetta non trovata'}), 404
        a.ricetta_id, a.ignorata = r.id, False
    a.automatico = False                 # scelta del consulente: l'analisi non la cambia
    db.session.add(a)
    db.session.commit()
    return jsonify({'ok': True})


# ── cassa SumUp: le vendite senza report ──

@rete_fc_bp.route('/api/rete/locali/<int:lid>/sumup', methods=['POST'])
@admin_required
def collega_sumup(lid):
    """{chiave}: la chiave API del conto SumUp del locale. Si prova subito e si salva cifrata."""
    l = LocaleRete.query.get_or_404(lid)
    chiave = ((request.get_json(silent=True) or {}).get('chiave') or '').strip()
    if len(chiave) < 10:
        return jsonify({'error': 'Incolla la chiave API di SumUp'}), 400
    try:
        codice, nome = sumup.profilo(chiave)
    except sumup.ErroreSumUp as e:
        return jsonify({'error': str(e)}), 400
    imp = dict(l.impostazioni or {})
    imp['sumup'] = {'chiave': sumup.cifra(chiave), 'esercente': codice, 'nome': nome, 'collegata': date.today().isoformat()}
    l.impostazioni = imp
    db.session.commit()
    return jsonify({'esercente': codice, 'nome': nome})


@rete_fc_bp.route('/api/rete/locali/<int:lid>/sumup', methods=['DELETE'])
@admin_required
def scollega_sumup(lid):
    l = LocaleRete.query.get_or_404(lid)
    imp = dict(l.impostazioni or {})
    imp.pop('sumup', None)
    l.impostazioni = imp
    db.session.commit()
    return jsonify({'ok': True})


@rete_fc_bp.route('/api/rete/locali/<int:lid>/sumup/scarica', methods=['POST'])
@admin_required
def scarica_sumup(lid):
    """{dal, al}: scarica e riscrive le vendite di quei giorni (al massimo 62 alla volta)."""
    l = LocaleRete.query.get_or_404(lid)
    su = (l.impostazioni or {}).get('sumup')
    if not su:
        return jsonify({'error': 'La cassa SumUp non è collegata'}), 400
    d = request.get_json(silent=True) or {}
    al = _giorno(d.get('al')) or date.today()
    dal = _giorno(d.get('dal')) or al
    if dal > al or (al - dal).days > 61:
        return jsonify({'error': 'Scegli al massimo 62 giorni, dal più vecchio al più recente'}), 400
    try:
        righe, n = sumup.vendite(sumup.decifra(su['chiave']), su['esercente'], dal, al)
    except sumup.ErroreSumUp as e:
        return jsonify({'error': str(e)}), 400
    vendite = {}
    for (g, nome), x in righe.items():
        k = (g, normalizza_voce(nome))
        y = vendite.setdefault(k, {'quantita': 0.0, 'incasso': 0.0, 'originale': nome[:200]})
        y['quantita'] += x['quantita']
        y['incasso'] = round(y['incasso'] + x['incasso'], 2)
    giorni = [dal + timedelta(days=i) for i in range((al - dal).days + 1)]
    r = V.blocco_su_giorni(lid, giorni)
    if r:
        return jsonify({'error': f'Dal {r.dal.strftime("%d/%m/%Y")} al {r.al.strftime("%d/%m/%Y")} c\'è già un report di periodo: '
                                 'scarica i giorni fuori da quel periodo, oppure togli il report.'}), 409
    esito = _salva_vendite(lid, vendite, giorni_interi=giorni)
    imp = dict(l.impostazioni or {})
    imp['sumup'] = {**su, 'ultimo': al.isoformat()}
    l.impostazioni = imp
    db.session.commit()
    esito['analisi'] = _analizza_dopo(l)
    esito['voci_da_abbinare'] = _da_abbinare(lid)
    esito['transazioni'] = n
    return jsonify(esito)


# ── scarti e carichi senza fattura ──

@rete_fc_bp.route('/api/rete/locali/<int:lid>/movimenti', methods=['GET'])
@admin_required
def movimenti(lid):
    LocaleRete.query.get_or_404(lid)
    q = MovimentoRete.query.filter_by(locale_id=lid).order_by(MovimentoRete.giorno.desc(), MovimentoRete.id.desc())
    return jsonify([{'id': m.id, 'giorno': m.giorno.isoformat(), 'articolo_id': m.articolo_id, 'tipo': m.tipo,
                     'quantita': m.quantita, 'nota': m.nota} for m in q.limit(300).all()])


@rete_fc_bp.route('/api/rete/locali/<int:lid>/movimenti', methods=['POST'])
@admin_required
def crea_movimento(lid):
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    a = _articolo_del_locale(lid, int(d.get('articolo_id') or 0))
    q, g = _num(d.get('quantita'), minimo=0), _giorno(d.get('giorno')) or date.today()
    if not a or not q or d.get('tipo') not in ('scarto', 'carico'):
        return jsonify({'error': 'Servono articolo, tipo (scarto o carico) e quantità'}), 400
    m = MovimentoRete(locale_id=lid, giorno=g, articolo_id=a.id, tipo=d['tipo'], quantita=q, nota=_testo(d.get('nota'), 200))
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id}), 201


@rete_fc_bp.route('/api/rete/locali/<int:lid>/movimenti/<int:mid>', methods=['DELETE'])
@admin_required
def elimina_movimento(lid, mid):
    m = _del_locale(MovimentoRete, lid, mid)
    if not m:
        return jsonify({'error': 'Movimento non trovato'}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})


# ── inventari ──

def _inv_dict(i):
    return {'id': i.id, 'giorno': i.giorno.isoformat(), 'chiuso': i.chiuso,
            'righe': {str(r.articolo_id): r.quantita for r in i.righe}}


@rete_fc_bp.route('/api/rete/locali/<int:lid>/inventari', methods=['GET'])
@admin_required
def inventari(lid):
    LocaleRete.query.get_or_404(lid)
    q = InventarioRete.query.filter_by(locale_id=lid).order_by(InventarioRete.giorno.desc())
    return jsonify([_inv_dict(i) for i in q.all()])


@rete_fc_bp.route('/api/rete/locali/<int:lid>/inventari', methods=['POST'])
@admin_required
def crea_inventario(lid):
    """Apre (o riapre) l'inventario di un giorno; di default oggi."""
    LocaleRete.query.get_or_404(lid)
    g = _giorno((request.get_json(silent=True) or {}).get('giorno')) or date.today()
    i = InventarioRete.query.filter_by(locale_id=lid, giorno=g).first()
    if not i:
        i = InventarioRete(locale_id=lid, giorno=g)
        db.session.add(i)
        db.session.commit()
    return jsonify(_inv_dict(i)), 201


@rete_fc_bp.route('/api/rete/locali/<int:lid>/inventari/<int:iid>', methods=['PATCH'])
@admin_required
def conta(lid, iid):
    """{righe: {articolo_id: quantità | null}, chiuso?}. null toglie la riga (non contato)."""
    i = _del_locale(InventarioRete, lid, iid)
    if not i:
        return jsonify({'error': 'Inventario non trovato'}), 404
    d = request.get_json(silent=True) or {}
    attuali = {r.articolo_id: r for r in i.righe}
    for k, v in (d.get('righe') or {}).items():
        a = _articolo_del_locale(lid, int(k))
        if not a:
            continue
        if v is None or v == '':
            if a.id in attuali:
                i.righe.remove(attuali.pop(a.id))
            continue
        q = _num(v, minimo=0)
        if q is None:
            return jsonify({'error': f'Quantità non valida per {a.nome}'}), 400
        if a.id in attuali:
            attuali[a.id].quantita = q
        else:
            attuali[a.id] = RigaInventario(articolo_id=a.id, quantita=q)
            i.righe.append(attuali[a.id])
    if 'chiuso' in d:
        i.chiuso = bool(d['chiuso'])
    db.session.commit()
    return jsonify(_inv_dict(i))


@rete_fc_bp.route('/api/rete/locali/<int:lid>/inventari/<int:iid>', methods=['DELETE'])
@admin_required
def elimina_inventario(lid, iid):
    i = _del_locale(InventarioRete, lid, iid)
    if not i:
        return jsonify({'error': 'Inventario non trovato'}), 404
    db.session.delete(i)
    db.session.commit()
    return jsonify({'ok': True})


# ── la rete: un semaforo per locale ──

def semaforo(d):
    """Dalla diagnosi al colore della console: il food cost vero contro l'obiettivo
    e il consumo oltre ricetta, che è la perdita su cui il consulente può intervenire."""
    if not d or d.get('food_cost_reale') is None:
        return 'vuoto'
    fc, ob, consumo = d['food_cost_reale'], d['obiettivo'], d['voci']['consumo']['punti'] or 0
    if fc > ob + 2 or consumo >= 1:
        return 'fuori'
    if fc > ob or consumo >= 0.3:
        return 'attesa'
    return 'buono'


def _settimana(l):
    """Gli ultimi 7 giorni del locale, per la scheda della rete: incasso, personale, chiusure, turni dimenticati."""
    from services.quadro import _incasso, _personale, giorno_di_lavoro
    from models import ChiusuraRete, TurnoRete
    from datetime import datetime
    oggi = giorno_di_lavoro()
    al, dal = oggi - timedelta(days=1), oggi - timedelta(days=7)
    inc, giorni = _incasso(l.id, dal, al)
    inc0, _ = _incasso(l.id, dal - timedelta(days=7), dal - timedelta(days=1))
    _, costo, _ = _personale(l.id, dal, al)
    netto = inc / (1 + float((l.impostazioni or {}).get('iva', 10)) / 100)
    return {'incasso': round(inc, 2), 'variazione': round((inc - inc0) / inc0 * 100, 1) if inc0 else None, 'giorni': giorni,
            'personale': round(costo / netto * 100, 1) if netto and costo else None,
            'chiusure': ChiusuraRete.query.filter(ChiusuraRete.locale_id == l.id, ChiusuraRete.giorno >= dal, ChiusuraRete.giorno <= al).count(),
            'turni_dimenticati': TurnoRete.query.filter(TurnoRete.locale_id == l.id, TurnoRete.fine.is_(None),
                                                        TurnoRete.inizio < datetime.utcnow() - timedelta(hours=14)).count()}


@rete_fc_bp.route('/api/rete/riepilogo', methods=['GET'])
@admin_required
def riepilogo():
    """Tutti i locali con l'ultima diagnosi e le cose rimaste da fare."""
    from models import FatturaRete, RigaFattura
    from services.indicatori import indicatori
    out = []
    for l in LocaleRete.query.order_by(LocaleRete.nome).all():
        chiusi = (InventarioRete.query.filter_by(locale_id=l.id, chiuso=True)
                  .order_by(InventarioRete.giorno.desc()).limit(2).all())
        d = diagnosi(l, chiusi[1], chiusi[0]) if len(chiusi) == 2 else None
        da_collegare = (db.session.query(RigaFattura.chiave).join(FatturaRete)
                        .filter(FatturaRete.locale_id == l.id, RigaFattura.articolo_id.is_(None),
                                RigaFattura.quantita.isnot(None), RigaFattura.ignorata.isnot(True), db.func.coalesce(FatturaRete.tipo, '') != 'DDT')
                        .distinct().count())
        noti = {a.voce for a in AliasVendita.query.filter_by(locale_id=l.id).all()}
        voci = V.voci(l.id)
        x = l.to_dict()
        x.update({
            'semaforo': semaforo(d),
            'diagnosi': {k: d[k] for k in ('dal', 'al', 'food_cost_reale', 'food_cost_teorico', 'obiettivo', 'frase')}
                        | {'consumo_punti': d['voci']['consumo']['punti']} if d else None,
            'ultimo_inventario': chiusi[0].giorno.isoformat() if chiusi else None,
            'da_collegare': da_collegare, 'voci_da_abbinare': len(voci - noti),
            'ricette': RicettaRete.query.filter_by(locale_id=l.id).count(),
            'settimana': _settimana(l),
        })
        ind = indicatori(l)
        x['indicatori'] = {'conta': ind['conta'], 'fuori': ind['fuori']}
        out.append(x)
    return jsonify(out)


# ── diagnosi ──

@rete_fc_bp.route('/api/rete/locali/<int:lid>/diagnosi', methods=['GET'])
@admin_required
def diagnosi_periodo(lid):
    """?dal=<id inventario>&al=<id inventario>; senza, gli ultimi due inventari chiusi."""
    l = LocaleRete.query.get_or_404(lid)
    if request.args.get('dal') and request.args.get('al'):
        a = _del_locale(InventarioRete, lid, int(request.args['dal']))
        b = _del_locale(InventarioRete, lid, int(request.args['al']))
    else:
        chiusi = (InventarioRete.query.filter_by(locale_id=lid, chiuso=True)
                  .order_by(InventarioRete.giorno.desc()).limit(2).all())
        b, a = (chiusi + [None, None])[:2]
    if not a or not b:
        return jsonify({'error': 'Servono due inventari chiusi: la diagnosi si calcola tra l\'uno e l\'altro'}), 400
    if a.giorno >= b.giorno:
        a, b = b, a
    if a.giorno == b.giorno:
        return jsonify({'error': 'I due inventari sono dello stesso giorno'}), 400
    return jsonify(diagnosi(l, a, b))
