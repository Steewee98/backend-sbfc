"""Il dossier di un locale per Monitoring: le sette schede del prototipo della console
(Diagnosi, Parametri, Personale, Magazzino, Dotazione, Storia, Contratto) sui dati veri.

Quello che nasce dai dati (cassa, fatture, timbrature, inventari) si calcola qui.
Quello che sa solo il consulente (contratto, dotazione installata, storia, le note e le
mosse sugli indicatori) lo scrive in Managing e sta in scheda['dossier'] e in EventoRete.

Le tabelle delle «misure» hanno celle di testo già formattate («18,4 kg», «+12%»):
la console le disegna con lo stesso motore di grafici del prototipo.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from models import (db, AliasVendita, ArticoloRete, ChiusuraRete, EventoRete, FatturaRete, InventarioRete, LocaleRete,
                    MovimentoRete, PersonaLocale, RicettaRete, ReportCassa, RigaFattura, TurnoRete, UnioneVoce, VenditaRete)

GIORNI = ['lun', 'mar', 'mer', 'gio', 'ven', 'sab', 'dom']
MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre',
        'ottobre', 'novembre', 'dicembre']

# ── i campi che il consulente compila in Managing: percorso in scheda → tipo ──
CAMPI = {
    'locale.indirizzo': 'testo', 'locale.coperti': 'numero', 'locale.tavoli': 'numero',
    'numeri.cassa_marca': 'testo', 'numeri.incasso': 'numero', 'formalita.ref_nome': 'testo', 'formalita.ref_tel': 'testo',
    'dossier.zona': 'testo', 'dossier.titolare': 'testo', 'dossier.telefono': 'testo', 'dossier.in_formazione': 'testo',
    'dossier.pacchetto': 'testo', 'dossier.canone': 'numero', 'dossier.dal': 'data', 'dossier.voto_titolare': 'numero',
    'dossier.prossima_visita': 'data', 'dossier.bollino': ('auto', 'attivo', 'sospeso'),
}
PACCHETTI = ['Avvio', 'Mantenimento', 'Rilancio']

# ── gli strumenti: cosa raccolgono e quali indicatori alimentano ──
STRUMENTI = {
    'cassa': {'ico': 'point_of_sale', 'nome': 'Cassa collegata', 'freq': 'ogni giorno',
              'raccoglie': 'Le vendite piatto per piatto: quantità e incasso di ogni voce.',
              'alimenta': 'Food cost, incasso, costo del personale, incasso per ora, vendite coperte dal ricettario'},
    'fatture': {'ico': 'receipt_long', 'nome': 'Fatture dei fornitori', 'freq': 'a ogni fattura',
                'raccoglie': 'Ogni riga di acquisto con quantità e prezzo: XML dal cassetto fiscale, PDF e foto delle bolle.',
                'alimenta': 'Food cost, acquisti sull\'incasso, rincari, sprechi, consegne con problemi'},
    'timbra': {'ico': 'badge', 'nome': 'Tag «Timbra qui» sulla cassa', 'freq': 'a ogni turno',
               'raccoglie': 'Entrata e uscita di ogni persona col suo PIN, dal telefono, senza app.',
               'alimenta': 'Costo del personale, incasso per ora lavorata, turni senza uscita'},
    'chiusura': {'ico': 'checklist', 'nome': 'Chiusura della sera', 'freq': 'ogni sera',
                 'raccoglie': 'Chi chiude segna celle, gas, luci, cassa e porte, con una nota.',
                 'alimenta': 'Chiusure segnate'},
    'inventario': {'ico': 'inventory_2', 'nome': 'Inventari e tag di magazzino', 'freq': 'ogni settimana',
                   'raccoglie': 'La conta della merce del consulente e gli scarti registrati dal tag dello scaffale.',
                   'alimenta': 'Food cost vero, consumo oltre ricetta, sprechi'},
    'sonde': {'ico': 'thermostat', 'nome': 'Sonde di temperatura', 'freq': 'ogni quindici minuti',
              'raccoglie': 'Temperatura di celle e frigo, allarmi di notte, registro HACCP.',
              'alimenta': 'Temperature di celle e frigo (fase 3)'},
    'recensioni': {'ico': 'reviews', 'nome': 'Placca NFC recensioni', 'freq': 'ogni giorno',
                   'raccoglie': 'Tap sulla placca e recensioni lasciate sul profilo Google.',
                   'alimenta': 'Voto delle recensioni (fase 3)'},
    'menu': {'ico': 'qr_code_2', 'nome': 'Menù digitale e placche ai tavoli', 'freq': 'sempre',
             'raccoglie': 'Menù con foto e lingue, Wi-Fi e recensioni dal tavolo.',
             'alimenta': 'Nessun indicatore: serve ai clienti'},
}
SORGENTE = {'food': ['inventario', 'fatture', 'cassa'], 'teo': ['fatture', 'cassa'], 'oltre': ['inventario', 'cassa'],
            'acq': ['fatture', 'cassa'], 'rinc': ['fatture'], 'spr': ['inventario', 'fatture'],
            'pers': ['timbra', 'cassa'], 'persp': ['timbra', 'cassa'], 'prev': ['timbra'],
            'eora': ['timbra', 'cassa'], 'turni': ['timbra'], 'inc': ['cassa'],
            'ric': ['cassa'], 'sco': ['cassa'], 'sconti': ['cassa'], 'storni': ['cassa'], 'chk': ['chiusura'], 'inv': ['inventario'], 'cassa': ['cassa'],
            'cons': ['fatture'], 'doc': ['fatture'], 'rec': ['recensioni'], 'temp': ['sonde']}


# ── formati italiani per le celle ──
def dec(v, c=1):
    return f'{v:,.{c}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def eur(v, c=0):
    return dec(v or 0, c) + ' €'


def pc(v, segno=False):
    return ('+' if segno and v > 0 else '') + dec(v, 1) + '%'


def qta(v, u):
    u = {'l': 'L'}.get(u, u or '')
    return f'{dec(v, 1)} {u}'.strip()


def giorno_it(g):
    if not g:
        return None
    if isinstance(g, str):
        g = date.fromisoformat(g[:10])
    return f'{g.day} {MESI[g.month - 1]}' + (f' {g.year}' if g.year != date.today().year else '')


def _campo(scheda, percorso):
    sez, k = percorso.split('.', 1)
    return (scheda.get(sez) or {}).get(k)


def _utc(g, ora=5):
    from services.quadro import ROMA
    from datetime import timezone
    return datetime(g.year, g.month, g.day, ora, tzinfo=ROMA).astimezone(timezone.utc).replace(tzinfo=None)


def _giorno_turno(t):
    from services.quadro import ora_locale
    return (ora_locale(t.inizio) - timedelta(hours=5)).date()


# ─────────────────────────────────────────────────────────────────────────────

def dotazione(l, scheda, oggi):
    """Cosa è installato: dai dati quando si vede (la cassa arriva, lo staff timbra),
    altrimenti da quello che ha segnato il consulente. Il consulente ha sempre l'ultima parola."""
    lid, man = l.id, ((scheda.get('dossier') or {}).get('dotazione') or {})
    imp = l.impostazioni or {}
    from services.vendite import ultima as ultima_vendita
    ultima = ultima_vendita(lid)
    n_fatt = FatturaRete.query.filter_by(locale_id=lid).count()
    con_pin = PersonaLocale.query.filter(PersonaLocale.locale_id == lid, PersonaLocale.attiva.is_(True),
                                         PersonaLocale.pin_hash.isnot(None)).count()
    turni = TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.inizio >= _utc(oggi - timedelta(days=14))).count()
    chiusure = ChiusuraRete.query.filter(ChiusuraRete.locale_id == lid, ChiusuraRete.giorno >= oggi - timedelta(days=14)).count()
    inventari = InventarioRete.query.filter_by(locale_id=lid, chiuso=True).count()
    marca = _campo(scheda, 'numeri.cassa_marca')
    sumup = imp.get('sumup') or {}

    auto = {
        'cassa': ('attivo', f"SumUp collegata ({sumup.get('nome') or sumup.get('esercente')}), ultima giornata {giorno_it(ultima)}")
        if sumup.get('esercente') and ultima else
        ('attivo', f'Report caricato dal consulente{" · " + marca if marca else ""}, ultima giornata {giorno_it(ultima)}') if ultima else
        ('da sistemare', f'Da collegare{": " + marca if marca else ""}'),
        'fatture': ('attivo', f'{n_fatt} documenti caricati') if n_fatt else ('da sistemare', 'Nessuna fattura caricata'),
        'timbra': ('attivo', f'{con_pin} persone col PIN, {turni} turni nelle ultime due settimane') if turni else
        ('da sistemare', f'{con_pin} persone col PIN, nessun turno timbrato') if con_pin else ('assente', 'Nessuna persona col PIN'),
        'chiusura': ('attivo', f'{chiusure} sere segnate nelle ultime due settimane') if chiusure else ('da sistemare', 'Nessuna chiusura segnata'),
        'inventario': ('attivo', f'{inventari} inventari chiusi') if inventari else ('da sistemare', 'Nessun inventario chiuso'),
        'sonde': ('assente', 'Fase 3'),
        'recensioni': ('assente', 'Non ancora installata'),
        'menu': ('assente', 'Non ancora installato'),
    }
    out = []
    for k, s in STRUMENTI.items():
        stato, desc = auto[k]
        m = man.get(k) or {}
        out.append({'id': k, **s, 'stato': m.get('stato') or stato, 'descrizione': m.get('nota') or desc,
                    'automatico': not m.get('stato'), 'dai_dati': desc})
    return out


