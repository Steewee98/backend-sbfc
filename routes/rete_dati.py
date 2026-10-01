"""Rete SB, fase 1 — i dati del food cost di un locale.

Passo 2: le fatture di acquisto e l'anagrafica degli articoli.
  - il consulente carica i documenti d'acquisto come li ha: fatture elettroniche
    (XML, .p7m), PDF, foto di fatture e di bolle, anche tutti mischiati in uno ZIP.
    Gli XML si leggono subito; PDF e foto li legge Claude in sottofondo
    (services.lettura_ai) e la pagina segue l'avanzamento;
  - ogni riga si collega a un articolo del locale con un alias, che il
    sistema ricorda: la seconda fattura dello stesso fornitore si collega da sola;
  - il prezzo dell'articolo è quello dell'ultima fattura collegata.

Stessa protezione del resto della rete: chiave admin (X-Admin-Token).
"""
import hashlib
from datetime import datetime
import io
import logging
import os
import re
import secrets
import threading
import time
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError

from models import db, LocaleRete, ArticoloRete, AliasArticolo, FatturaRete, RigaFattura, RicettaRete
from routes.rete import admin_required, _testo
from services.fatturapa import leggi_file, leggi_xml, suggerisci_fattore, normalizza, FatturaNonLeggibile
from services import lettura_ai

logger = logging.getLogger(__name__)
rete_dati_bp = Blueprint('rete_dati', __name__)

UNITA = ('kg', 'l', 'pz')
MAX_UPLOAD = 60 * 1024 * 1024
MAX_FILE_CARICATI = 60
MAX_NEL_ZIP = 200
LETTURE_INSIEME = 3


def _num(v, minimo=None):
    try:
        x = float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    if x != x or (minimo is not None and x < minimo):   # NaN o sotto il minimo
        return None
    return x


def _articolo_del_locale(lid, aid):
    a = db.session.get(ArticoloRete, aid) if aid else None
    return a if a and a.locale_id == lid else None


def aggiorna_prezzo(articolo):
    """Prezzo per unità dall'ultima riga di fattura collegata (note di credito escluse)."""
    riga = (RigaFattura.query.join(FatturaRete)
            .filter(RigaFattura.articolo_id == articolo.id, RigaFattura.quantita_articolo > 0,
                    RigaFattura.totale > 0, FatturaRete.segno == 1)
            .order_by(FatturaRete.data.desc(), RigaFattura.id.desc()).first())
    if riga:
        articolo.prezzo = round(riga.totale / riga.quantita_articolo, 4)
        articolo.prezzo_data = riga.fattura.data
    else:
        articolo.prezzo, articolo.prezzo_data = None, None


def _applica_alias(righe, alias_per_chiave):
    toccati = set()
    for r in righe:
        al = alias_per_chiave.get(r.chiave)
        if al and r.quantita:
            r.articolo_id = al.articolo_id
            r.quantita_articolo = round(r.quantita * al.fattore, 4)
            toccati.add(al.articolo_id)
    return toccati


# ── articoli ──

@rete_dati_bp.route('/api/rete/locali/<int:lid>/articoli', methods=['GET'])
@admin_required
def articoli(lid):
    LocaleRete.query.get_or_404(lid)
    q = ArticoloRete.query.filter_by(locale_id=lid).order_by(ArticoloRete.nome)
    from services.analisi_vendite import uso_articoli, consumi, GIORNI_SCORTA
    uso = uso_articoli(lid)
    al_giorno, giorni, _, _ = consumi(lid)
    scorta = float((db.session.get(LocaleRete, lid).impostazioni or {}).get('giorni_scorta') or GIORNI_SCORTA)
    # in_ricette: in quante ricette entra; da_fattura: è collegato a una fattura. Va in inventario se è l'uno o l'altro.
    # scorta_minima: quanto serve per reggere il menù per `giorni_scorta` giorni, al consumo medio delle vendite
    return jsonify([{**a.to_dict(), **uso.get(a.id, {'in_ricette': 0, 'da_fattura': False}),
                     'da_contare': bool(uso.get(a.id, {}).get('in_ricette') or uso.get(a.id, {}).get('da_fattura')),
                     'consumo_giorno': round(al_giorno[a.id], 4) if a.id in al_giorno else None,
                     'scorta_minima': round(al_giorno[a.id] * scorta, 3) if a.id in al_giorno else None,
                     'giorni_scorta': scorta, 'giorni_vendite': giorni}
                    for a in q.all()])


