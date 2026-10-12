"""Il resoconto degli incassi di un locale: una pagina da leggere e da mandare al locale.

Nasce per Mera, che per ora manda solo il report della cassa: con quello si fanno le cose che la
cassa sa (cosa si vende, quanto, a che prezzo) e si dicono quelle che i numeri mostrano ma a occhio
non si vedono. Niente AI e niente stime spacciate per dati: ogni numero viene dalle vendite caricate,
e quello che senza fatture e turni non si può sapere si dice in fondo.

`dati(locale, dal, al)` fa i conti, `pagina(locale, dal, al)` li mette in una pagina HTML sola
(stili dentro, niente script esterni), che si apre da Monitoring e si stampa o si salva in PDF.
"""
from collections import defaultdict
from datetime import date
from html import escape

from models import AliasVendita, VenditaRete
from services.vendite import vendite, unisci, incasso, prima, ultima, a_cavallo, _quando, MESI

GENERICI = 'Da chiarire'           # la categoria dell'analisi per i tasti come «Varie», «A scelta», «Drink»
FUORI_LEVA = {GENERICI, 'Coperto e servizio', 'Rivendita'}
PIATTI = {'Cucina', 'Pizzeria'}         # il «piatto più venduto» si cerca prima qui, poi nel resto
ALIQUOTE = (0, 4, 5, 10, 22)
FASCE = [('Più di 10 al giorno', 10, float('inf')), ('Da 1 a 10 al giorno', 1, 10), ('Da 1 a settimana a 1 al giorno', 1 / 7, 1),
         ('Da 1 al mese a 1 a settimana', 1 / 30.44, 1 / 7), ('Meno di 1 al mese', 0, 1 / 30.44)]
GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']


class NienteDaRaccontare(Exception):
    pass


def _somma(righe, k):
    return sum(getattr(v, k) or 0 for v in righe)


def _nome(v):
    return v.voce_originale or v.voce


def dati(l, dal=None, al=None):
    """Tutti i numeri del resoconto, tra dal e al compresi (di solito tutto quello che c'è)."""
    lid = l.id
    dal = dal or prima(lid)
    al = al or ultima(lid)
    if not dal or not al:
        raise NienteDaRaccontare('Per questo locale non ci sono ancora vendite caricate.')
    tutte = unisci(vendite(lid, dal, al))
    righe = [v for v in tutte if (v.incasso or 0) > 0]
    tot, giorni = incasso(lid, dal, al)
    if not righe or not giorni or tot <= 0:
        raise NienteDaRaccontare('In questo periodo non ci sono incassi caricati per intero.')
    pezzi = _somma(righe, 'quantita')
    anno = 365 / giorni
    alias = {a.voce: a for a in AliasVendita.query.filter_by(locale_id=lid).all()}

    def categoria(v):
        a = alias.get(v.voce)
        return a.categoria if a and a.categoria else 'Da abbinare'

    # ── per categoria ──
    per_cat = defaultdict(lambda: {'incasso': 0.0, 'pezzi': 0.0, 'prodotti': 0})
    for v in righe:
        c = per_cat[categoria(v)]
        c['incasso'] += v.incasso
        c['pezzi'] += v.quantita or 0
        c['prodotti'] += 1
    categorie = sorted(({'nome': n, **x, 'quota': x['incasso'] / tot * 100,
                         'prezzo': x['incasso'] / x['pezzi'] if x['pezzi'] else None}
                        for n, x in per_cat.items()), key=lambda c: -c['incasso'])

    # ── i prodotti ──
    ordinati = sorted(righe, key=lambda v: -v.incasso)
    prodotti = [{'nome': _nome(v), 'categoria': categoria(v), 'incasso': v.incasso, 'pezzi': v.quantita or 0,
                 'prezzo': v.incasso / v.quantita if v.quantita else None, 'quota': v.incasso / tot * 100}
                for v in ordinati]
    soglie, cum, i = {}, 0.0, 0
    for p in prodotti:
        cum += p['incasso']
        i += 1
        for s in (50, 80):
            if s not in soglie and cum >= tot * s / 100:
                soglie[s] = i
    # quelli che si vendono meno di una volta a settimana (solo su un periodo abbastanza lungo per dirlo)
    rari = [p for p in prodotti if p['categoria'] != GENERICI and p['pezzi'] < giorni / 7] if giorni >= 28 else []

    # ── la leva del prezzo: 10 centesimi sui prodotti che si battono di più, contro 1 euro sul piatto più venduto ──
    leva = []
    for p in sorted((p for p in prodotti if p['categoria'] not in FUORI_LEVA and p['prezzo']), key=lambda p: -p['pezzi'])[:5]:
        leva.append({'nome': p['nome'], 'pezzi': p['pezzi'], 'prezzo': p['prezzo'], 'aumento': 0.10,
                     'valore': p['pezzi'] * 0.10 * anno})
    piatti = [p for p in prodotti if p['categoria'] in PIATTI and (p['prezzo'] or 0) >= 8] or \
             [p for p in prodotti if p['categoria'] not in FUORI_LEVA and (p['prezzo'] or 0) >= 8]
    piatto = max(piatti, key=lambda p: p['pezzi']) if piatti else None
    if piatto and leva and all(piatto['nome'] != x['nome'] for x in leva):
        leva.append({'nome': piatto['nome'], 'pezzi': piatto['pezzi'], 'prezzo': piatto['prezzo'], 'aumento': 1.0,
                     'valore': piatto['pezzi'] * 1.0 * anno, 'piatto': True})

    # ── da mettere in ordine in cassa ──
    generici = [p for p in prodotti if p['categoria'] == GENERICI]
    voci_cassa = sum(len(v.nomi_cassa) for v in righe)
    doppi = sorted((v for v in righe if len(v.nomi_cassa) > 1), key=lambda v: (-len(v.nomi_cassa), -v.incasso))
    miste = []
    for v in righe:
        if v.netto and v.iva is not None:
            a = v.iva / v.netto * 100
            vera = min(ALIQUOTE, key=lambda k: abs(k - a))
            if abs(vera - a) > 1:
                miste.append({'nome': _nome(v), 'pezzi': v.quantita or 0, 'incasso': v.incasso, 'iva': a})
    miste.sort(key=lambda m: -m['incasso'])
    aliquote = defaultdict(lambda: {'incasso': 0.0, 'prodotti': 0})
    for v in righe:
        if v.netto and v.iva is not None:
            a = v.iva / v.netto * 100
            vera = min(ALIQUOTE, key=lambda k: abs(k - a))
            x = aliquote[f'IVA {vera}%' if abs(vera - a) <= 1 else 'Aliquote miste']
            x['incasso'] += v.incasso
            x['prodotti'] += 1
    aliquote = sorted(({'nome': k, **x} for k, x in aliquote.items()), key=lambda x: -x['incasso'])

    # ── ogni quanto si vende un prodotto (i tasti generici no: non sono prodotti) ──
    frequenze = []
    if giorni >= 28:
        for nome, da, a in FASCE:
            dentro = [p for p in prodotti if p['categoria'] != GENERICI and da <= p['pezzi'] / giorni < a]
            frequenze.append({'nome': nome, 'prodotti': len(dentro), 'incasso': sum(p['incasso'] for p in dentro)})

    # ── giorno per giorno, solo se la cassa arriva a giorni (il report di periodo non lo sa) ──
    settimana = None
    gg = defaultdict(float)
    for g, e in VenditaRete.query.with_entities(VenditaRete.giorno, VenditaRete.incasso).filter(
            VenditaRete.locale_id == lid, VenditaRete.giorno >= dal, VenditaRete.giorno <= al).all():
        gg[g] += e or 0
    if len(gg) >= 14:
        per = defaultdict(list)
        for g, e in gg.items():
            per[g.weekday()].append(e)
        settimana = [{'giorno': GIORNI[d], 'media': sum(per[d]) / len(per[d]), 'giorni': len(per[d])} for d in range(7) if per[d]]

    # un report di periodo copre tutti i giorni del calendario, anche quelli di chiusura: le medie al giorno lo sono
    blocchi = any(v.giorno is None for v in tutte)
    sconti = _somma(tutte, 'sconti')
    resi_q, resi_e = _somma(tutte, 'resi_quantita'), _somma(tutte, 'resi_incasso')
    netto = _somma(righe, 'netto') or None
    return {
        'locale': l.nome, 'blocchi': blocchi, 'dal': dal, 'al': al, 'giorni': giorni, 'quando': _quando(dal, al),
        'esclusi': [_quando(r.dal, r.al) for r in a_cavallo(lid, dal, al)],
        'incasso': tot, 'netto': netto, 'iva': _somma(righe, 'iva') if netto else None,
        'pezzi': pezzi, 'al_giorno': tot / giorni, 'a_settimana': tot / giorni * 7, 'annuo': tot * anno,
        'prodotti_n': len(prodotti), 'categorie': categorie, 'prodotti': prodotti, 'soglie': soglie, 'rari': rari,
        'leva': leva, 'generici': generici, 'voci_cassa': voci_cassa, 'doppi': doppi[:6], 'doppi_n': len(doppi),
        'miste': miste, 'aliquote': aliquote, 'frequenze': frequenze, 'sconti': sconti, 'resi_pezzi': resi_q, 'resi_incasso': resi_e, 'settimana': settimana,
    }


