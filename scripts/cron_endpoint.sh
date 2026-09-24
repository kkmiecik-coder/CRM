#!/bin/sh
# Woła endpoint CRON aplikacji z sekretem z config/core.json.
#
# Użycie:  cron_endpoint.sh METODA ŚCIEŻKA
#   cron_endpoint.sh GET /production/api/sync-cron
#   cron_endpoint.sh GET /reports/api/cron/sync-statuses
#
# Po co: endpointy CRON (cron_auth.py) nie mają już wartości zapasowej sekretu,
# więc wpis crontaba MUSI wysłać PRODUCTION_CRON_SECRET z core.json. Ten skrypt
# czyta go przy każdym wywołaniu, żeby sekret nie leżał w crontabie ani w gicie,
# i podaje nagłówek curlowi przez stdin (-H @-), żeby nie było go widać w `ps`.
#
# Wpis crontaba (przykład, jako użytkownik aplikacji, z logiem):
#   0 * * * * woodpower-crm /home/woodpower-crm/htdocs/crm.woodpower.pl/scripts/cron_endpoint.sh GET /production/api/sync-cron >> /home/woodpower-crm/logs/cron-endpointy.log 2>&1
#
# Kod wyjścia: 0 przy HTTP 200, 1 w każdym innym przypadku (treść błędu na stderr).

set -eu

KATALOG_APLIKACJI="${KATALOG_APLIKACJI:-/home/woodpower-crm/htdocs/crm.woodpower.pl}"
ADRES="${ADRES:-https://crm.woodpower.pl}"
# Synchronizacja z BaseLinkerem potrafi trwać minuty; limit chroni przed
# wiszącym procesem, który blokowałby kolejne przebiegi.
LIMIT_CZASU="${LIMIT_CZASU:-1800}"

if [ "$#" -ne 2 ]; then
    echo "Użycie: $0 METODA ŚCIEŻKA   (np. $0 GET /production/api/sync-cron)" >&2
    exit 1
fi
METODA="$1"
SCIEZKA="$2"

teraz() { date '+%Y-%m-%d %H:%M:%S'; }

# Brak pliku, zły JSON albo brak pola kończą się pustym napisem — obsłużonym niżej.
SEKRET=$(KATALOG_APLIKACJI="$KATALOG_APLIKACJI" python3 -c '
import json, os, sys
try:
    with open(os.path.join(os.environ["KATALOG_APLIKACJI"], "config", "core.json"), encoding="utf-8") as f:
        wartosc = json.load(f).get("PRODUCTION_CRON_SECRET")
except Exception:
    wartosc = None
sys.stdout.write(wartosc if isinstance(wartosc, str) else "")
')

if [ -z "$(printf '%s' "$SEKRET" | tr -d '[:space:]')" ]; then
    echo "$(teraz) BLAD: brak PRODUCTION_CRON_SECRET w ${KATALOG_APLIKACJI}/config/core.json" >&2
    exit 1
fi

ODPOWIEDZ=$(printf 'X-Cron-Secret: %s\n' "$SEKRET" | curl -sS -m "$LIMIT_CZASU" -w '\n%{http_code}' \
    -X "$METODA" -H @- "${ADRES}${SCIEZKA}" 2>&1) || {
        echo "$(teraz) BLAD polaczenia ${METODA} ${SCIEZKA}: ${ODPOWIEDZ}" >&2
        exit 1
    }

KOD=$(printf '%s' "$ODPOWIEDZ" | tail -n1)
TRESC=$(printf '%s' "$ODPOWIEDZ" | sed '$d')

if [ "$KOD" != "200" ]; then
    echo "$(teraz) ${METODA} ${SCIEZKA} HTTP ${KOD}: ${TRESC}" >&2
    exit 1
fi

echo "$(teraz) ${METODA} ${SCIEZKA} OK: ${TRESC}"
