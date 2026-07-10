#!/bin/bash
# crm-fix-logs-perms.sh — przywraca właściciela katalogu logów CRM na woodpower-crm.
#
# ⚠️ TO JEST WZORZEC / ŹRÓDŁO (kopia w repo dla wersjonowania).
#    Plik wykonywany przez sudo MUSI leżeć w /usr/local/sbin/crm-fix-logs-perms.sh
#    i być własnością roota (root:root, 0755), NIEzapisywalny dla woodpower-crm.
#    NIE podpinaj pod sudo kopii z repo — repo należy do woodpower-crm, więc
#    dałoby to możliwość eskalacji uprawnień.
#
# Po co: gdy dzienny plik logu app_YYYY-MM-DD.log utworzy inny proces jako root,
# gunicorn (user=woodpower-crm) nie ma prawa zapisu i nie wstaje → nginx 502.
# deploy.sh woła ten wrapper PRZED restartem, żeby oddać logi właścicielowi appki.
#
# Instalacja na VPS (jako root):
#   install -o root -g root -m 0755 ops/crm-fix-logs-perms.sh /usr/local/sbin/crm-fix-logs-perms.sh
#   printf 'woodpower-crm ALL=(root) NOPASSWD: /usr/local/sbin/crm-fix-logs-perms.sh\n' > /etc/sudoers.d/crm-deploy-logs
#   chmod 0440 /etc/sudoers.d/crm-deploy-logs
#   visudo -cf /etc/sudoers.d/crm-deploy-logs   # walidacja składni sudoers
#
# Wołane z deploy.sh:  sudo /usr/local/sbin/crm-fix-logs-perms.sh
set -e
LOGS_DIR="/home/woodpower-crm/htdocs/crm.woodpower.pl/modules/logging/logs"
chown -R woodpower-crm:woodpower-crm "$LOGS_DIR"
