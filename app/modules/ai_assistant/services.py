"""
Serwis integracji z Google Gemini API
Z automatycznym fallbackiem między modelami przy przekroczeniu limitów
"""

import re
import traceback
import requests
from flask import current_app


class GeminiService:
    """Serwis do komunikacji z Google Gemini API"""

    # Lista modeli do użycia (w kolejności priorytetu)
    # Jeśli jeden ma limit, próbujemy kolejnego
    MODELS = [
        "gemini-2.5-flash",       # Główny model - najlepszy
        "gemini-2.5-flash-lite",  # Lżejszy, ale wciąż dobry
        "gemini-2.0-flash",       # Starszy, ale unlimited
    ]

    API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self):
        current_app.logger.debug("[GeminiService] Inicjalizacja...")
        self.api_key = self._get_api_key()

        # Lazy import knowledge_base i system_prompt
        try:
            from .knowledge_base import KnowledgeBase
            self.knowledge_base = KnowledgeBase()
            current_app.logger.debug("[GeminiService] KnowledgeBase załadowany")
        except Exception as e:
            current_app.logger.error(f"[GeminiService] Błąd ładowania KnowledgeBase: {e}")
            current_app.logger.error(traceback.format_exc())
            self.knowledge_base = None

    def _get_api_key(self) -> str:
        """Pobiera klucz API z konfiguracji"""
        config = current_app.config.get('AI_ASSISTANT', {})
        api_key = config.get('api_key', '')

        if not api_key:
            current_app.logger.warning("[GeminiService] Brak klucza API w konfiguracji!")
        elif api_key == 'TUTAJ_WKLEJ_KLUCZ_API_GEMINI':
            current_app.logger.warning("[GeminiService] Klucz API nie został zmieniony - używa placeholdera!")
            return ''
        else:
            current_app.logger.debug(f"[GeminiService] Klucz API znaleziony (długość: {len(api_key)})")

        return api_key

    def is_configured(self) -> bool:
        """Sprawdza czy API jest skonfigurowane"""
        return bool(self.api_key)

    def chat(self, user_message: str, history: list = None) -> dict:
        """
        Wysyła wiadomość do Gemini i zwraca odpowiedź.
        Automatycznie przełącza się między modelami przy przekroczeniu limitów.

        Args:
            user_message: Wiadomość użytkownika
            history: Historia rozmowy (opcjonalna)

        Returns:
            dict z kluczami 'success' i 'response' lub 'error'
        """
        current_app.logger.info(f"[GeminiService] chat() wywołane z wiadomością: {user_message[:50]}...")

        if not self.is_configured():
            current_app.logger.error("[GeminiService] API nie jest skonfigurowane!")
            return {
                'success': False,
                'error': 'API nie jest skonfigurowane. Wklej klucz API Gemini w config/core.json'
            }

        try:
            # Budowanie kontekstu
            from .system_prompt import get_system_prompt
            system_prompt = get_system_prompt()

            if self.knowledge_base:
                knowledge_context = self.knowledge_base.get_relevant_context(user_message)
            else:
                knowledge_context = "Brak bazy wiedzy"
                current_app.logger.warning("[GeminiService] KnowledgeBase niedostępny")

            # Budowanie zawartości rozmowy
            contents = self._build_contents(system_prompt, knowledge_context, history, user_message)

            # Próbuj kolejne modele
            last_error = None
            for model in self.MODELS:
                result = self._call_model(model, contents)

                if result['success']:
                    return result

                # Sprawdź czy to błąd limitu - wtedy próbuj następny model
                if result.get('is_rate_limit'):
                    current_app.logger.warning(f"[GeminiService] Model {model} ma limit, próbuję następny...")
                    last_error = result
                    continue
                else:
                    # Inny błąd - nie próbuj kolejnych modeli
                    return result

            # Wszystkie modele mają limit
            current_app.logger.error("[GeminiService] Wszystkie modele osiągnęły limit!")
            if last_error:
                return {
                    'success': False,
                    'error': 'Wszystkie modele AI osiągnęły limit zapytań. Spróbuj ponownie za kilka minut.',
                    'retry_after': last_error.get('retry_after', 60)
                }

            return {
                'success': False,
                'error': 'Nie udało się uzyskać odpowiedzi od AI'
            }

        except Exception as e:
            current_app.logger.error(f"[GeminiService] Unexpected error: {str(e)}")
            current_app.logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': f'Nieoczekiwany błąd: {str(e)}'
            }

    def _call_model(self, model: str, contents: list) -> dict:
        """Wywołuje konkretny model Gemini"""
        url = f"{self.API_BASE_URL}/{model}:generateContent?key={self.api_key}"

        request_body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,  # Zwiększone - mamy dużo TPM
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
            ]
        }

        current_app.logger.info(f"[GeminiService] Wysyłam request do modelu: {model}")

        try:
            response = requests.post(url, json=request_body, timeout=30)
            current_app.logger.info(f"[GeminiService] {model} - Response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                if 'candidates' in data and len(data['candidates']) > 0:
                    candidate = data['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        ai_response = candidate['content']['parts'][0].get('text', '')
                        current_app.logger.info(f"[GeminiService] Sukces z modelem: {model}")
                        return {
                            'success': True,
                            'response': ai_response,
                            'model': model
                        }

                return {
                    'success': False,
                    'error': 'Nie udało się uzyskać odpowiedzi od AI'
                }

            else:
                # Obsługa błędów
                error_msg = f"Błąd API: {response.status_code}"
                is_rate_limit = False
                retry_seconds = None

                try:
                    error_data = response.json()
                    current_app.logger.error(f"[GeminiService] {model} Error: {error_data}")

                    if 'error' in error_data:
                        error_msg = error_data['error'].get('message', error_msg)

                        # Sprawdź czy to błąd limitu
                        if response.status_code == 429 or 'quota' in error_msg.lower() or 'rate' in error_msg.lower():
                            is_rate_limit = True

                            # Wyciągnij czas retry
                            retry_match = re.search(r'retry in (\d+(?:\.\d+)?)\s*s', error_msg)
                            if retry_match:
                                retry_seconds = int(float(retry_match.group(1))) + 1
                            else:
                                retry_seconds = 60

                except Exception:
                    pass

                return {
                    'success': False,
                    'error': error_msg,
                    'is_rate_limit': is_rate_limit,
                    'retry_after': retry_seconds
                }

        except requests.exceptions.Timeout:
            current_app.logger.error(f"[GeminiService] {model} Timeout!")
            return {
                'success': False,
                'error': 'Przekroczono czas oczekiwania na odpowiedź (30s).'
            }
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"[GeminiService] {model} Request error: {str(e)}")
            return {
                'success': False,
                'error': f'Problem z połączeniem: {str(e)}'
            }

    def _build_contents(self, system_prompt: str, knowledge_context: str, history: list, user_message: str) -> list:
        """Buduje strukturę contents dla API Gemini"""
        contents = []

        # System prompt jako pierwsza wiadomość "użytkownika" (Gemini nie ma dedykowanego system prompt)
        full_system = f"{system_prompt}\n\n### Wiedza kontekstowa:\n{knowledge_context}"

        contents.append({
            "role": "user",
            "parts": [{"text": f"[INSTRUKCJE SYSTEMOWE - NIE ODPOWIADAJ NA TO, TO SĄ TWOJE WYTYCZNE]\n\n{full_system}\n\n[KONIEC INSTRUKCJI SYSTEMOWYCH]"}]
        })

        contents.append({
            "role": "model",
            "parts": [{"text": "Rozumiem. Jestem asystentem WoodPower CRM i będę odpowiadał tylko na pytania związane z produktami, zamówieniami i systemem CRM. Jak mogę pomóc?"}]
        })

        # Historia rozmowy
        if history:
            for msg in history[-10:]:  # Ostatnie 10 wiadomości
                role = "user" if msg.get('role') == 'user' else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.get('content', '')}]
                })

        # Aktualna wiadomość użytkownika
        contents.append({
            "role": "user",
            "parts": [{"text": user_message}]
        })

        return contents
