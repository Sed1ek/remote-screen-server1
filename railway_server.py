#!/usr/bin/env python3
"""
Максимально простой сервер для Railway
"""

from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route('/api/start_session', methods=['POST'])
def start_session():
    """Создать новую сессию - всегда успех"""
    print("=== START SESSION REQUEST ===")
    print("Raw data:", request.get_data())
    
    # Всегда возвращаем успех
    return jsonify({
        'status': 'success',
        'token': 'working_token_123',
        'message': 'Session created successfully'
    })

@app.route('/api/session_status/<token>')
def session_status(token):
    """Проверить статус сессии - всегда активна"""
    print(f"=== SESSION STATUS REQUEST: {token} ===")
    return jsonify({
        'active': True,
        'token': token,
        'message': 'Session is active'
    })

@app.route('/api/stop_session', methods=['POST'])
def stop_session():
    """Остановить сессию - всегда успех"""
    print("=== STOP SESSION REQUEST ===")
    return jsonify({
        'status': 'success',
        'message': 'Session stopped'
    })

@app.route('/')
def index():
    return """
    <h1>Remote Screen Control Server</h1>
    <p>Сервер работает на Railway!</p>
    <p>API endpoints:</p>
    <ul>
        <li>POST /api/start_session</li>
        <li>GET /api/session_status/&lt;token&gt;</li>
        <li>POST /api/stop_session</li>
    </ul>
    """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
