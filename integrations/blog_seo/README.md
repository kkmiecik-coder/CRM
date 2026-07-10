# blog_seo — automat blogowy SEO (PrestaShop / ETS Simple Blog)

Raz na dobę tworzy JEDEN nieopublikowany szkic artykułu (enabled=0) w Simple Blog.
Publikację zatwierdza człowiek w panelu PrestaShop.

## Uruchomienie lokalne (test)
    cd integrations/blog_seo
    python -m pytest                 # testy
    python run_daily.py --dry-run    # przebieg bez zapisu do sklepu

## Deploy na VPS
Kod jedzie z repo (integrations/blog_seo/). Sekrety w OSOBNYM pliku .env (poza gitem):
1. Skopiuj config.example.env -> .env, wypełnij dedykowanymi kluczami, `chmod 600 .env`.
2. Uruchamiaj jako uzytkownik `woodpower` (musi miec prawo zapisu do img/ets_blog/post/).
3. Zainstaluj zaleznosci w venv (PyMySQL, Pillow, requests — sa w requirements.txt CRM).

## Cron (raz na dobe, np. 06:15)
Plik /etc/cron.d/woodpower-blog (uruchamia jako woodpower, laduje .env):
    15 6 * * * woodpower cd /sciezka/integrations/blog_seo && set -a && . ./.env && set +a && /sciezka/venv/bin/python run_daily.py >> /home/woodpower/blog_seo/blog.log 2>&1

## Przełączanie dostawcy LLM
W .env: BLOG_LLM_PROVIDER=openai  ->  anthropic (i odpowiedni klucz). Rdzeń tekstowy działa na obu.

## Ważne
- enabled=0: szkic NIE jest widoczny na froncie do czasu publikacji w panelu PS.
- Baza sklepu: automat tylko czyta katalog i wstawia nowy post bloga. Nie zmienia danych sklepu.
