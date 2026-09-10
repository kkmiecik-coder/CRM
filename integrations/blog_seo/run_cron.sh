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
KOD_PIPELINE=$?

# Obrazy hero zapisujemy prosto na dysk SKLEPU, a ten nalezy do innego uzytkownika
# systemowego (woodpower) niz CRM (woodpower-crm) — CloudPanel izoluje konta i katalog
# docelowy ma drwxr-xr-x woodpower:woodpower. Dlatego wpis w /etc/cron.d/woodpower-blog
# chodzi jako root: bez tego pipeline nie mialby tam prawa zapisu.
#
# Skutkiem ubocznym byly pliki root:root w katalogu sklepu. Usuwac je PrestaShop moze
# (usuniecie wymaga prawa do katalogu, nie do pliku), ale NADPISAC juz nie — php-fpm
# sklepu dziala jako woodpower, wiec regeneracja miniatur albo ponowne wgranie tego
# samego obrazu konczyloby sie bledem uprawnien. Sprowadzamy je wiec do wlasciciela sklepu.
#
# Sciezke bierzemy z tej samej zmiennej co config.py (BLOG_PS_IMG_DIR), zeby nie mogly
# sie rozjechac. Ruszamy TYLKO pliki o zlym wlascicielu i tylko na jednym poziomie —
# katalog zostaje czyj jest. Bez zalozen o rozszerzeniu, bo publisher.py zapisuje
# przez open() i nazwa pliku nie jest tu gwarantowana.
PS_IMG_DIR="${BLOG_PS_IMG_DIR:-/home/woodpower/htdocs/woodpower.pl/img/ets_blog/post}"
if [ -d "$PS_IMG_DIR" ]; then
  ILE=$(find "$PS_IMG_DIR" -maxdepth 1 -type f ! -user woodpower 2>/dev/null | wc -l | tr -d ' ')
  if [ "$ILE" -gt 0 ]; then
    # Uruchomienie recznie jako woodpower-crm nie ma uprawnien do chown — wtedy tylko
    # odnotowujemy w logu i idziemy dalej, zamiast wywracac caly przebieg.
    if find "$PS_IMG_DIR" -maxdepth 1 -type f ! -user woodpower -exec chown woodpower:woodpower {} + 2>/dev/null; then
      echo "chown: sprowadzono $ILE plikow do woodpower:woodpower"
    else
      echo "UWAGA: $ILE plikow nie nalezy do woodpower, a chown sie nie powiodl (brak roota?)"
    fi
  fi
fi

# Kod wyjscia pipeline'u przechwycony WYZEJ, przed chownem — inaczej log raportowalby
# wynik sprzatania zamiast wyniku automatu i bledy Pythona zniknelyby po cichu.
echo "===== $(date '+%Y-%m-%d %H:%M:%S') koniec (kod $KOD_PIPELINE) ====="
