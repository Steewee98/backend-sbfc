import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from models import db

load_dotenv()

app = Flask(__name__)

# Database
database_url = os.environ.get('DATABASE_URL', 'sqlite:///sbfc.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-fallback-key')

# CORS
frontend_url = os.environ.get('FRONTEND_URL', 'http://localhost:8891')
CORS(app, origins=[frontend_url, 'http://localhost:*', 'http://127.0.0.1:*'])

# Init DB
db.init_app(app)

# Register blueprints
from routes.contatti import contatti_bp
from routes.studenti import studenti_bp
from routes.pagamenti import pagamenti_bp
from routes.stats import stats_bp

app.register_blueprint(contatti_bp)
app.register_blueprint(studenti_bp)
app.register_blueprint(pagamenti_bp)
app.register_blueprint(stats_bp)


# Ensure tables exist on first request
_db_initialized = False

@app.before_request
def ensure_db():
    global _db_initialized
    if not _db_initialized:
        try:
            db.create_all()
            _db_initialized = True
            print("Database tables created successfully")
        except Exception as e:
            print(f"DB init error: {e}")


@app.route('/')
def health():
    db_type = 'postgresql' if 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI'] else 'sqlite'
    return {'status': 'ok', 'service': 'SB Food Consulting API', 'db': db_type, 'db_ready': _db_initialized}, 200


if __name__ == '__main__':
    app.run(debug=True, port=5001)
