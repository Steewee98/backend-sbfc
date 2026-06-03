from flask import Blueprint, request, jsonify
import requests
from models import db, Contatto
from utils.whatsapp import invia_whatsapp
from utils.email import invia_email
from utils.templates import email_benvenuto_contatto
from datetime import datetime
import os
import csv
import io

google_leads_bp = Blueprint('google_leads', __name__)

SPREADSHEET_ID = '1PWYr4y1X3SQg9VGf2I1VR6p2hheDAyn3JaH5VztLnNw'


@google_leads_bp.route('/api/sync-leads', methods=['POST'])
def sync_leads():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        nuovi = 0
        già_presenti = 0

        # Legge il foglio come CSV pubblico
        for gid in ['0', '1', '2', '3']:
            url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"

            res = requests.get(url, timeout=15)
            if res.status_code != 200:
                continue

            content = res.content.decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))

            for riga in reader:
                # Estrai campi — prova vari nomi colonna
                nome = ''
                for key in riga.keys():
                    if any(k in key.lower() for k in
                           ['name', 'nome', 'full']):
                        nome = str(riga[key]).strip()
                        if nome:
                            break

                telefono = ''
                for key in riga.keys():
                    if any(k in key.lower() for k in
                           ['phone', 'telefono', 'number',
                            'numero', 'mobile']):
                        telefono = str(riga[key]).strip()
                        if telefono:
                            break

                email = ''
                for key in riga.keys():
                    if 'email' in key.lower() or \
                       'mail' in key.lower():
                        email = str(riga[key]).strip()
                        if email:
                            break

                if not telefono and not email:
                    continue

                if nome in ['', 'nan', 'None']:
                    nome = ''
                if telefono in ['', 'nan', 'None']:
                    telefono = ''
                if email in ['', 'nan', 'None']:
                    email = ''

                # Rimuovi prefisso "p:" dai numeri Meta Lead Form
                if telefono.startswith('p:'):
                    telefono = telefono[2:].strip()

                # Salta test lead
                if '<test lead' in nome.lower() or \
                   '<test lead' in telefono.lower():
                    continue

                if not telefono and not email:
                    continue

                # Controlla duplicati
                esistente = None
                if telefono:
                    esistente = Contatto.query\
                        .filter_by(telefono=telefono).first()
                if not esistente and email:
                    esistente = Contatto.query\
                        .filter_by(email=email).first()

                if esistente:
                    già_presenti += 1
                    continue

                # Salva
                nome_breve = nome.split()[0] \
                             if nome else 'Contatto'

                contatto = Contatto(
                    nome=nome_breve,
                    cognome=' '.join(nome.split()[1:])
                             if nome and len(nome.split()) > 1
                             else '',
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

                # WhatsApp
                if telefono:
                    try:
                        msg = f"""Buongiorno {nome_breve},

grazie per il suo interesse in SB Food Consulting.

Sono Simone Braghetta. Sarò felice di parlare del suo locale.

Prenoti una chiamata gratuita:
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone Braghetta"""
                        invia_whatsapp(telefono, msg,
                            nome=nome_breve,
                            tipo='meta_leads')
                    except Exception as e:
                        print(f"WA error: {e}")

                # Email
                if email:
                    try:
                        corpo = email_benvenuto_contatto(
                            nome_breve)
                        invia_email(
                            email, nome_breve,
                            "Grazie per il tuo interesse — "
                            "SB Food Consulting",
                            corpo
                        )
                    except Exception as e:
                        print(f"Email error: {e}")

        return jsonify({
            'success': True,
            'nuovi': nuovi,
            'già_presenti': già_presenti
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
