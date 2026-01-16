# modules/logging/logger.py
"""
Główne klasy systemu logowania
"""

import logging
import logging.handlers
import os
import glob
import sys
from datetime import datetime, timedelta
from flask import request, session, has_request_context
from .config import LogConfig


class CustomFormatter(logging.Formatter):
    """Custom formatter z kontekstem Flask - POPRAWKA ENKODOWANIA"""
    
    def format(self, record):
        # Pobierz kontekst z Flask (jeśli dostępny)
        user = 'system'
        endpoint = '-'
        
        if has_request_context():
            try:
                # Pobierz użytkownika z sesji
                if session and 'user_email' in session:
                    user = session['user_email']
                
                # Pobierz endpoint
                if request and request.endpoint:
                    endpoint = request.endpoint
                elif request and request.path:
                    endpoint = request.path
                    
            except RuntimeError:
                # Poza kontekstem aplikacji
                pass
        
        # Pobierz nazwę modułu z logger name
        module = record.name
        if module.startswith('app.'):
            module = module[4:]  # Usuń prefiks 'app.'
        
        # Formatuj timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime(LogConfig.TIMESTAMP_FORMAT)
        
        # POPRAWKA: Bezpieczne formatowanie message
        try:
            message = record.getMessage()
            # Zachowaj polskie znaki w miarę możliwości
            safe_message = message.encode('utf-8', errors='replace').decode('utf-8')
        except Exception as e:
            safe_message = f"<message_encoding_error: {type(record.msg).__name__}>"
        
        # Buduj sformatowany komunikat - BEZPIECZNIE
        try:
            formatted_message = LogConfig.LOG_FORMAT.format(
                timestamp=timestamp,
                level=record.levelname,
                module=module,
                user=user,
                endpoint=endpoint,
                message=safe_message
            )
        except Exception as e:
            # Fallback format
            formatted_message = f"[{timestamp}] [{record.levelname}] [{module}] <formatting_error>"
        
        return formatted_message

