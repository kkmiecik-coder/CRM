from flask import Blueprint

deploy_bp = Blueprint('deploy', __name__)

from modules.deploy import routes  # noqa: E402, F401