@rete_dati_bp.route('/api/rete/locali/<int:lid>/articoli/<int:aid>/scheda', methods=['GET'])
@admin_required
def scheda_articolo(lid, aid):
    """Tutto su un ingrediente, per la scheda che si apre dall'inventario: in quali ricette entra e quanto,
    quanto se ne consuma, le consegne (ultima e storico, fornitore e prezzo), scarti e carichi."""
    from models import RicettaRete, RigaRicetta, MovimentoRete
    from services.analisi_vendite import consumi, GIORNI_SCORTA
    a = _articolo_del_locale(lid, aid)
    if not a:
        return jsonify({'error': 'Articolo non trovato'}), 404
    l = db.session.get(LocaleRete, lid)
    al_giorno, giorni, dal, al = consumi(lid)
    scorta = float((l.impostazioni or {}).get('giorni_scorta') or GIORNI_SCORTA)

    # le ricette: quanto ne serve per una porzione (le quantità sono per tutta la resa)
    ricette = []
    for rr in (RigaRicetta.query.join(RicettaRete).filter(RicettaRete.locale_id == lid, RigaRicetta.articolo_id == aid).all()):
        r = rr.ricetta
        ricette.append({'id': r.id, 'nome': r.nome, 'categoria': r.categoria, 'per_porzione': round(rr.quantita / (r.resa or 1), 5),
                        'automatica': bool(r.automatica)})
    ricette.sort(key=lambda x: (-x['per_porzione'], x['nome']))

    # le consegne: fatture e bolle con questo articolo, la più recente prima
    righe = (RigaFattura.query.join(FatturaRete)
             .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id == aid)
             .order_by(FatturaRete.data.desc(), RigaFattura.id.desc()).limit(15).all())
    consegne = [{'data': x.fattura.data.isoformat() if x.fattura.data else None, 'fornitore': x.fattura.fornitore,
                 'documento': 'bolla' if x.fattura.tipo == 'DDT' else ('nota di credito' if (x.fattura.segno or 1) < 0 else 'fattura'),
                 'numero': x.fattura.numero, 'descrizione': x.descrizione, 'quantita': x.quantita_articolo,
                 'totale': x.totale, 'prezzo_unitario': round(x.totale / x.quantita_articolo, 4) if x.totale and x.quantita_articolo else None}
                for x in righe]
    movimenti = [{'data': m.giorno.isoformat(), 'tipo': m.tipo, 'quantita': m.quantita, 'nota': m.nota}
                 for m in MovimentoRete.query.filter_by(locale_id=lid, articolo_id=aid).order_by(MovimentoRete.giorno.desc()).limit(10).all()]
    return jsonify({
        'articolo': a.to_dict(), 'ricette': ricette,
        'consumo_giorno': round(al_giorno[aid], 4) if aid in al_giorno else None,
        'scorta_minima': round(al_giorno[aid] * scorta, 3) if aid in al_giorno else None,
        'giorni_scorta': scorta, 'vendite': {'giorni': giorni, 'dal': dal.isoformat() if dal else None, 'al': al.isoformat() if al else None},
        'ultima_consegna': next((x for x in consegne if x['documento'] != 'nota di credito'), None),
        'consegne': consegne, 'movimenti': movimenti,
    })


@rete_dati_bp.route('/api/rete/locali/<int:lid>/articoli', methods=['POST'])
@admin_required
def crea_articolo(lid):
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    nome, unita = _testo(d.get('nome'), 160), (d.get('unita') or 'kg').lower()
    if not nome:
        return jsonify({'error': 'Serve il nome dell\'articolo'}), 400
    if unita not in UNITA:
        return jsonify({'error': 'Unità non valida: kg, l o pz'}), 400
    a = ArticoloRete(locale_id=lid, nome=nome, unita=unita, categoria=_testo(d.get('categoria'), 60))
    db.session.add(a)
    db.session.commit()
    return jsonify(a.to_dict()), 201


