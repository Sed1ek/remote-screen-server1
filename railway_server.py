from flask import Flask, request, jsonify
import json
import logging
import uuid
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Хранилище данных в памяти
devices = {}
sessions = {}

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'message': 'Server is running',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len([s for s in sessions.values() if s['status'] == 'active']),
        'total_devices': len(devices)
    })

@app.route('/api/start_session', methods=['POST'])
def start_session():
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'error': 'device_id is required'}), 400
        
        # Создаем сессию
        session_id = str(uuid.uuid4())
        sessions[session_id] = {
            'device_id': device_id,
            'status': 'active',
            'created_at': datetime.now().isoformat()
        }
        
        logger.info(f"Session {session_id} created for device {device_id}")
        
        return jsonify({
            'session_id': session_id,
            'status': 'active',
            'message': 'Session started successfully'
        })
        
    except Exception as e:
        logger.error(f"Error starting session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop_session', methods=['POST'])
def stop_session():
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400
        
        if session_id in sessions:
            sessions[session_id]['status'] = 'stopped'
            logger.info(f"Session {session_id} stopped")
            return jsonify({'message': 'Session stopped successfully'})
        else:
            return jsonify({'error': 'Session not found'}), 404
            
    except Exception as e:
        logger.error(f"Error stopping session: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/session_status', methods=['GET'])
def session_status():
    try:
        session_id = request.args.get('session_id')
        
        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400
        
        if session_id in sessions:
            return jsonify(sessions[session_id])
        else:
            return jsonify({'error': 'Session not found'}), 404
            
    except Exception as e:
        logger.error(f"Error getting session status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/servers', methods=['GET'])
def get_servers():
    try:
        # Возвращаем список активных сессий как серверов
        active_sessions = [
            {
                'device_id': session['device_id'],
                'session_id': session_id,
                'status': session['status'],
                'created_at': session['created_at']
            }
            for session_id, session in sessions.items()
            if session['status'] == 'active'
        ]
        
        return jsonify({
            'servers': active_sessions,
            'count': len(active_sessions)
        })
        
    except Exception as e:
        logger.error(f"Error getting servers: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting Railway server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
