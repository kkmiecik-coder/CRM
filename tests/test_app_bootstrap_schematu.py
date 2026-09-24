# -*- coding: utf-8 -*-
"""
Test bootstrapu schematu bazy w `app.py` (funkcja `_bootstrap_schema`).

Kontekst błędu (21.09.2026): `db.create_all()` tworzył brakujące tabele z
AKTUALNYCH modeli SQLAlchemy, uruchamiany PRZED migracjami. Migracja, która
np. zmienia nazwę tabeli (`clients` -> `leads`), zastawała tabelę docelową
już utworzoną (pustą) przez `create_all()` i nie miała czego migrować —
dane zostawały w starej tabeli, aplikacja czytała z nowej, pustej.

Kontekst regresji (21.09.2026): odwrócenie kolejności naprawiło bazę
ISTNIEJĄCĄ, ale zepsuło PUSTĄ. Na świeżej instalacji migracje nie mają czego
zmieniać (ALTER/UPDATE/DROP na nieistniejących tabelach), więc padają hurtowo,
a `failed` blokowało `create_all()` — nowy deweloper dostawał bazę praktycznie
bez tabel. Zmierzone na czystej bazie MySQL: 8 tabel zamiast 73.

Ten test dowodzi trzech własności `_bootstrap_schema()`:
1. na bazie NIEPUSTEJ migracje wykonują się PRZED `db.create_all()` (twardy
   dowód kolejności przez wspólny Mock-manager i jego `mock_calls`, a nie tylko
   sprawdzenie, że oba zostały wywołane),
2. na bazie niepustej `db.create_all()` NIE wykonuje się, gdy migracje zgłosiły
   niepowodzenie (`migration_service.failed` niepuste) — inaczej create_all()
   dotworzyłby tabele w nowym kształcie i zamaskował awarię o krok później,
3. na bazie PUSTEJ kolejność jest ODWROTNA: `db.create_all()` idzie pierwszy
   i wykonuje się BEZ WZGLĘDU na wynik migracji.

Detekcję pustej bazy (`_baza_jest_pusta()`) sprawdzamy osobno, na prawdziwym
SQLite — bo to na SQLite jadą testy, a detekcja nie może być przywiązana do
`information_schema` MySQL-a.
"""
from unittest.mock import Mock, call, patch

import pytest
from flask import Flask


@pytest.fixture
def bootstrap_schema():
    # Import odroczony do wnętrza fixture'a: samo zaimportowanie modułu
    # app.py na poziomie modułu odpala `app = create_app()` (linia bez
    # osłony `if __name__ == "__main__"`), co łączy się z prawdziwą bazą
    # z config/core.json. Ten sam wzorzec co w tests/test_daily_report_cli.py
    # — ochroną jest wyłącznie to, że testy jadą w kontenerze `app`, gdzie
    # kontener `db` już stoi, więc samo wykonanie się nie wywala.
    from app import _bootstrap_schema
    return _bootstrap_schema


@pytest.fixture
def baza_jest_pusta():
    """Prawdziwa detekcja pustej bazy — do testów na SQLite (bez mocków)."""
    from app import _baza_jest_pusta
    return _baza_jest_pusta


def _zbuduj_app(run_db_setup=True, run_migrations=True):
    """Lekka apka Flask — bez db.init_app(), bo db.create_all() jest mockowane."""
    app = Flask(__name__)
    app.config['RUN_DB_SETUP'] = run_db_setup
    app.config['RUN_MIGRATIONS'] = run_migrations
    return app


def _fake_migration_service(failed=None):
    """
    Atrapa MigrationService: `.failed` jest zwykłym atrybutem instancji
    (nie da się go ustawić z zewnątrz przez side_effect na zamockowanej
    metodzie klasowej, bo Mock nie jest deskryptorem i nie dostaje `self`),
    więc kontrolujemy go bezpośrednio na atrapie instancji.
    """
    service = Mock()
    service.failed = failed or []
    return service


