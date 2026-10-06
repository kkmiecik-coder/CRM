# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WoodPower CRM - A Flask-based CRM application for manufacturing/production management. Features include pricing calculator, client management, production order tracking, 3D AR previews, quote management, and AI assistant integration.

## Development Workflow

### Local Development (Docker)

Codzienny start (kontenery NIE wstają same po zamknięciu Docker Desktop):
```bash
cd <katalog repo> && docker compose up -d    # macOS: ~/Documents/woodpower-crm
```

Pierwszy raz / po zmianie Dockerfile lub requirements.txt:
```bash
docker compose up -d --build
```

Porty pochodzą z pliku `.env` (poza gitem, bo różnią się między maszynami):

```
CRM_APP_PORT=5002
CRM_DB_PORT=3308
```

Bez `.env` `docker-compose.yml` używa domyślnych **5000** i **3306**. Na macOS Konrada
te domyślne są zajęte (5000 — odbiornik AirPlay, 3306 — MariaDB z XAMPP, która musi dalej
działać dla bazy `thunder_orders` innego projektu), stąd 5002 i 3308.

W tym samym `.env` leży **klucz sesji** `FLASK_SECRET_KEY` — bez niego aplikacja nie wstanie
(czytelny błąd `BrakKluczaSesjiError` przy starcie). Jednorazowo na maszynę, z katalogu repo
(macOS: `python3` zamiast `python`; jeśli `.env` ma już linię `FLASK_SECRET_KEY`, pomiń):
```bash
python -c "import secrets; open('.env','a',encoding='utf-8',newline='\n').write('\nFLASK_SECRET_KEY=' + secrets.token_hex(32) + '\n')"
docker compose up -d    # odtworzy kontener app już z kluczem
```
Komenda działa tak samo w PowerShellu, cmd, bashu i zsh i nie wyświetla klucza. **Nie używaj
`... >> .env`**: Windows PowerShell 5.1 dopisuje wtedy linię w UTF-16LE, po czym każde
polecenie `docker compose` (także `down`/`ps`) pada na `unexpected character "\x00"`,
a przy `.env` bez końcowego znaku nowej linii klucz skleja się z poprzednią linią.

Zrób to **przed** pobraniem kodu, który wymaga klucza (pull `main` / przełączenie gałęzi):
dev server przeładowuje się przy zmianie plików i bez klucza kontener `app` od razu
przestaje działać. Stary kod zmienną ignoruje, więc kolejność „najpierw klucz” jest bezpieczna.

Każda maszyna ma własny, losowy klucz. Wartości nie wpisuj do `docker-compose.yml` ani
nigdzie w repo — repo jest publiczne. Testy klucza nie potrzebują (`tests/conftest.py`
losuje własny). `.env` to wyłącznie sprawa **lokalnego Dockera** — na serwerze klucz jest
tylko w `config/core.json` (patrz „Ważne” w sekcji Deployment).

App: http://localhost:5002, Flask dev server z auto-reloadem przy zmianie plików.
MySQL 8.4: port 3308 na hoście (wolumen `db_data` — dane przeżywają restart kontenerów).

Testy:
```bash
docker compose exec app pytest tests/                                 # główny pakiet
docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest"  # blog_seo (własna konwencja importów)
```
Gołe `pytest` z korzenia repo NIE działa — `integrations/blog_seo` importuje swoje moduły
płasko (`import catalog` itp.) i wymaga bycia uruchomionym z własnego katalogu jako cwd.

### Local Environment Requirements
- Docker Desktop (repo jest rozwijane i na Windows, i na macOS — nie zakładaj systemu)
- WeasyPrint działa od razu w kontenerze (biblioteki systemowe w `docker/python/Dockerfile`) —
  bez ręcznej instalacji MSYS2 + GTK3
- Fonty PDF: obraz ma `fonts-liberation` **i** `fonts-dejavu-core`. DejaVu jest za symbole
  Unicode, których Liberation nie ma (np. flaga U+2691 w nagłówku protokołu trakowni).
  Bez niego WeasyPrint wstawia `.notdef` i psuje mapę ToUnicode całej linii — PDF wygląda
  źle, a `test_protocol_pdf_renderuje_polskie_znaki` oblewa
- Testy jadą na SQLite in-memory, więc **nie sprawdzają MySQL-a**. Zmiany dotykające
  specyfiki MySQL trzeba weryfikować osobno, na działającym kontenerze `db`

### Migracje bazy

Migracje leżą w `migrations/` i wykonują się **automatycznie**: przy deployu
(`deploy.sh` → `flask migrate`, przed restartem aplikacji) oraz przy starcie
aplikacji (`RUN_MIGRATIONS`, domyślnie włączone). Wykonane migracje są
odnotowane w tabeli `schema_migrations` i nie powtarzają się.

Nazwa pliku MUSI pasować do jednego z dwóch formatów, inaczej runner go
pominie (test `tests/test_migration_service.py` tego pilnuje):

- `2026-08-06-nazwa.sql` — format bieżący
- `001_nazwa.sql` — format historyczny, nie używaj do nowych

Migracja ma być **idempotentna** (`CREATE TABLE IF NOT EXISTS`,
`INSERT IGNORE`, `ALTER` osłonięty) — runner uruchamia katalog przy każdym
deployu. Nieudana migracja przerywa deploy PRZED restartem, więc aplikacja
zostaje na starym kodzie i starym schemacie.

`DELIMITER` nie jest obsługiwany — procedur i triggerów tą drogą nie wgrywamy.

Ręczne uruchomienie:
```bash
flask migrate         # wykonaj oczekujące
flask migrate-status  # co zostało wykonane
```

### Database Setup
```bash
# Tworzy schemat bazy (tabele z modeli) — konta admina NIE zakłada
flask setup-db

# Or set RUN_DB_SETUP: true in config/core.json for auto-setup on startup
```

W kodzie nie ma żadnego konta z hasłem (dawne `create_admin()` usunięte). Nowych
użytkowników zaprasza istniejący admin z `/users/manage`.

### Klucz sesji (SECRET_KEY)

Podpisuje ciasteczko sesji, „remember me" i linki resetu hasła. Źródła, w kolejności:
zmienna środowiskowa `FLASK_SECRET_KEY` (wygrywa), a gdy jej brak — pole `SECRET_KEY`
w `config/core.json`. **Nie ma wartości domyślnej w kodzie**: brak klucza albo klucz
krótszy niż 32 znaki = `create_app()` rzuca `BrakKluczaSesjiError` i aplikacja nie
startuje. Logika: `wczytaj_klucz_sesji()` w `app.py`, testy: `tests/test_klucz_sesji.py`.

Zmiana klucza wylogowuje wszystkich i unieważnia wysłane linki resetu hasła.
Tablety hali to nie dotyczy — API mobilne ma własny `API_MOBILE.jwt_secret`.

### Zadania cykliczne (cron)

**Nie ma żadnego schedulera w aplikacji.** `scheduler_daemon.py` został usunięty
commitem `0684949` (2026-05-18) razem z APScheduler/tzlocal/tzdata — nie planuj
zadań pod nieistniejący daemon.

