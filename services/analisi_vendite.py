"""L'analisi delle vendite: ogni volta che entra la cassa, il locale si capisce da solo.

  1. le voci doppie si uniscono: «Caffe» e «Caffè» (già alla lettura, services.cassa.normalizza_voce),
     «Caffe» e «Caffè espresso» (stesso prodotto del catalogo), «Moretti» e «MORETII» (nomi quasi
     uguali allo stesso prezzo) → UnioneVoce;
  2. ogni prodotto va nella sua categoria (caffetteria, cucina, birre…) e prende la ricetta standard
     del catalogo (services/catalogo.py), con gli ingredienti collegati agli articoli del locale:
     quelli delle fatture col prezzo vero, gli altri creati col prezzo stimato (ArticoloRete.prezzo_stima);
  3. ogni voce si abbina alla sua ricetta (AliasVendita automatico), coperto e servizio fuori dal food cost,
     le voci generiche («Varie», «A scelta») restano da chiarire col locale;
  4. quello che il catalogo non conosce si chiede a Claude, se la chiave c'è e ha credito; se no resta da guardare.

Quello che ha deciso il consulente non si tocca: un abbinamento fatto a mano, una ricetta scritta
o corretta da lui (RicettaRete.automatica False) restano com'erano.
"""
import difflib
import logging
import os
import re
from collections import defaultdict
from datetime import datetime

from models import (db, AliasArticolo, AliasVendita, ArticoloRete, FatturaRete, MovimentoRete, RicettaRete, RigaFattura,
                    RigaInventario, RigaRicetta, UnioneVoce)
from services import catalogo as C
from services import vendite as V
from services.cassa import normalizza_voce

logger = logging.getLogger(__name__)

SOMIGLIANZA = 0.86        # quanto due nomi devono assomigliarsi per essere lo stesso prodotto
PREZZO_SIMILE = (0.6, 1.67)   # e i prezzi medi non devono essere troppo diversi
NOTA_AUTO = 'Creata dal prodotto venduto con le grammature standard: quando si pesa il piatto, correggerla.'
NOTA_FORMULA = 'Formula: ricetta stimata su quello che di solito c\'è dentro. Da controllare con il locale.'


def _voci_grezze(lid):
    """{voce: {nome, quantita, incasso, prezzo}} sommando giorni e report, senza unioni."""
    out = {}
    for v in V.vendite(lid, unite=False):
        x = out.setdefault(v.voce, {'nome': v.voce_originale or v.voce, 'quantita': 0.0, 'incasso': 0.0, '_q': -1, 'varianti': set()})
        x['varianti'] |= v.nomi_cassa
        x['quantita'] += v.quantita or 0
        x['incasso'] += v.incasso or 0
        if (v.quantita or 0) > x['_q']:             # il nome scritto più spesso
            x['nome'], x['_q'] = v.voce_originale or v.voce, v.quantita or 0
    for x in out.values():
        x['prezzo'] = x['incasso'] / x['quantita'] if x['quantita'] > 0 else None
    return out


def _radice(voce):
    """Il nome per confrontare: senza spazi, ogni parola senza la vocale finale (cornetto/cornetti)."""
    return ''.join(re.sub(r'[aeiou]+$', '', w) if len(w) > 4 else w for w in voce.lower().split())


# parole che fanno di due nomi simili due prodotti diversi: Corona e Corona zero, Cornetto e Cornetto grande
DISTINTIVI = re.compile(r'^(zero|grand|piccol|mignon|dek|deka|deca|decaffeinat|soia|senza|lattosio|doppi|fredd|vegan|light|analcol'
                        r'|ross|bianc|rosat|66|20|40|50|75|1l|litro|frizzant|naturale|nutella|pistacch|crema|salat|integral|fragol|bomb)')


