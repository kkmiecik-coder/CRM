"""AI Assistant — routers (API + strony)"""

import threading
import time
import uuid
from flask import request, jsonify, render_template, current_app, redirect, url_for
from flask_login import login_required, current_user

from extensions import db

from . import ai_assistant_bp

# In-memory storage dla statusów requestów (polling)
_request_statuses = {}
_statuses_lock = threading.Lock()


def _require_admin_or_user():
    """Sprawdza czy użytkownik ma rolę admin lub user"""
    if not current_user.is_authenticated:
        return False
    return current_user.is_admin() or current_user.is_user()


def _cleanup_old_statuses():
    """Czyści statusy starsze niż 5 min"""
    now = time.time()
    with _statuses_lock:
        expired = [k for k, v in _request_statuses.items() if now - v.get('_created', 0) > 300]
        for k in expired:
            del _request_statuses[k]


def _set_status(request_id: str, status: str, **kwargs):
    """Ustawia status requestu"""
    with _statuses_lock:
        _request_statuses[request_id] = {
            'status': status,
            '_created': _request_statuses.get(request_id, {}).get('_created', time.time()),
            **kwargs
        }


# ==========================================
# STRONY HTML
# ==========================================

@ai_assistant_bp.route('/')
@login_required
def conversations_page():
    """Widok listy rozmów"""
    if not _require_admin_or_user():
        return redirect(url_for('dashboard.index'))

    return render_template('ai_assistant/conversations.html')


@ai_assistant_bp.route('/conversation/<int:conversation_id>')
@login_required
def chat_page(conversation_id):
    """Widok rozmowy"""
    if not _require_admin_or_user():
        return redirect(url_for('dashboard.index'))

    from .services.conversation_service import ConversationService

    # Admin może podglądać cudze, user tylko swoje
    if current_user.is_admin():
        conv = ConversationService.get_conversation(conversation_id)
    else:
        conv = ConversationService.get_conversation(conversation_id, current_user.id)

    if conv is None:
        return redirect(url_for('ai_assistant.conversations_page'))

    is_readonly = conv.user_id != current_user.id
    owner_name = conv.user.get_full_name() if is_readonly else None

    return render_template('ai_assistant/chat.html',
                           conversation_id=conversation_id,
                           is_readonly=is_readonly,
                           owner_name=owner_name)


# ==========================================
# API — KONWERSACJE
# ==========================================

@ai_assistant_bp.route('/api/conversations', methods=['GET'])
@login_required
def api_list_conversations():
    """Lista konwersacji"""
    if not _require_admin_or_user():
        return jsonify({'success': False, 'error': 'Brak dostępu'}), 403

    from .services.conversation_service import ConversationService

    if current_user.is_admin():
        convs = ConversationService.get_all_conversations()
    else:
        convs = ConversationService.get_user_conversations(current_user.id)

    return jsonify({
        'success': True,
        'conversations': [{
            'id': c.id,
            'title': c.title or 'Nowa rozmowa',
            'created_at': c.created_at.isoformat() + 'Z',
            'last_message_at': c.last_message_at.isoformat() + 'Z' if c.last_message_at else None,
            'is_active': c.is_active,
            'user_id': c.user_id,
            'user_name': c.user.get_full_name() if current_user.is_admin() else None,
        } for c in convs]
    })


@ai_assistant_bp.route('/api/conversations', methods=['POST'])
@login_required
def api_create_conversation():
    """Tworzy nową konwersację"""
    if not _require_admin_or_user():
        return jsonify({'success': False, 'error': 'Brak dostępu'}), 403

    from .services.conversation_service import ConversationService

    conv = ConversationService.create_conversation(current_user.id)
    return jsonify({
        'success': True,
        'conversation': {
            'id': conv.id,
            'title': conv.title,
            'created_at': conv.created_at.isoformat() + 'Z',
        }
    })


@ai_assistant_bp.route('/api/conversations/<int:conv_id>/messages', methods=['GET'])
@login_required
def api_get_messages(conv_id):
    """Pobiera wiadomości konwersacji"""
    if not _require_admin_or_user():
        return jsonify({'success': False, 'error': 'Brak dostępu'}), 403

    from .services.conversation_service import ConversationService

    if current_user.is_admin():
        conv = ConversationService.get_conversation(conv_id)
    else:
        conv = ConversationService.get_conversation(conv_id, current_user.id)

    if conv is None:
        return jsonify({'success': False, 'error': 'Nie znaleziono rozmowy'}), 404

    messages = ConversationService.get_messages(conv_id)

    return jsonify({
        'success': True,
        'messages': [{
            'id': m.id,
            'role': m.role,
            'content': m.content,
            'created_at': m.created_at.isoformat() + 'Z',
        } for m in messages]
    })


# ==========================================
# API — CHAT (wysyłanie wiadomości + polling)
# ==========================================

