"""Invio messaggi tramite WhatsApp Business Cloud API (Meta) — soluzione
ufficiale, conforme alle ToS, basata su access token (ban-free).

Env richieste:
  WHATSAPP_CLOUD_TOKEN     access token permanente (System User)
  WHATSAPP_PHONE_NUMBER_ID id del numero registrato sulla Cloud API
  WHATSAPP_API_VERSION     opzionale, default v21.0
"""
import os
import requests
from models import db, MessaggioWhatsapp

API_VERSION = os.environ.get('WHATSAPP_API_VERSION', 'v21.0')


def _config():
    return (
        os.environ.get('WHATSAPP_CLOUD_TOKEN'),
        os.environ.get('WHATSAPP_PHONE_NUMBER_ID'),
    )


def cloud_api_attiva():
    """True se le credenziali Cloud API sono configurate."""
    token, phone_id = _config()
    return bool(token and phone_id)


def _log(nome, numero, messaggio, stato, tipo):
    try:
        db.session.add(MessaggioWhatsapp(
            nome=nome, telefono=numero, messaggio=messaggio,
            stato=stato, tipo=tipo))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WA-CLOUD] Errore log: {e}")


def invia_whatsapp_cloud(numero, messaggio, nome='', tipo='cloud'):
    """Invia un messaggio di testo. Funziona dentro la finestra di 24h
    aperta da un messaggio in arrivo del cliente."""
    token, phone_id = _config()
    if not token or not phone_id:
        print("[WA-CLOUD] Config mancante "
              "(WHATSAPP_CLOUD_TOKEN / WHATSAPP_PHONE_NUMBER_ID)")
        return False

    to = str(numero).lstrip('+')
    url = f"https://graph.facebook.com/{API_VERSION}/{phone_id}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'text',
        'text': {'preview_url': True, 'body': messaggio},
    }
    stato = 'errore'
    try:
        res = requests.post(url, json=payload, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }, timeout=15)
        stato = 'inviato' if res.status_code == 200 else 'errore'
        print(f"[WA-CLOUD] {stato} a {to}: {res.status_code} "
              f"{res.text[:300]}")
    except Exception as e:
        print(f"[WA-CLOUD] Errore invio: {e}")

    _log(nome, numero, messaggio, stato, tipo)
    return stato == 'inviato'


def invia_template_cloud(numero, template_name, lang='it',
                         parametri=None, nome='', tipo='cloud_template'):
    """Invia un template approvato — usato per ricontattare FUORI dalla
    finestra di 24h (es. follow-up il giorno dopo). I template vanno
    creati e approvati nel Business Manager di Meta."""
    token, phone_id = _config()
    if not token or not phone_id:
        print("[WA-CLOUD] Config mancante per template")
        return False

    to = str(numero).lstrip('+')
    url = f"https://graph.facebook.com/{API_VERSION}/{phone_id}/messages"
    components = []
    if parametri:
        components.append({
            'type': 'body',
            'parameters': [{'type': 'text', 'text': str(p)}
                           for p in parametri],
        })
    payload = {
        'messaging_product': 'whatsapp',
        'to': to,
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': lang},
            'components': components,
        },
    }
    stato = 'errore'
    try:
        res = requests.post(url, json=payload, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }, timeout=15)
        stato = 'inviato' if res.status_code == 200 else 'errore'
        print(f"[WA-CLOUD] template {stato} a {to}: {res.status_code} "
              f"{res.text[:300]}")
    except Exception as e:
        print(f"[WA-CLOUD] Errore invio template: {e}")

    _log(nome, numero, f"[template:{template_name}]", stato, tipo)
    return stato == 'inviato'
