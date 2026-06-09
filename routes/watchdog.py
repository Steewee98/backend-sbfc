"""Watchdog — controllo automatico salute del sistema.

Gira ogni 6 ore, controlla e corregge problemi comuni:
- Lead nel foglio Google non importati
- Messaggi WhatsApp in errore da ritentare
- Prenotazioni senza telefono (cerca nei contatti)
- Nomi troncati o spazzatura da pulire
- Reminder non inviati a prenotazioni attive

Manda un report WhatsApp a Simone solo se trova problemi.
"""
import os
import re
import requests
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from models import db, Contatto, Prenotazione, MessaggioWhatsapp

watchdog_bp = Blueprint('watchdog', __name__)

SIMONE_PHONE = os.environ.get('SIMONE_PHONE', '+393382636677')


def _is_spam_name(nome):
    """Rileva nomi spam/spazzatura."""
    if not nome:
        return True
    if len(nome) > 80:
        return True
    # Troppi caratteri ripetuti
    if re.search(r'(.)\1{5,}', nome):
        return True
    # Solo simboli/unicode strani
    lettere = sum(1 for c in nome if c.isalpha())
    if len(nome) > 3 and lettere / len(nome) < 0.4:
        return True
    return False


def run_watchdog():
    """Esegue tutti i controlli e ritorna un report."""
    problemi = []
    fix = []

    # --- 1. Lead mancanti dal foglio Google ---
    try:
        from routes.google_leads import SPREADSHEET_ID
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0"
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            content = res.content.decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            mancanti = 0
            for riga in reader:
                telefono = ''
                for key in ['phone', 'Phone', 'Telefono']:
                    if key in riga and str(riga[key]).strip():
                        telefono = str(riga[key]).strip()
                        break
                if not telefono:
                    for key in riga.keys():
                        if key.lower() in ['phone', 'telefono', 'mobile']:
                            telefono = str(riga[key]).strip()
                            break
                if telefono.startswith('p:'):
                    telefono = telefono[2:].strip()
                if not telefono or '<test lead' in telefono.lower():
                    continue

                nome = ''
                for key in ['full_name', 'Full Name', 'Nome', 'nome']:
                    if key in riga and str(riga[key]).strip():
                        nome = str(riga[key]).strip()
                        break
                if '<test lead' in (nome or '').lower():
                    continue

                esistente = Contatto.query.filter_by(telefono=telefono).first()
                if not esistente:
                    # Prova con normalizzazione
                    from utils.whatsapp import normalizza_telefono
                    num_norm, _ = normalizza_telefono(telefono)
                    esistente = Contatto.query.filter_by(telefono=num_norm).first()

                if not esistente:
                    mancanti += 1

            if mancanti > 0:
                # Forza sync
                from routes.google_leads import _do_sync
                nuovi, _ = _do_sync()
                if nuovi > 0:
                    fix.append(f'{nuovi} lead mancanti importati dal foglio Google')
                elif mancanti > 0:
                    problemi.append(f'{mancanti} lead nel foglio non importabili (controllare manualmente)')
    except Exception as e:
        problemi.append(f'Errore controllo lead Google: {e}')

    # --- 2. Nomi spam/spazzatura da pulire ---
    try:
        contatti_spam = Contatto.query.filter(
            Contatto.tipo_locale == 'Lead Meta Ads'
        ).all()
        puliti = 0
        for c in contatti_spam:
            changed = False
            if _is_spam_name(c.nome):
                c.nome = 'Contatto'
                changed = True
            if c.cognome and _is_spam_name(c.cognome):
                c.cognome = ''
                changed = True
            # Tronca se troppo lungo
            if c.nome and len(c.nome) > 100:
                c.nome = c.nome[:100]
                changed = True
            if c.cognome and len(c.cognome) > 100:
                c.cognome = c.cognome[:100]
                changed = True
            if changed:
                db.session.commit()
                puliti += 1
        if puliti > 0:
            fix.append(f'{puliti} contatti con nomi spam puliti')
    except Exception as e:
        problemi.append(f'Errore pulizia nomi: {e}')

    # --- 3. Prenotazioni senza telefono ---
    try:
        pren_senza_tel = Prenotazione.query.filter(
            db.or_(Prenotazione.telefono == '', Prenotazione.telefono.is_(None)),
            Prenotazione.stato.notin_(['cancellato', 'non_confermato']),
            Prenotazione.data_appuntamento > datetime.utcnow()
        ).all()
        trovati = 0
        for pren in pren_senza_tel:
            telefono = None
            # Cerca per email
            if pren.email:
                contatto = Contatto.query.filter_by(email=pren.email).first()
                if contatto and contatto.telefono:
                    telefono = contatto.telefono
            # Cerca per nome
            if not telefono and pren.nome:
                for parte in pren.nome.split():
                    if len(parte) < 3:
                        continue
                    pat = f'%{parte.lower()}%'
                    contatto = Contatto.query.filter(
                        db.or_(
                            db.func.lower(Contatto.nome).like(pat),
                            db.func.lower(Contatto.cognome).like(pat)
                        ),
                        Contatto.telefono != '',
                        Contatto.telefono.isnot(None)
                    ).first()
                    if contatto:
                        telefono = contatto.telefono
                        break
            if telefono:
                pren.telefono = telefono
                db.session.commit()
                trovati += 1
        if trovati > 0:
            fix.append(f'{trovati} prenotazioni: telefono trovato dai contatti')
        non_trovati = len(pren_senza_tel) - trovati
        if non_trovati > 0:
            problemi.append(f'{non_trovati} prenotazioni future senza telefono')
    except Exception as e:
        problemi.append(f'Errore controllo prenotazioni: {e}')

    # --- 4. Messaggi WhatsApp in errore recenti (ultime 24h) ---
    try:
        ieri = datetime.utcnow() - timedelta(hours=24)
        errori_wa = MessaggioWhatsapp.query.filter(
            MessaggioWhatsapp.stato.in_(['errore', 'numero_invalido']),
            MessaggioWhatsapp.created_at >= ieri
        ).count()
        if errori_wa > 0:
            problemi.append(f'{errori_wa} messaggi WhatsApp in errore nelle ultime 24h')
    except Exception as e:
        problemi.append(f'Errore controllo WA: {e}')

    # --- 5. Contatti duplicati (stesso telefono) ---
    try:
        from sqlalchemy import func
        duplicati = db.session.query(
            Contatto.telefono, func.count(Contatto.id)
        ).filter(
            Contatto.telefono != '',
            Contatto.telefono.isnot(None)
        ).group_by(Contatto.telefono).having(
            func.count(Contatto.id) > 1
        ).count()
        if duplicati > 0:
            problemi.append(f'{duplicati} numeri di telefono duplicati nei contatti')
    except Exception as e:
        problemi.append(f'Errore controllo duplicati: {e}')

    return problemi, fix


