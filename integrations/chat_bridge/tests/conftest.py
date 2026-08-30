# -*- coding: utf-8 -*-
# Wspolny setup testow mostka: ustawia env PRZED pierwszym importem config.py,
# zeby DB_PATH wskazywal na wspolna, zapisywalna baze tymczasowa. Bez tego testy
# zalezne od DB przechodza w izolacji, ale wywalaja sie w pelnym suite (DB_PATH
# wiazany jest raz, przy pierwszym imporcie config).
import os
import tempfile

os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge.db"))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("MODEL_ROUTER", "gpt-5.6-luna")
os.environ.setdefault("MODEL_WYCENA", "gpt-5.6-terra")
os.environ.setdefault("MODEL_WIEDZA", "gpt-5.6-terra")
os.environ.setdefault("MODEL_POSPRZEDAZ", "gpt-5.6-terra")
os.environ.setdefault("MODEL_GUARDRAIL", "gpt-5.6-luna")