# ── la pagina ──
# Grafici in HTML e SVG scritti qui, senza librerie: la pagina deve aprirsi anche da sola, salvata o stampata.
# Colori: le prime quattro categorie hanno ognuna il suo (lo stesso in ogni grafico), le altre sono grigie;
# i grafici di una serie sola usano l'inchiostro. Ogni valore è anche scritto: il colore non è mai l'unico modo di leggerlo.

COLORI = ('s1', 's2', 's3', 's4')


def _dec(v, c=0):
    return f'{v:,.{c}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _eur(v, c=0):
    return _dec(v, c) + ' €'


def _pc(v):
    return _dec(v, 1 if v < 10 else 0) + '%'


def _e(t):
    return escape(str(t))


def _colori(d):
    """{categoria: classe colore}: le prime quattro vere categorie; i tasti generici e il resto restano grigi."""
    vere = [c['nome'] for c in d['categorie'] if c['nome'] not in (GENERICI, 'Da abbinare')]
    return {n: COLORI[i] for i, n in enumerate(vere[:4])}


def _col(colori, categoria):
    return colori.get(categoria) or ('gen' if categoria == GENERICI else 'alt')


def _barre(voci, massimo=None):
    """Barre orizzontali: [{nome, valore, testo, sotto?, colore?}]. Il valore è sempre scritto a destra."""
    massimo = massimo or max((x['valore'] for x in voci), default=1) or 1
    out = []
    for x in voci:
        w = max(x['valore'] / massimo * 100, 0.6)
        out.append(f'<div class="rs-riga" data-tip="{_e(x["nome"])} · {_e(x["testo"])}">'
                   f'<div class="rs-nome">{_e(x["nome"])}{"<small>" + _e(x["sotto"]) + "</small>" if x.get("sotto") else ""}</div>'
                   f'<div class="rs-pista"><div class="rs-barra c-{x.get("colore") or "ink"}" style="width:{w:.1f}%"></div></div>'
                   f'<div class="rs-val">{_e(x["testo"])}</div></div>')
    return '<div class="rs-barre">' + ''.join(out) + '</div>'


def _legenda(voci):
    """[(colore, testo)]"""
    return '<div class="rs-leg">' + ''.join(f'<span><i class="c-{c}"></i>{_e(t)}</span>' for c, t in voci) + '</div>'


def _pila(parti, alta=False):
    """Una barra divisa in parti: [(valore, colore, tip)], 2px di stacco tra una parte e l'altra."""
    tot = sum(v for v, *_ in parti) or 1
    return (f'<div class="rs-pila{" alta" if alta else ""}">' + ''.join(
        f'<div class="c-{c}" style="flex:{v / tot * 1000:.0f}" data-tip="{_e(t)}"></div>' for v, c, t in parti if v > 0) + '</div>')


def _mini_coppie(righe):
    """Il piccolo grafico di una scoperta: righe di barre affiancate [(etichetta, [(valore, colore, testo)])],
    ogni riga con la sua scala (si confrontano le barre della stessa riga)."""
    out = []
    for etichetta, barre in righe:
        m = max(v for v, *_ in barre) or 1
        out.append(f'<div class="rs-mini-t">{_e(etichetta)}</div>' + ''.join(
            f'<div class="rs-mini-r"><div class="rs-mini-p"><div class="c-{c}" style="width:{max(v / m * 100, 1.5):.1f}%"></div></div>'
            f'<span>{_e(t)}</span></div>' for v, c, t in barre))
    return '<div class="rs-mini">' + ''.join(out) + '</div>'


def _quadretti(quota, colore='ink', n=100):
    """Cento quadretti, quelli pieni sono la quota: «uno su quattordici» si vede."""
    pieni = round(quota / 100 * n)
    return '<div class="rs-quad">' + ''.join(f'<i class="c-{colore}"></i>' if i < pieni else '<i></i>' for i in range(n)) + '</div>'