def storia(l):
    """Gli eventi scritti dal consulente, più le tappe che si leggono dai dati."""
    lid = l.id
    ev = [{**e.to_dict(), 'auto': False} for e in EventoRete.query.filter_by(locale_id=lid).all()]
    auto = []
    if l.created_at:
        auto.append((l.created_at.date(), 'Ingresso nella rete', True, 'Il locale entra nella Rete SB.'))
    f = FatturaRete.query.filter_by(locale_id=lid).order_by(FatturaRete.created_at).first()
    if f:
        auto.append((f.created_at.date(), 'Fatture', False, 'Caricate le prime fatture dei fornitori.'))
    from services.vendite import prima
    v = prima(lid)
    if v:
        auto.append((v, 'Cassa', False, 'Prima giornata di vendite letta dalla cassa.'))
    i = InventarioRete.query.filter_by(locale_id=lid, chiuso=True).order_by(InventarioRete.giorno).all()
    if i:
        auto.append((i[0].giorno, 'Inventario', False, 'Primo inventario chiuso.'))
    if len(i) >= 2:
        auto.append((i[1].giorno, 'Diagnosi', True, 'Secondo inventario: da qui c\'è la diagnosi del food cost.'))
    t = TurnoRete.query.filter_by(locale_id=lid).order_by(TurnoRete.inizio).first()
    if t:
        auto.append((_giorno_turno(t), 'Timbrature', False, 'Primo turno timbrato dal tag sulla cassa.'))
    ev += [{'id': None, 'giorno': g.isoformat(), 'tipo': tipo, 'testo': testo, 'chiave': k, 'autore': None, 'auto': True}
           for g, tipo, k, testo in auto]
    ev.sort(key=lambda e: (e['giorno'], not e['auto']), reverse=True)
    return ev


def personale(l, oggi, prezzo_netto):
    from services.quadro import _personale
    lid = l.id
    al, dal = oggi - timedelta(days=1), oggi - timedelta(days=7)
    ore, costo, senza = _personale(lid, dal, al)
    persone = PersonaLocale.query.filter_by(locale_id=lid, attiva=True).all()
    # quante persone in turno, sera per sera: la media delle ultime quattro settimane
    per_giorno = defaultdict(set)
    ore_giorno = defaultdict(float)
    for t in TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.inizio >= _utc(oggi - timedelta(days=28)),
                                    TurnoRete.inizio < _utc(oggi)).all():
        g = _giorno_turno(t)
        per_giorno[g].add(t.persona_id)
        if t.fine:
            ore_giorno[g] += t.ore()
    medie = []
    for k in range(7):
        gg = [g for g in per_giorno if g.weekday() == k]
        medie.append(round(sum(len(per_giorno[g]) for g in gg) / len(gg), 1) if gg else 0)
    per_persona = defaultdict(float)
    for t in TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.inizio >= _utc(dal), TurnoRete.inizio < _utc(oggi),
                                    TurnoRete.fine.isnot(None)).all():
        per_persona[t.persona_id] += t.ore()
    nomi = {p.id: p for p in persone}
    chiusure = []
    for c in ChiusuraRete.query.filter(ChiusuraRete.locale_id == lid, ChiusuraRete.giorno >= oggi - timedelta(days=14)) \
            .order_by(ChiusuraRete.giorno.desc()).all():
        from services.quadro import ora_locale
        p = db.session.get(PersonaLocale, c.persona_id) if c.persona_id else None
        manca = [k for k in ('celle', 'gas', 'luci', 'cassa', 'porte') if not (c.voci or {}).get(k)]
        chiusure.append({'giorno': c.giorno.isoformat(), 'chi': p.nome if p else '—',
                         'ora': ora_locale(c.ora).strftime('%H:%M') if c.ora else None, 'manca': manca,
                         'nota': (c.voci or {}).get('nota') or ''})
    # il turno previsto: quante persone sera per sera e quanto costano la settimana e il mese
    from services.previsto import ore_giorno as og, ore_periodo, riepilogo
    from services.quadro import previsto
    sera_prevista = [sum(1 for p in persone if p.orario and og(p.orario, k) > 0) for k in range(7)]
    # il costo diviso per reparto: quanto costa la cucina, quanto la sala
    from services.squadra import REPARTI
    rep = defaultdict(lambda: {'persone': 0, 'ore': 0.0, 'costo': 0.0, 'ore_previste': 0.0, 'costo_previsto': 0.0})
    for p in persone:
        if p.ruolo == 'titolare' and not per_persona.get(p.id) and not p.orario:
            continue
        r = rep[p.reparto or '']
        r['persone'] += 1
        r['ore'] += per_persona.get(p.id, 0)
        r['costo'] += per_persona.get(p.id, 0) * (p.costo_orario or 0)
        if p.orario:
            h = ore_periodo(p.orario, oggi, oggi + timedelta(days=6))
            r['ore_previste'] += h
            r['costo_previsto'] += h * (p.costo_orario or 0)
    reparti = sorted(({'id': k, 'nome': REPARTI.get(k, 'Reparto da indicare'), **{a: round(b, 1) for a, b in v.items()}}
                      for k, v in rep.items()), key=lambda x: -(x['costo_previsto'] or x['costo']))
    return {
        'reparti': reparti,
        'organico': sum(1 for p in persone if p.ruolo != 'titolare'), 'ore': round(ore, 1), 'costo': round(costo),
        'costo_ora': round(costo / ore, 2) if ore and costo else None, 'senza_costo_orario': len(senza),
        'sera': medie, 'sera_prevista': sera_prevista if any(sera_prevista) else None,
        'previsto': previsto(lid, dal, al), 'prossima': previsto(lid, oggi, oggi + timedelta(days=6), mese_di=oggi),
        'persone': sorted(({'nome': p.nome, 'ruolo': p.ruolo, 'mansione': p.mansione, 'reparto': p.reparto,
                            'contratto': p.contratto, 'ore_contratto': p.ore_contratto,
                            'ore': round(per_persona.get(p.id, 0), 1),
                            'ore_previste': round(ore_periodo(p.orario, dal, al), 1) if p.orario else None,
                            'orario': p.orario or [], 'costo_mese': riepilogo(p, oggi)['costo_mese'] if p.orario else None,
                            'costo_orario': p.costo_orario, 'pin': bool(p.pin_hash)} for p in persone),
                          key=lambda x: -max(x['ore'], x['ore_previste'] or 0)),
        'chiusure': chiusure,
        '_ore_giorno': ore_giorno,
    }


