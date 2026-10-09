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


class FilePrivato(db.Model):
    """File venduti (es. manuali PDF) tenuti nel database e non nei repository, che sono
    pubblici: si scaricano solo dal link firmato mandato a chi ha pagato
    (routes/pagamenti.py, /api/download/<slug>)."""
    __tablename__ = 'file_privati'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    nome_file = db.Column(db.String(200), nullable=False)
    mime = db.Column(db.String(100), default='application/pdf')
    dati = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CodaCampagna(db.Model):
    """Invii scaglionati di una campagna email: una riga per destinatario. Il giro in
    background (app.py → processa_coda) ne manda al massimo N al giorno."""
    __tablename__ = 'coda_campagne'
    __table_args__ = (db.UniqueConstraint('campagna', 'email', name='uq_coda_campagna_email'),)

    id = db.Column(db.Integer, primary_key=True)
    campagna = db.Column(db.String(50), nullable=False, index=True)
    email = db.Column(db.String(200), nullable=False)
    stato = db.Column(db.String(20), default='in_coda', index=True)  # in_coda | inviata | fallita | saltata
    tentativi = db.Column(db.Integer, default=0)
    resend_id = db.Column(db.String(100))
    creata_at = db.Column(db.DateTime, default=datetime.utcnow)
    inviata_at = db.Column(db.DateTime)


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


class EmailSequenza(db.Model):
    """Iscrizione di un lead alla sequenza nurture automatica (una email a settimana).
    L'iscrizione è per PERSONA (email unica), non per download: un lead entra una
    sola volta e non viene mai re-iscritto (niente email doppie).

    step = numero di email nurture già inviate (0..6). Quando step raggiunge 6 la
    sequenza diventa 'completata'. prossimo_invio_at indica quando è dovuta la
    prossima email; il processore giornaliero invia le sequenze con data <= adesso
    e sposta la data avanti di 7 giorni."""
    __tablename__ = 'email_sequenze'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    segmento = db.Column(db.String(30), default='numeri')  # numeri | sistema | lancio
    step = db.Column(db.Integer, default=0)                # email già inviate (0..6)
    stato = db.Column(db.String(20), default='attiva', index=True)  # attiva|completata|disiscritta|sospesa
    prossimo_invio_at = db.Column(db.DateTime, index=True)
    last_sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'segmento': self.segmento,
            'step': self.step,
            'stato': self.stato,
            'prossimo_invio_at': self.prossimo_invio_at.isoformat() if self.prossimo_invio_at else None,
            'last_sent_at': self.last_sent_at.isoformat() if self.last_sent_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class OrdineNfc(db.Model):
    """Ordine di una Placca NFC recensioni (shop sbfoodconsulting.com/placca-nfc).

    Creato PRIMA del pagamento (stato 'in_attesa'); il webhook Stripe lo porta a
    'pagato' e salva l'indirizzo di spedizione raccolto da Stripe. Lo slug è
    l'identificativo pubblico scritto sul tag NFC: il tap apre
    sbfoodconsulting.com/tap.html?p=<slug> che legge /api/nfc/p/<slug>.
    """
    __tablename__ = 'ordini_nfc'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    stato = db.Column(db.String(30), default='in_attesa')  # in_attesa · pagato · in_lavorazione · spedito · consegnato · annullato
    tier = db.Column(db.String(40), nullable=False)        # base · personalizzata · personalizzata-menu
    quantita = db.Column(db.Integer, default=1)
    variante = db.Column(db.String(20))                     # chiara · scura (solo tier base)

    nome_locale = db.Column(db.String(200), nullable=False)
    referente = db.Column(db.String(200))
    email = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(50))

    link_google = db.Column(db.String(600))
    link_tripadvisor = db.Column(db.String(600))
    link_thefork = db.Column(db.String(600))

    colore_primario = db.Column(db.String(20))
    colore_sfondo = db.Column(db.String(20))
    testo_placca = db.Column(db.String(200))
    menu_link = db.Column(db.String(600))
    note = db.Column(db.Text)
    # allegati: {'logo': {'nome','mime','dati'(base64)}, 'foto': {...}, 'menu': {...}}
    allegati = db.Column(db.JSON, default=dict)
    # la famiglia del tap: pezzi che viaggiano con la placca recensioni, stesso slug.
    # {'menu': {'quantita': n, 'variante': 'scura'|'chiara'}, 'wifi': {...}}
    # Il tag menù punta a tap.html?p=<slug>&t=menu, il Wi-Fi a &t=wifi.
    articoli = db.Column(db.JSON, default=dict)
    wifi_rete = db.Column(db.String(100))
    wifi_password = db.Column(db.String(100))
    sconto = db.Column(db.Float)          # euro scalati dal kit, già dentro importo

    importo = db.Column(db.Float)
    stripe_id = db.Column(db.String(200))
    spedizione = db.Column(db.JSON)   # nome + indirizzo raccolti da Stripe
    tap_count = db.Column(db.Integer, default=0)
    tap_pezzi = db.Column(db.JSON, default=dict)   # {'menu': n, 'wifi': n}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pagato_at = db.Column(db.DateTime)

    def to_dict(self, con_allegati=False):
        alle = self.allegati or {}
        d = {
            'id': self.id, 'slug': self.slug, 'stato': self.stato,
            'tier': self.tier, 'quantita': self.quantita, 'variante': self.variante,
            'nome_locale': self.nome_locale, 'referente': self.referente,
            'email': self.email, 'telefono': self.telefono,
            'link_google': self.link_google, 'link_tripadvisor': self.link_tripadvisor,
            'link_thefork': self.link_thefork,
            'colore_primario': self.colore_primario, 'colore_sfondo': self.colore_sfondo,
            'testo_placca': self.testo_placca, 'menu_link': self.menu_link,
            'note': self.note,
            'allegati': {k: {'nome': v.get('nome'), 'mime': v.get('mime')} for k, v in alle.items()},
            'importo': self.importo, 'stripe_id': self.stripe_id,
            'spedizione': self.spedizione, 'tap_count': self.tap_count or 0,
            'articoli': self.articoli or {}, 'wifi_rete': self.wifi_rete,
            'wifi_password': self.wifi_password, 'sconto': self.sconto,
            'tap_pezzi': self.tap_pezzi or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'pagato_at': self.pagato_at.isoformat() if self.pagato_at else None,
        }
        if con_allegati:
            d['allegati'] = alle
        return d


