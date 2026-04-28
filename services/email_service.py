import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')


def invia_email_benvenuto(nome: str, destinatario: str):
    """Invia email di benvenuto dopo la compilazione del form contatti."""
    mail_username = os.environ.get('MAIL_USERNAME')
    mail_password = os.environ.get('MAIL_PASSWORD')
    mail_from = os.environ.get('MAIL_FROM', 'info@sbfoodconsulting.com')

    if not mail_username or not mail_password:
        logger.warning("MAIL_USERNAME o MAIL_PASSWORD non configurate, email non inviata")
        return False

    # Carica template
    template_path = os.path.join(TEMPLATES_DIR, 'email_benvenuto.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Sostituisci placeholder
    html_content = html_content.replace('[NOME]', nome)

    # Componi messaggio
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Grazie per averci contattato, {nome} — SB Food Consulting'
    msg['From'] = f'SB Food Consulting <{mail_from}>'
    msg['To'] = destinatario

    # Versione plain text
    text_content = (
        f"Grazie per averci contattato, {nome}.\n\n"
        "Abbiamo ricevuto la tua richiesta e ti risponderemo personalmente entro 24 ore.\n\n"
        "Prenota una chiamata gratuita di 30 minuti con Simone Braghetta:\n"
        "https://calendly.com/sbfoodconsulting-info/30min\n\n"
        "---\n"
        "SB Food Consulting — Roma, Italia\n"
        "info@sbfoodconsulting.com\n"
    )

    msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    # Invio SMTP
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(mail_username, mail_password)
            server.send_message(msg)
        logger.info(f"Email benvenuto inviata a {destinatario}")
        return True
    except Exception as e:
        logger.error(f"Errore invio email a {destinatario}: {e}")
        return False
