import io
import traceback
from flask import Blueprint, request, jsonify, send_file
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pptx import Presentation
from pptx.util import Inches as PptxInches, Pt as PptxPt
from pptx.dml.color import RGBColor as PptxRGB
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn

brandizzatore_bp = Blueprint('brandizzatore', __name__)

COLORE_SCURO = RGBColor(0x37, 0x39, 0x3f)
COLORE_TERRACOTTA = RGBColor(0xc4, 0x62, 0x2d)
COLORE_AVORIO = RGBColor(0xf5, 0xf2, 0xee)


@brandizzatore_bp.route('/api/brandizza/word', methods=['POST'])
def brandizza_word():
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file'}), 400

    file = request.files['file']
    doc = Document(file)

    # Modifica stili paragrafi
    for para in doc.paragraphs:
        if para.style.name.startswith('Heading'):
            for run in para.runs:
                run.font.color.rgb = COLORE_TERRACOTTA
                run.font.bold = True
        else:
            for run in para.runs:
                if run.font.color and run.font.color.type is not None:
                    run.font.color.rgb = COLORE_SCURO

    # Modifica stili nelle tabelle
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for run in para.runs:
                        if run.font.color and run.font.color.type is not None:
                            run.font.color.rgb = COLORE_SCURO

    # Header su tutte le sezioni
    for section in doc.sections:
        header = section.header
        header.is_linked_to_previous = False
        if header.paragraphs:
            header.paragraphs[0].clear()
        else:
            header.add_paragraph()
        header_para = header.paragraphs[0]
        header_run = header_para.add_run('SB Food Consulting')
        header_run.font.color.rgb = COLORE_TERRACOTTA
        header_run.font.bold = True
        header_run.font.size = Pt(10)
        header_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        # Linea terracotta sotto header
        border_run = header_para.add_run('\n')
        border_run.font.size = Pt(2)

        # Footer
        footer = section.footer
        footer.is_linked_to_previous = False
        if footer.paragraphs:
            footer.paragraphs[0].clear()
        else:
            footer.add_paragraph()
        footer_para = footer.paragraphs[0]
        footer_run = footer_para.add_run(
            'SB Food Consulting  |  info@sbfoodconsulting.com  |  www.sbfoodconsulting.com'
        )
        footer_run.font.color.rgb = COLORE_SCURO
        footer_run.font.size = Pt(8)
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name='contratto-sbfood-brandizzato.docx'
    )


