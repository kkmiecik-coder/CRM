#!/bin/bash
# CRM WoodPower — Auto-Deploy (wołany przez webhook GitHub po push do main)
# Wzorzec z ThunderOrders. Uruchamiany przez modules/deploy/routes.py (subprocess, start_new_session).
# Webhook aktywny od 2026-06-24.

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

LOCK_FILE="/tmp/crm-deploy.lock"
APP_DIR="/home/woodpower-crm/htdocs/crm.woodpower.pl"
LOG_PREFIX="[DEPLOY $(date '+%Y-%m-%d %H:%M:%S')]"

# Blokada równoległych deployów
if [ -f "$LOCK_FILE" ]; then
    echo "$LOG_PREFIX Already deploying, skipping."
    exit 0
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

echo "$LOG_PREFIX Starting deploy..."
cd "$APP_DIR" || exit 1
export FLASK_APP=app.py

OLD_HEAD=$(git rev-parse HEAD)

echo "$LOG_PREFIX Pulling latest code..."
git fetch origin main 2>&1
git reset --hard origin/main 2>&1

NEW_HEAD=$(git rev-parse HEAD)
echo "$LOG_PREFIX Deploy: $OLD_HEAD -> $NEW_HEAD"

echo "$LOG_PREFIX Installing dependencies..."
venv/bin/pip install -q -r requirements.txt 2>&1 || true

# Synchronizacja changeloga (best-effort)
if [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
    echo "$LOG_PREFIX Syncing changelog..."
    venv/bin/flask sync-changelog --before "$OLD_HEAD" --after "$NEW_HEAD" 2>&1 || echo "$LOG_PREFIX [sync-warn] changelog failed"
fi

# Migracje bazy PRZED restartem. Aplikacja odpala je również przy starcie
# (RUN_MIGRATIONS), ale tam błąd ląduje w stderr gunicorna i nikt go nie widzi
# — tutaj jest w logu deployu, obok reszty kroków.
#
# Niepowodzenie PRZERYWA deploy przed restartem: kod jest już pobrany, ale
# proces nadal chodzi na starym, więc stary kod + stary schemat zostaje
# spójny. Restart z nowym kodem na niezmigrowanej bazie byłby gorszy.
echo "$LOG_PREFIX Running database migrations..."
if ! venv/bin/flask migrate 2>&1; then
    echo "$LOG_PREFIX [MIGRATION FAILED] Przerywam deploy PRZED restartem."
    echo "$LOG_PREFIX Aplikacja dziala nadal na starym kodzie. Napraw migracje i wypchnij ponownie."
    exit 1
fi

echo "$LOG_PREFIX Restarting application..."
# Zwolnij lock PRZED restartem (dodatkowe zabezpieczenie, gdyby proces jednak nie dożył trap-a).
rm -f "$LOCK_FILE"

# Defensywnie: przywróć właściciela katalogu logów na woodpower-crm PRZED restartem.
# Jeśli inny proces (np. ręczna komenda admina jako root) utworzył dzienny plik
# logu jako root, gunicorn jako woodpower-crm nie miałby prawa zapisu i nie wstałby
# (skutek: nginx 502). Wołamy root-owy wrapper przez sudo (NOPASSWD) — patrz
# /etc/sudoers.d/crm-deploy-logs oraz /usr/local/sbin/crm-fix-logs-perms.sh.
# Wrapper MUSI być własnością roota i niezapisywalny dla woodpower-crm.
# Best-effort — logger ma też własny fallback, więc brak wrappera nie blokuje deployu.
sudo /usr/local/sbin/crm-fix-logs-perms.sh 2>&1 || echo "$LOG_PREFIX [perms-warn] chown logow nieudany (wrapper/sudoers?)"

sudo /usr/bin/supervisorctl restart crm_woodpower 2>&1

echo "$LOG_PREFIX Deploy complete!"