@rete_dati_bp.route('/api/rete/locali/<int:lid>/articoli/<int:aid>', methods=['PATCH'])
@admin_required
def modifica_articolo(lid, aid):
    a = _articolo_del_locale(lid, aid)
    if not a:
        return jsonify({'error': 'Articolo non trovato'}), 404
    d = request.get_json(silent=True) or {}
    if 'nome' in d:
        nome = _testo(d['nome'], 160)
        if not nome:
            return jsonify({'error': 'Il nome non può restare vuoto'}), 400
        a.nome = nome
    if 'categoria' in d:
        a.categoria = _testo(d['categoria'], 60)
    if 'unita' in d and d['unita'] != a.unita:
        # cambiare unità renderebbe sbagliate le quantità già collegate
        if AliasArticolo.query.filter_by(articolo_id=a.id).first():
            return jsonify({'error': 'L\'articolo ha già fatture collegate: l\'unità non si cambia'}), 409
        if d['unita'] not in UNITA:
            return jsonify({'error': 'Unità non valida: kg, l o pz'}), 400
        a.unita = d['unita']
    db.session.commit()
    return jsonify(a.to_dict())


@rete_dati_bp.route('/api/rete/locali/<int:lid>/articoli/<int:aid>', methods=['DELETE'])
@admin_required
def elimina_articolo(lid, aid):
    a = _articolo_del_locale(lid, aid)
    if not a:
        return jsonify({'error': 'Articolo non trovato'}), 404
    RigaFattura.query.filter_by(articolo_id=a.id).update({'articolo_id': None, 'quantita_articolo': None})
    AliasArticolo.query.filter_by(articolo_id=a.id).delete()
    db.session.delete(a)
    db.session.commit()
    return jsonify({'ok': True})


# ── fatture ──

def _pezzi(nome, dati, profondita=0):
    """Un file caricato → i documenti da leggere: ('xml', nome, fattura | errore) oppure ('ai', nome, byte).
    Gli ZIP si aprono (anche uno dentro l'altro) e il loro contenuto può essere mischiato."""
    base = (nome or '').split('/')[-1]
    if dati[:2] == b'PK' or base.lower().endswith('.zip'):
        if profondita > 2:
            return [('xml', base, FatturaNonLeggibile('Troppi ZIP uno dentro l\'altro'))]
        try:
            z = zipfile.ZipFile(io.BytesIO(dati))
        except zipfile.BadZipFile:
            return [('xml', base, FatturaNonLeggibile('ZIP rovinato'))]
        out = []
        voci = [i for i in z.infolist() if not i.is_dir() and '__MACOSX' not in i.filename
                and not i.filename.split('/')[-1].startswith(('.', '~'))]
        for info in voci[:MAX_NEL_ZIP]:
            if info.file_size > MAX_UPLOAD:
                out.append(('xml', info.filename, FatturaNonLeggibile('File troppo grande')))
                continue
            dentro = z.read(info)
            n = info.filename.split('/')[-1]
            if not re.search(r'\.(xml|p7m|zip|pdf|jpe?g|png|webp|heic|heif|gif)$', n, re.I) and not lettura_ai.tipo_file(n, dentro):
                continue    # LEGGIMI.txt, fogli di calcolo, file di sistema: si saltano senza errore
            out.extend(_pezzi(n, dentro, profondita + 1))
        return out
    t = lettura_ai.tipo_file(base, dati)
    if not t and not re.search(r'\.(xml|p7m)$', base, re.I) and b'<' not in dati[:200] and dati[:1] != b'\x30':
        return [('salta', base, None)]     # LEGGIMI.txt, un foglio Excel: non è un documento d'acquisto
    if t == 'pdf':
        xml = lettura_ai.xml_dentro_pdf(dati)
        if xml:
            try:
                return [('xml', base, f) for f in leggi_xml(xml)]
            except FatturaNonLeggibile:
                pass
        return [('ai', base, dati)]
    if t == 'immagine':
        return [('ai', base, dati)]
    return [('xml', n, f) for n, f in leggi_file(base, dati)]


def _numero(n):
    return re.sub(r'[^0-9A-Z]', '', (n or '').upper())


ANNI = {'2024', '2025', '2026', '2027', '2028', '24', '25', '26', '27', '28'}


def _stesso_numero(a, b):
    """«112/26» e «112-26», «778/2026» e «2026/778», «PL-88» e «88»: lo stesso documento scritto diversamente."""
    if _numero(a) == _numero(b):
        return True
    ga = {g for g in re.findall(r'\d+', a or '') if g.lstrip('0') and g not in ANNI}
    gb = {g for g in re.findall(r'\d+', b or '') if g.lstrip('0') and g not in ANNI}
    return bool(ga) and (ga == gb or any(len(g) >= 3 for g in ga & gb))


