from flask import Flask, render_template, redirect, url_for, request, session, flash, current_app, Blueprint, jsonify
import os
import json
import sys
import pkgutil
import importlib
import click
import pytz
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from functools import wraps
from flask_mail import Mail, Message
from jinja2 import ChoiceLoader, FileSystemLoader
from extensions import db, mail
from sqlalchemy import desc
from datetime import timedelta, datetime
from modules.calculator import calculator_bp
from modules.users.models import User, Invitation
from modules.calculator.models import Price, Multiplier
from modules.clients import clients_bp
from modules.public_calculator import public_calculator_bp
from modules.quotes.routers import quotes_bp
from modules.baselinker import baselinker_bp
from modules.preview3d_ar import preview3d_ar_bp
from modules.logging import AppLogger, get_logger, logging_bp, get_structured_logger
from modules.reports import reports_bp
from modules.dashboard import dashboard_bp
from modules.dashboard.models import ChangelogEntry, ChangelogItem, UserSession
from modules.production import production_bp
from modules.production.routers import register_production_routers
from modules.dashboard.services.user_activity_service import UserActivityService
from modules.partner_academy import partner_academy_bp
from modules.partner_academy.models import PartnerApplication
from modules.sales import sales_bp
from modules.sales.models import SalesApplication
from modules.users import users_bp
from modules.help import help_bp
from modules.issues import issues_bp
from modules.ai_assistant import ai_assistant_bp
from modules.settings import settings_bp
from modules.settings.models import AppSetting

from flask_login import login_user, logout_user  # DODANE importy
from sqlalchemy.exc import ResourceClosedError, OperationalError
from flask.cli import with_appcontext

os.environ['PYTHONIOENCODING'] = 'utf-8:replace'

# ============================================================================
# PRODUCTION OPTIMIZATIONS
# ============================================================================
if os.environ.get('FLASK_ENV') == 'production':
    # Wyłącz debug pin w production
    os.environ['WERKZEUG_DEBUG_PIN'] = 'off'
    
    # Zmniejsz verbosity SQLAlchemy
    import logging
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)

# Domyślne metadane modułów (etykieta i ikona)
DEFAULT_MODULE_METADATA = {
    'dashboard': {'label': 'Dashboard', 'icon': '📊'},
    'calculator': {'label': 'Kalkulator', 'icon': '🧮'},
    'quotes': {'label': 'Wyceny', 'icon': '📄'},
    'clients': {'label': 'Klienci', 'icon': '👥'},
    'production': {'label': 'Produkcja', 'icon': '🏭'},
    'reports': {'label': 'Raporty', 'icon': '📊'},
    'settings': {'label': 'Ustawienia', 'icon': '⚙️'},
}


def discover_module_metadata(app):
    """Skanuje katalog app/modules w poszukiwaniu blueprintów."""
    metadata = {}
    modules_path = os.path.join(app.root_path, 'modules')

    for finder, name, ispkg in pkgutil.iter_modules([modules_path]):
        if not ispkg:
            continue
        try:
            module = importlib.import_module(f'modules.{name}')
        except Exception:
            continue

        for attr in module.__dict__.values():
            if isinstance(attr, Blueprint):
                default_meta = DEFAULT_MODULE_METADATA.get(attr.name, {})
                label = default_meta.get('label', attr.name.replace('_', ' ').title())
                icon = default_meta.get('icon', '📱')
                metadata[attr.name] = {'label': label, 'icon': icon}

    return metadata

def create_admin():
    """Tworzy użytkownika admina, jeśli nie istnieje."""
    admin_email = "admin@woodpower.pl"
    admin_password = "Kmiecik99"  # Ustaw mocne hasło
    admin_user = User.query.filter_by(email=admin_email).first()
    if not admin_user:
        hashed_pass = generate_password_hash(admin_password)
        new_admin = User(
            email=admin_email,
            password=hashed_pass,
            role="admin"
        )
        db.session.add(new_admin)
        db.session.commit()