def _stesso_nome(a, b):
    """Due voci sono lo stesso nome scritto male: radici molto simili, o una contiene l'altra («MORETTI», «BIRRA MORETTI»),
    purché non le distingua una parola come «zero», «grande», «dek»."""
    if any(DISTINTIVI.match(w) for w in set(a.lower().split()) ^ set(b.lower().split())):
        return False
    ra, rb = _radice(a), _radice(b)
    if min(len(ra), len(rb)) >= 5 and (ra in rb or rb in ra):
        return True
    return difflib.SequenceMatcher(None, ra, rb).ratio() >= SOMIGLIANZA


def _bel_nome(n):
    """«CORNETTI CLASSICI» → «Cornetti classici»: la cassa scrive spesso in maiuscolo."""
    return n[:1].upper() + n[1:].lower() if n.isupper() else n


def _prezzi_simili(a, b):
    if not a or not b:
        return True
    return PREZZO_SIMILE[0] <= a / b <= PREZZO_SIMILE[1]


def _articolo(lid, iid, articoli):
    """L'articolo del locale per un ingrediente del catalogo → (articolo, fattore), dove
    quantità nell'unità dell'articolo = quantità della ricetta × fattore.
    Prima un articolo vero delle fatture che combacia, poi uno già creato dal catalogo, se no lo crea."""
    ing = C.ingrediente(iid)

    def fattore(a):
        if a.unita == ing['unita'] or {a.unita, ing['unita']} == {'kg', 'l'}:
            return 1.0
        conv = ing['conv']
        if conv and ing['unita'] == 'pz' and conv[0] in (a.unita, 'kg' if a.unita == 'l' else 'l'):
            return conv[1]
        if conv and a.unita == 'pz' and conv[0] == 'pz':
            return 1 / conv[1]
        return None

    # prima gli articoli delle fatture col prezzo vero, poi quello creato dal catalogo, poi gli altri che combaciano
    candidati = sorted((a for a in articoli if a.nome == ing['nome'] or ing['parole'].search(normalizza_voce(a.nome).lower())),
                       key=lambda a: (a.prezzo is None, a.nome != ing['nome']))
    for a in candidati:
        f = fattore(a)
        if f is not None:
            if a.prezzo is None and a.prezzo_stima is None:
                a.prezzo_stima = round(ing['prezzo'] / f, 4)
            return a, f
    a = ArticoloRete(locale_id=lid, nome=ing['nome'], unita=ing['unita'], categoria='Dal catalogo', prezzo_stima=ing['prezzo'])
    db.session.add(a)
    articoli.append(a)
    return a, 1.0


def _ricetta(lid, p, prezzo, ricette, articoli):
    """La ricetta del locale per un prodotto del catalogo: quella del consulente se c'è, se no la proposta."""
    r = ricette.get(p['nome'].lower())
    if r and not r.automatica:
        return r                                             # scritta o corretta dal consulente: non si tocca
    if not r:
        r = RicettaRete(locale_id=lid, nome=p['nome'], automatica=True)
        db.session.add(r)
        ricette[p['nome'].lower()] = r
    r.categoria, r.resa = p['categoria'], 1.0
    r.prezzo = round(prezzo, 2) if prezzo else r.prezzo
    r.nota = NOTA_FORMULA if p.get('formula') else NOTA_AUTO
    r.righe.clear()
    somma = defaultdict(float)
    for iid, q in p['ricetta']:
        a, f = _articolo(lid, iid, articoli)
        db.session.flush()
        somma[a.id] += q * f
    for aid, q in somma.items():
        r.righe.append(RigaRicetta(articolo_id=aid, quantita=round(q, 5)))
    return r


