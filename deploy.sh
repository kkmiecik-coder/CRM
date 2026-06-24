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

echo "$LOG_PREFIX Restarting application..."
# Zwolnij lock PRZED restartem (dodatkowe zabezpieczenie, gdyby proces jednak nie dożył trap-a).
rm -f "$LOCK_FILE"
sudo /usr/bin/supervisorctl restart crm_woodpower 2>&1

echo "$LOG_PREFIX Deploy complete!"
