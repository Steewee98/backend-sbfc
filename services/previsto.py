"""Il turno previsto: la settimana tipo di ogni persona, scritta dal consulente.

    orario = [{'g': 0-6 (lunedì = 0), 'da': 'HH:MM', 'a': 'HH:MM'}, …]

Più fasce nello stesso giorno per i turni spezzati (12:00-15:00 e 19:00-23:30). Una fascia
che finisce prima di cominciare passa la mezzanotte (19:00-01:00 = 6 ore) e conta per il
giorno in cui comincia, come le timbrature. Da qui escono le ore e il costo previsti
della settimana e del mese, da confrontare con quello che le timbrature dicono davvero.
"""
import calendar
import re
from datetime import timedelta

ORA = re.compile(r'^([01]?\d|2[0-3]):([0-5]\d)$')
MAX_FASCE = 21


def _minuti(h):
    m = ORA.match(h or '')
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def valida(orario):
    """La lista pulita e ordinata, oppure un messaggio d'errore."""
    if orario in (None, ''):
        return []
    if not isinstance(orario, list) or len(orario) > MAX_FASCE:
        return 'Orario non valido'
    out = []
    for f in orario:
        try:
            g = int(f.get('g'))
        except (TypeError, ValueError, AttributeError):
            return 'Giorno non valido'
        da, a = (f.get('da') or '').strip(), (f.get('a') or '').strip()
        if not 0 <= g <= 6 or _minuti(da) is None or _minuti(a) is None:
            return f'Orario non valido: scrivi le ore come 19:00'
        if da == a:
            return 'Una fascia deve durare almeno qualche minuto'
        if ore_fascia({'da': da, 'a': a}) > 16:
            return 'Una fascia non può durare più di 16 ore'
        out.append({'g': g, 'da': da.zfill(5), 'a': a.zfill(5)})
    return sorted(out, key=lambda f: (f['g'], f['da']))


def ore_fascia(f):
    d, a = _minuti(f['da']), _minuti(f['a'])
    return ((a - d) % (24 * 60)) / 60


def ore_giorno(orario, wd):
    return sum(ore_fascia(f) for f in (orario or []) if f['g'] == wd)


def ore_settimana(orario):
    return round(sum(ore_fascia(f) for f in (orario or [])), 2)


def ore_periodo(orario, dal, al):
    """Ore previste tra due date comprese."""
    if not orario:
        return 0.0
    tot, g = 0.0, dal
    while g <= al:
        tot += ore_giorno(orario, g.weekday())
        g += timedelta(days=1)
    return round(tot, 2)


def ore_mese(orario, anno, mese):
    from datetime import date
    return ore_periodo(orario, date(anno, mese, 1), date(anno, mese, calendar.monthrange(anno, mese)[1]))


def riepilogo(persona, oggi):
    """Quello che serve alla scheda della persona: ore e costo previsti a settimana e nel mese in corso."""
    o = persona.orario or []
    ore_s, ore_m = ore_settimana(o), ore_mese(o, oggi.year, oggi.month)
    c = persona.costo_orario
    return {'ore_settimana': ore_s, 'ore_mese': ore_m,
            'costo_settimana': round(ore_s * c, 2) if c is not None else None,
            'costo_mese': round(ore_m * c, 2) if c is not None else None}
