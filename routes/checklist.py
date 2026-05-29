from flask import Blueprint, request, jsonify
from models import db
from datetime import datetime
import os

checklist_bp = Blueprint('checklist', __name__)


class RisultatoChecklist(db.Model):
    __tablename__ = 'risultati_checklist'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200))
    email = db.Column(db.String(200))
    punteggio_totale = db.Column(db.Integer)
    punteggio_food_cost = db.Column(db.Integer)
    punteggio_personale = db.Column(db.Integer)
    punteggio_menu = db.Column(db.Integer)
    punteggio_comunicazione = db.Column(db.Integer)
    punteggio_numeri = db.Column(db.Integer)
    risposte = db.Column(db.JSON)
    email_inviata = db.Column(db.Boolean, default=False)
    tipo_email = db.Column(db.String(20))  # 'critico', 'medio', 'buono'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@checklist_bp.route('/api/checklist', methods=['POST'])
def salva_checklist():
    data = request.json

    risultato = RisultatoChecklist(
        nome=data.get('nome'),
        email=data.get('email'),
        punteggio_totale=data.get('punteggio_totale'),
        punteggio_food_cost=data.get('punteggio_food_cost'),
        punteggio_personale=data.get('punteggio_personale'),
        punteggio_menu=data.get('punteggio_menu'),
        punteggio_comunicazione=data.get('punteggio_comunicazione'),
        punteggio_numeri=data.get('punteggio_numeri'),
        risposte=data.get('risposte', [])
    )
    db.session.add(risultato)
    db.session.commit()

    # Email notifica a Simone
    try:
        from utils.email import invia_email
        invia_email(
            'info@sbfoodconsulting.com',
            'Simone',
            f'Nuova checklist — {data.get("nome")} ({data.get("punteggio_totale")}/20)',
            f"""<h3>Nuova checklist completata</h3>
            <p><strong>Nome:</strong> {data.get('nome')}</p>
            <p><strong>Email:</strong> {data.get('email')}</p>
            <p><strong>Punteggio:</strong> {data.get('punteggio_totale')}/20</p>
            <p><strong>Food Cost:</strong> {data.get('punteggio_food_cost')}/4</p>
            <p><strong>Personale:</strong> {data.get('punteggio_personale')}/4</p>
            <p><strong>Menu:</strong> {data.get('punteggio_menu')}/4</p>
            <p><strong>Comunicazione:</strong> {data.get('punteggio_comunicazione')}/4</p>
            <p><strong>Numeri:</strong> {data.get('punteggio_numeri')}/4</p>
            <a href="https://www.sbfoodconsulting.com/admin.html">Apri gestionale →</a>"""
        )
    except Exception as e:
        print(f"Email non inviata: {e}")

    # Email automatica all'utente in base al punteggio
    punteggio = data.get('punteggio_totale', 0)
    nome = data.get('nome', '')
    email = data.get('email', '')

    try:
        from utils.email import invia_email
        from utils.templates_checklist import (
            email_checklist_critico,
            email_checklist_medio,
            email_checklist_buono
        )

        if punteggio <= 8:
            tipo = 'critico'
            oggetto = "Il tuo locale ha bisogno di un intervento — SB Food Consulting"
            corpo = email_checklist_critico(nome, punteggio, data)
        elif punteggio <= 14:
            tipo = 'medio'
            oggetto = "Abbiamo trovato le aree critiche del tuo locale — SB Food Consulting"
            corpo = email_checklist_medio(nome, punteggio, data)
        else:
            tipo = 'buono'
            oggetto = "Il tuo locale ha basi solide — ecco il prossimo passo"
            corpo = email_checklist_buono(nome, punteggio, data)

        if invia_email(email, nome, oggetto, corpo):
            risultato.email_inviata = True
            risultato.tipo_email = tipo
            db.session.commit()

    except Exception as e:
        print(f"Email checklist non inviata: {e}")

    return jsonify({'success': True}), 201


def _build_checklist_email(r):
    """Genera tipo, oggetto e corpo email per un risultato checklist."""
    from utils.templates_checklist import (
        email_checklist_critico, email_checklist_medio, email_checklist_buono
    )
    data = {
        'punteggio_food_cost': r.punteggio_food_cost,
        'punteggio_personale': r.punteggio_personale,
        'punteggio_menu': r.punteggio_menu,
        'punteggio_comunicazione': r.punteggio_comunicazione,
        'punteggio_numeri': r.punteggio_numeri,
    }
    p = r.punteggio_totale or 0
    if p <= 8:
        tipo = 'critico'
        oggetto = "Il tuo locale ha bisogno di un intervento — SB Food Consulting"
        corpo = email_checklist_critico(r.nome, p, data)
    elif p <= 14:
        tipo = 'medio'
        oggetto = "Abbiamo trovato le aree critiche del tuo locale — SB Food Consulting"
        corpo = email_checklist_medio(r.nome, p, data)
    else:
        tipo = 'buono'
        oggetto = "Il tuo locale ha basi solide — ecco il prossimo passo"
        corpo = email_checklist_buono(r.nome, p, data)
    return tipo, oggetto, corpo


@checklist_bp.route('/api/checklist/<int:id>/invia-email', methods=['POST'])
def invia_email_checklist(id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    r = RisultatoChecklist.query.get_or_404(id)
    tipo, oggetto, corpo = _build_checklist_email(r)

    from utils.email import invia_email
    if invia_email(r.email, r.nome, oggetto, corpo):
        r.email_inviata = True
        r.tipo_email = tipo
        db.session.commit()
        return jsonify({'success': True, 'tipo_email': tipo})
    return jsonify({'error': 'Invio fallito'}), 500


@checklist_bp.route('/api/checklist/<int:id>/email-preview', methods=['GET'])
def preview_email_checklist(id):
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    r = RisultatoChecklist.query.get_or_404(id)
    tipo, oggetto, corpo = _build_checklist_email(r)
    return corpo, 200, {'Content-Type': 'text/html; charset=utf-8'}


@checklist_bp.route('/api/checklist', methods=['GET'])
def get_checklist():
    token = request.headers.get('X-Admin-Token')
    if token != os.environ.get('ADMIN_TOKEN'):
        return jsonify({'error': 'Unauthorized'}), 401

    risultati = RisultatoChecklist.query\
        .order_by(RisultatoChecklist.created_at.desc())\
        .all()

    return jsonify([{
        'id': r.id,
        'nome': r.nome,
        'email': r.email,
        'punteggio_totale': r.punteggio_totale,
        'punteggio_food_cost': r.punteggio_food_cost,
        'punteggio_personale': r.punteggio_personale,
        'punteggio_menu': r.punteggio_menu,
        'punteggio_comunicazione': r.punteggio_comunicazione,
        'punteggio_numeri': r.punteggio_numeri,
        'risposte': r.risposte,
        'email_inviata': r.email_inviata or False,
        'tipo_email': r.tipo_email,
        'created_at': r.created_at.isoformat()
    } for r in risultati])
