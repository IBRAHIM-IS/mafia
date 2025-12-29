import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import random
import string
import math
import time
from collections import Counter

# -------------------------------------------------------
# 1. إعدادات السيرفر
# -------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'mafia_pro_secret_key_2025'

# إدارة الغرف
games = {}       
player_rooms = {} 

socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*", ping_timeout=10, ping_interval=5)

# -------------------------------------------------------
# 2. محرك اللعبة (Game Engine)
# -------------------------------------------------------
class GameEngine:
    def __init__(self):
        self.players = {}        
        self.phase = "LOBBY"    
        self.mafia_votes = {}          
        self.mafia_pre_votes = {}     
        self.doctor_target = None
        self.last_protected = None 
        self.day_votes = {}      
        self.timer = 0
        self.admin_id = None
        self.skip_timer_flag = False
        self.protected_target = None
        self.last_saved_from_kill = None 

    def reset_game(self):
        self.phase = "LOBBY"
        self.mafia_votes = {}
        self.mafia_pre_votes = {}     
        self.doctor_target = None
        self.last_protected = None
        self.day_votes = {}
        self.timer = 0
        self.skip_timer_flag = False
        self.protected_target = None
        self.last_saved_from_kill = None
        
        active_players = {k: v for k, v in self.players.items() if v.get('connected', True)}
        self.players = active_players

        for pid in list(self.players.keys()):
            p = self.players[pid]
            p['role'] = 'Lobby'
            p['alive'] = True
            p['shaib_used'] = False
            p['last_msg_time'] = 0
            p['has_acted'] = False 

