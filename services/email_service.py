import os
import time
import hmac
import hashlib
import logging
import threading
from datetime import datetime
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
            "tags": [{"name": "categoria", "value": "benvenuto"}],
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
            "tags": [{"name": "categoria", "value": "credenziali"}],
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


# ─── Email transazionale "Grazie per il download" (auto al primo download) ──

# Nomi leggibili e URL del PDF per ogni slug (coerenti con STRUMENTI_VALIDI).
NOMI_STRUMENTI = {
    'checklist-apertura-chiusura': 'Checklist Apertura & Chiusura',
    'scheda-food-cost': 'Scheda Food Cost',
    'scheda-ricetta': 'Scheda Ricetta',
    'checklist-pre-servizio': 'Checklist Pre-Servizio',
    'quiz-numeri': 'Quiz — I Numeri del Locale',
    'autovalutazione-team': 'Autovalutazione del Team',
    'manuale-operativo': 'Manuale Operativo',
}

GRAZIE_SUBJECT = "La tua scheda è pronta — e due vantaggi riservati (SB Food Consulting)"

_PDF_BASE = "https://www.sbfoodconsulting.com/assets/pdf/risorse"


def _grazie_text(nome_scheda, scheda_url):
    return (
        "Buongiorno,\n\n"
        f"grazie per aver scaricato la scheda \"{nome_scheda}\". Il download e' partito nel "
        f"browser; se ti serve di nuovo, la riscarichi qui:\n{scheda_url}\n\n"
        "Tutte le schede operative gratuite: https://www.sbfoodconsulting.com/schede\n\n"
        "Due vantaggi riservati a chi scarica le schede:\n\n"
        "1) Il Cruscotto dell'Imprenditore al -15%. In meno di 30 minuti al mese "
        "sai dove guadagni, dove perdi e quale decisione prendere.\n"
        "   Codice CRUSCOTTO15 -> 21,25 EUR anziche' 25,00 EUR.\n"
        "   https://www.sbfoodconsulting.com/cruscotto-imprenditore\n\n"
        "2) SB Food Academy al -10%. Singolo modulo 17,91 EUR (invece di 19,90) "
        "o percorso completo 85,41 EUR (invece di 94,90).\n"
        "   Codice SCHEDE10.\n"
        "   https://www.sbfoodconsulting.com/academy.html\n\n"
        "Per qualsiasi domanda rispondi pure a questa email.\n"
        "A presto,\nSB Food Consulting\n\n"
        "---\n"
        "SB Food Consulting — Roma, Italia — info@sbfoodconsulting.com\n"
        "Per non ricevere piu' queste email rispondi 'Cancellami'.\n"
    )