# prezzi plausibili per unità: fuori da qui quasi sempre è il fattore di conversione sbagliato
PREZZO_PLAUSIBILE = {'kg': (0.3, 90), 'l': (0.3, 70), 'pz': (0.05, 60)}


def prezzo_strano(a):
    lo, hi = PREZZO_PLAUSIBILE.get(a.unita, (0, 1e9))
    return a.prezzo is not None and not lo <= a.prezzo <= hi


def giacenze(lid, oggi):
    """La merce che dovrebbe esserci oggi, articolo per articolo:
    ultimo inventario + entrate dalle fatture (e carichi) − uscite delle vendite secondo le ricette − scarti.
    Senza inventario si parte da zero e conta solo quello che è entrato e uscito."""
    art = {a.id: a for a in ArticoloRete.query.filter_by(locale_id=lid).all()}
    inv = InventarioRete.query.filter_by(locale_id=lid, chiuso=True).order_by(InventarioRete.giorno.desc()).first()
    base_g = inv.giorno if inv else None
    base = {r.articolo_id: r.quantita for r in (inv.righe if inv else [])}
    entrate, speso, ultimo = defaultdict(float), defaultdict(float), {}
    q = (RigaFattura.query.join(FatturaRete)
         .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.isnot(None), RigaFattura.quantita_articolo.isnot(None),
                 db.func.coalesce(FatturaRete.tipo, '') != 'DDT'))
    if base_g:
        q = q.filter(FatturaRete.data > base_g)
    for r in q.all():
        sg = r.fattura.segno if r.fattura.segno is not None else 1
        entrate[r.articolo_id] += r.quantita_articolo * sg
        speso[r.articolo_id] += (r.totale or 0) * sg
        if sg > 0 and (r.articolo_id not in ultimo or r.fattura.data > ultimo[r.articolo_id]):
            ultimo[r.articolo_id] = r.fattura.data
    carichi, scarti = defaultdict(float), defaultdict(float)
    mq = MovimentoRete.query.filter(MovimentoRete.locale_id == lid)
    if base_g:
        mq = mq.filter(MovimentoRete.giorno > base_g)
    for m in mq.all():
        (carichi if m.tipo == 'carico' else scarti)[m.articolo_id] += m.quantita
    # le uscite: le vendite dopo l'inventario, per le ricette
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}
    ricette = {r.id: r for r in RicettaRete.query.filter_by(locale_id=lid).all()}
    uscite = defaultdict(float)
    from services.vendite import vendite
    for v in vendite(lid, base_g + timedelta(days=1) if base_g else None):
        a = alias.get(v.voce)
        ric = ricette.get(a.ricetta_id) if a and a.ricetta_id and not a.ignorata else None
        if ric:
            for rr in ric.righe:
                uscite[rr.articolo_id] += v.quantita * rr.quantita / (ric.resa or 1)
    righe = []
    for aid, a in art.items():
        if not any(x.get(aid) for x in (base, entrate, carichi, scarti, uscite)) and aid not in base:
            continue
        stima = base.get(aid, 0) + entrate[aid] + carichi[aid] - uscite[aid] - scarti[aid]
        righe.append({'articolo_id': aid, 'nome': a.nome, 'unita': a.unita, 'prezzo': a.prezzo, 'prezzo_strano': prezzo_strano(a),
                      'inventario': base.get(aid), 'entrate': round(entrate[aid] + carichi[aid], 3), 'speso': round(speso[aid], 2),
                      'uscite': round(uscite[aid], 3), 'scarti': round(scarti[aid], 3), 'stima': round(stima, 3),
                      'valore': round(max(stima, 0) * (a.prezzo or 0), 2), 'ultimo_acquisto': ultimo[aid].isoformat() if aid in ultimo else None,
                      'negativa': stima < -0.001})
    righe.sort(key=lambda x: -x['valore'])
    return {'da': base_g.isoformat() if base_g else None, 'righe': righe,
            'valore': round(sum(r['valore'] for r in righe), 2), 'entrate_euro': round(sum(speso.values()), 2)}


