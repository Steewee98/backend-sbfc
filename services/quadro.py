"""«Il quadro» del titolare (Rete SB, fase 2): una pagina, pochi numeri, una frase.

Il titolare non inserisce niente: i numeri arrivano dalla cassa, dalle
timbrature e dalla diagnosi del food cost che prepara il consulente.

    incasso della settimana       vendite degli ultimi 7 giorni, contro i 7 prima
    costo del personale           ore timbrate × costo orario, sull'incasso senza IVA
    food cost                     l'ultima diagnosi tra due inventari
    chiusure segnate              quante sere chi ha chiuso l'ha segnato
"""
from datetime import datetime, timedelta, timezone

from dateutil import tz

from models import (db, InventarioRete, VenditaRete, ReportCassa, PersonaLocale, TurnoRete, ChiusuraRete,
                    FatturaRete, RigaFattura, MovimentoRete, RicettaRete, ArticoloRete, AliasVendita)

ROMA = tz.gettz('Europe/Rome')


def ora_locale(dt_utc):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(ROMA)


def giorno_di_lavoro(adesso_utc=None):
    """La giornata del locale: fino alle 5 del mattino è ancora quella di ieri."""
    t = ora_locale(adesso_utc or datetime.utcnow())
    return (t - timedelta(hours=5)).date()


def _incasso(lid, dal, al):
    """(incasso, giorni coperti): i giorni e i report di periodo che stanno per intero tra dal e al."""
    from services.vendite import incasso
    return incasso(lid, dal, al)


def _fc_ricette(locale, iva):
    """Prima dei due inventari: il food cost delle ricette sulle vendite (ultime 4 settimane o ultimo report),
    con quanto pesano i prezzi stimati."""
    from services.foodcost import food_cost_ricette
    from services.vendite import base_cassa
    oggi = giorno_di_lavoro()
    righe, quando = base_cassa(locale.id, oggi - timedelta(days=28), oggi - timedelta(days=1))
    f = food_cost_ricette(locale.id, righe, iva) if righe else None
    return {'valore': f['valore'], 'quota_stima': f['quota_stima'], 'quando': quando,
            'obiettivo': float((locale.impostazioni or {}).get('obiettivo', 30))} if f else None


def _personale(lid, dal, al):
    """Ore e costo dei turni iniziati in quei giorni (ora di Roma); i turni ancora aperti non contano."""
    inizio = datetime(dal.year, dal.month, dal.day, 5, tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None)
    fine = datetime(al.year, al.month, al.day, 5, tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    costi = {p.id: p.costo_orario for p in PersonaLocale.query.filter_by(locale_id=lid).all()}
    ore, costo, senza_costo = 0.0, 0.0, set()
    for t in TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.inizio >= inizio,
                                    TurnoRete.inizio < fine, TurnoRete.fine.isnot(None)).all():
        h = t.ore()
        ore += h
        if costi.get(t.persona_id):
            costo += h * costi[t.persona_id]
        else:
            senza_costo.add(t.persona_id)
    return ore, costo, senza_costo


def _ore_per_persona(lid, dal, al):
    inizio = datetime(dal.year, dal.month, dal.day, 5, tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None)
    fine = datetime(al.year, al.month, al.day, 5, tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    ore = {}
    for t in TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.inizio >= inizio,
                                    TurnoRete.inizio < fine, TurnoRete.fine.isnot(None)).all():
        ore[t.persona_id] = ore.get(t.persona_id, 0) + t.ore()
    return ore


def squadra(lid, dal, al):
    """Chi lavora nel locale e quante ore ha timbrato nella settimana."""
    ore = _ore_per_persona(lid, dal, al)
    aperti = {t.persona_id for t in TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.fine.is_(None),
                                                           TurnoRete.inizio > datetime.utcnow() - timedelta(hours=14))}
    ordine = {'titolare': 0, 'responsabile': 1, 'staff': 2}
    persone = sorted(PersonaLocale.query.filter_by(locale_id=lid, attiva=True).all(),
                     key=lambda p: (ordine.get(p.ruolo, 3), p.nome.lower()))
    from services.previsto import ore_periodo
    return [{'nome': p.nome, 'ruolo': p.ruolo, 'mansione': p.mansione, 'reparto': p.reparto,
             'ore': round(ore.get(p.id, 0), 1), 'in_servizio': p.id in aperti,
             'costo_orario': p.costo_orario is not None, 'timbra': bool(p.pin_hash),
             'ore_previste': round(ore_periodo(p.orario, dal, al), 1) if p.orario else None} for p in persone]


