#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
On Line Messenger - Desktop App
Запускает Flask сервер и открывает браузер
"""

import os
import sys
import threading
import webbrowser
import socket
import time

# Добавляем путь к папке с проектом
base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, base_path)

# Устанавливаем переменные окружения
os.environ['FLASK_ENV'] = 'production'
os.environ['FLASK_DEBUG'] = '0'

# Импортируем приложение
from messenger_web import app, socketio

def find_free_port():
    """Находит свободный порт"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

def open_browser(port):
    """Открывает браузер через пару секунд"""
    time.sleep(2)
    webbrowser.open(f'http://localhost:{port}')

if __name__ == '__main__':
    # Находим свободный порт
    port = find_free_port()
    
    # Открываем браузер в отдельном потоке
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║     🟢 ON LINE MESSENGER - Desktop Application 🟢       ║
    ╠══════════════════════════════════════════════════════════╣
    ║  Сервер запущен на: http://localhost:{port}              ║
    ║  Для закрытия приложения нажмите Ctrl+C                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # Запускаем сервер
    socketio.run(app, debug=False, host='127.0.0.1', port=port)