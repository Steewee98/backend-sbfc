import os
import smtplib
import logging
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')


def _send_email(nome: str, destinatario: str):
    """Invio effettivo SMTP (eseguito in thread separato)."""
    mail_username = os.environ.get('MAIL_USERNAME')
    mail_password = os.environ.get('MAIL_PASSWORD')
    mail_from = os.environ.get('MAIL_FROM', 'info@sbfoodconsulting.com')

    # Carica template
    template_path = os.path.join(TEMPLATES_DIR, 'email_benvenuto.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    html_content = html_content.replace('[NOME]', nome)

    # Componi messaggio
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Grazie per averci contattato, {nome} \u2014 SB Food Consulting'
    msg['From'] = f'SB Food Consulting <{mail_from}>'
    msg['To'] = destinatario

    text_content = (
        f"Grazie per averci contattato, {nome}.\n\n"
        "Abbiamo ricevuto la tua richiesta e ti risponderemo personalmente entro 24 ore.\n\n"
        "Prenota una chiamata gratuita di 30 minuti con Simone Braghetta:\n"
        "https://calendly.com/sbfoodconsulting-info/30min\n\n"
        "---\n"
        "SB Food Consulting \u2014 Roma, Italia\n"
        "info@sbfoodconsulting.com\n"
    )

    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as server:
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
        logger.info(f"Email benvenuto inviata a {destinatario}")
    except Exception as e:
        logger.error(f"Errore invio email a {destinatario}: {e}")


def invia_email_benvenuto(nome: str, destinatario: str):
    """Invia email di benvenuto in background (non blocca la risposta API)."""
    mail_username = os.environ.get('MAIL_USERNAME')
    mail_password = os.environ.get('MAIL_PASSWORD')

    if not mail_username or not mail_password:
        logger.warning("MAIL_USERNAME o MAIL_PASSWORD non configurate, email non inviata")
        return

    thread = threading.Thread(target=_send_email, args=(nome, destinatario), daemon=True)
    thread.start()
