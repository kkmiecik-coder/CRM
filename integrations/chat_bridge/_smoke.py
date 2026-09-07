# -*- coding: utf-8 -*-
# Smoke importu: atrapa wymaganych env + import modułów pakietu.
# Uruchamiać z katalogu pakietu: `python _smoke.py <mod1> <mod2> ...`
# Wykrywa błędy importu po przeniesieniu kodu (np. brakujący import między modułami).
import os, sys, importlib

# Tylko te 3 env-y są wymagane (os.environ[...]); reszta ma .get z defaultami.
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")

# Silnik Debusia Pro (bots_pro/) obsluguje dzis skrzynke produkcyjna, a lista
# modulow w `bridge-deploy.sh` na serwerze powstala, zanim ten silnik istnial —
# zepsuty import w bots_pro przechodzil wiec przez bramke wdrozeniowa i wywalal
# sie dopiero na produkcji, przy pierwszej wiadomosci klienta. Doklejamy te
# moduly ZAWSZE, niezaleznie od argumentow, zeby poprawka nie wymagala edycji
# skryptu lezacego poza repozytorium. `agenci` ciagnie prompty, narzedzia,
# guardraile i models, `tura` ciagnie stan, podsumowanie, wysylke i obrazy —
# razem pokrywaja caly pakiet, wiec nie ma potrzeby wyliczac go modul po module.
_PRO = ["bots_pro.agenci", "bots_pro.tura", "bots_pro.potwierdzenia",
        "bots_pro.notatki", "bots_pro.wiedza", "pro_watchdog"]

mods = sys.argv[1:] or ["bridge"]
for m in mods + [m for m in _PRO if m not in mods]:
    importlib.import_module(m)
    print("OK", m)
print("SMOKE OK")
