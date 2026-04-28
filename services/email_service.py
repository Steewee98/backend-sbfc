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