Wzorzec dla pracy cyklicznej: **endpoint wołany zewnętrznym cronem hostingu**,
autoryzowany tokenem (nie `@login_required` — cron nie ma sesji). Przykład
w kodzie: `/production/api/sync-cron`. Nowy wpis w crontabie trzeba dodać
ręcznie przy wdrożeniu — to element zakresu zadania, nie coś, co samo wstanie.

Autoryzacja: dekorator `cron_secret_required` z `cron_auth.py` (jeden dla wszystkich
endpointów CRON), nagłówek `X-Cron-Secret` porównywany stałoczasowo z polem
`PRODUCTION_CRON_SECRET` w `config/core.json`. **Wartości domyślnej w kodzie nie ma**:
brak pola = endpointy CRON odpowiadają 500 (zamknięte), zły nagłówek = 403. Wpis
crontaba nie trzyma sekretu: woła `scripts/cron_endpoint.sh METODA ŚCIEŻKA`, który
czyta go z `core.json` i podaje curlowi przez stdin (albo własny skrypt według tego
samego wzoru, jak `scripts/cron_close_worker_sessions.sh`).

Brak pola to log **CRITICAL**, czyli zdarzenie w Sentry (Sentry robi zdarzenia tylko
z CRITICAL i z wyjątków, a odpowiedź 500 wyjątkiem nie jest). Alarm idzie najwyżej raz
na godzinę na endpoint i worker, pozostałe wywołania logują ERROR. Nowy endpoint CRON
podpinaj pod ten sam dekorator, a nie pod własne sprawdzanie nagłówka.

Cron logistyki (od etapu 1 logistyki równoległej): `scripts/cron_endpoint.sh POST /production/api/logistics/cron`
co godzinę. Przelicza cykl logistyczny zamówień i **uruchamia w tle** dopychacz, który wysyła do Base. zaległe
zmiany sposobu dostawy, statusów i adresów (odstęp 1,5 s, jeden wątek na serwer — dzierżawa `logistyka_bl_dzierzawa`
w `prod_config`). Adres poprawiony w zakładce (dwuklik w adres) czeka na wysyłkę z flagą
`prod_orders.bl_address_pending` (`setOrderFields`: `delivery_address`, `delivery_postcode`, `delivery_city`).
Do czasu wysyłki synchronizacja z Base. nie nadpisuje adresu. Flaga znika dopiero po udanej wysyłce i tylko
wtedy, gdy adres w CRM nie zmienił się w międzyczasie. Endpoint odpowiada od razu: sync worker gunicorna ma 30 s na żądanie, więc długiej pracy
w żądaniu nie robimy. Limit API Base. (100/min na konto) wstrzymuje wysyłki logistyki do chwili z komunikatu
błędu (`logistyka_bl_wstrzymane_do`).

Od etapu 2 ten sam cron uruchamia w tle **geokoder** adresów (`logistics/services/geocoding.py`: GUGiK UUG →
Nominatim → przybliżenie; dzierżawa `logistyka_geo_dzierzawa`, Nominatim ≤ 1 zapytanie/s). Do usług idzie
wyłącznie adres. Ręczny punkt (przeciągnięta pinezka) nigdy nie jest nadpisywany automatem. Przebieg przerywa
się wcześniej tylko po 3 pełnych awariach z rzędu — pełna awaria to geokodowanie zamówienia, w którym żadne
zapytanie do usług nie dostało odpowiedzi (`BladUslugi.pelna_awaria`; adres zagraniczny pyta tylko Nominatim).
Awaria częściowa (jedna usługa odpowiedziała) i nieoczekiwany błąd pojedynczego zamówienia liczą się do błędów
przebiegu, ale go nie przerywają. Błąd usługi nigdy nie zużywa próby adresu, a po awarii nie zapisuje się
przybliżony punkt (zamówienie czeka na kolejny przebieg). Poprawka adresu w zakładce uruchamia geokoder od razu,
a trwający przebieg dobiera przed końcem zamówienia dodane albo zmienione w jego trakcie.

Od P1 priorytetów ten sam cron na końcu dopisuje brakujące szczeble drabiny i utrwala rangi produkcji
(`szczeble_uzupelnione` i `priorytety_utrwalone` w odpowiedzi; własny `try/except`, błąd tej fazy nie psuje faz
logistyki) — szczegóły w sekcji „Priorytety produkcji”.

## Deployment

### Automatyczny deploy (webhook GitHub)

Push do `main` uruchamia deploy. Ścieżka: GitHub wysyła webhook push na
`POST /deploy/webhook` (HTTPS/443) → `modules/deploy/routes.py` weryfikuje
podpis HMAC-SHA256 (`GITHUB_WEBHOOK_SECRET`) i sprawdza gałąź → odpala
`deploy.sh` przez `subprocess.Popen(start_new_session=True)`, żeby skrypt
przeżył restart gunicorna.

Kroki `deploy.sh`:
1. Lock `/tmp/crm-deploy.lock` — blokada równoległych deployów;
   `FLASK_SKIP_DOTENV=1`, żeby CLI Flaska nie czytał `.env` (gunicorn go nie czyta,
   więc bramka z kroku 5 musi widzieć to samo środowisko co gunicorn)
2. `git fetch` + `git reset --hard origin/main`
3. `venv/bin/pip install -r requirements.txt` (best-effort)
4. `flask sync-changelog` (best-effort)
5. **`flask migrate` — PRZED restartem.** Niepowodzenie PRZERYWA deploy
   i cofa kod na dysku (`git reset --hard` do poprzedniego HEAD), więc dysk,
   działający proces i schemat zostają spójne. Samo „nie restartujemy” nie
   wystarcza: gunicorn importuje `app.py` przy każdym nowym workerze (timeout,
   awaria, `max_requests`), więc nowy kod na dysku mógłby położyć serwer sam
6. `venv/bin/python scripts/przelicz_klientow_sprzedazy.py --apply` (best-effort)
   — przeliczenie denormalizacji klientów Analizy sprzedażowej
   (`sales_clients`: liczniki zamówień, `lifetime_net`, daty). Po migracjach,
   przed restartem, z `timeout -k 10 300` (proces głuchy na SIGTERM dostaje
   SIGKILL 10 s później). Błąd albo przekroczony czas zostawia
   w logu `[recount-warn]` i **nie przerywa**
   deployu — analityka nie blokuje wdrożeń reszty CRM (tablety hali, produkcja);
   liczniki poprawi następny udany przebieg
7. `sudo /usr/local/sbin/crm-fix-logs-perms.sh` — chown katalogu logów
   (bez tego gunicorn może nie wstać → nginx 502)
8. `sudo /usr/bin/supervisorctl restart crm_woodpower`

Uwaga: webhook uruchamia `deploy.sh` w wersji leżącej na dysku **przed** pobraniem
kodu. Zmiana samego `deploy.sh` działa więc dopiero od następnego deployu.
Jeśli bezpieczne wdrożenie zmiany zależy od nowej wersji `deploy.sh`, wdrażaj
**dwuetapowo**: najpierw osobny push z samym `deploy.sh` na kodzie, który na pewno
przechodzi migracje, a po `Deploy complete!` w `logs/deploy.log` push reszty.
Drugi push wcześniej niż koniec pierwszego deployu trafi w lock
(`Already deploying, skipping.`) i sam się nie wdroży.

