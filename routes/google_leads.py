from flask import Blueprint, request, jsonify
import requests
import threading
from models import db, Contatto, MessaggioWhatsapp
from utils.whatsapp import invia_whatsapp, normalizza_telefono
from utils.email import invia_email
from utils.templates import email_benvenuto_contatto
from datetime import datetime
import os
import csv
import io

google_leads_bp = Blueprint('google_leads', __name__)

SPREADSHEET_ID = '1PWYr4y1X3SQg9VGf2I1VR6p2hheDAyn3JaH5VztLnNw'

_sync_lock = threading.Lock()


def _do_sync():
    """Core sync logic — ritorna (nuovi, già_presenti). Thread-safe."""
    if not _sync_lock.acquire(blocking=False):
        print("[SYNC] Già in esecuzione, skip")
        return 0, 0
    try:
        return _do_sync_inner()
    finally:
        _sync_lock.release()


def _do_sync_inner():
    nuovi = 0
    già_presenti = 0

    for gid in ['0', '1', '2', '3']:
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"

        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            continue

        content = res.content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))

        for riga in reader:
            nome = ''
            for exact in ['full_name', 'Full Name', 'Nome',
                          'nome']:
                if exact in riga and str(riga[exact]).strip():
                    nome = str(riga[exact]).strip()
                    break
            if not nome:
                for key in riga.keys():
                    kl = key.lower()
                    if kl in ['full_name', 'nome', 'name'] \
                       or 'full' in kl:
                        nome = str(riga[key]).strip()
                        if nome:
                            break

            telefono = ''
            for exact in ['phone', 'Phone', 'Phone Number',
                          'Telefono', 'telefono', 'mobile']:
                if exact in riga and str(riga[exact]).strip():
                    telefono = str(riga[exact]).strip()
                    break
            if not telefono:
                for key in riga.keys():
                    kl = key.lower()
                    if kl in ['phone', 'telefono', 'mobile',
                              'phone_number']:
                        telefono = str(riga[key]).strip()
                        if telefono:
                            break

            email = ''
            for exact in ['email', 'Email', 'e-mail']:
                if exact in riga and str(riga[exact]).strip():
                    email = str(riga[exact]).strip()
                    break

            if not telefono and not email:
                continue

            if nome in ['', 'nan', 'None']:
                nome = ''
            if telefono in ['', 'nan', 'None']:
                telefono = ''
            if email in ['', 'nan', 'None']:
                email = ''

            if telefono.startswith('p:'):
                telefono = telefono[2:].strip()

            if '<test lead' in nome.lower() or \
               '<test lead' in telefono.lower():
                continue

            if not telefono and not email:
                continue

            # Normalizza telefono per il check duplicati
            tel_norm = telefono
            if telefono:
                tel_norm, _ = normalizza_telefono(telefono)

            esistente = None
            if telefono:
                esistente = Contatto.query.filter(
                    db.or_(
                        Contatto.telefono == telefono,
                        Contatto.telefono == tel_norm
                    )
                ).first()
            if not esistente and email:
                esistente = Contatto.query\
                    .filter_by(email=email).first()

            if esistente:
                già_presenti += 1
                continue

            nome_breve = nome.split()[0] \
                         if nome else 'Contatto'
            cognome_lead = ' '.join(nome.split()[1:]) \
                           if nome and len(nome.split()) > 1 \
                           else ''

            # Tronca campi per evitare errori DB
            nome_breve = nome_breve[:100]
            cognome_lead = cognome_lead[:100]

            try:
                contatto = Contatto(
                    nome=nome_breve,
                    cognome=cognome_lead,
                    email=email,
                    telefono=telefono,
                    tipo_locale='Lead Meta Ads',
                    messaggio='Da Google Sheets Meta Lead Form',
                    stato='nuovo',
                    created_at=datetime.utcnow()
                )
                db.session.add(contatto)
                db.session.commit()
                nuovi += 1
            except Exception as e:
                db.session.rollback()
                print(f"[SYNC] Errore inserimento lead {nome_breve}: {e}")
                continue

            contattato_ok = False

            # NB: l'invio WhatsApp a freddo è DISABILITATO.
            # Mandare messaggi a numeri che non ci hanno scritto per primi
            # ha causato la sospensione del profilo. I lead con telefono ma
            # senza email restano 'nuovo' e vanno chiamati dal call center.

            if email:
                try:
                    corpo = email_benvenuto_contatto(
                        nome_breve)
                    if invia_email(
                        email, nome_breve,
                        "Grazie per il tuo interesse — "
                        "SB Food Consulting",
                        corpo
                    ):
                        contattato_ok = True
                except Exception as e:
                    print(f"Email error: {e}")

            # Aggiorna lo stato: il lead è stato effettivamente contattato
            if contattato_ok:
                contatto.stato = 'contattato'
                db.session.commit()

    return nuovi, già_presenti


