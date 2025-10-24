#!/usr/bin/env python3
"""
Enhanced Railway Server for AnyDesk-like functionality
Расширенный сервер для полноценного удаленного доступа
"""

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import time
import json
import logging
from datetime import datetime, timedelta
import threading
import redis
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'

# SocketIO для real-time коммуникации
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Redis для хранения данных (Railway предоставляет REDIS_URL)
try:
    redis_client = redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
    redis_client.ping()
    logger.info("Redis подключен успешно")
except:
    redis_client = None
    logger.warning("Redis недоступен, используем память")

# Хранилище данных
class DeviceRegistry:
    def __init__(self):
        self.devices = {}
        self.sessions = {}
        self.cleanup_thread = threading.Thread(target=self._cleanup_expired, daemon=True)
        self.cleanup_thread.start()
    
    def register_device(self, device_id, device_info):
        """Регистрация устройства"""
        self.devices[device_id] = {
            'id': device_id,
            'name': device_info.get('name', f'Device {device_id[:8]}'),
            'status': 'online',
            'last_seen': time.time(),
            'capabilities': device_info.get('capabilities', ['client']),
            'public_ip': device_info.get('public_ip'),
            'local_ip': device_info.get('local_ip'),
            'device_type': device_info.get('device_type', 'android'),
            'version': device_info.get('version', '1.0.0')
        }
        
        # Сохраняем в Redis если доступен
        if redis_client:
            redis_client.hset('devices', device_id, json.dumps(self.devices[device_id]))
        
        logger.info(f"Устройство зарегистрировано: {device_id}")
        return self.devices[device_id]
    
    def update_device_status(self, device_id, status='online'):
        """Обновить статус устройства"""
        if device_id in self.devices:
            self.devices[device_id]['status'] = status
            self.devices[device_id]['last_seen'] = time.time()
            
            if redis_client:
                redis_client.hset('devices', device_id, json.dumps(self.devices[device_id]))
    
    def get_available_servers(self):
        """Получить список доступных серверов"""
        servers = []
        for device_id, device_data in self.devices.items():
            if (device_data['status'] == 'online' and 
                'server' in device_data['capabilities'] and
                time.time() - device_data['last_seen'] < 300):  # 5 минут
                servers.append({
                    'id': device_id,
                    'name': device_data['name'],
                    'device_type': device_data['device_type'],
                    'last_seen': device_data['last_seen']
                })
        return servers
    
    def create_session(self, server_id, client_id):
        """Создать новую сессию"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            'id': session_id,
            'server_id': server_id,
            'client_id': client_id,
            'status': 'connecting',
            'created_at': time.time(),
            'last_activity': time.time()
        }
        
        if redis_client:
            redis_client.hset('sessions', session_id, json.dumps(self.sessions[session_id]))
        
        logger.info(f"Сессия создана: {session_id} между {server_id} и {client_id}")
        return session_id
    
    def update_session_status(self, session_id, status):
        """Обновить статус сессии"""
        if session_id in self.sessions:
            self.sessions[session_id]['status'] = status
            self.sessions[session_id]['last_activity'] = time.time()
            
            if redis_client:
                redis_client.hset('sessions', session_id, json.dumps(self.sessions[session_id]))
    
    def get_session(self, session_id):
        """Получить информацию о сессии"""
        return self.sessions.get(session_id)
    
    def _cleanup_expired(self):
        """Очистка устаревших данных"""
        while True:
            time.sleep(60)  # Каждую минуту
            current_time = time.time()
            
            # Очистка неактивных устройств
            expired_devices = [
                device_id for device_id, device_data in self.devices.items()
                if current_time - device_data['last_seen'] > 600  # 10 минут
            ]
            
            for device_id in expired_devices:
                del self.devices[device_id]
                if redis_client:
                    redis_client.hdel('devices', device_id)
                logger.info(f"Устройство удалено (неактивно): {device_id}")
            
            # Очистка завершенных сессий
            expired_sessions = [
                session_id for session_id, session_data in self.sessions.items()
                if current_time - session_data['last_activity'] > 3600  # 1 час
            ]
            
            for session_id in expired_sessions:
                del self.sessions[session_id]
                if redis_client:
                    redis_client.hdel('sessions', session_id)
                logger.info(f"Сессия удалена (завершена): {session_id}")

# Глобальный реестр устройств
device_registry = DeviceRegistry()

# WebRTC Signaling endpoints
@socketio.on('connect')
def handle_connect():
    """Обработка подключения клиента"""
    logger.info(f"Клиент подключился: {request.sid}")
    emit('connected', {'message': 'Подключено к серверу'})

@socketio.on('disconnect')
def handle_disconnect():
    """Обработка отключения клиента"""
    logger.info(f"Клиент отключился: {request.sid}")

@socketio.on('register_device')
def handle_device_registration(data):
    """Регистрация устройства"""
    device_id = data.get('device_id')
    if not device_id:
        emit('error', {'message': 'Device ID required'})
        return
    
    # Регистрируем устройство
    device_info = device_registry.register_device(device_id, data)
    
    # Присоединяем к комнате устройства
    join_room(f"device_{device_id}")
    
    emit('device_registered', {
        'device_id': device_id,
        'status': 'success',
        'message': 'Устройство зарегистрировано'
    })
    
    # Уведомляем о доступных серверах
    servers = device_registry.get_available_servers()
    emit('available_servers', {'servers': servers})

@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    """Обработка WebRTC offer"""
    session_id = data.get('session_id')
    target_device = data.get('target_device')
    
    if not session_id or not target_device:
        emit('error', {'message': 'Session ID and target device required'})
        return
    
    logger.info(f"WebRTC offer от {request.sid} к {target_device}")
    
    # Пересылаем offer целевому устройству
    emit('webrtc_offer', data, room=f"device_{target_device}")

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    """Обработка WebRTC answer"""
    session_id = data.get('session_id')
    target_device = data.get('target_device')
    
    if not session_id or not target_device:
        emit('error', {'message': 'Session ID and target device required'})
        return
    
    logger.info(f"WebRTC answer от {request.sid} к {target_device}")
    
    # Пересылаем answer целевому устройству
    emit('webrtc_answer', data, room=f"device_{target_device}")

@socketio.on('ice_candidate')
def handle_ice_candidate(data):
    """Обработка ICE candidate"""
    session_id = data.get('session_id')
    target_device = data.get('target_device')
    
    if not session_id or not target_device:
        emit('error', {'message': 'Session ID and target device required'})
        return
    
    logger.info(f"ICE candidate от {request.sid} к {target_device}")
    
    # Пересылаем ICE candidate целевому устройству
    emit('ice_candidate', data, room=f"device_{target_device}")

@socketio.on('session_started')
def handle_session_started(data):
    """Сессия началась"""
    session_id = data.get('session_id')
    if session_id:
        device_registry.update_session_status(session_id, 'active')
        emit('session_status_updated', {'session_id': session_id, 'status': 'active'})

@socketio.on('session_ended')
def handle_session_ended(data):
    """Сессия завершена"""
    session_id = data.get('session_id')
    if session_id:
        device_registry.update_session_status(session_id, 'ended')
        emit('session_status_updated', {'session_id': session_id, 'status': 'ended'})

# REST API endpoints (существующие)
@app.route('/')
def index():
    """Главная страница"""
    return """
    <h1>🚀 Remote Screen Control Server</h1>
    <p>Сервер работает на Railway!</p>
    
    <h2>📡 API Endpoints:</h2>
    <ul>
        <li><strong>POST</strong> /api/start_session - Запуск сессии</li>
        <li><strong>GET</strong> /api/session_status/&lt;token&gt; - Статус сессии</li>
        <li><strong>POST</strong> /api/stop_session - Остановка сессии</li>
        <li><strong>GET</strong> /api/devices - Список устройств</li>
        <li><strong>GET</strong> /api/servers - Доступные серверы</li>
    </ul>
    
    <h2>🔌 WebSocket Events:</h2>
    <ul>
        <li><strong>register_device</strong> - Регистрация устройства</li>
        <li><strong>webrtc_offer</strong> - WebRTC offer</li>
        <li><strong>webrtc_answer</strong> - WebRTC answer</li>
        <li><strong>ice_candidate</strong> - ICE candidate</li>
    </ul>
    
    <h2>🌐 WebRTC Configuration:</h2>
    <pre>
    STUN Servers:
    - stun:stun.l.google.com:19302
    - stun:stun.cloudflare.com:3478
    
    TURN Servers (рекомендуется):
    - turn:your-turn-server.com:3478
    </pre>
    """

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Получить список всех устройств"""
    devices = []
    for device_id, device_data in device_registry.devices.items():
        devices.append({
            'id': device_id,
            'name': device_data['name'],
            'status': device_data['status'],
            'capabilities': device_data['capabilities'],
            'last_seen': device_data['last_seen'],
            'device_type': device_data['device_type']
        })
    
    return jsonify({
        'devices': devices,
        'total': len(devices)
    })