@ai_assistant_bp.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Wysyła wiadomość — zwraca request_id do pollingu"""
    if not _require_admin_or_user():
        return jsonify({'success': False, 'error': 'Brak dostępu'}), 403

    data = request.get_json()
    if not data or 'message' not in data or 'conversation_id' not in data:
        return jsonify({'success': False, 'error': 'Brak message lub conversation_id'}), 400

    user_message = data['message'].strip()
    conversation_id = data['conversation_id']

    if not user_message:
        return jsonify({'success': False, 'error': 'Wiadomość nie może być pusta'}), 400

    if len(user_message) > 2000:
        return jsonify({'success': False, 'error': 'Max 2000 znaków'}), 400

    from .services.conversation_service import ConversationService

    # Sprawdź czy to konwersacja użytkownika
    conv = ConversationService.get_conversation(conversation_id, current_user.id)
    if conv is None:
        return jsonify({'success': False, 'error': 'Nie znaleziono rozmowy'}), 404

    # Zapisz wiadomość użytkownika
    user_msg = ConversationService.add_message(conversation_id, 'user', user_message)

    # Generuj request_id
    request_id = str(uuid.uuid4())

    _set_status(request_id, 'pending')

    # Przygotuj dane dla wątku
    app = current_app._get_current_object()
    user_id = current_user.id

    def process():
        with app.app_context():
            try:
                _process_chat(request_id, conversation_id, user_message, user_id, user_msg.id)
            finally:
                db.session.remove()

    try:
        thread = threading.Thread(target=process)
        thread.start()
    except Exception:
        # Synchronous fallback — Passenger may not support threads
        process()
        status_data = _request_statuses.get(request_id, {})
        with _statuses_lock:
            _request_statuses.pop(request_id, None)
        if status_data.get('status') == 'complete':
            return jsonify({
                'success': True,
                'response': status_data.get('response', ''),
            })
        else:
            return jsonify({
                'success': False,
                'error': status_data.get('error', 'Błąd przetwarzania'),
            }), 500

    return jsonify({
        'success': True,
        'request_id': request_id,
        'message_id': user_msg.id,
    })


def _process_chat(request_id: str, conversation_id: int, user_message: str,
                   user_id: int, user_message_id: int):
    """Przetwarza wiadomość w osobnym wątku"""
    start_time = time.time()

    try:
        from .services.ai_service import AIService
        from .services.conversation_service import ConversationService
        from .services.usage_service import UsageService
        from .integrations.baselinker import BaselinkerIntegration
        from .integrations.crm_queries import CRMQueryIntegration
        from .integrations.prestashop import PrestaShopIntegration
        from modules.users.models import User

        _set_status(request_id, 'analyzing')

        user = User.query.get(user_id)
        if not user:
            _set_status(request_id, 'error', error='Użytkownik nie znaleziony')
            return

        ai_service = AIService()
        extra_context_parts = []

        # Pobierz kontekst z CRM (wyceny, klienci)
        _set_status(request_id, 'crm')
        crm = CRMQueryIntegration()
        crm_context = crm.get_context_for_message(user_message, user)
        if crm_context:
            extra_context_parts.append(crm_context)

        # Pobierz kontekst z Baselinker
        _set_status(request_id, 'baselinker')
        bl = BaselinkerIntegration()
        bl_context = bl.get_context_for_message(user_message, user)
        if bl_context:
            extra_context_parts.append(bl_context)

        # Szukaj produktów w sklepie
        _set_status(request_id, 'prestashop')
        ps = PrestaShopIntegration()
        ps_context = ps.get_context_for_message(user_message)
        if ps_context:
            extra_context_parts.append(ps_context)

        # Pobierz historię z DB
        history_msgs = ConversationService.get_recent_messages(conversation_id, count=10)
        history = [{'role': m.role, 'content': m.content} for m in history_msgs
                    if m.id != user_message_id]  # Wykluczamy bieżącą wiadomość

        # Wywołaj AI
        _set_status(request_id, 'generating')
        extra_context = '\n\n'.join(extra_context_parts) if extra_context_parts else ''

        result = ai_service.chat(user_message, history=history, extra_context=extra_context)

        elapsed_ms = int((time.time() - start_time) * 1000)

        if result['success']:
            # Zapisz odpowiedź asystenta
            assistant_msg = ConversationService.add_message(
                conversation_id, 'assistant', result['response']
            )

            # Zapisz metryki
            UsageService.log_usage(
                user_id=user_id,
                provider=result.get('provider', 'unknown'),
                model=result.get('model', 'unknown'),
                response_time_ms=elapsed_ms,
                message_id=assistant_msg.id,
                tokens_input=result.get('tokens_input'),
                tokens_output=result.get('tokens_output'),
                was_fallback=result.get('was_fallback', False),
            )

            _set_status(request_id, 'complete', response=result['response'])
        else:
            _set_status(request_id, 'error', error=result.get('error', 'Błąd AI'))

    except Exception as e:
        current_app.logger.error(f"[AIAssistant] Chat processing error: {e}")
        _set_status(request_id, 'error', error=f'Błąd serwera: {str(e)}')


@ai_assistant_bp.route('/api/chat/status/<request_id>', methods=['GET'])
@login_required
def api_chat_status(request_id):
    """Polling statusu przetwarzania"""
    if not _require_admin_or_user():
        return jsonify({'success': False, 'error': 'Brak dostępu'}), 403

    _cleanup_old_statuses()

    with _statuses_lock:
        status_data = _request_statuses.get(request_id)

    if status_data is None:
        return jsonify({'success': False, 'error': 'Nieznany request_id'}), 404

    # Usuń internal fields
    result = {k: v for k, v in status_data.items() if not k.startswith('_')}
    result['success'] = True

    # Jeśli complete/error — wyczyść po pobraniu
    if status_data['status'] in ('complete', 'error'):
        with _statuses_lock:
            _request_statuses.pop(request_id, None)

    return jsonify(result)
