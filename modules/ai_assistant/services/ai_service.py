"""Singleton AI Service — Gemini z fallbackiem do Groq"""

import re
import time
import threading
import requests
from flask import current_app

from modules.ai_assistant.knowledge.loader import KnowledgeLoader
from modules.ai_assistant.services.cache_service import CacheService


class AIService:
    """Singleton service do komunikacji z API AI"""

    _instance = None
    _lock = threading.Lock()

    GEMINI_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    GROQ_MODELS = [
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-3.1-8b-instant",
    ]

    GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    GROQ_API_BASE = "https://api.groq.com/openai/v1/chat/completions"

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def init_app(self, app):
        """Inicjalizacja z kontekstem aplikacji"""
        if self._initialized:
            return
        config = app.config.get('AI_ASSISTANT', {})
        self._gemini_key = config.get('api_key', '')
        self._groq_key = config.get('groq_api_key', '')
        self._knowledge = KnowledgeLoader()
        self._knowledge.load()
        self._system_prompt = self._load_system_prompt()
        self._initialized = True

    def _load_system_prompt(self) -> str:
        """Ładuje system prompt z pliku MD"""
        import os
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'prompts', 'system_prompt.md'
        )
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return "Jesteś asystentem WoodPower CRM."

    @property
    def is_configured(self) -> bool:
        return bool(self._gemini_key) or bool(self._groq_key)

    def chat(self, user_message: str, history: list = None,
             extra_context: str = '') -> dict:
        """
        Wysyła wiadomość do AI.

        Args:
            user_message: wiadomość użytkownika
            history: lista dict {'role': 'user'/'assistant', 'content': '...'}
            extra_context: dodatkowy kontekst (dane z CRM/BL/PrestaShop)

        Returns:
            {
                'success': bool,
                'response': str,
                'model': str,
                'provider': str,
                'was_fallback': bool,
                'tokens_input': int or None,
                'tokens_output': int or None,
                'error': str (jeśli success=False)
            }
        """
        if not self.is_configured:
            return {'success': False, 'error': 'API nie jest skonfigurowane'}

        # Pobierz kontekst z bazy wiedzy
        knowledge_context = self._knowledge.get_relevant_context(user_message)

        # Połącz konteksty
        full_context = ''
        if knowledge_context:
            full_context += knowledge_context
        if extra_context:
            if full_context:
                full_context += '\n\n'
            full_context += extra_context

        # Próbuj Gemini
        was_fallback = False
        if self._gemini_key:
            contents = self._build_gemini_contents(
                self._system_prompt, full_context, history, user_message
            )
            for model in self.GEMINI_MODELS:
                result = self._call_gemini(model, contents)
                if result['success']:
                    result['provider'] = 'gemini'
                    result['was_fallback'] = False
                    return result
                if not result.get('is_rate_limit'):
                    break

        # Fallback do Groq
        was_fallback = True
        if self._groq_key:
            messages = self._build_groq_messages(
                self._system_prompt, full_context, history, user_message
            )
            for model in self.GROQ_MODELS:
                result = self._call_groq(model, messages)
                if result['success']:
                    result['provider'] = 'groq'
                    result['was_fallback'] = True
                    return result
                if not result.get('is_rate_limit'):
                    break

        return {
            'success': False,
            'error': 'Wszystkie modele AI niedostępne. Spróbuj za kilka minut.'
        }

    def _build_gemini_contents(self, system_prompt, context, history, message):
        """Buduje contents dla Gemini API"""
        contents = [
            {
                "role": "user",
                "parts": [{"text": f"[INSTRUKCJE SYSTEMOWE]\n\n{system_prompt}\n\n[KONIEC INSTRUKCJI]"}]
            },
            {
                "role": "model",
                "parts": [{"text": "Rozumiem. Jestem częścią zespołu WoodPower. Jak mogę pomóc?"}]
            }
        ]

        if history:
            for msg in history[-10:]:
                role = "user" if msg.get('role') == 'user' else "model"
                contents.append({"role": role, "parts": [{"text": msg.get('content', '')}]})

        user_text = message
        if context:
            user_text = f"[DANE Z SYSTEMU]\n{context}\n[KONIEC DANYCH]\n\nPytanie: {message}"

        contents.append({"role": "user", "parts": [{"text": user_text}]})
        return contents

    def _build_groq_messages(self, system_prompt, context, history, message):
        """Buduje messages dla Groq API (format OpenAI)"""
        messages = [{"role": "system", "content": system_prompt}]

        if history:
            for msg in history[-10:]:
                role = "user" if msg.get('role') == 'user' else "assistant"
                messages.append({"role": role, "content": msg.get('content', '')})

        user_text = message
        if context:
            user_text = f"[DANE Z SYSTEMU]\n{context}\n[KONIEC DANYCH]\n\nPytanie: {message}"

        messages.append({"role": "user", "content": user_text})
        return messages

    def _call_gemini(self, model: str, contents: list) -> dict:
        """Wywołuje model Gemini"""
        url = f"{self.GEMINI_API_BASE}/{model}:generateContent?key={self._gemini_key}"
        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ]
        }

        try:
            resp = requests.post(url, json=body, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get('candidates', [])
                if candidates and 'content' in candidates[0]:
                    text = candidates[0]['content']['parts'][0].get('text', '')
                    usage = data.get('usageMetadata', {})
                    return {
                        'success': True,
                        'response': text,
                        'model': model,
                        'tokens_input': usage.get('promptTokenCount'),
                        'tokens_output': usage.get('candidatesTokenCount'),
                    }
                return {'success': False, 'error': 'Brak odpowiedzi od AI'}

            is_rate = resp.status_code in (429, 503)
            if not is_rate:
                try:
                    err = resp.json().get('error', {}).get('message', '')
                    is_rate = any(w in err.lower() for w in ['quota', 'rate', 'overloaded', 'resource exhausted'])
                except Exception:
                    pass

            return {'success': False, 'error': f'Gemini {model}: {resp.status_code}', 'is_rate_limit': is_rate}

        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Timeout Gemini (30s)'}
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"[AIService] Gemini request error: {e}")
            return {'success': False, 'error': str(e)}

    def _call_groq(self, model: str, messages: list) -> dict:
        """Wywołuje model Groq"""
        headers = {
            "Authorization": f"Bearer {self._groq_key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 8192,
            "top_p": 0.95,
        }

        try:
            resp = requests.post(self.GROQ_API_BASE, headers=headers, json=body, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                choices = data.get('choices', [])
                if choices and 'message' in choices[0]:
                    text = choices[0]['message']['content']
                    usage = data.get('usage', {})
                    return {
                        'success': True,
                        'response': text,
                        'model': f"groq/{model}",
                        'tokens_input': usage.get('prompt_tokens'),
                        'tokens_output': usage.get('completion_tokens'),
                    }
                return {'success': False, 'error': 'Brak odpowiedzi od Groq'}

            is_rate = resp.status_code in (429, 503)
            return {'success': False, 'error': f'Groq {model}: {resp.status_code}', 'is_rate_limit': is_rate}

        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Timeout Groq (30s)'}
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"[AIService] Groq request error: {e}")
            return {'success': False, 'error': str(e)}