def _svg_curva(d):
    """L'incasso cumulato dal prodotto che incassa di più all'ultimo, con i punti del 50% e dell'80%."""
    W, H, l, r, t, b = 640, 250, 44, 18, 14, 38
    pw, ph = W - l - r, H - t - b
    n = d['prodotti_n']
    X = lambda i: l + i / n * pw
    Y = lambda q: t + ph - q / 100 * ph
    cum, punti = 0.0, [(X(0), Y(0))]
    tips = []
    for i, p in enumerate(d['prodotti'], 1):
        cum += p['quota']
        punti.append((X(i), Y(min(cum, 100))))
        tips.append((i, p['nome'], p['quota'], cum))
    linea = ' '.join(f'{x:.1f},{y:.1f}' for x, y in punti)
    out = [f'<svg class="rs-svg" viewBox="0 0 {W} {H}" role="img" aria-label="Incasso cumulato dei prodotti, dal più venduto">']
    for q in (25, 50, 75, 100):
        out.append(f'<line class="griglia" x1="{l}" x2="{W - r}" y1="{Y(q):.1f}" y2="{Y(q):.1f}"/>'
                   f'<text class="asse" x="{l - 8}" y="{Y(q) + 4:.1f}" text-anchor="end">{q}%</text>')
    out.append(f'<line class="base" x1="{l}" x2="{W - r}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>')
    passo = 50 if n > 150 else 25 if n > 60 else 10
    for i in range(0, n + 1, passo):
        out.append(f'<text class="asse" x="{X(i):.1f}" y="{H - b + 18}" text-anchor="middle">{i}</text>')
    out.append(f'<text class="asse" x="{W - r}" y="{H - 4}" text-anchor="end">prodotti, dal più venduto →</text>')
    out.append(f'<polygon class="area" points="{X(0):.1f},{Y(0):.1f} {linea} {X(n):.1f},{Y(0):.1f}"/>')
    out.append(f'<polyline class="linea" points="{linea}"/>')
    for s in (50, 80):
        k = d['soglie'].get(s)
        if not k:
            continue
        x, y = X(k), Y(s)
        out.append(f'<line class="rif" x1="{x:.1f}" x2="{x:.1f}" y1="{y:.1f}" y2="{Y(0):.1f}"/>'
                   f'<circle class="punto" cx="{x:.1f}" cy="{y:.1f}" r="5"/>'
                   f'<text class="nota" x="{x + 10:.1f}" y="{y + 16:.1f}">{k} prodotti fanno il {s}%</text>')
    out.append(f'<line id="rs-croce" class="croce" x1="0" x2="0" y1="{t}" y2="{Y(0):.1f}"/>')
    larga = pw / n
    for i, nome, q, c in tips:       # zone invisibili, una per prodotto: il valore al passaggio del mouse
        out.append(f'<rect class="zona" x="{X(i - 1):.1f}" y="{t}" width="{larga + .5:.2f}" height="{ph}" data-cx="{X(i):.1f}" '
                   f'data-tip="{i}. {_e(nome)}: {_pc(q)} dell\'incasso' + (f' · i primi {i} fanno il {_pc(min(c, 100))}' if i > 1 else '') + '"/>')
    return ''.join(out) + '</svg>'


def _svg_mappa(d, colori):
    """Ogni categoria: quanti pezzi (orizzontale) a che prezzo medio (verticale), scale logaritmiche.
    Le linee oblique sono a incasso costante: due categorie sulla stessa linea incassano uguale."""
    import math
    cat = [c for c in d['categorie'] if c['pezzi'] and c['prezzo'] and c['incasso'] >= d['incasso'] * 0.005]
    if len(cat) < 3:
        return ''
    W, H, l, r, t, b = 640, 330, 52, 24, 16, 40
    pw, ph = W - l - r, H - t - b
    xs, ys = [c['pezzi'] for c in cat], [c['prezzo'] for c in cat]
    x0, x1 = math.log10(min(xs) / 1.8), math.log10(max(xs) * 1.8)
    y0, y1 = math.log10(min(ys) / 1.5), math.log10(max(ys) * 1.5)
    X = lambda v: l + (math.log10(v) - x0) / (x1 - x0) * pw
    Y = lambda v: t + ph - (math.log10(v) - y0) / (y1 - y0) * ph
    out = [f'<svg class="rs-svg" viewBox="0 0 {W} {H}" role="img" aria-label="Pezzi venduti e prezzo medio per categoria">']
    for v in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000):
        if x0 <= math.log10(v) <= x1:
            out.append(f'<line class="griglia" x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{t}" y2="{t + ph}"/>'
                       f'<text class="asse" x="{X(v):.1f}" y="{H - b + 18}" text-anchor="middle">{_dec(v)}</text>')
        if y0 <= math.log10(v) <= y1:
            out.append(f'<line class="griglia" x1="{l}" x2="{W - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                       f'<text class="asse" x="{l - 8}" y="{Y(v) + 4:.1f}" text-anchor="end">{_dec(v)} €</text>')
    out.append(f'<text class="asse" x="{W - r}" y="{H - 4}" text-anchor="end">pezzi venduti nel periodo →</text>'
               f'<text class="asse" x="{l}" y="{t - 4}">↑ prezzo medio</text>')
    # linee a incasso costante: pezzi × prezzo = E
    for E in (1000, 2000, 5000, 10000, 20000, 50000, 100000):
        a = max(10 ** x0, E / 10 ** y1)
        z = min(10 ** x1, E / 10 ** y0)
        if a >= z:
            continue
        out.append(f'<line class="iso" x1="{X(a):.1f}" y1="{Y(E / a):.1f}" x2="{X(z):.1f}" y2="{Y(E / z):.1f}"/>')
        if Y(E / z) > t + ph - 4 and X(z) < W - r - 40:      # l'etichetta solo dove la linea tocca il fondo: in alto ci sono i punti
            out.append(f'<text class="iso-t" x="{X(z) - 4:.1f}" y="{t + ph - 6}" text-anchor="end">{_dec(E)} €</text>')
    m = max(c['incasso'] for c in cat)
    occupati = []
    for c in sorted(cat, key=lambda c: -c['incasso']):
        x, y, rr = X(c['pezzi']), Y(c['prezzo']), 5 + math.sqrt(c['incasso'] / m) * 13
        out.append(f'<circle class="pt c-{_col(colori, c["nome"])}" cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" '
                   f'data-tip="{_e(c["nome"])}: {_dec(c["pezzi"])} pezzi a {_eur(c["prezzo"], 2)} · {_eur(c["incasso"])}"/>')
        # l'etichetta a destra del punto; se ne copre un'altra si sposta sopra o sotto, o va a sinistra
        w = len(c['nome']) * 6.6
        for dx, dy, anc in ((rr + 5, 4, 'start'), (rr + 5, -12, 'start'), (rr + 5, 18, 'start'), (-rr - 5, 4, 'end'), (-rr - 5, -12, 'end'), (-rr - 5, 18, 'end')):
            bx = x + dx if anc == 'start' else x + dx - w
            box = (bx, y + dy - 11, bx + w, y + dy + 3)
            if box[2] <= W - 2 and box[0] >= 2 and not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in occupati):
                occupati.append(box)
                out.append(f'<text class="etic" x="{x + dx:.1f}" y="{y + dy:.1f}" text-anchor="{anc}">{_e(c["nome"])}</text>')
                break
    return ''.join(out) + '</svg>'