def _parole(nome):
    return {w for w in re.findall(r'\w+', normalizza(nome)) if len(w) >= 4 and w not in ('SRL', 'SNC', 'SPA', 'SOCIETA')}


def _stesso_fornitore(a, b, basta_una=False):
    """Due nomi dello stesso fornitore scritti in modo diverso («Latteria Valle Verde» e «LATTERIA VALLE VERDE SRL»)."""
    na, nb = normalizza(a), normalizza(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    pa, pb = _parole(a), _parole(b)
    comuni = len(pa & pb)
    return comuni >= 1 if basta_una else comuni >= min(2, len(pa), len(pb)) > 0


def _stesso_importo(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.02, abs(b) * 0.01)


def _gemello(lid, fa):
    """Lo stesso documento già caricato. Tra due XML: stessa P.IVA, numero e data.
    Se uno dei due è letto da PDF o foto (P.IVA spesso assente, numero letto a occhio):
    stessa data e stesso tipo, e poi numero compatibile con fornitore o importo, oppure fornitore e importo."""
    ai = bool(fa.get('etichette'))
    for f in FatturaRete.query.filter_by(locale_id=lid, data=fa['data']).all():
        if fa['piva'] and f.piva == fa['piva'] and _numero(f.numero) == _numero(fa['numero']) and (f.tipo == 'DDT') == (fa['tipo'] == 'DDT'):
            return f
        if not ai and (f.etichette or {}).get('fonte') in (None, 'xml'):
            continue
        if (f.tipo == 'DDT') != (fa['tipo'] == 'DDT') or (f.segno or 0) != fa['segno']:
            continue    # una bolla non è il doppione della sua fattura, né una nota di credito
        stessa_piva = bool(f.piva and fa['piva'] and f.piva == fa['piva'])
        numero = _stesso_numero(f.numero, fa['numero'])
        importo = _stesso_importo(f.imponibile, fa['imponibile'])
        if (numero and (stessa_piva or importo or _stesso_fornitore(f.fornitore, fa['fornitore'], basta_una=True))
                or ((stessa_piva or _stesso_fornitore(f.fornitore, fa['fornitore'])) and importo)):
            return f
    return None


def _salva(lid, nome_file, fa, alias, esito, toccati):
    """Una fattura letta (da XML o da Claude) → nel database, se non c'è già."""
    et = fa.get('etichette')
    if et:
        # la P.IVA che manca su PDF e foto si ritrova dalle fatture dello stesso fornitore già caricate
        if not fa['piva']:
            for f in FatturaRete.query.filter(FatturaRete.locale_id == lid, FatturaRete.piva.isnot(None)).all():
                if _stesso_fornitore(f.fornitore, fa['fornitore']):
                    fa['piva'], fa['fornitore'] = f.piva, f.fornitore
                    break
        lettura_ai.chiavi_righe(fa)
    else:
        et = {'fonte': 'xml', 'documento': 'nota_credito' if fa['segno'] < 0 else 'fattura'}
    gia = _gemello(lid, fa)
    if gia and fa['tipo'] != 'DDT' and et['fonte'] == 'xml' and (gia.etichette or {}).get('fonte') in ('pdf', 'foto'):
        # arriva l'XML di una fattura già letta da PDF o foto: vale l'XML, che è esatto al centesimo
        for aid in {r.articolo_id for r in gia.righe if r.articolo_id}:
            toccati.add(aid)
        esito.setdefault('sostituite', []).append({'file': nome_file, 'numero': fa['numero'], 'fornitore': fa['fornitore'],
                                                   'prima': gia.file_nome})
        db.session.delete(gia)
        db.session.flush()
    elif gia:
        esito['doppie'].append({'file': nome_file, 'numero': fa['numero'], 'fornitore': fa['fornitore'],
                                'uguale_a': f'{gia.fornitore} n. {gia.numero} del {gia.data.strftime("%d/%m/%Y")}'})
        return
    fat = FatturaRete(locale_id=lid, fornitore=fa['fornitore'], piva=fa['piva'], numero=fa['numero'],
                      data=fa['data'], tipo=fa['tipo'], segno=fa['segno'], imponibile=fa['imponibile'],
                      file_nome=(nome_file or '')[:200], etichette=et)
    fat.righe = [RigaFattura(n=r['n'], codice=r['codice'], descrizione=r['descrizione'], chiave=r['chiave'],
                             quantita=r['quantita'], unita=r['unita'], totale=r['totale'],
                             ignorata=r.get('cibo') is False)
                 for r in fa['righe']]
    try:
        with db.session.begin_nested():   # un doppione non butta via le altre fatture dell'invio
            db.session.add(fat)
    except IntegrityError:
        esito['doppie'].append({'file': nome_file, 'numero': fa['numero'], 'fornitore': fa['fornitore']})
        return
    toccati |= _applica_alias(fat.righe, alias)
    esito['importate'].append(fat.to_dict())
    if fat.tipo != 'DDT':    # le bolle non hanno prezzi: i prodotti si collegano dalla fattura
        esito['da_collegare'] += sum(1 for r in fat.righe if r.quantita and not r.articolo_id and not r.ignorata)
    if et.get('controlla') or et.get('note'):
        esito['da_controllare'].append({'id': fat.id, 'file': nome_file, 'fornitore': fat.fornitore, 'numero': fat.numero,
                                        'controlla': et.get('controlla') or [], 'note': et.get('note')})


def _chiudi(toccati):
    for aid in toccati:
        a = db.session.get(ArticoloRete, aid)
        if a:
            aggiorna_prezzo(a)
    db.session.commit()


# le letture in corso: un solo processo gunicorn, basta la memoria
LETTURE, _LUCCHETTO = {}, threading.Lock()


def _leggi_in_sottofondo(app, lid, lettura, da_leggere):
    def salva(nome, docs, impronta):
        with app.app_context():
            alias = {a.chiave: a for a in AliasArticolo.query.filter_by(locale_id=lid).all()}
            toccati = set()
            with _LUCCHETTO:
                es = lettura['esito']
                if isinstance(docs, FatturaNonLeggibile):
                    es['errori'].append({'file': nome, 'errore': str(docs)})
                else:
                    if not docs:
                        es['errori'].append({'file': nome, 'errore': 'Nessun documento trovato nel file'})
                    fonte = 'pdf' if nome.lower().endswith('.pdf') else 'foto'
                    for i, d in enumerate(docs):
                        fa = lettura_ai.converti(d, fonte)
                        n = nome if len(docs) == 1 else f'{nome} ({i + 1} di {len(docs)})'
                        if isinstance(fa, FatturaNonLeggibile):
                            es['errori'].append({'file': n, 'errore': str(fa)})
                        else:
                            fa['etichette']['impronta'] = impronta
                            _salva(lid, n, fa, alias, es, toccati)
                _chiudi(toccati)
                lettura['fatti'] += 1

    def lavora():
        try:
            with ThreadPoolExecutor(LETTURE_INSIEME) as ex:
                futuri = {ex.submit(lettura_ai.leggi, n, d): n for n, d, _ in da_leggere}
                impronte = {n: h for n, _, h in da_leggere}
                for fut in as_completed(futuri):
                    try:
                        docs = fut.result()
                    except FatturaNonLeggibile as e:
                        docs = e
                    except Exception as e:     # un file che va storto non ferma gli altri
                        logger.exception('Lettura di %s', futuri[fut])
                        docs = FatturaNonLeggibile('Lettura non riuscita: ' + str(e)[:120])
                    try:
                        salva(futuri[fut], docs, impronte[futuri[fut]])
                    except Exception:
                        logger.exception('Salvataggio di %s', futuri[fut])
                        with _LUCCHETTO:
                            lettura['esito']['errori'].append({'file': futuri[fut], 'errore': 'Non salvato: riprova'})
                            lettura['fatti'] += 1
        finally:
            lettura['finita'] = True

    if os.environ.get('RETE_LETTURA_SUBITO'):     # i test: tutto nella stessa richiesta
        lavora()
    else:
        threading.Thread(target=lavora, daemon=True, name=f'lettura-{lettura["id"]}').start()


@rete_dati_bp.route('/api/rete/locali/<int:lid>/fatture', methods=['POST'])
@admin_required
def carica_fatture(lid):
    """Uno o più file nel campo `file`: XML, p7m, ZIP, PDF, foto, anche mischiati.
    Le fatture già caricate si saltano. Se ci sono PDF o foto, la risposta ha `lettura`
    e l'esito completo si segue su /letture/<id>."""
    LocaleRete.query.get_or_404(lid)
    if (request.content_length or 0) > MAX_UPLOAD:
        return jsonify({'error': 'Troppi dati in una volta: massimo 60 MB'}), 413
    files = request.files.getlist('file')[:MAX_FILE_CARICATI]
    if not files:
        return jsonify({'error': 'Nessun file'}), 400

    alias = {a.chiave: a for a in AliasArticolo.query.filter_by(locale_id=lid).all()}
    esito = {'importate': [], 'doppie': [], 'errori': [], 'da_collegare': 0, 'da_controllare': [], 'saltati': []}
    toccati, da_leggere = set(), []
    # un PDF o una foto già letti (stesso contenuto) non si rimandano a Claude: si pagherebbe due volte
    lette = {(f.etichette or {}).get('impronta'): f for f in FatturaRete.query.filter_by(locale_id=lid).all()}
    lette.pop(None, None)
    for f in files:
        for tipo, nome_file, x in _pezzi(f.filename, f.read()):
            if tipo == 'salta':
                esito['saltati'].append(nome_file)
            elif tipo == 'ai':
                h = hashlib.sha256(x).hexdigest()[:24]
                if h in lette:
                    g = lette[h]
                    esito['doppie'].append({'file': nome_file, 'numero': g.numero, 'fornitore': g.fornitore,
                                            'uguale_a': f'{g.fornitore} n. {g.numero} del {g.data.strftime("%d/%m/%Y")}'})
                elif h not in {i for _, _, i in da_leggere}:
                    da_leggere.append((nome_file, x, h))
            elif isinstance(x, FatturaNonLeggibile):
                esito['errori'].append({'file': nome_file, 'errore': str(x)})
            else:
                _salva(lid, nome_file, x, alias, esito, toccati)
    _chiudi(toccati)
    if not da_leggere:
        return jsonify(esito)

    with _LUCCHETTO:
        for k in [k for k, v in LETTURE.items() if time.time() - v['creata'] > 3600]:
            del LETTURE[k]
        lettura = {'id': secrets.token_urlsafe(8), 'locale': lid, 'totale': len(da_leggere), 'fatti': 0,
                   'finita': False, 'creata': time.time(), 'esito': esito}
        LETTURE[lettura['id']] = lettura
    _leggi_in_sottofondo(current_app._get_current_object(), lid, lettura, da_leggere)
    return jsonify({**esito, 'lettura': {'id': lettura['id'], 'totale': lettura['totale'], 'fatti': lettura['fatti'],
                                         'finita': lettura['finita']}})


@rete_dati_bp.route('/api/rete/locali/<int:lid>/letture/<lid2>', methods=['GET'])
@admin_required
def stato_lettura(lid, lid2):
    with _LUCCHETTO:
        l = LETTURE.get(lid2)
        if not l or l['locale'] != lid:
            return jsonify({'error': 'Lettura non trovata (il server è ripartito?): ricarica la pagina'}), 404
        return jsonify({'id': l['id'], 'totale': l['totale'], 'fatti': l['fatti'], 'finita': l['finita'], **l['esito']})


def _fattura_del_locale(lid, fid):
    f = db.session.get(FatturaRete, fid)
    return f if f and f.locale_id == lid else None


@rete_dati_bp.route('/api/rete/locali/<int:lid>/fatture/<int:fid>', methods=['PATCH'])
@admin_required
def correggi_fattura(lid, fid):
    """{visto: true} per confermare un documento letto da PDF o foto; fornitore, numero e data si correggono."""
    from datetime import date as _date
    f = _fattura_del_locale(lid, fid)
    if not f:
        return jsonify({'error': 'Documento non trovato'}), 404
    d = request.get_json(silent=True) or {}
    et = dict(f.etichette or {})
    if 'fornitore' in d:
        f.fornitore = _testo(d['fornitore'], 200) or f.fornitore
    if 'numero' in d:
        f.numero = _testo(d['numero'], 60) or f.numero
    if 'data' in d:
        try:
            f.data = _date.fromisoformat(str(d['data'])[:10])
        except ValueError:
            return jsonify({'error': 'Data non valida'}), 400
    if 'visto' in d:
        if d['visto']:
            from routes.rete import consulente_da_token
            c = consulente_da_token(request.headers.get('X-Admin-Token'))
            et['visto'] = {'chi': c.nome if c else 'SB', 'quando': datetime.utcnow().isoformat(timespec='minutes')}
        else:
            et.pop('visto', None)
    f.etichette = et
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'C\'è già un documento con questo numero e questa data'}), 409
    return jsonify({**f.to_dict(), 'dettaglio': [r.to_dict() for r in f.righe]})