def register_cli_commands(app):
    """Rejestruje komendy Flask CLI."""

    @app.cli.command("setup-db")
    @with_appcontext
    def setup_db_command():
        """Tworzy schemat bazy danych i konto administratora."""
        click.echo("[setup-db] Tworzę schemat bazy danych…")
        db.create_all()
        click.echo("[setup-db] Sprawdzam konto administratora…")
        create_admin()
        click.echo("[setup-db] Gotowe.")

    @app.cli.command("migrate")
    @with_appcontext
    def migrate_command():
        """Wykonuje oczekujące migracje bazy danych."""
        from migrations import MigrationService
        service = MigrationService(db)
        count = service.run_pending_migrations()
        click.echo(f"Wykonano {count} migracji.")

    @app.cli.command("migrate-status")
    @with_appcontext
    def migrate_status_command():
        """Pokazuje status wszystkich migracji."""
        from migrations import MigrationService
        service = MigrationService(db)
        status = service.get_migration_status()

        click.echo("\n" + "=" * 60)
        click.echo("STATUS MIGRACJI")
        click.echo("=" * 60)

        for m in status:
            if m['status'] == 'success':
                icon = "✓"
                color = 'green'
            elif m['status'] == 'failed':
                icon = "✗"
                color = 'red'
            else:
                icon = "○"
                color = 'yellow'

            click.echo(click.style(
                f"  {icon} {m['version']}_{m['name']}.{m['extension']} [{m['status']}]",
                fg=color
            ))
            if m['error_message']:
                click.echo(f"      Błąd: {m['error_message'][:80]}")

        click.echo("=" * 60 + "\n")

    @app.cli.command("migrate-finish-data")
    @with_appcontext
    def migrate_finish_data_command():
        """Przeparsowuje istniejące produkty i uzupełnia nowe kolumny wykończenia."""
        from modules.production.models import ProductionItem
        from modules.production.services.parser_service import parse_product_name

        items = ProductionItem.query.filter(
            ProductionItem.original_product_name.isnot(None),
            ProductionItem.original_product_name != ''
        ).all()

        click.echo(f"[migrate-finish-data] Znaleziono {len(items)} produktów do przetworzenia.")

        updated = 0
        errors = 0

        for i, item in enumerate(items, 1):
            try:
                parsed = parse_product_name(item.original_product_name, use_cache=False)
                item.parsed_finish_type = parsed.get('finish_type', 'surowe')
                item.parsed_finish_color_type = parsed.get('finish_color_type')
                item.parsed_finish_gloss = parsed.get('finish_gloss')
                item.parsed_finish_color = parsed.get('finish_color')
                item.parsed_finish_state = parsed.get('finish_state', 'Surowe')
                updated += 1
            except Exception as e:
                errors += 1
                click.echo(click.style(f"  ✗ Błąd [{item.short_product_id}]: {e}", fg='red'))

            if i % 100 == 0:
                db.session.flush()
                click.echo(f"  ... przetworzono {i}/{len(items)}")

        db.session.commit()
        click.echo(f"[migrate-finish-data] Gotowe: {updated} zaktualizowanych, {errors} błędów.")

    @app.cli.command("sync-changelog")
    @click.option('--before', required=True, help='SHA przed git pull')
    @click.option('--after', required=True, help='SHA po git pull')
    @with_appcontext
    def sync_changelog_command(before, after):
        """Synchronizuje wpisy changeloga z commitami z zakresu before..after."""
        import json
        from modules.dashboard.services.changelog_sync_service import (
            read_git_log, sync_commits
        )

        if before == after:
            click.echo('[sync-changelog] before == after, nic do roboty')
            return

        repo_path = app.config.get('CHANGELOG_SYNC', {}).get('REPO_PATH')
        if not repo_path:
            click.echo('[sync-changelog] BŁĄD: brak CHANGELOG_SYNC.REPO_PATH w configu', err=True)
            raise click.Abort()

        try:
            commits = read_git_log(repo_path, rev_range=f'{before}..{after}')
            click.echo(f'[sync-changelog] {len(commits)} commitów w zakresie')
            result = sync_commits(commits)
            click.echo(f'[sync-changelog] {json.dumps(result)}')
        except Exception as e:
            click.echo(f'[sync-changelog] BŁĄD: {e}', err=True)
            raise click.Abort()

    @app.cli.command("seed-changelog-sync")
    @click.option('--admin-id', type=int, required=True, help='ID admina jako created_by entry 1.5.0')
    @with_appcontext
    def seed_changelog_sync_command(admin_id):
        """One-time: tworzy entry 1.5.0 + pre-fill changelog_synced_commits historią git log."""
        from modules.dashboard.models import (
            ChangelogEntry, ChangelogItem, ChangelogSyncedCommit
        )
        from modules.dashboard.services.changelog_sync_service import read_git_log
        from modules.calculator.models import User

        # Idempotencja: jeśli 1.5.0 już istnieje, abort
        existing = ChangelogEntry.query.filter_by(version='1.5.0').first()
        if existing:
            click.echo(f'[seed] Entry 1.5.0 już istnieje (id={existing.id}), abort')
            return

        # Walidacja admina
        admin = User.query.get(admin_id)
        if not admin or admin.role != 'admin':
            click.echo(f'[seed] BŁĄD: user id={admin_id} nie istnieje lub nie jest adminem', err=True)
            raise click.Abort()

        # Repo path
        repo_path = app.config.get('CHANGELOG_SYNC', {}).get('REPO_PATH')
        if not repo_path:
            click.echo('[seed] BŁĄD: brak CHANGELOG_SYNC.REPO_PATH w configu', err=True)
            raise click.Abort()

        try:
            # Krok 1: Utworzenie entry 1.5.0
            entry = ChangelogEntry(
                version='1.5.0',
                is_visible=True,
                created_by=admin_id,
            )
            db.session.add(entry)
            db.session.flush()

            note = ChangelogItem(
                entry_id=entry.id,
                section_type='custom',
                custom_section_name='Informacja',
                item_text='Uruchomienie automatycznej synchronizacji nowości z GitHub — '
                          'kolejne wersje będą generowane automatycznie po każdym wdrożeniu.',
                sort_order=0,
            )
            db.session.add(note)

            # Krok 2: Pre-fill całą historią git log
            all_commits = read_git_log(repo_path, rev_range=None, limit=None)
            click.echo(f'[seed] Znaleziono {len(all_commits)} commitów w historii')

            for c in all_commits:
                db.session.add(ChangelogSyncedCommit(
                    commit_sha=c['sha'],
                    entry_id=None,
                    is_seed=True,
                ))

            db.session.commit()
            click.echo(f'[seed] OK: entry v1.5.0 utworzone, {len(all_commits)} SHA pre-filled')
        except Exception as e:
            db.session.rollback()
            click.echo(f'[seed] BŁĄD, rollback: {e}', err=True)
            raise click.Abort()

# Funkcje do generowania i weryfikacji tokena resetującego hasło
def generate_reset_token(email, secret_key, salt='password-reset-salt'):
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps(email, salt=salt)

def verify_reset_token(token, secret_key, salt='password-reset-salt', expiration=3600):
    serializer = URLSafeTimedSerializer(secret_key)
    try:
        email = serializer.loads(token, salt=salt, max_age=expiration)
    except (SignatureExpired, BadSignature):
        return None
    return email

def get_local_now():
    """Zwraca aktualny czas w strefie czasowej Polski"""
    poland_tz = pytz.timezone('Europe/Warsaw')
    return datetime.now(poland_tz).replace(tzinfo=None)