def _scoperte(d, colori):
    """Le cose che a occhio non si vedono: ognuna con il suo numero, cosa farne e un piccolo grafico."""
    out = []
    cat = [c for c in d['categorie'] if c['nome'] not in (GENERICI, 'Da abbinare')]
    if len(cat) >= 2:
        a, b = cat[0], cat[1]
        ca, cb = _col(colori, a['nome']), _col(colori, b['nome'])
        vis = _mini_coppie([('Incasso', [(a['incasso'], ca, f'{a["nome"]} {_eur(a["incasso"])}'), (b['incasso'], cb, f'{b["nome"]} {_eur(b["incasso"])}')]),
                            ('Pezzi battuti', [(a['pezzi'], ca, f'{a["nome"]} {_dec(a["pezzi"])}'), (b['pezzi'], cb, f'{b["nome"]} {_dec(b["pezzi"])}')])])
        if b['incasso'] >= a['incasso'] * 0.9 and a['pezzi'] and b['pezzi']:
            r = max(a['pezzi'], b['pezzi']) / min(a['pezzi'], b['pezzi'])
            molti, pochi = (a, b) if a['pezzi'] > b['pezzi'] else (b, a)
            out.append({'numero': f'{_dec(r)} a 1', 'titolo': f'{a["nome"]} e {b["nome"]} incassano quasi uguale', 'vis': vis,
                        'testo': f'{_eur(a["incasso"])} contro {_eur(b["incasso"])}. Ma per arrivarci {molti["nome"].lower()} batte '
                                 f'{_dec(molti["pezzi"])} pezzi a {_eur(molti["prezzo"], 2)} l\'uno, {pochi["nome"].lower()} {_dec(pochi["pezzi"])} '
                                 f'a {_eur(pochi["prezzo"], 2)}: {_dec(r)} volte il lavoro per lo stesso incasso.',
                        'mossa': f'Ogni centesimo sul prezzo di {molti["nome"].lower()} pesa {_dec(r)} volte di più: è lì che i ritocchi rendono.'})
        else:
            out.append({'numero': _pc(a['quota']), 'titolo': f'{a["nome"]} è la prima voce del locale', 'vis': vis,
                        'testo': f'{_eur(a["incasso"])} su {_eur(d["incasso"])}, con {_dec(a["pezzi"])} pezzi battuti.', 'mossa': None})
    s, n = d['soglie'], d['prodotti_n']
    if s.get(50) and s.get(80) and n >= 20:
        vis = ('<div class="rs-mini"><div class="rs-mini-t">Prodotti</div>'
               + _pila([(s[50], 'o1', f'i primi {s[50]}'), (s[80] - s[50], 'o2', f'i {s[80] - s[50]} dopo'), (n - s[80], 'o3', f'gli altri {n - s[80]}')])
               + '<div class="rs-mini-t">Incasso</div>'
               + _pila([(50, 'o1', f'i primi {s[50]}: 50%'), (30, 'o2', f'i {s[80] - s[50]} dopo: 30%'), (20, 'o3', f'gli altri {n - s[80]}: 20%')])
               + _legenda([('o1', f'primi {s[50]}'), ('o2', f'{s[80] - s[50]} dopo'), ('o3', f'altri {n - s[80]}')]) + '</div>')
        out.append({'numero': f'{s[50]} su {n}', 'titolo': 'Pochi prodotti fanno metà dell\'incasso', 'vis': vis,
                    'testo': f'I primi {s[50]} prodotti portano il 50% dell\'incasso, i primi {s[80]} l\'80%. '
                             f'Gli altri {n - s[80]} insieme fanno il 20%.',
                    'mossa': 'Quei pochi devono essere sempre perfetti e sempre disponibili: sono loro a tenere in piedi il locale.'})
    if len(d['rari']) >= 10:
        e = sum(p['incasso'] for p in d['rari'])
        sotto10 = sum(1 for p in d['rari'] if p['pezzi'] <= 10)
        qp, qe = len(d['rari']) / n * 100, e / d['incasso'] * 100
        vis = ('<div class="rs-mini">'
               f'<div class="rs-mini-t">Sono il {_pc(qp)} dei prodotti</div>'
               + _pila([(qp, 'ink', f'{len(d["rari"])} prodotti poco venduti'), (100 - qp, 'alt', 'gli altri prodotti')])
               + f'<div class="rs-mini-t">e fanno il {_pc(qe)} dell\'incasso</div>'
               + _pila([(qe, 'ink', f'{_eur(e)} dai prodotti poco venduti'), (100 - qe, 'alt', 'dagli altri')])
               + _legenda([('ink', 'si vendono meno di 1 a settimana'), ('alt', 'gli altri')]) + '</div>')
        out.append({'numero': str(len(d['rari'])), 'titolo': 'Prodotti che si vendono meno di una volta a settimana', 'vis': vis,
                    'testo': f'Insieme fanno {_eur(e)}, il {_pc(qe)} dell\'incasso; {sotto10} sono stati battuti '
                             f'10 volte o meno in {d["giorni"]} giorni.',
                    'mossa': 'Ogni voce in più vuol dire scorte, spreco e tempo in cucina. Vale la pena chiedersi quali tenere.'})
    if d['leva']:
        cent = sum(x['valore'] for x in d['leva'] if x['aumento'] < 1)
        quanti = sum(1 for x in d['leva'] if x['aumento'] < 1)
        piatto = next((x for x in d['leva'] if x.get('piatto')), None)
        t = f'10 centesimi in più sui {quanti} prodotti più battuti valgono circa {_eur(cent)} in un anno'
        t += f'; 1 euro in più sul piatto più venduto ({piatto["nome"]}) circa {_eur(piatto["valore"])}.' if piatto else '.'
        barre = [(cent, 'ink', f'+10 cent su {quanti} prodotti: {_eur(cent)}')]
        if piatto:
            barre.append((piatto['valore'], 'alt', f'+1 € sul piatto: {_eur(piatto["valore"])}'))
        out.append({'numero': _eur(cent), 'titolo': 'I centesimi contano più degli euro', 'testo': t + ' A vendite uguali.',
                    'vis': _mini_coppie([('In un anno', barre)]),
                    'mossa': 'Prima di toccare i prezzi dei piatti, guardare quelli che si battono cento volte al giorno.'})
    if d['generici']:
        e = sum(p['incasso'] for p in d['generici'])
        q = e / d['incasso'] * 100
        if q >= 2:
            nomi = ', '.join(f'«{p["nome"]}»' for p in d['generici'][:3])
            out.append({'numero': _pc(q), 'titolo': 'Incasso battuto su tasti generici',
                        'vis': _quadretti(q, 'gen') + f'<p class="rs-mini-n">Ogni quadretto è l\'1% dell\'incasso: {round(q)} non dicono cosa si è venduto.</p>',
                        'testo': f'{_eur(e)} sono passati da tasti come {nomi}: si sa quanto hanno incassato, non cosa si è venduto.',
                        'mossa': 'Un tasto per ogni prodotto: è l\'unico modo per sapere cosa rende e cosa no.'})
    q = d['resi_incasso'] + d['sconti']
    if q / d['incasso'] < 0.01:
        out.append({'numero': _pc(q / d['incasso'] * 100), 'titolo': 'Sconti e storni quasi a zero', 'buona': True,
                    'testo': f'{_eur(d["sconti"])} di sconti e {_dec(d["resi_pezzi"])} storni per {_eur(d["resi_incasso"])} su tutto il periodo.',
                    'mossa': 'Un buon segno: in cassa si batte quello che si serve. Da tenere così.'})
    return out


