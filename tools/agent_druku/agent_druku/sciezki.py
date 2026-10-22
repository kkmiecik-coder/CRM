"""Ścieżki danych agenta druku (konfiguracja, dziennik)."""
import os
import time
from pathlib import Path


def katalog_danych() -> Path:
    """%ProgramData%\\WoodPower\\AgentDruku; w testach podmieniany (monkeypatch)."""
    baza = os.environ.get('ProgramData') or os.environ.get('PROGRAMDATA') or r'C:\ProgramData'
    return Path(baza) / 'WoodPower' / 'AgentDruku'


def plik_konfiguracji() -> Path:
    return katalog_danych() / 'konfiguracja.json'


def plik_dziennika() -> Path:
    return katalog_danych() / 'dziennik.db'


def plik_klucza_lokalnego() -> Path:
    """Klucz lokalnego API (nagłówek X-Klucz) — usługa i zasobnik czytają ten sam plik."""
    return katalog_danych() / 'klucz_lokalny'


def plik_adresu_crm() -> Path:
    """Adres CRM przypięty przez instalator (/CRM=...). Usługa łączy się tylko z nim; zmiana
    serwera wymaga ponownej instalacji. Plik chroni ACL katalogu danych (SYSTEM i Administratorzy)."""
    return katalog_danych() / 'crm_url.txt'


def plik_logu() -> Path:
    return katalog_danych() / 'logi' / 'agent_druku.log'


def odloz_uszkodzony(plik):
    """Przenosi uszkodzony plik danych na bok (`<nazwa>.uszkodzony-<rrrrmmdd-ggmmss>`), żeby usługa wstała
    z pustym stanem zamiast padać w pętli restartów, a plik został do obejrzenia. Zwraca nową ścieżkę albo
    None, gdy przeniesienie się nie udało (wtedy wołający i tak zaczyna od pustego stanu)."""
    plik = Path(plik)
    cel = plik.with_name('%s.uszkodzony-%s' % (plik.name, time.strftime('%Y%m%d-%H%M%S')))
    try:
        os.replace(plik, cel)
    except OSError:
        return None
    return cel
