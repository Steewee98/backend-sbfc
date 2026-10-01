"""Il motore della diagnosi del food cost (Rete SB, fase 1).

Tra due inventari, articolo per articolo:

    consumo reale   = giacenza iniziale + acquisti + carichi − giacenza finale
    consumo teorico = Σ piatti venduti × grammatura della ricetta

e lo scostamento in euro si divide in tre pezzi che si spiegano al titolare
riga per riga (controllo di gestione classico, niente scatole nere):

    prezzo            = consumo teorico × (prezzo pagato nel periodo − prezzo di prima)
    scarti registrati = scarti × prezzo del periodo
    consumo oltre     = (reale − teorico − scarti) × prezzo del periodo
                        ricetta

così che  costo reale = costo teorico ai prezzi di prima + prezzo + scarti + consumo.
Tutto si dà anche in punti di food cost sui ricavi netti (IVA tolta).
"""
from collections import defaultdict
from datetime import timedelta

from models import (db, ArticoloRete, FatturaRete, RigaFattura, RicettaRete, AliasVendita,
                    VenditaRete, MovimentoRete, InventarioRete)

SOGLIA_PUNTI = 0.3      # sotto questa differenza non si parla di perdita


def _prezzo_al(articolo_id, giorno):
    """Prezzo per unità dell'ultima fattura fino a quel giorno compreso."""
    r = (RigaFattura.query.join(FatturaRete)
         .filter(RigaFattura.articolo_id == articolo_id, RigaFattura.quantita_articolo > 0,
                 RigaFattura.totale > 0, FatturaRete.segno == 1, FatturaRete.data <= giorno)
         .order_by(FatturaRete.data.desc(), RigaFattura.id.desc()).first())
    return r.totale / r.quantita_articolo if r else None


def costo_ricetta(ricetta, stime=False):
    """Costo di una porzione ai prezzi di oggi; None se manca il prezzo di un ingrediente.
    Con `stime` vale anche il prezzo stimato del catalogo dove la fattura non c'è ancora."""
    c = costo_ricetta_dettaglio(ricetta, stime)
    return c['costo'], c['mancano']


def costo_ricetta_dettaglio(ricetta, stime=True):
    """{costo, mancano, stimati}: `stimati` = ingredienti pagati col prezzo stimato, da dire sempre."""
    tot, di_stima, mancano, stimati = 0.0, 0.0, [], []
    for rr in ricetta.righe:
        a = db.session.get(ArticoloRete, rr.articolo_id)
        p = a.prezzo if a else None
        if p is None and stime and a and a.prezzo_stima is not None:
            p = a.prezzo_stima
            stimati.append(a.nome)
            di_stima += rr.quantita * p
        if p is None:
            mancano.append(a.nome if a else '?')
            continue
        tot += rr.quantita * p
    resa = ricetta.resa or 1
    ok = not mancano and ricetta.righe
    return {'costo': round(tot / resa, 4) if ok else None, 'di_stima': round(di_stima / resa, 4) if ok else None,
            'mancano': mancano, 'stimati': stimati}


def food_cost_ricette(lid, righe, iva):
    """Il food cost delle ricette sulle vendite, senza inventari: Σ venduti × costo della porzione / incasso senza IVA.
    `righe` = vendite già unite (services.vendite). Prezzi veri delle fatture dove ci sono, stimati dove no:
    quanto pesa la stima si dice sempre (`quota_stima`). None se nessun piatto venduto ha una ricetta col costo."""
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    ricette = {r.id: r for r in RicettaRete.query.filter_by(locale_id=lid).all()}
    cache, piatti = {}, {}
    costo = stima = ricavi = escluso = 0.0
    for v in righe:
        a = alias.get(v.voce)
        r = ricette.get(a.ricetta_id) if a and a.ricetta_id and not a.ignorata else None
        if not r:
            continue
        if r.id not in cache:
            cache[r.id] = costo_ricetta_dettaglio(r, stime=True)
        c = cache[r.id]
        incasso = v.incasso if v.incasso is not None else v.quantita * (r.prezzo or 0)
        netto = v.netto if v.netto is not None else incasso / (1 + iva / 100)
        if c['costo'] is None or netto <= 0:
            escluso += incasso
            continue
        costo += v.quantita * c['costo']
        stima += v.quantita * c['di_stima']
        ricavi += netto
        x = piatti.setdefault(r.nome, {'nome': r.nome, 'venduti': 0.0, 'netto': 0.0, 'costo': 0.0, 'porzione': c['costo'],
                                       'stimati': c['stimati'], 'automatica': bool(r.automatica)})
        x['venduti'] += v.quantita
        x['netto'] += netto
        x['costo'] += v.quantita * c['costo']
    if not ricavi:
        return None
    for x in piatti.values():
        x['food_cost'] = round(x['costo'] / x['netto'] * 100, 1) if x['netto'] else None
    return {'valore': round(costo / ricavi * 100, 1), 'costo': round(costo, 2), 'ricavi': round(ricavi, 2),
            'quota_stima': round(stima / costo * 100) if costo else 0, 'escluso': round(escluso, 2),
            'piatti': sorted(piatti.values(), key=lambda x: -x['costo'])}


