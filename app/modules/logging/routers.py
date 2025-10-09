# modules/logging/routers.py
"""
Endpointy API dla panelu administracyjnego logów
"""

import os
import glob
from datetime import datetime
from flask import Blueprint, jsonify, request
from .config import LogConfig

logging_bp = Blueprint('logging', __name__)


@logging_bp.route('/api/logs/files')
def list_log_files():
    """Zwraca listę dostępnych plików logów"""
    try:
        LogConfig.ensure_log_dir()
        pattern = os.path.join(LogConfig.LOG_DIR, 'app_*.log')
        files = []
        
        for filepath in sorted(glob.glob(pattern), reverse=True):
            filename = os.path.basename(filepath)
            
            # Wyciągnij datę z nazwy pliku
            if filename.startswith('app_') and filename.endswith('.log'):
                date_str = filename[4:-4]
                try:
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    file_size = os.path.getsize(filepath)
                    
                    files.append({
                        'filename': filename,
                        'date': date_str,
                        'formatted_date': file_date.strftime('%d.%m.%Y'),
                        'size': file_size,
                        'size_mb': round(file_size / 1024 / 1024, 2)
                    })
                except ValueError:
                    continue
        
        return jsonify({
            'success': True,
            'files': files
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@logging_bp.route('/api/logs/read/<filename>')
def read_log_file(filename):
    """Zwraca zawartość pliku logu (ostatnie 250 linii)"""
    try:
        # Sprawdź bezpieczeństwo nazwy pliku
        if not filename.startswith('app_') or not filename.endswith('.log'):
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowa nazwa pliku'
            }), 400
        
        filepath = os.path.join(LogConfig.LOG_DIR, filename)
        
        if not os.path.exists(filepath):
            return jsonify({
                'success': False,
                'error': 'Plik nie istnieje'
            }), 404
        
        # Przeczytaj ostatnie 250 linii
        lines = []
        with open(filepath, 'r', encoding='utf-8') as f:
            # Czytaj plik od końca
            lines = f.readlines()
            
        # Weź ostatnie 250 linii
        last_lines = lines[-250:] if len(lines) > 250 else lines
        
        return jsonify({
            'success': True,
            'content': ''.join(last_lines),
            'lines_count': len(last_lines),
            'total_lines': len(lines)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@logging_bp.route('/api/logs/current')
def get_current_log():
    """Zwraca aktualne logi (dla real-time refresh)"""
    try:
        # Pobierz dzisiejszy plik logu
        today_file = os.path.basename(LogConfig.get_log_filepath())
        return read_log_file(today_file)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500