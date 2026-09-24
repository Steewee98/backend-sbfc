"""Login del gestionale (admin.html e inbox WhatsApp).

Prima utente, password e chiave admin stavano scritti in admin.html, pubblico:
chiunque leggeva il sorgente aveva accesso a contatti, ordini e richieste.
Ora la pagina non contiene niente: manda utente e password qui, il server li
confronta con ADMIN_USER / ADMIN_PASSWORD_HASH (variabili Railway) e solo se
sono giusti restituisce la chiave ADMIN_TOKEN, che il resto delle API continua
a controllare com'era.

Per cambiare password:
    python3 -c "from werkzeug.security import generate_password_hash as g; print(g('NUOVA'))"
e si mette il risultato in ADMIN_PASSWORD_HASH su Railway (service web).
"""
import os
import time
import hmac
import logging
from collections import defaultdict, deque

from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash

logger = logging.getLogger(__name__)
admin_auth_bp = Blueprint('admin_auth', __name__)

# Freno ai tentativi: 8 errori in 15 minuti dallo stesso indirizzo e si aspetta.
MAX_ERRORI = 8
FINESTRA = 15 * 60
_errori = defaultdict(deque)


def _ip():
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '?').split(',')[0].strip()


def _bloccato(ip):
    q, ora = _errori[ip], time.time()
    while q and ora - q[0] > FINESTRA:
        q.popleft()
    return len(q) >= MAX_ERRORI


@admin_auth_bp.route('/api/admin/login', methods=['POST'])
def login():
    utente_ok = os.environ.get('ADMIN_USER', 'admin')
    hash_ok = os.environ.get('ADMIN_PASSWORD_HASH')
    token = os.environ.get('ADMIN_TOKEN')
    if not hash_ok or not token:
        logger.error('Login admin: ADMIN_PASSWORD_HASH o ADMIN_TOKEN mancanti')
        return jsonify({'error': 'Accesso non configurato sul server'}), 503

    ip = _ip()
    if _bloccato(ip):
        return jsonify({'error': 'Troppi tentativi sbagliati. Riprova fra un quarto d\'ora.'}), 429

    data = request.get_json(silent=True) or {}
    utente = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    # si controllano entrambi sempre, così la risposta non dice quale dei due era sbagliato
    utente_giusto = hmac.compare_digest(utente.encode(), utente_ok.encode())
    password_giusta = check_password_hash(hash_ok, password)
    if not (utente_giusto and password_giusta):
        _errori[ip].append(time.time())
        logger.warning('Login admin fallito da %s', ip)
        return jsonify({'error': 'Credenziali non valide'}), 401

    _errori.pop(ip, None)
    return jsonify({'token': token})
