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

    # DWA formaty nazw, bo repo ma historycznie oba:
    #   001_nazwa.sql              — starsze, wersja = numer
    #   2026-08-05-nazwa.sql       — nowsze, wersja = cała nazwa bez rozszerzenia
    #
    # Do 2026-08-06 wzorzec akceptował WYŁĄCZNIE pierwszy format, więc cztery
    # migracje datowane były po cichu pomijane — bez błędu, bez ostrzeżenia,
    # bez śladu w logu. Efekt: schemat trzeba było wgrywać ręcznie przez
    # phpMyAdmin i nikt nie wiedział dlaczego. Stąd też `_log_ignored_files()`
    # niżej: plik w tym katalogu, którego runner nie rozumie, musi krzyczeć.
    MIGRATION_PATTERNS = (
        re.compile(r'^(\d{3})_(.+)\.(sql|py)$'),
        re.compile(r'^((?:\d{4}-\d{2}-\d{2})-.+?)\.(sql|py)$'),
    )

    # Pliki katalogu, które NIE są migracjami i nie mają o sobie przypominać.
    NON_MIGRATION_FILES = frozenset({'__init__.py', 'migration_service.py'})

    def __init__(self, db, logger=None):
        self.db = db
        self.logger = logger
        # Migracje, które padły w ostatnim przebiegu. Pętla celowo NIE
        # przerywa się na pierwszym błędzie (kolejne bywają niezależne),
        # więc bez tej listy wywołujący nie miałby jak odróżnić przebiegu
        # udanego od takiego, w którym wszystko padło — `flask migrate`
        # kończył się kodem 0 również wtedy, a deploy szedł dalej.
        self.failed = []

    def log(self, message, level='info'):
        """Loguje wiadomość."""
        prefix = '[Migrations]'
        full_message = f"{prefix} {message}"

        if self.logger:
            getattr(self.logger, level)(full_message)
        else:
            print(full_message, file=sys.stderr)

    def _match(self, filename):
        """Zwraca (wersja, nazwa, rozszerzenie) albo None."""
        numeryczny, datowany = self.MIGRATION_PATTERNS

        m = numeryczny.match(filename)
        if m:
            return m.group(1), m.group(2), m.group(3)

        m = datowany.match(filename)
        if m:
            # Wersją jest cała nazwa pliku bez rozszerzenia — sama data nie
            # wystarczy, bo dwie migracje z tego samego dnia kolidowałyby
            # na UNIQUE(version) i druga nigdy by się nie wykonała.
            return m.group(1), m.group(1), m.group(2)

        return None

    def _log_ignored_files(self):
        """
        Ostrzega o plikach, których runner nie rozpoznaje. Cicha ignorancja
        w tym miejscu kosztowała cztery niewykonane migracje — plik o złej
        nazwie ma być widoczny w logu deployu, a nie znikać bez słowa.
        """
        for file in sorted(self.MIGRATIONS_DIR.iterdir()):
            if file.is_dir() or file.name in self.NON_MIGRATION_FILES:
                continue
            if file.name.endswith(('.pyc',)) or self._match(file.name):
                continue
            self.log(
                "POMIJAM plik o nierozpoznanej nazwie: {} — oczekiwany format "
                "'001_nazwa.sql' albo '2026-08-05-nazwa.sql'".format(file.name),
                'warning')

    def ensure_migrations_table(self):
        """Tworzy tabelę schema_migrations jeśli nie istnieje."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            version VARCHAR(128) NOT NULL UNIQUE,
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

        # Tabela mogła powstać wcześniej z VARCHAR(10) — za mało na wersję
        # datowaną ('2026-08-05-sawmill'). ALTER jest idempotentny w skutku
        # (poszerzenie kolumny do tej samej szerokości nic nie zmienia),
        # a błąd nie może wywrócić bootu aplikacji.
        try:
            self.db.session.execute(self.db.text(
                "ALTER TABLE schema_migrations MODIFY version VARCHAR(128) NOT NULL"))
            self.db.session.commit()
        except Exception as e:
            self.db.session.rollback()
            self.log(f"Nie udało się poszerzyć kolumny version: {e}", 'warning')

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

        self._log_ignored_files()

        # sorted() po nazwie pliku daje właściwą kolejność: '0' < '2', więc
        # najpierw migracje numeryczne, potem datowane rosnąco.
        for file in sorted(self.MIGRATIONS_DIR.iterdir()):
            if file.is_dir() or file.name in self.NON_MIGRATION_FILES:
                continue
            match = self._match(file.name)
            if not match:
                continue
            version, name, ext = match
            if version not in executed:
                pending.append({
                    'version': version,
                    'name': name,
                    'extension': ext,
                    'path': file
                })

        return pending

    @staticmethod
    def split_statements(sql_content):
        """
        Dzieli plik na polecenia, respektując cudzysłowy i komentarze.

        Zwykły `split(';')` wystarczał, dopóki migracje pisał człowiek i
        pilnował, żeby średnik nie trafił do stringa. Teraz runner chodzi
        automatycznie przy każdym deployu, więc średnik w treści (np. w
        wartości JSON w seedzie albo w komentarzu `-- krok 1; krok 2`)
        rozciąłby polecenie w środku i wywalił migrację na produkcji.

        NIE obsługuje `DELIMITER` — procedur i triggerów tą drogą nie da się
        wgrać (i celowo: to nie jest miejsce na kod wykonywalny w bazie).
        """
        statements = []
        biezace = []
        i, n = 0, len(sql_content)
        cudzyslow = None  # aktywny znak cytowania: ' " lub `

        while i < n:
            znak = sql_content[i]

            if cudzyslow:
                biezace.append(znak)
                if znak == '\\' and i + 1 < n:      # escape wewnątrz stringa
                    biezace.append(sql_content[i + 1])
                    i += 2
                    continue
                if znak == cudzyslow:
                    # Podwojony znak cytowania to znak dosłowny, nie koniec.
                    if i + 1 < n and sql_content[i + 1] == cudzyslow:
                        biezace.append(sql_content[i + 1])
                        i += 2
                        continue
                    cudzyslow = None
                i += 1
                continue

            if znak in ('\'', '"', '`'):
                cudzyslow = znak
                biezace.append(znak)
                i += 1
                continue

            if sql_content.startswith('--', i) or znak == '#':
                koniec = sql_content.find('\n', i)
                i = n if koniec == -1 else koniec + 1
                biezace.append('\n')
                continue

            if sql_content.startswith('/*', i):
                koniec = sql_content.find('*/', i + 2)
                i = n if koniec == -1 else koniec + 2
                continue

            if znak == ';':
                statements.append(''.join(biezace).strip())
                biezace = []
                i += 1
                continue

            biezace.append(znak)
            i += 1

        ogon = ''.join(biezace).strip()
        if ogon:
            statements.append(ogon)

        return [s for s in statements if s]

    def execute_sql_migration(self, migration):
        """Wykonuje migrację SQL."""
        sql_content = migration['path'].read_text(encoding='utf-8')
        statements = self.split_statements(sql_content)

        for statement in statements:
            try:
                self.db.session.execute(self.db.text(statement))
            except Exception as e:
                # Ignoruj błędy "kolumna już istnieje" / "tabela już istnieje"
                error_str = str(e).lower()
                # 1060 duplicate column / 1061 duplicate key name / 1050 table
                # exists — wszystkie znaczą „ta zmiana już jest w bazie".
                # Runner chodzi automatycznie przy każdym deployu, więc migracja
                # wgrana wcześniej ręcznie nie może wywracać całego przebiegu.
                juz_jest = ('duplicate column', 'duplicate key name',
                            'already exists')
                if any(f in error_str for f in juz_jest):
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
        self.failed = []
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
                self.failed.append((migration_desc, error_msg))
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