CSS = """
:root{color-scheme:light;--fondo:#f3efe9;--carta:#fcfaf7;--ink:#1a1a1a;--ink2:#5b5650;--muto:#8b867e;--linea:#e4dfd7;--pista:#efebe5;
--s1:#c4622d;--s2:#2a78d6;--s3:#d9a020;--s4:#5e8c3a;--gen:#8b867e;--alt:#cfc8be;--inkb:#3a3631;--o1:#2b2825;--o2:#8b867e;--o3:#d9d3ca;
--buono:#0b7a3b;--cop:#1f1c19;--cop-ink:#f4f2ef;--cop-2:#b9b1a6}
@media screen and (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;--fondo:#121110;--carta:#1c1a18;--ink:#f4f2ef;
--ink2:#c7c1b8;--muto:#8b867e;--linea:#2e2b28;--pista:#26231f;--s1:#d9692e;--s2:#3987e5;--s3:#c98500;--s4:#199e70;--gen:#8b867e;--alt:#4a4540;
--inkb:#d9d3ca;--o1:#efe9e1;--o2:#8b867e;--o3:#45403a;--buono:#57c390;--cop:#0b0a09}}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--ink);font:15px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
.rs{max-width:920px;margin:0 auto;padding:0 16px 64px}
h1,h2{font-family:"Playfair Display",Georgia,serif;font-weight:600;line-height:1.1;margin:0}
h2{font-size:28px;margin:0 0 6px}
.c-s1{background:var(--s1);fill:var(--s1)}.c-s2{background:var(--s2);fill:var(--s2)}.c-s3{background:var(--s3);fill:var(--s3)}.c-s4{background:var(--s4);fill:var(--s4)}
.c-gen{background:var(--gen);fill:var(--gen)}.c-alt{background:var(--alt);fill:var(--alt)}.c-ink{background:var(--inkb);fill:var(--inkb)}
.c-o1{background:var(--o1)}.c-o2{background:var(--o2)}.c-o3{background:var(--o3)}
/* copertina */
.rs-cop{background:var(--cop);color:var(--cop-ink);margin:0 -16px;padding:36px 40px 30px;border-radius:0 0 22px 22px;position:relative;overflow:hidden}
.rs-cop::after{content:"";pointer-events:none;position:absolute;right:-90px;top:-90px;width:280px;height:280px;border-radius:50%;border:1px solid rgba(255,255,255,.08);box-shadow:0 0 0 40px rgba(255,255,255,.02),0 0 0 80px rgba(255,255,255,.015)}
.rs-cop-su{display:flex;justify-content:space-between;align-items:center;gap:16px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--cop-2)}
.rs-cop-su b{color:#ef8b52;font-weight:600}
.rs-cop h1{font-size:52px;margin:34px 0 6px;letter-spacing:-.01em}
.rs-cop p{margin:0;color:var(--cop-2)}
.rs-eroe{display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px 28px;margin:30px 0 14px}
.rs-eroe b{font-size:56px;font-weight:600;letter-spacing:-.02em;line-height:1;white-space:nowrap}
.rs-eroe span{color:var(--cop-2);padding-bottom:6px}
.rs-cop .rs-pila{height:16px}.rs-cop .rs-pila div{border-radius:4px}
.rs-cop .rs-leg{color:var(--cop-2);margin-top:10px}
.rs-stampa{position:relative;z-index:1;font:inherit;font-size:12px;letter-spacing:.04em;text-transform:none;border:1px solid rgba(255,255,255,.22);background:transparent;color:var(--cop-ink);border-radius:999px;padding:7px 14px;cursor:pointer;white-space:nowrap}
.rs-stampa:hover{background:rgba(255,255,255,.08)}
.rs-numeri{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 6px}
.rs-numeri div{background:var(--carta);border:1px solid var(--linea);border-radius:14px;padding:16px 18px}
.rs-numeri b{display:block;white-space:nowrap;font-size:26px;font-weight:600;letter-spacing:-.01em}
.rs-numeri span{font-size:13px;color:var(--ink2)}
.rs-sotto{color:var(--ink2);margin:0}
.rs-piccolo{font-size:12.5px;color:var(--muto);margin:10px 0 0}
/* sezioni */
.rs-sez{margin-top:56px}
.rs-kick{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--s1);font-weight:600;margin-bottom:8px}
.rs-sez>p.rs-nota{color:var(--ink2);margin:0 0 20px;max-width:660px}
.rs-box{background:var(--carta);border:1px solid var(--linea);border-radius:16px;padding:22px}
.rs-box h3{margin:0 0 4px;font-size:16px}
.rs-box+.rs-box{margin-top:14px}
/* scoperte */
.rs-scop{display:grid;gap:14px}
.rs-card{background:var(--carta);border:1px solid var(--linea);border-radius:16px;padding:22px 24px;display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:24px;align-items:center;position:relative}
.rs-card::before{content:"";position:absolute;left:0;top:22px;bottom:22px;width:3px;border-radius:0 3px 3px 0;background:var(--s1)}
.rs-card.buona::before{background:var(--buono)}
.rs-big{font-size:34px;font-weight:600;color:var(--s1);line-height:1;letter-spacing:-.01em;margin-bottom:10px}
.rs-card.buona .rs-big{color:var(--buono)}
.rs-card h3{margin:0 0 6px;font-size:17px}
.rs-card p{margin:0 0 8px;color:var(--ink2)}
.rs-card .rs-mossa{color:var(--ink);font-weight:500;margin:0}
.rs-card .rs-mossa::before{content:"→ ";color:var(--s1)}
.rs-card.solo{grid-template-columns:1fr}
.rs-mini{display:grid;gap:5px;font-size:12px;color:var(--ink2)}
.rs-mini-t{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muto);margin-top:6px}
.rs-mini-t:first-child{margin-top:0}
.rs-mini-r{display:grid;gap:2px}
.rs-mini-p{height:10px;background:var(--pista);border-radius:0 4px 4px 0}
.rs-mini-p div{height:100%;border-radius:0 4px 4px 0}
.rs-mini-n{font-size:12px!important;color:var(--muto)!important;margin:8px 0 0!important}
.rs-quad{display:grid;grid-template-columns:repeat(20,1fr);gap:2px}
.rs-quad i{aspect-ratio:1;border-radius:2px}.rs-quad i:not([class]){background:var(--pista)}
/* barre */
.rs-barre{display:grid;gap:7px}
.rs-riga{display:grid;grid-template-columns:minmax(120px,220px) 1fr 150px;gap:14px;align-items:center;font-size:14px;padding:2px 0;border-radius:6px}
.rs-riga:hover{background:var(--pista)}
.rs-nome{overflow-wrap:anywhere}.rs-nome small{display:block;color:var(--muto);font-size:12px}
.rs-pista{height:14px;background:var(--pista);border-radius:0 4px 4px 0}
.rs-barra{height:100%;border-radius:0 4px 4px 0}
.rs-val{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.rs-pila{display:flex;height:12px;gap:2px}
.rs-pila.alta{height:30px}
.rs-pila div{border-radius:3px;min-width:2px}
.rs-leg{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12.5px;color:var(--ink2);margin-top:8px}
.rs-leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.rs-due{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.rs-due>.rs-box+.rs-box{margin-top:0}
/* svg */
.rs-svg{width:100%;height:auto;display:block;overflow:visible}
.rs-svg text{font-family:Inter,system-ui,sans-serif}
.rs-svg .asse{font-size:11px;fill:var(--muto);font-variant-numeric:tabular-nums}
.rs-svg .griglia{stroke:var(--linea);stroke-width:1}
.rs-svg .base{stroke:var(--muto);stroke-width:1}
.rs-svg .area{fill:var(--s1);opacity:.1}
.rs-svg .linea{fill:none;stroke:var(--s1);stroke-width:2.2;stroke-linejoin:round}
.rs-svg .rif{stroke:var(--ink2);stroke-width:1}
.rs-svg .punto{fill:var(--s1);stroke:var(--carta);stroke-width:2}
.rs-svg .nota{font-size:12.5px;fill:var(--ink);font-weight:600}
.rs-svg .croce{stroke:var(--ink2);stroke-width:1;opacity:0;pointer-events:none}
.rs-svg .zona{fill:transparent}
.rs-svg .iso{stroke:var(--alt);stroke-width:1;opacity:.8}
.rs-svg .iso-t{font-size:10.5px;fill:var(--muto)}
.rs-svg .pt{stroke:var(--carta);stroke-width:2;fill-opacity:.9}
.rs-svg .pt:hover{fill-opacity:1;stroke:var(--ink)}
.rs-svg .etic{font-size:12px;fill:var(--ink)}
/* frequenze */
.rs-freq{display:grid;grid-template-columns:minmax(140px,230px) 1fr 1fr;gap:10px 18px;align-items:center;font-size:14px}
.rs-freq .t{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muto)}
.rs-freq .b{display:grid;grid-template-columns:1fr 64px;gap:8px;align-items:center}
.rs-freq .b span{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-weight:500;color:var(--muto);font-size:11px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--linea);padding:6px 8px}
td{border-bottom:1px solid var(--linea);padding:8px;vertical-align:top}
tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.rs-manca{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;padding:0;margin:0;list-style:none}
.rs-manca li{background:var(--carta);border:1px dashed var(--alt);border-radius:16px;padding:18px 20px;color:var(--ink2)}
.rs-manca b{display:block;color:var(--ink);font-size:16px;margin-bottom:4px}
.rs-piede{margin-top:56px;border-top:1px solid var(--linea);padding-top:16px;font-size:12px;color:var(--muto)}
.rs-tip{position:fixed;z-index:9;max-width:300px;background:var(--ink);color:var(--carta);font-size:12.5px;line-height:1.4;padding:7px 10px;border-radius:8px;pointer-events:none;box-shadow:0 6px 20px rgba(0,0,0,.18)}
@media (max-width:700px){.rs-cop{padding:26px 20px 22px}.rs-cop h1{font-size:36px;margin-top:22px}.rs-eroe b{font-size:42px}
.rs-card{grid-template-columns:1fr;gap:16px}.rs-riga{grid-template-columns:1fr 100px}.rs-riga .rs-pista{grid-column:1/-1;grid-row:2}
.rs-due{grid-template-columns:1fr}.rs-freq{grid-template-columns:1fr 1fr}.rs-freq>.n{grid-column:1/-1;margin-top:6px}.rs-freq>.t:first-child{display:none}}
@page{margin:12mm 11mm}
@media print{body{background:#fff;font-size:12.5px;-webkit-print-color-adjust:exact;print-color-adjust:exact}.rs{padding:0;max-width:none}
.rs-cop{margin:0;border-radius:18px}.rs-stampa,.rs-tip{display:none}.rs-sez{margin-top:30px}
.rs-card,.rs-riga,.rs-numeri,.rs-pila,tr,.rs-svg,.rs-freq,.rs-manca li{break-inside:avoid}h2,.rs-nota,.rs-kick{break-after:avoid}.rs-nota{break-inside:avoid}
.rs-barre{display:block}.rs-riga{margin-bottom:7px}.rs-schermo{display:none}
.rs-due{display:block}.rs-due>.rs-box{break-inside:auto}.rs-due>.rs-box+.rs-box{margin-top:14px}}
"""