`.github/workflows/deploy.yml` istnieje, ale ma **`on: workflow_dispatch`** —
tylko ręczne uruchomienie, jako fallback. Deploy po SSH był loteryjny przez
ochronę SSH Hostingera, stąd przejście na webhook (2026-06-24). Fallback robi
kroki 2–6 i 8 jak `deploy.sh` (migracje przed restartem, przeliczenie klientów
best-effort z tym samym `timeout -k 10 300`), bez locka i bez chown logów.

### Serwer produkcyjny

Po migracji na Hostinger KVM4 (cutover 2026-06-24, szczegóły w `MIGRATION_PLAN.md`):

- Host: crm.woodpower.pl
- Ścieżka: `/home/woodpower-crm/htdocs/crm.woodpower.pl/`
- Użytkownik systemowy: `woodpower-crm`
- App server: **gunicorn** na `127.0.0.1:8090`, pod **supervisorem**
  (program `crm_woodpower`), za nginx
- venv w katalogu aplikacji: `venv/` (Python 3.12.3 — sprawdzone na serwerze 6.10.2026; lokalny obraz Dockera też 3.12)

`passenger_wsgi.py` leży jeszcze w repo, ale jest **martwy** — pozostałość
po Passengerze na starym hostingu współdzielonym. Nie jest wejściem aplikacji.

### Ręczny deploy / restart

```bash
# na serwerze produkcyjnym
cd /home/woodpower-crm/htdocs/crm.woodpower.pl
git fetch origin main && git reset --hard origin/main
venv/bin/pip install -r requirements.txt
FLASK_SKIP_DOTENV=1 venv/bin/flask migrate \
  && { FLASK_SKIP_DOTENV=1 venv/bin/python scripts/przelicz_klientow_sprzedazy.py --apply || true; } \
  && sudo /usr/local/sbin/crm-fix-logs-perms.sh \
  && sudo /usr/bin/supervisorctl restart crm_woodpower
```
Gdy `flask migrate` padnie, NIE restartuj — wróć kodem do poprzedniego commita
(`git reset --hard <poprzedni HEAD>`), jak robi to `deploy.sh`.

Albo po prostu `./deploy.sh` — robi dokładnie to samo, z lockiem i logami.

### Ważne

- Restart to kilka sekund niedostępności. Tablety hali to przetrwają —
  akcje lądują w kolejce offline apki i dosynchronizują się same
- Hasła: produkcja używa `scrypt`, lokalnie `pbkdf2` (zgodność Werkzeug)
- Klucz sesji na serwerze: **wyłącznie** pole `SECRET_KEY` w `config/core.json`
  (czytają je gunicorn, `flask migrate` z `deploy.sh` i komendy `flask` z crona).
  **Nie** w `.env` — gunicorn go nie czyta, a `deploy.sh` celowo wyłącza go dla CLI.
  **Nie** w środowisku supervisora — nie dotarłoby do ręcznie odpalonego `./deploy.sh`,
  a zmienna ma pierwszeństwo przed core.json, więc stara wartość tam zniweczyłaby
  rotację. Bez klucza `flask migrate` kończy się błędem, deploy przerywa się
  **przed** restartem i cofa kod na dysku do poprzedniej wersji
- Pozostałe sekrety też tylko w `config/core.json`, bez wartości domyślnych w kodzie:
  `PRODUCTION_CRON_SECRET` (endpointy CRON, patrz „Zadania cykliczne”),
  `CEIDG_JWT_TOKEN` (wyszukiwanie firm w CEIDG; bez niego, gdy GUS i MF nie znajdą
  firmy, `/clients/api/gus_lookup` zwraca 503 zamiast szukać w CEIDG),
  `OPENROUTESERVICE_API_KEY` (przebieg tras logistyki po drogach, km i czas; bez niego trasy rysują się liniami
  prostymi z dopiskiem „przebieg przybliżony” — nic się nie psuje; ten sam klucz liczy „Optymalizuj trasę”, bez
  niego przycisku nie ma),
  `CARTO_BASEMAPS_KEY` (kafelki mapy logistyki; bez niego mapa ma znak wodny CARTO;
  klucz jest widoczny w przeglądarce, więc w panelu CARTO ogranicz go do domeny
  crm.woodpower.pl; limit darmowy 1 mln kafelków/mies.). Po dopisaniu klucza do
  core.json **od razu** `supervisorctl restart crm_woodpower` — zapis i restart razem
  (incydent 24.09 z `SECRET_KEY`: bez restartu gunicorn podmienia workery stopniowo
  i część działa na starej konfiguracji, część na nowej)
- Dodając zależność, pamiętaj o `requirements.txt` — deploy instaluje z niego
- API mobilne (`/api/mobile/*`) jest **niezależne** od paneli webowych
  produkcji; zmiany w `modules/production/routers/stations/` nie dotykają tabletów
- **Logistyka równoległa:** status `czeka_na_logistyke` nie jest już etapem — produkcja kończy się wejściem do
  pakowania, a sposób dostawy (`prod_orders.override_delivery_method`, NULL = „Nie ustawiono”) ustawia logistyk
  w zakładce „Logistyka”. Pakowanie bez niego przechodzi (etap 4, krok 4.6; dawniej 409 `delivery_method_not_set`):
  etykieta paczki ma pas „NIE USTAWIONO”, Base. nie dostaje statusu po spakowaniu, zamówienie zostaje otwarte w
  Logistyce, a status po spakowaniu wysyła pierwsze ustawienie sposobu (okno 8.7, „Zmień bez przepakowania”).
  Appka 1.7.3 sama blokuje ZAKOŃCZ przy nieustawionym sposobie — na tabletach działa to dopiero z nowym APK. Mapowania:
  `modules/production/logistics/sposoby.py`. Appkę tabletową z obsługą obiektu `transport` wydajemy PRZED
  backendem (stara appka pokazuje nieustawione jako „KURIER”). **Po wdrożeniu etapu 1 uruchom raz ręcznie**
  `scripts/cron_endpoint.sh POST /production/api/logistics/cron` — między migracją a restartem (przeliczenie
  klientów trwa do 300 s) stary kod wciąż zapisuje `czeka_na_logistyke`; cron przenosi takie produkty do
  pakowania (`przeniesione_z_logistyki` w odpowiedzi), inaczej do pierwszego godzinnego przebiegu nie widzi
  ich żaden tablet ani filtr. **Po wdrożeniu kroku 4.3 logistyki uruchom cron tak samo raz ręcznie, po
  restarcie** — jednorazowo przestawia pozycje już wydanych odbiorów osobistych na `dostarczone`
  (`wydane_dostarczone` w odpowiedzi; znacznik `logistyka_wydane_dostarczone` w `prod_config` blokuje kolejne
  przebiegi). Migracja tego nie robi, bo stary kod w oknie wdrożenia nie zna tej
  wartości ENUM (odczyt takiego wiersza rzuciłby `LookupError`, czyli 500 na listach). Z tego samego powodu
  wycofanie 4.3 po zapisaniu nowych statusów wymaga migracji cofającej je na `spakowane` — gotowy przepis
  w specu etapu 4, sekcja 14. **Przed wdrożeniem etapu 4 logistyki** na koncie Base. musi istnieć status
  524520 „Załadowane - trans. WoodPower” (`sposoby.STATUS_ZALADOWANE`, ustawiany po zakończeniu załadunku) —
  kod go nie zakłada; bez niego `setOrderStatus` dopychacza kończy się błędem Base., a `bl_status_pending_id`
  zostaje na zamówieniu i ponawia się co godzinę. **Etykiety paczek** (krok 4.2) drukują się zawsze przez
  kolejkę agenta druku (`prod_print_queue`, niezależnie od `LABEL_PRINTER_USE_AGENT`; tryb TCP dotyczy tylko
  etykiet produktów): przed wdrożeniem na hubie hali nowy `tools/print_agent/print_agent.py` z sekcją
  `[printer:wysylka]` w `config.ini` (kalibracja `--kalibruj wysylka`). Bez działającego agenta zadania paczek
  wygasają po godzinie, a nieudany albo wygasły druk cofa znacznik wydruku paczki (operator widzi, że etykiety
  nie ma, i drukuje ponownie). **Od P1 priorytetów** trasa robocza albo zatwierdzona ma szczebel na drabinie
  priorytetów (`drabina.zapewnij_szczebel_trasy` pod blokadą tras w `routes.utworz`), a akcje tras, zmiana sposobu
  dostawy, „Wydane klientowi”, Dostawa i „Cofnij do pakowania” przeliczają rangi produkcji po commicie
  (`kolejka.utrwal_po_commicie`; w API mobilnym przez plan wykonywany po commicie w `with_idempotency`) — patrz
  „Priorytety produkcji”.
