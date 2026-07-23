# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WoodPower CRM - A Flask-based CRM application for manufacturing/production management. Features include pricing calculator, client management, production order tracking, 3D AR previews, quote management, and AI assistant integration.

## Development Workflow

### Local Development (Docker)

Codzienny start (kontenery NIE wstają same po zamknięciu Docker Desktop):
```bash
cd ~/Documents/woodpower-crm && docker compose up -d
```

Pierwszy raz / po zmianie Dockerfile lub requirements.txt:
```bash
docker compose up -d --build
```

App: http://localhost:5000 (Flask dev server, auto-reload przy zmianie plików).
MySQL: port 3306 na hoście (wolumen `db_data` — dane przeżywają restart kontenerów).

Testy:
```bash
docker compose exec app pytest tests/                                 # główny pakiet
docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest"  # blog_seo (własna konwencja importów)
```
Gołe `pytest` z korzenia repo NIE działa — `integrations/blog_seo` importuje swoje moduły
płasko (`import catalog` itp.) i wymaga bycia uruchomionym z własnego katalogu jako cwd.

### Local Environment Requirements
- Docker Desktop (Windows)
- WeasyPrint działa od razu w kontenerze (biblioteki systemowe w `docker/python/Dockerfile`) —
  bez ręcznej instalacji MSYS2 + GTK3

### Database Setup
```bash
# CLI command to create schema and admin user
flask setup-db

# Or set RUN_DB_SETUP: true in config/core.json for auto-setup on startup
```

### Background Scheduler
```bash
# Run scheduler daemon separately from web server
python scheduler_daemon.py
```

## Deployment

### Automatic Deployment (GitHub Actions)
Push to `main` branch triggers automatic deployment:
```bash
git add .
git commit -m "message"
git push
```

GitHub Actions workflow (`.github/workflows/deploy.yml`):
1. SSH connects to production server (195.78.66.85:222)
2. Pulls latest code from `main` branch
3. Installs dependencies from requirements.txt
4. Restarts Passenger app server via `touch tmp/restart.txt`

### Production Server
- Host: crm.woodpower.pl
- Path: `~/domains/crm.woodpower.pl/public_html/app`
- Python: 3.9 virtualenv at `~/virtualenv/domains/crm.woodpower.pl/public_html/3.9/`
- App server: Phusion Passenger (entry: `passenger_wsgi.py`)

### Manual Deployment
```bash
# On production server
cd ~/domains/crm.woodpower.pl/public_html/app
git pull origin main
source ~/virtualenv/domains/crm.woodpower.pl/public_html/3.9/bin/activate
pip install -r requirements.txt
touch tmp/restart.txt
```

### Important Notes
- Password hashing: Production uses `scrypt`, local uses `pbkdf2` (Werkzeug compatibility)
- Sync requirements.txt with server when adding dependencies
- GitHub secret `SSH_PASSWORD` required for deployment

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