# -------------------------------------------------------
# 3. الواجهة (HTML + JS + CSS)
# -------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>مافيا صمله Pro</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        :root { --bg: #121212; --card: #1e1e1e; --accent: #d32f2f; --text: #fff; --confirm: #2e7d32; --self: #1565c0; }
        * { box-sizing: border-box; touch-action: manipulation; }
        html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
        
        body { 
            background-color: var(--bg); 
            color: var(--text); 
            font-family: 'Segoe UI', Tahoma, sans-serif; 
            display: flex; 
            flex-direction: column; 
            height: 100dvh; 
            transition: background-color 1.5s ease-in-out; 
        }

        /* --- تنسيق نافذة الدور --- */
        #role-popup { 
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); 
            background: #ffffff; color: black; padding: 25px; border-radius: 20px; 
            text-align: center; font-weight: bold; display: none; z-index: 150; 
            box-shadow: 0 0 50px rgba(0,0,0,0.9); width: 85%; max-width: 350px; 
            animation: rolePop 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275); 
        }
        #role-image { 
            width: 140px; height: 140px; margin: 15px auto; 
            display: block; object-fit: contain; border-radius: 10px;
        }
        #role-text { font-size: 2rem; margin: 10px 0; color: #d32f2f; }

        /* --- تنسيق شاشة الدخول --- */
        #login-overlay { 
            position: absolute; top: 0; left: 0; width: 100%; height: 100%; 
            background: #000; z-index: 200; display: flex; flex-direction: column; 
            justify-content: center; align-items: center; 
            background-image: radial-gradient(circle, #2a2a2a 0%, #000000 100%); 
        }
        .login-card { 
            background: #1e1e1e; padding: 25px; border-radius: 20px; 
            width: 90%; max-width: 400px; text-align: center; 
            box-shadow: 0 10px 40px rgba(0,0,0,0.7); border: 1px solid #333; 
        }
        
        /* تنسيق صورة الصفحة الرئيسية */
        .home-img { 
            width: 120px; height: 120px; margin-bottom: 15px; 
            object-fit: cover; border-radius: 50%; border: 3px solid var(--accent); 
            box-shadow: 0 0 20px rgba(211, 47, 47, 0.3);
        }

        .login-title { color: var(--accent); font-size: 2.2rem; margin: 0 0 20px 0; font-weight: 900; }
        .main-input { 
            padding: 15px; border-radius: 12px; border: 2px solid #333; 
            background: #2b2b2b; color: white; text-align: center; 
            font-size: 1.1rem; width: 100%; margin-bottom: 15px; outline: none; 
        }
        .btn { border: none; padding: 15px; border-radius: 12px; font-size: 1rem; font-weight: bold; cursor: pointer; width: 100%; }
        .btn-create { background: linear-gradient(45deg, #d32f2f, #b71c1c); color: white; }
        .btn-join { background: #333; color: white; border: 1px solid #555; }

        /* --- اللعبة --- */
        #game-container { display: none; flex-direction: column; height: 100%; width: 100%; position: relative; }
        
        header { 
            background: var(--card); padding: 10px 15px; 
            display: flex; justify-content: space-between; align-items: center; 
            height: 60px; border-bottom: 1px solid #333; 
        }
        
        /* زر التحكم في الغرفة */
        #toggle-lobby-btn {
            width: auto; padding: 8px 15px; font-size: 0.85rem; 
            background: #444; color: #fff; margin-right: 10px;
            border-radius: 8px; cursor: pointer; border: 1px solid #555;
            transition: all 0.3s;
        }

        .badge { padding: 5px 12px; border-radius: 15px; font-size: 0.9rem; background: #333; color: white; }
        
        #chat-area { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 8px; background-color: rgba(0,0,0,0.5); border-radius: 10px; margin: 5px; }
        .msg { padding: 12px 16px; border-radius: 12px; max-width: 85%; font-size: 1rem; word-wrap: break-word; margin-bottom: 5px; }
        .sys { background: #263238; color: #cfd8dc; align-self: center; font-size: 0.9rem; text-align: center; width: 90%; }
        .global { background: #424242; align-self: flex-start; color: white; }
        .mafia { background: #3e0a0a; color: #ff8a80; border-right: 3px solid #d32f2f; align-self: flex-end; }

        #controls-area { background: var(--card); padding: 10px; border-top: 1px solid #333; padding-bottom: max(10px, env(safe-area-inset-bottom)); }
        
        /* الحاوية التي سنخفيها ونظهرها */
        #lobby-wrapper { display: block; transition: all 0.3s ease; }

        .grid { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-height: 25vh; overflow-y: auto; margin-bottom: 5px; }
        .p-card { background: #424242; padding: 10px 15px; border-radius: 20px; font-size: 0.95rem; cursor: pointer; border: 2px solid transparent; color: white; }
        .p-card.selected { background: var(--accent); border-color: #fff; transform: scale(1.05); }
        .p-card.partner-pick { border: 2px solid #ff9100; opacity: 0.8; }
        
        .input-group { display: flex; gap: 8px; height: 45px; margin-top: 5px; }
        .input-group input { margin: 0; flex: 1; padding: 0 15px; font-size: 1rem; }
        .input-group button { width: 50px; font-size: 1.2rem; margin: 0; }
        
        #mafia-toggle-btn { display: none; width: auto; padding: 0 15px; background: #424242; color: #ccc; }
        #mafia-toggle-btn.active-red { background: #b71c1c; color: white; }

        @keyframes rolePop { from { transform: translate(-50%, -50%) scale(0.5); opacity: 0; } to { transform: translate(-50%, -50%) scale(1); opacity: 1; } }
    </style>
</head>
<body>

    <div id="login-overlay">
        <div class="login-card">
            <img id="main-home-img" src="" alt="Mafia Game" class="home-img">
            
            <h1 class="login-title">مافيا صمله</h1>
            <div style="margin-bottom: 20px;">
                <input type="text" id="username" class="main-input" placeholder="اكتب اسمك هنا..." maxlength="12">
            </div>
            <button class="btn btn-create" onclick="createRoom()">🌟 إنشاء غرفة جديدة</button>
            
            <div style="display: flex; align-items: center; margin: 20px 0; color: #555;">
                <div style="flex:1; height:1px; background:#333;"></div>
                <span style="padding:0 10px;">أو</span>
                <div style="flex:1; height:1px; background:#333;"></div>
            </div>
            
            <div style="display: flex; gap: 10px;">
                <input type="text" id="room_code_input" class="main-input" placeholder="CODE" style="margin:0;">
                <button class="btn btn-join" onclick="joinRoom()" style="width: auto; padding: 0 25px;">دخول</button>
            </div>
        </div>
    </div>

    <div id="game-container">
        
        <div id="role-popup">
            <h2 style="margin:0; font-size: 1.2rem; color: #666;">🎭 دورك هو:</h2>
            <img id="role-image" src="" alt="Role Image">
            <div id="role-text"></div>
            <button class="btn" style="background:black; color:white; width: 100%;" onclick="document.getElementById('role-popup').style.display='none'">فهمت</button>
        </div>

        <header>
            <div style="display:flex; align-items:center;">
                <div class="badge" id="phase-badge">انتظار</div>
                <button id="toggle-lobby-btn" onclick="toggleLobby()">إغلاق</button>
            </div>
            
            <div style="text-align: left;">
                <div id="timer-box" style="color: #ff9100; font-weight: bold; font-size:1.1rem;"></div>
                <div id="room-code-display" style="color: #ffeb3b; font-size:0.8rem; border:1px dashed #555; padding:2px 5px; cursor:pointer;" onclick="copyRoomCode()">Code: ----</div>
            </div>
        </header>

        <div id="chat-area">
            <div class="msg sys">أهلاً بك! انتظر المشرف ليبدأ اللعبة.</div>
        </div>

        <div id="controls-area">
            
            <div id="lobby-wrapper">
                <div id="admin-panel" style="display:none; text-align:center; margin-bottom:10px;">
                    <div id="lobby-list" style="color:#888; margin-bottom:5px; font-size:0.9rem;"></div>
                    <button id="btn-start" class="btn" style="background:#2e7d32; width:100%; padding: 10px;" onclick="socket.emit('start_game')">🚀 ابدأ اللعبة</button>
                    <button id="btn-reset" class="btn" style="background:#ff6f00; width:100%; margin-top:5px; display:none; padding: 10px;" onclick="socket.emit('reset_game')">🔄 إعادة</button>
                </div>

                <div id="game-controls">
                    <div id="instruction" style="text-align:center; color:#ffeb3b; margin-bottom:8px; font-weight: bold;"></div>
                    <div class="grid" id="players-grid"></div>
                    <button id="confirm-btn" class="btn" style="background:var(--confirm); display:none; margin-bottom: 5px;" onclick="submitVote()">✅ تأكيد اختيارك</button>
                </div>
            </div>

            <div class="input-group">
                <button id="mafia-toggle-btn" class="btn" onclick="toggleMafiaChat()">📢</button>
                <input type="text" id="chat-input" placeholder="اكتب رسالة..." autocomplete="off">
                <button class="btn" onclick="sendMsg()">➤</button>
            </div>
        </div>
    </div>

    <script>
        // ============================================================
        // 🛑 منطقة تعديل الروابط (GITHUB IMAGES) 🛑
        // ============================================================
        // ضع رابط مجلد الصور "Raw" هنا. يجب أن ينتهي بـ slash (/)
        const GITHUB_BASE = "https://raw.githubusercontent.com/اسم_حسابك/اسم_المستودع/main/images/";
        // ============================================================

        // تحميل صورة الصفحة الرئيسية فوراً
        document.getElementById('main-home-img').src = GITHUB_BASE + "home.png";

        let socket;
        let myId;
        let currentPhase = 'LOBBY';
        let selectedTargetId = null; 
        let isMafia = false; 
        let mafiaChatMode = false;
        let myRoomCode = "";

        // دالة تبديل ظهور منطقة التحكم
        function toggleLobby() {
            const wrapper = document.getElementById('lobby-wrapper');
            const btn = document.getElementById('toggle-lobby-btn');
            
            if (wrapper.style.display === 'none') {
                wrapper.style.display = 'block';
                btn.innerText = 'إغلاق';
                btn.style.background = '#444'; 
                btn.style.color = '#fff';
            } else {
                wrapper.style.display = 'none';
                btn.innerText = 'إظهار';
                btn.style.background = '#2e7d32'; 
                btn.style.color = '#fff';
            }
        }

        function createRoom() {
            const name = document.getElementById('username').value.trim();
            if(!name) return alert("الاسم مطلوب!");
            initSocket('create', name, null);
        }

        function joinRoom() {
            const name = document.getElementById('username').value.trim();
            const code = document.getElementById('room_code_input').value.trim().toUpperCase();
            if(!name) return alert("الاسم مطلوب!");
            if(!code) return alert("كود الغرفة مطلوب!");
            initSocket('join', name, code);
        }

        function initSocket(action, name, code) {
            socket = io();
            const uuid = 'user_' + Math.random().toString(36).substr(2) + Date.now().toString(36);

            socket.on('connect', () => {
                myId = socket.id;
                socket.emit('join_request', {name: name, action: action, code: code, uuid: uuid});
            });
            
            socket.on('join_error', (data) => {
                alert(data.msg);
                location.reload();
            });

            socket.on('join_success', (data) => {
                myRoomCode = data.room_code;
                document.getElementById('room-code-display').innerText = "Code: " + myRoomCode;
                document.getElementById('login-overlay').style.display = 'none';
                document.getElementById('game-container').style.display = 'flex';
            });

            // إظهار الدور مع الصورة من GitHub
            socket.on('show_role', (r) => {
                isMafia = (r.indexOf('مافيا') !== -1);
                document.getElementById('role-text').innerText = r;
                
                const imgEl = document.getElementById('role-image');
                let imgName = "citizen.png"; // الافتراضي
                
                if (r.includes('مافيا')) imgName = "mafia.png";
                else if (r.includes('دكتور')) imgName = "doctor.png";
                else if (r.includes('شايب')) imgName = "shaib.png";
                
                imgEl.src = GITHUB_BASE + imgName;
                document.getElementById('role-popup').style.display = 'block';
            });

            socket.on('ui_update', (data) => {
                currentPhase = data.phase;
                document.getElementById('phase-badge').innerText = data.phase_ar;
                document.getElementById('timer-box').innerText = data.timer > 0 ? data.timer : "";
                
                // تحديث قائمة الانتظار للمشرف
                if(data.phase === 'LOBBY' || data.phase === 'ENDED') {
                   const listDiv = document.getElementById('lobby-list');
                   const names = data.players_list.map(p => p.name).join(', ');
                   listDiv.innerText = "المتواجدون: " + names;
                }

                if (isMafia && data.phase === 'DAY') {
                    document.getElementById('mafia-toggle-btn').style.display = 'block';
                } else {
                    document.getElementById('mafia-toggle-btn').style.display = 'none';
                }

                const adminPanel = document.getElementById('admin-panel');
                const gameControls = document.getElementById('game-controls');
                const btnStart = document.getElementById('btn-start');
                const btnReset = document.getElementById('btn-reset');
                
                if(data.phase === 'LOBBY' || data.phase === 'ENDED') {
                    adminPanel.style.display = 'block';
                    gameControls.style.display = 'none';
                    if(data.is_admin) {
                        if(data.phase === 'LOBBY') {
                            btnStart.style.display = 'block';
                            btnReset.style.display = 'none';
                        } else {
                            btnStart.style.display = 'none';
                            btnReset.style.display = 'block';
                        }
                    } else {
                        btnStart.style.display = 'none';
                        btnReset.style.display = 'none';
                    }
                } else {
                    adminPanel.style.display = 'none';
                    gameControls.style.display = 'block';
                }
            });

            socket.on('log', (data) => {
                const area = document.getElementById('chat-area');
                const div = document.createElement('div');
                div.className = `msg ${data.style}`;
                div.innerHTML = data.txt;
                area.appendChild(div);
                area.scrollTop = area.scrollHeight;
            });

            socket.on('mafia_sync', (data) => {
                if(!isMafia || currentPhase !== 'NIGHT') return;
                document.querySelectorAll('.p-card').forEach(el => {
                    const pid = el.getAttribute('data-id');
                    if(data.selections.includes(pid) && pid !== selectedTargetId) el.classList.add('partner-pick');
                    else el.classList.remove('partner-pick');
                });
                const btn = document.getElementById('confirm-btn');
                const instr = document.getElementById('instruction');
                if (data.consensus && selectedTargetId) {
                    btn.style.display = 'block';
                    btn.innerText = "☠️ تأكيد الاغتيال (اجماع)";
                    instr.innerText = "اتفق الجميع! اضغط للتنفيذ.";
                } else {
                    btn.style.display = 'none';
                    if(selectedTargetId) instr.innerText = "بانتظار اتفاق باقي المافيا...";
                }
            });

            socket.on('update_buttons', (data) => {
                const grid = document.getElementById('players-grid');
                const instr = document.getElementById('instruction');
                
                // إذا كان زر التأكيد ظاهراً للمافيا لا نمسح الجريد
                if (document.getElementById('confirm-btn').style.display === 'block' && isMafia && currentPhase === 'NIGHT') { } 
                else {
                    grid.innerHTML = "";
                    instr.innerText = data.msg || "";
                }
                
                if(!data.can_act) return;
                
                if(data.show_skip) {
                    const skipBtn = document.createElement('div');
                    skipBtn.className = 'p-card';
                    skipBtn.innerText = "⛔ امتناع";
                    skipBtn.style.border = "1px dashed #777";
                    skipBtn.onclick = () => { selectTarget('SKIP', skipBtn); };
                    grid.appendChild(skipBtn);
                }
                
                data.targets.forEach(p => {
                    const el = document.createElement('div');
                    el.className = 'p-card';
                    if(p.id === myId) { el.innerText = " (أنت) " + p.name; el.style.border = "1px solid #1565c0"; } 
                    else { el.innerText = p.name; }
                    el.setAttribute('data-id', p.id);
                    el.onclick = () => { selectTarget(p.id, el); };
                    grid.appendChild(el);
                });
            });
            
            socket.on('game_over', (data) => {
                alert("انتهت اللعبة! الفائز: " + data.winner);
            });
        }

        function selectTarget(tid, el) {
            selectedTargetId = tid;
            document.querySelectorAll('.p-card').forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            
            if(isMafia && currentPhase === 'NIGHT') {
                socket.emit('mafia_select', {target: tid});
                document.getElementById('confirm-btn').style.display = 'none';
            } else {
                const btn = document.getElementById('confirm-btn');
                btn.style.display = 'block';
                btn.innerText = "✅ تأكيد اختيارك";
            }
        }

        function submitVote() {
            if (selectedTargetId) {
                socket.emit('action', {target: selectedTargetId});
                document.getElementById('confirm-btn').style.display = 'none';
                if(!isMafia) {
                    document.getElementById('instruction').innerText = "✅ تم إرسال قرارك. بانتظار البقية...";
                    document.getElementById('players-grid').innerHTML = "";
                    selectedTargetId = null;
                }
            }
        }

        function toggleMafiaChat() {
            mafiaChatMode = !mafiaChatMode;
            const btn = document.getElementById('mafia-toggle-btn');
            if(mafiaChatMode) {
                btn.innerText = "😈";
                btn.classList.add('active-red');
                document.getElementById('chat-input').placeholder = "رسالة سرية للمافيا...";
            } else {
                btn.innerText = "📢";
                btn.classList.remove('active-red');
                document.getElementById('chat-input').placeholder = "رسالة عامة...";
            }
        }

        function sendMsg() {
            const inp = document.getElementById('chat-input');
            if(inp.value.trim()) {
                socket.emit('chat', {msg: inp.value.trim(), is_private: mafiaChatMode});
                inp.value = "";
                inp.focus();
            }
        }
        
        function copyRoomCode() {
            navigator.clipboard.writeText(myRoomCode);
            alert("تم نسخ الكود: " + myRoomCode);
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

def translate_role(r):
    return {
        'Mafia': 'مافيا 😈', 
        'Doctor': 'دكتور 🚑', 
        'Shaib': 'شايب 🕵️‍♂️', 
        'Citizen': 'مواطن 🧔',
        'Spectator': 'مشاهد 👀',
        'Lobby': 'في الانتظار ⏳'
    }.get(r, r)

# --- Helper Functions ---
def generate_room_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        if code not in games:
            return code

def get_game(sid):
    room = player_rooms.get(sid)
    if room and room in games:
        return games[room], room
    return None, None

def broadcast_ui(game, room):
    alive_count = sum(1 for p in game.players.values() if p.get('alive', False))
    # إرسال قائمة مختصرة فقط لتحديث واجهة الانتظار
    players_list = [{'id': k, 'name': v['name']} for k,v in game.players.items()]
    
    phase_ar = {'LOBBY': 'الانتظار', 'NIGHT': 'ليل 🌑', 'DAY': 'نهار ☀️', 'ENDED': 'النهاية'}.get(game.phase, '')
    
    socketio.emit('ui_update', {
        'phase': game.phase,
        'phase_ar': phase_ar,
        'timer': game.timer,
        'alive_count': alive_count,
        'is_admin': False, 
        'players_list': players_list
    }, room=room)

    for pid in game.players:
        socketio.emit('ui_update', {
            'phase': game.phase,
            'phase_ar': phase_ar,
            'timer': game.timer,
            'alive_count': alive_count,
            'is_admin': (pid == game.admin_id),
            'players_list': players_list
        }, room=pid)

def system_log(txt, room, style='sys'):
    socketio.emit('log', {'txt': txt, 'style': style}, room=room)

# --- أحداث SocketIO ---

@socketio.on('join_request')
def on_join_request(data):
    sid = request.sid
    name = data.get('name', 'Unknown')[:12]
    action = data.get('action')
    raw_code = data.get('code')
    code = raw_code.upper() if raw_code else ''

    room_code = None
    
    if action == 'create':
        room_code = generate_room_code()
        games[room_code] = GameEngine()
        games[room_code].admin_id = sid
    elif action == 'join':
        if code in games:
            room_code = code
        else:
            emit('join_error', {'msg': 'كود الغرفة غير صحيح!'})
            return

    if room_code:
        game = games[room_code]
        role = 'Lobby' if game.phase == "LOBBY" else 'Spectator'
        
        join_room(room_code)
        player_rooms[sid] = room_code
        
        alive = True if game.phase == "LOBBY" else False
        game.players[sid] = {
            'name': name, 'role': role, 'alive': alive, 
            'shaib_used': False, 'last_msg_time':0, 'has_acted': False, 'connected': True
        }
        
        emit('join_success', {'room_code': room_code})
        system_log(f"دخل <b>{name}</b>.", room_code)
        broadcast_ui(game, room_code)
        
        if role == 'Spectator':
             emit('show_role', 'مشاهد 👀', room=sid)

@socketio.on('start_game')
def on_start():
    game, room = get_game(request.sid)
    if not game: return
    if request.sid != game.admin_id: return
    
    if len(game.players) < 2: # للتجربة جعلتها 2
        system_log("❌ العدد قليل!", room)
        return
    
    p_ids = list(game.players.keys())
    count = len(p_ids)
    num_mafia = max(1, math.floor(count / 4))
    
    roles = ['Mafia'] * num_mafia
    if count - num_mafia >= 2: roles.extend(['Doctor', 'Shaib'])
    elif count - num_mafia == 1: roles.append('Doctor')
    while len(roles) < count: roles.append('Citizen')
    
    random.shuffle(roles)
    mafia_names = []
    
    for i, pid in enumerate(p_ids):
        r = roles[i]
        game.players[pid]['role'] = r
        game.players[pid]['alive'] = True
        game.players[pid]['has_acted'] = False
        
        socketio.emit('show_role', translate_role(r), room=pid)
        if r == 'Mafia':
            join_room(f"mafia_{room}", pid)
            mafia_names.append(game.players[pid]['name'])
            
    if mafia_names:
        socketio.emit('log', {'txt': f"شركاؤك: {', '.join(mafia_names)}", 'style': 'mafia'}, room=f"mafia_{room}")

    game.phase = "NIGHT"
    game.timer = 60
    system_log("🌃 خيم الليل... المافيا، الطبيب، والشايب، استيقظوا!", room)
    broadcast_ui(game, room)
    send_action_buttons(game, room)
    socketio.start_background_task(game_loop, room)

@socketio.on('reset_game')
def on_reset():
    game, room = get_game(request.sid)
    if not game: return
    if request.sid != game.admin_id: return
    game.reset_game()
    system_log("🔄 تم إعادة اللعبة.", room)
    broadcast_ui(game, room)

@socketio.on('mafia_select')
def on_mafia_select(data):
    game, room = get_game(request.sid)
    if not game: return
    sid = request.sid
    target = data.get('target')
    
    if game.phase != "NIGHT" or game.players[sid]['role'] != 'Mafia': return
    game.mafia_pre_votes[sid] = target
    
    mafia_ids = [pid for pid, p in game.players.items() if p['role'] == 'Mafia' and p['alive']]
    votes = [game.mafia_pre_votes.get(pid) for pid in mafia_ids]
    
    consensus = (len(votes) == len(mafia_ids) and all(v == votes[0] for v in votes) and None not in votes)
        
    socketio.emit('mafia_sync', {'selections': list(game.mafia_pre_votes.values()), 'consensus': consensus}, room=f"mafia_{room}")

@socketio.on('action')
def on_action(data):
    game, room = get_game(request.sid)
    if not game: return
    sid = request.sid
    target_id = data.get('target')
    player = game.players[sid]
    role = player['role']

    if player.get('has_acted', False): return

    if game.phase == "NIGHT":
        if role == 'Mafia':
            mafia_ids = [pid for pid, p in game.players.items() if p['role'] == 'Mafia' and p['alive']]
            votes = [game.mafia_pre_votes.get(pid) for pid in mafia_ids]
            if not (len(votes) == len(mafia_ids) and all(v == target_id for v in votes)): return

            for m_id in mafia_ids:
                game.mafia_votes[m_id] = target_id
                game.players[m_id]['has_acted'] = True
                socketio.emit('update_buttons', {'can_act': False, 'msg': 'تم التنفيذ'}, room=m_id)
            check_night_finished(game)
        
        elif role == 'Doctor':
            game.doctor_target = target_id
            player['has_acted'] = True
            socketio.emit('update_buttons', {'can_act': False, 'msg': 'تمت الحماية'}, room=sid)
            check_night_finished(game)

        elif role == 'Shaib':
            target_role = game.players[target_id]['role']
            result = "مافيا 😈" if target_role == 'Mafia' else "بريئ 😇"
            socketio.emit('log', {'txt': f"كشف الهوية: {game.players[target_id]['name']} هو {result}", 'style': 'sys'}, room=sid)
            player['shaib_used'] = True
            player['has_acted'] = True
            socketio.emit('update_buttons', {'can_act': False, 'msg': 'تم الكشف'}, room=sid)
            check_night_finished(game)
            
    elif game.phase == "DAY":
        game.day_votes[sid] = target_id
        player['has_acted'] = True
        socketio.emit('update_buttons', {'can_act': False, 'msg': 'تم التصويت'}, room=sid)
        
        alive_count = sum(1 for p in game.players.values() if p.get('alive', False))
        if len([v for k,v in game.day_votes.items() if game.players[k]['alive']]) >= alive_count:
            game.skip_timer_flag = True

def check_night_finished(game):
    needed = 0
    completed = 0
    for r in ['Mafia', 'Doctor', 'Shaib']:
        alive = [p for p in game.players.values() if p['role'] == r and p['alive']]
        if alive:
            needed += 1
            if r == 'Mafia':
                if game.mafia_votes: completed += 1
            else:
                if alive[0]['has_acted']: completed += 1
    
    if needed > 0 and completed == needed:
        game.skip_timer_flag = True

@socketio.on('chat')
def on_chat(data):
    game, room = get_game(request.sid)
    if not game: return
    sid = request.sid
    msg = data.get('msg', '')[:200]
    is_private = data.get('is_private', False)
    p = game.players[sid]
    
    if not p.get('alive', False): return

    if game.phase == "NIGHT":
        if p['role'] == 'Mafia':
            socketio.emit('log', {'txt': f"😈 {p['name']}: {msg}", 'style': 'mafia'}, room=f"mafia_{room}")
    elif game.phase == "DAY":
        if p['role'] == 'Mafia' and is_private:
             socketio.emit('log', {'txt': f"😈 [همس] {p['name']}: {msg}", 'style': 'mafia'}, room=f"mafia_{room}")
        else:
            socketio.emit('log', {'txt': f"<b>{p['name']}</b>: {msg}", 'style': 'global'}, room=room)

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    game, room = get_game(sid)
    if game and sid in game.players:
        game.players[sid]['connected'] = False
        broadcast_ui(game, room)

# --- Game Loop & Logic ---
def game_loop(room):
    while room in games and games[room].phase not in ["LOBBY", "ENDED"]:
        game = games[room]
        socketio.sleep(1)
        game.timer -= 1
        broadcast_ui(game, room)

        if game.timer <= 0 or game.skip_timer_flag:
            game.skip_timer_flag = False
            if game.phase == "NIGHT": process_night(game, room)
            elif game.phase == "DAY": process_day(game, room)

def process_night(game, room):
    victim_id = list(game.mafia_votes.values())[0] if game.mafia_votes else None
    
    actual_victim = None
    if victim_id and victim_id != game.doctor_target:
        actual_victim = victim_id
        game.players[actual_victim]['alive'] = False
        try: leave_room(f"mafia_{room}", actual_victim)
        except: pass

    if check_win_condition(game, room): return

    game.phase = "DAY"
    game.timer = 120
    
    msg = "☀️ أشرقت الشمس..."
    if actual_victim:
        msg += f" وقُتل {game.players[actual_victim]['name']}!"
    else:
        msg += " ولم يُقتل أحد!"
    system_log(msg, room)

    game.day_votes = {}
    game.mafia_votes = {}
    game.mafia_pre_votes = {}
    game.doctor_target = None
    for p in game.players.values(): p['has_acted'] = False
    
    broadcast_ui(game, room)
    send_action_buttons(game, room)

def process_day(game, room):
    alive_ids = [pid for pid,p in game.players.items() if p['alive']]
    votes = [t for pid, t in game.day_votes.items() if pid in alive_ids]
    
    victim_id = None
    if votes:
        most = Counter(votes).most_common()
        if most[0][0] != 'SKIP' and (len(most) == 1 or most[0][1] > most[1][1]):
            victim_id = most[0][0]

    if victim_id:
        game.players[victim_id]['alive'] = False
        system_log(f"⚖️ تم إعدام {game.players[victim_id]['name']}", room)
    else:
        system_log("⚖️ لم يتم إعدام أحد.", room)

    if check_win_condition(game, room): return

    game.phase = "NIGHT"
    game.timer = 60
    
    game.day_votes = {}
    for p in game.players.values(): p['has_acted'] = False
    
    broadcast_ui(game, room)
    send_action_buttons(game, room)

def check_win_condition(game, room):
    mafia = sum(1 for p in game.players.values() if p['alive'] and p['role'] == 'Mafia')
    innocent = sum(1 for p in game.players.values() if p['alive'] and p['role'] != 'Mafia')
    
    winner = None
    if mafia == 0 and innocent > 0: winner = "القرية 🧔"
    elif mafia >= innocent and mafia > 0: winner = "المافيا 😈"

    if winner:
        game.phase = "ENDED"
        socketio.emit('game_over', {'winner': winner}, room=room)
        broadcast_ui(game, room)
        return True
    return False

def send_action_buttons(game, room):
    alive_players = [{'id': k, 'name': v['name']} for k,v in game.players.items() if v.get('alive')]
    
    for sid, p in game.players.items():
        if not p.get('alive') or game.phase == "ENDED":
            socketio.emit('update_buttons', {'can_act': False, 'msg': 'أنت متفرج', 'targets': []}, room=sid)
            continue
            
        data = {'can_act': False, 'msg': '', 'targets': [], 'show_skip': False}
        others = [tp for tp in alive_players if tp['id'] != sid]

        if game.phase == "NIGHT":
            if p['role'] == 'Mafia':
                data = {'can_act': True, 'msg': 'اختر ضحية:', 'targets': others}
            elif p['role'] == 'Doctor':
                data = {'can_act': True, 'msg': 'اختر شخصاً لحمايته:', 'targets': alive_players}
            elif p['role'] == 'Shaib' and not p['shaib_used']:
                data = {'can_act': True, 'msg': 'اكشف هوية:', 'targets': others}
        elif game.phase == "DAY":
            data = {'can_act': True, 'msg': 'صوت للإعدام:', 'targets': others, 'show_skip': True}

        if p.get('has_acted'): data = {'can_act': False, 'msg': 'تم استلام قرارك', 'targets': []}
        socketio.emit('update_buttons', data, room=sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
