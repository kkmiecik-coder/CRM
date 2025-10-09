# app/modules/partner_academy/__init__.py
"""
Partner Academy Module
======================

Moduł rekrutacji i szkoleń partnerów handlowych WoodPower.

Składa się z dwóch elementów:
1. Element 1 (Recruitment) - Strona rekrutacyjna z formularzem NDA
2. Element 2 (Learning Platform) - Platforma e-learningowa

Autor: Development Team
Data: 2025-09-30
"""

from flask import Blueprint

# Utworzenie Blueprint
partner_academy_bp = Blueprint(
    'partner_academy',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/static/partner_academy',
    url_prefix='/partner-academy'
)

# Import routes (będzie później)
from . import routers

__all__ = ['partner_academy_bp']