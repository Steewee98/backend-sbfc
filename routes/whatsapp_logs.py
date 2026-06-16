from flask import Blueprint, request, jsonify
from models import db, MessaggioWhatsapp, Contatto
from utils.whatsapp import invia_whatsapp, normalizza_telefono
from datetime import datetime, timedelta
import os

whatsapp_logs_bp = Blueprint('whatsapp_logs', __name__)

# Non ri-rispondere allo stesso numero entro questa finestra:
# durante una conversazione attiva risponde l'operatore, non il bot.
AUTO_REPLY_COOLDOWN_ORE = int(os.environ.get('WA_AUTO_REPLY_COOLDOWN_ORE', 12))


def _messaggio_benvenuto(nome):
    """Risposta automatica al primo messaggio di un nuovo contatto."""
    saluto = f"Ciao {nome}!" if nome else "Ciao!"
    return f"""{saluto} 👋

Grazie per averci scritto. Sono Simone Braghetta di SB Food Consulting.

Mi piacerebbe capire come posso aiutarti con il tuo locale. Il modo più semplice è una chiamata gratuita di 30 minuti: scegli tu quando ti è più comodo 👇
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone"""


@whatsapp_logs_bp.route('/api/whatsapp', methods=['GET'])
def get_whatsapp_logs():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    logs = MessaggioWhatsapp.query\
        .order_by(MessaggioWhatsapp.created_at.desc())\
        .all()

    return jsonify([{
        'id': l.id,
        'nome': l.nome,
        'telefono': l.telefono,
        'messaggio': l.messaggio,
        'stato': l.stato,
        'tipo': l.tipo,
        'created_at': l.created_at.isoformat()
    } for l in logs])


@whatsapp_logs_bp.route('/api/whatsapp/<int:id>', methods=['PATCH'])
def update_whatsapp_log(id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    log = MessaggioWhatsapp.query.get_or_404(id)
    data = request.get_json()

    if 'stato' in data:
        log.stato = data['stato']

    db.session.commit()
    return jsonify({'success': True, 'id': log.id, 'stato': log.stato})


@whatsapp_logs_bp.route('/api/whatsapp/webhook', methods=['POST', 'GET'])
def whatsapp_webhook():
    """Riceve i messaggi in arrivo da UltraMsg e risponde in automatico.

    Configura l'URL su UltraMsg (Settings > Webhooks):
      https://<dominio>/api/whatsapp/webhook?token=<WA_WEBHOOK_TOKEN>
    Abilita l'evento "Message Received".
    """
    # GET = verifica/healthcheck del webhook
    if request.method == 'GET':
        return jsonify({'status': 'ok', 'service': 'whatsapp-webhook'}), 200

    # Auth: UltraMsg non invia header custom, usiamo un token in querystring
    token = request.args.get('token')
    expected = os.environ.get('WA_WEBHOOK_TOKEN',
                              os.environ.get('ADMIN_TOKEN'))
    if expected and token != expected:
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(force=True, silent=True) or {}
    data = payload.get('data', payload)

    event_type = payload.get('event_type', '')
    from_me = data.get('fromMe', data.get('self', False))

    # Ignora i nostri stessi messaggi in uscita -> niente loop
    if from_me in (True, 'true', 1, '1'):
        return jsonify({'status': 'ignored', 'reason': 'fromMe'}), 200

    # Reagisci solo ai messaggi ricevuti (se l'evento è specificato)
    if event_type and event_type not in ('message_received',
                                         'message', 'chat'):
        return jsonify({'status': 'ignored',
                        'reason': f'event {event_type}'}), 200

    # Estrai mittente: UltraMsg usa "393331234567@c.us"
    mittente = str(data.get('from', '')).split('@')[0].strip()
    if not mittente:
        return jsonify({'status': 'ignored', 'reason': 'no sender'}), 200
    # Ignora gruppi (@g.us)
    if '@g.us' in str(data.get('from', '')):
        return jsonify({'status': 'ignored', 'reason': 'group'}), 200

    numero, _ = normalizza_telefono(mittente)
    pushname = str(data.get('pushname', '')).strip()
    nome_breve = pushname.split()[0][:100] if pushname else ''
    corpo = str(data.get('body', '')).strip()

    # Logga il messaggio in arrivo
    try:
        db.session.add(MessaggioWhatsapp(
            nome=nome_breve, telefono=numero, messaggio=corpo,
            stato='ricevuto', tipo='inbound'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WA-WEBHOOK] Errore log inbound: {e}")

    # Crea il contatto se non esiste ancora
    try:
        esistente = Contatto.query.filter(
            db.or_(Contatto.telefono == numero,
                   Contatto.telefono == mittente)).first()
        if not esistente:
            db.session.add(Contatto(
                nome=nome_breve or 'Contatto',
                cognome=' '.join(pushname.split()[1:])[:100]
                        if pushname else '',
                email='',
                telefono=numero,
                tipo_locale='Lead WhatsApp',
                messaggio=corpo or 'Messaggio in arrivo da WhatsApp',
                stato='nuovo',
                created_at=datetime.utcnow()))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[WA-WEBHOOK] Errore creazione contatto: {e}")

    # Auto-risposta solo se non già inviata di recente a questo numero
    cooldown = datetime.utcnow() - timedelta(hours=AUTO_REPLY_COOLDOWN_ORE)
    gia_risposto = MessaggioWhatsapp.query.filter(
        MessaggioWhatsapp.telefono == numero,
        MessaggioWhatsapp.tipo == 'auto_reply',
        MessaggioWhatsapp.stato == 'inviato',
        MessaggioWhatsapp.created_at >= cooldown
    ).first()

    if gia_risposto:
        return jsonify({'status': 'ok',
                        'auto_reply': False,
                        'reason': 'cooldown'}), 200

    invia_whatsapp(numero, _messaggio_benvenuto(nome_breve),
                   nome=nome_breve, tipo='auto_reply')

    return jsonify({'status': 'ok', 'auto_reply': True}), 200
