"""Modele bazy danych dla AI Assistant"""

from datetime import datetime
from extensions import db


class AIConversation(db.Model):
    __tablename__ = 'ai_conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('ai_conversations', lazy='dynamic'))
    messages = db.relationship('AIMessage', backref='conversation', lazy='dynamic',
                               order_by='AIMessage.created_at')

    def generate_title(self, first_message: str):
        if len(first_message) <= 50:
            self.title = first_message
        else:
            truncated = first_message[:50]
            last_space = truncated.rfind(' ')
            if last_space > 20:
                self.title = truncated[:last_space] + '...'
            else:
                self.title = truncated + '...'


class AIMessage(db.Model):
    __tablename__ = 'ai_messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('ai_conversations.id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AIUsageLog(db.Model):
    __tablename__ = 'ai_usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('ai_messages.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    tokens_input = db.Column(db.Integer, nullable=True)
    tokens_output = db.Column(db.Integer, nullable=True)
    response_time_ms = db.Column(db.Integer, nullable=False)
    was_fallback = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('ai_usage_logs', lazy='dynamic'))
    message = db.relationship('AIMessage', backref=db.backref('usage_log', uselist=False))
