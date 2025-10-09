# modules/preview3d_ar/__init__.py
from flask import Blueprint

preview3d_ar_bp = Blueprint('preview3d_ar', __name__, 
                           template_folder='templates', 
                           static_folder='static',
                           url_prefix='/preview3d-ar')

from . import routers