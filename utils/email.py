"""Invio email transazionali via Resend.

Nota: storicamente questo modulo usava Brevo (sib_api_v3_sdk), ma l'autenticazione
del dominio su Brevo era incompleta (niente DKIM/SPF) e gli invii fallivano o
finivano in spam. Ora usa Resend (dominio verificato con SPF+DKIM+DMARC), lo stesso
provider delle campagne. La firma di invia_email è invariata: tutti i chiamanti
esistenti (credenziali acquisto, notifiche admin, contatti...) restano compatibili.
"""
import os
import logging
import resend

logger = logging.getLogger(__name__)


def invia_email(destinatario_email, destinatario_nome, oggetto, corpo_html):
    """Invia una email HTML via Resend. Ritorna True/False. Non solleva eccezioni."""
    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        logger.error("RESEND_API_KEY non configurata — email non inviata a %s", destinatario_email)
        return False

    resend.api_key = api_key
    mail_from = os.environ.get('MAIL_FROM', 'SB Food Consulting <info@sbfoodconsulting.com>')

    try:
        resend.Emails.send({
            "from": mail_from,
            "to": [destinatario_email],
            "subject": oggetto,
            "html": corpo_html,
        })
        logger.info("Email inviata a %s (%s)", destinatario_email, oggetto)
        return True
    except Exception as e:
        logger.error("Errore Resend invio a %s: %s", destinatario_email, e, exc_info=True)
        return False
