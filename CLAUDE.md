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
- venv w katalogu aplikacji: `venv/` (Python 3.9)

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
  w zakładce „Logistyka”. Pakowanie bez niego: API mobilne zwraca 409 `delivery_method_not_set`. Mapowania:
  `modules/production/logistics/sposoby.py`. Appkę tabletową z obsługą obiektu `transport` wydajemy PRZED
  backendem (stara appka pokazuje nieustawione jako „KURIER”). **Po wdrożeniu etapu 1 uruchom raz ręcznie**
  `scripts/cron_endpoint.sh POST /production/api/logistics/cron` — między migracją a restartem (przeliczenie
  klientów trwa do 300 s) stary kod wciąż zapisuje `czeka_na_logistyke`; cron przenosi takie produkty do
  pakowania (`przeniesione_z_logistyki` w odpowiedzi), inaczej do pierwszego godzinnego przebiegu nie widzi
  ich żaden tablet ani filtr.

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
