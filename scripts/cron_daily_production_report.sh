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
#
# ── WPIS CRONTAB — GOTOWY DO SKOPIOWANIA ────────────────────────────────────
# Plik /etc/cron.d/woodpower-raport-dzienny (18:00, poniedziałek–piątek,
# jako użytkownik aplikacji). Cała linia, razem z przekierowaniem:
#
# 0 18 * * 1-5 woodpower-crm /home/woodpower-crm/htdocs/crm.woodpower.pl/scripts/cron_daily_production_report.sh >> /home/woodpower-crm/logs/raport-dzienny.log 2>&1
#
# Przed pierwszym uruchomieniem:
#     chmod +x /home/woodpower-crm/htdocs/crm.woodpower.pl/scripts/cron_daily_production_report.sh
#     mkdir -p /home/woodpower-crm/logs && chown woodpower-crm /home/woodpower-crm/logs
#
# Przekierowanie NIE jest ozdobą. Na pytanie „czy raport za 20.08 poszedł?"
# odpowiada właśnie ten plik — komenda wypisuje na stdout podsumowanie doby
# i liczbę odbiorców, a `>> ... 2>&1` łapie też stderr, czyli treść awarii.
# Bez przekierowania cron próbuje wysłać wyjście mailem lokalnym, którego na
# tym VPS-ie nikt nie czyta, a ślad po przebiegu znika.
#
# Rotacja: plik rośnie o kilka linii dziennie, więc logrotate nie jest tu
# konieczny — jeśli jednak ma być, wystarczy wpis `weekly rotate 12`.
# ────────────────────────────────────────────────────────────────────────────

set -eu

KATALOG_APLIKACJI="${KATALOG_APLIKACJI:-/home/woodpower-crm/htdocs/crm.woodpower.pl}"
BLOKADA="/tmp/crm-raport-dzienny.lock"

cd "$KATALOG_APLIKACJI"

# -n: nie czekaj na zwolnienie blokady. Przebieg, który zastał inny w toku,
# ma po prostu odpuścić — o 18:00 następnego dnia będzie kolejny.
exec flock -n "$BLOKADA" \
    "${KATALOG_APLIKACJI}/venv/bin/flask" raport-dzienny