@rete_dati_bp.route('/api/rete/locali/<int:lid>/fatture/<int:fid>/righe/<int:rid>', methods=['PATCH'])
@admin_required
def correggi_riga(lid, fid, rid):
    """Una cifra letta male su PDF o foto: {quantita, totale, descrizione, cibo}."""
    f = _fattura_del_locale(lid, fid)
    r = db.session.get(RigaFattura, rid)
    if not f or not r or r.fattura_id != f.id:
        return jsonify({'error': 'Riga non trovata'}), 404
    d = request.get_json(silent=True) or {}
    for campo in ('quantita', 'totale'):
        if campo in d:
            v = None if d[campo] in (None, '') else _num(d[campo], minimo=0)
            if d[campo] not in (None, '') and v is None:
                return jsonify({'error': f'Valore non valido: {campo}'}), 400
            setattr(r, campo, v)
    if 'descrizione' in d:
        r.descrizione = _testo(d['descrizione'], 500) or r.descrizione
    if 'cibo' in d:
        r.ignorata = not d['cibo']
    toccati = {r.articolo_id} if r.articolo_id else set()
    al = AliasArticolo.query.filter_by(locale_id=lid, chiave=r.chiave).first()
    if al and r.quantita and not r.ignorata:
        toccati |= _applica_alias([r], {r.chiave: al})
    elif r.articolo_id and (not r.quantita or r.ignorata):
        r.articolo_id, r.quantita_articolo = None, None
    if f.tipo != 'DDT':
        f.imponibile = round(sum((x.totale or 0) for x in f.righe), 2)
    db.session.flush()
    for aid in toccati:
        a = db.session.get(ArticoloRete, aid)
        if a:
            aggiorna_prezzo(a)
    db.session.commit()
    return jsonify(r.to_dict())


