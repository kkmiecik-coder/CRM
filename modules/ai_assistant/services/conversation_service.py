"""CRUD dla konwersacji i wiadomości AI"""

from datetime import datetime
from typing import Optional
from extensions import db
from modules.ai_assistant.models import AIConversation, AIMessage


class ConversationService:

    @staticmethod
    def create_conversation(user_id: int) -> AIConversation:
        conv = AIConversation(user_id=user_id)
        db.session.add(conv)
        db.session.commit()
        return conv

    @staticmethod
    def get_conversation(conversation_id: int, user_id: int = None) -> Optional[AIConversation]:
        conv = AIConversation.query.get(conversation_id)
        if conv is None:
            return None
        if user_id is not None and conv.user_id != user_id:
            return None
        return conv

    @staticmethod
    def get_user_conversations(user_id: int, limit: int = 50) -> list:
        return AIConversation.query.filter_by(
            user_id=user_id
        ).order_by(
            AIConversation.last_message_at.desc()
        ).limit(limit).all()

    @staticmethod
    def get_all_conversations(limit: int = 100) -> list:
        return AIConversation.query.order_by(
            AIConversation.last_message_at.desc()
        ).limit(limit).all()

    @staticmethod
    def add_message(conversation_id: int, role: str, content: str) -> AIMessage:
        msg = AIMessage(
            conversation_id=conversation_id,
            role=role,
            content=content
        )
        db.session.add(msg)

        conv = AIConversation.query.get(conversation_id)
        conv.last_message_at = datetime.utcnow()

        if conv.title is None and role == 'user':
            conv.generate_title(content)

        db.session.commit()
        return msg

    @staticmethod
    def get_messages(conversation_id: int, limit: int = 50) -> list:
        return AIMessage.query.filter_by(
            conversation_id=conversation_id
        ).order_by(
            AIMessage.created_at.asc()
        ).limit(limit).all()

    @staticmethod
    def get_recent_messages(conversation_id: int, count: int = 10) -> list:
        messages = AIMessage.query.filter_by(
            conversation_id=conversation_id
        ).order_by(
            AIMessage.created_at.desc()
        ).limit(count).all()
        return list(reversed(messages))
