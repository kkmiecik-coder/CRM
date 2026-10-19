# -*- coding: utf-8 -*-
"""
Tablet kierownika hali — API /api/mobile/manager/* (spec 2026-10-19, kontrakt docs/api-mobile-kierownik.md).

Blueprint rejestruje się w app.py:register_blueprints_lazy() pod /api/mobile/manager. Trasy leżą w routers/mobile_api.py,
a logika w services/ (bramka dostępu, biała lista pól odpowiedzi i kolejne serwisy odczytu).
"""
from modules.production.kierownik.routers.mobile_api import kierownik_mobile_bp  # noqa: F401
