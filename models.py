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
    # Quando True il contatto viene messo in cima alla coda del call center
    priorita_richiamo = db.Column(db.Boolean, default=False)
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
            'priorita_richiamo': bool(self.priorita_richiamo),
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


class MessaggioWhatsapp(db.Model):
    __tablename__ = 'messaggi_whatsapp'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    messaggio = db.Column(db.Text)
    stato = db.Column(db.String(50), default='inviato')
    tipo = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Prenotazione(db.Model):
    __tablename__ = 'prenotazioni'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    data_appuntamento = db.Column(db.DateTime, nullable=False)
    calendly_event_id = db.Column(db.String(300), unique=True)
    # Stato reminder: pending -> reminder_2h (reminder 1h prima) -> confermato / non_confermato
    stato = db.Column(db.String(30), default='pending')
    reminder_2d_inviato = db.Column(db.Boolean, default=False)  # legacy, non più usato
    reminder_2h_inviato = db.Column(db.Boolean, default=False)  # reminder 1h prima
    confermato = db.Column(db.Boolean, default=False)
    token_conferma = db.Column(db.String(64), unique=True)
    link_chiamata = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'email': self.email,
            'telefono': self.telefono,
            'data_appuntamento': self.data_appuntamento.isoformat(),
            'stato': self.stato,
            'reminder_2d_inviato': self.reminder_2d_inviato,
            'reminder_2h_inviato': self.reminder_2h_inviato,
            'confermato': self.confermato,
            'link_chiamata': self.link_chiamata,
            'created_at': self.created_at.isoformat(),
        }


class NoteChiamata(db.Model):
    __tablename__ = 'note_chiamate'

    id = db.Column(db.Integer, primary_key=True)
    contatto_id = db.Column(db.Integer, db.ForeignKey('contatti.id'), nullable=False)
    esito = db.Column(db.String(30), nullable=False)  # risposto, non_risponde, richiamare, non_interessato, appuntamento
    note = db.Column(db.Text)
    operatore = db.Column(db.String(100), default='Simone')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contatto = db.relationship('Contatto', backref=db.backref('note_chiamate', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'contatto_id': self.contatto_id,
            'esito': self.esito,
            'note': self.note,
            'operatore': self.operatore,
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


class EventoTraffico(db.Model):
    """Eventi di navigazione per-visitatore (solo con consenso cookie).
    visitor_id = persistente (localStorage), session_id = per visita."""
    __tablename__ = 'eventi_traffico'

    id = db.Column(db.Integer, primary_key=True)
    visitor_id = db.Column(db.String(64), index=True)
    session_id = db.Column(db.String(64), index=True)
    tipo = db.Column(db.String(30))   # pageview, click, scroll, tempo, identificazione
    pagina = db.Column(db.String(300))
    valore = db.Column(db.String(300))  # label CTA, % scroll, secondi, email...
    referrer = db.Column(db.String(500))
    dispositivo = db.Column(db.String(20))
    ip_hash = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'visitor_id': self.visitor_id,
            'session_id': self.session_id,
            'tipo': self.tipo,
            'pagina': self.pagina,
            'valore': self.valore,
            'referrer': self.referrer,
            'dispositivo': self.dispositivo,
            'created_at': self.created_at.isoformat(),
        }


class LeadStrumento(db.Model):
    """Lead raccolti dal download dei 7 strumenti PDF dell'Academy.
    L'email viene solo salvata (riuso marketing futuro) — nessuna mail transazionale.
    Il consenso marketing esplicito è la prova per poter riutilizzare l'email."""
    __tablename__ = 'lead_strumenti'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, index=True)
    strumento = db.Column(db.String(100), nullable=False, index=True)  # slug dello strumento
    consenso_marketing = db.Column(db.Boolean, default=False)
    consenso_at = db.Column(db.DateTime)  # timestamp del consenso (prova)
    referrer = db.Column(db.String(500))
    utm_source = db.Column(db.String(200))
    utm_medium = db.Column(db.String(200))
    utm_campaign = db.Column(db.String(200))
    dispositivo = db.Column(db.String(20))
    ip_hash = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'strumento': self.strumento,
            'consenso_marketing': bool(self.consenso_marketing),
            'consenso_at': self.consenso_at.isoformat() if self.consenso_at else None,
            'referrer': self.referrer,
            'utm_source': self.utm_source,
            'utm_medium': self.utm_medium,
            'utm_campaign': self.utm_campaign,
            'dispositivo': self.dispositivo,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class EmailInvio(db.Model):
    """Una riga per ogni email inviata via Resend. I timestamp degli eventi
    (consegna, apertura, click, rimbalzo, reclamo) vengono aggiornati dal
    webhook Resend (POST /api/webhook/resend). Serve al gestionale per i tassi
    di consegna/apertura/click."""
    __tablename__ = 'email_invii'

    id = db.Column(db.Integer, primary_key=True)
    resend_id = db.Column(db.String(100), unique=True, index=True)  # id restituito da Resend
    destinatario = db.Column(db.String(200), index=True)
    subject = db.Column(db.String(300))
    tipo = db.Column(db.String(50), index=True)  # grazie_download, benvenuto, credenziali, campagna, altro
    sent_at = db.Column(db.DateTime, index=True)
    delivered_at = db.Column(db.DateTime)
    opened_at = db.Column(db.DateTime)      # prima apertura
    clicked_at = db.Column(db.DateTime)     # primo click
    bounced_at = db.Column(db.DateTime)
    complained_at = db.Column(db.DateTime)  # segnalato come spam
    last_event = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'resend_id': self.resend_id,
            'destinatario': self.destinatario,
            'subject': self.subject,
            'tipo': self.tipo,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'clicked_at': self.clicked_at.isoformat() if self.clicked_at else None,
            'bounced_at': self.bounced_at.isoformat() if self.bounced_at else None,
            'complained_at': self.complained_at.isoformat() if self.complained_at else None,
            'last_event': self.last_event,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