@rete_dati_bp.route('/api/rete/locali/<int:lid>/fatture', methods=['GET'])
@admin_required
def fatture(lid):
    LocaleRete.query.get_or_404(lid)
    q = FatturaRete.query.filter_by(locale_id=lid).order_by(FatturaRete.data.desc(), FatturaRete.id.desc())
    return jsonify([f.to_dict() for f in q.all()])


@rete_dati_bp.route('/api/rete/locali/<int:lid>/fatture/<int:fid>', methods=['GET'])
@admin_required
def fattura(lid, fid):
    f = db.session.get(FatturaRete, fid)
    if not f or f.locale_id != lid:
        return jsonify({'error': 'Fattura non trovata'}), 404
    d = f.to_dict()
    d['dettaglio'] = [r.to_dict() for r in f.righe]
    return jsonify(d)


@rete_dati_bp.route('/api/rete/locali/<int:lid>/fatture/<int:fid>', methods=['DELETE'])
@admin_required
def elimina_fattura(lid, fid):
    f = db.session.get(FatturaRete, fid)
    if not f or f.locale_id != lid:
        return jsonify({'error': 'Fattura non trovata'}), 404
    articoli_toccati = {r.articolo_id for r in f.righe if r.articolo_id}
    db.session.delete(f)
    db.session.flush()
    for aid in articoli_toccati:
        a = db.session.get(ArticoloRete, aid)
        if a:
            aggiorna_prezzo(a)
    db.session.commit()
    return jsonify({'ok': True})


