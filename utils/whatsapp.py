import requests
import os
from datetime import datetime, timedelta
from models import db, MessaggioWhatsapp

ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', 'instance179124')
ULTRAMSG_TOKEN = os.environ.get('ULTRAMSG_TOKEN', 'zct26h140v589icp')


def normalizza_telefono(telefono):
    """Normalizza e valida un numero di telefono italiano.
    Ritorna (numero_normalizzato, errore) — errore è None se valido."""
    numero = telefono.strip()
    # Rimuovi spazi, trattini, punti
    numero = numero.replace(' ', '').replace('-', '').replace('.', '')

    if not numero.startswith('+'):
        if numero.startswith('0'):
            numero = '+39' + numero[1:]
        elif numero.startswith('39') and len(numero) >= 12:
            numero = '+' + numero
        else:
            numero = '+39' + numero

    # Validazione numeri italiani: +39 + 10 cifre (cellulare) o 6-11 (fisso)
    if numero.startswith('+39'):
        cifre = numero[3:]
        if not cifre.isdigit():
            return numero, 'contiene caratteri non numerici'
        if cifre.startswith('3') and len(cifre) != 10:
            return numero, f'cellulare italiano deve avere 10 cifre, trovate {len(cifre)}'

    return numero, None


def invia_whatsapp(telefono, messaggio, nome='', tipo='manuale'):
    try:
        numero, errore_num = normalizza_telefono(telefono)

        if errore_num is None:
            # Deduplicazione: evita doppi invii allo stesso numero/tipo in 5 min
            cinque_min_fa = datetime.utcnow() - timedelta(minutes=5)
            duplicato = MessaggioWhatsapp.query.filter(
                MessaggioWhatsapp.telefono == numero,
                MessaggioWhatsapp.tipo == tipo,
                MessaggioWhatsapp.stato == 'inviato',
                MessaggioWhatsapp.created_at >= cinque_min_fa
            ).first()
            if duplicato:
                print(f"[WA] Duplicato ignorato: {numero} tipo={tipo}")
                return True  # già inviato, tutto ok

        if errore_num:
            print(f"[WA] Numero non valido {numero}: {errore_num}")
            # Salva nel log con stato errore
            try:
                log = MessaggioWhatsapp(
                    nome=nome,
                    telefono=numero,
                    messaggio=messaggio,
                    stato='numero_invalido',
                    tipo=tipo
                )
                db.session.add(log)
                db.session.commit()
            except Exception as e:
                print(f"Errore salvataggio log WA: {e}")
            return False

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