class TimedRotatingFileHandlerWithCleanup(logging.handlers.TimedRotatingFileHandler):
    """Handler z automatycznym czyszczeniem starych logów"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cleanup_old_logs()
    
    def doRollover(self):
        """Override rollover aby dodać cleanup"""
        super().doRollover()
        self.cleanup_old_logs()
    
    def cleanup_old_logs(self):
        """Usuwa logi starsze niż RETENTION_DAYS"""
        try:
            cutoff_date = datetime.now() - timedelta(days=LogConfig.RETENTION_DAYS)
            pattern = os.path.join(LogConfig.LOG_DIR, 'app_*.log')
            
            for log_file in glob.glob(pattern):
                try:
                    # Wyciągnij datę z nazwy pliku
                    filename = os.path.basename(log_file)
                    if filename.startswith('app_') and filename.endswith('.log'):
                        date_str = filename[4:-4]  # Usuń 'app_' i '.log'
                        file_date = datetime.strptime(date_str, '%Y-%m-%d')
                        
                        if file_date < cutoff_date:
                            os.remove(log_file)
                            print(f"[LogCleanup] Usunięto stary log: {log_file}")
                            
                except (ValueError, OSError) as e:
                    print(f"[LogCleanup] Błąd podczas usuwania {log_file}: {e}")
                    
        except Exception as e:
            print(f"[LogCleanup] Błąd podczas czyszczenia logów: {e}")

class AppLogger:
    """Główna klasa systemu logowania"""
    
    _instance = None
    _configured = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def setup(cls):
        """Konfiguruje system logowania dla całej aplikacji - POPRAWKA ENKODOWANIA"""
        if cls._configured:
            return
        
        # POPRAWKA: Ustaw kodowanie dla całego środowiska Python
        try:
            # Upewnij się, że stdout i stderr używają UTF-8
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')

            # Ustaw zmienne środowiskowe dla kodowania
            os.environ['PYTHONIOENCODING'] = 'utf-8:replace'

        except BrokenPipeError as e:
            try:
                sys.stderr.write(f"[Logger] Broken pipe while setting UTF-8: {e}\n")
            except Exception:
                pass
        except UnicodeEncodeError as e:
            # Upewnij się, że komunikat nie powoduje kolejnego wyjątku
            try:
                sys.stderr.write("[Logger] Unicode encode error while setting UTF-8\n")
            except Exception:
                pass
        except Exception as e:
            try:
                sys.stderr.write(f"[Logger] Unable to set UTF-8 encoding: {e}\n")
            except Exception:
                pass
        
        # Upewnij się, że katalog logów istnieje
        LogConfig.ensure_log_dir()
        
        # Pobierz root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Usuń istniejące handlery
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Utwórz handler z rotacją dzienną - Z BEZPIECZNYM ENCODING
        log_file = LogConfig.get_log_filepath()
        try:
            handler = TimedRotatingFileHandlerWithCleanup(
                filename=log_file,
                when=LogConfig.ROTATION_TIME,
                interval=LogConfig.ROTATION_INTERVAL,
                backupCount=LogConfig.RETENTION_DAYS,
                encoding='utf-8',
                errors='replace'  # POPRAWKA: Dodane errors='replace'
            )
        except Exception as e:
            # Fallback - handler bez encoding
            print(f"[Logger] Nie można utworzyć file handler z UTF-8: {e}")
            handler = TimedRotatingFileHandlerWithCleanup(
                filename=log_file,
                when=LogConfig.ROTATION_TIME,
                interval=LogConfig.ROTATION_INTERVAL,
                backupCount=LogConfig.RETENTION_DAYS
            )
        
        # Ustaw formatter
        formatter = CustomFormatter()
        handler.setFormatter(formatter)
        
        # Dodaj handler do root loggera
        root_logger.addHandler(handler)
        
        # POPRAWKA: Console handler z bezpiecznym encoding + fallback
        try:
            # Sprawdź czy stderr/stdout są dostępne
            if hasattr(sys.stderr, 'write') and not sys.stderr.closed:
                console_stream = sys.stderr
            elif hasattr(sys.stdout, 'write') and not sys.stdout.closed:
                console_stream = sys.stdout
            else:
                # Brak dostępnego stream - pomiń console handler
                raise OSError("No available console stream")
            
            # Spróbuj utworzyć console handler
            console_handler = logging.StreamHandler(stream=console_stream)
            console_handler.setFormatter(formatter)
            console_handler.setLevel(logging.INFO)
            
            # Test czy console handler działa z polskimi znakami
            test_message = "Test polskich znakow: ąćęłńóśźż"
            test_record = logging.LogRecord(
                name='test', level=logging.INFO, pathname='', lineno=0,
                msg=test_message, args=(), exc_info=None
            )
            
            try:
                # Spróbuj sformatować i zapisać testową wiadomość
                formatted = formatter.format(test_record)
                console_handler.stream.write(formatted + '\n')
                console_handler.stream.flush()
                
                # Jeśli się udało, dodaj handler
                root_logger.addHandler(console_handler)
                print("[Logger] Console handler z UTF-8 działa poprawnie")
                
            except (UnicodeEncodeError, BrokenPipeError, OSError):
                # Console nie obsługuje UTF-8 lub jest zamknięty
                print("[Logger] Console nie obsługuje UTF-8 lub jest zamknięty - wyłączono console logging")
                
        except (OSError, BrokenPipeError, AttributeError) as e:
            # Console stream niedostępny - logowanie tylko do pliku
            print(f"[Logger] Nie można utworzyć console handler: {e}")
            print("[Logger] Logowanie tylko do pliku - sprawdź logi w logs/app_*.log")
        
        cls._configured = True
        
        # Log pierwszej wiadomości - BEZPIECZNIE
        try:
            logger = logging.getLogger('app.logging')
            logger.info("System logowania uruchomiony")
        except Exception as e:
            print(f"[Logger] Błąd pierwszego loga: {e}")
    
    @classmethod
    def get_logger(cls, module_name):
        """Zwraca logger dla konkretnego modułu"""
        if not cls._configured:
            cls.setup()
        
        return logging.getLogger(f'app.{module_name}')

# Pomocnicza funkcja dla łatwego dostępu
def get_logger(module_name):
    """
    Pobiera logger dla modułu
    
    Args:
        module_name (str): Nazwa modułu (np. 'baselinker.service')
    
    Returns:
        logging.Logger: Skonfigurowany logger
    """
    return AppLogger.get_logger(module_name)