def magazzino(l, dg, oggi=None):
    lid = l.id
    from services.quadro import giorno_di_lavoro
    oggi = oggi or giorno_di_lavoro()
    art = {a.id: a for a in ArticoloRete.query.filter_by(locale_id=lid).all()}
    ult = InventarioRete.query.filter_by(locale_id=lid, chiuso=True).order_by(InventarioRete.giorno.desc()).first()
    aperto = InventarioRete.query.filter_by(locale_id=lid, chiuso=False).order_by(InventarioRete.giorno.desc()).first()
    conteggio = [{'nome': art[r.articolo_id].nome, 'quantita': r.quantita, 'unita': art[r.articolo_id].unita,
                  'prezzo': art[r.articolo_id].prezzo} for r in (ult.righe if ult else []) if r.articolo_id in art]
    conteggio.sort(key=lambda x: -(x['quantita'] * (x['prezzo'] or 0)))
    scarti = [{'giorno': m.giorno.isoformat(), 'nome': art[m.articolo_id].nome if m.articolo_id in art else '?',
               'quantita': m.quantita, 'unita': art[m.articolo_id].unita if m.articolo_id in art else '',
               'valore': round(m.quantita * ((art.get(m.articolo_id).prezzo if art.get(m.articolo_id) else 0) or 0), 2),
               'tipo': m.tipo, 'nota': m.nota or ''}
              for m in MovimentoRete.query.filter_by(locale_id=lid).order_by(MovimentoRete.giorno.desc()).limit(12).all()]
    # le ultime entrate dalle fatture, e quello che non entra perché non è collegato
    entrate = [{'giorno': r.fattura.data.isoformat(), 'fornitore': r.fattura.fornitore, 'descrizione': r.descrizione,
                'articolo': art[r.articolo_id].nome if r.articolo_id in art else None,
                'quantita': round((r.quantita_articolo or 0) * (r.fattura.segno or 1), 3),
                'unita': art[r.articolo_id].unita if r.articolo_id in art else (r.unita or ''), 'totale': r.totale}
               for r in (RigaFattura.query.join(FatturaRete)
                         .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.isnot(None),
                                 db.func.coalesce(FatturaRete.tipo, '') != 'DDT')
                         .order_by(FatturaRete.data.desc(), RigaFattura.id.desc()).limit(12).all())]
    fuori = (RigaFattura.query.join(FatturaRete)
             .filter(FatturaRete.locale_id == lid, RigaFattura.articolo_id.is_(None), RigaFattura.quantita.isnot(None),
                     RigaFattura.ignorata.isnot(True), db.func.coalesce(FatturaRete.tipo, '') != 'DDT').all())
    return {'ultimo': ult.giorno.isoformat() if ult else None, 'aperto': aperto.giorno.isoformat() if aperto else None,
            'conteggio': conteggio[:15], 'movimenti': scarti, 'giacenze': giacenze(lid, oggi), 'entrate': entrate,
            'da_collegare': {'prodotti': len({r.chiave for r in fuori}), 'righe': len(fuori),
                             'euro': round(sum((r.totale or 0) * (r.fattura.segno or 1) for r in fuori), 2)},
            'prezzi_strani': [{'nome': a.nome, 'prezzo': a.prezzo, 'unita': a.unita} for a in art.values() if prezzo_strano(a)],
            'consumo': [{'nome': a['nome'], 'unita': a['unita'], 'teorico': a['teorico'], 'reale': a['reale'],
                         'oltre_pct': a['oltre_pct'], 'euro': a['consumo']} for a in (dg['articoli'] if dg else [])
                        if a['teorico'] or a['reale']][:15]}


def _giudizio(p, alto=8, medio=3):
    return 'alto' if p is not None and p > alto else 'da guardare' if p is not None and p > medio else 'in linea'


def cause_food(l, dg, note):
    """La scomposizione del food cost in cause, ognuna con la prova e la mossa (come nel prototipo)."""
    if not dg:
        return None
    voci, arts = dg['voci'], dg['articoli']
    periodo = f"dal {giorno_it(dg['dal'])} al {giorno_it(dg['al'])}"
    cause = []
    rinc = sorted((a for a in arts if a['prezzo'] > 0.5), key=lambda a: -a['prezzo'])[:3]
    if (voci['prezzo']['punti'] or 0) > 0.05 and rinc:
        cause.append({'id': 'prezzo', 'titolo': 'I prezzi d\'acquisto sono saliti', 'punti': voci['prezzo']['punti'],
                      'euro': voci['prezzo']['euro'],
                      'dettaglio': '; '.join(f"{a['nome']} da {dec(a['prezzo_prima'], 2)} a {dec(a['prezzo_periodo'], 2)} € al {a['unita']}"
                                             for a in rinc) + '.',
                      'prova': f'Fatture {periodo} confrontate con l\'ultimo prezzo prima del periodo',
                      'mossa': 'Rinegoziare col fornitore o chiedere il listino del mese prima; valutare un secondo fornitore.'})
    oltre = [a for a in arts if a['consumo'] > 1 and a['oltre_pct'] is not None][:3]
    if (voci['consumo']['punti'] or 0) > 0.05 and oltre:
        cause.append({'id': 'consumo', 'titolo': 'Se ne usa più di quanto dicono le ricette', 'punti': voci['consumo']['punti'],
                      'euro': voci['consumo']['euro'],
                      'dettaglio': '; '.join(f"{a['nome']}: {qta(a['reale'], a['unita'])} usati contro {qta(a['teorico'], a['unita'])} "
                                             f"giustificati dalle vendite ({pc(a['oltre_pct'], True)})" for a in oltre) + '.',
                      'prova': f'Inventari {periodo}, acquisti e vendite della cassa moltiplicate per le ricette',
                      'mossa': 'Tre giorni di pesatura in postazione sui piatti che usano questi ingredienti; rivedere le grammature con la cucina.'})
    sc = sorted((a for a in arts if a['scarto'] > 0.5), key=lambda a: -a['scarto'])[:3]
    if (voci['scarto']['punti'] or 0) > 0.05 and sc:
        cause.append({'id': 'scarto', 'titolo': 'Gli scarti registrati', 'punti': voci['scarto']['punti'], 'euro': voci['scarto']['euro'],
                      'dettaglio': '; '.join(f"{a['nome']}: {qta(a['scarti'], a['unita'])} buttati ({eur(a['scarto'])})" for a in sc) + '.',
                      'prova': 'Registro degli scarichi del periodo',
                      'mossa': 'Ordini più piccoli e più frequenti sugli articoli che scadono; etichette con la data di apertura.'})
    for c in cause:
        n = (note.get('food.' + c['id']) or {})
        if n.get('mossa'):
            c['mossa'] = n['mossa']
        if n.get('nota'):
            c['nota'] = n['nota']
    return {'sintesi': dg['frase'], 'cause': cause, 'avvisi': dg['avvisi'], 'periodo': periodo,
            'scostamento': round((dg['food_cost_reale'] or 0) - dg['obiettivo'], 1),
            'reale': dg['food_cost_reale'], 'teorico': dg['food_cost_teorico'], 'obiettivo': dg['obiettivo']}


