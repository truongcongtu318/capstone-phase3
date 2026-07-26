"""
demo_chat.py — Real Shopping Copilot Chat UI

Dùng CopilotAgent thật (LLM Bedrock Nova + tools + guardrails + memory + cache).
Cần AWS credentials (AWS_PROFILE hoặc IAM Role) để LLM hoạt động.

Chạy:
    py demo_chat.py
Mở: http://localhost:9002
"""

import sys, os, uuid, logging
from dotenv import load_dotenv
load_dotenv(override=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

import argparse
parser = argparse.ArgumentParser(description="Run Shopping Copilot Chat UI")
parser.add_argument("--mock", action="store_true", help="Chạy với gRPC mock EKS")
args, _ = parser.parse_known_args()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(name)s | %(message)s")

app = FastAPI(title="Shopping Copilot — Chat")

_agent = None

class ChatReq(BaseModel):
    message: str
    session_id: str = ""
    user_id: str = "demo_user"

class ConfirmReq(BaseModel):
    session_id: str
    token: str

def _init_agent():
    """Khởi tạo CopilotAgent — hỗ trợ gọi EKS thật hoặc Mock."""
    global _agent
    if _agent:
        return
    
    if args.mock or os.getenv("MOCK_EKS") == "true":
        print("[MOCK MODE] Initializing with EKS Microservices Mocked!")
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_interactive import _setup_grpc_mocks
        _setup_grpc_mocks()
        
    from agent.copilot_agent import CopilotAgent
    _agent = CopilotAgent()

@app.post("/api/chat")
def api_chat(req: ChatReq):
    sid = req.session_id or str(uuid.uuid4())
    _init_agent()
    result = _agent.chat(
        session_id=sid,
        user_id=req.user_id,
        user_message=req.message,
    )
    status = result.get("status", "error")
    if status == "error" and "không được phép" in result.get("reply", ""):
        status = "blocked"
    return {
        "status": status,
        "reply": result.get("reply", ""),
        "token": result.get("token"),
        "session_id": sid,
    }

@app.post("/api/confirm")
def api_confirm(req: ConfirmReq):
    _init_agent()
    result = _agent.confirm(session_id=req.session_id, token=req.token)
    return {"status": result.get("status"), "reply": result.get("reply", "")}

@app.post("/api/session/new")
def api_session_new():
    return {"session_id": str(uuid.uuid4())}

@app.get("/api/health")
def api_health():
    return {"status": "ok"}

HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shopping Copilot — Chat</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e2e8f0; height: 100vh; display: flex; flex-direction: column; }
  .header { background: linear-gradient(135deg, #1a365d, #0d2137); padding: 12px 20px; border-bottom: 1px solid #2d3748; display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
  .header h1 { font-size: 1rem; font-weight: 700; color: #63b3ed; }
  .badge { font-size: 0.65rem; padding: 2px 8px; border-radius: 99px; font-weight: 600; background: #2d3748; color: #68d391; border: 1px solid #48bb78; }
  .header-right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  .btn { padding: 6px 14px; border: none; border-radius: 6px; font-size: 0.78rem; font-weight: 600; cursor: pointer; transition: all 0.15s; }
  .btn:hover { transform: translateY(-1px); }
  .btn-primary { background: #3182ce; color: white; }
  .btn-primary:hover { background: #2b6cb0; }
  .btn-success { background: #276749; color: #9ae6b4; }
  .btn-success:hover { background: #22543d; }
  .btn-danger { background: #742a2a; color: #fc8181; }
  .btn-danger:hover { background: #63171b; }
  .chat-area { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; scroll-behavior: smooth; }
  .message { max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 0.88rem; line-height: 1.5; animation: fadeIn 0.2s; }
  .message.user { align-self: flex-end; background: #2b6cb0; color: white; border-bottom-right-radius: 4px; }
  .message.bot { align-self: flex-start; background: #1a202c; border: 1px solid #2d3748; color: #e2e8f0; border-bottom-left-radius: 4px; }
  .message.bot.blocked { background: #3b1616; border-color: #9b2c2c; color: #fc8181; }
  .message.bot.pending { background: #1a365d; border-color: #2c5282; color: #90cdf4; }
  .message.bot.error { background: #3a2014; border-color: #c05621; color: #fbd38d; }
  .message.bot.success { background: #1c4532; border-color: #276749; color: #9ae6b4; }
  .message .sender { font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; opacity: 0.7; }
  .message .text { white-space: pre-wrap; word-break: break-word; }
  .message .text p { margin: 4px 0; }
  .input-area { padding: 12px 20px; border-top: 1px solid #2d3748; background: #1a202c; display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
  .input-area input { flex: 1; background: #2d3748; border: 1px solid #4a5568; border-radius: 8px; padding: 10px 14px; color: #e2e8f0; font-size: 0.88rem; outline: none; transition: border-color 0.2s; }
  .input-area input:focus { border-color: #63b3ed; }
  .input-area input::placeholder { color: #718096; }
  .input-area .btn { padding: 10px 20px; }
  .confirm-btn { display: inline-flex; gap: 6px; margin-top: 8px; }
  .confirm-btn .btn { font-size: 0.78rem; padding: 6px 16px; }
  .loader { display: inline-block; width: 16px; height: 16px; border: 2px solid #4a5568; border-top-color: #63b3ed; border-radius: 50%; animation: spin 0.6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #2d3748; border-radius: 3px; }
  @media (max-width: 600px) { .message { max-width: 95%; } }
</style>
</head>
<body>

<div class="header">
  <div>&#128722;</div>
  <h1>Shopping Copilot</h1>
  <span class="badge" id="status-badge">OK</span>
  <div class="header-right">
    <button class="btn btn-primary" onclick="newSession()">Moi</button>
  </div>
</div>

<div class="chat-area" id="chat"></div>

<div class="input-area">
  <input type="text" id="input" placeholder="Nhap cau hoi..." autofocus
    onkeydown="if(event.key==='Enter') send()">
  <button class="btn btn-primary" onclick="send()">Gui</button>
</div>

<script>
let sessionId = crypto.randomUUID();
let pendingToken = null;

async function api(path, body) {
  const res = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {}),
  });
  const data = await res.json();
  document.getElementById('status-badge').textContent = 'OK';
  return data;
}

function esc(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

function addMsg(role, html, cls = '') {
  const el = document.createElement('div');
  el.className = 'message ' + role + (cls ? ' ' + cls : '');
  el.innerHTML = '<div class="sender">' + (role === 'user' ? 'Ban' : 'Tro ly') + '</div><div class="text">' + html + '</div>';
  document.getElementById('chat').appendChild(el);
  el.scrollIntoView({ behavior: 'smooth' });
  return el;
}

function addPending(msg, token) {
  const el = addMsg('bot', msg, 'pending');
  const div = document.createElement('div');
  div.className = 'confirm-btn';
  div.innerHTML = '<button class="btn btn-success" onclick="confirmAction(\'' + token + '\')">Xac nhan</button>'
    + '<button class="btn btn-danger" onclick="cancelAction()">Huy</button>';
  el.appendChild(div);
  pendingToken = token;
}

function addLoader() {
  const el = document.createElement('div');
  el.className = 'message bot'; el.id = 'loader';
  el.innerHTML = '<div class="text" style="display:flex;align-items:center;gap:8px"><span class="loader"></span> Dang xu ly...</div>';
  document.getElementById('chat').appendChild(el);
  el.scrollIntoView({ behavior: 'smooth' });
}

function removeLoader() {
  const el = document.getElementById('loader');
  if (el) el.remove();
}

async function send() {
  const input = document.getElementById('input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  addMsg('user', esc(msg));
  addLoader();
  try {
    const data = await api('/api/chat', { message: msg, session_id: sessionId });
    removeLoader();
    if (data.status === 'pending') {
      addPending(data.reply, data.token);
    } else if (data.status === 'blocked' || data.status === 'error') {
      addMsg('bot', esc(data.reply), 'error');
    } else {
      addMsg('bot', esc(data.reply).replace(/\n/g, '<br>'), 'success');
    }
  } catch (e) {
    removeLoader();
    addMsg('bot', 'Loi ket noi: ' + esc(e.message), 'error');
  }
}

async function confirmAction(token) {
  const data = await api('/api/confirm', { session_id: sessionId, token: token });
  document.getElementById('status-badge').textContent = 'OK';
  if (data.status === 'ok') {
    addMsg('bot', data.reply, 'success');
  } else {
    addMsg('bot', data.reply, 'error');
  }
  pendingToken = null;
}

function cancelAction() {
  pendingToken = null;
  addMsg('bot', 'Da huy hanh dong.', 'blocked');
}

function newSession() {
  sessionId = crypto.randomUUID();
  document.getElementById('chat').innerHTML = '';
  pendingToken = null;
  document.getElementById('status-badge').textContent = 'OK';
  addMsg('bot', 'Xin chao! Toi la tro ly mua sam cua TechX Corp. To co the giup gi cho ban?', 'success');
}

newSession();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    html_content = HTML
    if args.mock or os.getenv("MOCK_EKS") == "true":
        mock_badge = '<span class="badge" style="background:#b7791f; border-color:#d69e2e; color:#fefcbf; margin-left: 5px;">MOCK EKS</span>'
        html_content = html_content.replace(
            '<h1>Shopping Copilot — Chat</h1>',
            f'<h1>Shopping Copilot — Chat</h1> {mock_badge}'
        )
    return html_content

if __name__ == "__main__":
    mode_str = "MOCK" if (args.mock or os.getenv("MOCK_EKS") == "true") else "LIVE"
    print(f"Shopping Copilot Chat [{mode_str}] — http://localhost:9002")
    uvicorn.run(app, host="0.0.0.0", port=9002, log_level="warning")