def analizza(locale, ai=True):
    """Analizza tutte le vendite del locale e aggiorna unioni, ricette e abbinamenti. → il riassunto."""
    lid = locale.id
    voci = _voci_grezze(lid)
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    manuali = {k for k, a in alias.items() if not a.automatico}
    tot = sum(x['incasso'] for x in voci.values()) or 1

    # 1. il catalogo riconosce i prodotti. Un prodotto vero (Caffè, Cappuccino) unisce tutte le sue voci;
    #    una famiglia (birre, succhi, vini, voci generiche) unisce solo i nomi uguali scritti male
    prodotto = {k: p for k, x in voci.items() if (p := C.riconosci(k, x['prezzo']))}
    gruppo, per_prodotto = {}, defaultdict(list)
    for k, p in prodotto.items():
        per_prodotto[p['id']].append(k)
    for ks in per_prodotto.values():
        p = prodotto[ks[0]]
        if not p['famiglia']:
            for k in ks:
                gruppo[k] = (normalizza_voce(p['nome']), p['nome'], 'catalogo')
            continue
        teste = defaultdict(list)
        for k in sorted(ks, key=lambda k: -voci[k]['incasso']):
            # basta assomigliare a un nome qualsiasi del gruppo («Heiniken» a «Heineken», non solo a «Heineken da 33»)
            t = next((t for t, ms in teste.items() if _prezzi_simili(voci[k]['prezzo'], voci[t]['prezzo'])
                      and any(_stesso_nome(k, m) for m in ms)), None)
            teste[t or k].append(k)
        # secondo giro: chi è rimasto da solo si riprova contro i gruppi ormai completi (l'ordine non deve contare)
        for t in [t for t, ms in teste.items() if len(ms) == 1]:
            altro = next((o for o, ms in teste.items() if o != t and len(ms) and _prezzi_simili(voci[t]['prezzo'], voci[o]['prezzo'])
                          and any(_stesso_nome(t, m) for m in ms)), None)
            if altro:
                teste[altro] += teste.pop(t)
        for t, membri_t in teste.items():
            nome = _bel_nome(min((voci[k]['nome'] for k in membri_t),            # il nome più vicino a tutti gli altri:
                                 key=lambda n: sum(1 - difflib.SequenceMatcher(None, n.lower(), voci[o]['nome'].lower()).ratio()
                                                   for o in membri_t)))      # «Moretti», non «MORETII»
            for k in membri_t:
                gruppo[k] = (t, nome, 'catalogo')

    # 2. i nomi quasi uguali allo stesso prezzo vanno con il più venduto («MORETII» con «Moretti»)
    for k in sorted((k for k in voci if k not in prodotto), key=lambda k: -voci[k]['incasso']):
        rk, migliore = _radice(k), None
        for o in voci:
            if o == k or not _prezzi_simili(voci[k]['prezzo'], voci[o]['prezzo']):
                continue
            if difflib.SequenceMatcher(None, rk, _radice(o)).ratio() >= SOMIGLIANZA and \
                    (migliore is None or voci[o]['incasso'] > voci[migliore]['incasso']) and \
                    not (prodotto.get(o) or {}).get('famiglia'):        # una voce sconosciuta non entra in una famiglia
                migliore = o
        if migliore and voci[migliore]['incasso'] >= voci[k]['incasso']:
            gruppo[k] = gruppo.get(migliore) or (migliore, voci[migliore]['nome'], 'somiglianza')
            if migliore in prodotto:
                prodotto[k] = prodotto[migliore]

    # 3. quello che resta lo guarda Claude (se c'è credito); il riassunto dice com'è andata
    esito_ai = None
    sconosciute = [k for k in voci if k not in gruppo and voci[k]['incasso'] / tot >= 0.0005]
    if ai and sconosciute:
        esito_ai = _chiedi_ai(voci, sconosciute, gruppo)
        for k, (p, canon) in esito_ai.pop('risposte', {}).items():
            prodotto[k] = p
            gruppo[k] = canon

    # una voce che il consulente ha abbinato a mano resta com'è, non entra in un altro prodotto
    for k in manuali:
        if k in gruppo and gruppo[k][0] != k:
            del gruppo[k]
            prodotto.pop(k, None)

    # 4. le unioni: si riscrivono tutte quelle automatiche
    UnioneVoce.query.filter(UnioneVoce.locale_id == lid, UnioneVoce.perche != 'manuale').delete()
    for k, (canon, nome, perche) in gruppo.items():
        if canon != k or nome != voci[k]['nome']:            # anche solo per il nome pulito («CAFFE» → «Caffè»)
            db.session.add(UnioneVoce(locale_id=lid, voce=k, canonica=canon, nome=nome, perche=perche))

    # 5. per ogni prodotto: categoria, ricetta, abbinamento
    membri = defaultdict(list)
    for k in voci:
        membri[gruppo[k][0] if k in gruppo else k].append(k)
    ricette = {r.nome.lower(): r for r in RicettaRete.query.filter_by(locale_id=lid).all()}
    articoli = ArticoloRete.query.filter_by(locale_id=lid).all()
    creati_prima = {r.nome.lower() for r in ricette.values()}
    per_categoria, chiarire, non_riconosciute = defaultdict(float), [], []
    for canon, ks in membri.items():
        inc = sum(voci[k]['incasso'] for k in ks)
        q = sum(voci[k]['quantita'] for k in ks)
        p = next((prodotto[k] for k in ks if k in prodotto), None)
        a = alias.get(canon)
        if a and not a.automatico:                         # deciso dal consulente
            per_categoria[a.categoria or ('Fuori dal food cost' if a.ignorata else 'Abbinate a mano')] += inc
            continue
        if not p:
            non_riconosciute.append({'voce': voci[ks[0]]['nome'], 'incasso': round(inc, 2)})
            per_categoria['Non riconosciute'] += inc
            continue
        per_categoria[p['categoria']] += inc
        if not a:
            a = AliasVendita(locale_id=lid, voce=canon)
            db.session.add(a)
            alias[canon] = a
        a.automatico, a.categoria = True, p['categoria']
        if p.get('fuori'):
            a.ricetta_id, a.ignorata = None, True
        elif p.get('chiarire') or not p['ricetta']:
            a.ricetta_id, a.ignorata = None, False
            chiarire.append({'voce': ', '.join(sorted({voci[k]['nome'] for k in ks}))[:120], 'incasso': round(inc, 2)})
        else:
            r = _ricetta(lid, p, inc / q if q else None, ricette, articoli)
            db.session.flush()
            a.ricetta_id, a.ignorata = r.id, False
    db.session.commit()

    unite = []
    for canon, ks in membri.items():
        nomi_cassa = set().union(*(voci[k]['varianti'] for k in ks))
        if len(nomi_cassa) > 1:
            g = next((gruppo[k] for k in ks if k in gruppo), (canon, voci[ks[0]]['nome'], 'scrittura'))
            unite.append({'nome': g[1], 'voci': sorted(nomi_cassa), 'perche': g[2] if len(ks) > 1 else 'scrittura'})
    coperto = sum(inc for c, inc in per_categoria.items() if c not in ('Da chiarire', 'Non riconosciute', 'Coperto e servizio', 'Rivendita'))
    riassunto = {
        'quando': datetime.utcnow().isoformat(timespec='seconds'),
        'voci_cassa': len(voci), 'prodotti': len(membri),
        'unite': sorted(unite, key=lambda u: -len(u['voci'])),
        'ricette_nuove': len({r.lower() for r in ricette} - creati_prima),
        'ricette_automatiche': sum(1 for r in ricette.values() if r.automatica),
        'categorie': sorted(({'nome': c, 'incasso': round(v, 2), 'quota': round(v / tot * 100, 1)} for c, v in per_categoria.items()),
                            key=lambda x: -x['incasso']),
        'quota_con_ricetta': round(coperto / tot * 100, 1),
        'da_chiarire': sorted(chiarire, key=lambda x: -x['incasso'])[:20],
        'non_riconosciute': sorted(non_riconosciute, key=lambda x: -x['incasso'])[:30],
        'ai': esito_ai,
    }
    imp = dict(locale.impostazioni or {})
    imp['analisi_vendite'] = riassunto
    locale.impostazioni = imp
    db.session.commit()
    riassunto['articoli_tolti'] = pulisci_articoli(lid)          # gli ingredienti rimasti senza ricetta
    return riassunto


