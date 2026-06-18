"""Inbox WhatsApp in-house: leggere le conversazioni e rispondere a mano
dalla dashboard, riusando i log di MessaggioWhatsapp. Le risposte manuali
partono via Cloud API ufficiale.

Pagina: GET /admin/whatsapp  (chiede il token admin, salvato nel browser)
API protette da X-Admin-Token.
"""
import os
from flask import Blueprint, request, jsonify, Response
from models import db, MessaggioWhatsapp
from services.whatsapp_cloud import invia_whatsapp_cloud, cloud_api_attiva

whatsapp_inbox_bp = Blueprint('whatsapp_inbox', __name__)


def _admin():
    return request.headers.get('X-Admin-Token') == os.environ.get('ADMIN_TOKEN')


@whatsapp_inbox_bp.route('/api/whatsapp/conversazioni', methods=['GET'])
def conversazioni():
    if not _admin():
        return jsonify({'error': 'Unauthorized'}), 401

    # Ultimi messaggi, raggruppati per numero (il più recente in alto)
    msgs = MessaggioWhatsapp.query.order_by(
        MessaggioWhatsapp.created_at.desc()).limit(5000).all()

    convo = {}
    for m in msgs:
        if not m.telefono:
            continue
        c = convo.get(m.telefono)
        if c is None:
            convo[m.telefono] = {
                'telefono': m.telefono,
                'nome': m.nome or '',
                'ultimo': (m.messaggio or '')[:120],
                'ultimo_at': m.created_at.isoformat(),
                'ultimo_dir': 'in' if m.tipo == 'inbound' else 'out',
                'totale': 1,
            }
        else:
            c['totale'] += 1
            if not c['nome'] and m.nome:
                c['nome'] = m.nome

    lista = sorted(convo.values(),
                   key=lambda x: x['ultimo_at'], reverse=True)
    return jsonify(lista)


@whatsapp_inbox_bp.route('/api/whatsapp/conversazioni/<numero>',
                         methods=['GET'])
def thread(numero):
    if not _admin():
        return jsonify({'error': 'Unauthorized'}), 401

    msgs = MessaggioWhatsapp.query.filter_by(
        telefono=numero).order_by(MessaggioWhatsapp.created_at.asc()).all()

    return jsonify([{
        'id': m.id,
        'dir': 'in' if m.tipo == 'inbound' else 'out',
        'testo': m.messaggio or '',
        'stato': m.stato,
        'tipo': m.tipo,
        'at': m.created_at.isoformat(),
    } for m in msgs])


@whatsapp_inbox_bp.route('/api/whatsapp/invia-manuale', methods=['POST'])
def invia_manuale():
    if not _admin():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    numero = (data.get('numero') or '').strip()
    testo = (data.get('messaggio') or '').strip()
    if not numero or not testo:
        return jsonify({'error': 'numero e messaggio obbligatori'}), 400

    if not cloud_api_attiva():
        return jsonify({
            'error': 'Cloud API non configurata. Imposta WHATSAPP_CLOUD_TOKEN '
                     'e WHATSAPP_PHONE_NUMBER_ID su Railway.'
        }), 400

    ok = invia_whatsapp_cloud(numero, testo, tipo='manuale')
    if not ok:
        return jsonify({
            'success': False,
            'error': "Invio fallito. Probabile causa: la finestra di 24h "
                     "dall'ultimo messaggio del cliente è scaduta (fuori "
                     "finestra serve un template approvato)."
        }), 200
    return jsonify({'success': True})


@whatsapp_inbox_bp.route('/admin/whatsapp', methods=['GET'])
def inbox_page():
    return Response(_INBOX_HTML, mimetype='text/html')


