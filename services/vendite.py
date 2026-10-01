"""Le vendite di un locale, da qualunque parte arrivino.

Ci sono due forme:
  - giorno per giorno (report di un giorno, cassa SumUp collegata) → VenditaRete
  - blocchi di periodo (report di più giorni senza il giorno di ogni vendita,
    il «product sales report» di SumUp) → ReportCassa + VenditaPeriodo

Un blocco non si divide sui giorni, per non inventare numeri: in un intervallo
conta solo se ci sta per intero. Così un report scaricato settimana per settimana
fa le settimane, e uno scaricato da un inventario all'altro fa il food cost.
I blocchi che scavalcano l'intervallo si dicono (`a_cavallo`), non si spalmano.
"""
from types import SimpleNamespace

from models import db, ReportCassa, UnioneVoce, VenditaPeriodo, VenditaRete

CAMPI = ('quantita', 'incasso', 'netto', 'iva', 'sconti', 'costo', 'margine', 'resi_quantita', 'resi_incasso')


def varianti(v):
    """I modi in cui la cassa scrive la voce di una riga («Caffe», «Caffè»)."""
    return set(filter(None, (v.nomi or '').split(' · '))) or {v.voce_originale or v.voce}


def unioni(lid):
    """{voce: (canonica, nome)}: le voci che sono lo stesso prodotto scritto in modi diversi (UnioneVoce)."""
    return {u.voce: (u.canonica, u.nome) for u in UnioneVoce.query.filter_by(locale_id=lid).all()}


def _riga(v, dal, al, mappa=None):
    """Una riga di vendita nella forma comune; con `mappa` la voce diventa quella del prodotto unito."""
    voce, nome = (mappa or {}).get(v.voce, (v.voce, v.voce_originale))
    return SimpleNamespace(voce=voce, voce_originale=nome or v.voce_originale, voce_cassa=v.voce, nomi_cassa=varianti(v), dal=dal, al=al,
                           giorno=dal if dal == al else None, **{k: getattr(v, k) for k in CAMPI})


def unisci(righe):
    """Somma le righe con la stessa voce (dopo le unioni): una riga per prodotto."""
    out = {}
    for v in righe:
        x = out.get(v.voce)
        if x is None:
            out[v.voce] = SimpleNamespace(**vars(v))
            out[v.voce].nomi_cassa = set(v.nomi_cassa)
            continue
        x.nomi_cassa |= v.nomi_cassa
        for k in CAMPI:
            a, b = getattr(x, k), getattr(v, k)
            setattr(x, k, None if a is None and b is None else (a or 0) + (b or 0))
    return list(out.values())


def righe_report(r, mappa=None):
    """Le voci di un report di periodo, con le unioni applicate e sommate."""
    return unisci([_riga(v, r.dal, r.al, mappa) for v in r.righe])


def vendite(lid, dal=None, al=None, unite=True):
    """Le righe di vendita tra dal e al compresi: i giorni, e i blocchi che ci stanno per intero.
    Ogni riga ha voce, voce_originale, dal, al, giorno (None per un blocco) e i CAMPI.
    Con `unite` (sempre, tranne che per l'analisi stessa) le voci doppie si leggono come il loro prodotto."""
    m = unioni(lid) if unite else None
    q = VenditaRete.query.filter(VenditaRete.locale_id == lid)
    p = VenditaPeriodo.query.filter(VenditaPeriodo.locale_id == lid)
    if dal:
        q, p = q.filter(VenditaRete.giorno >= dal), p.filter(VenditaPeriodo.dal >= dal)
    if al:
        q, p = q.filter(VenditaRete.giorno <= al), p.filter(VenditaPeriodo.al <= al)
    return [_riga(v, v.giorno, v.giorno, m) for v in q.all()] + [_riga(v, v.dal, v.al, m) for v in p.all()]


def a_cavallo(lid, dal, al):
    """I report di periodo che toccano l'intervallo ma non ci stanno per intero: lì non contano."""
    return [r for r in ReportCassa.query.filter(ReportCassa.locale_id == lid, ReportCassa.dal <= al,
                                                ReportCassa.al >= dal).all()
            if not (dal <= r.dal and r.al <= al)]


def incasso(lid, dal, al):
    """(incasso IVA compresa, giorni coperti) tra dal e al compresi."""
    tot = db.session.query(db.func.coalesce(db.func.sum(VenditaRete.incasso), 0.0)).filter(
        VenditaRete.locale_id == lid, VenditaRete.giorno >= dal, VenditaRete.giorno <= al).scalar()
    giorni = db.session.query(VenditaRete.giorno).filter(
        VenditaRete.locale_id == lid, VenditaRete.giorno >= dal, VenditaRete.giorno <= al).distinct().count()
    for r in ReportCassa.query.filter(ReportCassa.locale_id == lid, ReportCassa.dal >= dal, ReportCassa.al <= al).all():
        tot += sum(v.incasso or 0 for v in r.righe)
        giorni += (r.al - r.dal).days + 1
    return float(tot or 0), giorni


def ultima(lid):
    """L'ultimo giorno di vendite caricato, giorni o blocchi."""
    g = db.session.query(db.func.max(VenditaRete.giorno)).filter_by(locale_id=lid).scalar()
    r = db.session.query(db.func.max(ReportCassa.al)).filter_by(locale_id=lid).scalar()
    return max(filter(None, (g, r)), default=None)


