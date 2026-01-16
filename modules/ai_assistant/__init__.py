from flask import Blueprint

ai_assistant_bp = Blueprint(
    'ai_assistant',
    __name__,
    url_prefix='/ai-assistant',
    static_folder='static',
    static_url_path='/ai-assistant/static'
)

from . import routers
