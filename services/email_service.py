import os
import time
import logging
import threading
from urllib.parse import quote
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


# ─── Campagna "Riscopri le schede" (follow-up lead strumenti) ──────────

CAMPAGNA_SUBJECT = "Sono uscite 3 nuove schede gratuite — SB Food Consulting"
UNSUB_MAILTO = "mailto:info@sbfoodconsulting.com?subject=" + quote(
    "Cancellami dalla lista schede")

_CAMPAGNA_TEXT = (
    "Ciao,\n\n"
    "con le nostre schede operative abbiamo gia' aiutato oltre 150 ristoratori a "
    "mettere ordine in cucina, in sala e nei numeri.\n\n"
    "Oggi sono uscite 3 nuove schede gratuite:\n"
    "- Checklist Pre-Servizio: https://web-production-f3794.up.railway.app/api/strumenti/checklist-pre-servizio/pdf\n"
    "- Quiz I Numeri del Locale: https://web-production-f3794.up.railway.app/api/strumenti/quiz-numeri/pdf\n"
    "- Autovalutazione del Team: https://web-production-f3794.up.railway.app/api/strumenti/autovalutazione-team/pdf\n\n"
    "Scaricale tutte (6 schede) in un'unica pagina:\n"
    "https://www.sbfoodconsulting.com/schede\n\n"
    "E se vuoi il metodo completo, la SB Food Academy: singolo modulo 17,91 EUR "
    "(invece di 19,90) o percorso completo 85,41 EUR (invece di 94,90) con il codice SCHEDE10.\n"
    "https://www.sbfoodconsulting.com/academy.html\n\n"
    "---\n"
    "SB Food Consulting — Roma, Italia — info@sbfoodconsulting.com\n"
    "Per non ricevere piu' queste email rispondi 'Cancellami'.\n"
)


def campagna_configurata():
    """True se la chiave Resend è presente."""
    return bool(os.environ.get('RESEND_API_KEY'))


def _send_campagna_schede(destinatari):
    """Invia la email di follow-up via Resend, una alla volta con una piccola
    pausa (deliverability)."""
    resend.api_key = os.environ.get('RESEND_API_KEY')
    mail_from = os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>')

    template_path = os.path.join(TEMPLATES_DIR, 'email_riscopri_schede.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        base_html = f.read()
    html_content = base_html.replace('[UNSUBSCRIBE_URL]', UNSUB_MAILTO)

    inviati, falliti = 0, 0
    for email in destinatari:
        try:
            params: resend.Emails.SendParams = {
                "from": mail_from,
                "to": [email],
                "subject": CAMPAGNA_SUBJECT,
                "html": html_content,
                "text": _CAMPAGNA_TEXT,
                "headers": {"List-Unsubscribe": "<%s>" % UNSUB_MAILTO},
            }
            res = resend.Emails.send(params)
            inviati += 1
            logger.info("Campagna schede inviata a %s (id: %s)", email, res.get('id'))
        except Exception as e:
            falliti += 1
            logger.error("Errore invio campagna a %s: %s", email, e)
        time.sleep(0.6)

    logger.info("Campagna schede completata: %s inviate, %s fallite", inviati, falliti)
    print("[CAMPAGNA-SCHEDE] completata: %s inviate, %s fallite" % (inviati, falliti),
          flush=True)


def invia_campagna_schede(destinatari):
    """Avvia l'invio della campagna in background (non blocca la risposta HTTP)."""
    if not campagna_configurata():
        logger.warning("RESEND_API_KEY non configurata, campagna non inviata")
        return False
    thread = threading.Thread(
        target=_send_campagna_schede, args=(list(destinatari),), daemon=True)
    thread.start()
    return True


# ─── Campagna "Feedback + sconto 20%" (broadcast ai lead esistenti) ────

CAMPAGNA_FB_SUBJECT = "Il tuo riscontro sulle schede operative — SB Food Consulting"

_CAMPAGNA_FB_TEXT = (
    "Buongiorno,\n\n"
    "qualche tempo fa ha scaricato una delle schede operative di SB Food Consulting.\n"
    "Ci farebbe piacere conoscere la Sua opinione: gli strumenti si sono rivelati utili "
    "nella gestione quotidiana del locale? Puo' rispondere direttamente a questa email.\n\n"
    "Un vantaggio riservato: se ha gia' scaricato l'intera raccolta di schede, Le riconosciamo "
    "uno sconto del 20% sulla SB Food Academy, il percorso formativo dedicato alla gestione del ristorante.\n"
    "Codice SCHEDE20 -> percorso completo 75,92 EUR (anziche' 94,90), singolo modulo 15,92 EUR.\n"
    "https://www.sbfoodconsulting.com/academy.html\n\n"
    "Non dispone ancora dell'intera raccolta? Le schede sono sei (tre di recente pubblicazione), "
    "tutte gratuite, in un'unica pagina:\n"
    "https://www.sbfoodconsulting.com/schede\n\n"
    "Grazie per l'attenzione.\n"
    "SB Food Consulting\n\n"
    "---\n"
    "SB Food Consulting — Roma, Italia — info@sbfoodconsulting.com\n"
    "Per annullare l'iscrizione rispondi 'Cancellami'.\n"
)


def _send_campagna_feedback(destinatari):
    """Invia la email di feedback + sconto 20%, una alla volta con pausa."""
    resend.api_key = os.environ.get('RESEND_API_KEY')
    mail_from = os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>')

    template_path = os.path.join(TEMPLATES_DIR, 'email_feedback_sconto.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        base_html = f.read()
    html_content = base_html.replace('[UNSUBSCRIBE_URL]', UNSUB_MAILTO)

    inviati, falliti = 0, 0
    for email in destinatari:
        try:
            params: resend.Emails.SendParams = {
                "from": mail_from,
                "to": [email],
                "subject": CAMPAGNA_FB_SUBJECT,
                "html": html_content,
                "text": _CAMPAGNA_FB_TEXT,
                "headers": {"List-Unsubscribe": "<%s>" % UNSUB_MAILTO},
            }
            res = resend.Emails.send(params)
            inviati += 1
            logger.info("Campagna feedback inviata a %s (id: %s)", email, res.get('id'))
        except Exception as e:
            falliti += 1
            logger.error("Errore invio campagna feedback a %s: %s", email, e)
        time.sleep(0.6)

    logger.info("Campagna feedback completata: %s inviate, %s fallite", inviati, falliti)
    print("[CAMPAGNA-FEEDBACK] completata: %s inviate, %s fallite" % (inviati, falliti),
          flush=True)


def invia_campagna_feedback(destinatari):
    """Avvia l'invio della campagna feedback in background."""
    if not campagna_configurata():
        logger.warning("RESEND_API_KEY non configurata, campagna feedback non inviata")
        return False
    thread = threading.Thread(
        target=_send_campagna_feedback, args=(list(destinatari),), daemon=True)
    thread.start()
    return True