- **Trasy logistyki — jeden piszący naraz:** każda funkcja, która zmienia trasy albo przystanki (także zmiana
  sposobu dostawy, adresu i pinezki zamówienia z trasy oraz nazwy pojazdu; pod tą samą blokadą idzie też
  „Wydane klientowi”, które zaraz po niej blokuje także zamówienie i wszystkie jego pozycje —
  `blokady_zamowien.zablokuj_zamowienie`, bo telefon Weryfikacji blokady tras nie bierze — i decyduje na tych
  obiektach), bierze **najpierw** blokadę `routes.zablokuj_trasy()` (`logistics/services/routes.py`):
  `FOR UPDATE` na wierszu `prod_config` `logistyka_trasy_blokada`, który zakłada migracja
  `2026-09-27-logistyka-trasy-flota.sql`. Nowy zapis tras też musi zaczynać od tej blokady, inaczej kolejność
  blokad się rozjedzie (MySQL 1213). Stan, na którym zapis decyduje, czyta po blokadzie **odczytem bieżącym**
  (`with_for_update()` albo `with_for_update(read=True)` + `populate_existing()`, jak `routes.dodaj_przystanki`)
  albo zaczyna transakcję od nowa: `db.session.commit()` tuż przed blokadą, bez żadnego odczytu pomiędzy (także
  atrybutów ORM), jak `_zapis_pod_blokada()` w `logistics/routers/panel_api.py`. Zwykły SELECT w tej samej
  transakcji widzi migawkę sprzed blokady: MySQL pracuje na REPEATABLE READ, a migawka powstaje przy pierwszym
  zwykłym odczycie transakcji (już w `before_request`), nie przy wzięciu blokady. Baza, która wykonała starszą
  wersję pliku migracji, nie ma wiersza blokady (runner pamięta migracje po nazwie pliku): na MySQL kod zakłada
  go sam (`INSERT IGNORE`, WARNING w logu), a na innych bazach zapisy tras nie są wtedy serializowane.
  **Dostawa (krok 4.4, `logistics/services/dostawa.py`)** — telefon kierowcy (`/api/mobile/delivery/*`) i przejścia
  z panelu tras (odhaczenie z odznaczeniem przystanków, czyli „Niedostarczone” z panelu, „Cofnij załadunek”, „Cofnij
  dostarczenie”, „Cofnij niedostarczenie”, „Zdejmij z trasy” niedostarczonego, „Cofnij zatwierdzenie” trasy ze
  znacznikami załadunku — bez znaczników ta ostatnia bierze tylko blokadę tras): [pracownicy, tylko telefon] →
  blokada tras → blokada deklaracji paczek → zamówienia CAŁEJ trasy rosnąco po id → paczki → pozycje; decyzje na
  odczycie bieżącym, a odpowiedź telefonu (pełna trasa) z tych samych blokad. Zakleszczenie 1213 — jedno ponowienie
  całego zapisu (`dostawa_api._zapis`, `trasy_api._akcja`, niżej).
  **Doróbka, zmiana z Base. i hurtowa zmiana statusu też biorą blokadę tras NAJPIERW**, przed blokadami zamówień
  (decyzja Konrada 2.10, Ruling 30): zamówienie z przystankiem na trasie załadowanej albo w drodze, które wraca do
  produkcji, doróbka i zmiana z Base. zdejmują z trasy jak „Niedostarczone” (`dostawa.zdejmij_z_trasy_w_drodze`,
  Base. 417343), a hurt mu odmawia (odmowa w `errors`, 409 gdy obejmuje wszystko); status trasy czytają odczytem
  bieżącym pod tą blokadą. Doróbka i zmiana z Base. blokują wtedy całą trasę w kolejności Dostawy
  (`dostawa.blokady_trasy_w_drodze`), bo zdjęcie może ją zamknąć. **„Niedostarczone” zostaje na trasie do jej końca**
  (U10, decyzja Konrada 2.10, Ruling 32 w specu etapu 4): stan na przystanku (`prod_route_stops.not_delivered_*`,
  pozycje dalej `zaladowane`, Base. bez zmian), a do puli zamówienie schodzi przy zamknięciu trasy (każdy przystanek
  dostarczony albo niedostarczony; `dostawa._zdejmij_niedostarczone` przed ustawieniem `wykonana`, na krotce
  `zablokuj` — także w zamknięciu po doróbce) albo przez „Zdejmij z trasy” w panelu. `order_id` przystanku jest
  UNIQUE, więc historia zdjętych idzie z logu (`dostawa.niedostarczone_zdjete`, indeks `route_id`); odpowiedź zapisu
  telefonu czyta ją odczytem bieżącym pod blokadą tras. Powtórkę „Niedostarczone” rozpoznaje ostatni wpis ROZLICZENIA
  zamówienia (`dostawa.AKCJE_ROZLICZENIA`), nie ostatni wpis logu. Transport własny zamyka się po `dostarczone`
  na pozycjach (reguła nie czyta tras); siatka crona otwiera transport zamknięty po znaczniku
  `logistyka_weryfikacja_od` z pozycją niedostarczoną.