def create_app():
    app = Flask(__name__)
    app.secret_key = "65d769148feb6bc476c6d2120d4abb40069cdfd919c37f99"

    # ============================================================================
    # KONFIGURACJA SESJI I FLASK-LOGIN
    # ============================================================================
    
    # Flask session configuration
    is_production = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_production  # Wymaga HTTPS (tylko production)
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Ochrona przed XSS
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Ochrona przed CSRF

    # Flask-Login configuration
    app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)  # 30 dni
    app.config['REMEMBER_COOKIE_SECURE'] = is_production  # Wymaga HTTPS (tylko production)
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True # Ochrona przed XSS
    
    # ============================================================================

    app.jinja_loader = ChoiceLoader([
        app.jinja_loader,
        FileSystemLoader(os.path.join(app.root_path, 'modules'))
    ])

    # Ładowanie konfiguracji z pliku config/core.json
    config_path = os.path.join(app.root_path, "config", "core.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as config_file:
            config_data = json.load(config_file)
        app.config.update(config_data)
        print("Konfiguracja załadowana z app/config/core.json", file=sys.stderr)
    else:
        config_data = {
            "DEBUG": True,
            "DATABASE_URI": "sqlite:///kalkulator_web.db",
            "RUN_DB_SETUP": False
        }
        app.config.update(config_data)
        print("Nie znaleziono app/config/core.json – użyto wartości domyślnych", file=sys.stderr)

    app.config.setdefault('RUN_DB_SETUP', False)

    # Dodajemy ustawienia utrzymujące połączenie z bazą:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,              # Sprawdź połączenie przed użyciem
            'pool_recycle': 280,                # Recycle połączeń przed MySQL timeout (300s)
            'pool_size': 10,                    # ZWIĘKSZONE: więcej równoległych połączeń
            'max_overflow': 20,                 # ZWIĘKSZONE: więcej overflow connections
            'pool_timeout': 30,                 # Timeout oczekiwania na połączenie
            'echo': False,                      # Wyłącz echo SQL (performance)
            'echo_pool': False,                 # Wyłącz echo pool events
            'connect_args': {
                'connect_timeout': 10,          # MySQL connection timeout
                'charset': 'utf8mb4',           # UTF-8 support
                'use_unicode': True
            }
    }
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config["DATABASE_URI"]
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ============================================================================
    # FILE UPLOAD CONFIGURATION (limit rozmiaru plików)
    # ============================================================================
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

    # ============================================================================
    # JINJA2 TEMPLATE CACHING (szybsze renderowanie)
    # ============================================================================
    if not app.config.get('DEBUG'):
        app.jinja_env.cache = {}              # Enable template caching
        app.jinja_env.auto_reload = False     # Disable auto-reload w production
    
    # ============================================================================
    # SESSION OPTIMIZATION (krótsze sesje w production)
    # ============================================================================
    if not app.config.get('DEBUG'):
        # W production: sesje 12h zamiast 30 dni (lepsze bezpieczeństwo + performance)
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)

    # Inicjalizacja Flask-Mail oraz bazy danych itp.
    from extensions import init_extensions
    init_extensions(app)
    register_cli_commands(app)

    if hasattr(app, 'login_manager'):
        print("✅ LoginManager zainicjalizowany poprawnie", file=sys.stderr)
    else:
        print("❌ LoginManager nie został zainicjalizowany", file=sys.stderr)
    
    with app.app_context():
        if app.config.get('RUN_DB_SETUP'):
            print("[DB_SETUP] RUN_DB_SETUP włączone - tworzę schemat bazy i konto admina", file=sys.stderr)
            db.create_all()
            create_admin()

        # Automatyczne migracje bazy danych
        if app.config.get('RUN_MIGRATIONS', True):
            try:
                from migrations import MigrationService
                migration_service = MigrationService(db)
                migration_service.run_pending_migrations()
            except Exception as e:
                print(f"[Migrations] Błąd podczas migracji: {e}", file=sys.stderr)

        # Odkrywanie dostępnych modułów i ich metadanych
        app.config['MODULE_METADATA'] = discover_module_metadata(app)

    def register_blueprints_lazy(app):
        """Rejestracja blueprintów - importy tylko gdy potrzebne"""
        app.register_blueprint(calculator_bp, url_prefix='/calculator')
        app.register_blueprint(clients_bp, url_prefix='/clients')
        app.register_blueprint(public_calculator_bp)
        app.register_blueprint(quotes_bp, url_prefix="/quotes")
        app.register_blueprint(baselinker_bp, url_prefix='/baselinker')
        app.register_blueprint(logging_bp, url_prefix='/logging')
        app.register_blueprint(preview3d_ar_bp)
        app.register_blueprint(reports_bp, url_prefix='/reports')
        app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
        register_production_routers(production_bp)
        app.register_blueprint(production_bp, url_prefix='/production')
        app.register_blueprint(partner_academy_bp, url_prefix='/partner-academy')
        app.register_blueprint(sales_bp, url_prefix='/sales')
        app.register_blueprint(users_bp)
        app.register_blueprint(help_bp)
        app.register_blueprint(issues_bp)
        app.register_blueprint(ai_assistant_bp)
        app.register_blueprint(settings_bp, url_prefix='/settings')

        print("✅ Wszystkie blueprinty zarejestrowane", file=sys.stderr)

    register_blueprints_lazy(app)

    from modules.ai_assistant import init_ai_service
    init_ai_service(app)

    # =========================================================================
    # Auto-login przez HTTP Basic Auth (dla Fully Kiosk Browser na tabletach)
    # =========================================================================
    @app.before_request
    def auto_login_basic_auth():
        """Automatyczne logowanie przez HTTP Basic Auth (nagłówek Authorization).
        Fully Kiosk Browser wysyła te dane z każdym requestem."""
        from flask_login import current_user

        if current_user.is_authenticated:
            return

        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return

        user = User.query.filter_by(email=auth.username).first()
        if not user or not user.active:
            return

        try:
            if not check_password_hash(user.password, auth.password):
                return
        except ValueError:
            return

        # Zaloguj użytkownika
        session['user_email'] = user.email
        session['user_id'] = user.id
        session.permanent = True
        login_user(user, remember=True)

        current_app.logger.info(f"[BasicAuth] Auto-login: {user.email} (tablet/kiosk)")

    # Cache trybu konserwacji (aby nie odpytywać DB przy każdym requeście)
    _maintenance_cache = {'enabled': False, 'checked_at': 0}

    @app.before_request
    def check_maintenance_mode():
        """Sprawdza tryb konserwacji - blokuje dostęp nie-adminom"""
        import time

        # Pomiń statyczne pliki
        if request.endpoint and ('static' in request.endpoint or request.endpoint == 'favicon'):
            return

        # /login — zawsze dostępny (formularz logowania dla admina podczas konserwacji)
        if request.endpoint == 'login':
            return

        # Cache: sprawdzaj DB co 5 sekund
        now = time.time()
        if now - _maintenance_cache['checked_at'] > 5:
            try:
                _maintenance_cache['enabled'] = AppSetting.get_value('maintenance_mode', 'false') == 'true'
                _maintenance_cache['checked_at'] = now
            except Exception:
                _maintenance_cache['enabled'] = False

        if not _maintenance_cache['enabled']:
            return

        # Tryb konserwacji aktywny — sprawdź czy user jest adminem
        user_email = session.get('user_email')
        if user_email:
            try:
                user = User.query.filter_by(email=user_email).first()
                if user and user.is_admin():
                    return  # Admin — przepuść
            except Exception:
                pass
            # Nie-admin zalogowany — wyloguj
            session.clear()

        # Niezalogowany (lub właśnie wylogowany) — pokaż stronę konserwacji
        return render_template('login.html', mode='maintenance'), 503

    @app.before_request
    def extend_session():
        session.permanent = True

        # DODAJ tracking aktywności użytkowników
        track_user_activity()

    # Dekorator zabezpieczający strony – wymaga zalogowania
    def login_required(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_email = session.get('user_email')
            if not user_email:
                flash("Twoja sesja wygasła. Zaloguj się ponownie.", "info")
                return redirect(url_for('login'))
            return func(*args, **kwargs)
        return wrapper

    def track_user_activity():
        """
        Śledzi aktywność użytkowników przy każdym żądaniu HTTP
        """
        try:
            # Sprawdź czy użytkownik jest zalogowany
            user_id = session.get('user_id')
            user_email = session.get('user_email')
        
            if not user_id or not user_email:
                return
        
            # Pobierz informacje o żądaniu
            current_page = request.endpoint
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        
            # Jeśli IP zawiera wiele adresów (proxy), weź pierwszy
            if ip_address and ',' in ip_address:
                ip_address = ip_address.split(',')[0].strip()
        
            # Aktualizuj aktywność
            UserActivityService.update_activity(
                user_id=user_id,
                current_page=current_page,
                ip_address=ip_address
            )
        
        except Exception as e:
            # Nie przerywaj żądania jeśli tracking się nie powiedzie
            current_app.logger.debug(f"[Activity] Błąd tracking aktywności: {e}")

    def check_user_session_validity():
        """
        Sprawdza ważność sesji użytkownika i wylogowuje jeśli nieważna
        """
        try:
            session_token = session.get('user_session_token')
            user_id = session.get('user_id')
        
            if not session_token or not user_id:
                return True  # Brak sesji - OK
        
            # Sprawdź czy sesja istnieje w bazie
            user_session = UserSession.query.filter_by(
                session_token=session_token,
                user_id=user_id,
                is_active=True
            ).first()
        
            if not user_session:
                # Sesja nieważna - wyloguj
                current_app.logger.warning(f"[Security] Wykryto nieważną sesję dla user_id={user_id}")
                session.clear()
                return False
        
            # Sprawdź czy sesja nie jest zbyt stara (ponad 24h)
            from datetime import datetime, timedelta
            if user_session.last_activity_at < get_local_now() - timedelta(hours=24):
                current_app.logger.info(f"[Security] Sesja wygasła dla user_id={user_id}")
                user_session.force_logout()
                session.clear()
                return False
        
            return True
        
        except Exception as e:
            current_app.logger.error(f"[Security] Błąd sprawdzania sesji: {e}")
            return True  # W razie błędu nie wylogowuj

    @app.errorhandler(401)
    def handle_unauthorized(error):
        """
        Obsługa błędów autoryzacji - przekieruj na login
        """
        if request.path.startswith('/api/'):
            return jsonify({
                'success': False,
                'error': 'Sesja wygasła',
                'redirect': url_for('login')
            }), 401
        else:
            flash("Twoja sesja wygasła. Zaloguj się ponownie.", "info")
            return redirect(url_for('login'))

    # -------------------------
    #         ROUTES
    # -------------------------

    @app.route('/api/session/ping', methods=['POST'])
    def session_ping():
        """
        Endpoint do odświeżania sesji (heartbeat)
        Może być wywoływany przez JavaScript co kilka minut
        """
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'success': False, 'error': 'Nie zalogowano'}), 401
        
            # Aktualizuj aktywność
            success = UserActivityService.update_activity(
                user_id=user_id,
                current_page=request.json.get('current_page') if request.is_json else None
            )
        
            if success:
                return jsonify({
                    'success': True,
                    'timestamp': get_local_now().isoformat()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Nie udało się zaktualizować sesji'
                }), 500
            
        except Exception as e:
            current_app.logger.error(f"[SessionPing] Błąd: {e}")
            return jsonify({
                'success': False,
                'error': 'Błąd serwera'
            }), 500

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        from flask_login import current_user
        # Jeśli już zalogowany (np. przez Basic Auth z tabletu) — przekieruj
        if current_user.is_authenticated:
            return redirect(url_for('dashboard.dashboard'))

        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            remember_me = request.form.get('remember_me')

            # Pobieramy użytkownika z bazy
            user = User.query.filter_by(email=email).first()
            if not user:
                return render_template('login.html',
                                    email_value=email,
                                    password_error='Błędne hasło lub e-mail.',
                                    email_error=None)
            if not user.active:
                return render_template('login.html',
                                    email_value=email,
                                    password_error='Twoje konto zostało dezaktywowane.',
                                    email_error=None)

            # Sprawdzenie hasła z obsługą niekompatybilnego algorytmu hashowania
            try:
                password_valid = check_password_hash(user.password, password)
            except ValueError as e:
                if 'unsupported hash type' in str(e) and user.password.startswith('scrypt:'):
                    # Hasło używa scrypt, który nie jest obsługiwany na tym serwerze
                    # Przekieruj na reset hasła
                    current_app.logger.warning(f"[Login] Nieobsługiwany algorytm hashowania dla {email} - wymagany reset hasła")
                    return render_template('login.html',
                                        email_value=email,
                                        password_error='Twoje hasło wymaga aktualizacji. Skorzystaj z opcji "Nie pamiętam hasła" aby ustawić nowe hasło.',
                                        email_error=None,
                                        show_forgot_password=True)
                raise

            if not password_valid:
                return render_template('login.html',
                                    email_value=email,
                                    password_error='Błędne hasło lub e-mail.',
                                    email_error=None)
            
            session['user_email'] = email
            session['user_id'] = user.id
            
            # NOWE: Ustawiamy sesję jako permanent tylko gdy checkbox zaznaczony
            if remember_me:
                session.permanent = True
                current_app.logger.info(f"[Login] Sesja trwała (30 dni) dla {email}")
            else:
                session.permanent = False
                current_app.logger.info(f"[Login] Sesja tymczasowa (do zamknięcia przeglądarki) dla {email}")
            
            login_user(user, remember=bool(remember_me))
            
            # Logowanie sukcesu
            current_app.logger.info(f"[Login] Pomyślne logowanie: {email} (Flask-Login + Session)")
        
            try:
                ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
                
                user_agent = request.headers.get('User-Agent', '')
            
                UserActivityService.create_session(
                    user_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            
                current_app.logger.info(f"[Login] Utworzono sesję tracking dla {email}")
            
            except Exception as e:
                current_app.logger.error(f"[Login] Błąd tworzenia sesji tracking: {e}")
        
            return redirect(url_for("dashboard.dashboard"))

        return render_template("login.html", mode='login')

    @app.route("/")
    def index():
        # Jeśli użytkownik jest zalogowany, przekieruj na dashboard
        if session.get('user_email'):
            return redirect(url_for('dashboard.dashboard'))
        # Niezalogowany — pokaż formularz logowania (mode='login' domyślnie)
        return render_template("login.html", mode='login')

    @app.route("/clients")
    @login_required
    def clients():
        user_email = session.get('user_email')
        return render_template("clients.html", user_email=user_email)

    @app.route("/logged_out")
    def logged_out():
        try:
            # Zakończ sesję tracking przed wylogowaniem
            user_id = session.get('user_id')
            session_token = session.get('user_session_token')

            if user_id or session_token:
                UserActivityService.end_session(
                    user_id=user_id,
                    session_token=session_token
                )
                current_app.logger.info(f"[Logout] Zakończono sesję tracking dla user_id={user_id}")

        except Exception as e:
            current_app.logger.error(f"[Logout] Błąd kończenia sesji tracking: {e}")

        # Czyszczenie sesji i wyświetlenie ekranu wylogowania
        session.clear()
        return render_template("login.html", mode='logged_out')

    @app.route("/settings/prices", methods=["GET", "POST"])
    @login_required
    def admin_prices():
        # Nowy system logowania
        prices_logger = get_logger('admin.prices')
        prices_logger.info("Wejście do endpointu /settings/prices")
        
        # 1. Sprawdź, czy zalogowany jest admin
        current_email = session.get('user_email')
        prices_logger.debug("Sprawdzanie uprawnień użytkownika", user_email=current_email)
        current_user = User.query.filter_by(email=current_email).first()
        prices_logger.debug("Pobrano użytkownika z bazy", 
                        user_found=bool(current_user), 
                        user_role=current_user.role if current_user else None)
        
        if not current_user or current_user.role != 'admin':
            prices_logger.warning("Odmowa dostępu - brak uprawnień administratora", 
                                user_email=current_email,
                                user_role=current_user.role if current_user else 'brak_użytkownika')
            flash("Brak uprawnień. Tylko administrator może edytować cennik.", "error")
            return redirect(url_for('users.profile'))

        # 2A. Obsługa zapisu (POST)
        if request.method == "POST":
            prices_logger.info("Rozpoczęcie aktualizacji cennika", operation='POST_update')
            all_prices = Price.query.all()
            prices_logger.debug("Pobrano rekordy cennika z bazy danych", 
                            total_records=len(all_prices))
            
            updated_records = 0
            errors_count = 0
            
            # Dla każdego rekordu w bazie:
            for price_record in all_prices:
                prefix = f"price_{price_record.id}_"
                prices_logger.debug("Przetwarzanie rekordu cennika", 
                                record_id=price_record.id,
                                species=price_record.species,
                                wood_class=price_record.wood_class,
                                form_prefix=prefix)
                
                # Odczytujemy wartości z formularza i zamieniamy przecinek na kropkę
                new_thickness_min = request.form.get(prefix + "thickness_min", "").replace(",", ".")
                new_thickness_max = request.form.get(prefix + "thickness_max", "").replace(",", ".")
                new_length_min = request.form.get(prefix + "length_min", "").replace(",", ".")
                new_length_max = request.form.get(prefix + "length_max", "").replace(",", ".")
                new_price_per_m3 = request.form.get(prefix + "price_per_m3", "").replace(",", ".")
                
                prices_logger.debug("Otrzymane dane z formularza", 
                                record_id=price_record.id,
                                form_data={
                                    'thickness_min_raw': new_thickness_min,
                                    'thickness_max_raw': new_thickness_max,
                                    'length_min_raw': new_length_min,
                                    'length_max_raw': new_length_max,
                                    'price_per_m3_raw': new_price_per_m3
                                })
                
                try:
                    # Konwersja na float/int
                    thickness_min_val = float(new_thickness_min)
                    thickness_max_val = float(new_thickness_max)
                    length_min_val = int(float(new_length_min))
                    length_max_val = int(float(new_length_max))
                    price_per_m3_val = float(new_price_per_m3)
                    
                    prices_logger.debug("Pomyślna konwersja wartości", 
                                    record_id=price_record.id,
                                    converted_values={
                                        'thickness_min': thickness_min_val,
                                        'thickness_max': thickness_max_val,
                                        'length_min': length_min_val,
                                        'length_max': length_max_val,
                                        'price_per_m3': price_per_m3_val
                                    })
                    
                    # Sprawdzenie, czy wartości nie są ujemne
                    if thickness_min_val < 0 or thickness_max_val < 0 or length_min_val < 0 or length_max_val < 0 or price_per_m3_val < 0:
                        prices_logger.error("Wykryto ujemne wartości w formularzu", 
                                        record_id=price_record.id,
                                        species=price_record.species,
                                        wood_class=price_record.wood_class,
                                        invalid_values={
                                            'thickness_min': thickness_min_val,
                                            'thickness_max': thickness_max_val,
                                            'length_min': length_min_val,
                                            'length_max': length_max_val,
                                            'price_per_m3': price_per_m3_val
                                        },
                                        validation_error='negative_values')
                        flash(f"Nie można wprowadzić ujemnych wartości (ID: {price_record.id}).", "error")
                        return redirect(url_for('admin_prices'))
                    
                    # Sprawdzenie logiki min/max
                    if thickness_min_val > thickness_max_val:
                        prices_logger.error("Nieprawidłowa logika min/max dla grubości", 
                                        record_id=price_record.id,
                                        thickness_min=thickness_min_val,
                                        thickness_max=thickness_max_val,
                                        validation_error='thickness_min_greater_than_max')
                        flash(f"Grubość min nie może być większa od max (ID: {price_record.id}).", "error")
                        return redirect(url_for('admin_prices'))
                    
                    if length_min_val > length_max_val:
                        prices_logger.error("Nieprawidłowa logika min/max dla długości", 
                                        record_id=price_record.id,
                                        length_min=length_min_val,
                                        length_max=length_max_val,
                                        validation_error='length_min_greater_than_max')
                        flash(f"Długość min nie może być większa od max (ID: {price_record.id}).", "error")
                        return redirect(url_for('admin_prices'))
                    
                    # Sprawdź czy są zmiany
                    changes_detected = (
                        price_record.thickness_min != thickness_min_val or
                        price_record.thickness_max != thickness_max_val or
                        price_record.length_min != length_min_val or
                        price_record.length_max != length_max_val or
                        price_record.price_per_m3 != price_per_m3_val
                    )
                    
                    if changes_detected:
                        # Loguj stare vs nowe wartości
                        prices_logger.info("Wykryto zmiany w rekordzie", 
                                        record_id=price_record.id,
                                        species=price_record.species,
                                        wood_class=price_record.wood_class,
                                        old_values={
                                            'thickness_min': float(price_record.thickness_min),
                                            'thickness_max': float(price_record.thickness_max),
                                            'length_min': price_record.length_min,
                                            'length_max': price_record.length_max,
                                            'price_per_m3': float(price_record.price_per_m3)
                                        },
                                        new_values={
                                            'thickness_min': thickness_min_val,
                                            'thickness_max': thickness_max_val,
                                            'length_min': length_min_val,
                                            'length_max': length_max_val,
                                            'price_per_m3': price_per_m3_val
                                        })
                        
                        # Aktualizacja rekordu
                        price_record.thickness_min = thickness_min_val
                        price_record.thickness_max = thickness_max_val
                        price_record.length_min = length_min_val
                        price_record.length_max = length_max_val
                        price_record.price_per_m3 = price_per_m3_val
                        updated_records += 1
                        
                        prices_logger.info("Rekord został zaktualizowany", 
                                        record_id=price_record.id,
                                        species=price_record.species,
                                        wood_class=price_record.wood_class,
                                        update_successful=True)
                    else:
                        prices_logger.debug("Brak zmian w rekordzie", 
                                        record_id=price_record.id,
                                        species=price_record.species,
                                        wood_class=price_record.wood_class)
                    
                except ValueError as e:
                    errors_count += 1
                    prices_logger.error("Błąd konwersji wartości liczbowych", 
                                    record_id=price_record.id,
                                    species=price_record.species,
                                    wood_class=price_record.wood_class,
                                    error_message=str(e),
                                    error_type='ValueError',
                                    form_data={
                                        'thickness_min_raw': new_thickness_min,
                                        'thickness_max_raw': new_thickness_max,
                                        'length_min_raw': new_length_min,
                                        'length_max_raw': new_length_max,
                                        'price_per_m3_raw': new_price_per_m3
                                    })
                    flash(f"Błąd konwersji wartości liczbowych przy rekordzie ID {price_record.id}.", "error")
                    return redirect(url_for('admin_prices'))
                
                except Exception as e:
                    errors_count += 1
                    prices_logger.error("Nieoczekiwany błąd podczas przetwarzania rekordu", 
                                    record_id=price_record.id,
                                    species=price_record.species,
                                    wood_class=price_record.wood_class,
                                    error_message=str(e),
                                    error_type=type(e).__name__)
                    flash(f"Nieoczekiwany błąd przy rekordzie ID {price_record.id}.", "error")
                    return redirect(url_for('admin_prices'))
            
            # Po zaktualizowaniu wszystkich rekordów
            try:
                db.session.commit()
                prices_logger.info("Pomyślnie zakończono aktualizację cennika", 
                                operation='database_commit',
                                total_records_processed=len(all_prices),
                                records_updated=updated_records,
                                records_unchanged=len(all_prices) - updated_records,
                                errors_count=errors_count,
                                commit_successful=True)
                
                if updated_records > 0:
                    flash(f"Pomyślnie zaktualizowano cennik. Zmieniono {updated_records} rekordów.", "success")
                else:
                    flash("Cennik sprawdzony - brak zmian do zapisania.", "info")
                    
            except Exception as e:
                db.session.rollback()
                prices_logger.error("Błąd podczas zapisywania do bazy danych", 
                                error_message=str(e),
                                error_type=type(e).__name__,
                                operation='database_commit',
                                records_to_update=updated_records)
                flash("Błąd podczas zapisywania zmian do bazy danych.", "error")
            
            return redirect(url_for('admin_prices'))
        
        # 2B. Obsługa GET – wyświetlenie
        prices_logger.info("Wyświetlanie strony administracji cennika", operation='GET_display')
        all_prices = Price.query.order_by(Price.species, Price.wood_class).all()
        prices_logger.debug("Pobrano dane cennika do wyświetlenia", 
                        total_records=len(all_prices),
                        species_count=len(set(p.species for p in all_prices)),
                        wood_classes=list(set(p.wood_class for p in all_prices)))
        
        prices_logger.info("Renderowanie szablonu admin_settings.html", 
                        template='admin_settings.html',
                        data_records=len(all_prices))
        
        return render_template("settings_page/admin_settings.html", prices=all_prices)

    @app.route('/settings/logs')
    @login_required
    def settings_logs():
        user_email = session.get('user_email')
        user = User.query.filter_by(email=user_email).first()
        if not user or user.role != 'admin':
            flash('Brak uprawnień. Tylko administrator ma dostęp do logów.', 'error')
            return redirect(url_for('users.profile'))
        return render_template('settings_page/logs_console.html')

    @app.route('/api/latest-version')
    def get_latest_version():
        try:
            # Sprawdź czy masz import modelu
        
            # Musisz zaimportować model - sprawdź jaki masz:
            # from modules.dashboard.models import ChangelogEntry  # lub inna ścieżka
        
            latest_entry = db.session.query(ChangelogEntry)\
                .order_by(desc(ChangelogEntry.id))\
                .first()
                
            if latest_entry:
                return {'version': latest_entry.version}
            else:
                return {'version': 'v1.2'}
            
        except Exception as e:
            return {'version': 'v1.2'}

    @app.route('/accept_invitation/<token>', methods=['GET', 'POST'])
    def accept_invitation(token):
        invitation = Invitation.query.filter_by(token=token, active=True).first()
        if not invitation:
            flash("Zaproszenie jest nieprawidłowe lub nieaktywne.", "error")
            return redirect(url_for('login'))

        if request.method == 'GET':
            return render_template("accept_invitation.html", token=token)

        # Pobieramy dane z formularza
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        password = request.form.get('password')
        password2 = request.form.get('password2')
        # ...

        if password != password2:
            flash("Hasła muszą być identyczne!", "error")
            return redirect(url_for('accept_invitation', token=token))

        existing_user = User.query.filter_by(email=invitation.email).first()
        if existing_user:
            flash("Konto z tym e-mailem już istnieje!", "error")
            return redirect(url_for('login'))

        hashed_pass = generate_password_hash(password)
        # Ustawiamy rolę na taką, jaka została zapisana w zaproszeniu
        new_user = User(
            email=invitation.email,
            password=hashed_pass,
            role=invitation.role if invitation.role else 'user',
            first_name=first_name,
            last_name=last_name,
            multiplier_id=invitation.multiplier_id
        )

        # Obsługa avatara ...
        db.session.add(new_user)
        db.session.commit()

        invitation.active = False
        db.session.commit()

        flash("Konto zostało utworzone! Możesz się zalogować.", "success")
        return redirect(url_for('login'))


    @app.context_processor
    def inject_user():
        user_email = session.get('user_email')
        if user_email:
            user = User.query.filter_by(email=user_email).first()
            if user:
                # Jeśli imię i nazwisko są uzupełnione, łączymy je. W przeciwnym razie używamy emaila.
                user_name = f"{user.first_name} {user.last_name}".strip() if user.first_name or user.last_name else user.email
                # Jeśli brak avatara, ustawiamy domyślną ścieżkę.
                if user.avatar_path:
                    user_avatar = url_for('static', filename=user.avatar_path)
                else:
                    user_avatar = url_for('static', filename='images/avatars/default_avatars/avatar1.svg')
            
                # DODAJ informacje o sesji
                session_info = {}
                try:
                    session_token = session.get('user_session_token')
                    if session_token:
                        user_session = UserSession.query.filter_by(
                            session_token=session_token,
                            is_active=True
                        ).first()
                    
                        if user_session:
                            session_info = {
                                'session_duration': user_session.get_session_duration(),
                                'last_activity': user_session.get_relative_time(),
                                'current_page': user_session.get_page_display_name()
                            }
                except Exception as e:
                    current_app.logger.debug(f"[Context] Błąd pobierania info sesji: {e}")
            
                return dict(
                    user_name=user_name,
                    user_avatar=user_avatar,
                    user_email=user.email,
                    user_role=user.role,  # Rola użytkownika dla sidebar
                    user=user,  # Dodaj cały obiekt user
                    user_session=session_info
                )
    
        # Domyślne wartości, gdy nie ma zalogowanego użytkownika.
        return dict(
            user_name="Dzielny człowieku!",
            user_avatar=url_for('static', filename='images/avatars/default_avatars/avatar1.svg'),
            user_role=None,
            user=None,
            user_session={}
        )

    @app.route('/debug/session-info')
    @login_required
    def debug_session_info():
        """
        Debug endpoint - informacje o sesji (tylko w trybie DEBUG)
        """
        if not current_app.config.get('DEBUG'):
            return "Debug mode wyłączony", 404
    
        try:
            user_id = session.get('user_id')
            session_token = session.get('user_session_token')
        
            session_data = {
                'flask_session': dict(session),
                'user_id': user_id,
                'session_token': session_token[:8] + '...' if session_token else None
            }
        
            if session_token:
                user_session = UserSession.query.filter_by(
                    session_token=session_token
                ).first()
            
                if user_session:
                    session_data['user_session'] = user_session.to_dict()
        
            return jsonify(session_data)
        
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # -------------------------
    # RESET HASŁA
    # -------------------------
    @app.route('/reset_password', methods=['GET', 'POST'])
    def reset_password_request():
        if request.method == 'POST':
            email = request.form.get('email')
            user = User.query.filter_by(email=email).first()
            if user:
                token = generate_reset_token(email, app.secret_key)
                user.reset_token = token
                db.session.commit()

                reset_link = url_for('reset_password_token', token=token, _external=True)
                html_body = render_template('reset_password_email_template.html', reset_link=reset_link)
            
                msg = Message("Resetowanie hasła CRM WoodPower",
                              sender=app.config.get("MAIL_USERNAME"),
                              recipients=[email])
                msg.html = html_body
                mail.send(msg)
            
                flash("Sprawdź swój email – link do resetowania hasła został wysłany.", "info")
                return redirect(url_for('reset_password_success'))
            else:
                email_error = "Ten mail nie występuje w bazie danych."
                return render_template("reset_password_request.html", email_value=email, email_error=email_error)
        email_value = request.args.get('email_value', '')
        return render_template("reset_password_request.html", email_value=email_value)

    @app.route('/reset_password_success')
    def reset_password_success():
        return render_template("reset_password_success.html")

    @app.route('/reset_password/<token>', methods=['GET', 'POST'])
    def reset_password_token(token):
        email = verify_reset_token(token, app.secret_key)
        if not email:
            return render_template("reset_password_expired.html")
    
        user = User.query.filter_by(email=email).first()
        if not user or user.reset_token != token:
            return render_template("reset_password_expired.html")
    
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            repeat_password = request.form.get('repeat_password')

            if not new_password or not repeat_password:
                flash("Wprowadź oba pola hasła.", "error")
                return render_template("reset_password_form.html", token=token)
            if new_password != repeat_password:
                flash("Hasła muszą być identyczne.", "error")
                return render_template("reset_password_form.html", token=token)

            user.password = generate_password_hash(new_password)
            user.reset_token = None
            db.session.commit()
            return render_template("reset_password_complete.html")
    
        return render_template("reset_password_form.html", token=token)

    @app.errorhandler(ResourceClosedError)
    def handle_resource_closed_error(e):
        db.session.rollback()
        
        # NOWE strukturalne logowanie:
        error_logger = get_structured_logger('app.errors')
        error_logger.error("ResourceClosedError occurred", 
                          error=str(e), 
                          error_type='ResourceClosedError')
        
        # ZOSTAW STARE:
        current_app.logger.error("ResourceClosedError – rollback wykonany")
        return render_template("error.html", message="Problem z bazą danych. Spróbuj ponownie."), 500

    @app.errorhandler(OperationalError)
    def handle_operational_error(e):
        db.session.rollback()
        
        # NOWE strukturalne logowanie:
        error_logger = get_structured_logger('app.errors')
        error_logger.error("OperationalError occurred", 
                          error=str(e), 
                          error_type='OperationalError')
        
        # ZOSTAW STARE:
        current_app.logger.error("OperationalError – rollback wykonany")
        return render_template("error.html", message="Problem z bazą danych. Spróbuj za chwilę."), 500

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if exception:
            # NOWE strukturalne logowanie:
            error_logger = get_structured_logger('app.teardown')
            error_logger.error("Teardown exception occurred", 
                              error=str(exception), 
                              error_type=type(exception).__name__)
            
            # ZOSTAW STARE:
            current_app.logger.error(f"Teardown exception: {exception}")
            db.session.rollback()
        db.session.remove()

    # Konfiguracja nowego systemu logowania
    AppLogger.setup()
    app_logger = get_structured_logger('main')
    app_logger.info("Aplikacja Flask została uruchomiona")

    # Logi debug aplikacji
    app_logger.info("Flask app created", app_info=str(app))

    # Sprawdź zarejestrowane blueprinty
    blueprints = list(app.blueprints.keys())
    app_logger.debug("Registered blueprints", blueprints_count=len(blueprints), blueprints=blueprints)

    # Sprawdź routy związane z wycenami
    wycena_routes = []
    for rule in app.url_map.iter_rules():
        if 'wycena' in str(rule.rule) or 'quotes' in str(rule.endpoint):
            wycena_routes.append({
                'rule': str(rule.rule),
                'endpoint': rule.endpoint,
                'methods': list(rule.methods)
            })

    if wycena_routes:
        app_logger.debug("Wycena routes registered", routes_count=len(wycena_routes))

    return app

def sprawdz_w_bazie(email, password):
    user = User.query.filter_by(email=email).first()
    if not user or not user.active:
        return False
    return check_password_hash(user.password, password)

app = create_app()

if __name__ == "__main__":
    app.run(debug=False)