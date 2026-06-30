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
