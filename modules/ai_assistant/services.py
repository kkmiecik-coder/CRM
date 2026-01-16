"""
Serwis integracji z Google Gemini API
Z automatycznym fallbackiem między modelami przy przekroczeniu limitów
oraz fallbackiem do Groq jako ostateczna opcja
"""

import re
import traceback
import requests
from flask import current_app

from .status_emitter import emit_status, get_current_emitter


class GeminiService:
    """Serwis do komunikacji z Google Gemini API z fallbackiem do Groq"""

    # Lista modeli Gemini do użycia (w kolejności priorytetu)
    # Jeśli jeden ma limit, próbujemy kolejnego
    GEMINI_MODELS = [
        "gemini-2.5-flash",       # Główny model - najlepszy
        "gemini-2.5-flash-lite",  # Lżejszy, ale wciąż dobry
        "gemini-2.0-flash",       # Starszy, stabilny
        "gemini-1.5-flash",       # Jeszcze starszy, ale niezawodny
        "gemini-1.5-pro",         # Mocniejszy, jako ostateczny fallback
    ]

    # Groq - modele do fallbacku (darmowe, szybkie)
    GROQ_MODELS = [
        "llama-3.3-70b-versatile",              # Najlepszy model tekstowy
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Llama 4 Scout - najnowszy
        "llama-3.1-8b-instant",                 # Szybszy, mniejszy
    ]

    GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    GROQ_API_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        current_app.logger.debug("[GeminiService] Inicjalizacja...")
        self.api_key = self._get_api_key()
        self.groq_api_key = self._get_groq_api_key()

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
        """Pobiera klucz API Gemini z konfiguracji"""
        config = current_app.config.get('AI_ASSISTANT', {})
        api_key = config.get('api_key', '')

        if not api_key:
            current_app.logger.warning("[GeminiService] Brak klucza API Gemini w konfiguracji!")
        elif api_key == 'TUTAJ_WKLEJ_KLUCZ_API_GEMINI':
            current_app.logger.warning("[GeminiService] Klucz API Gemini nie został zmieniony - używa placeholdera!")
            return ''
        else:
            current_app.logger.debug(f"[GeminiService] Klucz API Gemini znaleziony (długość: {len(api_key)})")

        return api_key

    def _get_groq_api_key(self) -> str:
        """Pobiera klucz API Groq z konfiguracji"""
        config = current_app.config.get('AI_ASSISTANT', {})
        api_key = config.get('groq_api_key', '')

        if not api_key:
            current_app.logger.debug("[GeminiService] Brak klucza API Groq - fallback niedostępny")
        elif api_key == 'TUTAJ_WKLEJ_KLUCZ_API_GROQ':
            current_app.logger.debug("[GeminiService] Klucz API Groq nie został skonfigurowany")
            return ''
        else:
            current_app.logger.debug(f"[GeminiService] Klucz API Groq znaleziony (długość: {len(api_key)})")

        return api_key

    def is_configured(self) -> bool:
        """Sprawdza czy API (Gemini lub Groq) jest skonfigurowane"""
        return bool(self.api_key) or bool(self.groq_api_key)

    def is_groq_configured(self) -> bool:
        """Sprawdza czy Groq API jest skonfigurowane"""
        return bool(self.groq_api_key)

    def chat(self, user_message: str, history: list = None) -> dict:
        """
        Wysyła wiadomość do AI i zwraca odpowiedź.
        Automatycznie przełącza się między modelami Gemini przy przekroczeniu limitów,
        a następnie używa Groq jako ostateczny fallback.

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
                'error': 'API nie jest skonfigurowane. Wklej klucz API Gemini lub Groq w config/core.json'
            }

        try:
            # Emituj status: analizuję pytanie
            emit_status('analyzing')

            # Budowanie kontekstu
            from .system_prompt import get_system_prompt
            system_prompt = get_system_prompt()

            if self.knowledge_base:
                knowledge_context = self.knowledge_base.get_relevant_context(user_message)
                current_app.logger.info(f"[GeminiService] Kontekst z bazy wiedzy ({len(knowledge_context)} znaków)")
                if len(knowledge_context) > 100:
                    current_app.logger.debug(f"[GeminiService] Kontekst (pierwsze 500 znaków): {knowledge_context[:500]}...")
            else:
                knowledge_context = "Brak bazy wiedzy"
                current_app.logger.warning("[GeminiService] KnowledgeBase niedostępny")

            # Budowanie zawartości rozmowy dla Gemini
            contents = self._build_contents(system_prompt, knowledge_context, history, user_message)

            # Emituj status: generuję odpowiedź
            emit_status('generating')

            # Próbuj kolejne modele Gemini (jeśli klucz skonfigurowany)
            last_error = None
            if self.api_key:
                for model in self.GEMINI_MODELS:
                    result = self._call_gemini_model(model, contents)

                    if result['success']:
                        return result

                    # Sprawdź czy to błąd limitu - wtedy próbuj następny model
                    if result.get('is_rate_limit'):
                        current_app.logger.warning(f"[GeminiService] Model {model} ma limit, próbuję następny...")
                        last_error = result
                        continue
                    else:
                        # Inny błąd - zapisz i przejdź do Groq
                        last_error = result
                        break

                current_app.logger.warning("[GeminiService] Wszystkie modele Gemini niedostępne, próbuję Groq...")

            # Fallback do Groq
            if self.is_groq_configured():
                current_app.logger.info("[GeminiService] Przełączam na Groq fallback...")
                emit_status('groq_fallback')

                # Budowanie wiadomości dla Groq (format OpenAI)
                messages = self._build_groq_messages(system_prompt, knowledge_context, history, user_message)

                for groq_model in self.GROQ_MODELS:
                    result = self._call_groq_model(groq_model, messages)

                    if result['success']:
                        return result

                    if result.get('is_rate_limit'):
                        current_app.logger.warning(f"[GeminiService] Groq model {groq_model} ma limit, próbuję następny...")
                        last_error = result
                        continue
                    else:
                        last_error = result
                        break

            # Wszystkie modele zawiodły
            if not self.is_groq_configured():
                current_app.logger.warning("[GeminiService] Groq nie jest skonfigurowany - brak fallbacku!")
            current_app.logger.error("[GeminiService] Wszystkie modele AI (Gemini + Groq) niedostępne!")
            if last_error:
                # Jeśli to był rate limit - pokaż komunikat o limicie
                if last_error.get('is_rate_limit'):
                    return {
                        'success': False,
                        'error': 'Wszystkie modele AI osiągnęły limit zapytań. Spróbuj ponownie za kilka minut.',
                        'retry_after': last_error.get('retry_after', 60)
                    }
                else:
                    # Inny błąd - pokaż rzeczywisty komunikat
                    return {
                        'success': False,
                        'error': last_error.get('error', 'Nie udało się uzyskać odpowiedzi od AI')
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

    def _call_gemini_model(self, model: str, contents: list) -> dict:
        """Wywołuje konkretny model Gemini"""
        url = f"{self.GEMINI_API_BASE_URL}/{model}:generateContent?key={self.api_key}"

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

                        # Sprawdź czy to błąd limitu lub przeciążenia
                        error_lower = error_msg.lower()
                        if (response.status_code == 429 or
                            response.status_code == 503 or
                            'quota' in error_lower or
                            'rate' in error_lower or
                            'overloaded' in error_lower or
                            'resource exhausted' in error_lower):
                            is_rate_limit = True
                            current_app.logger.warning(f"[GeminiService] {model} wykryto limit/przeciążenie: {error_msg}")

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
        # NIE dodajemy knowledge_context tutaj - dodamy go do aktualnej wiadomości
        contents.append({
            "role": "user",
            "parts": [{"text": f"[INSTRUKCJE SYSTEMOWE - NIE ODPOWIADAJ NA TO, TO SĄ TWOJE WYTYCZNE]\n\n{system_prompt}\n\n[KONIEC INSTRUKCJI SYSTEMOWYCH]"}]
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

        # Aktualna wiadomość użytkownika Z KONTEKSTEM
        # Kontekst CRM/Baselinker dołączamy bezpośrednio do pytania, żeby model go widział
        if knowledge_context and knowledge_context.strip():
            user_message_with_context = f"""[DANE Z SYSTEMU - TO SĄ PRAWDZIWE DANE, UŻYJ ICH W ODPOWIEDZI]
{knowledge_context}
[KONIEC DANYCH Z SYSTEMU]

