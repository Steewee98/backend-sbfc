import requests
import os
from models import db, MessaggioWhatsapp

ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', 'instance179124')
ULTRAMSG_TOKEN = os.environ.get('ULTRAMSG_TOKEN', 'zct26h140v589icp')


def invia_whatsapp(telefono, messaggio, nome='', tipo='manuale'):
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
        stato = 'inviato' if result.get('sent') == 'true' else 'errore'
        print(f"WhatsApp {stato} a {numero}: {result}")

        # Salva nel database
        try:
            log = MessaggioWhatsapp(
                nome=nome,
                telefono=numero,
                messaggio=messaggio,
                stato=stato,
                tipo=tipo
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            print(f"Errore salvataggio log WA: {e}")

        return stato == 'inviato'

    except Exception as e:
        print(f"Errore WhatsApp: {e}")
        return False
