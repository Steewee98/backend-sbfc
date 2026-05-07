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
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Nessun file'}), 400

        file = request.files['file']
        prs = Presentation(file)

        SCURO = PptxRGB(0x37, 0x39, 0x3f)
        TERRACOTTA = PptxRGB(0xc4, 0x62, 0x2d)
        AVORIO = PptxRGB(0xf5, 0xf2, 0xee)
        BIANCO = PptxRGB(0xFF, 0xFF, 0xFF)

        slide_width = prs.slide_width
        slide_height = prs.slide_height

        # Titolo originale dalla prima slide (per copertina)
        titolo_presentazione = 'Presentazione'
        try:
            if len(prs.slides) > 0 and prs.slides[0].shapes.title:
                titolo_presentazione = prs.slides[0].shapes.title.text or titolo_presentazione
        except Exception:
            pass

        for i, slide in enumerate(prs.slides):
            # Sfondo alternato
            bg = slide.background.fill
            bg.solid()
            if i % 2 == 0:
                bg.fore_color.rgb = SCURO
                testo_colore = BIANCO
                titolo_colore = TERRACOTTA
            else:
                bg.fore_color.rgb = AVORIO
                testo_colore = SCURO
                titolo_colore = TERRACOTTA

            # Colora testi
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                is_title = shape == slide.shapes.title if slide.shapes.title else False
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if is_title:
                            run.font.color.rgb = titolo_colore
                        else:
                            run.font.color.rgb = testo_colore

            # Logo testuale in alto a destra
            txBox = slide.shapes.add_textbox(
                slide_width - PptxInches(2.5),
                PptxInches(0.1),
                PptxInches(2.3),
                PptxInches(0.4)
            )
            tf = txBox.text_frame
            tf.text = 'SB Food Consulting'
            tf.paragraphs[0].runs[0].font.size = PptxPt(9)
            tf.paragraphs[0].runs[0].font.color.rgb = TERRACOTTA
            tf.paragraphs[0].runs[0].font.bold = True
            tf.paragraphs[0].alignment = PP_ALIGN.RIGHT

        # Slide copertina (inserita all'inizio)
        # Usa l'ultimo layout disponibile o il primo come fallback
        layout_index = min(6, len(prs.slide_layouts) - 1)
        slide_layout = prs.slide_layouts[layout_index]
        cover = prs.slides.add_slide(slide_layout)
        bg = cover.background.fill
        bg.solid()
        bg.fore_color.rgb = SCURO

        # Logo grande centrato
        txLogo = cover.shapes.add_textbox(
            PptxInches(1.5), PptxInches(1.8),
            PptxInches(7), PptxInches(1.2)
        )
        tfLogo = txLogo.text_frame
        tfLogo.word_wrap = True
        pLogo = tfLogo.paragraphs[0]
        pLogo.text = 'SB Food Consulting'
        pLogo.runs[0].font.size = PptxPt(40)
        pLogo.runs[0].font.bold = True
        pLogo.runs[0].font.color.rgb = TERRACOTTA
        pLogo.alignment = PP_ALIGN.CENTER

        # Titolo presentazione
        txTitle = cover.shapes.add_textbox(
            PptxInches(1.5), PptxInches(3.2),
            PptxInches(7), PptxInches(1)
        )
        tfTitle = txTitle.text_frame
        tfTitle.word_wrap = True
        pTitle = tfTitle.paragraphs[0]
        pTitle.text = titolo_presentazione
        pTitle.runs[0].font.size = PptxPt(24)
        pTitle.runs[0].font.color.rgb = BIANCO
        pTitle.alignment = PP_ALIGN.CENTER

        # Linea decorativa
        txLine = cover.shapes.add_textbox(
            PptxInches(3.5), PptxInches(3),
            PptxInches(3), PptxInches(0.15)
        )
        tfLine = txLine.text_frame
        pLine = tfLine.paragraphs[0]
        pLine.text = '______________________________'
        pLine.runs[0].font.size = PptxPt(8)
        pLine.runs[0].font.color.rgb = TERRACOTTA
        pLine.alignment = PP_ALIGN.CENTER

        # Sposta copertina all'inizio
        xml_slides = prs.slides._sldIdLst
        slides_list = list(xml_slides)
        cover_elem = slides_list[-1]
        xml_slides.remove(cover_elem)
        xml_slides.insert(0, cover_elem)

        # Slide finale CTA
        slide_finale = prs.slides.add_slide(slide_layout)
        bg = slide_finale.background.fill
        bg.solid()
        bg.fore_color.rgb = SCURO

        txCta = slide_finale.shapes.add_textbox(
            PptxInches(1), PptxInches(2.5),
            PptxInches(8), PptxInches(1.5)
        )
        tfCta = txCta.text_frame
        tfCta.word_wrap = True
        pCta = tfCta.paragraphs[0]
        pCta.text = 'Prenota una consulenza gratuita'
        pCta.runs[0].font.size = PptxPt(32)
        pCta.runs[0].font.bold = True
        pCta.runs[0].font.color.rgb = BIANCO
        pCta.alignment = PP_ALIGN.CENTER

        txUrl = slide_finale.shapes.add_textbox(
            PptxInches(1), PptxInches(4),
            PptxInches(8), PptxInches(0.8)
        )
        tfUrl = txUrl.text_frame
        pUrl = tfUrl.paragraphs[0]
        pUrl.text = 'calendly.com/sbfoodconsulting-info/30min'
        pUrl.runs[0].font.size = PptxPt(16)
        pUrl.runs[0].font.color.rgb = TERRACOTTA
        pUrl.alignment = PP_ALIGN.CENTER

        # Logo sulla slide finale
        txLogoFin = slide_finale.shapes.add_textbox(
            slide_width - PptxInches(2.5),
            PptxInches(0.1),
            PptxInches(2.3),
            PptxInches(0.4)
        )
        tfLogoFin = txLogoFin.text_frame
        tfLogoFin.text = 'SB Food Consulting'
        tfLogoFin.paragraphs[0].runs[0].font.size = PptxPt(9)
        tfLogoFin.paragraphs[0].runs[0].font.color.rgb = TERRACOTTA
        tfLogoFin.paragraphs[0].runs[0].font.bold = True
        tfLogoFin.paragraphs[0].alignment = PP_ALIGN.RIGHT

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
        print(f"ERRORE PPTX: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
