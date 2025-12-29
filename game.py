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

games = {}       
player_rooms = {} 

socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*", ping_timeout=10, ping_interval=5)

# -------------------------------------------------------
# 2. محرك اللعبة (Game Engine) - لم يتغير المنطق
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
# 3. الواجهة (HTML + JS + CSS) - التعديلات هنا
# -------------------------------------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>مافيا صمله - المتقدمة</title>
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
        }

        /* تنسيق نافذة الدور */
        #role-popup { 
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); 
            background: #ffffff; color: black; padding: 25px; border-radius: 20px; 
            text-align: center; font-weight: bold; display: none; z-index: 150; 
            box-shadow: 0 0 50px rgba(0,0,0,0.9); width: 85%; max-width: 350px; 
            animation: rolePop 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275); 
        }
        #role-image { width: 150px; height: 150px; margin: 15px auto; display: block; object-fit: contain; border-radius: 15px; }
        #role-text { font-size: 2.2rem; margin: 10px 0; color: #d32f2f; }

        /* تنسيق صفحة الدخول والصورة الرئيسية */
        #login-overlay { 
            position: absolute; top: 0; left: 0; width: 100%; height: 100%; 
            background: #000; z-index: 200; display: flex; flex-direction: column; 
            justify-content: center; align-items: center; 
            background-image: radial-gradient(circle, #2a2a2a 0%, #000000 100%); 
        }
        .login-card { background: #1e1e1e; padding: 25px; border-radius: 20px; width: 90%; max-width: 400px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,0.7); border: 1px solid #333; }
        
        /* تنسيق صورة الصفحة الرئيسية */
        .home-img { width: 120px; height: 120px; margin-bottom: 15px; object-fit: cover; border-radius: 50%; border: 3px solid var(--accent); }
        
        .login-title { color: var(--accent); font-size: 2.2rem; margin: 0 0 20px 0; font-weight: 900; letter-spacing: -1px; }
        .main-input { padding: 15px; border-radius: 12px; border: 2px solid #333; background: #2b2b2b; color: white; text-align: center; font-size: 1.1rem; width: 100%; margin-bottom: 15px; outline: none; }
        .btn { border: none; padding: 15px; border-radius: 12px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: 0.2s; width: 100%; }
        .btn-create { background: linear-gradient(45deg, #d32f2f, #b71c1c); color: white; }
        .btn-join { background: #333; color: white; border: 1px solid #555; }
        
        /* تنسيق الحاوية الرئيسية */
        #game-container { display: none; flex-direction: column; height: 100%; width: 100%; position: relative; }
        
        /* الهيدر وزر الإخفاء */
        header { background: var(--card); padding: 10px 15px; display: flex; justify-content: space-between; align-items: center; height: 60px; border-bottom: 1px solid #333; }
        .badge { padding: 5px 12px; border-radius: 15px; background: #333; font-size: 0.9rem;}
        
        #toggle-lobby-btn {
            width: auto; padding: 8px 15px; font-size: 0.85rem; 
            background: #444; color: #fff; margin-right: 10px;
        }

        #chat-area { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 8px; }
        .msg { padding: 12px 16px; border-radius: 12px; max-width: 85%; }
        
        #controls-area { background: var(--card); padding: 10px; border-top: 1px solid #333; }
        
        /* الحاوية التي سنخفيها ونظهرها */
        #lobby-wrapper { display: block; transition: all 0.3s ease; }

        .grid { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 10px; }
        .p-card { background: #424242; padding: 10px 15px; border-radius: 20px; color: white; cursor: pointer; }
        
        @keyframes rolePop { from { transform: translate(-50%, -50%) scale(0.5); opacity: 0; } to { transform: translate(-50%, -50%) scale(1); opacity: 1; } }
    </style>
</head>
<body>
    <div id="login-overlay">
        <div class="login-card">
            <img src="/static/images/home.png" alt="Main Logo" class="home-img">
            
            <h1 class="login-title">مافيا صمله</h1>
            <input type="text" id="username" class="main-input" placeholder="اسمك المستعار" maxlength="12">
            <button class="btn btn-create" onclick="createRoom()">🌟 إنشاء غرفة</button>
            <div style="margin: 15px 0; color: #555;">أو</div>
            <input type="text" id="room_code_input" class="main-input" placeholder="كود الغرفة">
            <button class="btn btn-join" onclick="joinRoom()">دخول ➡️</button>
        </div>
    </div>

    <div id="game-container">
        <div id="role-popup">
            <h2 style="margin:0; font-size: 1.2rem; color: #666;">🎭 دورك:</h2>
            <img id="role-image" src="" alt="Role">
            <div id="role-text"></div>
            <button class="btn" style="background:black; color:white; width: 100%;" onclick="document.getElementById('role-popup').style.display='none'">فهمت!</button>
        </div>

        <header>
            <div style="display:flex; align-items:center;">
                <div class="badge" id="phase-badge">انتظار</div>
                <button id="toggle-lobby-btn" onclick="toggleLobby()">إغلاق</button>
            </div>
            
            <div style="text-align: left;">
                <div id="timer-box" style="color: #ff9100; font-weight: bold; font-size:0.9rem;"></div>
                <div id="room-code-display" style="color: #ffeb3b; font-size:0.8rem;">Code: ----</div>
            </div>
        </header>

        <div id="chat-area"></div>

        <div id="controls-area">
            
            <div id="lobby-wrapper">
                <div id="admin-panel" style="display:none; text-align:center; margin-bottom: 10px;">
                    <button id="btn-start" class="btn btn-create" onclick="socket.emit('start_game')">🚀 ابدأ اللعبة</button>
                </div>
                
                <div id="game-controls">
                    <div id="instruction" style="text-align:center; color:#ffeb3b; margin-bottom:8px;"></div>
                    <div class="grid" id="players-grid"></div>
                    <button id="confirm-btn" class="btn" style="background:var(--confirm); display:none; margin-bottom: 5px;" onclick="submitVote()">✅ تأكيد</button>
                </div>
            </div>

            <div style="display:flex; gap:5px; margin-top:5px;">
                <input type="text" id="chat-input" style="flex:1; padding:10px; border-radius:8px;" placeholder="اكتب هنا...">
                <button class="btn" style="width:60px;" onclick="sendMsg()">➤</button>
            </div>
        </div>
    </div>

    <script>
        let socket;
        let isMafia = false;

        // دالة تبديل ظهور غرفة الانتظار
        function toggleLobby() {
            const wrapper = document.getElementById('lobby-wrapper');
            const btn = document.getElementById('toggle-lobby-btn');
            
            if (wrapper.style.display === 'none') {
                wrapper.style.display = 'block';
                btn.innerText = 'إغلاق';
                btn.style.background = '#444'; // لون عادي
            } else {
                wrapper.style.display = 'none';
                btn.innerText = 'إظهار';
                btn.style.background = '#2e7d32'; // لون أخضر للتنبيه أنه يمكن الإظهار
            }
        }

        function initSocket(action, name, code) {
            socket = io();
            socket.on('connect', () => {
                socket.emit('join_request', {name: name, action: action, code: code, uuid: 'user_'+Math.random()});
            });

            socket.on('join_success', (data) => {
                document.getElementById('room-code-display').innerText = "Code: " + data.room_code;
                document.getElementById('login-overlay').style.display = 'none';
                document.getElementById('game-container').style.display = 'flex';
            });

            socket.on('show_role', (roleName) => {
                const textEl = document.getElementById('role-text');
                const imgEl = document.getElementById('role-image');
                
                textEl.innerText = roleName;
                isMafia = roleName.includes('مافيا');

                let imgName = "citizen.png"; 
                if (roleName.includes('مافيا')) imgName = "mafia.png";
                else if (roleName.includes('دكتور')) imgName = "doctor.png";
                else if (roleName.includes('شايب')) imgName = "shaib.png";
                
                imgEl.src = "/static/images/" + imgName;
                document.getElementById('role-popup').style.display = 'block';
            });

            socket.on('ui_update', (data) => {
                document.getElementById('phase-badge').innerText = data.phase_ar;
                if(data.is_admin && data.phase === 'LOBBY') document.getElementById('admin-panel').style.display = 'block';
                else document.getElementById('admin-panel').style.display = 'none';
            });
            
            socket.on('chat_update', (data) => {
                const chat = document.getElementById('chat-area');
                const div = document.createElement('div');
                div.className = 'msg';
                div.style.background = data.style ? data.style : '#333';
                div.innerHTML = `<strong>${data.sender}:</strong> ${data.msg}`;
                chat.appendChild(div);
                chat.scrollTop = chat.scrollHeight;
            });

            socket.on('game_action', (data) => {
                const grid = document.getElementById('players-grid');
                const instr = document.getElementById('instruction');
                const confirmBtn = document.getElementById('confirm-btn');
                
                grid.innerHTML = '';
                instr.innerText = data.msg;
                confirmBtn.style.display = 'none';

                if (data.can_act) {
                    data.targets.forEach(p => {
                        const el = document.createElement('div');
                        el.className = 'p-card';
                        el.innerText = p.name;
                        el.onclick = () => {
                            document.querySelectorAll('.p-card').forEach(c => c.style.border = 'none');
                            el.style.border = '2px solid #d32f2f';
                            selectedTarget = p.id;
                            confirmBtn.style.display = 'block';
                        };
                        grid.appendChild(el);
                    });
                }
            });
        }

        let selectedTarget = null;
        function submitVote() {
            if(selectedTarget) {
                socket.emit('player_action', {target_id: selectedTarget});
                document.getElementById('players-grid').innerHTML = '<div style="color:#888;">تم إرسال قرارك...</div>';
                document.getElementById('confirm-btn').style.display = 'none';
                selectedTarget = null;
            }
        }

        function createRoom() { initSocket('create', document.getElementById('username').value, null); }
        function joinRoom() { initSocket('join', document.getElementById('username').value, document.getElementById('room_code_input').value); }
        function sendMsg() { 
            const inp = document.getElementById('chat-input');
            if(inp.value) { socket.emit('chat_msg', {msg: inp.value, mode: 'global'}); inp.value = ''; }
        }
    </script>
</body>
</html>
"""

# بقية الكود للـ Routes و SocketIO...
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('join_request')
def handle_join(data):
    # (نفس كود الانضمام السابق)
    # ...
    pass 

# ... (تأكد من نسخ بقية دوال الـ SocketIO من الملف الأصلي أو تركه كما هو إذا كنت تعدل الملف مباشرة)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