@google_leads_bp.route('/api/sync-leads', methods=['POST'])
def sync_leads():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        nuovi, già_presenti = _do_sync()
        return jsonify({
            'success': True,
            'nuovi': nuovi,
            'già_presenti': già_presenti
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@google_leads_bp.route('/api/fix-lead-names', methods=['POST'])
def fix_lead_names():
    """Corregge i nomi dei lead importati con nome sbagliato."""
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        # Leggi il foglio per avere i nomi corretti
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0"
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            return jsonify({'error': 'Cannot read sheet'}), 500

        content = res.content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))

        corretti = 0
        for riga in reader:
            telefono = str(riga.get('phone', '')).strip()
            full_name = str(riga.get('full_name', '')).strip()

            if not telefono or not full_name:
                continue
            if telefono.startswith('p:'):
                telefono = telefono[2:].strip()
            if '<test lead' in full_name.lower():
                continue

            nome_breve = full_name.split()[0]

            # Fix contatti
            contatto = Contatto.query.filter_by(
                telefono=telefono).first()
            if contatto and contatto.nome == 'Nuova':
                contatto.nome = nome_breve
                contatto.cognome = ' '.join(
                    full_name.split()[1:]) if len(
                    full_name.split()) > 1 else ''
                db.session.commit()
                corretti += 1

            # Fix log WhatsApp
            logs_wa = MessaggioWhatsapp.query.filter_by(
                telefono=telefono, nome='Nuova').all()
            for log in logs_wa:
                log.nome = nome_breve
            if logs_wa:
                db.session.commit()
                corretti += len(logs_wa)

        return jsonify({'success': True, 'corretti': corretti})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@google_leads_bp.route('/api/retry-failed-wa', methods=['POST'])
def retry_failed_wa():
    """Rimanda WhatsApp ai contatti Meta Ads con messaggio fallito."""
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    # Trova messaggi meta_leads in errore
    falliti = MessaggioWhatsapp.query.filter(
        MessaggioWhatsapp.tipo == 'meta_leads',
        MessaggioWhatsapp.stato.in_(['errore', 'numero_invalido'])
    ).all()

    # Trova contatti Meta Ads senza nessun log WhatsApp
    contatti_meta = Contatto.query.filter_by(
        tipo_locale='Lead Meta Ads'
    ).filter(Contatto.telefono != '').all()

    telefoni_con_log = {m.telefono for m in
        MessaggioWhatsapp.query.filter_by(tipo='meta_leads').all()}

    reinviati = 0
    errori = 0

    # Retry messaggi falliti
    numeri_fatti = set()
    for msg in falliti:
        if msg.telefono in numeri_fatti:
            continue
        numeri_fatti.add(msg.telefono)
        nome = msg.nome or 'Contatto'
        testo = f"""Buongiorno {nome},

grazie per il suo interesse in SB Food Consulting.

Sono Simone Braghetta. Sarò felice di parlare del suo locale.

Prenoti una chiamata gratuita:
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone Braghetta"""
        try:
            if invia_whatsapp(msg.telefono, testo,
                              nome=nome, tipo='meta_leads'):
                reinviati += 1
            else:
                errori += 1
        except Exception:
            errori += 1

    # Contatti senza alcun log WA
    for c in contatti_meta:
        if c.telefono in numeri_fatti:
            continue
        if c.telefono in telefoni_con_log:
            continue
        numeri_fatti.add(c.telefono)
        nome = c.nome or 'Contatto'
        testo = f"""Buongiorno {nome},

grazie per il suo interesse in SB Food Consulting.

Sono Simone Braghetta. Sarò felice di parlare del suo locale.

Prenoti una chiamata gratuita:
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone Braghetta"""
        try:
            if invia_whatsapp(c.telefono, testo,
                              nome=nome, tipo='meta_leads'):
                reinviati += 1
            else:
                errori += 1
        except Exception:
            errori += 1

    return jsonify({
        'success': True,
        'reinviati': reinviati,
        'errori': errori,
        'totale_tentati': len(numeri_fatti)
    })


