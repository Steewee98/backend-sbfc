import os
import json
from functools import wraps
from flask import Blueprint, request, jsonify
import anthropic

ai_bp = Blueprint('ai', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Admin-Token')
        if token != os.environ.get('ADMIN_TOKEN'):
            return jsonify({'error': 'Non autorizzato'}), 401
        return f(*args, **kwargs)
    return decorated


@ai_bp.route('/api/ai/consigli', methods=['POST'])
@admin_required
def consigli_ai():
    data = request.get_json()
    prompt = data.get('prompt', '')
    if not prompt:
        return jsonify({'error': 'Prompt mancante'}), 400

    try:
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        message = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1000,
            messages=[{'role': 'user', 'content': prompt}]
        )
        text = message.content[0].text
        clean = text.replace('```json', '').replace('```', '').strip()
        parsed = json.loads(clean)
        return jsonify(parsed)
    except json.JSONDecodeError:
        return jsonify({'text': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
