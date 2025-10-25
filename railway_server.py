#!/usr/bin/env python3
"""
RemoteDroid Relay Server для Railway
Совместим с Android приложением RemoteDroid
"""

from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import uuid
import time
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'remotedroid-secret-key'
CORS(app, origins="*")
socketio = SocketIO(app, cors_allowed_origins="*")

# Хранилище сессий
sessions = {}  # session_id -> {server_socket_id, client_socket_id, created_at, device_info}
server_sessions = {}  # server_socket_id -> session_id

@app.route('/')
def index():
    """Главная страница"""
    return jsonify({
        "message": "RemoteDroid Relay Server",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "api_servers": "/api/servers",
            "api_session": "/api/session",
            "websocket": "/socket.io/"
        }
    })

@app.route('/api/servers')
def get_servers():
    """Получить список доступных серверов"""
    available_servers = []
    
    for session_id, session in sessions.items():
        if session.get('server_socket_id') and not session.get('client_socket_id'):
            available_servers.append({
                'sessionId': session_id,
                'serverId': session.get('server_socket_id'),
                'createdAt': session.get('created_at', 0),
                'deviceInfo': session.get('device_info', 'Unknown Device')
            })
    
    return jsonify(available_servers)

@app.route('/api/session', methods=['POST'])
def create_session():
    """Создать новую сессию"""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        'server_socket_id': None,
        'client_socket_id': None,
        'created_at': int(time.time() * 1000),
        'device_info': None
    }
    
    logger.info(f"Создана новая сессия: {session_id}")
    return jsonify({'sessionId': session_id})

@app.route('/health')
def health_check():
    """Проверка здоровья сервера"""
    return jsonify({
        'status': 'healthy',
        'timestamp': int(time.time() * 1000),
        'active_sessions': len(sessions)
    })

# WebSocket события
@socketio.on('connect')
def handle_connect():
    """Обработка подключения"""
    logger.info(f"Клиент подключен: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения"""
    logger.info(f"Клиент отключен: {request.sid}")
    
    # Очистка сессий
    session_id = server_sessions.get(request.sid)
    if session_id and session_id in sessions:
        session = sessions[session_id]
        
        if session.get('server_socket_id') == request.sid:
            # Отключился сервер
            session['server_socket_id'] = None
            if session.get('client_socket_id'):
                emit('server-disconnected', room=session['client_socket_id'])
            logger.info(f"Сервер отключен: {session_id}")
            
        elif session.get('client_socket_id') == request.sid:
            # Отключился клиент
            session['client_socket_id'] = None
            if session.get('server_socket_id'):
                emit('client-disconnected', room=session['server_socket_id'])
            logger.info(f"Клиент отключен: {session_id}")
        
        # Удаляем сессию если оба отключились
        if not session.get('server_socket_id') and not session.get('client_socket_id'):
            del sessions[session_id]
            logger.info(f"Сессия удалена: {session_id}")
    
    if session_id in server_sessions:
        del server_sessions[request.sid]

@socketio.on('register-server')
def handle_register_server(data):
    """Регистрация сервера"""
    session_id = data.get('sessionId')
    device_info = data.get('deviceInfo', 'Unknown Device')
    
    if not session_id or session_id not in sessions:
        emit('error', {'message': 'Неверный session ID'})
        return
    
    session = sessions[session_id]
    if session.get('server_socket_id'):
        emit('error', {'message': 'Сервер уже зарегистрирован для этой сессии'})
        return
    
    session['server_socket_id'] = request.sid
    session['device_info'] = device_info
    server_sessions[request.sid] = session_id
    
    logger.info(f"Сервер зарегистрирован: {session_id} ({request.sid})")
    emit('server-registered', {'sessionId': session_id})
    
    # Уведомляем всех о доступности сервера
    socketio.emit('server-available', {
        'sessionId': session_id,
        'deviceInfo': device_info,
        'createdAt': session['created_at']
    })

@socketio.on('connect-client')
def handle_connect_client(data):
    """Подключение клиента"""
    session_id = data.get('sessionId')
    
    if not session_id or session_id not in sessions:
        emit('error', {'message': 'Неверный session ID'})
        return
    
    session = sessions[session_id]
    if not session.get('server_socket_id'):
        emit('error', {'message': 'Сервер не доступен'})
        return
    
    if session.get('client_socket_id'):
        emit('error', {'message': 'Клиент уже подключен к этой сессии'})
        return
    
    session['client_socket_id'] = request.sid
    
    logger.info(f"Клиент подключен: {session_id} ({request.sid})")
    emit('client-connected', {'sessionId': session_id})
    emit('client-connected', {'clientId': request.sid}, room=session['server_socket_id'])
    
    # Уведомляем всех что сервер занят
    socketio.emit('server-busy', {'sessionId': session_id})

@socketio.on('server-data')
def handle_server_data(data):
    """Пересылка данных от сервера к клиенту"""
    session_id = server_sessions.get(request.sid)
    if not session_id or session_id not in sessions:
        return
    
    session = sessions[session_id]
    if session.get('client_socket_id'):
        emit('server-data', data, room=session['client_socket_id'])

@socketio.on('client-data')
def handle_client_data(data):
    """Пересылка данных от клиента к серверу"""
    session_id = server_sessions.get(request.sid)
    if not session_id or session_id not in sessions:
        return
    
    session = sessions[session_id]
    if session.get('server_socket_id'):
        emit('client-data', data, room=session['server_socket_id'])

@socketio.on('error')
def handle_error(data):
    """Обработка ошибок"""
    logger.error(f"Ошибка от клиента {request.sid}: {data}")

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 3000))
    logger.info(f"🚀 RemoteDroid Relay Server запущен на порту {port}")
    logger.info(f"🌐 Railway URL: https://web-production-f8e27.up.railway.app")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
