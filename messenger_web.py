#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
On Line Messenger - Web Version with Message Status
"""

import os
import hashlib
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from functools import wraps
import mimetypes

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

DATA_DIR = 'web_data'
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')
CONTACTS_FILE = os.path.join(DATA_DIR, 'contacts.json')
FILES_DIR = os.path.join(DATA_DIR, 'files')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def load_messages():
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_messages(messages):
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

def load_contacts():
    if os.path.exists(CONTACTS_FILE):
        with open(CONTACTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_contacts(contacts):
    with open(CONTACTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Смайлики
EMOJIS = {
    '😀': '😀', '😃': '😃', '😄': '😄', '😁': '😁', '😆': '😆',
    '😅': '😅', '😂': '😂', '🤣': '🤣', '😊': '😊', '😇': '😇',
    '🙂': '🙂', '🙃': '🙃', '😉': '😉', '😌': '😌', '😍': '😍',
    '🥰': '🥰', '😘': '😘', '😗': '😗', '😙': '😙', '😚': '😚',
    '😋': '😋', '😛': '😛', '😝': '😝', '😜': '😜', '🤪': '🤪',
    '❤️': '❤️', '🧡': '🧡', '💛': '💛', '💚': '💚', '💙': '💙',
    '💜': '💜', '🖤': '🖤', '👍': '👍', '👎': '👎', '👊': '👊'
}

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    phone = data.get('phone', '').strip()
    
    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400
    
    users = load_users()
    
    if username in users:
        return jsonify({'error': 'Username already exists'}), 400
    
    users[username] = {
        'username': username,
        'password_hash': hash_password(password),
        'phone': phone,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'status': 'offline',
        'avatar': f'https://ui-avatars.com/api/?background=667eea&color=fff&name={username[0].upper()}',
        'bio': '',
        'last_seen': ''
    }
    
    save_users(users)
    
    contacts = load_contacts()
    if username not in contacts:
        contacts[username] = []
    save_contacts(contacts)
    
    return jsonify({'success': True, 'message': 'Registration successful'})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    users = load_users()
    
    if username in users and users[username]['password_hash'] == hash_password(password):
        session['username'] = username
        users[username]['status'] = 'online'
        users[username]['last_seen'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_users(users)
        
        socketio.emit('user_status', {'username': username, 'status': 'online'})
        
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid username or password'}), 401

@app.route('/logout')
def logout():
    if 'username' in session:
        users = load_users()
        if session['username'] in users:
            users[session['username']]['status'] = 'offline'
            users[session['username']]['last_seen'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_users(users)
            socketio.emit('user_status', {'username': session['username'], 'status': 'offline'})
        
        session.pop('username', None)
    return redirect(url_for('index'))

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('index'))
    return render_template('chat.html', username=session['username'], emojis=list(EMOJIS.keys()))

# Профиль
@app.route('/api/profile', methods=['GET', 'POST'])
@login_required
def profile():
    users = load_users()
    current_user = session['username']
    
    if request.method == 'GET':
        return jsonify(users.get(current_user, {}))
    
    data = request.get_json()
    if 'bio' in data:
        users[current_user]['bio'] = data['bio'][:200]
    if 'phone' in data:
        users[current_user]['phone'] = data['phone']
    if 'avatar' in data:
        users[current_user]['avatar'] = data['avatar']
    
    save_users(users)
    return jsonify({'success': True})

@app.route('/api/profile/avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ['jpg', 'jpeg', 'png', 'gif']:
        return jsonify({'error': 'Invalid file type'}), 400
    
    filename = f"avatar_{session['username']}.{ext}"
    filepath = os.path.join(FILES_DIR, filename)
    file.save(filepath)
    
    users = load_users()
    users[session['username']]['avatar'] = f'/api/files/{filename}'
    save_users(users)
    
    return jsonify({'success': True, 'avatar_url': f'/api/files/{filename}'})

# Поиск
@app.route('/api/users/search')
@login_required
def search_users():
    query = request.args.get('q', '').strip().lower()
    users = load_users()
    current_user = session['username']
    
    results = []
    for username, data in users.items():
        if username != current_user and (query in username.lower() or query in data.get('phone', '').lower()):
            results.append({
                'username': username,
                'avatar': data.get('avatar', ''),
                'phone': data.get('phone', ''),
                'status': data.get('status', 'offline')
            })
    
    return jsonify({'users': results[:20]})

# Загрузка файлов
@app.route('/api/files/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    file_id = str(uuid.uuid4())
    original_name = file.filename
    ext = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    filename = f"{file_id}.{ext}" if ext else file_id
    
    filepath = os.path.join(FILES_DIR, filename)
    file.save(filepath)
    
    mime_type, _ = mimetypes.guess_type(original_name)
    if mime_type is None:
        mime_type = 'application/octet-stream'
    
    file_type = 'image' if mime_type.startswith('image/') else 'video' if mime_type.startswith('video/') else 'file'
    
    return jsonify({
        'success': True,
        'file_id': file_id,
        'filename': original_name,
        'url': f'/api/files/{filename}',
        'type': file_type,
        'mime_type': mime_type,
        'size': os.path.getsize(filepath)
    })

@app.route('/api/files/<filename>')
def get_file(filename):
    filepath = os.path.join(FILES_DIR, filename)
    if not os.path.exists(filepath):
        return 'File not found', 404
    return send_file(filepath)

# Отправка сообщения с статусом
@app.route('/api/messages/send', methods=['POST'])
@login_required
def send_message():
    data = request.get_json()
    receiver = data.get('receiver', '').strip()
    content = data.get('content', '')
    message_type = data.get('type', 'text')
    file_data = data.get('file', None)
    
    if not receiver:
        return jsonify({'error': 'Receiver is required'}), 400
    
    messages = load_messages()
    
    message = {
        'id': str(uuid.uuid4()),
        'sender': session['username'],
        'receiver': receiver,
        'content': content,
        'type': message_type,
        'timestamp': datetime.now().strftime("%H:%M:%S"),
        'date': datetime.now().strftime("%Y-%m-%d"),
        'status': 'sent',  # sent, delivered, read
        'is_read': False
    }
    
    if file_data:
        message['file'] = file_data
    
    messages.append(message)
    save_messages(messages)
    
    # Отправляем получателю
    socketio.emit('new_message', message, room=receiver)
    
    # Обновляем статус на delivered (если получатель онлайн)
    users = load_users()
    if receiver in users and users[receiver]['status'] == 'online':
        message['status'] = 'delivered'
        save_messages(messages)
        socketio.emit('message_status', {
            'message_id': message['id'],
            'status': 'delivered'
        }, room=session['username'])
    
    return jsonify({'success': True, 'message': message})

# Отметить сообщение как прочитанное
@app.route('/api/messages/read/<message_id>', methods=['POST'])
@login_required
def mark_as_read(message_id):
    messages = load_messages()
    for msg in messages:
        if msg['id'] == message_id and msg['receiver'] == session['username']:
            msg['status'] = 'read'
            msg['is_read'] = True
            save_messages(messages)
            socketio.emit('message_status', {
                'message_id': message_id,
                'status': 'read'
            }, room=msg['sender'])
            break
    
    return jsonify({'success': True})

# Получить непрочитанные
@app.route('/api/messages/unread')
@login_required
def get_unread_messages():
    messages = load_messages()
    unread = [msg for msg in messages 
              if msg['receiver'] == session['username'] and not msg['is_read']]
    return jsonify({'messages': unread})

# Чат с пользователем
@app.route('/api/messages/chat/<receiver>')
@login_required
def get_chat_messages(receiver):
    messages = load_messages()
    chat_messages = [msg for msg in messages 
                     if (msg['sender'] == session['username'] and msg['receiver'] == receiver) or
                        (msg['sender'] == receiver and msg['receiver'] == session['username'])]
    
    # Отмечаем все сообщения от receiver как прочитанные
    for msg in chat_messages:
        if msg['sender'] == receiver and not msg['is_read']:
            msg['status'] = 'read'
            msg['is_read'] = True
            socketio.emit('message_status', {
                'message_id': msg['id'],
                'status': 'read'
            }, room=receiver)
    
    save_messages(chat_messages)
    
    return jsonify({'messages': chat_messages})

# Получить статусы сообщений
@app.route('/api/messages/status/<message_id>')
@login_required
def get_message_status(message_id):
    messages = load_messages()
    for msg in messages:
        if msg['id'] == message_id:
            return jsonify({'status': msg.get('status', 'sent')})
    return jsonify({'error': 'Message not found'}), 404

# Пользователи
@app.route('/api/users')
@login_required
def get_users():
    users = load_users()
    current_user = session['username']
    contacts = load_contacts()
    user_contacts = contacts.get(current_user, [])
    
    users_list = []
    for username, user_data in users.items():
        if username != current_user:
            users_list.append({
                'username': username,
                'status': user_data.get('status', 'offline'),
                'avatar': user_data.get('avatar', ''),
                'phone': user_data.get('phone', ''),
                'bio': user_data.get('bio', ''),
                'is_contact': username in user_contacts
            })
    
    return jsonify({'users': users_list})

# Контакты
@app.route('/api/contacts')
@login_required
def get_contacts():
    contacts = load_contacts()
    current_user = session['username']
    user_contacts = contacts.get(current_user, [])
    
    users = load_users()
    contacts_list = []
    for contact in user_contacts:
        if contact in users:
            contacts_list.append({
                'username': contact,
                'status': users[contact].get('status', 'offline'),
                'avatar': users[contact].get('avatar', ''),
                'phone': users[contact].get('phone', ''),
                'bio': users[contact].get('bio', '')
            })
    
    return jsonify({'contacts': contacts_list})

@app.route('/api/contacts/add', methods=['POST'])
@login_required
def add_contact():
    data = request.get_json()
    contact_username = data.get('username', '').strip()
    
    users = load_users()
    if contact_username not in users:
        return jsonify({'error': 'User not found'}), 404
    
    contacts = load_contacts()
    current_user = session['username']
    
    if current_user not in contacts:
        contacts[current_user] = []
    
    if contact_username not in contacts[current_user]:
        contacts[current_user].append(contact_username)
        save_contacts(contacts)
        
        if contact_username not in contacts:
            contacts[contact_username] = []
        if current_user not in contacts[contact_username]:
            contacts[contact_username].append(current_user)
            save_contacts(contacts)
        
        return jsonify({'success': True, 'message': 'Contact added'})
    
    return jsonify({'error': 'Contact already exists'}), 400

@app.route('/api/contacts/remove', methods=['POST'])
@login_required
def remove_contact():
    data = request.get_json()
    contact_username = data.get('username', '').strip()
    
    contacts = load_contacts()
    current_user = session['username']
    
    if current_user in contacts and contact_username in contacts[current_user]:
        contacts[current_user].remove(contact_username)
        save_contacts(contacts)
        return jsonify({'success': True, 'message': 'Contact removed'})
    
    return jsonify({'error': 'Contact not found'}), 404

# Импорт контактов из VCF/CSV
@app.route('/api/contacts/import', methods=['POST'])
@login_required
def import_contacts():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    content = file.read().decode('utf-8', errors='ignore')
    contacts = load_contacts()
    current_user = session['username']
    
    if current_user not in contacts:
        contacts[current_user] = []
    
    imported = 0
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Ищем username или телефон
        if line.startswith('BEGIN:VCARD'):
            # VCF формат
            for vcard_line in lines:
                if vcard_line.startswith('FN:'):
                    name = vcard_line[3:].strip()
                    # Пытаемся найти пользователя по имени
                    users = load_users()
                    for username in users:
                        if username.lower() == name.lower() and username != current_user:
                            if username not in contacts[current_user]:
                                contacts[current_user].append(username)
                                imported += 1
                    break
        else:
            # Простой текст: каждое имя или номер на новой строке
            users = load_users()
            for username in users:
                if (username.lower() == line.lower() or 
                    users[username].get('phone', '') == line) and username != current_user:
                    if username not in contacts[current_user]:
                        contacts[current_user].append(username)
                        imported += 1
    
    save_contacts(contacts)
    
    return jsonify({'success': True, 'imported': imported})

@app.route('/api/emojis')
def get_emojis():
    return jsonify({'emojis': list(EMOJIS.keys())})

# SocketIO
@socketio.on('join')
def on_join(data):
    username = data['username']
    join_room(username)
    print(f"{username} joined")

@socketio.on('typing')
def on_typing(data):
    emit('typing', {'sender': data['receiver']}, room=data['receiver'])

@socketio.on('stop_typing')
def on_stop_typing(data):
    emit('stop_typing', {'sender': data['receiver']}, room=data['receiver'])

@socketio.on('message_delivered')
def on_message_delivered(data):
    messages = load_messages()
    for msg in messages:
        if msg['id'] == data['message_id']:
            msg['status'] = 'delivered'
            save_messages(messages)
            emit('message_status', {
                'message_id': data['message_id'],
                'status': 'delivered'
            }, room=msg['sender'])
            break

@socketio.on('call_user')
def on_call(data):
    emit('incoming_call', {
        'caller': data['caller'],
        'call_type': data['type'],
        'call_id': data['call_id']
    }, room=data['callee'])

@socketio.on('accept_call')
def on_accept_call(data):
    emit('call_accepted', {
        'callee': data['callee'],
        'call_id': data['call_id']
    }, room=data['caller'])

@socketio.on('reject_call')
def on_reject_call(data):
    emit('call_rejected', {
        'call_id': data['call_id']
    }, room=data['caller'])

@socketio.on('end_call')
def on_end_call(data):
    socketio.emit('call_ended', {'call_id': data['call_id']})

@socketio.on('offer')
def on_offer(data):
    emit('offer', {
        'offer': data['offer'],
        'caller': data['caller'],
        'call_id': data['call_id']
    }, room=data['callee'])

@socketio.on('answer')
def on_answer(data):
    emit('answer', {
        'answer': data['answer'],
        'call_id': data['call_id']
    }, room=data['caller'])

@socketio.on('ice_candidate')
def on_ice_candidate(data):
    emit('ice_candidate', {
        'candidate': data['candidate'],
        'call_id': data['call_id']
    }, room=data['target'])

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)