- **Deklaracje paczek — jedna naraz:** `paczki.zablokuj_deklaracje()` (wiersz `logistyka_paczki_blokada` w
  `prod_config`, migracja `2026-09-30-logistyka-paczki-blokada.sql`) przed blokadą zamówienia; dwie pierwsze
  deklaracje różnych zamówień bez niej zakleszczały się na luce indeksu `prod_packages` (MySQL 1213).
  Zapisy telefonu Weryfikacji (`/api/mobile/verification/*`) biorą tę samą blokadę: pracownicy →
  `paczki.zablokuj_deklaracje()` → zamówienie po PK → paczki → pozycje (`paczki.zablokuj_stan`) i decydują na
  odczycie bieżącym; deklaracja paczek tak samo, z wstępną odmową „nie w całości spakowane” przed blokadą pozycji.
  Reguła `weryfikacja.uniewaznij_etapy` (powrót pozycji do produkcji) blokady globalnej nie bierze; gdy ma pracę,
  potwierdza ją odczytem bieżącym w tej samej kolejności. Hurtowa zmiana statusu i zmiana sposobu dostawy w panelu
  (obie po blokadzie tras) oraz cron logistyki blokują zamówienia rosnąco po id; hurt i przeniesienie
  osieroconych w cronie potem także wszystkie pozycje tych zamówień (jak niżej). **Zamówienie najpierw**
  (krok 4.4a): ZAKOŃCZ i wejście do pakowania na tabletach (`POST /api/mobile/orders/<id>/complete`), doróbka
  (`reject_product_quantity`), zmiany z Base. (`apply_baselinker_changes`), druk etykiet całego zamówienia w trybie
  agenta i przeniesienie osieroconych w cronie blokują wiersz zamówienia, potem wszystkie jego pozycje — jednym
  odczytem bieżącym po `order_id` (`services/blokady_zamowien.zablokuj_pozycje`; tak samo `paczki.zablokuj_stan`),
  zanim cokolwiek zapiszą. Widać więc też pozycje dodane albo usunięte tuż przed blokadą, a zablokowane obiekty
  sesja trzyma silnymi referencjami (mapa tożsamości SQLAlchemy trzyma czyste obiekty słabo — bez tego późniejsze
  `pozycja.order` czytałoby zamówienie od nowa ze starej migawki REPEATABLE READ). Nowy zapis pozycji zamówienia
  zaczyna od tej samej blokady. Wywołanie Base. (HTTP) idzie przed blokadami; id zamówienia czytamy jeszcze w starej
  transakcji (powiązanie z `baselinker_order_id` się nie zmienia), potem `commit`, blokada tras i blokada zamówienia —
  między commitem a blokadą zamówienia same odczyty blokujące. Cron logistyki commituje każdą fazę osobno. **Pisarz pozycji bez blokady zamówienia zapisuje
  pozycje jednym flushem rosnąco po PK i potem nie sięga po wiersz zamówienia — także pośrednio, przez INSERT do
  tabeli z FK do `prod_orders` (`prod_logistics_log`, `prod_packages`, `prod_route_stops`).** Jeden flush to: odczyt
  pozycji, potem same przypisania i zapis przy commicie (SQLAlchemy sortuje UPDATE-y jednego mappera po PK); każde
  zapytanie pomiędzy autoflushuje, a dwa flushe są rosnące każdy z osobna, razem już nie. Reguła wystarcza wobec
  pisarzy jednego zamówienia (ZAKOŃCZ, doróbka, Base., druk); hurt, przeniesienie osieroconych i Dostawa (pozycje
  wszystkich zamówień trasy — trasa robocza i zatwierdzona może mieć zamówienia w produkcji, a doróbka dokłada
  starszemu zamówieniu pozycję o wyższym id) blokują pozycje zamówienie po zamówieniu, czyli w kolejności
  (zamówienie, id), więc z pisarzem wielu zamówień bez blokady zamówień rzadkie 1213 jest nadal możliwe (hurt
  i Dostawa ponawiają raz). Tak piszą liczniki sztuk
  (`PATCH …/quantity`, edycja sztuk w panelu admina), faza 2 crona logistyki (`delivery.dostarcz_wydane`:
  jednorazowe przestawienie pozycji zamówień wydanych klientowi, we własnej transakcji, bez blokad zamówień), druk
  etykiet w trybie TCP i druk pojedynczej etykiety (`print_labels_batch`, zapis w końcowym commicie). Licznik sztuk
  czyta też zwykłym odczytem wiersz stołu stanowiska (bramka stołu), niczego w stole nie zapisując. Przeliczenie
  priorytetów **nie jest już** takim pisarzem: `kolejka.utrwal()` (własna sesja) blokuje zamówienia przed pozycjami
  (sekcja „Priorytety produkcji”), a przeciąganie, hurtowa zmiana priorytetu (`bulk-action` z `update_priority`)
  i ręczna gwiazdka pozycji (`set-priority`) zostały usunięte w P1 priorytetów. Akcje tras (`routes.py`, przez `delivery.podbij_pozycje`)
  chroni dziś sama kolejność flushu (INSERT z FK do `prod_orders`, czyli blokada S na zamówieniu, idzie przed
  UPDATE pozycji) — to przypadek, nie reguła: nowy zapis statusów pozycji pod blokadą tras bierze
  `blokady_zamowien.zablokuj_zamowienia(ids)` zaraz po `routes.zablokuj_trasy()`. Znane wyjątki, bez naprawy:
  hurtowe usunięcie pozycji (`bulk-action` z `delete`, tylko admin) — bez doróbek DELETE-y idą jednym flushem
  rosnąco, ale gdy wśród usuwanych jest pozycja z doróbką, SQLAlchemy porządkuje zapisy według zależności
  oryginał–doróbka, nie po PK: doróbka (wyższe id) dostaje UPDATE `original_product_id = NULL` albo DELETE przed
  DELETE oryginału, także przy usuwaniu całego zamówienia (naprawa: zamówienia, potem ich pozycje, jak w hurtowej
  zmianie statusu);
  ręczna synchronizacja z `force_update`, która dopisuje pozycje istniejącym zamówieniom, i `sync-cron`
  (`sync_paid_orders_only`) przy ponownym imporcie istniejącego zamówienia — ta sama klasa wyjątku, dziś
  nieaktywna, bo cron importu nie jest uruchamiany; gdyby miał wrócić, trzeba najpierw dodać blokadę zamówienia.
  Na rzadkie zakleszczenie z takim wyjątkiem zmiana sposobu dostawy w panelu, hurtowa zmiana statusu, zapisy
  Dostawy (telefon kierowcy — ponowienie wewnątrz handlera, wpis idempotencji raz — i akcje Dostawy w panelu tras),
  zapisy panelu priorytetów (gwiazdki, drabina, „Wyślij”, „Zdejmij”, „Przygotuj stoły” —
  `priorytety/routers/panel_api.py`), dopełnianie stołu (`GET desk`) oraz przeliczenie priorytetów (`kolejka.utrwal`,
  na nowej własnej sesji) odpowiadają jednym automatycznym ponowieniem: rollback i cały zapis od nowa, z decyzją na nowym stanie
  (`blokady_zamowien.kod_mysql`); drugie 1213 kończy się odpowiedzią 500 z rollbackiem (samo `utrwal` nie rzuca —
  zwraca `success: False`).