# ── collegare le righe agli articoli ──

@rete_dati_bp.route('/api/rete/locali/<int:lid>/da-collegare', methods=['GET'])
@admin_required
def da_collegare(lid):
    """Le righe merce non ancora collegate, raggruppate per prodotto (chiave),
    le più pesanti in euro per prime: coprono quasi tutto il food cost."""
    LocaleRete.query.get_or_404(lid)
    righe = (RigaFattura.query.join(FatturaRete)
             .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.is_(None), RigaFattura.quantita.isnot(None),
                     RigaFattura.ignorata.isnot(True), db.func.coalesce(FatturaRete.tipo, '') != 'DDT')
             .order_by(FatturaRete.data.desc()).all())
    gruppi = OrderedDict()
    for r in righe:
        g = gruppi.setdefault(r.chiave, {'chiave': r.chiave, 'descrizione': r.descrizione, 'codice': r.codice,
                                         'fornitore': r.fattura.fornitore, 'unita': r.unita,
                                         'righe': 0, 'quantita': 0.0, 'totale': 0.0,
                                         'fattore_kg': suggerisci_fattore(r.descrizione, r.unita, 'kg'),
                                         'fattore_l': suggerisci_fattore(r.descrizione, r.unita, 'l'),
                                         'fattore_pz': suggerisci_fattore(r.descrizione, r.unita, 'pz')})
        g['righe'] += 1
        g['quantita'] += r.quantita or 0
        g['totale'] += (r.totale or 0) * r.fattura.segno
    out = sorted(gruppi.values(), key=lambda g: -abs(g['totale']))
    for g in out:
        g['quantita'], g['totale'] = round(g['quantita'], 3), round(g['totale'], 2)
    return jsonify(out)


