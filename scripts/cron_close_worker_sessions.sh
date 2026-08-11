#!/bin/sh
# Domyka zapomniane sesje pracowników (bezczynność + nocny cutoff).
#
# W aplikacji NIE MA schedulera — scheduler_daemon.py został usunięty w maju
# 2026 razem z APScheduler. Jedyna działająca droga to cron hostingu wołający
# endpoint, tak samo jak przy synchronizacji Baselinkera.
#
# Bez tego wpisu sesje wiszą otwarte w nieskończoność: pracownik, który
# zapomniał się wylogować, „pracuje" przez noc i weekend, a raport wydajności
# dopisuje mu godziny, których nie było. Serwis przycina wprawdzie pojedynczą
# sesję do nocnego cutoffu jej doby, ale wiersz zostaje otwarty i wisi
# w panelu „kto teraz na hali".
#
# Sekret czytamy z config/core.json, żeby nie leżał w crontabie ani w gicie.
# Endpoint jest idempotentny — działa wyłącznie na wierszach z ended_at IS NULL,
# więc powtórka nic nie psuje.

set -eu

KATALOG_APLIKACJI="${KATALOG_APLIKACJI:-/home/woodpower-crm/htdocs/crm.woodpower.pl}"
ADRES="${ADRES:-https://crm.woodpower.pl}"

SEKRET=$(python3 -c "import json,sys; print(json.load(open('${KATALOG_APLIKACJI}/config/core.json')).get('PRODUCTION_CRON_SECRET',''))")

if [ -z "$SEKRET" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') BLAD: brak PRODUCTION_CRON_SECRET w config/core.json" >&2
    exit 1
fi

ODPOWIEDZ=$(curl -sS -m 30 -w '\n%{http_code}' -X POST \
    -H "X-Cron-Secret: ${SEKRET}" \
    "${ADRES}/production/api/workers/close-stale-sessions" 2>&1) || {
        echo "$(date '+%Y-%m-%d %H:%M:%S') BLAD polaczenia: ${ODPOWIEDZ}" >&2
        exit 1
    }

KOD=$(printf '%s' "$ODPOWIEDZ" | tail -n1)
TRESC=$(printf '%s' "$ODPOWIEDZ" | sed '$d')

# Logujemy tylko wtedy, gdy faktycznie coś się wydarzyło albo poszło źle —
# inaczej co 5 minut przez całą dobę zapisywalibyśmy "closed: 0".
if [ "$KOD" != "200" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') HTTP ${KOD}: ${TRESC}" >&2
    exit 1
fi

# Dwa niezależne testy, nie jeden wzorzec z kolejnością: Flask serializuje
# klucze ALFABETYCZNIE, więc w ciele jest "idle_timeout" przed "night_cutoff".
# Wzorzec zakładający odwrotną kolejność nie pasowałby nigdy i skrypt logowałby
# "closed: 0" co pięć minut, czyli 288 razy na dobę — a wtedy prawdziwy
# komunikat utonąłby w szumie.
if printf '%s' "$TRESC" | grep -q '"idle_timeout": *0' \
   && printf '%s' "$TRESC" | grep -q '"night_cutoff": *0'; then
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') ${TRESC}"
