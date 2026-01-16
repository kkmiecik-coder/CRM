#!/usr/bin/env python3
"""
Scheduler Daemon - Osobny proces dla APScheduler
Pozwala na uruchomienie schedulera niezależnie od aplikacji webowej
"""

import os
import sys
import signal
import time
import threading
from datetime import datetime

# Dodaj katalog aplikacji do ścieżki
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)

# Aktywuj virtualenv jeśli potrzeba
activate_this = '/home/woodpower/virtualenv/domains/crm.woodpower.pl/public_html/3.9/bin/activate_this.py'
if os.path.exists(activate_this):
    print(f"[Daemon] Aktywacja virtualenv...")
    exec(open(activate_this).read(), {'__file__': activate_this})

# Import aplikacji Flask
from app import create_app
from modules.scheduler.scheduler_service import init_scheduler, shutdown_scheduler, scheduler

# Globalne zmienne
daemon_running = True
app = None

def signal_handler(signum, frame):
    """Handler dla sygnałów zamknięcia"""
    global daemon_running
    print(f"\n[Daemon] Otrzymano sygnał {signum} - zamykanie...")
    daemon_running = False
    
    if scheduler and scheduler.running:
        print("[Daemon] Zamykanie schedulera...")
        shutdown_scheduler()
    
    print("[Daemon] Daemon zamknięty pomyślnie")
    sys.exit(0)

def setup_signal_handlers():
    """Konfiguracja obsługi sygnałów"""
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Systemowe zamknięcie
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)  # Restart

def initialize_daemon():
    """Inicjalizacja daemona schedulera"""
    global app
    
    print(f"[Daemon] Uruchamianie Scheduler Daemon - PID: {os.getpid()}")
    print(f"[Daemon] Czas uruchomienia: {datetime.now()}")
    
    try:
        # Utwórz kontekst aplikacji Flask
        app = create_app()
        
        with app.app_context():
            print("[Daemon] Inicjalizacja schedulera...")
            init_scheduler(app)
            
            if scheduler and scheduler.running:
                print("[Daemon] ✅ Scheduler uruchomiony pomyślnie")
                return True
            else:
                print("[Daemon] ❌ Nie udało się uruchomić schedulera")
                return False
                
    except Exception as e:
        print(f"[Daemon] ❌ Błąd inicjalizacji: {e}")
        import traceback
        traceback.print_exc()
        return False

def health_check():
    """Sprawdza stan schedulera"""
    if scheduler:
        jobs_count = len(scheduler.get_jobs()) if scheduler.running else 0
        status = "RUNNING" if scheduler.running else "STOPPED"
        print(f"[Daemon] Health check - Status: {status}, Jobs: {jobs_count}")
        return scheduler.running
    return False

def daemon_loop():
    """Główna pętla daemona"""
    global daemon_running
    
    print("[Daemon] Rozpoczęcie głównej pętli...")
    last_health_check = time.time()
    
    while daemon_running:
        try:
            current_time = time.time()
            
            # Health check co 5 minut
            if current_time - last_health_check > 300:  # 300 sekund = 5 minut
                with app.app_context():
                    if not health_check():
                        print("[Daemon] ⚠️ Scheduler nie działa - próba restartu...")
                        try:
                            init_scheduler(app)
                        except Exception as e:
                            print(f"[Daemon] ❌ Restart schedulera nieudany: {e}")
                
                last_health_check = current_time
            
            # Krótka przerwa żeby nie obciążać CPU
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\n[Daemon] Przerwano przez użytkownika")
            break
        except Exception as e:
            print(f"[Daemon] ❌ Błąd w głównej pętli: {e}")
            time.sleep(30)  # Dłuższa pauza po błędzie

def main():
    """Główna funkcja daemona"""
    print("="*60)
    print("          SCHEDULER DAEMON - CRM WOODPOWER")
    print("="*60)
    
    # Konfiguracja sygnałów
    setup_signal_handlers()
    
    # Inicjalizacja
    if not initialize_daemon():
        print("[Daemon] ❌ Inicjalizacja nieudana - zakończenie")
        sys.exit(1)
    
    print("[Daemon] 🚀 Daemon uruchomiony pomyślnie")
    print("[Daemon] Użyj Ctrl+C aby zatrzymać")
    print("-"*60)
    
    try:
        # Główna pętla
        daemon_loop()
        
    except Exception as e:
        print(f"[Daemon] ❌ Niespodziewany błąd: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Cleanup
        if scheduler and scheduler.running:
            print("[Daemon] Finalne zamknięcie schedulera...")
            shutdown_scheduler()
        
        print("[Daemon] Daemon zakończony")

if __name__ == "__main__":
    main()