class RichiestaNfc(db.Model):
    """Richiesta specifica dal box in fondo allo shop Placca NFC.

    Non è un ordine: è una domanda o un'esigenza fuori dai tre tier
    (grandi quantità, formati diversi, dubbi sulla grafica...). Arriva
    senza pagamento e va lavorata a mano dal gestionale.
    """
    __tablename__ = 'richieste_nfc'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200))
    nome_locale = db.Column(db.String(200))
    email = db.Column(db.String(200), nullable=False)
    telefono = db.Column(db.String(50))
    quantita = db.Column(db.String(50))
    messaggio = db.Column(db.Text, nullable=False)
    stato = db.Column(db.String(20), default='nuova')  # nuova · in_corso · chiusa
    note_interne = db.Column(db.Text)
    # file mandati col configuratore del menù digitale: {'menu'|'foto'|'logo': {'nome','mime','dati'(base64)}}
    allegati = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'allegati': {k: {'nome': v.get('nome'), 'mime': v.get('mime')} for k, v in (self.allegati or {}).items()},
            'id': self.id, 'nome': self.nome, 'nome_locale': self.nome_locale,
            'email': self.email, 'telefono': self.telefono, 'quantita': self.quantita,
            'messaggio': self.messaggio, 'stato': self.stato,
            'note_interne': self.note_interne,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class LocaleRete(db.Model):
    """Un locale della rete SB (consulenza continuativa con console e motore dati).

    Nasce all'incontro iniziale col ristoratore: la scheda compilata dal
    consulente sta in `scheda` (JSON, sezioni locale/persone/numeri/cucina/
    formalita/obiettivi) e i file in `allegati` (menù, foto dei turni, ricette).
    Stato: incontro → avvio → attivo (→ sospeso).
    """
    __tablename__ = 'rete_locali'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(40))
    citta = db.Column(db.String(120))
    stato = db.Column(db.String(20), default='incontro')
    consulente = db.Column(db.String(120))
    scheda = db.Column(db.JSON, default=dict)
    # food cost: {'obiettivo': 30, 'iva': 10, 'colonne_cassa': {...}}
    impostazioni = db.Column(db.JSON, default=dict)
    # l'indirizzo dell'app del locale (tag all'ingresso): /app/?l=<codice>, non si indovina
    codice = db.Column(db.String(16), unique=True, index=True)
    # {'<chiave>': {'nome','mime','dati'(base64),'caricato'}}
    allegati = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, completa=False):
        d = {
            'id': self.id, 'nome': self.nome, 'tipo': self.tipo, 'citta': self.citta,
            'stato': self.stato, 'consulente': self.consulente,
            # la chiave della cassa resta nel server, anche se cifrata
            'impostazioni': {k: ({kk: vv for kk, vv in v.items() if kk != 'chiave'} if isinstance(v, dict) and k == 'sumup' else v)
                             for k, v in (self.impostazioni or {}).items()},
            'allegati': {k: {'nome': v.get('nome'), 'mime': v.get('mime'), 'caricato': v.get('caricato')}
                         for k, v in (self.allegati or {}).items()},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if completa:
            d['scheda'] = self.scheda or {}
        return d


# ═══════════════════════════════════════════════════════════════════
# Rete SB — fase 1, il food cost. Tutto è per locale (locale_id).
# Le quantità degli articoli sono sempre nell'unità dell'articolo
# (kg, l, pz): le righe delle fatture ci arrivano con l'alias.
# ═══════════════════════════════════════════════════════════════════

class ArticoloRete(db.Model):
    """Un ingrediente del locale (fiordilatte, farina 00, guanciale…).
    `prezzo` = ultimo costo per unità, preso dalle fatture collegate."""
    __tablename__ = 'rete_articoli'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    nome = db.Column(db.String(160), nullable=False)
    unita = db.Column(db.String(8), nullable=False, default='kg')   # kg | l | pz
    categoria = db.Column(db.String(60))
    prezzo = db.Column(db.Float)            # € per unità, IVA esclusa
    prezzo_data = db.Column(db.Date)        # data della fattura da cui viene
    # prezzo medio all'ingrosso stimato dal catalogo (services/catalogo.py) finché non arriva una fattura:
    # serve solo al food cost delle ricette e si dice sempre che è una stima; la diagnosi usa solo `prezzo`
    prezzo_stima = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'locale_id': self.locale_id, 'nome': self.nome, 'unita': self.unita,
                'categoria': self.categoria, 'prezzo': self.prezzo, 'prezzo_stima': self.prezzo_stima,
                'prezzo_data': self.prezzo_data.isoformat() if self.prezzo_data else None}


