#!/bin/sh
# Dzienny raport produkcji — XLSX mailem o 18:00 w dni robocze.
#
# W aplikacji NIE MA schedulera (scheduler_daemon.py usunięty w maju 2026
# razem z APScheduler), więc jedyną drogą jest cron hostingu. W odróżnieniu
# od pozostałych zadań cyklicznych ten NIE idzie przez HTTP: dekorator
# cron_secret_required ma fallback do sekretu zapisanego wprost w repozytorium,
# a raport i tak liczy się na tej samej maszynie, na której stoi cron.
#
# flock: raport jest read-only, więc równoległy przebieg niczego nie zepsuje
# w bazie — ale WYŚLE DRUGI MAIL. Istniejący /sync-cron nie ma tej ochrony
# i nie powtarzamy tego wzorca.
#
# Ograniczenie do poniedziałku–piątku siedzi we WPISIE CRONA (1-5), nie tutaj:
# harmonogram jest sprawą harmonogramu, a ręczne odpalenie w sobotę ma działać.

set -eu

KATALOG_APLIKACJI="${KATALOG_APLIKACJI:-/home/woodpower-crm/htdocs/crm.woodpower.pl}"
BLOKADA="/tmp/crm-raport-dzienny.lock"

cd "$KATALOG_APLIKACJI"

# -n: nie czekaj na zwolnienie blokady. Przebieg, który zastał inny w toku,
# ma po prostu odpuścić — o 18:00 następnego dnia będzie kolejny.
exec flock -n "$BLOKADA" \
    "${KATALOG_APLIKACJI}/venv/bin/flask" raport-dzienny
