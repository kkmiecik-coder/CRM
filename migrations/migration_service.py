"""
Serwis do automatycznego wykonywania migracji bazy danych.
"""

import os
import re
import sys
import importlib.util
from datetime import datetime
from pathlib import Path


class MigrationService:
    """
    Zarządza migracjami bazy danych.

    Migracje są śledzone w tabeli `schema_migrations`.
    Wykonywane są tylko te, które jeszcze nie zostały zastosowane.
    """

    MIGRATIONS_DIR = Path(__file__).parent
    MIGRATION_PATTERN = re.compile(r'^(\d{3})_(.+)\.(sql|py)$')

    def __init__(self, db, logger=None):
        self.db = db
        self.logger = logger

    def log(self, message, level='info'):
        """Loguje wiadomość."""
        prefix = '[Migrations]'
        full_message = f"{prefix} {message}"

        if self.logger:
            getattr(self.logger, level)(full_message)
        else:
            print(full_message, file=sys.stderr)

    def ensure_migrations_table(self):
        """Tworzy tabelę schema_migrations jeśli nie istnieje."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            version VARCHAR(10) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success BOOLEAN DEFAULT TRUE,
            error_message TEXT DEFAULT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """
        try:
            self.db.session.execute(self.db.text(create_table_sql))
            self.db.session.commit()
        except Exception as e:
            self.log(f"Błąd tworzenia tabeli schema_migrations: {e}", 'error')
            self.db.session.rollback()
            raise

    def get_executed_migrations(self):
        """Pobiera listę już wykonanych migracji."""
        try:
            result = self.db.session.execute(
                self.db.text("SELECT version FROM schema_migrations WHERE success = TRUE")
            )
            return {row[0] for row in result.fetchall()}
        except Exception:
            # Tabela może nie istnieć jeszcze
            return set()

    def get_pending_migrations(self):
        """Zwraca listę migracji do wykonania (posortowane po numerze)."""
        executed = self.get_executed_migrations()
        pending = []

        for file in sorted(self.MIGRATIONS_DIR.iterdir()):
            match = self.MIGRATION_PATTERN.match(file.name)
            if match:
                version = match.group(1)
                name = match.group(2)
                ext = match.group(3)

                if version not in executed:
                    pending.append({
                        'version': version,
                        'name': name,
                        'extension': ext,
                        'path': file
                    })

        return pending

    def execute_sql_migration(self, migration):
        """Wykonuje migrację SQL."""
        sql_content = migration['path'].read_text(encoding='utf-8')

        # Podziel na pojedyncze polecenia (po średniku)
        statements = [s.strip() for s in sql_content.split(';') if s.strip()]

        for statement in statements:
            # Pomiń komentarze
            if statement.startswith('--'):
                continue
            try:
                self.db.session.execute(self.db.text(statement))
            except Exception as e:
                # Ignoruj błędy "kolumna już istnieje" / "tabela już istnieje"
                error_str = str(e).lower()
                if 'duplicate column' in error_str or 'already exists' in error_str:
                    self.log(f"  Pominięto (już istnieje): {statement[:50]}...", 'warning')
                    continue
                raise

        self.db.session.commit()

    def execute_python_migration(self, migration):
        """Wykonuje migrację Python."""
        spec = importlib.util.spec_from_file_location(
            f"migration_{migration['version']}",
            migration['path']
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'run_migration'):
            module.run_migration(self.db)
        else:
            raise AttributeError(
                f"Migracja {migration['path'].name} nie ma funkcji run_migration()"
            )

    def record_migration(self, migration, success=True, error_message=None):
        """Zapisuje informację o wykonanej migracji."""
        try:
            self.db.session.execute(
                self.db.text("""
                    INSERT INTO schema_migrations (version, name, success, error_message)
                    VALUES (:version, :name, :success, :error_message)
                    ON DUPLICATE KEY UPDATE
                        success = :success,
                        error_message = :error_message,
                        executed_at = CURRENT_TIMESTAMP
                """),
                {
                    'version': migration['version'],
                    'name': migration['name'],
                    'success': success,
                    'error_message': error_message
                }
            )
            self.db.session.commit()
        except Exception as e:
            self.log(f"Błąd zapisu migracji: {e}", 'error')
            self.db.session.rollback()

    def run_pending_migrations(self):
        """
        Wykonuje wszystkie oczekujące migracje.
        Zwraca liczbę wykonanych migracji.
        """
        self.ensure_migrations_table()
        pending = self.get_pending_migrations()

        if not pending:
            self.log("Brak nowych migracji do wykonania")
            return 0

        self.log(f"Znaleziono {len(pending)} migracji do wykonania")
        executed_count = 0

        for migration in pending:
            migration_desc = f"{migration['version']}_{migration['name']}.{migration['extension']}"
            self.log(f"Wykonuję: {migration_desc}")

            try:
                if migration['extension'] == 'sql':
                    self.execute_sql_migration(migration)
                elif migration['extension'] == 'py':
                    self.execute_python_migration(migration)

                self.record_migration(migration, success=True)
                self.log(f"  ✓ Sukces: {migration_desc}")
                executed_count += 1

            except Exception as e:
                error_msg = str(e)
                self.log(f"  ✗ Błąd: {migration_desc} - {error_msg}", 'error')
                self.record_migration(migration, success=False, error_message=error_msg)
                self.db.session.rollback()
                # Kontynuuj z następnymi migracjami (nie przerywaj całości)

        self.log(f"Wykonano {executed_count}/{len(pending)} migracji")
        return executed_count

    def get_migration_status(self):
        """Zwraca status wszystkich migracji."""
        self.ensure_migrations_table()

        # Pobierz wszystkie migracje z plików
        all_migrations = []
        for file in sorted(self.MIGRATIONS_DIR.iterdir()):
            match = self.MIGRATION_PATTERN.match(file.name)
            if match:
                all_migrations.append({
                    'version': match.group(1),
                    'name': match.group(2),
                    'extension': match.group(3)
                })

        # Pobierz wykonane migracje z bazy
        try:
            result = self.db.session.execute(
                self.db.text("SELECT version, name, executed_at, success, error_message FROM schema_migrations")
            )
            executed = {row[0]: {
                'name': row[1],
                'executed_at': row[2],
                'success': row[3],
                'error_message': row[4]
            } for row in result.fetchall()}
        except Exception:
            executed = {}

        # Połącz informacje
        status = []
        for m in all_migrations:
            if m['version'] in executed:
                exec_info = executed[m['version']]
                status.append({
                    **m,
                    'status': 'success' if exec_info['success'] else 'failed',
                    'executed_at': exec_info['executed_at'],
                    'error_message': exec_info['error_message']
                })
            else:
                status.append({
                    **m,
                    'status': 'pending',
                    'executed_at': None,
                    'error_message': None
                })

        return status