def misure(l, oggi, dg, pers, mag, extra):
    """Le tabelle dietro ogni indicatore, nel formato del motore di grafici del prototipo."""
    from services.quadro import _incasso
    lid, iva = l.id, float((l.impostazioni or {}).get('iva', 10))
    al, dal4 = oggi - timedelta(days=1), oggi - timedelta(days=28)
    M = defaultdict(list)

    if dg:
        righe = [[a['nome'], qta(a['teorico'], a['unita']), qta(a['reale'], a['unita']),
                  pc(a['oltre_pct'], True) if a['oltre_pct'] is not None else '—', _giudizio(a['oltre_pct'])]
                 for a in dg['articoli'] if a['teorico'] or a['reale']][:8]
        blocco = {'titolo': 'Consumo reale contro teorico, tra gli ultimi due inventari', 'verso': 'basso',
                  'nota': 'Il reale è inventario iniziale + acquisti − inventario finale. Il teorico è quanto sarebbe dovuto uscire per i piatti venduti in cassa.',
                  'colonne': ['Ingrediente', 'Teorico', 'Reale', 'Scostamento', 'Giudizio'], 'righe': righe}
        if righe:
            M['food'].append(blocco)
            M['oltre'].append(blocco)
        prezzi = [[a['nome'], dec(a['prezzo_prima'], 2) + ' €', dec(a['prezzo_periodo'], 2) + ' €',
                   pc((a['prezzo_periodo'] / a['prezzo_prima'] - 1) * 100, True)]
                  for a in dg['articoli'] if a['prezzo_prima']][:8]
        if prezzi:
            M['food'].append({'titolo': 'Prezzo per unità: prima del periodo contro il periodo', 'verso': 'basso',
                              'nota': 'Preso dalle fatture caricate. È il controllo che nessun locale fa da solo.',
                              'colonne': ['Ingrediente', 'Prima', 'Nel periodo', 'Variazione'], 'righe': prezzi})

    # food cost delle ricette, piatto per piatto
    from services.foodcost import costo_ricetta
    rr = []
    for r in RicettaRete.query.filter_by(locale_id=lid).all():
        c, _ = costo_ricetta(r)
        if c is not None and r.prezzo:
            rr.append((r.nome, r.prezzo, c, c / (r.prezzo / (1 + iva / 100)) * 100))
    rr.sort(key=lambda x: -x[3])
    if rr:
        M['teo'].append({'titolo': 'Food cost delle ricette, piatto per piatto', 'verso': 'basso',
                         'nota': 'Costo degli ingredienti ai prezzi dell\'ultima fattura, sul prezzo di menù senza IVA.',
                         'colonne': ['Piatto', 'Prezzo', 'Costo', 'Food cost'],
                         'righe': [[n, dec(p, 2) + ' €', dec(c, 2) + ' €', pc(f)] for n, p, c, f in rr[:10]]})

    # acquisti per fornitore, 4 settimane
    per_forn = defaultdict(lambda: [0, 0.0])
    for f in FatturaRete.query.filter(FatturaRete.locale_id == lid, FatturaRete.data >= dal4, FatturaRete.data <= al,
                                      db.func.coalesce(FatturaRete.tipo, '') != 'DDT').all():
        per_forn[f.fornitore][0] += 1
        per_forn[f.fornitore][1] += (f.imponibile or 0) * (f.segno if f.segno is not None else 1)
    tot = sum(v[1] for v in per_forn.values()) or 1
    if per_forn:
        M['acq'].append({'titolo': 'Acquisti per fornitore, ultime quattro settimane',
                         'nota': 'Imponibile delle fatture, note di credito in meno. Le bolle non contano: gli importi arrivano con la fattura.',
                         'colonne': ['Fornitore', 'Documenti', 'Spesa', 'Peso'],
                         'righe': [[k, str(n), eur(v), pc(v / tot * 100)] for k, (n, v) in
                                   sorted(per_forn.items(), key=lambda x: -x[1][1])[:10]]})
    if extra.get('rincari'):
        M['rinc'].append({'titolo': 'Prezzo per unità: ultimi 30 giorni contro prima', 'verso': 'basso',
                          'nota': 'Ultimo prezzo pagato per ogni articolo collegato. Pesati sulla spesa, fanno la variazione media.',
                          'colonne': ['Articolo', 'Variazione', 'Giudizio'],
                          'righe': [[n, pc(v, True), _giudizio(v, 8, 3)] for n, v in extra['rincari'][:10]]})
    sc = [m for m in mag['movimenti'] if m['tipo'] == 'scarto']
    if sc:
        M['spr'].append({'titolo': 'Scarti registrati, gli ultimi',
                         'nota': 'Ogni scarto passato sul tag dello scaffale o segnato dal consulente, con il motivo.',
                         'colonne': ['Articolo', 'Quantità', 'Valore', 'Motivo'],
                         'righe': [[m['nome'], qta(m['quantita'], m['unita']), eur(m['valore'], 2), m['nota'] or '—'] for m in sc[:10]]})

    # personale, giorno per giorno della settimana
    inc_g = defaultdict(list)
    for g, t in (db.session.query(VenditaRete.giorno, db.func.sum(VenditaRete.incasso))
                 .filter(VenditaRete.locale_id == lid, VenditaRete.giorno >= dal4, VenditaRete.giorno <= al)
                 .group_by(VenditaRete.giorno).all()):
        inc_g[g.weekday()].append(float(t or 0) / (1 + iva / 100))
    ore_g = defaultdict(list)
    for g, h in pers['_ore_giorno'].items():
        ore_g[g.weekday()].append(h)
    righe_p, righe_e = [], []
    for k in range(7):
        i = sum(inc_g[k]) / len(inc_g[k]) if inc_g[k] else 0
        h = sum(ore_g[k]) / len(ore_g[k]) if ore_g[k] else 0
        righe_p.append([GIORNI[k], dec(pers['sera'][k], 1), dec(h, 1) + ' h', eur(i)])
        righe_e.append([GIORNI[k], eur(i), dec(h, 1) + ' h', (dec(i / h, 1) + ' €') if h else '—'])
    if any(pers['sera']):
        M['pers'].append({'titolo': 'Chi c\'è sera per sera, media delle ultime quattro settimane',
                          'nota': 'Le persone e le ore vengono dalle timbrature, l\'incasso dalla cassa senza IVA: è chi c\'era davvero, non chi era previsto.',
                          'colonne': ['Giorno', 'Persone', 'Ore', 'Incasso'], 'righe': righe_p})
        M['eora'].append({'titolo': 'Incasso per ora lavorata, giorno per giorno', 'verso': 'alto',
                          'nota': 'Media delle ultime quattro settimane. I giorni con meno euro per ora sono quelli con troppe persone in turno.',
                          'colonne': ['Giorno', 'Incasso', 'Ore', 'Per ora'], 'righe': righe_e})
    if pers['persone']:
        M['pers'].append({'titolo': 'Ore della settimana, persona per persona',
                          'nota': 'Turni chiusi negli ultimi sette giorni. Senza costo orario la persona non entra nel costo del personale.',
                          'colonne': ['Persona', 'Ruolo', 'Ore', 'Costo orario'],
                          'righe': [[p['nome'], p['ruolo'], dec(p['ore'], 1) + ' h',
                                     (dec(p['costo_orario'], 2) + ' €') if p['costo_orario'] else 'manca'] for p in pers['persone']]})
    if len(pers['reparti']) > 1 or (pers['reparti'] and pers['reparti'][0]['id']):
        M['pers'].append({'titolo': 'Il costo del personale per reparto',
                          'nota': 'Timbrato negli ultimi sette giorni e previsto per i prossimi sette, dalla mansione di ogni persona.',
                          'colonne': ['Reparto', 'Persone', 'Ore timbrate', 'Costo timbrato', 'Costo previsto'],
                          'righe': [[r['nome'], str(r['persone']), dec(r['ore'], 1) + ' h', eur(r['costo']), eur(r['costo_previsto'])]
                                    for r in pers['reparti']]})
    oltre = [p for p in pers['persone'] if p['ore_contratto'] and p['ore_previste'] and p['ore_previste'] > p['ore_contratto'] + 0.5]
    if oltre:
        M['pers'].append({'titolo': 'Turno previsto oltre le ore da contratto', 'verso': 'basso',
                          'nota': 'Le ore in più sono straordinario o supplementare: vanno pagate di più, o il turno va riscritto.',
                          'colonne': ['Persona', 'Contratto', 'Da contratto', 'Previsto', 'In più'],
                          'righe': [[p['nome'], p['contratto'] or '—', dec(p['ore_contratto'], 0) + ' h', dec(p['ore_previste'], 1) + ' h',
                                     '+' + dec(p['ore_previste'] - p['ore_contratto'], 1) + ' h'] for p in oltre]})
    con_turno = [p for p in pers['persone'] if p['ore_previste'] is not None]
    if con_turno:
        M['pers'].insert(0, {'titolo': 'Turno previsto contro ore timbrate, ultimi sette giorni', 'verso': 'basso',
                             'nota': 'Il previsto è la settimana tipo scritta dal consulente; il timbrato è chi c\'era davvero. Più ore del previsto sono straordinari o turni scritti male.',
                             'colonne': ['Persona', 'Previsto', 'Timbrato', 'Differenza', 'Giudizio'],
                             'righe': [[p['nome'], dec(p['ore_previste'], 1) + ' h', dec(p['ore'], 1) + ' h',
                                        ('+' if p['ore'] - p['ore_previste'] > 0 else '') + dec(p['ore'] - p['ore_previste'], 1) + ' h',
                                        'alto' if p['ore'] > p['ore_previste'] * 1.1 + 1 else 'in linea']
                                       for p in con_turno]})
    aperti = TurnoRete.query.filter(TurnoRete.locale_id == lid, TurnoRete.fine.is_(None)).order_by(TurnoRete.inizio.desc()).limit(10).all()
    if aperti:
        from services.quadro import ora_locale
        M['turni'].append({'titolo': 'Turni senza uscita', 'nota': 'Oltre le quattordici ore un turno aperto è un\'uscita dimenticata: il consulente la corregge in Managing.',
                           'colonne': ['Persona', 'Entrata', 'Da quante ore'],
                           'righe': [[(db.session.get(PersonaLocale, t.persona_id).nome if t.persona_id else '?'),
                                      ora_locale(t.inizio).strftime('%d/%m %H:%M'),
                                      dec((datetime.utcnow() - t.inizio).total_seconds() / 3600, 0) + ' h'] for t in aperti]})

    # incasso degli ultimi 14 giorni
    giorni = [(al - timedelta(days=i)) for i in range(13, -1, -1)]
    inc = []
    for g in giorni:
        e, n = _incasso(lid, g, g)
        inc.append([f'{GIORNI[g.weekday()]} {g.day}', eur(e) if n else '—'])
    if any(r[1] != '—' for r in inc):
        M['inc'].append({'titolo': 'Incasso giorno per giorno, ultime due settimane', 'nota': 'Dalla cassa, IVA compresa.',
                         'colonne': ['Giorno', 'Incasso'], 'righe': inc})
        M['cassa'].append({'titolo': 'Giornate di cassa caricate, ultime due settimane', 'nota': 'Un trattino è un giorno senza vendite: chiuso, oppure report non ancora caricato.',
                           'colonne': ['Giorno', 'Incasso'], 'righe': inc})
    if extra.get('non_coperte'):
        M['ric'].append({'titolo': 'Cosa si vende e non è nel ricettario, ' + (extra.get('quando_cassa') or 'ultime 4 settimane'),
                         'nota': 'Voci della cassa non abbinate a una ricetta: il loro food cost non si vede. Si parte dalle più pesanti.',
                         'colonne': ['Voce di cassa', 'Incasso'],
                         'righe': [[n, eur(v)] for n, v in extra['non_coperte'][:10]]})
    _misure_cassa(M, lid, extra.get('cassa') or [], extra.get('quando_cassa'))
    _misure_analisi(M, l, extra.get('cassa') or [], extra.get('quando_cassa'), iva)
    if pers['chiusure']:
        M['chk'].append({'titolo': 'Le chiusure delle ultime due settimane',
                         'nota': 'Chi chiude segna le cinque voci dal tag sulla cassa. Una voce non spuntata è da ricontrollare il giorno dopo.',
                         'colonne': ['Sera', 'Chi', 'Ora', 'Da ricontrollare', 'Nota'],
                         'righe': [[giorno_it(c['giorno']), c['chi'], c['ora'] or '—', ', '.join(c['manca']) or 'niente', c['nota'] or '—']
                                   for c in pers['chiusure'][:10]]})
    inv = InventarioRete.query.filter_by(locale_id=lid).order_by(InventarioRete.giorno.desc()).limit(8).all()
    if inv:
        M['inv'].append({'titolo': 'Gli ultimi inventari', 'nota': 'Tra due inventari chiusi si calcola la diagnosi del food cost.',
                         'colonne': ['Giorno', 'Articoli contati', 'Stato'],
                         'righe': [[giorno_it(i.giorno), str(len(i.righe)), 'chiuso' if i.chiuso else 'aperto'] for i in inv]})
    if extra.get('bolle'):
        M['cons'].append({'titolo': 'Bolle con un problema, ultimi 30 giorni', 'nota': 'Scritto a mano sulla bolla alla consegna, letto dalla foto.',
                          'colonne': ['Giorno', 'Fornitore', 'Nota'], 'righe': extra['bolle']})
    if extra.get('documenti'):
        M['doc'].append({'titolo': 'Documenti da guardare', 'nota': 'Letti da PDF e foto con un dubbio: il consulente li conferma in Managing → Acquisti → Da guardare.',
                         'colonne': ['Fornitore', 'Numero', 'Perché'], 'righe': extra['documenti']})
    return dict(M)