### Priorytety produkcji

Od P1 priorytetów (2026-10) kolejność pracy wyznacza **drabina biura**, a nie algorytm z `priority_service` (data
opłacenia i grupowanie tygodniowe). Kod: pakiet `modules/production/priorytety/` (`stale.py`, `models.py`, serwisy
`kolejka`, `drabina`, `gwiazdki`, `ustawienia`, `stol`, `sygnaly`, `lista`, `widok`, router `routers/panel_api.py` pod
`/production/api/priorytety`). Kontrakt appki tabletowej: `docs/api-mobile-priorytety.md`.

**Model.** Drabina to wiersze `prod_priority_rungs`: szczeble gwiazdek (stałe) oraz ruchome szczeble tagów
(`po_terminie`, `blisko_terminu`, `rozpoczete`) i tras. Gwiazdki 0–5 są na **zamówieniu**
(`prod_orders.priority_stars`), nie na pozycji. Trasa robocza albo zatwierdzona ma własny szczebel
(`drabina.zapewnij_szczebel_trasy` pod blokadą tras w `routes.utworz`); po załadunku szczebel znika z widocznej
drabiny. Ranga zamówienia (`prod_orders.priority_rank`, `priority_rung`) i pozycji (`prod_products.priority_rank` =
ranga zamówienia × 100 + kolejność pozycji; doróbka ma 0, `is_priority` jest pochodną) to **pamięć podręczna**: liczy
ją czysta funkcja `kolejka.policz` na migawce, a zapisuje `kolejka.utrwal()`. Panel biura (drabina, cała kolejka,
modal priorytetu) liczy na żywo; tablety, monitory hali i lista Lakierni czytają kolumny, więc tag terminowy albo
„Rozpoczęte” może być na nich spóźniony do najbliższego `utrwal()`. Wyjątek: kolejność pobierania na stół liczy
„Rozpoczęte” na żywo ze statusów pozycji (`kolejka.kandydaci_stanowiska`), dlatego ZAKOŃCZ nie przelicza rang.
`priority_service.py` jest do P4 warstwą zgodności (import z Base. woła przez nią `kolejka.utrwal`);
`lock_priority`/`unlock_priority` pozycji są puste.

**`kolejka.utrwal()` — wołać wyłącznie po commicie.** Pracuje na własnej sesji i przypiętym połączeniu, nigdy na
`db.session`: migawka zwykłym odczytem → zamówienia `FOR UPDATE` rosnąco po id (tylko te, którym coś się zmienia) →
ich pozycje `FOR UPDATE` (`order_id IN (…) ORDER BY id`) → zapis zmienionych wierszy → commit. Nie bierze blokady tras
ani stołu. Router woła `kolejka.utrwal_po_commicie()` po własnym commicie; handler API mobilnego pod
`with_idempotency` tylko planuje (`kolejka.zaplanuj_po_commicie()`), a dekorator wykonuje plan po udanym commicie. Na
cudzą blokadę `utrwal` czeka **najwyżej 5 s** (`kolejka.LIMIT_CZEKANIA_NA_BLOKADE_S`, sesyjny
`innodb_lock_wait_timeout` przywracany przed oddaniem połączenia do puli): MySQL 1205 → raport `success: False` bez
ponowienia, 1213 → jedno ponowienie na nowej sesji. Wołający z niezatwierdzonym zapisem zamówienia albo pozycji
dostaje więc `success: False` po 5 s, a nie wisi do limitu serwera. Po zapisie `utrwal` czyta migawkę od nowa i
poprawia różnice — najwyżej 3 przebiegi na próbę (zapis, poprawka, kontrola; gdy i trzeci coś zmienił, kończy z
ostrzeżeniem w logu) — dwa przeliczenia naraz nie zostawiają mieszanki rang. `utrwal` nigdy nie rzuca; nieudane
przeliczenie nie cofa zapisu, który je wywołał (rangi nadrabia cron). Wyzwalacze: gwiazdki, drabina i próg „Blisko
terminu” w panelu priorytetów oraz ręczne przeliczenie `POST /production/api/priorytety/przelicz` (admin; sama
końcówka, bez przycisku w panelu); akcje tras (`trasy_api._akcja`; utworzenie i usunięcie trasy wołają przeliczenie
same), zmiana sposobu dostawy i „Wydane klientowi” w panelu Logistyki; Dostawa i „Cofnij do pakowania” (plan po
commicie); hurtowa zmiana statusu i zmiany z Base. w panelu; import z Base.; cron logistyki. ZAKOŃCZ, Odłóż, licznik
sztuk i doróbka rang nie przeliczają.

**Panel priorytetów** (`priorytety/routers/panel_api.py`): zapisy drabiny, gwiazdek i stołu („Wyślij”, „Zdejmij”,
„Przygotuj stoły”) idą wzorem commit → blokada → zapis → commit (`_zapis_z_ponowieniem`: jedno ponowienie po 1213),
bez żadnego odczytu między commitem a pierwszą blokadą; po commicie drabina i gwiazdki przeliczają rangi, a akcje
stołu wysyłają sygnał. Gwiazdki blokują zamówienia rosnąco po id (`blokady_zamowien.zablokuj_zamowienia`), bez blokady
tras. Drabina zaczyna od `routes.zablokuj_trasy()` i czyta szczeble odczytem bieżącym; klient podaje `oczekiwane`
(kolejność, którą widział) i przy innej drabinie dostaje 409 `drabina_zmieniona`. `PUT …/ustawienia` zapisuje bez
blokad i bez ponowienia. Samonaprawa drabiny w `GET /drabina` (brakujący szczebel) idzie poza tym wzorem: commit →
blokada tras → `drabina.uzupelnij` → commit, bez ponowienia i bez przeliczenia rang.

