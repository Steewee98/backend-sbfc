from flask import Blueprint, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
from models import db, Contatto
from utils.whatsapp import invia_whatsapp
from utils.email import invia_email
from utils.templates import email_benvenuto_contatto
from datetime import datetime
import os
import json

google_leads_bp = Blueprint('google_leads', __name__)

SPREADSHEET_ID = '1PWYr4y1X3SQg9VGf2I1VR6p2hheDAyn3JaH5VztLnNw'


def get_google_client():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise Exception("GOOGLE_CREDENTIALS_JSON non configurato")

    creds_dict = json.loads(creds_json)
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets.readonly'
    ]
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=scopes)
    return gspread.authorize(creds)


@google_leads_bp.route('/api/sync-leads', methods=['POST'])
def sync_leads():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        client = get_google_client()
        sheet = client.open_by_key(SPREADSHEET_ID)

        nuovi = 0
        già_presenti = 0

        for worksheet in sheet.worksheets():
            righe = worksheet.get_all_records()

            for riga in righe:
                nome = str(riga.get('Full Name', '') or
                           riga.get('Nome', '') or
                           riga.get('full_name', '')).strip()

                telefono = str(riga.get('Phone Number', '') or
                               riga.get('Telefono', '') or
                               riga.get('phone_number', '')).strip()

                email = str(riga.get('Email', '') or
                            riga.get('email', '')).strip()

                if not telefono and not email:
                    continue

                # Controlla se esiste già
                esistente = None
                if telefono:
                    esistente = Contatto.query.filter_by(
                        telefono=telefono).first()
                if not esistente and email:
                    esistente = Contatto.query.filter_by(
                        email=email).first()

                if esistente:
                    già_presenti += 1
                    continue

                # Salva nuovo contatto
                contatto = Contatto(
                    nome=nome.split()[0] if nome else 'Contatto',
                    cognome=' '.join(nome.split()[1:]) if nome else '',
                    email=email,
                    telefono=telefono,
                    tipo_locale='Lead Meta Ads',
                    messaggio='Importato da Google Sheets - Meta Lead Form',
                    stato='nuovo',
                    created_at=datetime.utcnow()
                )
                db.session.add(contatto)
                db.session.commit()
                nuovi += 1

                nome_breve = nome.split()[0] if nome else 'Contatto'

                # Invia WhatsApp
                if telefono:
                    try:
                        messaggio_wa = f"""Buongiorno {nome_breve},

grazie per il suo interesse in SB Food Consulting.

Sono Simone Braghetta. Ho ricevuto la sua richiesta e sarò felice di parlare del suo locale.

Prenoti una chiamata gratuita di 30 minuti:
https://calendly.com/sbfoodconsulting-info/30min

A presto,
Simone Braghetta
SB Food Consulting"""
                        invia_whatsapp(
                            telefono, messaggio_wa,
                            nome=nome_breve,
                            tipo='meta_leads')
                    except Exception as e:
                        print(f"WhatsApp error: {e}")

                # Invia email
                if email:
                    try:
                        corpo = email_benvenuto_contatto(nome_breve)
                        invia_email(
                            email, nome_breve,
                            "Grazie per il tuo interesse — SB Food Consulting",
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
