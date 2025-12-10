"""
AI Assistant API Router
Obsługuje komunikację z Google Gemini API
"""

import traceback
from flask import request, jsonify, current_app, session
from . import ai_assistant_bp
from functools import wraps


def login_required_api(f):
    """Dekorator wymagający zalogowania dla API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_email'):
            current_app.logger.warning("[AI Assistant] Próba dostępu bez zalogowania")
            return jsonify({
                'success': False,
                'error': 'Wymagane zalogowanie'
            }), 401
        return f(*args, **kwargs)
    return decorated_function


@ai_assistant_bp.route('/chat', methods=['POST'])
@login_required_api
def chat():
    """
    Endpoint do rozmowy z asystentem AI

    Request body:
    {
        "message": "Treść wiadomości użytkownika",
        "history": [  # opcjonalne - historia rozmowy
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
        ]
    }

    Response:
    {
        "success": true,
        "response": "Odpowiedź asystenta"
    }
    """
    current_app.logger.info("[AI Assistant] Otrzymano żądanie /chat")

    try:
        # Import serwisu wewnątrz funkcji dla lepszego raportowania błędów
        try:
            from .services import GeminiService
        except ImportError as e:
            current_app.logger.error(f"[AI Assistant] Błąd importu GeminiService: {str(e)}")
            current_app.logger.error(traceback.format_exc())
            return jsonify({
                'success': False,
                'error': f'Błąd konfiguracji modułu: {str(e)}'
            }), 500

        data = request.get_json()
        current_app.logger.debug(f"[AI Assistant] Otrzymane dane: {data}")

        if not data or 'message' not in data:
            current_app.logger.warning("[AI Assistant] Brak wiadomości w żądaniu")
            return jsonify({
                'success': False,
                'error': 'Brak wiadomości w żądaniu'
            }), 400

        user_message = data.get('message', '').strip()
        history = data.get('history', [])

        if not user_message:
            return jsonify({
                'success': False,
                'error': 'Wiadomość nie może być pusta'
            }), 400

        # Limit długości wiadomości
        if len(user_message) > 2000:
            return jsonify({
                'success': False,
                'error': 'Wiadomość jest zbyt długa (max 2000 znaków)'
            }), 400

        current_app.logger.info(f"[AI Assistant] Przetwarzam wiadomość: {user_message[:50]}...")

        # Wywołanie serwisu Gemini
        try:
            gemini_service = GeminiService()
            current_app.logger.debug(f"[AI Assistant] API skonfigurowane: {gemini_service.is_configured()}")
        except Exception as e:
            current_app.logger.error(f"[AI Assistant] Błąd tworzenia GeminiService: {str(e)}")
            current_app.logger.error(traceback.format_exc())
            return jsonify({
                'success': False,
                'error': f'Błąd inicjalizacji serwisu AI: {str(e)}'
            }), 500

        response = gemini_service.chat(user_message, history)
        current_app.logger.debug(f"[AI Assistant] Odpowiedź serwisu: success={response.get('success')}")

        if response['success']:
            current_app.logger.info("[AI Assistant] Pomyślnie uzyskano odpowiedź")
            return jsonify({
                'success': True,
                'response': response['response']
            })
        else:
            error_msg = response.get('error', 'Błąd komunikacji z AI')
            retry_after = response.get('retry_after')
            current_app.logger.warning(f"[AI Assistant] Błąd od serwisu: {error_msg}")

            result = {
                'success': False,
                'error': error_msg
            }
            if retry_after:
                result['retry_after'] = retry_after

            # 429 dla rate limit, 500 dla innych błędów
            status_code = 429 if retry_after else 500
            return jsonify(result), status_code

    except Exception as e:
        current_app.logger.error(f"[AI Assistant] Nieoczekiwany błąd: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'Wystąpił błąd serwera: {str(e)}'
        }), 500


@ai_assistant_bp.route('/status', methods=['GET'])
@login_required_api
def status():
    """Sprawdza status połączenia z AI"""
    try:
        gemini_service = GeminiService()
        is_configured = gemini_service.is_configured()

        return jsonify({
            'success': True,
            'configured': is_configured,
            'message': 'AI Assistant jest gotowy' if is_configured else 'Brak konfiguracji API'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
