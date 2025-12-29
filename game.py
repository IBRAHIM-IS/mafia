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
games = {}       # { 'ROOM_CODE': GameEngineInstance }
player_rooms = {} # { 'socket_id': 'ROOM_CODE' }

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
        # متغير جديد لحفظ الشخص الذي نجا من الاغتيال لمنع استهدافه الليلة التالية
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
    <title>مافيا صمله</title>
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
        
        /* --- تصميم شاشة الدخول --- */
        #login-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: #000; z-index: 200; display: flex; flex-direction: column; justify-content: center; align-items: center; background-image: radial-gradient(circle, #2a2a2a 0%, #000000 100%); }
        
        .login-card {
            background: #1e1e1e;
            padding: 25px;
            border-radius: 20px;
            width: 90%;
            max-width: 400px;
            text-align: center;
            box-shadow: 0 10px 40px rgba(0,0,0,0.7);
            border: 1px solid #333;
        }

        .login-title { color: var(--accent); font-size: 2.2rem; margin: 0 0 20px 0; font-weight: 900; letter-spacing: -1px; }
        
        .input-label { display: block; text-align: right; color: #888; font-size: 0.9rem; margin-bottom: 5px; margin-right: 5px; }
        
        .main-input { 
            padding: 15px; border-radius: 12px; border: 2px solid #333; 
            background: #2b2b2b; color: white; text-align: center; 
            font-size: 1.1rem; width: 100%; margin-bottom: 15px; 
            outline: none; transition: 0.3s; 
        }
        .main-input:focus { border-color: var(--accent); background: #333; }

        .btn { border: none; padding: 15px; border-radius: 12px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: 0.2s; width: 100%; }
        .btn:active { transform: scale(0.97); }
        
        .btn-create { background: linear-gradient(45deg, #d32f2f, #b71c1c); color: white; box-shadow: 0 4px 15px rgba(211, 47, 47, 0.4); }
        .btn-join { background: #333; color: white; border: 1px solid #555; }
        
        .divider { display: flex; align-items: center; color: #555; margin: 20px 0; font-size: 0.9rem; }
        .divider::before, .divider::after { content: ""; flex: 1; height: 1px; background: #333; }
        .divider span { padding: 0 10px; }

        .join-section { display: flex; gap: 10px; }
        .join-section input { margin: 0; flex: 1; text-transform: uppercase; letter-spacing: 2px; font-weight: bold; }
        .join-section button { width: auto; padding: 0 20px; background: var(--confirm); color: white; }

        /* --- اللعبة --- */
        #game-container { display: none; flex-direction: column; height: 100%; width: 100%; position: relative; }
        
        header { background: var(--card); padding: 10px 15px; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #333; height: 50px; flex-shrink: 0; transition: 0.5s; }
        .badge { padding: 5px 12px; border-radius: 15px; font-size: 0.9rem; background: #333; font-weight: bold; color: white; }
        #room-code-display { color: #ffeb3b; font-family: monospace; font-size: 1.1rem; border: 1px dashed #555; padding: 5px 10px; border-radius: 5px; cursor: pointer; background: rgba(255, 235, 59, 0.1); }
        #count-badge { cursor: pointer; border: 1px solid #555; transition: 0.2s; }
        #count-badge:active { transform: scale(0.95); background: #444; }

        #timer-box { font-family: monospace; font-size: 1.5rem; font-weight: bold; color: #ff9100; min-width: 40px; text-align: center; text-shadow: 2px 2px 4px #000; }
        
        #chat-area { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; gap: 8px; background-color: rgba(0, 0, 0, 0.5); backdrop-filter: blur(2px); border-radius: 10px; margin: 5px; -webkit-overflow-scrolling: touch; }
        .msg { padding: 12px 16px; border-radius: 12px; max-width: 85%; font-size: 1rem; line-height: 1.4; word-wrap: break-word; position: relative; margin-bottom: 5px; text-shadow: none; }
        
        .sys { background: #263238; color: #cfd8dc; align-self: center; font-size: 0.9rem; text-align: center; width: 90%; border: 1px solid #37474f; }
        .global { background: #424242; align-self: flex-start; border-bottom-right-radius: 2px; color: white; }
        .mafia { background: #3e0a0a; color: #ff8a80; border-right: 3px solid #d32f2f; align-self: flex-end; border-bottom-left-radius: 2px; }
        
        .chat-kill { background: #2a0000; color: #ff5252; border: 1px solid #d32f2f; align-self: center; width: 95%; text-align: center; font-weight: bold; }
        .chat-save { background: #001a2c; color: #40c4ff; border: 1px solid #00b0ff; align-self: center; width: 95%; text-align: center; font-weight: bold; }
        .chat-exec { background: #37474f; color: #eceff1; border: 1px solid #b0bec5; align-self: center; width: 95%; text-align: center; font-weight: bold; }
        .chat-win { background: #332a00; color: #ffd700; border: 1px solid #ffc400; align-self: center; width: 95%; text-align: center; font-weight: bold; font-size: 1.2rem; }

        #controls-area { background: var(--card); padding: 10px; border-top: 1px solid #333; flex-shrink: 0; padding-bottom: max(10px, env(safe-area-inset-bottom)); position: relative; }
        .grid { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-height: 25vh; overflow-y: auto; margin-bottom: 5px; }
        .p-card { background: #424242; padding: 10px 15px; border-radius: 20px; font-size: 0.95rem; cursor: pointer; border: 2px solid transparent; user-select: none; transition: 0.2s; position: relative; color: white; }
        .p-card.partner-pick { border: 2px solid #ff9100; opacity: 0.8; }
        .p-card.selected { background: var(--accent); border-color: #fff; transform: scale(1.05); box-shadow: 0 4px 10px rgba(0,0,0,0.5); opacity: 1; }
        .p-card.self-card { background: var(--self); border: 2px solid #42a5f5; font-weight: bold; }
        
        .lobby-card { display: flex; justify-content: space-between; align-items: center; background: #333; padding: 10px; margin-bottom: 5px; border-radius: 8px; }
        .lobby-actions { display: flex; gap: 5px; }
        .kick-btn { background: #b71c1c; color: white; border: none; padding: 5px 10px; border-radius: 5px; cursor: pointer; font-size: 0.8rem; }
        .promote-btn { background: #ffca28; color: black; border: none; padding: 5px 10px; border-radius: 5px; cursor: pointer; font-size: 0.8rem; }
        
        .skip-btn { background: #333; border: 1px dashed #777; color: #bbb; }
        #confirm-btn { width: 100%; background: var(--confirm); padding: 12px; margin-bottom: 10px; font-size: 1.1rem; display: none; animation: zoomInCenter 0.3s; }
        
        .input-group { display: flex; gap: 8px; height: 45px; }
        .input-group input { margin: 0; flex: 1; padding: 0 15px; font-size: 1rem; width: auto; height: 100%; box-sizing: border-box; }
        .input-group button { height: 100%; border-radius: 8px; width: 50px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; margin: 0; }
        
        #mafia-toggle-btn { display: none; width: auto; padding: 0 15px; background: #424242; color: #ccc; font-size: 0.9rem; transition: 0.3s; border: 1px solid #555; }
        #mafia-toggle-btn.active-red { background: #b71c1c; color: white; border-color: #ff5252; box-shadow: 0 0 10px rgba(183, 28, 28, 0.5); animation: pulseBtn 1s infinite alternate; }
        @keyframes pulseBtn { from { transform: scale(1); } to { transform: scale(1.05); } }

        #role-popup { 
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); 
            background: #ffd600; color: black; padding: 30px; border-radius: 15px; 
            text-align: center; font-weight: bold; display: none; z-index: 150; 
            box-shadow: 0 0 50px rgba(0,0,0,0.9); width: 85%; max-width: 400px; 
            animation: rolePop 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275); 
        }
        
        #players-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.8); z-index: 300; display: none; justify-content: center; align-items: center; backdrop-filter: blur(5px); }
        .modal-content { background: #212121; padding: 20px; border-radius: 15px; width: 90%; max-width: 400px; text-align: center; border: 1px solid #444; max-height: 70vh; display: flex; flex-direction: column; }
        .modal-header { font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 1px solid #333; padding-bottom: 10px; }
        #modal-list-container { overflow-y: auto; flex: 1; text-align: right; }
        .modal-player-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 5px; border-bottom: 1px solid #333; }
        .modal-player-row:last-child { border-bottom: none; }

        #news-overlay { position: fixed; inset: 0; width: 100%; height: 100dvh; display: none; justify-content: center; align-items: center; z-index: 9999; padding: 15px; backdrop-filter: blur(8px); background-color: rgba(0,0,0,0.7); }
        .news-content { position: relative; padding: 40px 20px; border-radius: 20px; box-shadow: 0 20px 50px rgba(0,0,0,0.9); width: 100%; max-width: 600px; text-align: center; font-weight: 900; line-height: 1.6; margin: 0 auto; font-size: clamp(1.8rem, 5vw, 3rem); animation: zoomInCenter 0.5s forwards; }
        
        .theme-kill .news-content { 
            background: #1a0505; 
            border: 4px solid #b71c1c; 
            color: #ff1744; 
            text-shadow: 0 0 20px rgba(255, 23, 68, 0.6); 
            animation: zoomInCenter 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards; 
        }

        .theme-save .news-content { background: #001020; border: 4px solid #00b0ff; color: #80d8ff; text-shadow: 0 0 20px rgba(0, 176, 255, 0.6); animation: glow 1.5s infinite alternate; }
        .theme-exec .news-content { background: linear-gradient(145deg, #455a64, #37474f); border: 4px solid #cfd8dc; color: #ffffff; text-shadow: 0 0 15px rgba(255, 255, 255, 0.6); box-shadow: 0 0 40px rgba(255, 255, 255, 0.15); animation: stamp 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55) forwards; }
        
        #win-overlay { position: fixed; inset: 0; width: 100%; height: 100%; display: none; flex-direction: column; justify-content: center; align-items: center; z-index: 10000; background: rgba(0,0,0,0.9); backdrop-filter: blur(10px); }
        .win-card { background: #212121; padding: 40px; border-radius: 20px; border: 5px solid #ffd700; text-align: center; box-shadow: 0 0 50px #ffd700; max-width: 90%; animation: zoomInCenter 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275); }
        .win-emoji { font-size: 5rem; margin-bottom: 20px; animation: bounce 2s infinite; }
        .win-title { font-size: 2.5rem; color: #ffd700; font-weight: bold; margin-bottom: 20px; text-shadow: 0 0 20px #ff6f00; }
        .win-text { font-size: 1.5rem; color: white; }

        #anim-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; display: flex; justify-content: center; align-items: center; z-index: 100; opacity: 0; transition: opacity 0.5s; overflow: hidden; }
        #anim-emoji { font-size: 15rem; filter: drop-shadow(0 0 20px rgba(0,0,0,0.5)); }
        
        @keyframes bounce { 0%, 20%, 50%, 80%, 100% {transform: translateY(0);} 40% {transform: translateY(-30px);} 60% {transform: translateY(-15px);} }
        @keyframes zoomInCenter { from { transform: scale(0); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        @keyframes rolePop { from { transform: translate(-50%, -50%) scale(0.5); opacity: 0; } to { transform: translate(-50%, -50%) scale(1); opacity: 1; } }
        @keyframes riseUp { 0% { transform: translateY(100vh) scale(0.5); opacity: 0; } 50% { transform: translateY(0) scale(1.2); opacity: 1; } 100% { transform: translateY(-10vh) scale(1); opacity: 0; } }
        @keyframes fadeInOut { 0% { opacity: 0; background: rgba(0,0,0,0); } 20% { opacity: 1; background: rgba(0,0,0,0.8); } 80% { opacity: 1; background: rgba(0,0,0,0.8); } 100% { opacity: 0; background: rgba(0,0,0,0); } }
        @keyframes shake { 0% { transform: translate(1px, 1px) rotate(0deg); } 10% { transform: translate(-1px, -2px) rotate(-1deg); } 20% { transform: translate(-3px, 0px) rotate(1deg); } 30% { transform: translate(3px, 2px) rotate(0deg); } 40% { transform: translate(1px, -1px) rotate(1deg); } 50% { transform: translate(-1px, 2px) rotate(-1deg); } 60% { transform: translate(-3px, 1px) rotate(0deg); } 70% { transform: translate(3px, 1px) rotate(-1deg); } 80% { transform: translate(-1px, -1px) rotate(1deg); } 90% { transform: translate(1px, 2px) rotate(0deg); } 100% { transform: translate(1px, -2px) rotate(-1deg); } }
        @keyframes glow { from { box-shadow: 0 0 20px #00b0ff; transform: scale(1); } to { box-shadow: 0 0 50px #00b0ff, 0 0 20px white; transform: scale(1.05); } }
        @keyframes stamp { 0% { opacity: 0; transform: scale(3); } 100% { opacity: 1; transform: scale(1); } }

        .anim-active { animation: fadeInOut 3s forwards; }
        .emoji-animate { animation: riseUp 3s cubic-bezier(0.25, 1, 0.5, 1) forwards; }

        /* ========================================= */
        /* 🔥 كود الفقاعة والنبض البرتقالي الجديد 🔥  */
        /* ========================================= */
        @keyframes pulse-orange {
            0% { color: white; text-shadow: 0 0 0px #ff8c00; transform: scale(1); border-color: transparent; }
            50% { color: #ff8c00; text-shadow: 0 0 10px #ff8c00; transform: scale(1.05); border-color: #ff8c00; }
            100% { color: white; text-shadow: 0 0 0px #ff8c00; transform: scale(1); border-color: transparent; }
        }

        .disconnecting-player {
            animation: pulse-orange 1s infinite ease-in-out !important;
            border: 2px solid #ff8c00 !important;
        }

        .connection-warning-bubble {
            position: fixed; 
            bottom: 80px; 
            left: 50%;
            transform: translateX(-50%);
            background-color: rgba(255, 69, 0, 0.95); 
            color: white;
            padding: 10px 20px;
            border-radius: 50px;
            box-shadow: 0 0 20px rgba(255, 69, 0, 0.6);
            font-weight: bold;
            z-index: 2000;
            display: none; 
            animation: slideUp 0.3s ease-out;
            text-align: center;
            font-size: 0.9rem;
            white-space: nowrap;
        }

        @keyframes slideUp {
            from { opacity: 0; bottom: 60px; }
            to { opacity: 1; bottom: 80px; }
        }
    </style>
</head>
<body>
    <div id="anim-overlay"><div id="anim-emoji"></div></div>

    <div id="news-overlay">
        <div id="news-text" class="news-content"></div>
    </div>
    
    <div id="win-overlay">
        <div class="win-card">
            <div id="win-emoji" class="win-emoji">🏆</div>
            <div id="win-title" class="win-title"></div>
            <div id="win-text" class="win-text"></div>
            <button class="btn" style="margin-top:20px; background:#444;" onclick="document.getElementById('win-overlay').style.display='none'">إغلاق</button>
        </div>
    </div>
    
    <div id="players-modal-overlay">
        <div class="modal-content">
            <div class="modal-header">قائمة اللاعبين</div>
            <div id="modal-list-container"></div>
            <button class="btn" style="margin-top: 15px; width: 100%; background: #444;" onclick="togglePlayerModal()">إغلاق</button>
        </div>
    </div>

    <div id="login-overlay">
        <div class="login-card">
            <h1 class="login-title">مافيا صمله</h1>
            
            <div style="margin-bottom: 20px;">
                <label class="input-label">الاسم المستعار:</label>
                <input type="text" id="username" class="main-input" placeholder="اكتب اسمك هنا..." maxlength="12">
            </div>
            
            <button class="btn btn-create" onclick="createRoom()">🌟 إنشاء غرفة جديدة</button>
            
            <div class="divider"><span>أو الانضمام لغرفة</span></div>
            
            <div class="join-section">
                <input type="text" id="room_code_input" class="main-input" placeholder="CODE">
                <button class="btn btn-join" onclick="joinRoom()">دخول ➡️</button>
            </div>
        </div>
    </div>

    <div id="game-container">
        
        <div id="disconnect-bubble" class="connection-warning-bubble">
            ⚠️ اللاعب <span id="target-player-name" style="text-decoration: underline;"></span> سينقطع اتصاله خلال 20 ثانية
        </div>

        <div id="role-popup">
            <h2 style="margin:0; font-size: 1.5rem;">🎭 دورك هو:</h2>
            <div id="role-text" style="font-size: 2.5rem; margin: 20px 0; color: #d32f2f;"></div>
            <button class="btn" style="background:black; color:white; width: 100%;" onclick="document.getElementById('role-popup').style.display='none'">فهمت</button>
        </div>

        <header>
            <div class="badge" id="phase-badge">انتظار</div>
            <div id="timer-box"></div>
            <div style="display:flex; gap:10px; align-items:center;">
                <div id="room-code-display" title="اضغط للنسخ" onclick="copyRoomCode()">Code: ----</div>
                <div class="badge" id="count-badge" onclick="togglePlayerModal()">👥 0</div>
            </div>
        </header>

        <div id="chat-area">
            <div class="msg sys">أهلاً بك! انتظر المشرف ليبدأ اللعبة.</div>
        </div>

        <div id="controls-area">
           <div id="admin-panel" style="display:none; text-align:center; margin-bottom:10px;">
                <h3 style="margin: 5px 0; color: #888; font-size: 0.9rem;">غرفة الانتظار</h3>
                <div id="lobby-list"></div>
                
                <button id="btn-start" class="btn" style="background:#2e7d32; width:100%; margin-top:10px; display:none; padding: 15px;" onclick="socket.emit('start_game')">🚀 <span style="color: black; font-weight: bold;">ابدأ اللعبة الآن</span></button>
                
                <button id="btn-reset" class="btn" style="background:#ff6f00; width:100%; margin-top:10px; display:none; padding: 15px;" onclick="socket.emit('reset_game')">🔄 إعادة اللعبة</button>
            </div>

            <div id="game-controls">
                <div id="instruction" style="text-align:center; color:#ffeb3b; margin-bottom:8px; font-weight: bold;"></div>
                <div class="grid" id="players-grid"></div>
                <button id="confirm-btn" class="btn" onclick="submitVote()">✅ تأكيد اختيارك</button>
            </div>

            <div class="input-group">
                <button id="mafia-toggle-btn" class="btn" onclick="toggleMafiaChat()">📢 عام</button>
                <input type="text" id="chat-input" placeholder="اكتب رسالة..." autocomplete="off">
                <button class="btn" onclick="sendMsg()">➤</button>
            </div>
        </div>
    </div>

    <script>
        let socket;
        let myId;
        let currentPhase = 'LOBBY';
        let selectedTargetId = null; 
        let isMafia = false; 
        let currentPlayersData = []; 
        let isAdminClient = false;
        let mafiaChatMode = false;
        let myRoomCode = "";

        // توليد معرف فريد للجهاز لحل مشكلة اعادة الاتصال
        function getMyUUID() {
            let u = localStorage.getItem('mafia_uuid_v2');
            if(!u) {
                u = 'user_' + Math.random().toString(36).substr(2) + Date.now().toString(36);
                localStorage.setItem('mafia_uuid_v2', u);
            }
            return u;
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
            const uuid = getMyUUID(); // الحصول على بصمة الجهاز

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
            
            setupListeners();
        }
        
        // --- دوال التحذير من الانقطاع ---
        function triggerDisconnectWarning(pid, name) {
            // إظهار الفقاعة
            const bubble = document.getElementById('disconnect-bubble');
            const nameSpan = document.getElementById('target-player-name');
            nameSpan.textContent = name;
            bubble.style.display = 'block';
            
            // إضافة نبض برتقالي للاعب في الجريد
            const card = document.querySelector(`.p-card[data-id="${pid}"]`);
            if(card) {
                card.classList.add('disconnecting-player');
            }
        }
        
        function clearDisconnectWarning(pid) {
            // إخفاء الفقاعة
            document.getElementById('disconnect-bubble').style.display = 'none';
            
            // إزالة النبض
            const card = document.querySelector(`.p-card[data-id="${pid}"]`);
            if(card) {
                card.classList.remove('disconnecting-player');
            }
            // محاولة إزالة الكلاس من كل البطاقات احتياطاً
            document.querySelectorAll('.disconnecting-player').forEach(el => el.classList.remove('disconnecting-player'));
        }
        // -------------------------------

        function copyRoomCode() {
            navigator.clipboard.writeText(myRoomCode);
            alert("تم نسخ كود الغرفة: " + myRoomCode);
        }
        
        function togglePlayerModal() {
            const modal = document.getElementById('players-modal-overlay');
            if (modal.style.display === 'flex') {
                modal.style.display = 'none';
            } else {
                modal.style.display = 'flex';
                renderPlayerModal();
            }
        }
        
        function renderPlayerModal() {
            const container = document.getElementById('modal-list-container');
            container.innerHTML = "";
            currentPlayersData.forEach(p => {
                const row = document.createElement('div');
                row.className = 'modal-player-row';
                let nameHtml = `<span>${p.name}</span>`;
                if(p.is_admin_flag) nameHtml = `<span>${p.name} <span title="مشرف">👑</span></span>`;
                
                // إضافة علامة الشبكة إذا كان غير متصل
                if(!p.connected) {
                    nameHtml += ' <span title="منقطع عن الاتصال" style="color: #ff9100; margin-right:5px;">📡</span>';
                }

                const infoDiv = document.createElement('div');
                infoDiv.innerHTML = nameHtml;
                row.appendChild(infoDiv);
                
                if(isAdminClient && p.id !== myId) {
                    const actionsDiv = document.createElement('div');
                    actionsDiv.className = 'lobby-actions';
                    const promoteBtn = document.createElement('button');
                    promoteBtn.className = 'promote-btn';
                    promoteBtn.innerHTML = '👑';
                    promoteBtn.onclick = () => { if(confirm(`تسليم الإدارة لـ ${p.name}؟`)) { socket.emit('promote_player', {id: p.id}); togglePlayerModal(); } };
                    const kickBtn = document.createElement('button');
                    kickBtn.className = 'kick-btn';
                    kickBtn.innerText = 'X';
                    kickBtn.onclick = () => { if(confirm(`طرد ${p.name}؟`)) { socket.emit('kick_player', {id: p.id}); } };
                    actionsDiv.appendChild(promoteBtn);
                    actionsDiv.appendChild(kickBtn);
                    row.appendChild(actionsDiv);
                }
                container.appendChild(row);
            });
        }

        function toggleMafiaChat() {
            mafiaChatMode = !mafiaChatMode;
            const btn = document.getElementById('mafia-toggle-btn');
            if(mafiaChatMode) {
                btn.innerText = "😈 خاص";
                btn.classList.add('active-red');
                document.getElementById('chat-input').placeholder = "رسالة سرية للمافيا...";
            } else {
                btn.innerText = "📢 عام";
                btn.classList.remove('active-red');
                document.getElementById('chat-input').placeholder = "رسالة عامة...";
            }
        }

        function triggerAnimation(phase) {
            const overlay = document.getElementById('anim-overlay');
            const emojiDiv = document.getElementById('anim-emoji');
            
            if(currentPhase === 'ENDED') return;

            overlay.classList.remove('anim-active');
            emojiDiv.classList.remove('emoji-animate');
            void overlay.offsetWidth; 
            
            if (phase === 'DAY') {
                emojiDiv.innerText = '☀️';
                overlay.classList.add('anim-active');
                emojiDiv.classList.add('emoji-animate');
            } else if (phase === 'NIGHT') {
                emojiDiv.innerText = '🌑';
                overlay.classList.add('anim-active');
                emojiDiv.classList.add('emoji-animate');
            }
        }

        function showNewsAnimation(text, type) {
            const overlay = document.getElementById('news-overlay');
            const content = document.getElementById('news-text');
            overlay.className = ''; 
            overlay.style.display = 'flex';
            if (type === 'kill') overlay.classList.add('theme-kill');
            else if (type === 'save') overlay.classList.add('theme-save');
            else if (type === 'exec') overlay.classList.add('theme-exec');
            
            content.innerHTML = text;
            setTimeout(() => { overlay.style.display = 'none'; }, 4000);
        }

        function showWinScreen(winner, emoji) {
            const overlay = document.getElementById('win-overlay');
            document.getElementById('win-title').innerText = "🏆 انتهت اللعبة!";
            document.getElementById('win-emoji').innerText = emoji;
            document.getElementById('win-text').innerText = "الفائزون: " + winner;
            overlay.style.display = 'flex';
        }

        function setupListeners() {
            // استقبال حدث التحذير من انقطاع الاتصال
            socket.on('player_disconnect_warning', (data) => {
                triggerDisconnectWarning(data.id, data.name);
            });
            
            // استقبال حدث عودة الاتصال لإلغاء التحذير
            socket.on('player_reconnected', (data) => {
                clearDisconnectWarning(data.id);
            });

            socket.on('game_over', (data) => {
                showWinScreen(data.winner, data.emoji);
            });

            socket.on('news_trigger', (data) => {
                showNewsAnimation(data.text, data.type);
                const area = document.getElementById('chat-area');
                const div = document.createElement('div');
                let chatClass = 'sys';
                if (data.type === 'kill') chatClass = 'chat-kill';
                else if (data.type === 'save') chatClass = 'chat-save';
                else if (data.type === 'exec') chatClass = 'chat-exec';
                div.className = `msg ${chatClass}`;
                div.innerHTML = data.text;
                area.appendChild(div);
                area.scrollTop = area.scrollHeight;
            });

            socket.on('log', (data) => {
                const area = document.getElementById('chat-area');
                const div = document.createElement('div');
                div.className = `msg ${data.style}`;
                div.innerHTML = data.txt;
                area.appendChild(div);
                area.scrollTop = area.scrollHeight;
            });

            socket.on('kicked', () => {
                alert("تم طردك من اللعبة من قبل المشرف.");
                location.reload();
            });

            socket.on('ui_update', (data) => {
                currentPlayersData = data.players_list;
                isAdminClient = data.is_admin;
                if(document.getElementById('players-modal-overlay').style.display === 'flex') renderPlayerModal();

                if(data.phase === 'DAY') {
                    document.body.style.backgroundColor = '#87CEEB'; 
                } else if(data.phase === 'NIGHT') {
                    document.body.style.backgroundColor = '#121212'; 
                } else if (data.phase === 'LOBBY') {
                    document.body.style.backgroundColor = '#121212';
                }

                if (data.phase !== currentPhase) {
                    if (data.phase === 'ENDED') {
                    } else if ((currentPhase === 'NIGHT' && data.phase === 'DAY') || 
                        (currentPhase === 'DAY' && data.phase === 'NIGHT') ||
                        (currentPhase === 'LOBBY' && data.phase === 'NIGHT')) {
                        triggerAnimation(data.phase);
                    }
                    
                    currentPhase = data.phase;
                    document.getElementById('confirm-btn').style.display = 'none';
                    selectedTargetId = null;
                    
                    if (data.phase === 'NIGHT') {
                         document.getElementById('mafia-toggle-btn').style.display = 'none';
                         mafiaChatMode = false;
                    }
                }

                if (isMafia && data.phase === 'DAY') {
                    document.getElementById('mafia-toggle-btn').style.display = 'block';
                } else {
                    document.getElementById('mafia-toggle-btn').style.display = 'none';
                }

                document.getElementById('phase-badge').innerText = data.phase_ar;
                document.getElementById('count-badge').innerText = `👥 ${data.alive_count}`;
                document.getElementById('timer-box').innerText = data.timer > 0 ? data.timer : "";

                const adminPanel = document.getElementById('admin-panel');
                const gameControls = document.getElementById('game-controls');
                const btnStart = document.getElementById('btn-start');
                const btnReset = document.getElementById('btn-reset');
                
                if(data.phase === 'LOBBY' || data.phase === 'ENDED') {
                    adminPanel.style.display = 'block';
                    gameControls.style.display = 'none';
                    updateLobbyList(data.players_list, data.is_admin);
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

            socket.on('show_role', (r) => {
                isMafia = (r.indexOf('مافيا') !== -1);
                document.getElementById('role-text').innerText = r;
                document.getElementById('role-popup').style.display = 'block';
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
                if (document.getElementById('confirm-btn').style.display === 'block' && isMafia && currentPhase === 'NIGHT') { } 
                else {
                    grid.innerHTML = "";
                    instr.innerText = data.msg || "";
                }
                if(!data.can_act) return;
                if(data.show_skip) {
                    const skipBtn = document.createElement('div');
                    skipBtn.className = 'p-card skip-btn';
                    skipBtn.innerText = "⛔ امتناع";
                    skipBtn.setAttribute('data-id', 'SKIP');
                    skipBtn.onclick = () => { selectTarget('SKIP', skipBtn); };
                    grid.appendChild(skipBtn);
                }
                data.targets.forEach(p => {
                    const el = document.createElement('div');
                    el.className = 'p-card';
                    if(p.id === myId) { el.innerText = " (أنت) " + p.name; el.classList.add('self-card'); } 
                    else { el.innerText = p.name; }
                    el.setAttribute('data-id', p.id);
                    el.onclick = () => { selectTarget(p.id, el); };
                    grid.appendChild(el);
                });
            });
        }

        function selectTarget(tid, el) {
            selectedTargetId = tid;
            highlightSelection(el);
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

        function updateLobbyList(players, isAdmin) {
            const list = document.getElementById('lobby-list');
            list.innerHTML = "";
            players.forEach(p => {
                const div = document.createElement('div');
                div.className = 'lobby-card';
                div.innerHTML = `<span>${p.name}</span>`;
                if(isAdmin && p.id !== myId) {
                    const actionsDiv = document.createElement('div');
                    actionsDiv.className = 'lobby-actions';
                    const promoteBtn = document.createElement('button');
                    promoteBtn.className = 'promote-btn';
                    promoteBtn.innerHTML = '👑';
                    promoteBtn.title = "تسليم القيادة";
                    promoteBtn.onclick = () => { if(confirm(`هل أنت متأكد من تسليم الإدارة لـ ${p.name}؟`)) socket.emit('promote_player', {id: p.id}); };
                    const kickBtn = document.createElement('button');
                    kickBtn.className = 'kick-btn';
                    kickBtn.innerText = 'X';
                    kickBtn.title = "طرد";
                    kickBtn.onclick = () => { if(confirm(`طرد ${p.name}؟`)) socket.emit('kick_player', {id: p.id}); };
                    actionsDiv.appendChild(promoteBtn);
                    actionsDiv.appendChild(kickBtn);
                    div.appendChild(actionsDiv);
                }
                list.appendChild(div);
            });
        }

        function highlightSelection(el) {
            document.querySelectorAll('.p-card').forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
        }

        function sendMsg() {
            const inp = document.getElementById('chat-input');
            if(inp.value.trim()) {
                socket.emit('chat', {msg: inp.value.trim(), is_private: mafiaChatMode});
                inp.value = "";
                inp.focus();
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

def translate_role(r):
    # إضافة ترجمة للأدوار التقنية لكي لا تظهر بالإنجليزية
    return {
        'Mafia': 'مافيا 😈', 
        'Doctor': 'دكتور 🚑', 
        'Shaib': 'شايب 🕵️‍♂️', 
        'Citizen': 'مواطن 🧔',
        'Spectator': 'مشاهد 👀',
        'Lobby': 'في الانتظار ⏳'
    }.get(r, r)

# --- Helper Functions for Rooms ---
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
    # تم تعديل هذا السطر لإرسال حالة الاتصال للفرونت اند
    players_list = [{'id': k, 'name': v['name'], 'is_admin_flag': (k == game.admin_id), 'connected': v.get('connected', True)} for k,v in game.players.items()]
    
    phase_ar = {'LOBBY': 'الانتظار', 'NIGHT': 'ليل 🌑', 'DAY': 'نهار ☀️', 'ENDED': 'النهاية'}.get(game.phase, '')
    
    socketio.emit('ui_update', {
        'phase': game.phase,
        'phase_ar': phase_ar,
        'timer': game.timer,
        'alive_count': alive_count,
        'is_admin': False, # Will be overridden per user
        'players_list': players_list
    }, room=room)

    # Need to send individual admin flags since broadcast sends same msg to all
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

def send_news(text, news_type, room):
    socketio.emit('news_trigger', {'text': text, 'type': news_type}, room=room)

# --- دالة لنقل بيانات اللاعب القديم للجديد ---
def migrate_player_state(game, room, old_sid, new_sid):
    # نقل بيانات اللاعب
    player_data = game.players[old_sid]
    player_data['connected'] = True
    game.players[new_sid] = player_data
    del game.players[old_sid]
    
    # تحديث الخرائط
    player_rooms[new_sid] = room
    if old_sid in player_rooms:
        del player_rooms[old_sid]
    
    # تحديث المشرف
    if game.admin_id == old_sid:
        game.admin_id = new_sid
        
    # تحديث التصويتات والقرارات
    # 1. المافيا
    if old_sid in game.mafia_votes:
        game.mafia_votes[new_sid] = game.mafia_votes.pop(old_sid)
    # تحديث القيم (إذا كان هو الهدف)
    for k, v in game.mafia_votes.items():
        if v == old_sid: game.mafia_votes[k] = new_sid

    if old_sid in game.mafia_pre_votes:
        game.mafia_pre_votes[new_sid] = game.mafia_pre_votes.pop(old_sid)
    for k, v in game.mafia_pre_votes.items():
        if v == old_sid: game.mafia_pre_votes[k] = new_sid

    # 2. الطبيب
    if game.doctor_target == old_sid:
        game.doctor_target = new_sid
    if game.last_protected == old_sid:
        game.last_protected = new_sid
        
    # 3. تصويت النهار
    if old_sid in game.day_votes:
        game.day_votes[new_sid] = game.day_votes.pop(old_sid)
    for k, v in game.day_votes.items():
        if v == old_sid: game.day_votes[k] = new_sid
    
    # الانضمام للغرف الصوتية
    join_room(room, new_sid)
    if player_data['role'] == 'Mafia':
        join_room(f"mafia_{room}", new_sid)


# -------------------------------------------------------
# 🔥 دالة جديدة: معالجة مهلة انقطاع الاتصال (30ث صمت + 20ث فقاعة) 🔥
# -------------------------------------------------------
def handle_disconnect_timeout(room_code, sid):
    """
    1. تنتظر 30 ثانية (صامتة).
    2. إذا لم يعد: تظهر الفقاعة.
    3. تنتظر 20 ثانية (وقت الفقاعة).
    4. إذا لم يعد: تقتله.
    """
    
    # === المرحلة الأولى: الانتظار الصامت (30 ثانية) ===
    socketio.sleep(30) 

    # التحقق: هل رجع اللاعب خلال الـ 30 ثانية؟
    if room_code not in games or sid not in games[room_code].players: return
    game = games[room_code]
    player = game.players[sid]
    
    if player.get('connected', False): 
        return # اللاعب رجع، نلغي العملية
        
    # === المرحلة الثانية: إظهار الفقاعة ===
    # الآن نرسل التنبيه لللاعبين (الفقاعة تطلع هنا)
    socketio.emit('player_disconnect_warning', 
                  {'id': sid, 'name': player['name']}, 
                  room=room_code)
    
    # تحديث الواجهة لإظهار علامة الشبكة في القائمة
    broadcast_ui(game, room_code)

    # === المرحلة الثالثة: انتظار العد التنازلي للفقاعة (20 ثانية) ===
    socketio.sleep(20) 
    
    # === المرحلة الرابعة: القتل النهائي ===
    # نتأكد للمرة الأخيرة
    if not player.get('connected', False) and player.get('alive', False):
        # 1. قتل اللاعب
        player['alive'] = False
        
        # 2. إرسال خبر الموت
        system_log(f"☠️ مات <b>{player['name']}</b> بسبب انقطاع الاتصال.", room_code, 'chat-kill')
        
        # 3. إخفاء الفقاعة
        socketio.emit('player_reconnected', {'id': sid}, room=room_code)
        
        # 4. خروجه من غرف المافيا
        try: leave_room(f"mafia_{room_code}", sid)
        except: pass

        # 5. التحقق من الفوز
        if not check_win_condition(game, room_code):
            broadcast_ui(game, room_code)
            send_action_buttons(game, room_code)


# --- أحداث SocketIO المعدلة للغرف ---

@socketio.on('join_request')
def on_join_request(data):
    sid = request.sid
    name = data.get('name', 'Unknown')[:12]
    action = data.get('action')
    raw_code = data.get('code')
    code = raw_code.upper() if raw_code else ''
    client_uuid = data.get('uuid')

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
        
        # --- منطق إعادة الاتصال الذكي المحسن ---
        existing_sid = None
        
        # 1. البحث عن اللاعب باستخدام بصمة الجهاز UUID
        for pid, p in game.players.items():
            if p.get('uuid') == client_uuid:
                existing_sid = pid
                break
        
        # 2. معالجة الدخول
        if existing_sid:
            # حالة إعادة اتصال (اللاعب موجود سابقاً)
            migrate_player_state(game, room_code, existing_sid, sid)
            
            emit('join_success', {'room_code': room_code})
            system_log(f"🔄 عاد <b>{name}</b> للاتصال.", room_code)
            
            # إرسال تنبيه إلغاء الفقاعة
            socketio.emit('player_reconnected', {'id': existing_sid}, room=room_code)
            
            # 🔥 (مهم) تأخير بسيط لضمان أن صفحة اللاعب حملت الأكواد وجاهزة لاستقبال الدور
            socketio.sleep(0.5) 
            
            # إعادة إرسال الدور والأزرار والواجهة
            p_data = game.players[sid]
            
            # التأكد من إظهار الدور الصحيح حتى لو كان متفرجاً
            current_role_ar = translate_role(p_data['role'])
            socketio.emit('show_role', current_role_ar, room=sid)
            
            broadcast_ui(game, room_code)
            send_action_buttons(game, room_code) 

        else:
            # حالة لاعب جديد تماماً
            # إذا اللعبة بدأت، يدخل كمتفرج (Spectator) وليس Lobby
            if game.phase != "LOBBY":
                role = 'Spectator'
            else:
                role = 'Lobby'

            join_room(room_code)
            player_rooms[sid] = room_code
            
            alive = True if game.phase == "LOBBY" else False
            
            game.players[sid] = {
                'name': name, 
                'role': role, 
                'alive': alive, 
                'shaib_used': False, 
                'last_msg_time':0, 
                'has_acted': False, 
                'connected': True,
                'uuid': client_uuid
            }
            
            emit('join_success', {'room_code': room_code})
            system_log(f"دخل <b>{name}</b>.", room_code)
            
            socketio.sleep(0.5) # تأخير بسيط للتزامن
            
            # إذا دخل كمتفرج أثناء اللعب، نظهر له دوره كمتفرج
            if role == 'Spectator':
                 socketio.emit('show_role', 'مشاهد 👀', room=sid)
                 
            broadcast_ui(game, room_code)

@socketio.on('kick_player')
def on_kick(data):
    game, room = get_game(request.sid)
    if not game: return

    requester = request.sid
    target_id = data.get('id')
    if requester != game.admin_id: return
    if target_id not in game.players: return
    
    target_name = game.players[target_id]['name']
    socketio.emit('kicked', room=target_id)
    try: leave_room(f"mafia_{room}", target_id)
    except: pass
    
    # Clean up maps
    if target_id in player_rooms:
        del player_rooms[target_id]
        
    del game.players[target_id]
    system_log(f"👮‍♂️ قام المشرف بطرد <b>{target_name}</b>.", room)
    broadcast_ui(game, room)

@socketio.on('promote_player')
def on_promote(data):
    game, room = get_game(request.sid)
    if not game: return

    requester = request.sid
    target_id = data.get('id')
    if requester != game.admin_id: return
    if target_id not in game.players: return
    game.admin_id = target_id
    target_name = game.players[target_id]['name']
    system_log(f"👑 قام المشرف بتسليم القيادة إلى <b>{target_name}</b>.", room)
    broadcast_ui(game, room)

@socketio.on('reset_game')
def on_reset():
    game, room = get_game(request.sid)
    if not game: return
    if request.sid != game.admin_id: return
    
    game.reset_game()
    system_log("🔄 تم إعادة اللعبة. الشات السابق تم مسحه.", room)
    broadcast_ui(game, room)

@socketio.on('start_game')
def on_start():
    game, room = get_game(request.sid)
    if not game: return
    if request.sid != game.admin_id: return
    
    if len(game.players) < 4:
        system_log("❌ العدد قليل! مطلوب 4 على الأقل.", room)
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
    mafia_room_id = f"mafia_{room}"
    
    for i, pid in enumerate(p_ids):
        r = roles[i]
        game.players[pid]['role'] = r
        game.players[pid]['alive'] = True
        game.players[pid]['shaib_used'] = False
        game.players[pid]['has_acted'] = False
        game.players[pid]['last_msg_time'] = 0
        game.players[pid]['connected'] = True
        
        socketio.emit('show_role', translate_role(r), room=pid)
        if r == 'Mafia':
            join_room(mafia_room_id, pid)
            mafia_names.append(game.players[pid]['name'])
            
    if mafia_names:
        socketio.emit('log', {'txt': f"شركاؤك هم: {', '.join(mafia_names)}", 'style': 'mafia'}, room=mafia_room_id)

    game.phase = "NIGHT"
    game.timer = 120  
    game.mafia_votes = {}
    game.mafia_pre_votes = {} 
    game.doctor_target = None
    game.day_votes = {}
    
    system_log("🌃 خيم الليل... المافيا، الطبيب، والشايب، استيقظوا!", room)
    broadcast_ui(game, room)
    send_action_buttons(game, room)
    socketio.start_background_task(game_loop, room)

@socketio.on('mafia_select')
def on_mafia_select(data):
    game, room = get_game(request.sid)
    if not game: return

    sid = request.sid
    target = data.get('target')
    
    if game.phase != "NIGHT" or game.players[sid]['role'] != 'Mafia': return
    if not game.players[sid]['alive']: return

    game.mafia_pre_votes[sid] = target
    
    mafia_ids = [pid for pid, p in game.players.items() if p['role'] == 'Mafia' and p['alive']]
    votes = [game.mafia_pre_votes.get(pid) for pid in mafia_ids]
    
    consensus = False
    if len(votes) == len(mafia_ids) and all(v == votes[0] for v in votes) and None not in votes:
        consensus = True
        
    socketio.emit('mafia_sync', {
        'selections': list(game.mafia_pre_votes.values()),
        'consensus': consensus
    }, room=f"mafia_{room}")

def check_night_finished(game):
    needed = 0
    completed = 0
    
    alive_mafia = [p for p in game.players.values() if p['role'] == 'Mafia' and p['alive']]
    if alive_mafia:
        needed += 1
        if game.mafia_votes: 
            completed += 1
            
    alive_doctor = [p for p in game.players.values() if p['role'] == 'Doctor' and p['alive']]
    if alive_doctor:
        needed += 1
        if alive_doctor[0]['has_acted']:
            completed += 1
            
    alive_shaib = [p for p in game.players.values() if p['role'] == 'Shaib' and p['alive']]
    if alive_shaib:
        needed += 1
        if alive_shaib[0]['has_acted']:
            completed += 1
            
    if needed > 0 and completed == needed:
        game.skip_timer_flag = True

@socketio.on('action')
def on_action(data):
    game, room = get_game(request.sid)
    if not game: return

    sid = request.sid
    if not game.players[sid].get('alive', False) or not game.players[sid].get('connected', True): return
    
    target_id = data.get('target')
    player = game.players[sid]
    role = player['role']

    if player.get('has_acted', False): return

    if game.phase == "NIGHT":
        if role == 'Mafia':
            mafia_ids = [pid for pid, p in game.players.items() if p['role'] == 'Mafia' and p['alive']]
            votes = [game.mafia_pre_votes.get(pid) for pid in mafia_ids]
            
            if not (len(votes) == len(mafia_ids) and all(v == target_id for v in votes) and target_id is not None):
                socketio.emit('log', {'txt': "⚠️ لم يتم الإجماع بعد.", 'style': 'mafia'}, room=sid)
                return 

            for m_id in mafia_ids:
                game.mafia_votes[m_id] = target_id
                game.players[m_id]['has_acted'] = True
                socketio.emit('update_buttons', {'can_act': False, 'msg': 'تم تنفيذ العملية'}, room=m_id)
            
            target_name = game.players.get(target_id, {}).get('name', 'Unknown')
            socketio.emit('log', {'txt': f"🔪 تم تأكيد عملية الاغتيال على: {target_name}", 'style': 'mafia'}, room=f"mafia_{room}")
            check_night_finished(game)
        
        elif role == 'Doctor':
            if target_id == game.last_protected:
                 socketio.emit('log', {'txt': "❌ لا يمكنك حماية نفس الشخص مرتين متتاليتين!", 'style': 'sys'}, room=sid)
                 send_action_buttons(game, room) 
                 return
                 
            game.doctor_target = target_id
            player['has_acted'] = True
            socketio.emit('log', {'txt': f"اخترت حماية: {game.players[target_id]['name']}", 'style': 'sys'}, room=sid)
            socketio.emit('update_buttons', {'can_act': False, 'msg': 'تم تسجيل الحماية'}, room=sid)
            check_night_finished(game)

        elif role == 'Shaib':
            if not player.get('shaib_used', False):
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
        
        msg = "تم تسجيل تصويتك." if target_id != 'SKIP' else "تم تسجيل امتناعك."
        socketio.emit('log', {'txt': msg, 'style': 'sys'}, room=sid)
        socketio.emit('update_buttons', {'can_act': False, 'msg': msg}, room=sid)
        
        alive_count = sum(1 for p in game.players.values() if p.get('alive', False))
        current_votes = [v for k,v in game.day_votes.items() if game.players[k].get('alive', False)]
        
        if len(current_votes) >= alive_count:
            game.skip_timer_flag = True

@socketio.on('chat')
def on_chat(data):
    game, room = get_game(request.sid)
    if not game: return

    sid = request.sid
    msg = data.get('msg', '')[:200]
    is_private = data.get('is_private', False) # استقبال حالة الزر

    p = game.players[sid]
    name = p['name']
    
    if not p.get('alive', False) or not p.get('connected', True): return

    now = time.time()
    if now - p.get('last_msg_time', 0) < 1: return
    p['last_msg_time'] = now

    if game.phase == "NIGHT":
        if p['role'] == 'Mafia':
            socketio.emit('log', {'txt': f"😈 {name}: {msg}", 'style': 'mafia'}, room=f"mafia_{room}")
        else:
            socketio.emit('log', {'txt': "🤫 الصمت يعم المكان ليلاً...", 'style': 'sys'}, room=sid)
    elif game.phase == "DAY":
        if p['role'] == 'Mafia' and is_private:
             socketio.emit('log', {'txt': f"😈 [همس] {name}: {msg}", 'style': 'mafia'}, room=f"mafia_{room}")
        else:
            style = 'global'
            socketio.emit('log', {'txt': f"<b>{name}</b>: {msg}", 'style': style}, room=room)
    else:
        socketio.emit('log', {'txt': f"<b>{name}</b>: {msg}", 'style': 'global'}, room=room)

# -------------------------------------------------------
# 🔥 تعديل دالة الخروج لتشغيل العداد في الخلفية 🔥
# -------------------------------------------------------
@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    game, room = get_game(sid)
    
    if game:
        if sid in game.players:
            game.players[sid]['connected'] = False
            
            # تم حذف سطر إرسال التنبيه الفوري من هنا
            # ونقله إلى دالة handle_disconnect_timeout ليظهر بعد 30 ثانية
            
            # 🔥 تشغيل المهمة الخلفية للعد التنازلي 🔥
            if game.players[sid].get('alive', False):
                socketio.start_background_task(handle_disconnect_timeout, room, sid)
        
        # إذا الغرفة فاضية تماماً من المتصلين، نحذفها لتوفير الموارد
        connected_count = sum(1 for p in game.players.values() if p['connected'])
        if connected_count == 0:
            del games[room]
        else:
            broadcast_ui(game, room)

# -------------------------------------------------------
# 5. منطق اللعبة (Game Loop) - معدل لكل غرفة
# -------------------------------------------------------
def game_loop(room):
    # نستخدم حلقة بينما الغرفة موجودة
    while room in games and games[room].phase not in ["LOBBY", "ENDED"]:
        game = games[room]
        socketio.sleep(1)
        game.timer -= 1
        broadcast_ui(game, room)

        if game.timer <= 0 or game.skip_timer_flag:
            game.skip_timer_flag = False
            
            if game.phase == "NIGHT":
                process_night(game, room)
            elif game.phase == "DAY":
                process_day(game, room)

def process_night(game, room):
    victim_id = None
    if game.mafia_votes:
        victim_id = list(game.mafia_votes.values())[0]

    if victim_id and (victim_id not in game.players or not game.players[victim_id].get('alive', False)):
        victim_id = None

    saved = False
    actual_victim = None
    
    # تصفير متغير الحماية من الاغتيال لليلة الجديدة قبل الحساب
    game.last_saved_from_kill = None

    if game.doctor_target and game.doctor_target == victim_id:
        saved = True
        game.last_protected = game.doctor_target
        # هنا يتم حفظ الشخص الذي نجا لمنع المافيا من استهدافه في الليلة التالية
        game.last_saved_from_kill = victim_id 
        actual_victim = None 
    else:
        game.last_protected = game.doctor_target
        actual_victim = victim_id

    if actual_victim:
        game.players[actual_victim]['alive'] = False
        try: leave_room(f"mafia_{room}", actual_victim)
        except: pass

    if check_win_condition(game, room):
        return

    game.phase = "DAY"
    game.timer = 300 
    broadcast_ui(game, room) 
    
    socketio.sleep(3.5)

    msg = "☀️ أشرقت الشمس..."
    if actual_victim:
        victim_name = game.players[actual_victim]['name']
        news = f"🩸 تم اغتيال <b>{victim_name}</b> الليلة! 🩸"
        send_news(news, 'kill', room)
        msg += f" وللأسف وجدنا <b>{victim_name}</b> مقتولاً! 💀"
        
    elif saved and victim_id:
        target_name = game.players[victim_id]['name']
        news = f"🛡️ تم إنقاذ <b>{target_name}</b> من محاولة اغتيال! 🛡️"
        send_news(news, 'save', room)
        msg += f" وقد تمت محاولة اغتيال فاشلة على <b>{target_name}</b>! لكنه نجا بفضل الطبيب."
    else:
        msg += " ولم يُقتل أحد الليلة! الحمدلله. 🙏"
        system_log(msg, room)
    
    game.day_votes = {}
    game.mafia_votes = {}
    game.mafia_pre_votes = {} 
    game.doctor_target = None
    
    for p in game.players.values():
        p['shaib_used'] = False 
        p['has_acted'] = False

    if not check_win_condition(game, room):
        broadcast_ui(game, room)
        send_action_buttons(game, room)

def process_day(game, room):
    victim_id = None
    alive_ids = [pid for pid,p in game.players.items() if p.get('alive', False)]
    current_votes = []
    
    for voter_id, target in game.day_votes.items():
        if voter_id in alive_ids:
            if target == 'SKIP':
                current_votes.append('SKIP')
            elif target in game.players and game.players[target].get('alive', False):
                current_votes.append(target)
                
    if current_votes:
        most_common = Counter(current_votes).most_common()
        top_target, top_count = most_common[0]
        
        if len(most_common) == 1:
            if top_target != 'SKIP':
                victim_id = top_target
        else:
            second_target, second_count = most_common[1]
            if top_count > second_count:
                if top_target != 'SKIP':
                    victim_id = top_target
                else:
                    victim_id = None
            else:
                victim_id = None 

    msg = "🌑 حل الظلام..."
    if victim_id:
        game.players[victim_id]['alive'] = False
        try: leave_room(f"mafia_{room}", victim_id)
        except: pass
        victim_name = game.players[victim_id]['name']
        news = f"⚖️ حكمت المدينة بإعدام <b>{victim_name}</b>! ⚰️"
        send_news(news, 'exec', room)
        msg = f"⚖️ قررت المدينة إعدام <b>{victim_name}</b>. \n" + msg
    else:
        system_log("⚖️ لم يتم إعدام أحد (تعادل أو غلبت كفة الامتناع).", room, 'sys')

    socketio.sleep(4.0)

    for p in game.players.values():
        p['has_acted'] = False
        p['shaib_used'] = False 

    game.day_votes = {}
    game.mafia_votes = {}
    game.mafia_pre_votes = {}
    game.doctor_target = None

    if check_win_condition(game, room):
        return

    game.phase = "NIGHT"
    game.timer = 120 
    broadcast_ui(game, room) 
    send_action_buttons(game, room)

def check_win_condition(game, room):
    if game.phase == "LOBBY": return False

    mafia_count = sum(1 for p in game.players.values() if p.get('alive', False) and p.get('role') == 'Mafia')
    innocent_count = sum(1 for p in game.players.values() if p.get('alive', False) and p.get('role') != 'Mafia')
    
    winner = None
    emoji = ""
    
    if mafia_count == 0 and innocent_count > 0:
        winner = "القرية (المواطنين) 🧔🚑🕵️‍"
        emoji = "🧔"
    elif mafia_count >= innocent_count and mafia_count > 0:
        winner = "المافيا 😈"
        emoji = "😈"

    if winner:
        game.phase = "ENDED"
        game.timer = 0
        socketio.emit('game_over', {'winner': winner, 'emoji': emoji}, room=room)
        broadcast_ui(game, room)
        send_action_buttons(game, room)
        return True
    return False

def send_action_buttons(game, room):
    alive_players = [{'id': k, 'name': v['name']} for k,v in game.players.items() if v.get('alive', False)]
    
    for sid, p in game.players.items():
        if not p.get('alive', False) or game.phase == "ENDED" or not p.get('connected', True):
            socketio.emit('update_buttons', {'can_act': False, 'msg': 'أنت متفرج الآن', 'targets': []}, room=sid)
            continue
            
        role = p['role']
        data = {'can_act': False, 'msg': '', 'targets': [], 'show_skip': False}
        
        others = [tp for tp in alive_players if tp['id'] != sid]

        if game.phase == "NIGHT":
            if role == 'Mafia':
                # تصفية القائمة لإزالة الشخص الذي تمت حمايته الليلة السابقة
                valid_targets = [tp for tp in others if tp['id'] != game.last_saved_from_kill]
                data = {'can_act': True, 'msg': 'اختر ضحية للقتل:', 'targets': valid_targets, 'show_skip': False}
            elif role == 'Doctor':
                # الطبيب يستطيع اختيار نفسه
                data = {'can_act': True, 'msg': 'اختر شخصاً لحمايته:', 'targets': alive_players, 'show_skip': False}
            elif role == 'Shaib':
                if not p.get('shaib_used', False): 
                    data = {'can_act': True, 'msg': 'اختر شخصاً للتحقق منه:', 'targets': others, 'show_skip': False}
                else:
                    data = {'can_act': False, 'msg': 'انتظر الليلة القادمة.', 'targets': []}
            else:
                data = {'can_act': False, 'msg': 'نم بأمان...', 'targets': []}

        elif game.phase == "DAY":
            # التصويت ضد الآخرين فقط
            data = {'can_act': True, 'msg': 'صوت لمن تشك به للإعدام:', 'targets': others, 'show_skip': True}

        if p.get('has_acted', False):
             data = {'can_act': False, 'msg': '✅ تم استلام قرارك.', 'targets': []}

        socketio.emit('update_buttons', data, room=sid)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)


# =========================
# ADDED: GitHub Images دعم الصور من GitHub
# =========================

# روابط الصور من الريبو
GITHUB_BASE = "https://raw.githubusercontent.com/IBRAHIM-IS/mafia/main/"

ROLE_IMAGES = {
    "مافيا": GITHUB_BASE + "mafia.png",
    "دكتور": GITHUB_BASE + "doctor.png",
    "شايب": GITHUB_BASE + "shaib.png",
    "مواطن": GITHUB_BASE + "citizen.png"
}

HOME_IMAGE = GITHUB_BASE + "home.png"


def get_role_image(role_name: str):
    """ترجع رابط صورة الدور"""
    return ROLE_IMAGES.get(role_name, "")


def get_home_image():
    """ترجع صورة الصفحة الرئيسية"""
    return HOME_IMAGE

# =========================
# END ADDITION
# =========================