def diagnosi(locale, inv_a, inv_b):
    lid, g0, g1 = locale.id, inv_a.giorno, inv_b.giorno
    imp = locale.impostazioni or {}
    iva = float(imp.get('iva', 10))
    obiettivo = float(imp.get('obiettivo', 30))
    articoli = {a.id: a for a in ArticoloRete.query.filter_by(locale_id=lid).all()}

    qi = {r.articolo_id: r.quantita for r in inv_a.righe}
    qf = {r.articolo_id: r.quantita for r in inv_b.righe}

    acquistato, speso = defaultdict(float), defaultdict(float)
    non_collegata = 0.0
    righe = (RigaFattura.query.join(FatturaRete)
             .filter(FatturaRete.locale_id == lid, FatturaRete.data > g0, FatturaRete.data <= g1).all())
    for r in righe:
        segno = r.fattura.segno
        if r.articolo_id and r.quantita_articolo:
            acquistato[r.articolo_id] += r.quantita_articolo * segno
            speso[r.articolo_id] += (r.totale or 0) * segno
        elif r.quantita and not r.ignorata:
            non_collegata += (r.totale or 0) * segno

    carichi, scarti = defaultdict(float), defaultdict(float)
    for m in MovimentoRete.query.filter(MovimentoRete.locale_id == lid, MovimentoRete.giorno > g0,
                                        MovimentoRete.giorno <= g1).all():
        (carichi if m.tipo == 'carico' else scarti)[m.articolo_id] += m.quantita

    # vendite → consumo teorico e ricavi
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    ricette = {r.id: r for r in RicettaRete.query.filter_by(locale_id=lid).all()}
    teorico = defaultdict(float)
    ricavi_lordi, ricavi, non_abbinate, piatti = 0.0, 0.0, defaultdict(float), defaultdict(float)
    # un piatto entra nel calcolo solo se tutti i suoi ingredienti hanno il prezzo vero delle fatture:
    # se no si conterebbe il suo incasso ma non il suo costo, e il food cost verrebbe più basso del vero
    prezzate, senza_prezzi_veri = {}, defaultdict(float)
    from services.vendite import vendite, a_cavallo
    for v in vendite(lid, g0 + timedelta(days=1), g1):
        al = alias.get(v.voce)
        if al and al.ignorata:
            continue
        ric = ricette.get(al.ricetta_id) if al and al.ricetta_id else None
        if not ric:
            non_abbinate[v.voce_originale or v.voce] += v.incasso or 0
            continue
        if ric.id not in prezzate:
            prezzate[ric.id] = bool(ric.righe) and costo_ricetta(ric)[0] is not None
        if not prezzate[ric.id]:
            senza_prezzi_veri[ric.nome] += v.incasso or 0
            continue
        incasso = v.incasso if v.incasso is not None else v.quantita * (ric.prezzo or 0)
        ricavi_lordi += incasso
        ricavi += v.netto if v.netto is not None else incasso / (1 + iva / 100)
        piatti[ric.nome] += v.quantita
        for rr in ric.righe:
            teorico[rr.articolo_id] += v.quantita * rr.quantita / (ric.resa or 1)

    righe_art, senza_prezzo, non_contati = [], [], []
    tot = defaultdict(float)
    for aid in set(qi) | set(qf) | set(acquistato) | set(carichi) | set(teorico) | set(scarti):
        a = articoli.get(aid)
        if not a:
            continue
        R = qi.get(aid, 0) + acquistato[aid] + carichi[aid] - qf.get(aid, 0)
        T, S = teorico[aid], scarti[aid]
        pm = speso[aid] / acquistato[aid] if acquistato[aid] > 0 else None
        pr = _prezzo_al(aid, g0)
        pm = pm if pm is not None else (pr if pr is not None else a.prezzo)
        pr = pr if pr is not None else pm
        if pm is None:
            if R or T:
                senza_prezzo.append(a.nome)
            continue
        if T and (aid not in qi or aid not in qf):
            non_contati.append(a.nome)
        x = {
            'articolo_id': aid, 'nome': a.nome, 'unita': a.unita,
            'iniziale': qi.get(aid), 'acquisti': round(acquistato[aid], 3), 'carichi': round(carichi[aid], 3),
            'finale': qf.get(aid), 'reale': round(R, 3), 'teorico': round(T, 3), 'scarti': round(S, 3),
            'prezzo_periodo': round(pm, 4), 'prezzo_prima': round(pr, 4),
            'costo_reale': R * pm, 'costo_teorico': T * pr,
            'prezzo': T * (pm - pr), 'scarto': S * pm, 'consumo': (R - T - S) * pm,
        }
        x['oltre_pct'] = round((R - T - S) / T * 100, 1) if T > 0 else None
        for k in ('costo_reale', 'costo_teorico', 'prezzo', 'scarto', 'consumo'):
            tot[k] += x[k]
            x[k] = round(x[k], 2)
        righe_art.append(x)

    punti = (lambda e: round(e / ricavi * 100, 2)) if ricavi > 0 else (lambda e: None)
    voci = {k: {'euro': round(tot[k], 2), 'punti': punti(tot[k])} for k in ('prezzo', 'scarto', 'consumo')}
    righe_art.sort(key=lambda x: -x['consumo'])

    # la frase per il titolare: la voce che pesa di più, se pesa davvero
    frase = None
    if ricavi > 0:
        nomi = {'consumo': 'il consumo oltre ricetta', 'prezzo': 'i prezzi d\'acquisto saliti', 'scarto': 'gli scarti'}
        k = max(voci, key=lambda k: voci[k]['punti'] or 0)
        if (voci[k]['punti'] or 0) >= SOGLIA_PUNTI:
            frase = f"In questo periodo hai perso {str(voci[k]['punti']).replace('.', ',')} punti di food cost per {nomi[k]}."
        else:
            frase = 'In questo periodo il food cost è in linea con le ricette.'

    avvisi = []
    if not ricavi_lordi:
        avvisi.append('Nessuna vendita abbinata a una ricetta nel periodo: carica il report della cassa e abbina le voci.')
    if non_abbinate:
        n = len(non_abbinate)
        avvisi.append(f"{n} {'voce venduta non è abbinata' if n == 1 else 'voci vendute non sono abbinate'} a una ricetta "
                      f'({round(sum(non_abbinate.values()))} € di incasso): {"resta" if n == 1 else "restano"} fuori dal calcolo.')
    if senza_prezzi_veri:
        n = len(senza_prezzi_veri)
        avvisi.append(f'{n} {"piatto ha" if n == 1 else "piatti hanno"} ingredienti ancora senza il prezzo di una fattura '
                      f'({round(sum(senza_prezzi_veri.values()))} € di incasso): fuori dal calcolo finché non si collegano le fatture. '
                      'I primi: ' + ', '.join(sorted(senza_prezzi_veri, key=lambda k: -senza_prezzi_veri[k])[:6]) + '.')
    for r in a_cavallo(lid, g0 + timedelta(days=1), g1):
        avvisi.append(f'Il report di cassa dal {r.dal.strftime("%d/%m")} al {r.al.strftime("%d/%m/%Y")} scavalca gli inventari '
                      'e resta fuori: per questa diagnosi scarica il report da un inventario all\'altro.')
    if non_collegata > 1:
        avvisi.append(f'{round(non_collegata)} € di acquisti del periodo non sono collegati a un articolo.')
    if senza_prezzo:
        avvisi.append('Senza prezzo, quindi fuori dal calcolo: ' + ', '.join(sorted(senza_prezzo)) + '.')
    if non_contati:
        avvisi.append('Usati nelle ricette ma non contati in uno dei due inventari (contati come zero): '
                      + ', '.join(sorted(non_contati)) + '.')

    return {
        'dal': g0.isoformat(), 'al': g1.isoformat(), 'giorni': (g1 - g0).days,
        'ricavi_lordi': round(ricavi_lordi, 2), 'ricavi_netti': round(ricavi, 2), 'iva': iva,
        'food_cost_reale': punti(tot['costo_reale']), 'food_cost_teorico': punti(tot['costo_teorico']),
        'obiettivo': obiettivo, 'costo_reale': round(tot['costo_reale'], 2),
        'costo_teorico': round(tot['costo_teorico'], 2), 'voci': voci, 'frase': frase,
        'articoli': righe_art, 'piatti': sorted(({'nome': k, 'quantita': v} for k, v in piatti.items()),
                                               key=lambda p: -p['quantita']),
        'non_abbinate': sorted(({'voce': k, 'incasso': round(v, 2)} for k, v in non_abbinate.items()),
                               key=lambda p: -p['incasso'])[:20],
        'avvisi': avvisi,
    }