# ── Claude per le voci che il catalogo non conosce ──

STRUMENTO_AI = {
    'name': 'classifica',
    'description': 'Classifica le voci di cassa di un locale italiano e proponi la ricetta di una porzione.',
    'input_schema': {'type': 'object', 'properties': {'voci': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'voce': {'type': 'string', 'description': 'la voce esattamente come data'},
        'uguale_a': {'type': ['string', 'null'], 'description': 'il prodotto già noto che è la stessa cosa, dalla lista data; null se nessuno'},
        'nome': {'type': 'string', 'description': 'il nome pulito del prodotto'},
        'categoria': {'type': 'string', 'enum': [C.CAFFETTERIA, C.COLAZIONE, C.CUCINA, C.PIZZERIA, C.FORMULE, C.BEVANDE, C.BIRRE,
                                                 C.VINI, C.COCKTAIL, C.SERVIZIO, C.RIVENDITA, C.CHIARIRE]},
        'ingredienti': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'ingrediente': {'type': 'string', 'enum': sorted(C.ING)},
            'quantita': {'type': 'number', 'description': 'per una porzione, nell\'unità dell\'ingrediente (kg, l o pz)'}},
            'required': ['ingrediente', 'quantita']}},
    }, 'required': ['voce', 'uguale_a', 'nome', 'categoria', 'ingredienti']}}}, 'required': ['voci']},
}