def previsto(lid, dal, al, mese_di=None):
    """Ore e costo del turno previsto di tutta la squadra tra due date, più il mese di `mese_di` (o di `al`)."""
    al_m = mese_di or al
    import calendar
    from datetime import date
    from services.previsto import ore_periodo
    persone = PersonaLocale.query.filter_by(locale_id=lid, attiva=True).all()
    con = [p for p in persone if p.orario]
    if not con:
        return None
    m0, m1 = date(al_m.year, al_m.month, 1), date(al_m.year, al_m.month, calendar.monthrange(al_m.year, al_m.month)[1])
    ore = sum(ore_periodo(p.orario, dal, al) for p in con)
    ore_m = sum(ore_periodo(p.orario, m0, m1) for p in con)
    return {'ore': round(ore, 1), 'euro': round(sum(ore_periodo(p.orario, dal, al) * (p.costo_orario or 0) for p in con), 2),
            'ore_mese': round(ore_m, 1), 'euro_mese': round(sum(ore_periodo(p.orario, m0, m1) * (p.costo_orario or 0) for p in con), 2),
            'mese': al_m.month, 'persone': len(con),
            # il titolare di solito non ha un turno: non si conta tra chi manca
            'senza_orario': sum(1 for p in persone if not p.orario and p.ruolo != 'titolare')}