_INBOX_HTML = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inbox WhatsApp · SB Food</title>
<style>
  :root{ --orange:#c4622d; --dark:#37393f; --in:#fff; --out:#dcf0d6;
         --bg:#f3efea; --line:#e3ddd4; }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       color:var(--dark);background:var(--bg);height:100vh;overflow:hidden}
  .app{display:grid;grid-template-columns:340px 1fr;height:100vh}
  /* lista */
  .side{background:#fff;border-right:1px solid var(--line);display:flex;
        flex-direction:column;min-height:0}
  .side h1{font-size:16px;padding:18px 20px;border-bottom:1px solid var(--line);
           display:flex;align-items:center;gap:8px}
  .side h1 b{color:var(--orange)}
  .convs{overflow-y:auto;flex:1}
  .conv{padding:14px 20px;border-bottom:1px solid var(--line);cursor:pointer;
        display:flex;flex-direction:column;gap:3px}
  .conv:hover{background:#faf7f3}
  .conv.active{background:#f6ece4;border-left:3px solid var(--orange);
               padding-left:17px}
  .conv .top{display:flex;justify-content:space-between;align-items:baseline}
  .conv .nome{font-weight:600}
  .conv .time{font-size:11px;color:#9a948b;white-space:nowrap}
  .conv .prev{font-size:13px;color:#7a746b;overflow:hidden;text-overflow:ellipsis;
              white-space:nowrap}
  .conv .prev .dir{color:var(--orange);font-weight:600}
  /* thread */
  .main{display:flex;flex-direction:column;min-height:0;height:100vh}
  .head{background:#fff;border-bottom:1px solid var(--line);padding:16px 22px;
        font-weight:600;display:flex;align-items:center;gap:10px}
  .head .num{font-weight:400;color:#9a948b;font-size:13px}
  .thread{flex:1;overflow-y:auto;padding:22px;display:flex;flex-direction:column;
          gap:8px;
          background-image:radial-gradient(#e7e0d6 1px,transparent 0);
          background-size:22px 22px}
  .msg{max-width:62%;padding:9px 13px;border-radius:12px;box-shadow:0 1px 1px rgba(0,0,0,.06);
       white-space:pre-wrap;word-wrap:break-word}
  .msg.in{align-self:flex-start;background:var(--in);border-top-left-radius:3px}
  .msg.out{align-self:flex-end;background:var(--out);border-top-right-radius:3px}
  .msg .meta{display:block;font-size:10px;color:#9a948b;margin-top:4px;text-align:right}
  .empty{margin:auto;color:#9a948b;text-align:center;padding:40px}
  /* composer */
  .composer{background:#fff;border-top:1px solid var(--line);padding:14px 18px;
            display:flex;gap:10px;align-items:flex-end}
  .composer textarea{flex:1;resize:none;border:1px solid var(--line);border-radius:10px;
            padding:10px 12px;font:inherit;max-height:120px}
  .composer button{background:var(--orange);color:#fff;border:0;border-radius:10px;
            padding:11px 20px;font-weight:600;cursor:pointer}
  .composer button:disabled{opacity:.5;cursor:default}
  .note{font-size:11px;color:#9a948b;padding:0 18px 10px;background:#fff}
  .gate{position:fixed;inset:0;background:rgba(55,57,63,.6);display:flex;
        align-items:center;justify-content:center;z-index:10}
  .card{background:#fff;padding:28px;border-radius:14px;width:340px;text-align:center;
        box-shadow:0 10px 40px rgba(0,0,0,.2)}
  .card h2{margin-bottom:6px}.card p{color:#7a746b;font-size:13px;margin-bottom:16px}
  .card input{width:100%;padding:11px;border:1px solid var(--line);border-radius:9px;margin-bottom:12px}
  .card button{width:100%;background:var(--orange);color:#fff;border:0;border-radius:9px;padding:11px;font-weight:600;cursor:pointer}
  @media(max-width:760px){.app{grid-template-columns:1fr}.side{display:none}.side.show{display:flex}}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <h1>💬 Inbox <b>WhatsApp</b></h1>
    <div class="convs" id="convs"></div>
  </aside>
  <section class="main">
    <div class="head" id="head"><span>Seleziona una conversazione</span></div>
    <div class="thread" id="thread">
      <div class="empty">Scegli un contatto a sinistra per vedere la chat.</div>
    </div>
    <div class="note" id="note" style="display:none"></div>
    <div class="composer" id="composer" style="display:none">
      <textarea id="input" rows="1" placeholder="Scrivi una risposta…"></textarea>
      <button id="send">Invia</button>
    </div>
  </section>
</div>

<div class="gate" id="gate">
  <div class="card">
    <h2>🔒 Accesso</h2>
    <p>Inserisci il token admin per aprire l'inbox.</p>
    <input id="tok" type="password" placeholder="Admin token">
    <button onclick="saveTok()">Entra</button>
  </div>
</div>

<script>
let TOKEN = localStorage.getItem('wa_admin_token') || '';
let current = null, pollTimer = null;
const H = () => ({'X-Admin-Token': TOKEN, 'Content-Type':'application/json'});

function saveTok(){
  const v = document.getElementById('tok').value.trim();
  if(!v) return;
  TOKEN = v; localStorage.setItem('wa_admin_token', v);
  document.getElementById('gate').style.display='none';
  loadConvs();
}
function fmt(iso){
  const d = new Date(iso);
  const oggi = new Date();
  const sameDay = d.toDateString()===oggi.toDateString();
  return sameDay ? d.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})
                 : d.toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit'});
}
async function loadConvs(){
  try{
    const r = await fetch('/api/whatsapp/conversazioni',{headers:H()});
    if(r.status===401){ logout(); return; }
    const list = await r.json();
    const el = document.getElementById('convs');
    el.innerHTML = list.map(c=>`
      <div class="conv ${c.telefono===current?'active':''}" onclick="openThread('${c.telefono.replace(/'/g,"")}')">
        <div class="top"><span class="nome">${esc(c.nome)||c.telefono}</span>
          <span class="time">${fmt(c.ultimo_at)}</span></div>
        <div class="prev">${c.ultimo_dir==='out'?'<span class="dir">Tu: </span>':''}${esc(c.ultimo)}</div>
      </div>`).join('') || '<div class="empty">Nessuna conversazione.</div>';
  }catch(e){ console.error(e); }
}
async function openThread(numero){
  current = numero;
  loadConvs();
  document.getElementById('head').innerHTML =
    `<span>${esc(numero)}</span><span class="num">${esc(numero)}</span>`;
  document.getElementById('composer').style.display='flex';
  await refreshThread();
  clearInterval(pollTimer);
  pollTimer = setInterval(()=>{ refreshThread(); loadConvs(); }, 10000);
}
async function refreshThread(){
  if(!current) return;
  const r = await fetch('/api/whatsapp/conversazioni/'+encodeURIComponent(current),{headers:H()});
  if(r.status===401){ logout(); return; }
  const msgs = await r.json();
  const t = document.getElementById('thread');
  const atBottom = t.scrollHeight - t.scrollTop - t.clientHeight < 80;
  t.innerHTML = msgs.map(m=>`
    <div class="msg ${m.dir}">${esc(m.testo)}
      <span class="meta">${fmt(m.at)} ${m.dir==='out'?'· '+esc(m.stato):''}</span>
    </div>`).join('') || '<div class="empty">Nessun messaggio.</div>';
  if(atBottom) t.scrollTop = t.scrollHeight;
}
async function send(){
  const inp = document.getElementById('input');
  const testo = inp.value.trim();
  if(!testo || !current) return;
  const btn = document.getElementById('send');
  btn.disabled = true;
  try{
    const r = await fetch('/api/whatsapp/invia-manuale',{method:'POST',headers:H(),
      body: JSON.stringify({numero: current, messaggio: testo})});
    const d = await r.json();
    if(d.success){ inp.value=''; await refreshThread(); }
    else { showNote(d.error || 'Invio fallito'); await refreshThread(); }
  }catch(e){ showNote('Errore di rete'); }
  btn.disabled = false;
}
function showNote(msg){
  const n = document.getElementById('note');
  n.style.display='block'; n.textContent = '⚠️ '+msg;
  setTimeout(()=>{ n.style.display='none'; }, 6000);
}
function esc(s){ return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function logout(){ localStorage.removeItem('wa_admin_token'); location.reload(); }

document.getElementById('send').onclick = send;
document.getElementById('input').addEventListener('keydown', e=>{
  if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send(); }
});
document.getElementById('tok').addEventListener('keydown', e=>{ if(e.key==='Enter') saveTok(); });

if(TOKEN){ document.getElementById('gate').style.display='none'; loadConvs(); }
</script>
</body>
</html>"""