def _chiedi_ai(voci, sconosciute, gruppo):
    """→ {'stato', 'voci', 'risposte': {voce: (prodotto, gruppo)}}. Mai un'eccezione: se non va, lo dice."""
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return {'stato': 'spenta', 'motivo': 'manca la chiave Anthropic', 'voci': len(sconosciute)}
    noti = sorted({g[1] for g in gruppo.values()})
    elenco = '\n'.join(f'- {voci[k]["nome"]} · {voci[k]["quantita"]:.0f} venduti · {voci[k]["prezzo"] or 0:.2f} € l\'uno' for k in sconosciute[:80])
    ingr = ', '.join(f'{i} ({v[0]}, {v[1]})' for i, v in C.ING.items())
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'], timeout=90, max_retries=1)
        r = client.messages.create(
            model=os.environ.get('RETE_MODELLO_LETTURA', 'claude-sonnet-5'), max_tokens=8000,
            tools=[STRUMENTO_AI], tool_choice={'type': 'tool', 'name': 'classifica'},
            system=('Sei un consulente di food cost per bar e ristoranti italiani. Per ogni voce della cassa: se è lo stesso '
                    'prodotto di uno già noto (anche scritto male) mettilo in `uguale_a`; se no dagli categoria e la ricetta '
                    'di una porzione con le grammature standard, usando solo gli ingredienti dati. Voci generiche come '
                    '«varie» o «menu» vanno in «Da chiarire» senza ingredienti. Non inventare: se non capisci, «Da chiarire».'),
            messages=[{'role': 'user', 'content': f'Prodotti già noti: {", ".join(noti)}\n\nIngredienti (unità, nome): {ingr}\n\n'
                                                  f'Voci da classificare:\n{elenco}'}])
        dati = next(b.input for b in r.content if b.type == 'tool_use')
    except Exception as e:                                # credito finito, rete, risposta strana: si va avanti senza
        logger.warning('Analisi vendite con Claude non riuscita: %s', e)
        motivo = 'credito Anthropic esaurito' if 'credit balance' in str(e) else str(e)[:160]
        return {'stato': 'errore', 'motivo': motivo, 'voci': len(sconosciute)}

    per_nome = {normalizza_voce(voci[k]['nome']): k for k in sconosciute}
    noti_chiave = {normalizza_voce(g[1]): g for g in gruppo.values()}
    risposte = {}
    for x in (dati or {}).get('voci', []):
        k = per_nome.get(normalizza_voce(x.get('voce')))
        if not k:
            continue
        uguale = noti_chiave.get(normalizza_voce(x.get('uguale_a') or ''))
        ricetta = [(i['ingrediente'], float(i['quantita'])) for i in x.get('ingredienti') or []
                   if i.get('ingrediente') in C.ING and 0 < float(i.get('quantita') or 0) < 5]
        cat = x.get('categoria') if x.get('categoria') in STRUMENTO_AI['input_schema']['properties']['voci']['items']['properties']['categoria']['enum'] else C.CHIARIRE
        p = {'id': 'ai', 'nome': (x.get('nome') or voci[k]['nome'])[:150], 'categoria': cat, 'ricetta': ricetta,
             'fuori': cat in (C.SERVIZIO, C.RIVENDITA), 'chiarire': cat == C.CHIARIRE or not ricetta}
        risposte[k] = (p, uguale if uguale else (normalizza_voce(p['nome']), p['nome'], 'ai'))
    return {'stato': 'fatta', 'voci': len(sconosciute), 'riconosciute': len(risposte), 'risposte': risposte}