class AliasArticolo(db.Model):
    """Come il fornitore chiama un articolo in fattura → l'articolo del locale.
    La prima volta lo collega il consulente, poi vale per tutte le fatture.
    `fattore` = unità dell'articolo per ogni unità della riga
    (riga «FIORDILATTE JULIENNE 3KG» in pezzi → 3 kg a pezzo)."""
    __tablename__ = 'rete_alias_articoli'
    __table_args__ = (db.UniqueConstraint('locale_id', 'chiave', name='uq_alias_locale_chiave'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    chiave = db.Column(db.String(320), nullable=False)     # partita IVA fornitore | codice o descrizione normalizzata
    articolo_id = db.Column(db.Integer, db.ForeignKey('rete_articoli.id', ondelete='CASCADE'), nullable=False)
    fattore = db.Column(db.Float, nullable=False, default=1.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FatturaRete(db.Model):
    """Una fattura elettronica di acquisto (FatturaPA) caricata per un locale.
    Le note di credito (TD04) hanno `segno` −1."""
    __tablename__ = 'rete_fatture'
    __table_args__ = (db.UniqueConstraint('locale_id', 'piva', 'numero', 'data', name='uq_fattura_locale'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    fornitore = db.Column(db.String(200))
    piva = db.Column(db.String(30))
    numero = db.Column(db.String(60), nullable=False)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(6))           # TD01, TD04…
    segno = db.Column(db.Integer, default=1)
    imponibile = db.Column(db.Float)
    file_nome = db.Column(db.String(200))
    etichette = db.Column(db.JSON)           # fonte (xml|pdf|foto), documento, categoria, note, controlla…
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    righe = db.relationship('RigaFattura', backref='fattura', cascade='all, delete-orphan',
                            order_by='RigaFattura.n', lazy='selectin')

    def to_dict(self):
        collegate = sum(1 for r in self.righe if r.articolo_id)
        con_qta = sum(1 for r in self.righe if r.quantita)
        return {'id': self.id, 'fornitore': self.fornitore, 'piva': self.piva, 'numero': self.numero,
                'data': self.data.isoformat(), 'tipo': self.tipo, 'imponibile': self.imponibile,
                'righe': len(self.righe), 'righe_merce': con_qta, 'collegate': collegate,
                'file_nome': self.file_nome, 'segno': self.segno, 'etichette': self.etichette or {}}


class RigaFattura(db.Model):
    """Una riga di dettaglio della fattura. `chiave` è la stessa degli alias:
    serve a ritrovare tutte le righe dello stesso prodotto."""
    __tablename__ = 'rete_righe_fattura'

    id = db.Column(db.Integer, primary_key=True)
    fattura_id = db.Column(db.Integer, db.ForeignKey('rete_fatture.id', ondelete='CASCADE'), nullable=False, index=True)
    n = db.Column(db.Integer)
    codice = db.Column(db.String(60))
    descrizione = db.Column(db.String(500))
    chiave = db.Column(db.String(320), index=True)
    quantita = db.Column(db.Float)           # nell'unità della riga; None = spese, trasporto…
    unita = db.Column(db.String(20))
    totale = db.Column(db.Float)             # PrezzoTotale, sconti compresi, IVA esclusa
    articolo_id = db.Column(db.Integer, db.ForeignKey('rete_articoli.id', ondelete='SET NULL'), index=True)
    quantita_articolo = db.Column(db.Float)  # quantita × fattore dell'alias
    ignorata = db.Column(db.Boolean, default=False)   # non è cibo (detersivi, imballi): fuori dal food cost

    def to_dict(self):
        return {'id': self.id, 'n': self.n, 'codice': self.codice, 'descrizione': self.descrizione,
                'quantita': self.quantita, 'unita': self.unita, 'totale': self.totale,
                'articolo_id': self.articolo_id, 'quantita_articolo': self.quantita_articolo, 'ignorata': bool(self.ignorata),
                'chiave': self.chiave}


class RicettaRete(db.Model):
    """Un piatto del menù con le sue grammature. Le quantità delle righe
    sono per l'intera `resa` (una teglia da 8 porzioni, o 1 pizza)."""
    __tablename__ = 'rete_ricette'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    nome = db.Column(db.String(160), nullable=False)
    categoria = db.Column(db.String(60))
    prezzo = db.Column(db.Float)             # prezzo di vendita in menù, IVA compresa
    resa = db.Column(db.Float, default=1.0)  # porzioni che escono dalle quantità scritte
    # proposta dall'analisi delle vendite (catalogo o AI): grammature standard, il consulente le controlla
    automatica = db.Column(db.Boolean, default=False)
    nota = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    righe = db.relationship('RigaRicetta', backref='ricetta', cascade='all, delete-orphan', lazy='selectin')


class RigaRicetta(db.Model):
    __tablename__ = 'rete_ricetta_righe'

    id = db.Column(db.Integer, primary_key=True)
    ricetta_id = db.Column(db.Integer, db.ForeignKey('rete_ricette.id', ondelete='CASCADE'), nullable=False, index=True)
    articolo_id = db.Column(db.Integer, db.ForeignKey('rete_articoli.id', ondelete='CASCADE'), nullable=False)
    quantita = db.Column(db.Float, nullable=False)   # nell'unità dell'articolo (kg, l, pz)


class AliasVendita(db.Model):
    """Come la cassa chiama un piatto → la ricetta. `ricetta_id` vuoto con
    `ignorata` = voce fuori dal food cost (coperto, bevande, caffè)."""
    __tablename__ = 'rete_alias_vendite'
    __table_args__ = (db.UniqueConstraint('locale_id', 'voce', name='uq_alias_vendita'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    voce = db.Column(db.String(200), nullable=False)          # normalizzata
    ricetta_id = db.Column(db.Integer, db.ForeignKey('rete_ricette.id', ondelete='CASCADE'))
    ignorata = db.Column(db.Boolean, default=False)
    categoria = db.Column(db.String(40))       # caffetteria, cucina, bevande, birre… (dall'analisi delle vendite)
    automatico = db.Column(db.Boolean, default=False)   # abbinata dall'analisi: il consulente può cambiarla


class UnioneVoce(db.Model):
    """Voci della cassa che sono lo stesso prodotto scritto in modi diversi («Caffe», «Caffè», «CAFFE'»):
    tutte si leggono come `canonica`, col nome `nome`. Le trova l'analisi delle vendite; il consulente le può sciogliere."""
    __tablename__ = 'rete_unioni_voci'
    __table_args__ = (db.UniqueConstraint('locale_id', 'voce', name='uq_unione_voce'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    voce = db.Column(db.String(200), nullable=False)
    canonica = db.Column(db.String(200), nullable=False)
    nome = db.Column(db.String(200))
    perche = db.Column(db.String(20))          # catalogo | somiglianza | ai


class VenditaRete(db.Model):
    """Quante volte una voce della cassa è stata venduta in un giorno.
    Reimportare lo stesso giorno sostituisce, non somma."""
    __tablename__ = 'rete_vendite'
    __table_args__ = (db.UniqueConstraint('locale_id', 'giorno', 'voce', name='uq_vendita_giorno'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    giorno = db.Column(db.Date, nullable=False, index=True)
    voce = db.Column(db.String(200), nullable=False)          # normalizzata
    voce_originale = db.Column(db.String(200))
    quantita = db.Column(db.Float, nullable=False, default=0)
    incasso = db.Column(db.Float)                              # IVA compresa, come lo dà la cassa
    # quello che danno le casse più complete (il report prodotti di SumUp): vuoto se il report non ce l'ha
    netto = db.Column(db.Float)                                # incasso senza IVA
    iva = db.Column(db.Float)                                  # l'IVA in euro
    sconti = db.Column(db.Float)                               # sconti fatti, in euro
    costo = db.Column(db.Float)                                # prezzo d'acquisto scritto in cassa, senza IVA
    margine = db.Column(db.Float)                              # margine lordo secondo la cassa
    resi_quantita = db.Column(db.Float)                        # pezzi stornati o resi (righe negative)
    resi_incasso = db.Column(db.Float)                         # euro stornati o resi
    nomi = db.Column(db.String(400))                           # i modi in cui la cassa la scrive: «Caffe · Caffè»


class ReportCassa(db.Model):
    """Un report della cassa che copre più giorni senza dire il giorno di ogni vendita
    (il «product sales report» di SumUp dal… al…). Resta un blocco: non si divide sui giorni."""
    __tablename__ = 'rete_report_cassa'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    dal = db.Column(db.Date, nullable=False)
    al = db.Column(db.Date, nullable=False)
    nome_file = db.Column(db.String(200))
    creato = db.Column(db.DateTime, default=datetime.utcnow)
    righe = db.relationship('VenditaPeriodo', backref='report', cascade='all, delete-orphan', lazy=True)


class VenditaPeriodo(db.Model):
    """Una voce di un report di periodo: le stesse colonne di VenditaRete, sul blocco dal… al…"""
    __tablename__ = 'rete_vendite_periodo'
    __table_args__ = (db.UniqueConstraint('report_id', 'voce', name='uq_vendita_periodo'),)

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('rete_report_cassa.id', ondelete='CASCADE'), nullable=False, index=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    dal = db.Column(db.Date, nullable=False, index=True)
    al = db.Column(db.Date, nullable=False, index=True)
    voce = db.Column(db.String(200), nullable=False)
    voce_originale = db.Column(db.String(200))
    quantita = db.Column(db.Float, nullable=False, default=0)
    incasso = db.Column(db.Float)
    netto = db.Column(db.Float)
    iva = db.Column(db.Float)
    sconti = db.Column(db.Float)
    costo = db.Column(db.Float)
    margine = db.Column(db.Float)
    resi_quantita = db.Column(db.Float)
    resi_incasso = db.Column(db.Float)
    nomi = db.Column(db.String(400))


class MovimentoRete(db.Model):
    """Quello che non passa dalle fatture: scarti registrati e merce entrata senza fattura."""
    __tablename__ = 'rete_movimenti'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    giorno = db.Column(db.Date, nullable=False)
    articolo_id = db.Column(db.Integer, db.ForeignKey('rete_articoli.id', ondelete='CASCADE'), nullable=False)
    tipo = db.Column(db.String(10), nullable=False)            # scarto | carico
    quantita = db.Column(db.Float, nullable=False)
    nota = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class InventarioRete(db.Model):
    """Una conta della merce a fine giornata. Tra due inventari si calcola la diagnosi."""
    __tablename__ = 'rete_inventari'
    __table_args__ = (db.UniqueConstraint('locale_id', 'giorno', name='uq_inventario_giorno'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    giorno = db.Column(db.Date, nullable=False)
    chiuso = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    righe = db.relationship('RigaInventario', backref='inventario', cascade='all, delete-orphan', lazy='selectin')


class RigaInventario(db.Model):
    __tablename__ = 'rete_inventario_righe'
    __table_args__ = (db.UniqueConstraint('inventario_id', 'articolo_id', name='uq_riga_inventario'),)

    id = db.Column(db.Integer, primary_key=True)
    inventario_id = db.Column(db.Integer, db.ForeignKey('rete_inventari.id', ondelete='CASCADE'), nullable=False, index=True)
    articolo_id = db.Column(db.Integer, db.ForeignKey('rete_articoli.id', ondelete='CASCADE'), nullable=False)
    quantita = db.Column(db.Float, nullable=False)


# ═══════════════════════════════════════════════════════════════════
# Rete SB — fase 2, il locale: chi ci lavora, i turni, la chiusura.
# ═══════════════════════════════════════════════════════════════════

class PersonaLocale(db.Model):
    """Chi lavora nel locale. Lo staff timbra con un PIN dal tag all'ingresso;
    il titolare entra nell'app con email e password e legge «Il quadro»."""
    __tablename__ = 'rete_persone'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    nome = db.Column(db.String(80), nullable=False)
    ruolo = db.Column(db.String(20), nullable=False, default='staff')   # l'accesso: titolare | responsabile | staff
    # chi è nel locale (services/squadra.py): mansione e reparto, contratto e ore da contratto
    mansione = db.Column(db.String(40))
    reparto = db.Column(db.String(20))
    contratto = db.Column(db.String(30))
    ore_contratto = db.Column(db.Float)
    telefono = db.Column(db.String(30))
    assunto_il = db.Column(db.Date)
    note = db.Column(db.String(300))
    email = db.Column(db.String(200), index=True)
    password_hash = db.Column(db.String(255))
    pin_hash = db.Column(db.String(255))
    costo_orario = db.Column(db.Float)      # € lordi all'ora per l'azienda: serve al costo del personale
    # la settimana tipo scritta dal consulente: [{'g': 0-6, 'da': 'HH:MM', 'a': 'HH:MM'}] (services/previsto.py)
    orario = db.Column(db.JSON)
    attiva = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        from services.previsto import riepilogo
        from services.quadro import giorno_di_lavoro
        return {'id': self.id, 'nome': self.nome, 'ruolo': self.ruolo, 'email': self.email,
                'mansione': self.mansione, 'reparto': self.reparto, 'contratto': self.contratto,
                'ore_contratto': self.ore_contratto, 'telefono': self.telefono,
                'assunto_il': self.assunto_il.isoformat() if self.assunto_il else None, 'note': self.note,
                'costo_orario': self.costo_orario, 'attiva': self.attiva,
                'ha_pin': bool(self.pin_hash), 'ha_password': bool(self.password_hash),
                'orario': self.orario or [], 'previsto': riepilogo(self, giorno_di_lavoro())}


class TurnoRete(db.Model):
    """Un turno timbrato: inizio e fine (vuota finché la persona è in servizio)."""
    __tablename__ = 'rete_turni'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    persona_id = db.Column(db.Integer, db.ForeignKey('rete_persone.id', ondelete='CASCADE'), nullable=False, index=True)
    inizio = db.Column(db.DateTime, nullable=False)     # UTC
    fine = db.Column(db.DateTime)                       # UTC
    corretto = db.Column(db.Boolean, default=False)     # sistemato a mano dal consulente

    def ore(self, adesso=None):
        f = self.fine or adesso
        return max(0.0, (f - self.inizio).total_seconds() / 3600) if f else 0.0


class ChiusuraRete(db.Model):
    """La chiusura della giornata, segnata da chi chiude: poche spunte e una nota."""
    __tablename__ = 'rete_chiusure'
    __table_args__ = (db.UniqueConstraint('locale_id', 'giorno', name='uq_chiusura_giorno'),)

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    giorno = db.Column(db.Date, nullable=False)
    persona_id = db.Column(db.Integer, db.ForeignKey('rete_persone.id', ondelete='SET NULL'))
    ora = db.Column(db.DateTime, default=datetime.utcnow)
    voci = db.Column(db.JSON, default=dict)     # {'celle': true, 'gas': true, ..., 'nota': '...'}


class EventoRete(db.Model):
    """La storia del locale: visite, chiamate, decisioni, scritte dal consulente.
    `chiave` = una tappa che conta (l'ingresso, un cambio di fornitore): in Monitoring è in evidenza."""
    __tablename__ = 'rete_eventi'

    id = db.Column(db.Integer, primary_key=True)
    locale_id = db.Column(db.Integer, db.ForeignKey('rete_locali.id', ondelete='CASCADE'), nullable=False, index=True)
    giorno = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default='nota')   # visita | chiamata | decisione | nota
    testo = db.Column(db.Text, nullable=False)
    chiave = db.Column(db.Boolean, default=False)
    autore = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'giorno': self.giorno.isoformat(), 'tipo': self.tipo, 'testo': self.testo,
                'chiave': bool(self.chiave), 'autore': self.autore}


class ConsulenteRete(db.Model):
    """Un consulente SB con il suo accesso alla console della rete.
    La chiave admin (Simone, gestionale) resta: questi accessi servono a non
    dare a ogni consulente la stessa chiave, e a toglierne uno senza cambiare le altre."""
    __tablename__ = 'rete_consulenti'

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # consulente: lavora sui dati dei locali · direzione (Simone): guarda tutto, non modifica niente
    ruolo = db.Column(db.String(20), nullable=False, default='consulente')
    attivo = db.Column(db.Boolean, default=True)
    ultimo_accesso = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'nome': self.nome, 'email': self.email, 'attivo': self.attivo, 'ruolo': self.ruolo,
                'ultimo_accesso': self.ultimo_accesso.isoformat() if self.ultimo_accesso else None}
