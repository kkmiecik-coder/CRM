# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WoodPower CRM - A Flask-based CRM application for manufacturing/production management. Features include pricing calculator, client management, production order tracking, 3D AR previews, quote management, and AI assistant integration.

## Development Workflow

### Local Development (Docker)

Codzienny start (kontenery NIE wstają same po zamknięciu Docker Desktop):
```bash
cd <katalog repo> && docker compose up -d    # np. ~/Documents/GitHub/CRM
```

Pierwszy raz / po zmianie Dockerfile lub requirements.txt:
```bash
docker compose up -d --build
```

App: http://localhost:5000 (Flask dev server, auto-reload przy zmianie plików).
MySQL 8.4: port 3306 na hoście (wolumen `db_data` — dane przeżywają restart kontenerów).

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
# CLI command to create schema and admin user
flask setup-db

# Or set RUN_DB_SETUP: true in config/core.json for auto-setup on startup
```

### Zadania cykliczne (cron)

**Nie ma żadnego schedulera w aplikacji.** `scheduler_daemon.py` został usunięty
commitem `0684949` (2026-05-18) razem z APScheduler/tzlocal/tzdata — nie planuj
zadań pod nieistniejący daemon.

Wzorzec dla pracy cyklicznej: **endpoint wołany zewnętrznym cronem hostingu**,
autoryzowany tokenem (nie `@login_required` — cron nie ma sesji). Przykład
w kodzie: `/production/api/sync-cron`. Nowy wpis w crontabie trzeba dodać
ręcznie przy wdrożeniu — to element zakresu zadania, nie coś, co samo wstanie.

## Deployment

### Automatyczny deploy (webhook GitHub)

Push do `main` uruchamia deploy. Ścieżka: GitHub wysyła webhook push na
`POST /deploy/webhook` (HTTPS/443) → `modules/deploy/routes.py` weryfikuje
podpis HMAC-SHA256 (`GITHUB_WEBHOOK_SECRET`) i sprawdza gałąź → odpala
`deploy.sh` przez `subprocess.Popen(start_new_session=True)`, żeby skrypt
przeżył restart gunicorna.

Kroki `deploy.sh`:
1. Lock `/tmp/crm-deploy.lock` — blokada równoległych deployów
2. `git fetch` + `git reset --hard origin/main`
3. `venv/bin/pip install -r requirements.txt` (best-effort)
4. `flask sync-changelog` (best-effort)
5. **`flask migrate` — PRZED restartem.** Niepowodzenie PRZERYWA deploy:
   kod jest pobrany, ale proces chodzi dalej na starym, więc stary kod
   i stary schemat zostają spójne
6. `sudo /usr/local/sbin/crm-fix-logs-perms.sh` — chown katalogu logów
   (bez tego gunicorn może nie wstać → nginx 502)
7. `sudo /usr/bin/supervisorctl restart crm_woodpower`

`.github/workflows/deploy.yml` istnieje, ale ma **`on: workflow_dispatch`** —
tylko ręczne uruchomienie, jako fallback. Deploy po SSH był loteryjny przez
ochronę SSH Hostingera, stąd przejście na webhook (2026-06-24).

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
venv/bin/flask migrate
sudo /usr/bin/supervisorctl restart crm_woodpower
```

Albo po prostu `./deploy.sh` — robi dokładnie to samo, z lockiem i logami.

### Ważne

- Restart to kilka sekund niedostępności. Tablety hali to przetrwają —
  akcje lądują w kolejce offline apki i dosynchronizują się same
- Hasła: produkcja używa `scrypt`, lokalnie `pbkdf2` (zgodność Werkzeug)
- Dodając zależność, pamiętaj o `requirements.txt` — deploy instaluje z niego
- API mobilne (`/api/mobile/*`) jest **niezależne** od paneli webowych
  produkcji; zmiany w `modules/production/routers/stations/` nie dotykają tabletów

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

## Key Patterns

### Service Layer
Business logic is separated from routes into `services/` directories. Example: `modules/dashboard/services/user_activity_service.py`

### Request Lifecycle
- `@app.before_request`: Session extension, user activity tracking
- `@app.context_processor`: Injects user info into templates
- `@app.teardown_appcontext`: Database session cleanup with rollback on errors

### Error Handling
Global handlers for `ResourceClosedError` and `OperationalError` with automatic rollback and structured logging.