@brandizzatore_bp.route('/api/brandizza/pptx', methods=['POST'])
def brandizza_pptx():
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file'}), 400

    try:
        from datetime import datetime

        file = request.files['file']
        prs_orig = Presentation(file)

        # ── PALETTE ──
        SCURO = PptxRGB(0x37, 0x39, 0x3f)
        TERRACOTTA = PptxRGB(0xc4, 0x62, 0x2d)
        AVORIO = PptxRGB(0xf5, 0xf2, 0xee)
        BIANCO = PptxRGB(0xFF, 0xFF, 0xFF)
        GRIGIO_TESTO = PptxRGB(0x5a, 0x5a, 0x5a)
        GRIGIO_INFO = PptxRGB(0x9a, 0x96, 0x90)

        # ── STEP 1: ESTRAI TESTO DA OGNI SLIDE ──
        slides_data = []
        for slide in prs_orig.slides:
            texts = []
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                for para in shape.text_frame.paragraphs:
                    line = para.text.strip()
                    if line:
                        # Stima dimensione font dal primo run
                        font_size = 0
                        if para.runs:
                            font_size = para.runs[0].font.size or 0
                        texts.append({
                            'text': line,
                            'size': font_size
                        })

            if not texts:
                continue

            # Il testo con font più grande = titolo
            texts.sort(key=lambda x: x['size'], reverse=True)
            titolo = texts[0]['text']
            contenuto = [t['text'] for t in texts[1:]
                         if t['text'] != titolo]

            slides_data.append({
                'titolo': titolo,
                'contenuto': contenuto
            })

        if not slides_data:
            return jsonify({'error': 'Nessun contenuto trovato'}), 400

        # ── STEP 2: CREA NUOVA PRESENTAZIONE ──
        prs = Presentation()
        prs.slide_width = prs_orig.slide_width
        prs.slide_height = prs_orig.slide_height
        sw = prs.slide_width
        sh = prs.slide_height

        layout_index = min(6, len(prs.slide_layouts) - 1)
        blank_layout = prs.slide_layouts[layout_index]

        # ── Helper: aggiungi rettangolo ──
        def add_rect(slide, left, top, width, height, color):
            from pptx.util import Emu
            shape = slide.shapes.add_shape(
                1, left, top, width, height)  # MSO_SHAPE.RECTANGLE
            shape.fill.solid()
            shape.fill.fore_color.rgb = color
            shape.line.fill.background()
            return shape

        # ── Helper: aggiungi testo ──
        def add_text(slide, left, top, width, height,
                     text, size, color, bold=False,
                     align=PP_ALIGN.LEFT):
            box = slide.shapes.add_textbox(left, top, width, height)
            tf = box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = text
            run.font.size = PptxPt(size)
            run.font.color.rgb = color
            run.font.bold = bold
            run.font.name = 'Calibri'
            p.alignment = align
            return tf

        # ── SLIDE COPERTINA ──
        cover = prs.slides.add_slide(blank_layout)
        fill = cover.background.fill
        fill.solid()
        fill.fore_color.rgb = SCURO

        # Rettangolo terracotta verticale sinistra (12px)
        add_rect(cover,
                 0, 0,
                 PptxInches(0.17), sh,
                 TERRACOTTA)

        # Brand name uppercase
        add_text(cover,
                 PptxInches(0.8), PptxInches(1.5),
                 PptxInches(8), PptxInches(0.5),
                 'SB FOOD CONSULTING', 11,
                 TERRACOTTA, bold=True)

        # Titolo grande
        add_text(cover,
                 PptxInches(0.8), PptxInches(2.4),
                 PptxInches(8), PptxInches(2.5),
                 slides_data[0]['titolo'], 32,
                 BIANCO, bold=True)

        # Anno
        add_text(cover,
                 PptxInches(0.8), PptxInches(4.5),
                 PptxInches(3), PptxInches(0.5),
                 str(datetime.utcnow().year), 14,
                 GRIGIO_INFO)

        # Sito in basso
        add_text(cover,
                 PptxInches(0.8), sh - PptxInches(0.7),
                 PptxInches(6), PptxInches(0.5),
                 'sbfoodconsulting.com', 9,
                 GRIGIO_INFO)

        # ── SLIDE CONTENUTO ──
        for i, data in enumerate(slides_data):
            slide = prs.slides.add_slide(blank_layout)
            is_odd = (i % 2 == 0)  # 0-indexed, prima slide contenuto = dispari

            fill = slide.background.fill
            fill.solid()

            if is_odd:
                # SLIDE DISPARI — sfondo scuro
                fill.fore_color.rgb = SCURO
                col_titolo = TERRACOTTA
                col_testo = AVORIO
                col_logo = TERRACOTTA

                # Rettangolo accent sinistra (8px)
                add_rect(slide,
                         0, 0,
                         PptxInches(0.11), sh,
                         TERRACOTTA)

                # Numero slide in basso a sinistra
                add_text(slide,
                         PptxInches(0.5), sh - PptxInches(0.6),
                         PptxInches(1), PptxInches(0.4),
                         str(i + 1), 9,
                         TERRACOTTA)

            else:
                # SLIDE PARI — sfondo chiaro
                fill.fore_color.rgb = AVORIO
                col_titolo = SCURO
                col_testo = GRIGIO_TESTO
                col_logo = SCURO

                # Rettangolo terracotta in alto (8px)
                add_rect(slide,
                         0, 0,
                         sw, PptxInches(0.11),
                         TERRACOTTA)

                # Numero slide in basso a destra
                add_text(slide,
                         sw - PptxInches(1.2), sh - PptxInches(0.6),
                         PptxInches(1), PptxInches(0.4),
                         str(i + 1), 9,
                         TERRACOTTA, align=PP_ALIGN.RIGHT)

            # Logo in alto a destra
            add_text(slide,
                     sw - PptxInches(2.8), PptxInches(0.2),
                     PptxInches(2.6), PptxInches(0.4),
                     'SB Food Consulting', 9,
                     col_logo, bold=True,
                     align=PP_ALIGN.RIGHT)

            # Titolo
            add_text(slide,
                     PptxInches(0.8), PptxInches(1.2),
                     PptxInches(8), PptxInches(1.2),
                     data['titolo'], 28,
                     col_titolo, bold=True)

            # Contenuto con bullet points
            if data['contenuto']:
                content_box = slide.shapes.add_textbox(
                    PptxInches(0.8), PptxInches(2.8),
                    PptxInches(8), PptxInches(4))
                content_tf = content_box.text_frame
                content_tf.word_wrap = True

                for j, punto in enumerate(data['contenuto']):
                    if j == 0:
                        p = content_tf.paragraphs[0]
                    else:
                        p = content_tf.add_paragraph()
                    run = p.add_run()
                    run.text = f'—  {punto}'
                    run.font.size = PptxPt(16)
                    run.font.color.rgb = col_testo
                    run.font.name = 'Calibri'
                    p.space_after = PptxPt(12)

        # ── SLIDE FINALE CTA ──
        finale = prs.slides.add_slide(blank_layout)
        fill = finale.background.fill
        fill.solid()
        fill.fore_color.rgb = TERRACOTTA

        add_text(finale,
                 PptxInches(0.8), PptxInches(2.0),
                 PptxInches(8.5), PptxInches(1.8),
                 'Prenota una\nconsulenza gratuita.', 36,
                 BIANCO, bold=True)

        add_text(finale,
                 PptxInches(0.8), PptxInches(4.0),
                 PptxInches(8.5), PptxInches(0.8),
                 'calendly.com/sbfoodconsulting-info/30min', 14,
                 BIANCO)

        add_text(finale,
                 PptxInches(0.8), sh - PptxInches(0.7),
                 PptxInches(8), PptxInches(0.5),
                 'SB FOOD CONSULTING', 9,
                 BIANCO, bold=True)

        # ── OUTPUT ──
        output = io.BytesIO()
        prs.save(output)
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
            as_attachment=True,
            download_name='presentazione-sbfood-brandizzata.pptx'
        )

    except Exception as e:
        traceback.print_exc()
        print(f"ERRORE PPTX: {e}")
        return jsonify({'error': str(e)}), 500
