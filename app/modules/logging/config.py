# modules/logging/config.py
"""
Konfiguracja systemu logowania
"""

import os
from datetime import datetime

class LogConfig:
    """Centralna konfiguracja systemu logowania"""
    
    # Katalog logów
    LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
    
    # Retencja logów (w dniach)
    RETENTION_DAYS = 14
    
    # Rotacja logów
    ROTATION_TIME = 'midnight'  # Rotacja o północy
    ROTATION_INTERVAL = 1       # Co 1 dzień
    
    # Format nazwy pliku z datą
    LOG_FILENAME_PATTERN = 'app_{date}.log'
    
    # Format logu
    LOG_FORMAT = '[{timestamp}] [{level}] [{module}] [{user}] [{endpoint}] {message}'
    
    # Format timestampu
    TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'
    
    # Mapowanie kolorów dla tagów (dla panelu admin)
    LEVEL_COLORS = {
        'DEBUG': '#2196F3',    # Niebieski
        'INFO': '#4CAF50',     # Zielony  
        'WARNING': '#FF9800',  # Pomarańczowy
        'ERROR': '#F44336',    # Czerwony
        'CRITICAL': '#9C27B0'  # Fioletowy
    }
    
    @classmethod
    def get_log_filepath(cls, date=None):
        """Zwraca pełną ścieżkę do pliku logu dla podanej daty"""
        if date is None:
            date = datetime.now()
        
        date_str = date.strftime('%Y-%m-%d')
        filename = cls.LOG_FILENAME_PATTERN.format(date=date_str)
        return os.path.join(cls.LOG_DIR, filename)
    
    @classmethod
    def ensure_log_dir(cls):
        """Tworzy katalog logów jeśli nie istnieje"""
        os.makedirs(cls.LOG_DIR, exist_ok=True)