def prima(lid):
    g = db.session.query(db.func.min(VenditaRete.giorno)).filter_by(locale_id=lid).scalar()
    r = db.session.query(db.func.min(ReportCassa.dal)).filter_by(locale_id=lid).scalar()
    return min(filter(None, (g, r)), default=None)


def voci(lid):
    """Tutte le voci della cassa mai viste in questo locale, con le doppie unite nel loro prodotto."""
    m = unioni(lid)
    return {m.get(v, (v,))[0] for v in
            {v for (v,) in db.session.query(VenditaRete.voce).filter_by(locale_id=lid).distinct()}
            | {v for (v,) in db.session.query(VenditaPeriodo.voce).filter_by(locale_id=lid).distinct()}}


def sovrapposti(lid, dal, al, tranne=None):
    """Perché non si può caricare un periodo dal…al: un altro report che si accavalla, o giorni già
    caricati uno per uno. Contare due volte le stesse vendite rovinerebbe tutti i numeri. None se va bene."""
    for r in ReportCassa.query.filter(ReportCassa.locale_id == lid, ReportCassa.dal <= al, ReportCassa.al >= dal).all():
        if r.id != tranne:
            return f'c\'è già un report dal {r.dal.strftime("%d/%m/%Y")} al {r.al.strftime("%d/%m/%Y")} che si accavalla'
    g = db.session.query(db.func.min(VenditaRete.giorno), db.func.max(VenditaRete.giorno), db.func.count(db.distinct(VenditaRete.giorno))).filter(
        VenditaRete.locale_id == lid, VenditaRete.giorno >= dal, VenditaRete.giorno <= al).first()
    if g and g[2]:
        return (f'ci sono già {g[2]} {"giorno" if g[2] == 1 else "giorni"} di vendite caricati uno per uno '
                f'tra il {g[0].strftime("%d/%m/%Y")} e il {g[1].strftime("%d/%m/%Y")}')
    return None


def blocco_su_giorni(lid, giorni):
    """Se uno di questi giorni è già dentro un report di periodo, quel report (per non contarlo due volte)."""
    if not giorni:
        return None
    return next((r for r in ReportCassa.query.filter(ReportCassa.locale_id == lid, ReportCassa.dal <= max(giorni),
                                                     ReportCassa.al >= min(giorni)).all()
                 if any(r.dal <= g <= r.al for g in giorni)), None)


def riassunto(r):
    """I totali di un report di periodo, per Managing e Monitoring."""
    s = {k: round(sum(getattr(v, k) or 0 for v in r.righe), 2) for k in CAMPI}
    con_costo = [v for v in r.righe if (v.costo or 0) > 0]
    return {'id': r.id, 'dal': r.dal.isoformat(), 'al': r.al.isoformat(), 'giorni': (r.al - r.dal).days + 1,
            'nome_file': r.nome_file, 'voci': len(r.righe), **s,
            # il margine della cassa vale solo dove in cassa c'è il prezzo d'acquisto: altrove è l'incasso intero
            'voci_con_costo': len(con_costo),
            'margine_con_costo': round(sum(v.margine or 0 for v in con_costo), 2) if con_costo else None,
            'netto_con_costo': round(sum(v.netto or 0 for v in con_costo), 2) if con_costo else None}


MESI = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic']


def _quando(dal, al):
    return f'dal {dal.day} {MESI[dal.month - 1]} al {al.day} {MESI[al.month - 1]} {al.year}'


def base_cassa(lid, dal, al):
    """(righe, «quando») per i numeri che non dipendono dal giorno (cosa si vende, sconti, storni):
    le vendite tra dal e al; se lì non c'è niente, l'ultimo report di periodo, dicendo quale."""
    righe = vendite(lid, dal, al)
    if righe:
        return unisci(righe), 'ultime 4 settimane'
    r = ReportCassa.query.filter_by(locale_id=lid).order_by(ReportCassa.al.desc()).first()
    if not r:
        return [], None
    return righe_report(r, unioni(lid)), 'ultimo report, ' + _quando(r.dal, r.al)


def riferimento(lid, dal, al, iva=10):
    """Quando tra dal e al non c'è cassa (niente giorni, niente report interi), l'ultimo report di periodo
    fa da riferimento: i suoi totali e le medie a settimana, dicendo di quale periodo. None se non c'è."""
    if incasso(lid, dal, al)[1]:
        return None
    r = ReportCassa.query.filter_by(locale_id=lid).order_by(ReportCassa.al.desc()).first()
    if not r:
        return None
    x = riassunto(r)
    if not x['netto'] and x['incasso']:
        x['netto'] = round(x['incasso'] / (1 + iva / 100), 2)      # report senza la colonna dell'incasso senza IVA
    sett = x['giorni'] / 7
    return {**x, 'settimane': round(sett, 1), 'sett_incasso': round(x['incasso'] / sett, 2),
            'sett_netto': round(x['netto'] / sett, 2), 'mese_incasso': round(x['incasso'] / x['giorni'] * 30.44, 2),
            'quando': _quando(r.dal, r.al)}


def medie_report(lid, quanti=8):
    """Incasso medio a settimana di ogni report di periodo, dal più vecchio: la linea quando la cassa arriva a blocchi."""
    reps = ReportCassa.query.filter_by(locale_id=lid).order_by(ReportCassa.al.desc()).limit(quanti).all()[::-1]
    out = []
    for r in reps:
        x = riassunto(r)
        out.append({'dal': x['dal'], 'al': x['al'], 'incasso': x['incasso'], 'sett_incasso': round(x['incasso'] / (x['giorni'] / 7), 2)})
    return out