def _misure_analisi(M, l, righe_cassa, quando, iva):
    """Quello che l'analisi delle vendite ha capito: incasso per categoria, food cost piatto per piatto
    (anche senza inventari, con i prezzi stimati detti), voci della cassa unite."""
    from services.foodcost import food_cost_ricette
    q = quando or 'ultime 4 settimane'
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=l.id).all()}
    per_cat = defaultdict(lambda: [0.0, 0])
    for v in righe_cassa:
        a = alias.get(v.voce)
        c = (a.categoria if a and a.categoria else ('Fuori dal food cost' if a and a.ignorata else 'Da abbinare'))
        per_cat[c][0] += v.incasso or 0
        per_cat[c][1] += 1
    tot = sum(x[0] for x in per_cat.values()) or 1
    if per_cat and any(a.categoria for a in alias.values()):
        blocco = {'titolo': 'Incasso per categoria, ' + q,
                  'nota': 'Le categorie le dà l\'analisi delle vendite (Managing → Vendite): il consulente può cambiare ogni abbinamento.',
                  'colonne': ['Categoria', 'Prodotti', 'Incasso', 'Quota'],
                  'righe': [[c, str(n), eur(e), pc(e / tot * 100)] for c, (e, n) in sorted(per_cat.items(), key=lambda y: -y[1][0])]}
        M['inc'].insert(0, blocco)
        M['ric'].insert(0, blocco)
    fcr = food_cost_ricette(l.id, righe_cassa, iva)
    if fcr:
        M['teo'].insert(0, {'titolo': 'Food cost delle ricette sulle vendite, piatto per piatto, ' + q, 'verso': 'basso',
                            'nota': (f'Venduti × costo della porzione, sull\'incasso senza IVA. Il {fcr["quota_stima"]}% del costo usa prezzi '
                                     'stimati del catalogo: diventano veri collegando le fatture in Managing → Acquisti.' if fcr['quota_stima'] else
                                     'Venduti × costo della porzione ai prezzi delle fatture, sull\'incasso senza IVA.'),
                            'colonne': ['Piatto', 'Venduti', 'Costo porzione', 'Food cost', 'Prezzi'],
                            'righe': [[x['nome'], dec(x['venduti'], 0), eur(x['porzione'], 2), pc(x['food_cost']) if x['food_cost'] is not None else '—',
                                       'stimati' if x['stimati'] else 'fatture'] for x in fcr['piatti'][:15]]})
    unite = defaultdict(list)
    for u in UnioneVoce.query.filter_by(locale_id=l.id).all():
        unite[u.nome or u.canonica].append(u.voce)
    if unite:
        M['ric'].append({'titolo': 'Voci della cassa unite in un prodotto solo',
                         'nota': 'Lo stesso prodotto scritto in modi diversi in cassa («Caffe», «Caffè»; «Moretti», «MORETII»): '
                                 'si contano insieme. Più sono, più conviene pulire i nomi in cassa.',
                         'colonne': ['Prodotto', 'Voci della cassa'],
                         'righe': [[n, ', '.join(sorted(v)).title()[:160]] for n, v in sorted(unite.items(), key=lambda y: -len(y[1]))[:15]]})


