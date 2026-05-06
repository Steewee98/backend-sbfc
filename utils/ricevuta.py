from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO
from datetime import datetime


def genera_ricevuta_pdf(nome, email, moduli,
                         prodotto_nome, importo,
                         stripe_id=None):

    nomi_moduli = {
        1: 'Modulo 1 — Hai davvero il controllo del tuo ristorante?',
        2: 'Modulo 2 — Stai pagando per i risultati giusti?',
        3: 'Modulo 3 — Cosa ti blocca dal crescere?',
        4: "Modulo 4 — L'Arte di Accogliere nel Food",
        5: 'Modulo 5 — Come prepararsi al lancio del tuo locale',
        'corso-completo': 'SB Food Academy — Corso Completo'
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    DARK = colors.HexColor('#37393f')
    ACCENT = colors.HexColor('#c4622d')
    IVORY = colors.HexColor('#f5f2ee')
    GRAY = colors.HexColor('#5a5a5a')

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'title', fontSize=22, fontName='Helvetica-Bold',
        textColor=colors.white, leading=28
    )
    subtitle_style = ParagraphStyle(
        'subtitle', fontSize=11, fontName='Helvetica',
        textColor=colors.HexColor('#c4622d'), leading=16
    )
    body_style = ParagraphStyle(
        'body', fontSize=10, fontName='Helvetica',
        textColor=GRAY, leading=16
    )
    label_style = ParagraphStyle(
        'label', fontSize=8, fontName='Helvetica-Bold',
        textColor=GRAY, leading=12,
        spaceBefore=4
    )

    story = []

    # HEADER scuro
    header_data = [[
        Paragraph('SB Food Academy', title_style),
        Paragraph('Ricevuta di pagamento', subtitle_style)
    ]]
    header_table = Table(header_data,
                         colWidths=[100*mm, 70*mm])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (0,-1), 8*mm),
        ('RIGHTPADDING', (-1,0), (-1,-1), 8*mm),
        ('TOPPADDING', (0,0), (-1,-1), 8*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8*mm),
        ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8*mm))

    # INFO CLIENTE E DATA
    data_oggi = datetime.utcnow().strftime('%d/%m/%Y')
    numero_ricevuta = f"SBF-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    info_data = [
        [Paragraph('CLIENTE', label_style),
         Paragraph('DATA', label_style),
         Paragraph('N. RICEVUTA', label_style)],
        [Paragraph(f'{nome}<br/>{email}', body_style),
         Paragraph(data_oggi, body_style),
         Paragraph(numero_ricevuta, body_style)],
    ]
    info_table = Table(info_data,
                       colWidths=[80*mm, 40*mm, 50*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), IVORY),
        ('TOPPADDING', (0,0), (-1,-1), 4*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 4*mm),
        ('LINEBELOW', (0,0), (-1,0), 0.5,
         colors.HexColor('#d9d4cc')),
        ('LINEBELOW', (0,1), (-1,1), 0.5,
         colors.HexColor('#d9d4cc')),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8*mm))

    # DETTAGLIO ACQUISTO
    story.append(Paragraph('DETTAGLIO ACQUISTO', label_style))
    story.append(Spacer(1, 3*mm))

    items_data = [
        [Paragraph('Descrizione', label_style),
         Paragraph('Importo', label_style)]
    ]

    if isinstance(moduli, list) and len(moduli) > 0:
        if len(moduli) == 5:
            desc = 'SB Food Academy — Corso Completo\n5 moduli operativi'
        else:
            desc = '\n'.join([nomi_moduli.get(m, f'Modulo {m}')
                             for m in moduli])
        items_data.append([
            Paragraph(desc, body_style),
            Paragraph(f'{importo:.2f} €', body_style)
        ])

    items_data.append([
        Paragraph('', body_style),
        Paragraph('')
    ])
    items_data.append([
        Paragraph('<b>TOTALE</b>',
                  ParagraphStyle('bold', fontSize=11,
                  fontName='Helvetica-Bold',
                  textColor=DARK)),
        Paragraph(f'<b>{importo:.2f} €</b>',
                  ParagraphStyle('bold_accent', fontSize=12,
                  fontName='Helvetica-Bold',
                  textColor=ACCENT))
    ])

    items_table = Table(items_data,
                        colWidths=[130*mm, 40*mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), IVORY),
        ('LINEBELOW', (0,0), (-1,0), 0.5,
         colors.HexColor('#d9d4cc')),
        ('LINEABOVE', (0,-1), (-1,-1), 1, DARK),
        ('BACKGROUND', (0,-1), (-1,-1), IVORY),
        ('TOPPADDING', (0,0), (-1,-1), 4*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4*mm),
        ('LEFTPADDING', (0,0), (-1,-1), 4*mm),
        ('ALIGN', (-1,0), (-1,-1), 'RIGHT'),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 8*mm))

    # STRIPE ID
    if stripe_id:
        story.append(Paragraph(
            f'ID transazione: {stripe_id}',
            ParagraphStyle('small', fontSize=8,
            fontName='Helvetica',
            textColor=colors.HexColor('#a0a0a0'))
        ))
        story.append(Paragraph(
            'Pagamento processato tramite Stripe',
            ParagraphStyle('small', fontSize=8,
            fontName='Helvetica',
            textColor=colors.HexColor('#a0a0a0'))
        ))

    story.append(Spacer(1, 12*mm))

    # FOOTER
    footer_data = [[
        Paragraph(
            'SB Food Consulting — Roma, Italia | '
            'info@sbfoodconsulting.com | '
            'www.sbfoodconsulting.com',
            ParagraphStyle('footer', fontSize=8,
            fontName='Helvetica',
            textColor=colors.white,
            alignment=1)
        )
    ]]
    footer_table = Table(footer_data,
                         colWidths=[170*mm])
    footer_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK),
        ('TOPPADDING', (0,0), (-1,-1), 4*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4*mm),
    ]))
    story.append(footer_table)

    doc.build(story)
    buffer.seek(0)
    return buffer
