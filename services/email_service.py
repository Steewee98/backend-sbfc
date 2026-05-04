import os
import logging
import threading
import resend

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')


def _send_email(nome: str, destinatario: str):
    """Invio effettivo via Resend API (eseguito in thread separato)."""
    resend.api_key = os.environ.get('RESEND_API_KEY')
    mail_from = os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>')

    # Carica template
    template_path = os.path.join(TEMPLATES_DIR, 'email_benvenuto.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    html_content = html_content.replace('[NOME]', nome)

    text_content = (
        f"Grazie per averci contattato, {nome}.\n\n"
        "Abbiamo ricevuto la tua richiesta e ti risponderemo personalmente entro 24 ore.\n\n"
        "Prenota una chiamata gratuita di 30 minuti con Simone Braghetta:\n"
        "https://calendly.com/sbfoodconsulting-info/30min\n\n"
        "---\n"
        "SB Food Consulting \u2014 Roma, Italia\n"
        "info@sbfoodconsulting.com\n"
    )

    try:
        params: resend.Emails.SendParams = {
            "from": mail_from,
            "to": [destinatario],
            "subject": f"Grazie per averci contattato, {nome} \u2014 SB Food Consulting",
            "html": html_content,
            "text": text_content,
        }
        email = resend.Emails.send(params)
        logger.info(f"Email benvenuto inviata a {destinatario} (id: {email['id']})")
    except Exception as e:
        logger.error(f"Errore invio email a {destinatario}: {e}")


def invia_email_benvenuto(nome: str, destinatario: str):
    """Invia email di benvenuto in background (non blocca la risposta API)."""
    api_key = os.environ.get('RESEND_API_KEY')

    if not api_key:
        logger.warning("RESEND_API_KEY non configurata, email non inviata")
        return

    thread = threading.Thread(target=_send_email, args=(nome, destinatario), daemon=True)
    thread.start()


# ─── Email credenziali Academy ───────────────────────────

NOMI_MODULI = {
    1: 'Hai davvero il controllo del tuo ristorante?',
    2: 'Stai pagando per i risultati giusti?',
    3: 'Cosa ti blocca dal crescere?',
    4: "L'Arte di Accogliere nel Food",
    5: 'Come prepararsi al lancio del tuo locale',
}


def _send_credenziali_email(nome: str, destinatario: str, password: str, moduli: list):
    """Invio credenziali via Resend API (eseguito in thread separato)."""
    resend.api_key = os.environ.get('RESEND_API_KEY')
    mail_from = os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>')
    frontend_url = os.environ.get('FRONTEND_URL', 'https://sito-sbfc-production.up.railway.app')

    # Carica template
    template_path = os.path.join(TEMPLATES_DIR, 'email_credenziali.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Genera lista moduli HTML
    moduli_html = ''
    for m in sorted(moduli):
        nome_modulo = NOMI_MODULI.get(m, f'Modulo {m:02d}')
        moduli_html += (
            f'<tr><td style="padding:8px 12px;border-bottom:1px solid #edeae5;color:#37393f;font-size:14px">'
            f'Modulo {m:02d} &mdash; {nome_modulo}</td></tr>'
        )

    html_content = html_content.replace('[NOME]', nome)
    html_content = html_content.replace('[EMAIL]', destinatario)
    html_content = html_content.replace('[PASSWORD]', password)
    html_content = html_content.replace('[MODULI]', moduli_html)
    html_content = html_content.replace('[FRONTEND_URL]', frontend_url)

    # Testo plain
    moduli_text = '\n'.join(
        f'  - Modulo {m:02d} - {NOMI_MODULI.get(m, "")}' for m in sorted(moduli)
    )
    text_content = (
        f"Ciao {nome},\n\n"
        f"Grazie per il tuo acquisto! Ecco le tue credenziali per la SB Food Academy:\n\n"
        f"Email: {destinatario}\n"
        f"Password: {password}\n\n"
        f"Moduli sbloccati:\n{moduli_text}\n\n"
        f"Accedi ai tuoi corsi: {frontend_url}/academy.html#area-studenti\n\n"
        f"---\n"
        f"SB Food Consulting - Roma, Italia\n"
    )

    try:
        params: resend.Emails.SendParams = {
            "from": mail_from,
            "to": [destinatario],
            "subject": f"Le tue credenziali SB Food Academy - Benvenuto {nome}",
            "html": html_content,
            "text": text_content,
        }
        email = resend.Emails.send(params)
        logger.info(f"Email credenziali inviata a {destinatario} (id: {email['id']})")
    except Exception as e:
        logger.error(f"Errore invio email credenziali a {destinatario}: {e}")


def invia_email_credenziali(nome: str, destinatario: str, password: str, moduli: list):
    """Invia email credenziali in background."""
    api_key = os.environ.get('RESEND_API_KEY')

    if not api_key:
        logger.warning("RESEND_API_KEY non configurata, email credenziali non inviata")
        return

    thread = threading.Thread(
        target=_send_credenziali_email,
        args=(nome, destinatario, password, moduli),
        daemon=True,
    )
    thread.start()
