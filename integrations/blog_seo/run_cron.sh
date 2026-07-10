#!/bin/sh
# Wrapper crona automatu blogowego: laduje .env (cron nie robi tego sam), uruchamia dzienny pipeline.
# Wpis crona wola ten skrypt; logi ida do blog.log obok. run_daily.py tworzy JEDEN szkic enabled=0.
cd "$(dirname "$0")" || exit 1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') start ====="
if [ ! -f ./.env ]; then
  echo "BLAD: brak .env w $(pwd) — nie uruchamiam"; exit 1
fi
set -a
. ./.env
set +a
../../venv/bin/python run_daily.py
echo "===== $(date '+%Y-%m-%d %H:%M:%S') koniec (kod $?) ====="