def _send_grazie_download(destinatario, strumento):
    """Invio della email transazionale di conferma download (thread separato)."""
    resend.api_key = os.environ.get('RESEND_API_KEY')
    mail_from = os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>')

    nome_scheda = NOMI_STRUMENTI.get(strumento, 'la tua scheda')
    scheda_url = '%s/%s.pdf' % (_PDF_BASE, strumento)

    template_path = os.path.join(TEMPLATES_DIR, 'email_grazie_download.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    html_content = html_content.replace('[NOME_SCHEDA]', nome_scheda)
    html_content = html_content.replace('[SCHEDA_URL]', scheda_url)
    html_content = html_content.replace('[UNSUBSCRIBE_URL]', UNSUB_MAILTO)

    try:
        params: resend.Emails.SendParams = {
            "from": mail_from,
            "to": [destinatario],
            "subject": GRAZIE_SUBJECT,
            "html": html_content,
            "text": _grazie_text(nome_scheda, scheda_url),
            "headers": {"List-Unsubscribe": "<%s>" % UNSUB_MAILTO},
            "tags": [{"name": "categoria", "value": "grazie_download"}],
        }
        res = resend.Emails.send(params)
        logger.info("Email grazie-download inviata a %s (id: %s)", destinatario, res.get('id'))
    except Exception as e:
        logger.error("Errore invio email grazie-download a %s: %s", destinatario, e)


def invia_email_grazie_download(destinatario, strumento):
    """Avvia in background la mail di ringraziamento + conferma download con i
    codici sconto Cruscotto e Academy. Non blocca la risposta HTTP."""
    if not os.environ.get('RESEND_API_KEY'):
        logger.warning("RESEND_API_KEY non configurata, email grazie-download non inviata")
        return False
    thread = threading.Thread(
        target=_send_grazie_download, args=(destinatario, strumento), daemon=True)
    thread.start()
    return True


# ─── Campagna "Riscopri le schede" (follow-up lead strumenti) ──────────

CAMPAGNA_SUBJECT = "Sono uscite 3 nuove schede gratuite — SB Food Consulting"
UNSUB_MAILTO = "mailto:info@sbfoodconsulting.com?subject=" + quote(
    "Cancellami dalla lista schede")

_CAMPAGNA_TEXT = (
    "Ciao,\n\n"
    "con le nostre schede operative abbiamo gia' aiutato oltre 150 ristoratori a "
    "mettere ordine in cucina, in sala e nei numeri.\n\n"
    "Oggi sono uscite 3 nuove schede gratuite:\n"
    "- Checklist Pre-Servizio: https://www.sbfoodconsulting.com/assets/pdf/risorse/checklist-pre-servizio.pdf\n"
    "- Quiz I Numeri del Locale: https://www.sbfoodconsulting.com/assets/pdf/risorse/quiz-numeri.pdf\n"
    "- Autovalutazione del Team: https://www.sbfoodconsulting.com/assets/pdf/risorse/autovalutazione-team.pdf\n\n"
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
                "tags": [{"name": "categoria", "value": "campagna_schede"}],
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

CAMPAGNA_FB_SUBJECT = "3 nuove schede gratuite, già online per il tuo locale"

_CAMPAGNA_FB_TEXT = (
    "Buongiorno,\n\n"
    "qualche tempo fa ha scaricato una delle schede operative di SB Food Consulting.\n"
    "Ci farebbe piacere conoscere la Sua opinione: gli strumenti si sono rivelati utili "
    "nella gestione quotidiana del locale? Puo' rispondere direttamente a questa email.\n\n"
    "Nel frattempo, sono disponibili tre nuove schede gratuite:\n"
    "- Checklist Pre-Servizio: https://www.sbfoodconsulting.com/assets/pdf/risorse/checklist-pre-servizio.pdf\n"
    "- Quiz I Numeri del Locale: https://www.sbfoodconsulting.com/assets/pdf/risorse/quiz-numeri.pdf\n"
    "- Autovalutazione del Team: https://www.sbfoodconsulting.com/assets/pdf/risorse/autovalutazione-team.pdf\n"
    "Tutte le schede (6): https://www.sbfoodconsulting.com/schede\n\n"
    "Un vantaggio riservato: Il Cruscotto dell'Imprenditore con il 15% di sconto.\n"
    "E' la guida pratica per capire, in meno di 30 minuti al mese, se la Sua attivita' sta "
    "funzionando: margini, cassa, prezzi, persone.\n"
    "Codice CRUSCOTTO15 -> 21,25 EUR anziche' 25,00 EUR.\n"
    "https://www.sbfoodconsulting.com/cruscotto-imprenditore\n\n"
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
                "tags": [{"name": "categoria", "value": "campagna_feedback"}],
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


# ─── Sequenza nurture automatica (una email a settimana) ──────────────
#
# Sei email inviate a cadenza settimanale a ogni lead delle schede. Il
# processore (routes/sequenze.py) decide QUANDO inviare; qui c'è il COSA:
# template, oggetto, testo, logging su EmailInvio (per il gestionale) e il
# link di disiscrizione one-click per-destinatario.

def _mail_from():
    return os.environ.get('MAIL_FROM', 'SB Food Consulting <onboarding@resend.dev>')


def _backend_base():
    dom = os.environ.get('RAILWAY_PUBLIC_DOMAIN') or 'web-production-f3794.up.railway.app'
    return 'https://' + dom


def unsub_token(email):
    """Token HMAC dell'email: permette la disiscrizione one-click senza dover
    salvare nulla (si verifica ricalcolando l'HMAC)."""
    secret = os.environ.get('SECRET_KEY', 'dev-fallback-key').encode()
    return hmac.new(secret, (email or '').lower().strip().encode(),
                    hashlib.sha256).hexdigest()[:20]


def unsub_url(email):
    return '%s/api/unsubscribe?e=%s&t=%s' % (
        _backend_base(), quote((email or '').lower().strip()), unsub_token(email))


# step -> (template, oggetto, testo-plain)
NURTURE = {
    1: ('email_nurture1_uso.html',
        'La Sua scheda vale solo se la usa bene',
        "Salve,\n\nqualche tempo fa ha scaricato la Scheda Food Cost. Vale solo se la usa bene: "
        "1) aggiornarla quando cambiano i prezzi; 2) considerare scarti e cali di resa; "
        "3) partire dai 5 piatti piu' venduti.\n\nLe manca ancora il Quiz - I Numeri del Locale (gratis): "
        "https://web-production-f3794.up.railway.app/api/strumenti/quiz-numeri/pdf\n\n"
        "Se vuole gia' fare sul serio: il Cruscotto dell'Imprenditore con CRUSCOTTO15 a 21,25 EUR. "
        "https://www.sbfoodconsulting.com/cruscotto-imprenditore.html\n\nUn caro saluto,\nSB Food Consulting"),
    2: ('email_nurture2_gap.html',
        'Quello che una scheda, da sola, non Le dice',
        "Salve,\n\nla Scheda Food Cost Le dice quanto costa un piatto. Ma il Suo locale, nel suo insieme, "
        "sta guadagnando? Serve un sistema, non un numero.\n\nE' cio' che costruisce nel Modulo 01 - "
        "La Challenge del Controllo: 14 giorni, 14 azioni.\nScopra il Modulo 01: "
        "https://www.sbfoodconsulting.com/academy.html#modulo-01\n\nUn caro saluto,\nSB Food Consulting"),
    3: ('email_nurture3_cruscotto.html',
        'Controllo totale in mezz’ora al mese',
        "Salve,\n\nse per ora Le basta smettere di navigare a vista, c'e' lo strumento piu' economico "
        "che abbiamo: Il Cruscotto dell'Imprenditore. I numeri del locale in meno di 30 minuti al mese.\n\n"
        "Codice CRUSCOTTO15 (-15%): 21,25 EUR anziche' 25,00 EUR.\n"
        "https://www.sbfoodconsulting.com/cruscotto-imprenditore.html\n\nUn caro saluto,\nSB Food Consulting"),
    4: ('email_nurture4_modulo.html',
        'Un’azione al giorno. E smette di guidare a occhio.',
        "Salve,\n\nla Challenge del Controllo e' un percorso da fare: un'azione al giorno, 5 minuti. "
        "Alla fine sa ogni mattina incassi, costi, punto di pareggio e quanto Le resta.\n\n"
        "Codice SCHEDE10 (-10%) sul Modulo 01: 17,91 EUR anziche' 19,90 EUR.\nScopra il Modulo 01: "
        "https://www.sbfoodconsulting.com/academy.html#modulo-01\n\nUn caro saluto,\nSB Food Consulting"),
    5: ('email_nurture5_bundle.html',
        'Un problema alla volta e’ lento. Il metodo e’ uno.',
        "Salve,\n\ncinque moduli, un solo metodo. Presi singoli sarebbero 99,50 EUR; il corso completo "
        "costa meno.\n\nCodice SCHEDE10 (-10%) sul corso completo: 85,41 EUR anziche' 94,90 EUR.\n"
        "Vada ai prezzi: https://www.sbfoodconsulting.com/academy.html#prezzi\n\nUn caro saluto,\nSB Food Consulting"),
    6: ('email_nurture6_ultimo.html',
        '35 anni di ristorazione, in due strumenti',
        "Salve,\n\nsono Simone Braghetta. Le lascio i due strumenti, con i Suoi vantaggi:\n"
        "1. SB Food Academy - SCHEDE10 (-10%): modulo 17,91 EUR, completo 85,41 EUR. "
        "https://www.sbfoodconsulting.com/academy.html\n"
        "2. Il Cruscotto - CRUSCOTTO15 (-15%): 21,25 EUR. "
        "https://www.sbfoodconsulting.com/cruscotto-imprenditore.html\n\n"
        "Se ha una domanda sul Suo locale, mi scriva pure rispondendo a questa email.\n\n"
        "A presto,\nSimone Braghetta - SB Food Consulting"),
}


def log_email_invio(resend_id, destinatario, subject, tipo):
    """Registra l'invio su EmailInvio così compare nel gestionale (sezione Email).
    Il webhook Resend aggiornerà consegna/apertura/click sulla stessa riga
    (match per resend_id). Va chiamata dentro un application context."""
    try:
        from models import db, EmailInvio
        if resend_id and EmailInvio.query.filter_by(resend_id=resend_id).first():
            return
        riga = EmailInvio(
            resend_id=resend_id,
            destinatario=(destinatario or '').lower().strip(),
            subject=subject, tipo=tipo, sent_at=datetime.utcnow())
        db.session.add(riga)
        db.session.commit()
    except Exception as e:
        try:
            from models import db as _db
            _db.session.rollback()
        except Exception:
            pass
        logger.error('log_email_invio errore: %s', e)


def invia_nurture(step, destinatario):
    """Invia l'email nurture dello step indicato (1..6) e la registra su EmailInvio.
    Ritorna il resend_id se inviata, altrimenti None. Va chiamata dentro un
    application context (usa il DB per il logging)."""
    cfg = NURTURE.get(step)
    if not cfg:
        return None
    if not resend.api_key:
        resend.api_key = os.environ.get('RESEND_API_KEY')
    if not resend.api_key:
        logger.warning('RESEND_API_KEY assente: nurture %s non inviata', step)
        return None

    fname, subject, text = cfg
    u = unsub_url(destinatario)
    with open(os.path.join(TEMPLATES_DIR, fname), 'r', encoding='utf-8') as f:
        html = f.read().replace('[UNSUBSCRIBE_URL]', u)
    try:
        params: resend.Emails.SendParams = {
            'from': _mail_from(),
            'to': [destinatario],
            'subject': subject,
            'html': html,
            'text': text,
            'headers': {
                'List-Unsubscribe': '<%s>' % u,
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
            },
            'tags': [{'name': 'categoria', 'value': 'nurture_%d' % step}],
        }
        res = resend.Emails.send(params)
        resend_id = res.get('id') if isinstance(res, dict) else getattr(res, 'id', None)
        log_email_invio(resend_id, destinatario, subject, 'nurture_%d' % step)
        logger.info('Nurture %s inviata a %s (id %s)', step, destinatario, resend_id)
        return resend_id
    except Exception as e:
        logger.error('Errore invio nurture %s a %s: %s', step, destinatario, e)
        return None
