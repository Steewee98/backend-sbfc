import os
import traceback
import threading
import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from models import db

load_dotenv()

try:
    from weasyprint import HTML as WeasyHTML
    print("WeasyPrint OK")
except Exception as e:
    print(f"WeasyPrint non disponibile: {e}")

app = Flask(__name__)

# Database
database_url = os.environ.get('DATABASE_URL', 'sqlite:///sbfc.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-fallback-key')

# CORS
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://www.sbfoodconsulting.com",
            "https://sbfoodconsulting.com",
            "https://sito-sbfc-production.up.railway.app",
            "http://localhost:8080",
            "http://localhost:3000"
        ],
        "methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Content-Type",
            "X-Admin-Token",
            "Accept",
            "Authorization"
        ],
        "expose_headers": [
            "Content-Disposition",
            "Content-Type"
        ],
        "supports_credentials": False
    }
})

# Init DB
db.init_app(app)

# Register blueprints
from routes.contatti import contatti_bp
from routes.studenti import studenti_bp
from routes.pagamenti import pagamenti_bp
from routes.stats import stats_bp
from routes.tracking import tracking_bp
from routes.ai import ai_bp
from routes.brandizzatore import brandizzatore_bp
from routes.checklist import checklist_bp
from routes.whatsapp_logs import whatsapp_logs_bp
from routes.google_leads import google_leads_bp
from routes.prenotazioni import prenotazioni_bp

app.register_blueprint(contatti_bp)
app.register_blueprint(studenti_bp)
app.register_blueprint(pagamenti_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(tracking_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(brandizzatore_bp)
app.register_blueprint(checklist_bp)
app.register_blueprint(whatsapp_logs_bp)
app.register_blueprint(google_leads_bp)
app.register_blueprint(prenotazioni_bp)


# Ensure tables exist
_db_initialized = False
_db_error = None

@app.before_request
def ensure_db():
    global _db_initialized, _db_error
    if not _db_initialized:
        try:
            db.create_all()
            # Aggiungi colonne mancanti a tabelle esistenti
            with db.engine.connect() as conn:
                for table, col, ddl in [
                    ('risultati_checklist', 'email_inviata', 'BOOLEAN DEFAULT FALSE'),
                    ('risultati_checklist', 'tipo_email', 'VARCHAR(20)'),
                    ('prenotazioni', 'link_chiamata', 'VARCHAR(500)'),
                ]:
                    try:
                        conn.execute(db.text(
                            f'ALTER TABLE {table} ADD COLUMN {col} {ddl}'
                        ))
                        conn.commit()
                    except Exception:
                        conn.rollback()  # reset transazione per PostgreSQL
            _db_initialized = True
            _db_error = None
            print("Database tables created successfully")
        except Exception as e:
            _db_error = str(e)
            print(f"DB init error: {e}")
            traceback.print_exc()
            if request.path != '/':
                return jsonify({'error': 'Database non disponibile', 'detail': _db_error}), 503


@app.route('/')
def health():
    db_type = 'postgresql' if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI'] else 'sqlite'
    return {
        'status': 'ok',
        'service': 'SB Food Consulting API',
        'db': db_type,
        'db_ready': _db_initialized,
    }, 200


@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return jsonify({'error': 'Internal server error', 'detail': str(e), 'type': type(e).__name__}), 500


# --- Background sync Google Sheets ogni 2 minuti ---
SYNC_INTERVAL = int(os.environ.get('SYNC_INTERVAL', 120))  # secondi

def _background_sync():
    """Controlla il foglio Google ogni 2 min e importa nuovi lead."""
    time.sleep(30)  # attendi avvio app
    while True:
        try:
            with app.app_context():
                from routes.google_leads import _do_sync
                nuovi, già = _do_sync()
                if nuovi > 0:
                    print(f"[AUTO-SYNC] {nuovi} nuovi lead importati")
        except Exception as e:
            print(f"[AUTO-SYNC] Errore: {e}")
        time.sleep(SYNC_INTERVAL)

# --- Background check reminder prenotazioni ogni 5 min ---
REMINDER_INTERVAL = int(os.environ.get('REMINDER_INTERVAL', 300))

def _background_reminders():
    """Controlla prenotazioni e invia reminder WA."""
    time.sleep(45)
    while True:
        try:
            with app.app_context():
                from routes.prenotazioni import _check_reminders
                _check_reminders()
        except Exception as e:
            print(f"[REMINDER] Errore: {e}")
        time.sleep(REMINDER_INTERVAL)


# Avvia solo in produzione (gunicorn) e solo una volta per processo
# Usa un file lock per evitare che più worker avviino thread duplicati
_bg_started = False
if not app.debug or os.environ.get('FORCE_SYNC'):
    if not _bg_started:
        _bg_started = True
        _sync_thread = threading.Thread(target=_background_sync, daemon=True)
        _sync_thread.start()
        print(f"[AUTO-SYNC] Avviato — controlla ogni {SYNC_INTERVAL}s")

        _reminder_thread = threading.Thread(target=_background_reminders, daemon=True)
        _reminder_thread.start()
        print(f"[REMINDER] Avviato — controlla ogni {REMINDER_INTERVAL}s")


if __name__ == '__main__':
    app.run(debug=True, port=5001)