# ── gli articoli seguono il ricettario ──

def uso_articoli(lid):
    """{articolo_id: {in_ricette, da_fattura}}: in quante ricette entra e se arriva da una fattura collegata."""
    out = {}
    for (aid, n) in (db.session.query(RigaRicetta.articolo_id, db.func.count(db.distinct(RigaRicetta.ricetta_id)))
                     .join(RicettaRete).filter(RicettaRete.locale_id == lid).group_by(RigaRicetta.articolo_id).all()):
        out.setdefault(aid, {'in_ricette': 0, 'da_fattura': False})['in_ricette'] = n
    for (aid,) in (db.session.query(RigaFattura.articolo_id).join(FatturaRete)
                   .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.isnot(None)).distinct().all()):
        out.setdefault(aid, {'in_ricette': 0, 'da_fattura': False})['da_fattura'] = True
    return out


def pulisci_articoli(lid):
    """Toglie gli ingredienti che non servono più: in nessuna ricetta, mai arrivati da una fattura, mai contati
    in un inventario, senza scarti o carichi. Chi ha una storia vera resta (esce solo dalla lista da contare).
    → quanti ne ha tolti. Si chiama dopo ogni ricetta tolta o cambiata e dopo l'analisi delle vendite."""
    uso = uso_articoli(lid)
    storia = ({a for (a,) in db.session.query(RigaInventario.articolo_id).distinct()}
              | {a for (a,) in db.session.query(MovimentoRete.articolo_id).filter(MovimentoRete.locale_id == lid).distinct()}
              | {a for (a,) in db.session.query(AliasArticolo.articolo_id).filter(AliasArticolo.locale_id == lid).distinct()})
    via = [a for a in ArticoloRete.query.filter_by(locale_id=lid).all()
           if not uso.get(a.id, {}).get('in_ricette') and not uso.get(a.id, {}).get('da_fattura') and a.id not in storia]
    for a in via:
        db.session.delete(a)
    if via:
        db.session.commit()
    return len(via)


GIORNI_SCORTA = 3          # di solito tra un ordine e la consegna passano 2-3 giorni: il consulente lo cambia per locale


def consumi(lid):
    """(consumo al giorno di ogni articolo, giorni di vendite su cui è calcolato, dal, al):
    piatti venduti × grammature delle ricette, diviso i giorni coperti dalla cassa (giorni e report di periodo)."""
    from services import vendite as V
    from models import ReportCassa
    righe = V.vendite(lid)
    giorni = len({v.giorno for v in righe if v.giorno})
    giorni += sum((r.al - r.dal).days + 1 for r in ReportCassa.query.filter_by(locale_id=lid).all())
    if not righe or not giorni:
        return {}, 0, None, None
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    ricette = {r.id: r for r in RicettaRete.query.filter_by(locale_id=lid).all()}
    uso = defaultdict(float)
    for v in righe:
        a = alias.get(v.voce)
        r = ricette.get(a.ricetta_id) if a and a.ricetta_id and not a.ignorata else None
        if not r or not v.quantita:
            continue
        for rr in r.righe:
            uso[rr.articolo_id] += v.quantita * rr.quantita / (r.resa or 1)
    dal = min(v.dal for v in righe if v.dal)
    al = max(v.al for v in righe if v.al)
    return {aid: max(q, 0) / giorni for aid, q in uso.items()}, giorni, dal, al