SCRIPT = """(()=>{const t=document.getElementById('rs-tip'),x=document.getElementById('rs-croce');
document.addEventListener('pointermove',e=>{const el=e.target.closest&&e.target.closest('[data-tip]');
if(!el){t.hidden=true;if(x)x.style.opacity=0;return}
t.textContent=el.dataset.tip;t.hidden=false;const w=t.offsetWidth,h=t.offsetHeight;
t.style.left=Math.max(8,Math.min(e.clientX+14,innerWidth-w-8))+'px';t.style.top=(e.clientY+18+h>innerHeight?e.clientY-h-12:e.clientY+18)+'px';
if(x){if(el.dataset.cx){x.setAttribute('x1',el.dataset.cx);x.setAttribute('x2',el.dataset.cx);x.style.opacity=1}else x.style.opacity=0}});
document.addEventListener('pointerleave',()=>{t.hidden=true})})();"""


def _sezione(n, titolo, nota, corpo):
    return (f'<section class="rs-sez"><div class="rs-kick">{n:02d}</div><h2>{_e(titolo)}</h2>'
            + (f'<p class="rs-nota">{_e(nota)}</p>' if nota else '') + corpo + '</section>')


def _tabella(col, righe):
    return ('<table><thead><tr>' + ''.join(f'<th{" class=n" if i and len(col) > 2 else ""}>{_e(c)}</th>' for i, c in enumerate(col)) + '</tr></thead><tbody>'
            + ''.join('<tr>' + ''.join(f'<td{" class=n" if i and len(col) > 2 else ""}>{_e(c)}</td>' for i, c in enumerate(r)) + '</tr>' for r in righe)
            + '</tbody></table>')


