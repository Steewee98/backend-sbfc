"""PDF dei percorsi dei visitatori (Traffico sito → Percorso dei visitatori).

Riceve una lista di visitatori gia' aggregati dalla route e produce un PDF
brandizzato SB Food: pagina di riepilogo + un blocco per visitatore con la
timeline degli eventi. Il rendering e' separato dalla logica dati (la route
prepara i dati, questo modulo li impagina)."""
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, CondPageBreak,
)

DARK = colors.HexColor('#37393f')
ACCENT = colors.HexColor('#c4622d')
IVORY = colors.HexColor('#f5f2ee')
GRAY = colors.HexColor('#5a5a5a')
LIGHT = colors.HexColor('#9a948b')
LINE = colors.HexColor('#e8e4df')

# Icona testuale per tipo evento (coerente col gestionale)
_ICONE = {
    'pageview': '▣', 'click': '☞', 'scroll': '↕', 'tempo': '◷',
    'identificazione': '✉', 'scheda_download': '↓', 'scheda_vista': '◉',
}


def _esc(s):
    return (str(s) if s is not None else '').replace('&', '&amp;') \
        .replace('<', '&lt;').replace('>', '&gt;')


def genera_percorsi_pdf(visitatori, giorni, generato_il, riepilogo=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title='Percorsi visitatori — SB Food Consulting',
    )

    st_title = ParagraphStyle('t', fontSize=20, fontName='Helvetica-Bold',
                              textColor=colors.white, leading=24)
    st_sub = ParagraphStyle('s', fontSize=10, fontName='Helvetica',
                            textColor=ACCENT, leading=14)
    st_meta = ParagraphStyle('m', fontSize=9, fontName='Helvetica',
                             textColor=colors.white, leading=14)
    st_vis = ParagraphStyle('v', fontSize=11, fontName='Helvetica-Bold',
                            textColor=colors.white, leading=14)
    st_vismeta = ParagraphStyle('vm', fontSize=8, fontName='Helvetica',
                                textColor=IVORY, leading=12)
    st_ora = ParagraphStyle('o', fontSize=8, fontName='Helvetica',
                            textColor=LIGHT, leading=12)
    st_ev = ParagraphStyle('e', fontSize=9, fontName='Helvetica',
                           textColor=DARK, leading=13)
    st_empty = ParagraphStyle('em', fontSize=10, fontName='Helvetica',
                              textColor=GRAY, leading=16)

    W = doc.width
    story = []

    # ── HEADER ──────────────────────────────────────────────
    header = Table([[Paragraph('SB FOOD CONSULTING', st_sub)],
                    [Paragraph('Percorsi dei visitatori', st_title)],
                    [Paragraph(
                        f'Ultimi {giorni} giorni &middot; generato il {generato_il}',
                        st_meta)]],
                   colWidths=[W])
    header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), DARK),
        ('LEFTPADDING', (0, 0), (-1, -1), 18),
        ('RIGHTPADDING', (0, 0), (-1, -1), 18),
        ('TOPPADDING', (0, 0), (0, 0), 16),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 16),
        ('TOPPADDING', (0, 1), (-1, -1), 2),
    ]))
    story.append(header)
    story.append(Spacer(1, 10))

    # ── RIEPILOGO ──────────────────────────────────────────
    if riepilogo:
        def kpi(label, val):
            return Table([[Paragraph(str(val), ParagraphStyle(
                'kv', fontSize=18, fontName='Helvetica-Bold',
                textColor=DARK, leading=20))],
                [Paragraph(label, ParagraphStyle(
                    'kl', fontSize=7.5, fontName='Helvetica', textColor=GRAY,
                    leading=10))]], colWidths=[W / 4 - 6])
        kpis = kpi('Visitatori', riepilogo.get('visitatori', 0)), \
            kpi('Identificati', riepilogo.get('convertiti', 0)), \
            kpi('Pagine viste', riepilogo.get('pageviews_totali', 0)), \
            kpi('Eventi', riepilogo.get('eventi_totali', 0))
        grid = Table([list(kpis)], colWidths=[W / 4] * 4)
        grid.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), IVORY),
            ('BOX', (0, 0), (-1, -1), 0.5, LINE),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, LINE),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(grid)
        story.append(Spacer(1, 16))

    if not visitatori:
        story.append(Paragraph(
            'Nessun visitatore tracciato nel periodo selezionato '
            '(il tracking richiede l\'accettazione dei cookie di analisi).',
            st_empty))
        doc.build(story)
        buffer.seek(0)
        return buffer

    # ── UN BLOCCO PER VISITATORE ───────────────────────────
    for idx, v in enumerate(visitatori, 1):
        story.append(CondPageBreak(60 * mm))

        ident = v.get('identita') or 'Visitatore anonimo'
        meta = ' · '.join(filter(None, [
            v.get('dispositivo'),
            f"Fonte: {v.get('fonte')}" if v.get('fonte') else None,
            f"{v.get('prima_visita')} → {v.get('ultima_attivita')}",
        ]))
        intest = Table([[
            Paragraph(f'{idx}. {_esc(ident)}', st_vis),
            Paragraph(
                f"{v.get('pageviews', 0)} pagine &middot; "
                f"{v.get('eventi_totali', 0)} eventi", st_vismeta),
        ], [Paragraph(_esc(meta), st_vismeta), '']], colWidths=[W * 0.68, W * 0.32])
        intest.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), DARK),
            ('SPAN', (1, 0), (1, 1)),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (0, 0), 9),
            ('BOTTOMPADDING', (0, 1), (-1, 1), 9),
        ]))
        story.append(intest)

        eventi = v.get('eventi', [])
        if not eventi:
            continue
        righe = []
        for e in eventi:
            ico = _ICONE.get(e.get('tipo'), '•')
            righe.append([
                Paragraph(_esc(e.get('quando', '')), st_ora),
                Paragraph(ico, st_ev),
                Paragraph(_esc(e.get('testo', '')), st_ev),
            ])
        tab = Table(righe, colWidths=[26 * mm, 7 * mm, W - 33 * mm])
        tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.5, LINE),
            ('LINEBELOW', (0, 0), (-1, -2), 0.4, colors.HexColor('#f0ece7')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TEXTCOLOR', (1, 0), (1, -1), ACCENT),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(tab)
        story.append(Spacer(1, 14))

    doc.build(story)
    buffer.seek(0)
    return buffer