def _misure_cassa(M, lid, righe_cassa, quando):
    """Tutte le colonne del report della cassa, dove servono: i report di periodo e l'ultimo
    voce per voce sotto l'incasso; sconti e storni sotto i loro indicatori."""
    from services.vendite import riassunto, _quando
    reps = ReportCassa.query.filter_by(locale_id=lid).order_by(ReportCassa.al.desc()).limit(8).all()
    if reps:
        M['inc'].append({'titolo': 'Report di cassa caricati',
                         'nota': 'Report di più giorni senza la data di ogni vendita (il report prodotti di SumUp): ogni report resta '
                                 'un blocco e conta solo nei periodi che copre per intero. Scaricato settimana per settimana fa le settimane.',
                         'colonne': ['Periodo', 'Giorni', 'Incasso', 'Senza IVA', 'IVA', 'Sconti', 'Storni'],
                         'righe': [[f'{giorno_it(r.dal)} → {giorno_it(r.al)}', str(x['giorni']), eur(x['incasso']), eur(x['netto']),
                                    eur(x['iva']), eur(x['sconti']), eur(x['resi_incasso'])] for r, x in ((r, riassunto(r)) for r in reps)]})
        r = reps[0]
        q = _quando(r.dal, r.al)
        from services.vendite import righe_report, unioni
        tutte = righe_report(r, unioni(lid))         # le voci doppie già unite nel loro prodotto
        righe = [v for v in tutte if v.incasso]
        tot = sum(v.incasso for v in righe) or 1
        per_al, miste = defaultdict(lambda: [0, 0.0, 0.0]), []
        for v in righe:
            if v.netto and v.iva is not None:
                # le aliquote italiane; uno scarto più largo è un prodotto venduto con aliquote diverse nel periodo
                a = v.iva / v.netto * 100
                vera = min((0, 4, 5, 10, 22), key=lambda k: abs(k - a))
                x = per_al[f'{vera}%' if abs(vera - a) <= 1 else 'miste']
                if abs(vera - a) > 1:
                    miste.append([v.voce_originale or v.voce, dec(v.quantita, 0), eur(v.incasso), pc(a)])
                x[0] += 1
                x[1] += v.incasso
                x[2] += v.netto
        if per_al:
            M['inc'].append({'titolo': 'Incasso per aliquota IVA, ' + q,
                             'nota': 'L\'aliquota di ogni prodotto viene dall\'IVA calcolata dalla cassa: il cibo di solito al 10%, '
                                     'alcolici e alcune bevande al 22%. «Miste»: prodotti battuti con aliquote diverse nel periodo, da controllare in cassa. '
                                     'Il food cost si fa sull\'incasso senza IVA vero, prodotto per prodotto.',
                             'colonne': ['Aliquota', 'Prodotti', 'Incasso', 'Senza IVA', 'Quota'],
                             'righe': [[a, str(x[0]), eur(x[1]), eur(x[2]), pc(x[1] / tot * 100)]
                                       for a, x in sorted(per_al.items(), key=lambda y: -y[1][1])]})
        if miste:
            M['inc'].append({'titolo': 'Prodotti con aliquote miste, ' + q,
                             'nota': 'L\'IVA di questi prodotti non torna con un\'aliquota sola: in cassa sono stati battuti a volte con un\'aliquota, '
                                     'a volte con un\'altra (per esempio un cocktail al 10% invece che al 22%). Da controllare con chi tiene la cassa.',
                             'colonne': ['Prodotto', 'Pezzi', 'Incasso', 'IVA media'],
                             'righe': sorted(miste, key=lambda r: r[0])})
        M['inc'].append({'titolo': 'I prodotti che incassano di più, ' + q,
                         'colonne': ['Prodotto', 'Pezzi', 'Incasso', 'Quota'],
                         'righe': [[v.voce_originale or v.voce, dec(v.quantita, 0), eur(v.incasso), pc(v.incasso / tot * 100)]
                                   for v in sorted(righe, key=lambda v: -v.incasso)[:15]]})
        con_costo = [v for v in tutte if (v.costo or 0) > 0 and v.netto]
        if con_costo:
            M['inc'].append({'titolo': 'Margine scritto in cassa, ' + q,
                             'nota': f'Solo {len(con_costo)} prodotti su {len(tutte)} hanno in cassa il prezzo d\'acquisto: per gli altri '
                                     'la cassa conta come margine tutto l\'incasso, quindi non si mostrano. Il food cost vero resta quello della diagnosi.',
                             'colonne': ['Prodotto', 'Pezzi', 'Senza IVA', 'Costo', 'Margine'],
                             'righe': [[v.voce_originale or v.voce, dec(v.quantita, 0), eur(v.netto), eur(v.costo),
                                        pc((v.margine if v.margine is not None else v.netto - v.costo) / v.netto * 100)]
                                       for v in sorted(con_costo, key=lambda v: -v.netto)[:15]]})
    q = quando or 'ultime 4 settimane'
    sconti = [v for v in righe_cassa if v.sconti]
    if sconti:
        per = defaultdict(lambda: [0.0, 0.0])
        for v in sconti:
            per[v.voce_originale or v.voce][0] += v.sconti
            per[v.voce_originale or v.voce][1] += (v.incasso or 0) + v.sconti
        M['sconti'].append({'titolo': 'Dove si fanno gli sconti, ' + q, 'verso': 'basso',
                            'colonne': ['Prodotto', 'Sconti', 'Sul venduto'],
                            'righe': [[n, eur(x[0], 2), pc(x[0] / x[1] * 100) if x[1] else '—']
                                      for n, x in sorted(per.items(), key=lambda y: -y[1][0])[:10]]})
    resi = [v for v in righe_cassa if v.resi_quantita]
    if resi:
        per = defaultdict(lambda: [0.0, 0.0])
        for v in resi:
            per[v.voce_originale or v.voce][0] += v.resi_quantita
            per[v.voce_originale or v.voce][1] += v.resi_incasso or 0
        M['storni'].append({'titolo': 'Cosa viene stornato, ' + q, 'verso': 'basso',
                            'nota': 'Righe con la quantità negativa nel report della cassa: resi, errori di battitura, piatti tolti dal conto.',
                            'colonne': ['Prodotto', 'Pezzi', 'Euro'],
                            'righe': [[n, dec(x[0], 0), eur(x[1], 2)] for n, x in sorted(per.items(), key=lambda y: -y[1][1])[:10]]})


