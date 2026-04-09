from flask import Blueprint

ai_assistant_bp = Blueprint(
    'ai_assistant',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/ai-assistant'
)

def init_ai_service(app):
    """Inicjalizuje singleton AIService z kontekstem aplikacji"""
    from modules.ai_assistant.services.ai_service import AIService
    service = AIService()
    service.init_app(app)

from . import routers  # noqa
