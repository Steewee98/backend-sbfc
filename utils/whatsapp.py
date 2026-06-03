import requests
import os

ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', 'instance179124')
ULTRAMSG_TOKEN = os.environ.get('ULTRAMSG_TOKEN', 'zct26h140v589icp')


def invia_whatsapp(telefono, messaggio):
    try:
        numero = telefono.strip()
        if not numero.startswith('+'):
            if numero.startswith('0'):
                numero = '+39' + numero[1:]
            elif numero.startswith('39'):
                numero = '+' + numero
            else:
                numero = '+39' + numero

        url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE}/messages/chat"

        payload = {
            'token': ULTRAMSG_TOKEN,
            'to': numero,
            'body': messaggio,
            'priority': 10
        }

        res = requests.post(url, data=payload, timeout=10)
        result = res.json()
        print(f"WhatsApp inviato a {numero}: {result}")
        return True

    except Exception as e:
        print(f"Errore WhatsApp: {e}")
        return False
