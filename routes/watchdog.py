"""Watchdog — monitora che il sistema funzioni.

Gira ogni 6 ore. Controlla SOLO problemi che bloccano il funzionamento:
1. Lead sync rotto (lead nelle ads non arrivano nel gestionale)
2. WhatsApp rotto (tutti i messaggi falliscono)
3. Reminder non partono (prenotazioni saltate)

Se trova problemi, prova a correggerli. Manda email solo se non riesce.
"""
import os
import threading
import requests
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from models import db, Contatto, Prenotazione, MessaggioWhatsapp

watchdog_bp = Blueprint('watchdog', __name__)

REPORT_EMAIL = os.environ.get('WATCHDOG_EMAIL', 'info@stefanodemartis.com')
_last_report_sent = None
_report_lock = threading.Lock()


def run_watchdog():
    """Controlla funzionalita' critiche. Ritorna (problemi, fix)."""
    problemi = []
    fix = []

    # --- 1. Lead sync: ci sono lead nelle ads non importati? ---
    try:
        from routes.google_leads import SPREADSHEET_ID, _do_sync
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

                from utils.whatsapp import normalizza_telefono
                num_norm, _ = normalizza_telefono(telefono)
                esistente = Contatto.query.filter(
                    db.or_(
                        Contatto.telefono == telefono,
                        Contatto.telefono == num_norm
                    )
                ).first()
                if not esistente:
                    mancanti += 1

            if mancanti > 0:
                nuovi, _ = _do_sync()
                if nuovi > 0:
                    fix.append(f'{nuovi} lead mancanti recuperati')
                else:
                    problemi.append(
                        f'{mancanti} lead dalle ads non importabili — '
                        f'sync bloccato, controllare i log')
        elif res.status_code != 200:
            problemi.append(
                f'Google Sheet non raggiungibile (HTTP {res.status_code}) — '
                f'i nuovi lead non vengono importati')
    except Exception as e:
        problemi.append(f'Sync lead rotto: {e}')

    # --- 2. WhatsApp: gli ultimi messaggi stanno andando? ---
    try:
        ultime_6h = datetime.utcnow() - timedelta(hours=6)
        recenti = MessaggioWhatsapp.query.filter(
            MessaggioWhatsapp.created_at >= ultime_6h
        ).all()
        if recenti:
            errori = [m for m in recenti if m.stato == 'errore']
            # Problema solo se TUTTI i messaggi recenti falliscono
            if len(errori) == len(recenti) and len(recenti) >= 2:
                problemi.append(
                    f'WhatsApp completamente fermo — '
                    f'tutti gli ultimi {len(recenti)} messaggi in errore. '
                    f'Controllare UltraMsg/abbonamento')
    except Exception as e:
        problemi.append(f'Controllo WhatsApp fallito: {e}')

    # --- 3. Reminder: prenotazioni future senza reminder che doveva partire ---
    try:
        now = datetime.utcnow()
        # Prenotazioni entro 2 giorni senza reminder_2d inviato
        tra_2gg = now + timedelta(days=2)
        pren_senza_2d = Prenotazione.query.filter(
            Prenotazione.data_appuntamento <= tra_2gg,
            Prenotazione.data_appuntamento > now,
            Prenotazione.reminder_2d_inviato == False,
            Prenotazione.stato.notin_(['cancellato', 'non_confermato']),
            Prenotazione.telefono != '',
            Prenotazione.telefono.isnot(None)
        ).all()

        if pren_senza_2d:
            # Forza invio reminder
            from routes.prenotazioni import _check_reminders
            _check_reminders()
            # Verifica se ha funzionato
            ancora_senza = Prenotazione.query.filter(
                Prenotazione.id.in_([p.id for p in pren_senza_2d]),
                Prenotazione.reminder_2d_inviato == False
            ).count()
            inviati = len(pren_senza_2d) - ancora_senza
            if inviati > 0:
                fix.append(f'{inviati} reminder in ritardo inviati')
            if ancora_senza > 0:
                problemi.append(
                    f'{ancora_senza} prenotazioni vicine senza reminder — '
                    f'il sistema reminder non funziona')
    except Exception as e:
        problemi.append(f'Controllo reminder fallito: {e}')

    return problemi, fix


def send_watchdog_report(problemi, fix):
    """Manda email solo se ci sono problemi critici. Max 1 ogni ora."""
    global _last_report_sent
    if not problemi and not fix:
        return

    with _report_lock:
        now = datetime.utcnow()
        if _last_report_sent and (now - _last_report_sent).total_seconds() < 3600:
            return
        _last_report_sent = now

    from utils.email import invia_email

    data_str = datetime.utcnow().strftime('%d/%m/%Y %H:%M')

    html = f"""<h2 style="font-family:Arial,sans-serif">Report Sistema SB Food</h2>
    <p style="color:#5a5a5a;font-size:14px">{data_str} UTC</p>"""

    if fix:
        html += '<h3 style="color:#1e8449">Corretto automaticamente</h3><ul>'
        for f in fix:
            html += f'<li>{f}</li>'
        html += '</ul>'

    if problemi:
        html += '<h3 style="color:#c0392b">Richiede attenzione</h3><ul>'
        for p in problemi:
            html += f'<li>{p}</li>'
        html += '</ul>'
    else:
        html += '<p style="color:#1e8449">Tutto corretto, nessun intervento manuale necessario.</p>'

    html += '<hr><p style="color:#999;font-size:12px"><a href="https://www.sbfoodconsulting.com/admin.html">Apri gestionale</a></p>'

    try:
        invia_email(REPORT_EMAIL, 'Stefano',
                    f'Report Sistema SB Food — {data_str}', html)
    except Exception as e:
        print(f"[WATCHDOG] Errore invio email: {e}")


@watchdog_bp.route('/api/watchdog', methods=['POST'])
def run_watchdog_endpoint():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    problemi, fix = run_watchdog()

    if request.args.get('report') == 'true':
        send_watchdog_report(problemi, fix)

    return jsonify({
        'problemi': problemi,
        'fix_applicati': fix,
        'stato': 'ok' if not problemi else 'attenzione'
    })
