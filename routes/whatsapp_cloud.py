"""Webhook WhatsApp Business Cloud API (Meta).

Riceve i messaggi in arrivo, registra il contatto, e risponde con Claude.

Setup su Meta (App > WhatsApp > Configuration > Webhook):
  Callback URL: https://<BACKEND>/api/whatsapp/cloud-webhook
  Verify token: il valore di WHATSAPP_VERIFY_TOKEN
  Sottoscrivi il campo "messages".
"""
import os
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify

from models import db, Contatto, MessaggioWhatsapp
from utils.whatsapp import normalizza_telefono
from services.whatsapp_cloud import invia_whatsapp_cloud
from services.ai_responder import genera_risposta

whatsapp_cloud_bp = Blueprint('whatsapp_cloud', __name__)

# Dedup: Meta può ri-consegnare lo stesso messaggio. Teniamo gli id già visti.
_lock = threading.Lock()
_processed_ids = set()


def _gia_processato(msg_id):
    with _lock:
        if msg_id in _processed_ids:
            return True
        _processed_ids.add(msg_id)
        if len(_processed_ids) > 2000:
            # taglia per non crescere all'infinito
            for x in list(_processed_ids)[:1000]:
                _processed_ids.discard(x)
        return False


def _storico(numero, limite=12):
    """Ricostruisce la conversazione dai log per dare contesto a Claude."""
    msgs = MessaggioWhatsapp.query.filter(
        MessaggioWhatsapp.telefono == numero,
        MessaggioWhatsapp.tipo.in_(['inbound', 'cloud'])
    ).order_by(MessaggioWhatsapp.created_at.desc()).limit(limite).all()
    storico = []
    for m in reversed(msgs):
        role = 'user' if m.tipo == 'inbound' else 'assistant'
        if m.messaggio:
            storico.append({'role': role, 'content': m.messaggio})
    return storico


def _registra_contatto(numero, mittente_raw, pushname, corpo):
    esistente = Contatto.query.filter(
        db.or_(Contatto.telefono == numero,
               Contatto.telefono == mittente_raw)).first()
    if esistente:
        return
    nome_breve = pushname.split()[0][:100] if pushname else 'Contatto'
    cognome = (' '.join(pushname.split()[1:])[:100]
               if pushname and len(pushname.split()) > 1 else '')
    db.session.add(Contatto(
        nome=nome_breve, cognome=cognome, email='',
        telefono=numero, tipo_locale='Lead WhatsApp',
        messaggio=corpo or 'Messaggio in arrivo da WhatsApp',
        stato='nuovo',
        priorita_richiamo=True,  # lead caldo: ci ha scritto lui -> in cima
        created_at=datetime.utcnow()))
    db.session.commit()


def _gestisci_messaggio(msg, nome_map):
    msg_id = msg.get('id')
    if msg_id and _gia_processato(msg_id):
        return

    mittente_raw = str(msg.get('from', '')).strip()
    if not mittente_raw:
        return
    numero, _ = normalizza_telefono(mittente_raw)
    pushname = str(nome_map.get(mittente_raw, '')).strip()

    # Estrai il testo (gestiamo i messaggi di testo; per altri tipi
    # rispondiamo comunque con un benvenuto generico)
    tipo_msg = msg.get('type')
    if tipo_msg == 'text':
        corpo = str(msg.get('text', {}).get('body', '')).strip()
    else:
        corpo = ''

    # Log del messaggio in arrivo
    try:
        db.session.add(MessaggioWhatsapp(
            nome=pushname.split()[0] if pushname else '',
            telefono=numero, messaggio=corpo or f'[{tipo_msg}]',
            stato='ricevuto', tipo='inbound'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WA-CLOUD] Errore log inbound: {e}")

    try:
        _registra_contatto(numero, mittente_raw, pushname, corpo)
    except Exception as e:
        db.session.rollback()
        print(f"[WA-CLOUD] Errore registrazione contatto: {e}")

    # Storico PRIMA del messaggio corrente (già loggato sopra -> lo escludo
    # ripassandolo come turno corrente)
    storico = _storico(numero)
    if storico and storico[-1]['role'] == 'user':
        storico = storico[:-1]

    nome_breve = pushname.split()[0] if pushname else ''
    risposta = genera_risposta(corpo, nome=nome_breve, storico=storico)

    if risposta:
        invia_whatsapp_cloud(numero, risposta,
                             nome=nome_breve, tipo='cloud')


@whatsapp_cloud_bp.route('/api/whatsapp/cloud-webhook', methods=['GET'])
def verifica_webhook():
    """Verifica del webhook richiesta da Meta in fase di setup."""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode == 'subscribe' and token == os.environ.get('WHATSAPP_VERIFY_TOKEN'):
        return challenge or '', 200
    return 'forbidden', 403


@whatsapp_cloud_bp.route('/api/whatsapp/cloud-webhook', methods=['POST'])
def ricevi_webhook():
    payload = request.get_json(force=True, silent=True) or {}

    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})

            # Mappa wa_id -> nome profilo
            nome_map = {}
            for c in value.get('contacts', []):
                nome_map[c.get('wa_id')] = \
                    c.get('profile', {}).get('name', '')

            # Ignora gli aggiornamenti di stato (consegnato/letto)
            for m in value.get('messages', []):
                try:
                    _gestisci_messaggio(m, nome_map)
                except Exception as e:
                    print(f"[WA-CLOUD] Errore gestione messaggio: {e}")

    # Rispondi sempre 200, altrimenti Meta ritenta in loop
    return jsonify({'status': 'ok'}), 200
