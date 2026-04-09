"""
Status Emitter dla AI Assistant
Umożliwia wysyłanie statusów przetwarzania przez Server-Sent Events (SSE)
"""

import random
import queue
import threading
from typing import Optional, Callable
from flask import current_app


# Słownik statusów z wariantami tekstowymi
AI_STATUS_MESSAGES = {
    'analyzing': [
        'Analizuję pytanie...',
        'Przetwarzam zapytanie...',
        'Zastanawiam się...',
    ],
    'knowledge_base': [
        'Przeszukuję bazę wiedzy...',
        'Szukam informacji...',
        'Sprawdzam w dokumentacji...',
    ],
    'baselinker': [
        'Pobieram dane z Baselinker...',
        'Łączę się z Baselinker...',
        'Sprawdzam zamówienie w Baselinker...',
    ],
    'crm_quotes': [
        'Sprawdzam wyceny w CRM...',
        'Szukam wycen...',
        'Pobieram dane wycen...',
    ],
    'crm_clients': [
        'Szukam danych klienta...',
        'Sprawdzam bazę klientów...',
        'Pobieram informacje o kliencie...',
    ],
    'prestashop': [
        'Szukam produktów w sklepie...',
        'Przeszukuję katalog produktów...',
        'Sprawdzam dostępność w sklepie...',
    ],
    'generating': [
        'Generuję odpowiedź...',
        'Przygotowuję odpowiedź...',
        'Składam odpowiedź...',
    ],
    'groq_fallback': [
        'Przełączam na zapasowy model AI...',
        'Używam alternatywnego modelu...',
        'Łączę z zapasowym AI...',
    ],
}


def get_status_message(status_key: str) -> str:
    """
    Zwraca losowy wariant tekstu dla danego statusu.

    Args:
        status_key: Klucz statusu (np. 'analyzing', 'baselinker')

    Returns:
        Losowy tekst statusu
    """
    messages = AI_STATUS_MESSAGES.get(status_key, ['Przetwarzam...'])
    return random.choice(messages)


class StatusEmitter:
    """
    Klasa do emitowania statusów przetwarzania AI.
    Wykorzystuje kolejkę do komunikacji między wątkami.
    """

    # Przechowuje aktywne emitery per request_id
    _emitters = {}
    _lock = threading.Lock()

    def __init__(self, request_id: str):
        """
        Inicjalizuje emitter dla konkretnego requestu.

        Args:
            request_id: Unikalny identyfikator requestu
        """
        self.request_id = request_id
        self.queue = queue.Queue()
        self._is_active = True

        # Zarejestruj emitter
        with StatusEmitter._lock:
            StatusEmitter._emitters[request_id] = self

    @classmethod
    def get_emitter(cls, request_id: str) -> Optional['StatusEmitter']:
        """Pobiera emitter dla danego request_id"""
        with cls._lock:
            return cls._emitters.get(request_id)

    @classmethod
    def remove_emitter(cls, request_id: str):
        """Usuwa emitter z rejestru"""
        with cls._lock:
            if request_id in cls._emitters:
                cls._emitters[request_id]._is_active = False
                del cls._emitters[request_id]

    def emit(self, status_key: str, custom_message: Optional[str] = None):
        """
        Emituje status do kolejki.

        Args:
            status_key: Klucz statusu (np. 'analyzing')
            custom_message: Opcjonalny własny tekst (zamiast losowego)
        """
        if not self._is_active:
            return

        message = custom_message or get_status_message(status_key)

        try:
            self.queue.put_nowait({
                'type': 'status',
                'status': status_key,
                'message': message
            })
        except queue.Full:
            pass  # Ignoruj jeśli kolejka pełna

    def emit_complete(self, response: str):
        """
        Emituje końcową odpowiedź AI.

        Args:
            response: Treść odpowiedzi AI
        """
        if not self._is_active:
            return

        try:
            self.queue.put_nowait({
                'type': 'complete',
                'response': response
            })
        except queue.Full:
            pass

    def emit_error(self, error: str, retry_after: Optional[int] = None):
        """
        Emituje błąd.

        Args:
            error: Treść błędu
            retry_after: Opcjonalny czas retry w sekundach
        """
        if not self._is_active:
            return

        data = {
            'type': 'error',
            'error': error
        }
        if retry_after:
            data['retry_after'] = retry_after

        try:
            self.queue.put_nowait(data)
        except queue.Full:
            pass

    def get_event(self, timeout: float = 30.0) -> Optional[dict]:
        """
        Pobiera następne zdarzenie z kolejki.

        Args:
            timeout: Timeout w sekundach

        Returns:
            Słownik z danymi zdarzenia lub None
        """
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        """Zamyka emitter"""
        self._is_active = False
        StatusEmitter.remove_emitter(self.request_id)


# Thread-local storage dla aktualnego emittera
_current_emitter = threading.local()


def set_current_emitter(emitter: Optional[StatusEmitter]):
    """Ustawia aktualny emitter dla bieżącego wątku"""
    _current_emitter.emitter = emitter


def get_current_emitter() -> Optional[StatusEmitter]:
    """Pobiera aktualny emitter dla bieżącego wątku"""
    return getattr(_current_emitter, 'emitter', None)


def emit_status(status_key: str, custom_message: Optional[str] = None):
    """
    Funkcja pomocnicza do emitowania statusu z dowolnego miejsca w kodzie.

    Args:
        status_key: Klucz statusu
        custom_message: Opcjonalny własny tekst
    """
    emitter = get_current_emitter()
    if emitter:
        emitter.emit(status_key, custom_message)