Pytanie użytkownika: {user_message}

WAŻNE: Odpowiedz na podstawie DANYCH Z SYSTEMU powyżej. Jeśli dane mówią że klient ma wycenę X - podaj wycenę X. NIE WYMYŚLAJ innych wycen!"""
        else:
            user_message_with_context = user_message

        contents.append({
            "role": "user",
            "parts": [{"text": user_message_with_context}]
        })

        return contents

    def _build_groq_messages(self, system_prompt: str, knowledge_context: str, history: list, user_message: str) -> list:
        """Buduje strukturę messages dla API Groq (format OpenAI)"""
        messages = []

        # System prompt (Groq obsługuje natywnie system role)
        # NIE dodajemy knowledge_context tutaj - dodamy go do aktualnej wiadomości
        messages.append({
            "role": "system",
            "content": system_prompt
        })

        # Historia rozmowy
        if history:
            for msg in history[-10:]:  # Ostatnie 10 wiadomości
                role = "user" if msg.get('role') == 'user' else "assistant"
                messages.append({
                    "role": role,
                    "content": msg.get('content', '')
                })

        # Aktualna wiadomość użytkownika Z KONTEKSTEM
        # Kontekst CRM/Baselinker dołączamy bezpośrednio do pytania
        if knowledge_context and knowledge_context.strip():
            user_message_with_context = f"""[DANE Z SYSTEMU - TO SĄ PRAWDZIWE DANE, UŻYJ ICH W ODPOWIEDZI]
{knowledge_context}
[KONIEC DANYCH Z SYSTEMU]

