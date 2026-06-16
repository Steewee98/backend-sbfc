import os
from flask import Blueprint, request, jsonify
from models import db, Contatto, NoteChiamata
from datetime import datetime

callcenter_bp = Blueprint('callcenter', __name__)

ADMIN_TOKEN = lambda: os.environ.get('ADMIN_TOKEN')


def _check_admin():
    token = request.headers.get('X-Admin-Token')
    return token == ADMIN_TOKEN()


@callcenter_bp.route('/api/callcenter/coda', methods=['GET'])
def coda_chiamate():
    """Contatti da chiamare: hanno telefono, stato nuovo/contattato,
    ordinati dal più vecchio. Escludi chi ha già esito 'non_interessato' o 'appuntamento'."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401

    # Contatti con esiti definitivi (non_interessato, appuntamento) da escludere
    esiti_chiusi = db.session.query(NoteChiamata.contatto_id).filter(
        NoteChiamata.esito.in_(['non_interessato', 'appuntamento'])
    ).distinct().subquery()

    contatti = Contatto.query.filter(
        Contatto.telefono != '',
        Contatto.telefono.isnot(None),
        Contatto.stato.in_(['nuovo', 'contattato']),
        ~Contatto.id.in_(db.session.query(esiti_chiusi))
    ).order_by(
        db.func.coalesce(Contatto.priorita_richiamo, False).desc(),
        Contatto.created_at.asc()
    ).all()

    result = []
    for c in contatti:
        ultima_nota = NoteChiamata.query.filter_by(
            contatto_id=c.id
        ).order_by(NoteChiamata.created_at.desc()).first()

        result.append({
            **c.to_dict(),
            'ultima_nota': ultima_nota.to_dict() if ultima_nota else None,
            'totale_chiamate': c.note_chiamate.count()
        })

    return jsonify(result)


@callcenter_bp.route('/api/callcenter/note/<int:contatto_id>', methods=['GET'])
def note_contatto(contatto_id):
    """Storico note chiamate per un contatto."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401

    note = NoteChiamata.query.filter_by(
        contatto_id=contatto_id
    ).order_by(NoteChiamata.created_at.desc()).all()

    return jsonify([n.to_dict() for n in note])


@callcenter_bp.route('/api/callcenter/note', methods=['POST'])
def salva_nota():
    """Salva nota di una chiamata effettuata."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or not data.get('contatto_id') or not data.get('esito'):
        return jsonify({'error': 'contatto_id e esito obbligatori'}), 400

    esiti_validi = ['risposto', 'non_risponde', 'richiamare',
                    'non_interessato', 'appuntamento']
    if data['esito'] not in esiti_validi:
        return jsonify({'error': f'Esito non valido. Valori: {esiti_validi}'}), 400

    nota = NoteChiamata(
        contatto_id=data['contatto_id'],
        esito=data['esito'],
        note=data.get('note', ''),
        operatore=data.get('operatore', 'Simone')
    )
    db.session.add(nota)

    # Aggiorna stato contatto in base all'esito
    contatto = Contatto.query.get(data['contatto_id'])
    if contatto:
        if data['esito'] == 'appuntamento':
            contatto.stato = 'trattativa'
        elif data['esito'] == 'non_interessato':
            contatto.stato = 'chiuso_perso'
        elif data['esito'] in ['risposto', 'richiamare', 'non_risponde']:
            contatto.stato = 'contattato'
        contatto.updated_at = datetime.utcnow()

    db.session.commit()

    return jsonify(nota.to_dict()), 201
