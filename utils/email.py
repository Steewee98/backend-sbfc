import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
import os
import logging

logger = logging.getLogger(__name__)


def invia_email(destinatario_email, destinatario_nome, oggetto, corpo_html):
    api_key = os.environ.get('BREVO_API_KEY')
    if not api_key:
        logger.error("BREVO_API_KEY non configurata — email non inviata")
        return False

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = api_key

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": destinatario_email, "name": destinatario_nome}],
        sender={"email": "info@sbfoodconsulting.com",
                "name": "SB Food Consulting"},
        subject=oggetto,
        html_content=corpo_html
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        logger.info(f"Email inviata a {destinatario_email}")
        return True
    except ApiException as e:
        logger.error(f"Errore Brevo API invio a {destinatario_email}: {e}", exc_info=True)
        return False