Pytanie użytkownika: {user_message}

WAŻNE: Odpowiedz na podstawie DANYCH Z SYSTEMU powyżej. Jeśli dane mówią że klient ma wycenę X - podaj wycenę X. NIE WYMYŚLAJ innych wycen!"""
        else:
            user_message_with_context = user_message

        messages.append({
            "role": "user",
            "content": user_message_with_context
        })

        return messages

    def _call_groq_model(self, model: str, messages: list) -> dict:
        """Wywołuje model przez Groq API (format OpenAI)"""
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }

        request_body = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 8192,
            "top_p": 0.95,
        }

        current_app.logger.info(f"[GeminiService] Wysyłam request do Groq modelu: {model}")

        try:
            response = requests.post(
                self.GROQ_API_BASE_URL,
                headers=headers,
                json=request_body,
                timeout=30
            )
            current_app.logger.info(f"[GeminiService] Groq {model} - Response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                if 'choices' in data and len(data['choices']) > 0:
                    choice = data['choices'][0]
                    if 'message' in choice and 'content' in choice['message']:
                        ai_response = choice['message']['content']
                        current_app.logger.info(f"[GeminiService] Sukces z Groq modelem: {model}")
                        return {
                            'success': True,
                            'response': ai_response,
                            'model': f"groq/{model}"
                        }

                return {
                    'success': False,
                    'error': 'Nie udało się uzyskać odpowiedzi od Groq AI'
                }

            else:
                # Obsługa błędów
                error_msg = f"Błąd Groq API: {response.status_code}"
                is_rate_limit = False
                retry_seconds = None

                try:
                    error_data = response.json()
                    current_app.logger.error(f"[GeminiService] Groq {model} Error: {error_data}")

                    if 'error' in error_data:
                        error_msg = error_data['error'].get('message', error_msg)

                        # Sprawdź czy to błąd limitu lub przeciążenia
                        error_lower = error_msg.lower()
                        if (response.status_code == 429 or
                            response.status_code == 503 or
                            'rate' in error_lower or
                            'limit' in error_lower or
                            'overloaded' in error_lower or
                            'capacity' in error_lower):
                            is_rate_limit = True
                            retry_seconds = 60
                            current_app.logger.warning(f"[GeminiService] Groq {model} wykryto limit: {error_msg}")

                except Exception as parse_err:
                    current_app.logger.error(f"[GeminiService] Groq {model} błąd parsowania odpowiedzi: {parse_err}")

                return {
                    'success': False,
                    'error': error_msg,
                    'is_rate_limit': is_rate_limit,
                    'retry_after': retry_seconds
                }

        except requests.exceptions.Timeout:
            current_app.logger.error(f"[GeminiService] Groq {model} Timeout!")
            return {
                'success': False,
                'error': 'Przekroczono czas oczekiwania na odpowiedź od Groq (30s).'
            }
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"[GeminiService] Groq {model} Request error: {str(e)}")
            return {
                'success': False,
                'error': f'Problem z połączeniem do Groq: {str(e)}'
            }