class TestKolejnoscMigracjePrzedCreateAll:
    """
    Własność 1: na bazie NIEPUSTEJ migracje idą PRZED create_all() — dowód
    przez mock_calls. Stan bazy podmieniamy jawnie (`_baza_jest_pusta` ->
    False), bo od 22.09.2026 kolejność zależy właśnie od niego.
    """

    def test_migracje_wykonuja_sie_przed_create_all(self, bootstrap_schema):
        manager = Mock()

        fake_service = _fake_migration_service(failed=[])
        manager.attach_mock(fake_service.run_pending_migrations, 'run_pending_migrations')

        mock_create_all = Mock()
        manager.attach_mock(mock_create_all, 'create_all')

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=False), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        # Twardy dowód kolejności: sekwencja wywołań na WSPÓLNYM managerze,
        # nie tylko fakt, że oba mocki zostały wywołane.
        assert manager.mock_calls == [
            call.run_pending_migrations(),
            call.create_all(),
        ]

    def test_create_all_wolane_gdy_run_db_setup_wylaczone_migracje_ok(self, bootstrap_schema):
        """Migracje bez RUN_DB_SETUP: create_all() w ogóle nie powinno paść."""
        manager = Mock()

        fake_service = _fake_migration_service(failed=[])
        manager.attach_mock(fake_service.run_pending_migrations, 'run_pending_migrations')

        mock_create_all = Mock()
        manager.attach_mock(mock_create_all, 'create_all')

        app = _zbuduj_app(run_db_setup=False, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=False), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        assert manager.mock_calls == [call.run_pending_migrations()]
        mock_create_all.assert_not_called()


class TestCreateAllPominietePrzyNieudanychMigracjach:
    """
    Własność 2: na bazie NIEPUSTEJ create_all() NIE wykonuje się, gdy migracje
    padły. Na pustej bazie jest odwrotnie — patrz klasa niżej.
    """

    def test_create_all_pominiete_gdy_migration_service_zglosil_failed(self, bootstrap_schema):
        fake_service = _fake_migration_service(
            failed=[('2026-09-22-clients-na-leads.sql', 'boom')]
        )

        mock_create_all = Mock()

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=False), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        mock_create_all.assert_not_called()

    def test_create_all_pominiete_gdy_run_pending_migrations_rzuca_wyjatek(self, bootstrap_schema):
        """
        Druga ścieżka niepowodzenia: wyjątek podniesiony POZA pętlą per-migrację
        (np. _ensure_migrations_table()), łapany przez try/except w bootstrapie.
        """
        fake_service = Mock()
        fake_service.run_pending_migrations.side_effect = RuntimeError("brak polaczenia z baza")
        fake_service.failed = []

        mock_create_all = Mock()

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=False), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        mock_create_all.assert_not_called()

    def test_create_all_wolane_gdy_migracje_przechodza(self, bootstrap_schema):
        """Kontrola pozytywna: bez niepowodzeń create_all() jednak wołane."""
        fake_service = _fake_migration_service(failed=[])

        mock_create_all = Mock()

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=False), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        mock_create_all.assert_called_once()