@google_leads_bp.route('/api/fix-blocco-profilo', methods=['POST'])
def fix_blocco_profilo():
    """One-shot: dopo il blocco del profilo WhatsApp i messaggi risultavano
    'inviato' ma non sono mai partiti. Cancella quei log fasulli e rimette
    in coda (in cima) i contatti che credevamo di aver contattato.

    Body opzionale: {"cutoff": "2026-06-11T08:57:57.306411", "dry_run": true}
    """
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    cutoff_str = data.get('cutoff', '2026-06-11T08:57:57.306411')
    dry_run = bool(data.get('dry_run', False))

    try:
        cutoff = datetime.fromisoformat(cutoff_str)
    except ValueError:
        return jsonify({'error': f'cutoff non valido: {cutoff_str}'}), 400

    # Messaggi che dichiarano l'invio ma sono falliti (profilo bloccato)
    falsi = MessaggioWhatsapp.query.filter(
        MessaggioWhatsapp.stato == 'inviato',
        MessaggioWhatsapp.created_at >= cutoff
    ).all()

    # Numeri coinvolti, normalizzati per il match coi contatti
    numeri_falliti = set()
    for m in falsi:
        if m.telefono:
            norm, _ = normalizza_telefono(m.telefono)
            numeri_falliti.add(norm)

    # Contatti che credevamo contattati ma non lo sono
    candidati = Contatto.query.filter(
        Contatto.telefono.isnot(None),
        Contatto.telefono != '',
        Contatto.stato.in_(['nuovo', 'contattato'])
    ).all()

    contatti_da_riportare = []
    for c in candidati:
        norm, _ = normalizza_telefono(c.telefono)
        if norm in numeri_falliti:
            contatti_da_riportare.append(c)

    if dry_run:
        return jsonify({
            'dry_run': True,
            'cutoff': cutoff_str,
            'messaggi_da_cancellare': len(falsi),
            'contatti_da_riportare': len(contatti_da_riportare),
            'anteprima_contatti': [
                {'id': c.id, 'nome': c.nome, 'telefono': c.telefono,
                 'stato': c.stato}
                for c in contatti_da_riportare[:20]
            ]
        })

    # 1) Cancella i log fasulli
    for m in falsi:
        db.session.delete(m)

    # 2) Riporta i contatti in cima: stato -> nuovo + priorità richiamo
    riportati = 0
    for c in contatti_da_riportare:
        if c.stato == 'contattato':
            c.stato = 'nuovo'
        c.priorita_richiamo = True
        c.updated_at = datetime.utcnow()
        riportati += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'cutoff': cutoff_str,
        'messaggi_cancellati': len(falsi),
        'contatti_riportati_in_cima': riportati
    })


@google_leads_bp.route('/api/auto-sync-leads', methods=['POST'])
def auto_sync_leads():
    """Endpoint per cron automatico — usa token dedicato."""
    cron_token = request.headers.get('X-Cron-Token') or \
                 request.args.get('token')
    expected = os.environ.get('CRON_TOKEN',
                              os.environ.get('ADMIN_TOKEN'))
    if cron_token != expected:
        return jsonify({'error': 'Unauthorized'}), 401

    # Richiama sync_leads internamente
    import flask
    with flask.current_app.test_request_context(
            '/api/sync-leads',
            method='POST',
            headers={'X-Admin-Token': os.environ.get('ADMIN_TOKEN')}):
        return sync_leads()