@app.route('/api/servers', methods=['GET'])
def get_servers():
    """Получить список доступных серверов"""
    servers = device_registry.get_available_servers()
    return jsonify({
        'servers': servers,
        'total': len(servers)
    })

@app.route('/api/start_session', methods=['POST'])
def start_session():
    """Запуск новой сессии (существующий endpoint)"""
    data = request.json
    
    if not data or 'device_id' not in data:
        return jsonify({'error': 'Device ID required'}), 400
    
    device_id = data['device_id']
    device_type = data.get('device_type', 'client')
    
    # Регистрируем устройство если не зарегистрировано
    if device_id not in device_registry.devices:
        device_registry.register_device(device_id, data)
    
    # Обновляем статус
    device_registry.update_device_status(device_id, 'online')
    
    # Создаем сессию если это сервер
    session_id = None
    if device_type == 'server':
        session_id = device_registry.create_session(device_id, None)
    
    return jsonify({
        'status': 'success',
        'device_id': device_id,
        'session_id': session_id,
        'message': 'Сессия запущена'
    })

@app.route('/api/session_status/<token>', methods=['GET'])
def get_session_status(token):
    """Получить статус сессии (существующий endpoint)"""
    session = device_registry.get_session(token)
    
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify({
        'session_id': token,
        'status': session['status'],
        'server_id': session['server_id'],
        'client_id': session['client_id'],
        'created_at': session['created_at'],
        'last_activity': session['last_activity']
    })

@app.route('/api/stop_session', methods=['POST'])
def stop_session():
    """Остановка сессии"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Request body required'}), 400
    
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'error': 'session_id is required'}), 400
    
    session = device_registry.get_session(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    device_registry.update_session_status(session_id, 'ended')
    
    return jsonify({
        'status': 'success',
        'message': 'Сессия остановлена'
    })

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Проверка состояния сервера"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'devices_count': len(device_registry.devices),
        'sessions_count': len(device_registry.sessions),
        'redis_connected': redis_client is not None
    })

    @app.route('/api/health', methods=['GET'])
def api_health_check():
    """API Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'message': 'Server is running',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len([s for s in device_registry.sessions.values() if s['status'] == 'active']),
        'total_devices': len(device_registry.devices)
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Запуск сервера на порту {port}")
    
    # Запускаем сервер
socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