class TestPustaBazaCreateAllPierwszy:
    """
    Własność 3: na bazie PUSTEJ (świeża instalacja) kolejność jest odwrotna —
    create_all() idzie PIERWSZY i wykonuje się niezależnie od wyniku migracji.

    To jest regresja z 2dec689: na pustej bazie 40 z 52 migracji pada (ALTER /
    UPDATE / DROP na tabelach, których jeszcze nie ma), więc reguła „create_all
    tylko gdy migracje przeszły" zostawiała nowego dewelopera z bazą bez tabel.
    """

    def test_create_all_idzie_przed_migracjami_na_pustej_bazie(self, bootstrap_schema):
        manager = Mock()

        fake_service = _fake_migration_service(failed=[])
        manager.attach_mock(fake_service.run_pending_migrations, 'run_pending_migrations')

        mock_create_all = Mock()
        manager.attach_mock(mock_create_all, 'create_all')

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=True), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        # Twardy dowód kolejności ODWROTNEJ niż na bazie niepustej.
        assert manager.mock_calls == [
            call.create_all(),
            call.run_pending_migrations(),
        ]

    def test_create_all_wykonane_mimo_nieudanych_migracji_na_pustej_bazie(self, bootstrap_schema):
        """
        Sedno regresji: migracje padają (bo nie mają czego zmieniać), a schemat
        MIMO TO musi powstać — inaczej świeża instalacja kończy się bez tabel.
        """
        fake_service = _fake_migration_service(
            failed=[('013_finish_columns.sql', 'brak tabeli prod_items')]
        )

        mock_create_all = Mock()

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=True), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        mock_create_all.assert_called_once()

    def test_create_all_wykonane_raz_gdy_migracje_przechodza_na_pustej_bazie(self, bootstrap_schema):
        """Świeża instalacja bez awarii migracji nie może wołać create_all() dwa razy."""
        fake_service = _fake_migration_service(failed=[])

        mock_create_all = Mock()

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=True), \
             patch('app.db.create_all', new=mock_create_all), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        mock_create_all.assert_called_once()

    def test_migracje_i_tak_leca_na_pustej_bazie(self, bootstrap_schema):
        """
        Świeża instalacja NIE jest „stemplowana" — migracje muszą pójść także
        na pustej bazie, bo część z nich wstawia dane startowe
        (np. 005_finishing_options_data.sql).
        """
        fake_service = _fake_migration_service(failed=[])

        app = _zbuduj_app(run_db_setup=True, run_migrations=True)

        with patch('app._baza_jest_pusta', return_value=True), \
             patch('app.db.create_all', new=Mock()), \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        fake_service.run_pending_migrations.assert_called_once()

    def test_stan_bazy_nie_jest_sprawdzany_gdy_run_db_setup_wylaczone(self, bootstrap_schema):
        """
        Bez RUN_DB_SETUP create_all() nie padnie tak czy inaczej, więc silnika
        nie odpytujemy — inaczej boot z wyłączonym setupem wymuszałby połączenie
        z bazą tylko po to, żeby policzyć tabele.
        """
        fake_service = _fake_migration_service(failed=[])

        app = _zbuduj_app(run_db_setup=False, run_migrations=True)

        with patch('app._baza_jest_pusta') as mock_detekcja, \
             patch('app.db.create_all') as mock_create_all, \
             patch('migrations.MigrationService', return_value=fake_service), \
             patch('app.discover_module_metadata', return_value={}):
            with app.app_context():
                bootstrap_schema(app)

        mock_detekcja.assert_not_called()
        mock_create_all.assert_not_called()


class TestDetekcjaPustejBazyNaSQLite:
    """
    Detekcja pustej bazy na PRAWDZIWYM silniku, nie na mocku. SQLite, bo na tym
    jadą testy — a detekcja oparta o `information_schema` działałaby wyłącznie
    na MySQL-u i tutaj wywracałaby się cicho w stronę „baza niepusta".
    """

    @staticmethod
    def _app_na_sqlite(tmp_path, nazwa):
        from extensions import db as prawdziwe_db

        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(tmp_path / nazwa)
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        prawdziwe_db.init_app(app)
        return app, prawdziwe_db

    def test_baza_bez_tabel_jest_pusta(self, baza_jest_pusta, tmp_path):
        app, _ = self._app_na_sqlite(tmp_path, 'pusta.db')

        with app.app_context():
            assert baza_jest_pusta() is True

    def test_baza_z_samym_schema_migrations_wciaz_jest_pusta(self, baza_jest_pusta, tmp_path):
        """
        Runner migracji zakłada `schema_migrations` SAM, zanim wykona cokolwiek.
        Gdyby liczyła się jako tabela aplikacji, wystarczyłby jeden przerwany
        start, żeby świeża baza na zawsze udawała istniejącą instalację.
        """
        app, prawdziwe_db = self._app_na_sqlite(tmp_path, 'tylko_migracje.db')

        with app.app_context():
            prawdziwe_db.session.execute(prawdziwe_db.text(
                "CREATE TABLE schema_migrations (version VARCHAR(128))"))
            prawdziwe_db.session.commit()

            assert baza_jest_pusta() is True

    def test_baza_z_tabela_aplikacji_nie_jest_pusta(self, baza_jest_pusta, tmp_path):
        app, prawdziwe_db = self._app_na_sqlite(tmp_path, 'z_danymi.db')

        with app.app_context():
            prawdziwe_db.session.execute(prawdziwe_db.text(
                "CREATE TABLE leads (id INTEGER PRIMARY KEY)"))
            prawdziwe_db.session.commit()

            assert baza_jest_pusta() is False

    def test_brak_silnika_traktujemy_jak_baze_niepusta(self, baza_jest_pusta):
        """
        Wariant ostrożny: jeśli stanu bazy nie da się ustalić, zostajemy przy
        kolejności chroniącej dane istniejącej instalacji (migracje pierwsze).
        """
        app = Flask(__name__)  # bez db.init_app() — db.engine rzuci

        with app.app_context():
            assert baza_jest_pusta() is False
