"""
AI Assistant API Router
Obsługuje komunikację z Google Gemini API
"""

import json
import uuid
import traceback
import threading
from flask import request, jsonify, current_app, session, Response
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
        from .services import GeminiService
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


@ai_assistant_bp.route('/chat/stream', methods=['POST'])
@login_required_api
def chat_stream():
    """
    Endpoint SSE do rozmowy z asystentem AI ze streamingiem statusów.

    Request body:
    {
        "message": "Treść wiadomości użytkownika",
        "history": [...]
    }

    Response: Server-Sent Events stream
    - event: status - statusy przetwarzania
    - event: complete - finalna odpowiedź
    - event: error - błędy
    """
    current_app.logger.info("[AI Assistant] Otrzymano żądanie /chat/stream (SSE)")

    try:
        from .services import GeminiService
        from .status_emitter import StatusEmitter, set_current_emitter
    except ImportError as e:
        current_app.logger.error(f"[AI Assistant] Błąd importu: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Błąd konfiguracji modułu: {str(e)}'
        }), 500

    data = request.get_json()

    if not data or 'message' not in data:
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

    if len(user_message) > 2000:
        return jsonify({
            'success': False,
            'error': 'Wiadomość jest zbyt długa (max 2000 znaków)'
        }), 400

    # Generuj unikalny request_id
    request_id = str(uuid.uuid4())
    current_app.logger.info(f"[AI Assistant] SSE request_id: {request_id}")

    # Pobierz user_id z sesji PRZED utworzeniem wątku
    user_id = session.get('user_id')

    # Utwórz emitter
    emitter = StatusEmitter(request_id)

    # Potrzebujemy app context dla wątku
    app = current_app._get_current_object()

    def process_chat():
        """Funkcja przetwarzająca w osobnym wątku"""
        with app.app_context():
            try:
                # Ustaw emitter dla bieżącego wątku
                set_current_emitter(emitter)

                # Ustaw user_id dla wątku (do użycia przez KnowledgeBase)
                from .baselinker_ai_service import set_thread_user_id
                set_thread_user_id(user_id)

                gemini_service = GeminiService()

                if not gemini_service.is_configured():
                    emitter.emit_error('API nie jest skonfigurowane. Wklej klucz API Gemini w config/core.json')
                    return

                response = gemini_service.chat(user_message, history)

                if response['success']:
                    emitter.emit_complete(response['response'])
                else:
                    emitter.emit_error(
                        response.get('error', 'Błąd komunikacji z AI'),
                        response.get('retry_after')
                    )

            except Exception as e:
                current_app.logger.error(f"[AI Assistant] SSE thread error: {str(e)}")
                current_app.logger.error(traceback.format_exc())
                emitter.emit_error(f'Wystąpił błąd serwera: {str(e)}')
            finally:
                set_current_emitter(None)
                # Wyczyść thread-local user_id
                from .baselinker_ai_service import set_thread_user_id
                set_thread_user_id(None)

    # Uruchom przetwarzanie w osobnym wątku
    thread = threading.Thread(target=process_chat)
    thread.start()

    def generate_sse():
        """Generator zdarzeń SSE"""
        try:
            while True:
                event = emitter.get_event(timeout=60.0)

                if event is None:
                    # Timeout - wyślij keepalive
                    yield ': keepalive\n\n'
                    continue

                event_type = event.get('type', 'status')
                event_data = json.dumps(event, ensure_ascii=False)

                yield f'event: {event_type}\ndata: {event_data}\n\n'

                # Zakończ stream po complete lub error
                if event_type in ('complete', 'error'):
                    break

        except GeneratorExit:
            current_app.logger.info(f"[AI Assistant] SSE client disconnected: {request_id}")
        finally:
            emitter.close()

    return Response(
        generate_sse(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'  # Dla nginx
        }
    )