def lavoro(lid, dal, al):
    """A che punto è il lavoro del consulente: quello che si vede anche da Monitoring e dall'app del titolare."""
    fatture = FatturaRete.query.filter_by(locale_id=lid)
    sett = fatture.filter(FatturaRete.data >= dal, FatturaRete.data <= al).all()
    ultima = fatture.order_by(FatturaRete.data.desc()).first()
    da_collegare = (db.session.query(RigaFattura.chiave).join(FatturaRete)
                    .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.is_(None),
                            RigaFattura.quantita.isnot(None), RigaFattura.ignorata.isnot(True),
                            db.func.coalesce(FatturaRete.tipo, '') != 'DDT').distinct().count())
    noti = {a.voce for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    from services import vendite as V
    voci = V.voci(lid)
    inv = InventarioRete.query.filter_by(locale_id=lid)
    ultimo_inv = inv.filter_by(chiuso=True).order_by(InventarioRete.giorno.desc()).first()
    aperto = inv.filter_by(chiuso=False).order_by(InventarioRete.giorno.desc()).first()
    ultima_vendita = V.ultima(lid)
    scarti = MovimentoRete.query.filter(MovimentoRete.locale_id == lid, MovimentoRete.tipo == 'scarto',
                                        MovimentoRete.giorno >= dal, MovimentoRete.giorno <= al).all()
    prezzi = {a.id: a.prezzo or 0 for a in ArticoloRete.query.filter_by(locale_id=lid).all()}
    return {
        'acquisti': round(sum((f.imponibile or 0) * (f.segno if f.segno is not None else 1) for f in sett), 2),
        'fatture_settimana': sum(1 for f in sett if f.segno), 'fatture': fatture.count(),
        'ultima_fattura': ultima.data.isoformat() if ultima else None,
        'da_collegare': da_collegare, 'voci_da_abbinare': len(voci - noti),
        'articoli': ArticoloRete.query.filter_by(locale_id=lid).count(),
        'ricette': RicettaRete.query.filter_by(locale_id=lid).count(),
        'inventari': inv.filter_by(chiuso=True).count(),
        'ultimo_inventario': ultimo_inv.giorno.isoformat() if ultimo_inv else None,
        'inventario_aperto': aperto.giorno.isoformat() if aperto else None,
        'ultima_vendita': ultima_vendita.isoformat() if ultima_vendita else None,
        'scarti': len(scarti), 'scarti_euro': round(sum(m.quantita * prezzi.get(m.articolo_id, 0) for m in scarti), 2),
    }


def _var(a, b):
    return round((a - b) / b * 100, 1) if b else None


def quadro(locale, oggi=None):
    from services.foodcost import diagnosi
    from routes.rete_foodcost import semaforo
    lid = locale.id
    imp = locale.impostazioni or {}
    iva = float(imp.get('iva', 10))
    oggi = oggi or giorno_di_lavoro()
    al, dal = oggi - timedelta(days=1), oggi - timedelta(days=7)
    al0, dal0 = dal - timedelta(days=1), dal - timedelta(days=7)

    inc, giorni_vendite = _incasso(lid, dal, al)
    inc0, _ = _incasso(lid, dal0, al0)
    # senza cassa nelle ultime due settimane, l'ultimo report di periodo (SumUp) dice quanto incassa il locale
    from services.vendite import riferimento
    rif = riferimento(lid, dal0, al, iva)
    ore, costo, senza_costo = _personale(lid, dal, al)
    ore0, costo0, _ = _personale(lid, dal0, al0)
    netto, netto0 = inc / (1 + iva / 100), inc0 / (1 + iva / 100)
    pers = round(costo / netto * 100, 1) if netto and costo else None
    pers0 = round(costo0 / netto0 * 100, 1) if netto0 and costo0 else None

    chiusi = (InventarioRete.query.filter_by(locale_id=lid, chiuso=True)
              .order_by(InventarioRete.giorno.desc()).limit(2).all())
    d = diagnosi(locale, chiusi[1], chiusi[0]) if len(chiusi) == 2 else None

    fatte = {c.giorno: c for c in ChiusuraRete.query.filter(ChiusuraRete.locale_id == lid, ChiusuraRete.giorno >= dal,
                                                           ChiusuraRete.giorno <= al).all()}
    chiusure = len(fatte)
    # le sette sere, una per una: fatta, fatta con qualcosa da ricontrollare, non segnata
    sere = []
    for i in range(7):
        g = dal + timedelta(days=i)
        c = fatte.get(g)
        manca = [k for k in ('celle', 'gas', 'luci', 'cassa', 'porte') if c and not (c.voci or {}).get(k)]
        sere.append({'giorno': g.isoformat(), 'stato': 'no' if not c else 'controlla' if manca else 'ok', 'manca': manca})
    # stasera: la chiusura di oggi si vede subito, anche se la settimana del quadro arriva a ieri
    co = ChiusuraRete.query.filter_by(locale_id=lid, giorno=oggi).first()
    chi_co = db.session.get(PersonaLocale, co.persona_id) if co and co.persona_id else None
    manca_oggi = [k for k in ('celle', 'gas', 'luci', 'cassa', 'porte') if co and not (co.voci or {}).get(k)]
    stasera = {'stato': 'no' if not co else 'controlla' if manca_oggi else 'ok', 'manca': manca_oggi,
               'ora': ora_locale(co.ora).strftime('%H:%M') if co and co.ora else None, 'chi': chi_co.nome if chi_co else None}
    in_servizio = [p.nome for p in PersonaLocale.query.join(TurnoRete, TurnoRete.persona_id == PersonaLocale.id)
                   .filter(TurnoRete.locale_id == lid, TurnoRete.fine.is_(None),
                           TurnoRete.inizio > datetime.utcnow() - timedelta(hours=14)).all()]

    # la frase: la cosa che è cambiata di più, detta come la direbbe il consulente
    frase = None
    if d and (d['voci']['consumo']['punti'] or 0) >= 0.3:
        frase = d['frase']
    elif pers is not None and pers0 is not None and pers - pers0 >= 2:
        frase = f'Il costo del personale è salito di {str(round(pers - pers0, 1)).replace(".", ",")} punti rispetto alla settimana prima.'
    elif _var(inc, inc0) is not None and abs(_var(inc, inc0)) >= 10:
        v = _var(inc, inc0)
        frase = f"L'incasso è {'salito' if v > 0 else 'sceso'} del {str(abs(v)).replace('.', ',')}% rispetto alla settimana prima."
    elif inc:
        frase = 'Settimana in linea con la precedente.'
    elif rif:
        e = lambda v: f'{v:,.0f} €'.replace(',', '.')
        frase = f"{rif['quando'].capitalize()} hai incassato {e(rif['incasso'])}: in media {e(rif['sett_incasso'])} a settimana."
    else:
        frase = 'Ancora pochi dati: il quadro si riempie con la cassa e le timbrature.'

    return {
        'locale': locale.nome, 'dal': dal.isoformat(), 'al': al.isoformat(), 'frase': frase,
        'incasso': {'euro': round(inc, 2), 'prima': round(inc0, 2), 'variazione': _var(inc, inc0), 'giorni': giorni_vendite,
                    'periodo': {k: rif[k] for k in ('dal', 'al', 'giorni', 'incasso', 'netto', 'sett_incasso', 'mese_incasso', 'quando')} if rif else None},
        'personale': {'percento': pers, 'prima': pers0, 'ore': round(ore, 1), 'ore_prima': round(ore0, 1),
                      'euro': round(costo, 2), 'senza_costo_orario': len(senza_costo),
                      # il turno previsto: la settimana passata (per il confronto) e quella che comincia oggi, col mese in corso
                      'previsto': previsto(lid, dal, al),
                      'prossima': previsto(lid, oggi, oggi + timedelta(days=6), mese_di=oggi)},
        'food_cost': ({'vero': d['food_cost_reale'], 'ricette': d['food_cost_teorico'], 'obiettivo': d['obiettivo'],
                       'dal': d['dal'], 'al': d['al'], 'semaforo': semaforo(d)} if d else None),
        'food_cost_ricette': _fc_ricette(locale, iva) if not d else None,
        'chiusure': {'segnate': chiusure, 'giorni': 7, 'sere': sere, 'stasera': stasera},
        'in_servizio': in_servizio,
        'squadra': squadra(lid, dal, al),
        'lavoro': lavoro(lid, dal, al),
    }


GIORNI = ['lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom']
MESI = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic']


def andamento(locale, settimane=8, oggi=None):
    """Le serie per i grafici: settimana per settimana (le ultime `settimane`, fino a ieri),
    il food cost di ogni periodo tra due inventari, l'incasso medio per giorno della settimana
    e i piatti più venduti negli ultimi 7 giorni."""
    from collections import defaultdict
    from services.foodcost import diagnosi
    from models import AliasVendita, RicettaRete
    lid = locale.id
    iva = float((locale.impostazioni or {}).get('iva', 10))
    oggi = oggi or giorno_di_lavoro()

    serie = []
    for i in range(settimane - 1, -1, -1):
        al = oggi - timedelta(days=1 + 7 * i)
        dal = al - timedelta(days=6)
        inc, giorni = _incasso(lid, dal, al)
        ore, costo, _ = _personale(lid, dal, al)
        netto = inc / (1 + iva / 100)
        serie.append({'dal': dal.isoformat(), 'al': al.isoformat(), 'incasso': round(inc, 2), 'giorni': giorni,
                      'ore': round(ore, 1), 'personale': round(costo / netto * 100, 1) if netto and costo else None,
                      'chiusure': ChiusuraRete.query.filter(ChiusuraRete.locale_id == lid, ChiusuraRete.giorno >= dal,
                                                            ChiusuraRete.giorno <= al).count()})

    # food cost: un punto per ogni coppia di inventari chiusi consecutivi (gli ultimi sei)
    chiusi = (InventarioRete.query.filter_by(locale_id=lid, chiuso=True)
              .order_by(InventarioRete.giorno.desc()).limit(7).all())[::-1]
    food = []
    for a, b in zip(chiusi, chiusi[1:]):
        d = diagnosi(locale, a, b)
        if d['food_cost_reale'] is not None:
            food.append({'dal': d['dal'], 'al': d['al'], 'vero': d['food_cost_reale'], 'ricette': d['food_cost_teorico'],
                         'consumo': d['voci']['consumo']['punti']})

    # giorni della settimana: incasso medio delle ultime 4 settimane
    per_giorno = defaultdict(list)
    dal4 = oggi - timedelta(days=28)
    for g, tot in (db.session.query(VenditaRete.giorno, db.func.sum(VenditaRete.incasso))
                   .filter(VenditaRete.locale_id == lid, VenditaRete.giorno >= dal4, VenditaRete.giorno < oggi)
                   .group_by(VenditaRete.giorno).all()):
        per_giorno[g.weekday()].append(float(tot or 0))
    settimana = [{'giorno': GIORNI[k], 'incasso': round(sum(v) / len(v), 2) if v else 0} for k, v in
                 ((k, per_giorno.get(k, [])) for k in range(7))]

    # piatti più venduti negli ultimi 7 giorni, col nome del ricettario quando c'è
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    nomi_ric = {r.id: r.nome for r in RicettaRete.query.filter_by(locale_id=lid).all()}
    from services import vendite as V
    righe = V.vendite(lid, oggi - timedelta(days=7), oggi - timedelta(days=1))
    quando = 'ultimi 7 giorni'
    if not righe:
        # niente cassa giorno per giorno nell'ultima settimana: l'ultimo report di periodo, dicendo quale
        r = ReportCassa.query.filter_by(locale_id=lid).order_by(ReportCassa.al.desc()).first()
        if r:
            righe = V.righe_report(r, V.unioni(lid))
            quando = f'dal {r.dal.day} {MESI[r.dal.month - 1]} al {r.al.day} {MESI[r.al.month - 1]}'
    piatti = defaultdict(lambda: [0.0, 0.0])
    for v in righe:
        al = alias.get(v.voce)
        if al and al.ignorata:
            continue
        # il nome del prodotto (già pulito e unito dall'analisi delle vendite), non quello della ricetta:
        # «Coca cola/fanta/sprite», non «Bibita in lattina»
        nome = v.voce_originale or nomi_ric.get(al.ricetta_id if al else None) or v.voce
        piatti[nome][0] += v.quantita
        piatti[nome][1] += v.incasso or 0
    top = sorted(({'nome': k, 'quantita': round(q), 'incasso': round(e, 2)} for k, (q, e) in piatti.items()),
                 key=lambda x: -x['quantita'])[:8]

    return {'settimane': serie, 'food_cost': food, 'giorni_settimana': settimana, 'piatti': top, 'piatti_quando': quando,
            'obiettivo': float((locale.impostazioni or {}).get('obiettivo', 30))}
