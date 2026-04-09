"""AI Assistant — routers (API + strony)"""

import time
from flask import request, jsonify, render_template, current_app, redirect, url_for
from flask_login import login_required, current_user

from extensions import db

from . import ai_assistant_bp


def _require_admin_or_user():
    """Sprawdza czy użytkownik ma rolę admin lub user"""
    if not current_user.is_authenticated:
        return False
    return current_user.is_admin() or current_user.is_user()


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
    try:
        if not _require_admin_or_user():
            return jsonify({'success': False, 'error': 'Brak dostępu'}), 403

        from .services.conversation_service import ConversationService

        if current_user.is_admin():
            convs = ConversationService.get_all_conversations()
        else:
            convs = ConversationService.get_user_conversations(current_user.id)

        return jsonify({
            'success': True,
            'current_user_id': current_user.id,
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
    except Exception as e:
        current_app.logger.error(f"[AIAssistant] api_list_conversations error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        'owner_id': conv.user_id,
        'current_user_id': current_user.id,
        'owner_name': conv.user.get_full_name() if conv.user_id != current_user.id else None,
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
    try:
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

        user_id = current_user.id

        # Synchronous processing — Passenger nie obsługuje threading poprawnie
        _process_chat(conversation_id, user_message, user_id, user_msg.id)

        # Pobierz ostatnią wiadomość asystenta
        from .models import AIMessage
        assistant_msg = AIMessage.query.filter_by(
            conversation_id=conversation_id,
            role='assistant'
        ).order_by(AIMessage.created_at.desc()).first()

        if assistant_msg:
            return jsonify({
                'success': True,
                'response': assistant_msg.content,
                'message_id': user_msg.id,
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Nie udało się uzyskać odpowiedzi od AI'
            }), 500

    except Exception as e:
        current_app.logger.error(f"[AIAssistant] api_chat error: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


def _process_chat(conversation_id: int, user_message: str,
                   user_id: int, user_message_id: int):
    """Przetwarza wiadomość synchronicznie"""
    start_time = time.time()

    from .services.ai_service import AIService
    from .services.conversation_service import ConversationService
    from .services.usage_service import UsageService
    from .integrations.baselinker import BaselinkerIntegration
    from .integrations.crm_queries import CRMQueryIntegration
    from .integrations.prestashop import PrestaShopIntegration
    from modules.users.models import User

    user = User.query.get(user_id)
    if not user:
        return

    ai_service = AIService()
    extra_context_parts = []

    # Pobierz kontekst z CRM (wyceny, klienci)
    crm = CRMQueryIntegration()
    crm_context = crm.get_context_for_message(user_message, user)
    if crm_context:
        extra_context_parts.append(crm_context)

    # Pobierz kontekst z Baselinker
    bl = BaselinkerIntegration()
    bl_context = bl.get_context_for_message(user_message, user)
    if bl_context:
        extra_context_parts.append(bl_context)

    # Szukaj produktów w sklepie
    ps = PrestaShopIntegration()
    ps_context = ps.get_context_for_message(user_message)
    if ps_context:
        extra_context_parts.append(ps_context)

    # Pobierz historię z DB
    history_msgs = ConversationService.get_recent_messages(conversation_id, count=10)
    history = [{'role': m.role, 'content': m.content} for m in history_msgs
                if m.id != user_message_id]

    # Wywołaj AI
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


