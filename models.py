from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Contatto(db.Model):
    __tablename__ = 'contatti'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cognome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(30))
    tipo_locale = db.Column(db.String(100))
    messaggio = db.Column(db.Text)
    stato = db.Column(db.String(20), default='nuovo')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'cognome': self.cognome,
            'email': self.email,
            'telefono': self.telefono,
            'tipo_locale': self.tipo_locale,
            'messaggio': self.messaggio,
            'stato': self.stato,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Studente(db.Model):
    __tablename__ = 'studenti'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    moduli_acquistati = db.Column(db.JSON, default=list)
    data_iscrizione = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_accesso = db.Column(db.DateTime)
    attivo = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'email': self.email,
            'moduli_acquistati': self.moduli_acquistati or [],
            'data_iscrizione': self.data_iscrizione.isoformat(),
            'ultimo_accesso': self.ultimo_accesso.isoformat() if self.ultimo_accesso else None,
            'attivo': self.attivo,
        }


class Evento(db.Model):
    __tablename__ = 'eventi'

    id = db.Column(db.Integer, primary_key=True)
    titolo = db.Column(db.String(200), nullable=False)
    data = db.Column(db.Date, nullable=False)
    ora_inizio = db.Column(db.String(5))
    ora_fine = db.Column(db.String(5))
    tipo = db.Column(db.String(30), default='call')
    nome_cliente = db.Column(db.String(200))
    note = db.Column(db.Text)
    link_call = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'titolo': self.titolo,
            'data': self.data.isoformat(),
            'ora_inizio': self.ora_inizio,
            'ora_fine': self.ora_fine,
            'tipo': self.tipo,
            'nome_cliente': self.nome_cliente,
            'note': self.note,
            'link_call': self.link_call,
            'created_at': self.created_at.isoformat(),
        }


class Pagamento(db.Model):
    __tablename__ = 'pagamenti'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    prodotto = db.Column(db.String(200), nullable=False)
    importo = db.Column(db.Float, nullable=False)
    stato = db.Column(db.String(20), default='completato')
    stripe_id = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'email': self.email,
            'prodotto': self.prodotto,
            'importo': self.importo,
            'stato': self.stato,
            'stripe_id': self.stripe_id,
            'created_at': self.created_at.isoformat(),
        }


class Visita(db.Model):
    __tablename__ = 'visite'

    id = db.Column(db.Integer, primary_key=True)
    pagina = db.Column(db.String(200), nullable=False)
    ip_hash = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    referrer = db.Column(db.String(500))
    paese = db.Column(db.String(100))
    dispositivo = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