@rete_dati_bp.route('/api/rete/locali/<int:lid>/collega', methods=['POST'])
@admin_required
def collega(lid):
    """{chiave, fattore, articolo_id | articolo:{nome, unita, categoria}}
    oppure {chiave, ignora: true} per le righe che non sono cibo (detersivi, imballi)."""
    LocaleRete.query.get_or_404(lid)
    d = request.get_json(silent=True) or {}
    chiave = (d.get('chiave') or '')[:320]
    if not chiave or not RigaFattura.query.join(FatturaRete).filter(
            FatturaRete.locale_id == lid, RigaFattura.chiave == chiave).first():
        return jsonify({'error': 'Prodotto non trovato nelle fatture di questo locale'}), 404

    if d.get('ignora'):
        # le righe non-cibo restano senza articolo e non tornano nella lista
        n = (RigaFattura.query.filter(RigaFattura.chiave == chiave,
                                      RigaFattura.fattura_id.in_(db.session.query(FatturaRete.id).filter_by(locale_id=lid)))
             .update({'ignorata': True}, synchronize_session=False))
        db.session.commit()
        return jsonify({'ok': True, 'righe': n})

    fattore = _num(d.get('fattore'), minimo=0.000001)
    if not fattore:
        return jsonify({'error': 'Serve il fattore: quante unità dell\'articolo ci sono in una unità della riga'}), 400
    if d.get('articolo_id'):
        art = _articolo_del_locale(lid, int(d['articolo_id']))
        if not art:
            return jsonify({'error': 'Articolo non trovato'}), 404
    else:
        nuovo = d.get('articolo') or {}
        nome, unita = _testo(nuovo.get('nome'), 160), (nuovo.get('unita') or 'kg').lower()
        if not nome or unita not in UNITA:
            return jsonify({'error': 'Per un articolo nuovo servono nome e unità (kg, l, pz)'}), 400
        art = ArticoloRete(locale_id=lid, nome=nome, unita=unita, categoria=_testo(nuovo.get('categoria'), 60))
        db.session.add(art)
        db.session.flush()

    al = AliasArticolo.query.filter_by(locale_id=lid, chiave=chiave).first()
    if al:
        vecchio = al.articolo_id
        al.articolo_id, al.fattore = art.id, fattore
    else:
        vecchio = None
        al = AliasArticolo(locale_id=lid, chiave=chiave, articolo_id=art.id, fattore=fattore)
        db.session.add(al)
    righe = (RigaFattura.query.join(FatturaRete)
             .filter(FatturaRete.locale_id == lid, RigaFattura.chiave == chiave).all())
    _applica_alias(righe, {chiave: al})
    db.session.flush()
    aggiorna_prezzo(art)
    if vecchio and vecchio != art.id:
        v = db.session.get(ArticoloRete, vecchio)
        if v:
            aggiorna_prezzo(v)
    db.session.commit()
    # le ricette proposte dall'analisi delle vendite passano all'articolo col prezzo vero appena collegato
    if RicettaRete.query.filter_by(locale_id=lid, automatica=True).first():
        from services.analisi_vendite import analizza
        try:
            analizza(db.session.get(LocaleRete, lid), ai=False)
        except Exception:
            logger.exception('Analisi delle vendite dopo il collegamento, locale %s', lid)
            db.session.rollback()
    return jsonify({'articolo': art.to_dict(), 'righe': len(righe)})
