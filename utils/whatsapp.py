import requests
import os
import threading
from datetime import datetime, timedelta
from models import db, MessaggioWhatsapp

ULTRAMSG_INSTANCE = os.environ.get('ULTRAMSG_INSTANCE', 'instance179124')
ULTRAMSG_TOKEN = os.environ.get('ULTRAMSG_TOKEN', 'zct26h140v589icp')

# Lock + set in memoria per evitare invii doppi
_send_lock = threading.Lock()
_sent_recently = {}  # (numero, tipo) -> timestamp


def _cleanup_sent_cache():
    """Rimuovi entries più vecchie di 5 minuti."""
    now = datetime.utcnow()
    expired = [k for k, t in _sent_recently.items()
               if (now - t).total_seconds() > 300]
    for k in expired:
        del _sent_recently[k]


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
    with _send_lock:
        try:
            numero, errore_num = normalizza_telefono(telefono)

            if errore_num is None:
                # Dedup 1: cache in memoria (stesso processo)
                _cleanup_sent_cache()
                cache_key = (numero, tipo)
                if cache_key in _sent_recently:
                    print(f"[WA] Duplicato ignorato (cache): {numero} tipo={tipo}")
                    return True

                # Dedup 2: check DB con sessione fresca (cross-deploy)
                db.session.expire_all()
                cinque_min_fa = datetime.utcnow() - timedelta(minutes=5)
                duplicato = MessaggioWhatsapp.query.filter(
                    MessaggioWhatsapp.telefono == numero,
                    MessaggioWhatsapp.tipo == tipo,
                    MessaggioWhatsapp.stato == 'inviato',
                    MessaggioWhatsapp.created_at >= cinque_min_fa
                ).first()
                if duplicato:
                    print(f"[WA] Duplicato ignorato (DB): {numero} tipo={tipo}")
                    _sent_recently[cache_key] = datetime.utcnow()
                    return True

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

            # Segna come inviato nella cache in memoria
            if stato == 'inviato':
                _sent_recently[(numero, tipo)] = datetime.utcnow()

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