REPORT_EMAIL = os.environ.get('WATCHDOG_EMAIL', 'info@stefanodemartis.com')

_last_report_sent = None
_report_lock = __import__('threading').Lock()


def send_watchdog_report(problemi, fix):
    """Manda report via email solo se ci sono problemi/fix. Max 1 ogni ora."""
    global _last_report_sent
    if not problemi and not fix:
        return

    with _report_lock:
        now = datetime.utcnow()
        if _last_report_sent and (now - _last_report_sent).total_seconds() < 3600:
            print("[WATCHDOG] Report già inviato nell'ultima ora, skip")
            return
        _last_report_sent = now

    from utils.email import invia_email

    data_str = datetime.utcnow().strftime('%d/%m/%Y %H:%M')

    html = f"""<h2>Report Sistema — SB Food Consulting</h2>
    <p style="color:#5a5a5a;font-size:14px">{data_str} UTC</p>"""

    if fix:
        html += '<h3 style="color:#1e8449">Corretto automaticamente</h3><ul>'
        for f in fix:
            html += f'<li>{f}</li>'
        html += '</ul>'

    if problemi:
        html += '<h3 style="color:#c0392b">Problemi da verificare</h3><ul>'
        for p in problemi:
            html += f'<li>{p}</li>'
        html += '</ul>'

    if not problemi:
        html += '<p style="color:#1e8449;font-weight:bold">Nessun problema in sospeso.</p>'

    html += '<hr><p style="color:#999;font-size:12px">Watchdog automatico — <a href="https://www.sbfoodconsulting.com/admin.html">Apri gestionale</a></p>'

    try:
        invia_email(
            REPORT_EMAIL, 'Stefano',
            f'Report Sistema SB Food — {data_str}',
            html
        )
    except Exception as e:
        print(f"[WATCHDOG] Errore invio report email: {e}")


# --- Endpoint manuale ---
@watchdog_bp.route('/api/watchdog', methods=['POST'])
def run_watchdog_endpoint():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    problemi, fix = run_watchdog()

    send_report = request.args.get('report', 'false') == 'true'
    if send_report:
        send_watchdog_report(problemi, fix)

    return jsonify({
        'problemi': problemi,
        'fix_applicati': fix,
        'stato': 'ok' if not problemi else 'attenzione'
    })