def dossier(l, oggi=None):
    from services.indicatori import indicatori, _rincari, tipo_di
    from services.foodcost import diagnosi
    from services.quadro import giorno_di_lavoro
    oggi = oggi or giorno_di_lavoro()
    scheda = l.scheda or {}
    dos = scheda.get('dossier') or {}
    note = dos.get('indicatori') or {}
    ind = indicatori(l, oggi)
    for i in ind['indicatori']:
        n = note.get(i['id']) or {}
        i['nota'] = n.get('nota')
        if n.get('mossa'):
            i['mossa'] = n['mossa']
        i['sorgenti'] = SORGENTE.get(i['id'], [])

    chiusi = InventarioRete.query.filter_by(locale_id=l.id, chiuso=True).order_by(InventarioRete.giorno.desc()).limit(2).all()
    dg = diagnosi(l, chiusi[1], chiusi[0]) if len(chiusi) == 2 else None
    iva = float((l.impostazioni or {}).get('iva', 10))
    pers = personale(l, oggi, None)
    mag = magazzino(l, dg, oggi)

    # quello che serve alle misure e che gli indicatori hanno già calcolato altrove
    _, rincari = _rincari(l.id, oggi)
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=l.id).all()}
    nc = defaultdict(float)
    from services.vendite import base_cassa
    righe_cassa, quando_cassa = base_cassa(l.id, oggi - timedelta(days=28), oggi - timedelta(days=1))
    for v in righe_cassa:
        a = alias.get(v.voce)
        if not (a and (a.ignorata or a.ricetta_id)):
            nc[v.voce_originale or v.voce] += v.incasso or 0
    bolle = [[giorno_it(f.data), f.fornitore, f.etichette.get('note')] for f in FatturaRete.query.filter(
        FatturaRete.locale_id == l.id, FatturaRete.tipo == 'DDT', FatturaRete.data >= oggi - timedelta(days=30)).all()
        if (f.etichette or {}).get('note')]
    documenti = [[f.fornitore, f.numero, ' · '.join(filter(None, [(f.etichette or {}).get('note')] + ((f.etichette or {}).get('controlla') or [])))[:160]]
                 for f in FatturaRete.query.filter_by(locale_id=l.id).all()
                 if ((f.etichette or {}).get('controlla') or (f.etichette or {}).get('note')) and not (f.etichette or {}).get('visto')]
    mis = misure(l, oggi, dg, pers, mag, {'rincari': rincari, 'non_coperte': sorted(nc.items(), key=lambda x: -x[1]),
                                           'bolle': bolle, 'documenti': documenti,
                                           'cassa': righe_cassa, 'quando_cassa': quando_cassa})
    for i in ind['indicatori']:
        i['misure'] = mis.get(i['id'], [])

    # i piatti più venduti col loro food cost, per la diagnosi
    piatti = []
    if dg:
        from services.foodcost import costo_ricetta
        ric = {r.nome: r for r in RicettaRete.query.filter_by(locale_id=l.id).all()}
        for p in dg['piatti'][:6]:
            r = ric.get(p['nome'])
            c, _ = costo_ricetta(r) if r else (None, None)
            f = c / (r.prezzo / (1 + iva / 100)) * 100 if c is not None and r and r.prezzo else None
            piatti.append([p['nome'], dec(p['quantita'], 0), pc(f) if f is not None else '—',
                           'alto' if f and f > dg['obiettivo'] + 5 else 'in linea'])

    # il confronto con i locali dello stesso tipo nella rete
    tipo = tipo_di(l)
    confronto = defaultdict(list)
    for altro in LocaleRete.query.all():
        if tipo_di(altro) != tipo:
            continue
        vals = {i['id']: i['valore'] for i in (ind['indicatori'] if altro.id == l.id else indicatori(altro, oggi)['indicatori'])}
        for k, v in vals.items():
            if v is not None:
                confronto[k].append({'nome': altro.nome, 'valore': v, 'io': altro.id == l.id})

    # anagrafica e contratto
    ev = storia(l)
    visite = [e for e in ev if e['tipo'] == 'visita' and not e['auto']]
    bollino = dos.get('bollino') or 'auto'
    bollino_attivo = (ind['conta']['fuori'] == 0) if bollino == 'auto' else bollino == 'attivo'
    campi = {k: _campo(scheda, k) for k in CAMPI}
    return {
        'locale': {
            'id': l.id, 'nome': l.nome, 'tipo': l.tipo, 'tipo_rete': tipo, 'citta': l.citta, 'consulente': l.consulente,
            'stato': l.stato, 'campi': campi,
            'indirizzo': campi['locale.indirizzo'], 'zona': campi['dossier.zona'], 'coperti': campi['locale.coperti'],
            'titolare': campi['dossier.titolare'] or next((p.nome for p in PersonaLocale.query.filter_by(locale_id=l.id, ruolo='titolare')), None),
            'telefono': campi['dossier.telefono'] or campi['formalita.ref_tel'], 'referente_locale': campi['formalita.ref_nome'],
            'cassa': campi['numeri.cassa_marca'], 'in_formazione': campi['dossier.in_formazione'],
            'pacchetto': campi['dossier.pacchetto'], 'canone': campi['dossier.canone'], 'dal': campi['dossier.dal'] or (l.created_at.date().isoformat() if l.created_at else None),
            'voto_titolare': campi['dossier.voto_titolare'],
            'ultima_visita': visite[0]['giorno'] if visite else None, 'prossima_visita': campi['dossier.prossima_visita'],
            'bollino': bollino, 'bollino_attivo': bollino_attivo,
        },
        'indicatori': ind['indicatori'], 'gruppi': ind['gruppi'], 'conta': ind['conta'],
        'diagnosi': cause_food(l, dg, note) | {'piatti': piatti, 'ingredienti': mis.get('food', [None])[0]} if dg else None,
        'personale': {k: v for k, v in pers.items() if not k.startswith('_')},
        'magazzino': mag,
        'dotazione': dotazione(l, scheda, oggi),
        'storia': ev,
        'confronto': dict(confronto),
        'strumenti': STRUMENTI,
    }
