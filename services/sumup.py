"""Le vendite dalla cassa SumUp, senza passare dal report (Rete SB, passo 4b).

Con la chiave API del locale (scope transactions.history) si legge lo storico
delle transazioni andate a buon fine e, per ognuna, i prodotti venduti.
Si sommano per giorno (ora di Roma) e per prodotto: sono le stesse righe che
darebbe il report CSV, così il resto (abbinamento ai piatti, diagnosi) non cambia.

Doc: https://developer.sumup.com/api/transactions/list
La chiave si salva cifrata (Fernet, dalla SECRET_KEY del server).
"""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from dateutil import tz

API = 'https://api.sumup.com'
ROMA = tz.gettz('Europe/Rome')
MAX_TRANSAZIONI = 5000


class ErroreSumUp(RuntimeError):
    pass


# ── la chiave, cifrata a riposo ──

def _fernet():
    k = hashlib.sha256((os.environ.get('SECRET_KEY') or 'dev-fallback-key').encode()).digest()
    return Fernet(base64.urlsafe_b64encode(k))


def cifra(chiave):
    return _fernet().encrypt(chiave.encode()).decode()


def decifra(testo):
    try:
        return _fernet().decrypt(testo.encode()).decode()
    except (InvalidToken, AttributeError):
        raise ErroreSumUp('Chiave SumUp non leggibile: ricollegala')


# ── chiamate ──

def _get(chiave, percorso, params=None):
    """Una GET all'API SumUp. Sostituita nei test."""
    url = API + percorso + ('?' + urllib.parse.urlencode(params, doseq=True) if params else '')
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {chiave}', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ErroreSumUp('SumUp rifiuta la chiave: controlla che sia giusta e abbia il permesso sulle transazioni')
        if e.code == 429:
            raise ErroreSumUp('SumUp chiede di rallentare: riprova tra qualche minuto')
        raise ErroreSumUp(f'SumUp ha risposto con errore {e.code}')
    except urllib.error.URLError:
        raise ErroreSumUp('SumUp non raggiungibile: riprova')


def profilo(chiave):
    """→ (codice esercente, nome) del conto a cui appartiene la chiave."""
    me = _get(chiave, '/v0.1/me') or {}
    m = me.get('merchant_profile') or {}
    codice = m.get('merchant_code')
    if not codice:
        raise ErroreSumUp('La chiave non è legata a un conto esercente SumUp')
    return codice, m.get('company_name') or m.get('doing_business_as', {}).get('business_name') or codice


def _utc(d):
    return d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def vendite(chiave, codice, dal, al):
    """Giorni dal..al (date locali, compresi) → ({(giorno, prodotto): {'quantita', 'incasso'}}, transazioni lette)."""
    inizio = datetime(dal.year, dal.month, dal.day, tzinfo=ROMA)
    fine = datetime(al.year, al.month, al.day, tzinfo=ROMA) + timedelta(days=1)
    params = {'oldest_time': _utc(inizio), 'newest_time': _utc(fine), 'statuses[]': ['SUCCESSFUL'],
              'types[]': ['PAYMENT'], 'limit': 100, 'order': 'ascending'}
    ids, percorso = [], f'/v2.1/merchants/{codice}/transactions/history'
    while percorso and len(ids) < MAX_TRANSAZIONI:
        pagina = _get(chiave, percorso, params) or {}
        ids += [t['id'] for t in pagina.get('items', []) if t.get('id')]
        nxt = next((l.get('href') for l in pagina.get('links', []) if l.get('rel') == 'next'), None)
        if not nxt:
            break
        # il link «next» porta i suoi parametri: a volte un indirizzo intero, a volte solo la query
        if '?' in nxt:
            parti = urllib.parse.urlsplit(nxt)
            percorso, params = parti.path, urllib.parse.parse_qs(parti.query)
        else:
            params = urllib.parse.parse_qs(nxt)

    out = defaultdict(lambda: {'quantita': 0.0, 'incasso': 0.0})
    for tid in ids:
        t = _get(chiave, f'/v2.1/merchants/{codice}/transactions', {'id': tid}) or {}
        quando = t.get('local_time') or t.get('timestamp')
        try:
            ts = datetime.fromisoformat(quando.replace('Z', '+00:00'))
        except (AttributeError, ValueError):
            continue
        giorno = (ts if ts.tzinfo is None else ts.astimezone(ROMA)).date()
        prodotti = t.get('products') or []
        if not prodotti:
            # pagamento senza prodotti (importo libero): una voce sola, riconoscibile
            prodotti = [{'name': 'Importo libero (senza prodotto)', 'quantity': 1, 'total_with_vat': t.get('amount')}]
        for p in prodotti:
            nome = (p.get('name') or 'Senza nome').strip()
            x = out[(giorno, nome)]
            x['quantita'] += float(p.get('quantity') or 0)
            tot = p.get('total_with_vat')
            if tot is None and p.get('price_with_vat') is not None:
                tot = float(p['price_with_vat']) * float(p.get('quantity') or 0)
            x['incasso'] += float(tot or 0)
    return dict(out), len(ids)