def pagina(l, dal=None, al=None, oggi=None):
    d = dati(l, dal, al)
    oggi = oggi or date.today()
    colori = _colori(d)
    P = []

    # ── copertina: il totale e com'è fatto ──
    vere = [c for c in d['categorie'] if c['nome'] in colori]
    resto = d['incasso'] - sum(c['incasso'] for c in vere)
    parti = [(c['incasso'], colori[c['nome']], f'{c["nome"]}: {_eur(c["incasso"])} · {_pc(c["quota"])}') for c in vere]
    if resto > 0:
        parti.append((resto, 'alt', f'Tutto il resto: {_eur(resto)} · {_pc(resto / d["incasso"] * 100)}'))
    P.append('<header class="rs-cop"><div class="rs-cop-su"><span><b>SB Food Consulting</b> · Resoconto degli incassi</span>'
             '<button class="rs-stampa" type="button" onclick="window.print()">Stampa o salva in PDF</button></div>'
             f'<h1>{_e(d["locale"])}</h1><p>Le vendite {_e(d["quando"])}: {d["giorni"]} giorni{", chiusure comprese" if d["blocchi"] else " di cassa"}.</p>'
             f'<div class="rs-eroe"><b>{_eur(d["incasso"])}</b><span>incassati, IVA compresa'
             + (f' · {_eur(d["netto"])} senza IVA' if d['netto'] else '') + '</span></div>'
             + _pila(parti) + _legenda([(c, t.split(':')[0] + ' ' + t.split('·')[-1].strip()) for _, c, t in parti]) + '</header>')
    numeri = [(_eur(d['al_giorno']), 'in media al giorno'), (_eur(d['a_settimana']), 'in media a settimana'),
              (_dec(d['pezzi']), f'pezzi battuti, {_dec(d["pezzi"] / d["giorni"])} al giorno'), (_dec(d['prodotti_n']), 'prodotti diversi venduti')]
    P.append('<section class="rs-numeri">' + ''.join(f'<div><b>{a}</b><span>{_e(b)}</span></div>' for a, b in numeri) + '</section>')
    P.append(f'<p class="rs-piccolo">Allo stesso ritmo, un anno intero farebbe circa {_eur(d["annuo"])}.'
             + (f' IVA del periodo {_eur(d["iva"])}.' if d['iva'] else '') + '</p>')
    k = 0

    sc = _scoperte(d, colori)
    if sc:
        k += 1
        carte = ''.join(f'<article class="rs-card{" buona" if x.get("buona") else ""}{"" if x.get("vis") else " solo"}"><div>'
                        f'<div class="rs-big">{_e(x["numero"])}</div><h3>{_e(x["titolo"])}</h3><p>{_e(x["testo"])}</p>'
                        + (f'<p class="rs-mossa">{_e(x["mossa"])}</p>' if x.get('mossa') else '') + '</div>'
                        + (f'<div>{x["vis"]}</div>' if x.get('vis') else '') + '</article>' for x in sc)
        P.append(_sezione(k, 'Quello che i numeri dicono', 'Cose che dal bancone non si vedono, ma che la cassa ha registrato.',
                          f'<div class="rs-scop">{carte}</div>'))

    k += 1
    corpo = '<div class="rs-box">' + _barre([{'nome': c['nome'], 'valore': c['incasso'], 'colore': _col(colori, c['nome']),
                                              'sotto': f'{_dec(c["pezzi"])} pezzi' + (f' · {_eur(c["prezzo"], 2)} l\'uno' if c['prezzo'] else ''),
                                              'testo': f'{_eur(c["incasso"])} · {_pc(c["quota"])}'}
                                             for c in d['categorie'] if c['incasso'] >= d['incasso'] * 0.001]) + '</div>'
    mappa = _svg_mappa(d, colori)
    if mappa:
        corpo += ('<div class="rs-box"><h3>Tanti pezzi a poco, o pochi pezzi a tanto</h3><p class="rs-sotto" style="font-size:13px;margin-bottom:12px">'
                  'Ogni cerchio è una categoria: più a destra, più pezzi; più in alto, più caro il pezzo; più grande, più incassa. '
                  'Le linee oblique sono a incasso uguale: due cerchi sulla stessa linea incassano lo stesso, in modi opposti.</p>' + mappa + '</div>')
    P.append(_sezione(k, 'Dove arriva l\'incasso', 'Incasso per categoria, e quanto vale in media ogni pezzo battuto.', corpo))

    s = d['soglie']
    if s.get(50) and s.get(80):
        k += 1
        P.append(_sezione(k, 'Pochi prodotti, metà dell\'incasso',
                          f'Tutti i {d["prodotti_n"]} prodotti in fila, dal più venduto: la curva dice quanto dell\'incasso fanno i primi.', '<div class="rs-box">' + _svg_curva(d)
                          + '<p class="rs-piccolo rs-schermo">Passando col mouse sulla curva si vede ogni prodotto.</p></div>'))

    k += 1
    top = d['prodotti'][:15]
    usati = []
    for p in top:
        c = _col(colori, p['categoria'])
        if all(c != u[0] for u in usati):
            usati.append((c, p['categoria'] if c not in ('alt', 'gen') else ('Tasti generici' if c == 'gen' else 'Altre categorie')))
    P.append(_sezione(k, 'I 15 prodotti che incassano di più', 'Con i pezzi venduti e il prezzo medio battuto in cassa. Il colore è la categoria.',
                      '<div class="rs-box">' + _legenda(usati) + '<div style="height:12px"></div>'
                      + _barre([{'nome': f'{i}. {p["nome"]}', 'valore': p['incasso'], 'testo': f'{_eur(p["incasso"])} · {_pc(p["quota"])}',
                                 'sotto': f'{_dec(p["pezzi"])} pezzi' + (f' · {_eur(p["prezzo"], 2)}' if p['prezzo'] else ''),
                                 'colore': _col(colori, p['categoria'])} for i, p in enumerate(top, 1)]) + '</div>'))

    if d['leva']:
        k += 1
        P.append(_sezione(k, 'Quanto vale un ritocco di prezzo', 'In un anno, se si vende come in questo periodo: '
                          '10 centesimi in più sui prodotti battuti più spesso, e 1 euro in più sul piatto più venduto.',
                          '<div class="rs-box">' + _barre([{'nome': x['nome'], 'valore': x['valore'], 'colore': 'alt' if x.get('piatto') else 'ink',
                                                            'sotto': f'{_eur(x["prezzo"], 2)} → {_eur(x["prezzo"] + x["aumento"], 2)} · '
                                                                     f'{_dec(x["pezzi"] / d["giorni"], 0 if x["pezzi"] / d["giorni"] >= 10 else 1)} al giorno',
                                                            'testo': f'+{_eur(x["valore"])} l\'anno'} for x in d['leva']])
                          + _legenda([('ink', '+10 centesimi'), ('alt', '+1 euro')] if any(x.get('piatto') for x in d['leva']) else [('ink', '+10 centesimi')])
                          + '<p class="rs-piccolo">Una stima, non una previsione: un prezzo più alto può far vendere un po\' meno.</p></div>'))

    if d['frequenze']:
        k += 1
        mp = max(f['prodotti'] for f in d['frequenze']) or 1
        me = max(f['incasso'] for f in d['frequenze']) or 1
        tot_f = sum(f['incasso'] for f in d['frequenze']) or 1
        righe = ''.join(f'<div class="n">{_e(f["nome"])}</div>'
                        f'<div class="b" data-tip="{_e(f["nome"])}: {f["prodotti"]} prodotti"><div class="rs-pista"><div class="rs-barra c-gen" style="width:{max(f["prodotti"] / mp * 100, .6):.1f}%"></div></div><span>{f["prodotti"]}</span></div>'
                        f'<div class="b" data-tip="{_e(f["nome"])}: {_eur(f["incasso"])}"><div class="rs-pista"><div class="rs-barra c-ink" style="width:{max(f["incasso"] / me * 100, .6):.1f}%"></div></div><span>{_pc(f["incasso"] / tot_f * 100)}</span></div>'
                        for f in d['frequenze'])
        P.append(_sezione(k, 'Ogni quanto si vende ogni prodotto', 'A sinistra quanti prodotti stanno in ogni fascia, a destra quanta parte '
                          'dell\'incasso portano. Tanti prodotti in basso e poco incasso: è il peso della lista.',
                          '<div class="rs-box"><div class="rs-freq"><div class="t">Si vende…</div><div class="t">Prodotti</div><div class="t">Incasso</div>'
                          + righe + '</div></div>'))

    if d['settimana']:
        k += 1
        P.append(_sezione(k, 'Il giorno della settimana', 'Incasso medio per giorno della settimana.',
                          '<div class="rs-box">' + _barre([{'nome': g['giorno'], 'valore': g['media'], 'testo': _eur(g['media']),
                                                            'sotto': f'{g["giorni"]} giorni'} for g in d['settimana']]) + '</div>'))

    # ── in cassa ──
    box = []
    if d['generici']:
        box.append(('Tasti generici', 'Incasso che non dice cosa si è venduto.',
                    _tabella(['Tasto', 'Pezzi', 'Incasso'], [[p['nome'], _dec(p['pezzi']), _eur(p['incasso'])] for p in d['generici'][:8]])))
    if d['doppi']:
        box.append(('Lo stesso prodotto con più nomi', f'{_dec(d["voci_cassa"])} nomi in cassa per {d["prodotti_n"]} prodotti: '
                    f'{d["doppi_n"]} prodotti sono scritti in più modi. Qui li abbiamo contati insieme.',
                    _tabella(['Prodotto', 'Come è scritto in cassa'], [[_nome(v), ', '.join(sorted(v.nomi_cassa))[:120]] for v in d['doppi']])))
    if d['miste']:
        e = sum(m['incasso'] for m in d['miste'])
        al = d['aliquote']
        pila = ''
        if len(al) > 1:
            # tre parti al massimo: l'aliquota principale, le altre insieme, le miste (quelle da guardare)
            tot_a = sum(a['incasso'] for a in al) or 1
            giuste = [a for a in al if a['nome'] != 'Aliquote miste']
            parti = [(giuste[0]['incasso'], 'ink', giuste[0]['nome'])] if giuste else []
            altre = giuste[1:]
            if altre:
                parti.append((sum(a['incasso'] for a in altre), 'alt', altre[0]['nome'] if len(altre) == 1 else 'Altre aliquote (' + ', '.join(a['nome'][4:] for a in altre) + ')'))
            parti += [(a['incasso'], 'gen', a['nome']) for a in al if a['nome'] == 'Aliquote miste']
            pila = (_pila([(v, c, f'{n}: {_eur(v)}') for v, c, n in parti])
                    + _legenda([(c, f'{n} {_pc(v / tot_a * 100)}') for v, c, n in parti]) + '<div style="height:14px"></div>')
        box.append(('IVA diversa sullo stesso prodotto', f'{len(d["miste"])} prodotti ({_eur(e)} di incasso) sono stati battuti con aliquote diverse '
                    'nel periodo. Può essere giusto (consumo al tavolo e asporto) o un tasto impostato male: è una domanda per il commercialista.',
                    pila + _tabella(['Prodotto', 'Pezzi', 'Incasso', 'IVA media'], [[m['nome'], _dec(m['pezzi']), _eur(m['incasso']), _pc(m['iva'])] for m in d['miste'][:8]])))
    if d['rari']:
        r = sorted(d['rari'], key=lambda p: (p['pezzi'], p['incasso']))
        box.append(('I meno venduti', f'{len(d["rari"])} prodotti venduti meno di una volta a settimana. I primi della lista:',
                    _tabella(['Prodotto', 'Pezzi', 'Incasso'], [[p['nome'], _dec(p['pezzi']), _eur(p['incasso'])] for p in r[:8]])))
    if box:
        k += 1
        P.append(_sezione(k, 'Da mettere in ordine in cassa', 'Una cassa ordinata fa numeri più chiari, e numeri più chiari fanno decisioni migliori.',
                          '<div class="rs-due">' + ''.join(f'<div class="rs-box"><h3>{_e(t)}</h3><p class="rs-sotto" style="font-size:13px;margin-bottom:12px">{_e(n)}</p>{c}</div>'
                                                           for t, n, c in box) + '</div>'))

    k += 1
    manca = [('Le fatture dei fornitori', 'il food cost vero, piatto per piatto, e i rincari appena arrivano.'),
             ('I turni del personale', 'quanto costa ogni ora di apertura e se il personale segue l\'incasso.')]
    if not d['settimana']:
        manca.append(('La cassa giorno per giorno', 'questo report è un blocco unico, quindi non dice quali giorni e quali settimane vanno meglio.'))
    P.append(_sezione(k, 'Quello che la cassa da sola non può dire', 'La cassa sa cosa entra. Per sapere quanto resta servono anche le altre due metà dei conti:',
                      '<ul class="rs-manca">' + ''.join(f'<li><b>{_e(a)}</b>{_e(b)}</li>' for a, b in manca) + '</ul>'))
    if d['esclusi']:
        P.append(f'<p class="rs-piccolo">Non contati: report di cassa che escono dal periodo ({_e("; ".join(d["esclusi"]))}).</p>')
    P.append(f'<footer class="rs-piede">Preparato da SB Food Consulting il {oggi.day} {MESI[oggi.month - 1]} {oggi.year}, '
             'dal report delle vendite della cassa. I prodotti scritti in modi diversi sono contati insieme; '
             'le categorie sono quelle dell\'analisi delle vendite di Rete SB.</footer>')
    return ('<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Resoconto incassi · {_e(d["locale"])}</title>'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Playfair+Display:wght@600&display=swap" rel="stylesheet">'
            f'<style>{CSS}</style></head><body><main class="rs">' + ''.join(P) + '</main>'
            f'<div class="rs-tip" id="rs-tip" hidden></div><script>{SCRIPT}</script></body></html>')
