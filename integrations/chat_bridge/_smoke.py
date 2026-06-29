# -*- coding: utf-8 -*-
# Smoke importu: atrapa wymaganych env + import modułów pakietu.
# Uruchamiać z katalogu pakietu: `python _smoke.py <mod1> <mod2> ...`
# Wykrywa błędy importu po przeniesieniu kodu (np. brakujący import między modułami).
import os, sys, importlib

# Tylko te 3 env-y są wymagane (os.environ[...]); reszta ma .get z defaultami.
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")

mods = sys.argv[1:] or ["bridge"]
for m in mods:
    importlib.import_module(m)
    print("OK", m)
print("SMOKE OK")