**Stół stanowiska (`prod_station_desk`) — dwie klasy pisarzy.** *Pisarze zamówienia* (ZAKOŃCZ, Odłóż, hurtowa zmiana
statusu, doróbka, zmiany z Base., przeniesienie osieroconych w cronie) po blokadach z reguły „Zamówienie najpierw”
dotykają wierszy stołu **wyłącznie własnego zamówienia**: własnego kafla po kluczu unikalnym (`station_code` +
`unit_key`: `p:<id pozycji>` albo `o:<id zamówienia>`) albo wierszy po `order_id` — przez
`stol.zdejmij_nieaktualne(order)`, które samo zaczyna od `flush` (jedna reguła uzgadniania stołu u pięciu pisarzy;
Odłóż blokuje tylko własny kafel). Blokady stanowiska nie biorą, więc nie stoją za dopełnianiem w kolejce do niej;
mogą najwyżej poczekać, aż dopełnianie trzymające już blokady S ich zamówienia zrobi commit (bez cyklu). *Pisarze
stołu* (`stol.dopelnij`, `stol.wyslij`, `stol.zdejmij_przez_biuro`, `stol.przygotuj_start`): router commituje, a
pierwszym odczytem nowej transakcji jest `stol.zablokuj_stanowisko` (wiersz `prod_config` `priorytety_blokada_<S>`
`FOR UPDATE`; brakujący wiersz kod zakłada na MySQL przez `INSERT IGNORE`, jak blokadę tras) → zamówienia `FOR SHARE`
rosnąco po id (w SQL z SQLAlchemy 1.4 to `LOCK IN SHARE MODE`) → wszystkie ich pozycje `FOR SHARE` w kolejności
(`order_id`, `id`) → wiersze stołu **zwykłym** odczytem → INSERT → commit → sygnał. Dopełnianie i start stołów blokują
tak wszystkie zamówienia z pozycją w statusie stanowiska, „Wyślij” tylko zamówienie z żądania, „Zdejmij” tylko
zamówienie kafla; „Wyślij” i „Zdejmij” czytają do tego własne kafle odczytem bieżącym po kluczu unikalnym. Pisarz
stołu nigdy nie bierze blokad X zamówień ani pozycji, nigdy blokady tras. **Nikt nie blokuje wierszy stołu całego
stanowiska** (dawało to cykl indeks wtórny ↔ klucz główny z ZAKOŃCZ): odczyt bieżący stołu ma tylko dwa kształty —
równość po całym kluczu unikalnym albo `order_id` zablokowanego zamówienia. Limit odłożeń jest miękki (zwykły `COUNT`
z migawki żądania; dwa Odłóż naraz mogą go przekroczyć o 1). Znane wyjątki bez `zdejmij_nieaktualne`: hurtowe
usunięcie pozycji (`bulk-action` z `delete`) — kafel `o:` zamówienia bez pozycji na stanowisku zostaje jako „widmo”
(zakładka Stanowiska pokazuje je w „Do zdjęcia ze stołu”) — oraz ręczna synchronizacja z `force_update`: dopisana
pozycja czyni zamówienie niekompletnym, a jego kafel `o:` zostaje na stole jako zwykły kafel. W obu przypadkach kafel
zdejmie biuro albo następny pisarz zamówienia. Nowy zapis rang albo stołu zaczyna od tych samych zamków w tej
kolejności.

**Dopełnianie tylko w `GET desk`.** `stol.dopelnij` woła wyłącznie `GET /api/mobile/stations/<S>/desk` i tylko w
trybie `stol` — nigdy w transakcji ZAKOŃCZ (ta trzyma X na swoim zamówieniu, a dopełnienie czyta pozycje innych
zamówień: dwa tablety zamknęłyby cykl). W transakcji dopełnienia każde czekanie odczytów blokujących (blokada
stanowiska, zamówienia, pozycje) trwa **najwyżej 5 s** (`stol.krotkie_czekanie_na_blokady`; czekania na kolejne
blokady mogą się sumować — zmierzone do 9 s — stąd limit żądania `desk` w appce co najmniej 15 s); INSERT-y kafli idą
przy commicie routera, już z limitem serwera. Po 1205 `desk` nie ponawia i oddaje 200 z bieżącym stołem bez
dopełnienia, po 1213 ponawia raz (drugie → 500 `desk_failed`). W czasie czekania trzyma już blokady S zamówień o
niższych id, więc ZAKOŃCZ kafla takiego zamówienia czeka razem z nim (do 5 s). W trybie `stary` `GET desk` tylko
czyta: handler bez commita, blokady stanowiska, dopełniania i sygnału (jedyny zapis żądania to znacznik kontaktu
urządzenia w `require_device_token`, jak w każdej końcówce API mobilnego); oddaje pole `tryb` i bieżące wiersze stołu
(np. kafle startowe), a ZAKOŃCZ także w tym trybie zdejmuje kafel. Doróbka wchodzi na stół pierwsza, **w ramach K**;
ponad K stół wychodzi tylko przez kafle `biuro` („Wyślij na stanowisko”) i `start`. Formatowanie i Pakowanie pracują
zamówieniami: na stół wchodzą zamówienia kompletne na stanowisku, niekompletne są w osobnej sekcji.

**Ustawienia, bramka, wersja appki.** Klucze `prod_config` na stanowisko: `priorytety_tryb_<S>` (`stary` | `stol`),
`priorytety_stol_<S>` (K miejsc, 1–5), `priorytety_jednostka_<S>` (`pozycja` | `zamowienie`),
`priorytety_limit_odlozen_<S>`; wspólne: `priorytety_blisko_terminu_dni` (domyślnie 3 dni robocze) i
`priorytety_min_app_version_code`. `ustawienia.*` czytają `prod_config` wprost, bez pamięci podręcznej
`config_service` — zmiana działa od razu na wszystkich workerach (wyjątek: liczby dni terminu import z Base. czyta
przez `config_service`, do 60 minut na proces). Jedyna droga zapisu to `PUT /production/api/priorytety/ustawienia`
(karty „Terminy” i „Stół stanowisk” w Konfiguracji; także `DEADLINE_DEFAULT_DAYS`, `DEADLINE_FINISHED_DAYS`,
`DEADLINE_DAY_TYPE`) — `update-config` i `update-configs` tych kluczy nie przyjmują (wyjątek: `POST
/production/api/reset-configs` przywraca klucze `DEADLINE_*` do wartości domyślnych, bez wpisu w logu priorytetów).
Zapis ustawień nie bierze blokady: dwa równoczesne zapisy klucza, którego wiersza jeszcze nie ma w `prod_config`,
kończą się jednym 500 `blad_serwera` (drugi przechodzi, powtórka też). Bramka (`stol.bramka_zakoncz`: ZAKOŃCZ i
licznik sztuk) działa tylko w trybie `stol` i tylko dla nowej appki (przy progu > 0: `last_app_version_code` z
heartbeatu ≥ próg; tablet bez heartbeatu jest „stary”): pozycja, która nie czeka na tym stanowisku → 409
`pozycja_poza_stanowiskiem`, kafel poza stołem i odłożonymi → 409 `nie_na_stole` (na stanowisku zamówieniowym pozycje
zamówienia niekompletnego przechodzą). Oba 409 nie zapisują wpisu idempotencji. `PUT …/ustawienia` odmawia
wprowadzenia stanu „stół przy progu wersji 0” — włączenia `stol` przy progu 0 albo obniżenia progu do 0 przy włączonym
stole (400 `prog_wersji_wymagany`) — bo stół objąłby wtedy także starą appkę. Lakiernia nie ma stołu nigdy
(`ustawienia.STANOWISKA_BEZ_STOLU`): `desk` i `postpone` oddają 409 `stanowisko_bez_stolu`, bramka ją przepuszcza, a
lista `/stations/painting/orders` jest ułożona grupami wykończenia (`lista.porzadek_listy`).

