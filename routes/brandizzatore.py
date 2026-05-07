import io
import os
import json
import traceback
import anthropic
from flask import Blueprint, request, jsonify, send_file
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pptx import Presentation

brandizzatore_bp = Blueprint('brandizzatore', __name__)

COLORE_SCURO = RGBColor(0x37, 0x39, 0x3f)
COLORE_TERRACOTTA = RGBColor(0xc4, 0x62, 0x2d)
COLORE_AVORIO = RGBColor(0xf5, 0xf2, 0xee)


# ── WORD endpoint (invariato) ──

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


# ── PPTX endpoint — v3: Claude API + WeasyPrint ──

def estrai_testo_slides(file):
    prs = Presentation(file)
    slides_data = []

    for i, slide in enumerate(prs.slides):
        testi = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    testo = para.text.strip()
                    if testo:
                        size = None
                        if para.runs and para.runs[0].font.size:
                            size = para.runs[0].font.size
                        testi.append({
                            'testo': testo,
                            'size': size
                        })

        titolo = ''
        contenuto = []

        if testi:
            testi_con_size = [t for t in testi if t['size']]
            if testi_con_size:
                testi_con_size.sort(
                    key=lambda x: x['size'], reverse=True)
                titolo = testi_con_size[0]['testo']
                contenuto = [t['testo'] for t in testi
                             if t['testo'] != titolo]
            else:
                titolo = testi[0]['testo']
                contenuto = [t['testo'] for t in testi[1:]]

        slides_data.append({
            'numero': i + 1,
            'titolo': titolo,
            'contenuto': contenuto
        })

    return slides_data


def genera_html_presentazione(slides_data):
    client = anthropic.Anthropic(
        api_key=os.environ.get('ANTHROPIC_API_KEY')
    )

    slides_json = json.dumps(slides_data,
                             ensure_ascii=False,
                             indent=2)

    prompt = f"""Sei un designer esperto.
Genera una presentazione HTML/CSS professionale
e bellissima per SB Food Consulting.

Ecco il contenuto delle slide:
{slides_json}

DESIGN SYSTEM:
- Palette: #37393f scuro, #c4622d terracotta,
  #f5f2ee avorio, #ffffff bianco, #5a5a5a grigio
- Font: Playfair Display (titoli), Inter (corpo)
- Ogni slide: 297x210mm, class="slide",
  page-break-after: always

STRUTTURA RICHIESTA:

1. SLIDE COPERTINA (prima):
   - Sfondo #37393f pieno
   - Blocco verticale terracotta a sinistra (15px width)
   - "SB FOOD CONSULTING" uppercase tracking-widest
     terracotta in alto, font-size 11px
   - Titolo presentazione (dalla prima slide)
     bianco Playfair Display 42px bold al centro
   - Anno corrente grigio chiaro in basso
   - sbfoodconsulting.com grigio in basso

2. SLIDE CONTENUTO DISPARI (sfondo #37393f):
   - Blocco verticale terracotta sinistra (8px)
   - "SB Food Consulting" terracotta top-right 9px
   - Numero slide terracotta bottom-left 9px
   - Titolo: Playfair Display italic #c4622d 26px
   - Contenuto: Inter 15px bianco,
     bullet "—" terracotta, line-height 1.9
   - Padding generoso: 50px

3. SLIDE CONTENUTO PARI (sfondo #f5f2ee):
   - Bordo top terracotta 6px
   - "SB Food Consulting" #37393f top-right 9px
   - Numero slide #c4622d bottom-right 9px
   - Titolo: Playfair Display #37393f 26px bold
   - Linea decorativa terracotta sotto titolo 40px
   - Contenuto: Inter 15px #5a5a5a,
     bullet "—" terracotta, line-height 1.9
   - Padding generoso: 50px

4. SLIDE FINALE CTA (ultima):
   - Sfondo #c4622d pieno
   - "Prenota una consulenza gratuita."
     bianco Playfair Display 40px bold centrato
   - Linea bianca 60px sotto
   - "calendly.com/sbfoodconsulting-info/30min"
     bianco Inter 16px centrato
   - "SB FOOD CONSULTING" bianco uppercase
     tracking-widest 10px in basso centrato

CSS IMPORTANTE:
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=Inter:wght@300;400;600&display=swap');
@page {{ size: A4 landscape; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', sans-serif; }}
.slide {{
    width: 297mm; height: 210mm;
    page-break-after: always;
    position: relative; overflow: hidden;
    display: flex; flex-direction: column;
    justify-content: center;
}}

Genera l'HTML completo con tutte le slide.
Restituisci SOLO il codice HTML grezzo,
nessun testo prima o dopo, nessun markdown."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def converti_html_in_pdf(html_content):
    try:
        from weasyprint import HTML as WeasyHTML
        pdf_buffer = io.BytesIO()
        WeasyHTML(string=html_content).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        return pdf_buffer
    except ImportError:
        raise Exception(
            "WeasyPrint non disponibile sul server")


@brandizzatore_bp.route('/api/brandizza/pptx', methods=['POST'])
def brandizza_pptx():
    if 'file' not in request.files:
        return jsonify({'error': 'Nessun file'}), 400

    try:
        file = request.files['file']

        slides_data = estrai_testo_slides(file)
        print(f"Estratte {len(slides_data)} slide")

        html = genera_html_presentazione(slides_data)
        print("HTML generato da Claude")

        pdf_buffer = converti_html_in_pdf(html)
        print("PDF generato con WeasyPrint")

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='presentazione-sbfood.pdf'
        )

    except Exception as e:
        traceback.print_exc()
        print(f"ERRORE PPTX: {e}")
        return jsonify({'error': str(e)}), 500
