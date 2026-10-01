"""Gli indicatori di un locale per Monitoring: i quadranti del prototipo, sui dati veri.

Ogni indicatore ha un valore, un atteso con la sua tolleranza e un verso (se è meglio
basso o alto), la fonte da cui nasce e la mossa già decisa per quando esce. Quando un
dato non c'è ancora il valore è None e `manca` dice cosa serve per accenderlo.

Lo stato segue la regola del prototipo: dalla parte giusta dell'atteso è «buono»,
oltre ma dentro la tolleranza «attesa», più in là «fuori».

Gli attesi di partenza dipendono dal tipo di locale; il consulente li cambia per
locale in impostazioni['parametri'][id] = {atteso, toll}.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from models import (db, ArticoloRete, AliasVendita, ChiusuraRete, FatturaRete, InventarioRete, MovimentoRete,
                    RigaFattura, TurnoRete, VenditaRete)

# per tipo di locale: costo del personale (% sull'incasso senza IVA) e incasso per ora lavorata (€ senza IVA)
ATTESI_TIPO = {
    'pizzeria': {'pers': (30, 4), 'eora': (55, 10)},
    'trattoria': {'pers': (33, 4), 'eora': (50, 10)},
    'bar': {'pers': (32, 4), 'eora': (40, 8)},
    'ristorante': {'pers': (33, 4), 'eora': (50, 10)},
}

GRUPPI = [('economia', 'Food cost e acquisti'), ('personale', 'Personale'), ('vendite', 'Vendite'),
          ('routine', 'Controllo e routine'), ('presto', 'In arrivo')]


def tipo_di(locale):
    t = (locale.tipo or '').lower()
    for k, parole in (('pizzeria', ('pizz',)), ('bar', ('bar', 'caff', 'pastic')), ('trattoria', ('tratt', 'oster'))):
        if any(p in t for p in parole):
            return k
    return 'ristorante'


def stato(verso, atteso, toll, v):
    if v is None:
        return 'vuoto'
    scarto = v - atteso if verso == 'basso' else atteso - v
    return 'buono' if scarto <= 1e-9 else 'attesa' if scarto <= toll + 1e-9 else 'fuori'


def _giorno_utc(g, ora=5):
    from services.quadro import ROMA
    from datetime import timezone
    return datetime(g.year, g.month, g.day, ora, tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None)


def _acquisti(lid, dal, al):
    """Spesa senza IVA delle fatture del periodo (bolle escluse, non-cibo escluso; note di credito in meno)."""
    tot = 0.0
    for r in (RigaFattura.query.join(FatturaRete)
              .filter(FatturaRete.locale_id == lid, FatturaRete.data >= dal, FatturaRete.data <= al,
                      db.func.coalesce(FatturaRete.tipo, '') != 'DDT', RigaFattura.ignorata.isnot(True)).all()):
        tot += (r.totale or 0) * (r.fattura.segno if r.fattura.segno is not None else 1)
    return tot


def _scarti(lid, dal, al, prezzi):
    return sum(m.quantita * (prezzi.get(m.articolo_id) or 0) for m in MovimentoRete.query.filter(
        MovimentoRete.locale_id == lid, MovimentoRete.tipo == 'scarto', MovimentoRete.giorno >= dal, MovimentoRete.giorno <= al))


def _rincari(lid, oggi):
    """Variazione media dei prezzi d'acquisto: ultimo prezzo degli ultimi 30 giorni contro l'ultimo di prima,
    pesata sulla spesa recente di ogni articolo."""
    limite = oggi - timedelta(days=30)
    righe = (RigaFattura.query.join(FatturaRete)
             .filter(FatturaRete.locale_id == lid, FatturaRete.segno == 1, RigaFattura.articolo_id.isnot(None),
                     RigaFattura.quantita_articolo > 0, RigaFattura.totale > 0)
             .order_by(FatturaRete.data, RigaFattura.id).all())
    prima, dopo, spesa = {}, {}, defaultdict(float)
    for r in righe:
        p = r.totale / r.quantita_articolo
        if r.fattura.data < limite:
            prima[r.articolo_id] = p
        else:
            dopo[r.articolo_id] = p
            spesa[r.articolo_id] += r.totale
    comuni = [a for a in dopo if a in prima]
    if not comuni:
        return None, []
    peso = sum(spesa[a] for a in comuni) or 1
    media = sum((dopo[a] - prima[a]) / prima[a] * 100 * spesa[a] for a in comuni) / peso
    nomi = {a.id: a.nome for a in ArticoloRete.query.filter(ArticoloRete.id.in_(comuni)).all()}
    lista = sorted(((nomi.get(a, '?'), round((dopo[a] - prima[a]) / prima[a] * 100, 1)) for a in comuni), key=lambda x: -x[1])
    return round(media, 1), lista


def _manca_breve(lid, locale, chiusi, righe_cassa, rif, s, prev_passata, prev_prossima, acq4, inc4):
    """{id indicatore: il dato che manca, in poche parole e calcolato sullo stato del locale}."""
    from models import PersonaLocale, RicettaRete
    from services import vendite as V
    n_inv = InventarioRete.query.filter_by(locale_id=lid, chiuso=True).count()
    inv = '2 inventari chiusi' if n_inv == 0 else '1 inventario chiuso (ne serve un altro)'
    n_fatt = FatturaRete.query.filter(FatturaRete.locale_id == lid, db.func.coalesce(FatturaRete.tipo, '') != 'DDT').count()
    collegate = (RigaFattura.query.join(FatturaRete).filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.isnot(None)).count())
    cassa = V.ultima(lid) is not None
    n_ric = RicettaRete.query.filter_by(locale_id=lid).count()
    persone = PersonaLocale.query.filter(PersonaLocale.locale_id == lid, PersonaLocale.attiva.is_(True)).all()
    senza_costo = [p.nome for p in persone if p.ruolo != 'titolare' and not p.costo_orario]
    timbr = bool(s['ore'])
    prima_f = db.session.query(db.func.min(FatturaRete.data)).filter(
        FatturaRete.locale_id == lid, db.func.coalesce(FatturaRete.tipo, '') != 'DDT').scalar()
    fatture = 'le fatture dei fornitori' if not n_fatt else None
    if not fatture and rif and prima_f and str(prima_f) > rif['dal']:
        fatture = f'le fatture dal {rif["dal"][8:10]}/{rif["dal"][5:7]} al {prima_f.day:02d}/{prima_f.month:02d}'
    timbrature = 'le timbrature (tag «Timbra qui»)' if not timbr else None
    costo_orario = f'il costo orario di {", ".join(senza_costo[:3])}' if senza_costo else None
    incasso = 'la cassa' if not cassa else 'la cassa delle ultime settimane'
    previsto = 'il turno previsto (Persone e turni)' if not (prev_prossima and prev_prossima.get('euro')) else None
    return {
        'food': inv, 'oltre': inv,
        'teo': 'il ricettario' if not n_ric else 'la cassa' if not cassa else 'i prezzi degli ingredienti',
        'acq': fatture or ('la cassa' if not cassa else 'fatture e cassa delle stesse settimane'),
        'rinc': 'le fatture dei fornitori' if not n_fatt else 'fatture collegate agli articoli' if not collegate
                else 'fatture di almeno due mesi diversi',
        'spr': 'le fatture delle ultime 4 settimane' if not acq4 else 'il registro degli scarti',
        'pers': timbrature or costo_orario or incasso,
        'persp': previsto or incasso,
        'prev': previsto or timbrature or 'le timbrature',
        'eora': timbrature or incasso,
        'inc': incasso, 'cassa': 'la cassa',
        'ric': 'la cassa' if not cassa else 'il ricettario',
        'sconti': 'la cassa' if not cassa else 'la colonna «sconti» nel report della cassa',
        'storni': 'la cassa' if not cassa else 'gli storni nel report della cassa',
        'sco': 'il numero di scontrini (lettura diretta di SumUp)',
        'inv': 'il primo inventario',
        'rec': 'il collegamento al profilo Google (fase 3)',
        'temp': 'le sonde di temperatura (fase 3)',
    }


def indicatori(locale, oggi=None):
    from services.quadro import giorno_di_lavoro, _incasso, _personale
    from services.foodcost import diagnosi
    lid, imp = locale.id, locale.impostazioni or {}
    iva, ob = float(imp.get('iva', 10)), float(imp.get('obiettivo', 30))
    tipo = tipo_di(locale)
    oggi = oggi or giorno_di_lavoro()
    al, dal = oggi - timedelta(days=1), oggi - timedelta(days=7)
    dal4 = oggi - timedelta(days=28)
    netto = lambda x: x / (1 + iva / 100)
    prezzi = {a.id: a.prezzo for a in ArticoloRete.query.filter_by(locale_id=lid).all()}

    # le otto settimane, per le linee dentro le schede
    sett = []
    for i in range(7, -1, -1):
        a = oggi - timedelta(days=1 + 7 * i)
        d = a - timedelta(days=6)
        inc, giorni = _incasso(lid, d, a)
        ore, costo, _ = _personale(lid, d, a)
        acq = _acquisti(lid, d, a)
        sett.append({'inc': inc if giorni else None, 'netto': netto(inc), 'ore': ore, 'costo': costo, 'acq': acq,
                     'scarti': _scarti(lid, d, a, prezzi),
                     'chiusure': ChiusuraRete.query.filter(ChiusuraRete.locale_id == lid, ChiusuraRete.giorno >= d,
                                                           ChiusuraRete.giorno <= a).count()})
    s = sett[-1]
    pct = lambda a, b: round(a / b * 100, 1) if b else None

    chiusi = InventarioRete.query.filter_by(locale_id=lid, chiuso=True).order_by(InventarioRete.giorno.desc()).limit(2).all()
    dg = diagnosi(locale, chiusi[1], chiusi[0]) if len(chiusi) == 2 else None

    inc4 = sum(x['netto'] for x in sett[-4:])
    acq4 = sum(x['acq'] for x in sett[-4:])
    # niente cassa nelle ultime 4 settimane ma un report di periodo (SumUp): fa da riferimento, dicendo di quando
    from services import vendite as V
    rif = V.riferimento(lid, dal4, al, iva)
    scarti4 = sum(x['scarti'] for x in sett[-4:])
    prec = [x['inc'] for x in sett[-5:-1] if x['inc'] is not None]
    media_prec = sum(prec) / len(prec) if prec else None
    rinc, lista_rinc = _rincari(lid, oggi)

    # quanto dell'incasso passa da piatti del ricettario
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    from services import vendite as V
    righe_cassa, quando_cassa = V.base_cassa(lid, dal4, al)
    coperto = totale = 0.0
    mancanti = defaultdict(float)
    for v in righe_cassa:
        a = alias.get(v.voce)
        if a and a.ignorata:
            continue
        totale += v.incasso or 0
        if a and a.ricetta_id:
            coperto += v.incasso or 0
        else:
            mancanti[v.voce_originale or v.voce] += v.incasso or 0

    # sconti e storni: li danno le casse più complete (il report prodotti di SumUp)
    con_sconti = [v for v in righe_cassa if v.sconti is not None]
    sconti = sum(v.sconti for v in con_sconti)
    venduto_sc = sum(v.incasso or 0 for v in con_sconti) + sconti
    con_resi = [v for v in righe_cassa if v.resi_quantita is not None]
    resi = sum(v.resi_incasso or 0 for v in con_resi)
    venduto_re = sum(v.incasso or 0 for v in con_resi) + resi
    voci_resi = defaultdict(float)
    for v in con_resi:
        if v.resi_incasso:
            voci_resi[v.voce_originale or v.voce] += v.resi_incasso
    voci_sconti = defaultdict(float)
    for v in con_sconti:
        if v.sconti:
            voci_sconti[v.voce_originale or v.voce] += v.sconti

    ultima_vendita = V.ultima(lid)
    ultimo_inv = chiusi[0].giorno if chiusi else None
    adesso = datetime.utcnow()
    dimenticati = TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.fine.is_(None),
                                         TurnoRete.inizio < adesso - timedelta(hours=14),
                                         TurnoRete.inizio >= _giorno_utc(dal)).count()
    bolle = FatturaRete.query.filter(FatturaRete.locale_id == lid, FatturaRete.tipo == 'DDT',
                                     FatturaRete.data >= oggi - timedelta(days=30)).all()
    problemi = [b for b in bolle if (b.etichette or {}).get('note')]
    da_guardare = [f for f in FatturaRete.query.filter_by(locale_id=lid).all()
                   if ((f.etichette or {}).get('controlla') or (f.etichette or {}).get('note')) and not (f.etichette or {}).get('visto')]

    pa = {**ATTESI_TIPO[tipo]}
    P = lambda k, atteso, toll: tuple((imp.get('parametri') or {}).get(k, {}).get(x, d) for x, d in (('atteso', atteso), ('toll', toll)))

    out = []

    def aggiungi(gruppo, id_, nome, valore, unita, verso, atteso, toll, fonte, mossa, manca=None, serie=None, dettaglio=None, mostra=None):
        # mostra: quello che si sa già quando la percentuale non si può ancora fare (gli euro del personale)
        atteso, toll = P(id_, atteso, toll)
        out.append({'id': id_, 'gruppo': gruppo, 'nome': nome, 'valore': valore, 'unita': unita, 'verso': verso,
                    'atteso': atteso, 'toll': toll, 'stato': stato(verso, atteso, toll, valore), 'fonte': fonte,
                    'mossa': mossa, 'manca': manca if valore is None else None, 'serie': serie,
                    'dettaglio': dettaglio or [], 'mostra': mostra if valore is None else None})

    # ── food cost e acquisti ──
    aggiungi('economia', 'food', 'Food cost vero', dg['food_cost_reale'] if dg else None, '%', 'basso', ob, 2,
             'Inventari, fatture e cassa', 'Aprire la diagnosi: prezzi, scarti o consumo oltre ricetta',
             'servono due inventari chiusi',
             dettaglio=[('Periodo', f"{dg['dal']} → {dg['al']}")] + [(n, f"{dg['voci'][k]['punti']:+.2f} punti".replace('.', ','))
                        for k, n in (('prezzo', 'Prezzi d\'acquisto'), ('scarto', 'Scarti'), ('consumo', 'Consumo oltre ricetta'))] if dg else None)
    # senza due inventari, il food cost delle ricette si fa sulle vendite: venduti × costo della porzione
    from services.foodcost import food_cost_ricette
    fcr = None if dg else food_cost_ricette(lid, righe_cassa, iva)
    if fcr:
        fonte_teo = (f'Ricette × vendite, {quando_cassa}' + (f'; prezzi stimati per il {fcr["quota_stima"]}% del costo, '
                     'finché non si collegano le fatture' if fcr['quota_stima'] else '; prezzi delle fatture'))
    aggiungi('economia', 'teo', 'Food cost delle ricette', dg['food_cost_teorico'] if dg else (fcr['valore'] if fcr else None), '%', 'basso', ob, 2,
             'Ricettario e prezzi d\'acquisto' if dg or not fcr else fonte_teo,
             'Rivedere prezzi di vendita o grammature dei piatti più venduti',
             'servono ricettario e vendite (o due inventari)',
             dettaglio=[(x['nome'], f"{x['food_cost']:.0f}%".replace('.', ',')) for x in fcr['piatti'][:5] if x['food_cost'] is not None] if fcr else None)
    aggiungi('economia', 'oltre', 'Consumo oltre ricetta', dg['voci']['consumo']['punti'] if dg else None, 'punti', 'basso', 0, 0.5,
             'Inventari contro vendite × ricette', 'Pesare le porzioni dei piatti in testa alla classifica, formare la cucina',
             'servono due inventari chiusi',
             dettaglio=[(a['nome'], f"+{a['oltre_pct']:.0f}%".replace('.', ',')) for a in dg['articoli'] if a.get('consumo', 0) > 1][:5] if dg else None)
    v_acq, fonte_acq, manca_acq = (pct(acq4, inc4) if acq4 and inc4 else None), 'Fatture e cassa, ultime 4 settimane', 'servono fatture e cassa delle ultime 4 settimane'
    if v_acq is None and rif:
        from datetime import date as _d
        prima_f = db.session.query(db.func.min(FatturaRete.data)).filter(
            FatturaRete.locale_id == lid, db.func.coalesce(FatturaRete.tipo, '') != 'DDT').scalar()
        dal_r, al_r = _d.fromisoformat(rif['dal']), _d.fromisoformat(rif['al'])
        if prima_f and prima_f <= dal_r + timedelta(days=7):
            v_acq, fonte_acq = pct(_acquisti(lid, dal_r, al_r), rif['netto']), 'Fatture e report di cassa, ' + rif['quando']
        else:
            # confrontare poche settimane di fatture con mesi di incasso darebbe un numero finto
            manca_acq = ('le fatture caricate ' + (f'partono dal {prima_f.day}/{prima_f.month}' if prima_f else 'non ci sono') +
                         f', il report di cassa dal {dal_r.day}/{dal_r.month}: servono le fatture di tutto il periodo del report, '
                         'oppure il report scaricato per le stesse settimane delle fatture')
    aggiungi('economia', 'acq', 'Acquisti sull\'incasso', v_acq, '%', 'basso', ob, 4,
             fonte_acq, 'Confrontare ordini e vendite: si compra più di quanto si vende',
             manca_acq,
             serie=[pct(x['acq'], x['netto']) if x['acq'] and x['netto'] else None for x in sett])
    aggiungi('economia', 'rinc', 'Rincari dei fornitori', rinc, '%', 'basso', 0, 3,
             'Fatture: prezzo degli ultimi 30 giorni contro prima', 'Rinegoziare o cambiare fornitore sugli articoli rincarati',
             'servono fatture collegate di più di un mese',
             dettaglio=[(n, f"{v:+.1f}%".replace('.', ',')) for n, v in lista_rinc[:5]])
    aggiungi('economia', 'spr', 'Sprechi registrati', pct(scarti4, acq4) if acq4 and scarti4 else (0.0 if acq4 else None), '%', 'basso', 2.5, 1,
             'Registro degli scarichi sugli acquisti, 4 settimane', 'Etichettatura, rotazione, ordini più piccoli e più frequenti',
             'servono fatture e registro degli scarichi',
             serie=[pct(x['scarti'], x['acq']) if x['acq'] else None for x in sett])

    # ── personale ──
    from services.quadro import previsto
    prev_passata = previsto(lid, dal, al)
    prev_prossima = previsto(lid, oggi, oggi + timedelta(days=6), mese_di=oggi)
    media_netto = inc4 / 4 if inc4 else (rif['sett_netto'] if rif else None)
    # senza cassa, l'incasso medio mensile detto dal titolare all'incontro (IVA compresa) fa da riferimento
    try:
        dich = float(((locale.scheda or {}).get('numeri') or {}).get('incasso') or 0) or None
    except (TypeError, ValueError):
        dich = None
    sett_dich = netto(dich) / 4.33 if dich else None
    eur = lambda v: f'{v:,.0f} €'.replace(',', '.')
    serve_incasso = 'per la percentuale serve l\'incasso: la cassa, oppure l\'incasso medio in Managing → Dossier'
    if s['costo'] and s['netto']:
        v_pers, fonte_pers, manca_pers = pct(s['costo'], s['netto']), 'Timbrature × costo orario, sull\'incasso senza IVA', None
    elif s['costo'] and rif:
        v_pers, fonte_pers, manca_pers = pct(s['costo'], rif['sett_netto']), f'Timbrature × costo orario, sull\'incasso medio a settimana del report di cassa {rif["quando"]}', None
    elif s['costo'] and sett_dich:
        v_pers, fonte_pers, manca_pers = pct(s['costo'], sett_dich), 'Timbrature × costo orario, sull\'incasso medio dichiarato dal titolare (la cassa non c\'è ancora)', None
    else:
        v_pers, fonte_pers = None, 'Timbrature × costo orario, sull\'incasso senza IVA'
        manca_pers = (f'{eur(s["costo"])} timbrati negli ultimi 7 giorni: ' + serve_incasso if s['costo'] else
                      f'nessuna timbratura negli ultimi 7 giorni; dal turno previsto {eur(prev_prossima["euro"])} a settimana' if prev_prossima and prev_prossima['euro'] else
                      'servono timbrature, costo orario e cassa')
    aggiungi('personale', 'pers', 'Costo del personale', v_pers, '%', 'basso',
             *pa['pers'], fonte_pers, 'Turni rifatti sui coperti reali per giorno e fascia', manca_pers,
             serie=[pct(x['costo'], x['netto']) if x['costo'] and x['netto'] else None for x in sett],
             mostra=eur(s['costo']) if s['costo'] and v_pers is None else (eur(prev_prossima['euro']) + ' previsti' if prev_prossima and prev_prossima['euro'] and v_pers is None else None))
    base_persp = media_netto or sett_dich
    aggiungi('personale', 'persp', 'Costo del personale previsto', pct(prev_prossima['euro'], base_persp) if prev_prossima and prev_prossima['euro'] and base_persp else None,
             '%', 'basso', *pa['pers'],
             'Turno previsto dei prossimi 7 giorni × costo orario, ' + ('sull\'incasso medio delle ultime 4 settimane' if inc4 else
                                                                         f'sull\'incasso medio a settimana del report di cassa {rif["quando"]}' if rif else 'sull\'incasso medio dichiarato dal titolare'),
             'Rifare i turni prima che la settimana cominci: è l\'unico costo che si decide in anticipo',
             f'{eur(prev_prossima["euro"])} previsti a settimana: ' + serve_incasso if prev_prossima and prev_prossima['euro'] else 'serve il turno previsto (Managing → Persone e turni)',
             mostra=eur(prev_prossima['euro']) if prev_prossima and prev_prossima['euro'] and not base_persp else None,
             dettaglio=[('Settimana che comincia', f"{prev_prossima['euro']:,.0f} €".replace(',', '.') + f" · {prev_prossima['ore']:.0f} ore"),
                        ('Mese in corso', f"{prev_prossima['euro_mese']:,.0f} €".replace(',', '.') + f" · {prev_prossima['ore_mese']:.0f} ore")] if prev_prossima else None)
    aggiungi('personale', 'prev', 'Ore timbrate sul previsto', pct(s['ore'], prev_passata['ore']) if prev_passata and prev_passata['ore'] and s['ore'] else None,
             '%', 'basso', 100, 10, 'Timbrature degli ultimi 7 giorni contro il turno previsto',
             'Guardare chi ha fatto più ore del previsto: straordinari o turni scritti male',
             'servono il turno previsto e le timbrature')
    aggiungi('personale', 'eora', 'Incasso per ora lavorata', round(s['netto'] / s['ore'], 1) if s['ore'] and s['netto'] else None, '€', 'alto',
             *pa['eora'], 'Cassa senza IVA diviso ore timbrate', 'Meno ore nei giorni deboli, più in quelli forti',
             'servono timbrature e cassa',
             serie=[round(x['netto'] / x['ore'], 1) if x['ore'] and x['netto'] else None for x in sett])
    aggiungi('personale', 'turni', 'Turni senza uscita', dimenticati, '', 'basso', 0, 1,
             'Timbrature degli ultimi 7 giorni', 'Ricordare allo staff di timbrare l\'uscita; il consulente corregge il turno')

    # ── vendite ──
    if s['inc'] is None and rif:
        # la cassa arriva a blocchi: l'incasso medio a settimana del report, la linea report per report
        mr = V.medie_report(lid)
        aggiungi('vendite', 'inc', 'Incasso medio a settimana', round(rif['sett_incasso'], 0), '€', 'alto',
                 round(sum(x['sett_incasso'] for x in mr[:-1]) / len(mr[:-1]), 0) if len(mr) > 1 else round(rif['sett_incasso'], 0),
                 round(sum(x['sett_incasso'] for x in mr[:-1]) / len(mr[:-1]) * 0.1, 0) if len(mr) > 1 else 0,
                 f'Report di cassa {rif["quando"]}: {eur(rif["incasso"])} in {rif["giorni"]} giorni',
                 'Scaricare il report settimana per settimana: si vede l\'andamento e si confronta col personale',
                 serie=[round(x['sett_incasso'], 0) for x in mr],
                 dettaglio=[('Incasso del periodo', eur(rif['incasso'])), ('Senza IVA', eur(rif['netto'])),
                            ('Media al mese', eur(rif['mese_incasso'])), ('Media a settimana', eur(rif['sett_incasso']))])
    else:
        aggiungi('vendite', 'inc', 'Incasso della settimana', round(s['inc'], 0) if s['inc'] is not None else None, '€', 'alto',
                 round(media_prec, 0) if media_prec else (round(s['inc'], 0) if s['inc'] else 0),
                 round(media_prec * 0.1, 0) if media_prec else 0,
                 'Cassa · atteso: media delle 4 settimane prima', 'Capire se è stagione o calo vero: confrontare giorno per giorno',
                 'serve la cassa', serie=[round(x['inc'], 0) if x['inc'] is not None else None for x in sett])
    aggiungi('vendite', 'ric', 'Vendite coperte dal ricettario', pct(coperto, totale) if totale else None, '%', 'alto', 80, 10,
             'Cassa e ricettario, ' + (quando_cassa or 'ultime 4 settimane'), 'Aggiungere al ricettario i piatti venduti che mancano',
             'servono cassa e ricettario',
             dettaglio=[(n, f'{v:,.0f} €'.replace(',', '.')) for n, v in sorted(mancanti.items(), key=lambda x: -x[1])[:5]])
    aggiungi('vendite', 'sconti', 'Sconti sull\'incasso', pct(sconti, venduto_sc) if con_sconti and venduto_sc else None, '%', 'basso', 3, 2,
             'Cassa: sconti sul venduto, ' + (quando_cassa or 'ultime 4 settimane'),
             'Regole scritte per sconti e omaggi: chi li può fare e quando',
             'serve un report di cassa con la colonna degli sconti (il report prodotti di SumUp ce l\'ha)',
             dettaglio=[(n, eur(v)) for n, v in sorted(voci_sconti.items(), key=lambda x: -x[1])[:5]])
    aggiungi('vendite', 'storni', 'Storni e resi', pct(resi, venduto_re) if con_resi and venduto_re else None, '%', 'basso', 1, 1,
             'Cassa: righe stornate o rese sul venduto, ' + (quando_cassa or 'ultime 4 settimane'),
             'Guardare chi storna e quando: uno storno senza motivo è un incasso che sparisce',
             'serve un report di cassa che riporti gli storni (il report prodotti di SumUp li dà come righe negative)',
             dettaglio=[(n, eur(v)) for n, v in sorted(voci_resi.items(), key=lambda x: -x[1])[:5]])
    aggiungi('vendite', 'sco', 'Scontrino medio', None, '€', 'alto', 25, 3, 'Cassa: incasso diviso scontrini',
             'Abbinamenti e proposta in sala', 'serve il numero di scontrini dalla cassa: arriva con la lettura diretta di SumUp')

    # ── controllo e routine ──
    aggiungi('routine', 'chk', 'Chiusure segnate', round(s['chiusure'] / 7 * 100, 0), '%', 'alto', 90, 10,
             'App del locale, ultimi 7 giorni', 'Richiamo alla squadra: è il primo numero che scende',
             serie=[round(x['chiusure'] / 7 * 100, 0) for x in sett])
    aggiungi('routine', 'inv', 'Giorni dall\'ultimo inventario', (oggi - ultimo_inv).days if ultimo_inv else None, 'gg', 'basso', 7, 7,
             'Inventari del consulente', 'Fissare la visita settimanale: senza inventari non c\'è diagnosi', 'nessun inventario chiuso')
    aggiungi('routine', 'cassa', 'Cassa aggiornata', max(0, (al - ultima_vendita).days) if ultima_vendita else None, 'gg di ritardo', 'basso', 0, 2,
             'Ultima giornata di vendite caricata', 'Caricare il report o controllare il collegamento con la cassa', 'nessuna vendita caricata')
    aggiungi('routine', 'cons', 'Consegne con problemi', len(problemi), '', 'basso', 0, 2,
             'Bolle degli ultimi 30 giorni', 'Parlarne col fornitore; chiedere la nota di credito',
             dettaglio=[(b.fornitore, (b.etichette or {}).get('note')) for b in problemi[:5]])
    aggiungi('routine', 'doc', 'Documenti da guardare', len(da_guardare), '', 'basso', 0, 3,
             'Fatture e bolle lette da PDF e foto', 'Aprire Acquisti → Da guardare e confermarli')

    # ── in arrivo ──
    aggiungi('presto', 'rec', 'Voto delle recensioni', None, '', 'alto', 4.4, 0.3, 'Profilo Google',
             'Placca NFC al tavolo, protocollo di risposta', 'fase 3: collegamento al profilo Google')
    aggiungi('presto', 'temp', 'Temperature di celle e frigo', None, '°C', 'basso', 4, 2, 'Sonde',
             'Controllo della cella, registro HACCP', 'fase 3: sonde di temperatura')

    # quando un quadrante è vuoto, il dato preciso che manca (al posto di «manca il dato»)
    breve = _manca_breve(lid, locale, chiusi, righe_cassa, rif, s, prev_passata, prev_prossima, acq4, inc4)
    for i in out:
        i['manca_breve'] = breve.get(i['id']) if i['valore'] is None else None

    fuori = [i for i in out if i['stato'] == 'fuori']
    return {'tipo': tipo, 'gruppi': GRUPPI, 'indicatori': out,
            'conta': {k: sum(1 for i in out if i['stato'] == k) for k in ('buono', 'attesa', 'fuori', 'vuoto')},
            'fuori': [i['nome'] for i in fuori]}