**Sygnały dla tabletów** (`priorytety/services/sygnaly.py`, `realtime_service.publish_station_signal`): najpierw baza,
potem sygnał `station:<kod>` bez danych (`{"kind": "station", "station": "<kod>"}`) — tablet po sygnale woła `GET
desk`. Pod `with_idempotency` handler tylko planuje (`sygnaly.zaplanuj`), a dekorator wysyła po commicie jako pierwszy
z pięciu haków (sygnały stanowisk, status Base., sygnał agenta druku, dopychacz logistyki, zaplanowane `utrwal`) i
porzuca plan przy rollbacku; routery panelu, `desk`, import i cron wysyłają po własnym commicie. Publikacja nie rzuca,
ale jest synchroniczna (0,3 s na połączenie, 0,7 s na odpowiedź): broker, który przyjmuje połączenia i nie odpowiada,
dokłada do akcji do 0,7 s na sygnał (ZAKOŃCZ ma zwykle dwa: to stanowisko i następne; na Pakowaniu jeden); broker
wyłączony albo odrzucający połączenie nie dokłada nic. Token i kanały daje `GET /api/mobile/realtime-token`; przy
`REALTIME.enabled=false` odpowiada 503, sygnałów nie ma i tablet zostaje przy samym odpytywaniu `desk`. Sygnały
wymagają na serwerze brokera z przestrzenią nazw `station` (wzór: `ops/centrifugo/config.example.json`); bez niej
publikacja się nie udaje i tablety też zostają przy odpytywaniu.

**Cron.** `/production/api/logistics/cron` po fazach logistyki dopisuje brakujące szczeble (`drabina.uzupelnij()` pod
blokadą tras) i woła `kolejka.utrwal()` — tagi terminowe zmieniają się z datą, więc bez crona rangi stałyby do
pierwszego zdarzenia. W odpowiedzi są `szczeble_uzupelnione` i `priorytety_utrwalone` (raport `utrwal`); po błędzie
fazy oba są `null`, a cron kończy się normalnie.

**Wdrożenie i start stołów.** Priorytety wchodzą jednym wdrożeniem z logistyką etapów 1–4 (migracje
`2026-10-05-priorytety-produkcji.sql` i `2026-10-06-priorytety-stol-zrodlo.sql`; migracja nie liczy rang). **Po
restarcie uruchom raz ręcznie** `scripts/cron_endpoint.sh POST /production/api/logistics/cron` (ten sam przebieg,
którego wymaga logistyka): liczy rangi nowym algorytmem — w odpowiedzi `priorytety_utrwalone.success: true`. Po
wdrożeniu wszystkie stanowiska są w trybie `stary`, a próg wersji to 0: nowa appka zostaje na liście. Start stołów
robi administrator w Konfiguracji (karta „Stół stanowisk”, sekcja „Start stołów”; „Przygotuj stoły” i „Włącz stoły”
wymagają roli admina): podgląd `GET /production/api/priorytety/start`, „Przygotuj stoły” `POST
/production/api/priorytety/start/przygotuj` po zakończeniu zmiany (pozycje czekające na stanowisku z licznikiem
`quantity_done_<S>` > 0 stają się kaflami `start`, na stanowisku zamówieniowym — ich zamówienia; można powtarzać),
potem „Włącz stoły” — jeden `PUT …/ustawienia` z progiem wersji = kod nowej appki i trybem `stol` dla sześciu
stanowisk. Wycofanie stołów to tryb `stary` w Konfiguracji, bez wdrożenia. Zmiana trybu nie wysyła sygnału: tablet
zauważa ją przy najbliższym `desk` — po „Włącz stoły” w ciągu 30 s (na liście appka pyta `desk` co 30 s), po wycofaniu
do 30 s przy niepełnym stole i do 5 min przy pełnym.

**Sprawdzone na MySQL (krok K5, 5.10.2026):** 34 tryby wyścigów, 1222 przebiegi i trzy próby obciążeniowe — zero
zakleszczeń bez ponowienia, zero zdublowanych, nieaktualnych i niekompletnych kafli na stole. Jedyne 1213 (8 razy,
każde z udanym ponowieniem) dały dwa „Wyślij” naraz na puste stoły różnych stanowisk (luka indeksu unikalnego stołu).
Nazwy trybów i wyniki: spec priorytetów, sekcja 16.8.
## Architecture

### Application Structure
- **app.py**: Flask application factory with `create_app()`, blueprint registration, and core routes (login, password reset)
- **extensions.py**: Centralized Flask extensions initialization (SQLAlchemy, Flask-Mail, Flask-Login)
- **config/core.json**: Runtime configuration (database, mail, API keys) - copy from `core.json.example`

### Module System
19 independent Flask blueprints in `modules/`. Each module follows this pattern:
```
module_name/
├── __init__.py      # Blueprint initialization
├── models.py        # SQLAlchemy ORM models
├── routers.py       # Route handlers (or routers/ subdirectory)
├── services/        # Business logic
├── templates/       # Jinja2 templates
└── static/          # Module-specific CSS/JS
```

Key modules:
- **production**: Production order management with BaseLinker sync (largest module)
- **calculator/public_calculator**: Pricing calculation engine
- **quotes**: Quote management with public token access
- **users**: Authentication, permissions, user management
- **dashboard**: Analytics, changelog, user activity tracking
- **ai_assistant**: Google Generative AI integration

### Blueprint Registration
Blueprints are registered in `app.py:register_blueprints_lazy()` with URL prefixes like `/calculator`, `/production`, `/quotes`, etc.

### Database
- MySQL with PyMySQL connector (SQLite fallback)
- Connection pooling configured: pool_size=10, max_overflow=20, pool_recycle=280
- All models use SQLAlchemy ORM

### Authentication
- Flask-Login with session management
- Role-based access: admin, partner, user
- Permission service in `modules/users/services/permission_service.py`
- Token-based password reset and invitation system

### Logging
Two logging systems in `modules/logging/`:
- `AppLogger`: Traditional file + console logging
- `StructuredLogger`: JSON-compatible structured logging
- Logs stored in `modules/logging/logs/`

### External Integrations
Configured in `config/core.json`:
- BaseLinker API (e-commerce sync)
- Google Generative AI (AI assistant)
- SMTP mail server
- GlobKurier shipping API
- CEIDG API (`CEIDG_JWT_TOKEN`, wyszukiwanie firm po NIP — fallback po GUS i MF)
- CARTO Basemaps (`CARTO_BASEMAPS_KEY`, kafelki mapy logistyki)
- OpenRouteService (`OPENROUTESERVICE_API_KEY`, przebieg tras transportu własnego)

Bez konfiguracji w core.json (geokoder logistyki, `logistics/services/geocoding.py`, tylko z wątku w tle):
- GUGiK UUG (`services.gugik.gov.pl/uug/`, oficjalne punkty adresowe PRG, tylko Polska; odstęp 0,2 s)
- Nominatim (OpenStreetMap; najwyżej 1 zapytanie/s, własny `User-Agent`)

## Key Patterns

### Service Layer
Business logic is separated from routes into `services/` directories. Example: `modules/dashboard/services/user_activity_service.py`

### Request Lifecycle
- `@app.before_request`: Session extension, user activity tracking
- `@app.context_processor`: Injects user info into templates
- `@app.teardown_appcontext`: Database session cleanup with rollback on errors

### Error Handling
Global handlers for `ResourceClosedError` and `OperationalError` with automatic rollback and structured logging.
