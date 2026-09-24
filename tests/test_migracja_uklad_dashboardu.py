# -*- coding: utf-8 -*-
"""Kształt migracji zakładającej `reports_dashboard_layouts` i zgodność
modelu z tym, co zakłada migracja.

Testy jadą na SQLite, która nie zna ani information_schema, ani PREPARE.
Sprawdzamy więc to, co da się sprawdzić bez MySQL-a: czy runner weźmie plik
pod uwagę, na ile poleceń go podzieli, czy para PREPARE/EXECUTE/DEALLOCATE
się zgadza i czy CREATE TABLE stoi WYŁĄCZNIE w gałęzi „tabeli jeszcze nie ma".

DRUGA POŁOWA TEGO PLIKU pilnuje czegoś, czego żaden test tego repo dotąd nie
pilnował przy nowej tabeli: że MODEL deklaruje te same ograniczenia, co
migracja. Pakiet buduje SQLite Z MODELU, więc ograniczenie, które jest tylko
w SQL-u, jest dla wszystkich 3000 testów niewidzialne. Ta klasa rozjazdu już
raz w tym projekcie ugryzła (fk_so_client SET NULL kontra
sales_orders_ibfk_1 NO ACTION).

CZEGO TE TESTY NIE GWARANTUJĄ: że plik SQL naprawdę się wykona. Porównują
tekst. Wykonanie na czystej bazie MySQL potwierdzają kroki 8–10 tego zadania.
"""
from pathlib import Path

from migrations.migration_service import MigrationService

KATALOG_MIGRACJI = Path(__file__).resolve().parents[1] / "migrations"
SCIEZKA = KATALOG_MIGRACJI / "2026-09-23-uklad-dashboardu.sql"


def _tresc():
    return SCIEZKA.read_text(encoding="utf-8")


def _polecenia():
    return MigrationService.split_statements(_tresc())


def _bez_bialych(tekst):
    return " ".join(tekst.split())


def test_plik_istnieje():
    assert SCIEZKA.exists(), "brak pliku migracji"


def test_runner_rozpoznaje_nazwe_pliku():
    """STRAŻNIK: gdyby nazwa przestała pasować do wzorca, runner pominąłby
    migrację PO CICHU i deploy zakończyłby się zielono ze starym schematem."""
    service = MigrationService(db=None)
    assert service._match(SCIEZKA.name) is not None


def test_nie_uzywa_zmiany_separatora_polecen():
    """Runner dzieli plik wyłącznie po średniku; DELIMITER nie jest obsługiwany."""
    assert "DELIMITER" not in _tresc().upper()


def test_dzieli_sie_na_5_polecen():
    """1 SET (@tabela_istnieje) + 1 SET (@sql) + PREPARE + EXECUTE + DEALLOCATE."""
    polecenia = _polecenia()
    assert len(polecenia) == 5, [_bez_bialych(p)[:70] for p in polecenia]


def test_odczyt_istnienia_tabeli_nie_uzywa_prepare():
    """Zapytanie idzie do information_schema, nie do tworzonej tabeli, więc
    błąd 1146 mu nie grozi i PREPARE byłby tu złożonością bez korzyści."""
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    odczyt = next(p for p in polecenia if p.startswith("SET @tabela_istnieje"))
    assert "information_schema.TABLES" in odczyt
    assert "TABLE_NAME = 'reports_dashboard_layouts'" in odczyt
    assert "TABLE_SCHEMA = DATABASE()" in odczyt


def test_create_table_stoi_tylko_w_galezi_tabeli_jeszcze_nie_ma():
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    budowa = next(p for p in polecenia if p.startswith("SET @sql"))
    assert "@tabela_istnieje = 0" in budowa
    assert "CREATE TABLE reports_dashboard_layouts" in budowa
    # Żadne inne polecenie nie może tworzyć tabeli.
    inne = [p for p in polecenia if not p.startswith("SET @sql")]
    assert not any("CREATE TABLE" in p for p in inne)


def test_nie_uzywa_create_table_if_not_exists():
    """PUŁAPKA, która raz kosztowała zablokowany deploy: przy RUN_DB_SETUP=true
    `db.create_all()` tworzy tabelę Z METADANYCH, zanim migracja dostanie szansę.
    `CREATE TABLE IF NOT EXISTS` byłby wtedy no-opem — plik mógłby zawierać błąd
    składni, a lokalnie nikt by tego nie zobaczył. Budowanie polecenia
    warunkowo z information_schema nie zmienia tego faktu, ale przynajmniej
    nazywa go wprost, a krok weryfikacji tego zadania wykonuje plik na CZYSTEJ
    bazie, wprost przez `mysql`."""
    assert "IF NOT EXISTS" not in _tresc().upper()


def test_napisy_w_sql_sa_w_apostrofach_a_nie_w_cudzyslowach():
    """Przegląd gałęzi, D6. Przy `sql_mode` z ANSI_QUOTES `"…"` jest
    IDENTYFIKATOREM, nie napisem — gałąź „tabela już istnieje" padłaby wtedy
    błędem nieznanej kolumny. Wdrożone migracje piszą napis wewnątrz
    dynamicznego SQL-a jako `''…''` i ta robi tak samo. Sprawdzamy polecenia
    PO podziale runnera, czyli bez komentarzy (polskie „…" w komentarzach
    niczego nie psują)."""
    for polecenie in _polecenia():
        assert '"' not in polecenie, _bez_bialych(polecenie)[:90]


def test_kazdy_prepare_ma_execute_i_deallocate_pod_ta_sama_nazwa():
    polecenia = [_bez_bialych(p) for p in _polecenia()]
    przygotowania = [p for p in polecenia if p.upper().startswith("PREPARE ")]
    wykonania = [p for p in polecenia if p.upper().startswith("EXECUTE ")]
    zwolnienia = [p for p in polecenia if p.upper().startswith("DEALLOCATE ")]
    assert len(przygotowania) == len(wykonania) == len(zwolnienia) == 1
    nazwa = przygotowania[0].split()[1]
    assert wykonania[0].split()[1] == nazwa
    assert zwolnienia[0].split()[2] == nazwa


def test_tabela_ma_klucz_obcy_z_kaskada_na_users():
    """Skasowanie użytkownika ma zabrać jego układ. Bez CASCADE zostałby
    wiersz-sierota, którego nic już nie odczyta."""
    tresc = _bez_bialych(_tresc())
    assert "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE" in tresc


def test_tabela_ma_unikalnosc_na_user_id():
    """Jeden układ na użytkownika. Bez tego dwa równoległe zapisy z dwóch kart
    przeglądarki zostawiłyby DWA wiersze i odczyt wybierałby niedeterministycznie."""
    assert "UNIQUE KEY uq_rdl_user (user_id)" in _bez_bialych(_tresc())


def test_nazwy_ograniczen_sa_jawne():
    """MySQL nadaje własne nazwy (reports_dashboard_layouts_ibfk_1), które
    różnią się od tych, które nada `db.create_all()`. Jawna nazwa to jedyny
    sposób, żeby obie drogi dały ten sam schemat."""
    tresc = _bez_bialych(_tresc())
    assert "CONSTRAINT fk_rdl_user" in tresc


def test_kolumna_ukladu_jest_typu_json_i_nie_moze_byc_pusta():
    assert "uklad JSON NOT NULL" in _bez_bialych(_tresc())


# --- zgodność modelu z migracją --------------------------------------------

def test_model_ma_te_sama_nazwe_tabeli_co_migracja():
    from modules.reports.models_uklad import UkladDashboardu
    assert UkladDashboardu.__tablename__ == "reports_dashboard_layouts"


def test_model_deklaruje_unikalnosc_user_id_pod_nazwa_z_migracji():
    """Pakiet buduje SQLite Z MODELU. Ograniczenie, którego model nie zna
    POD TĄ SAMĄ NAZWĄ co migracja, jest niewidzialne dla wszystkich testów —
    samo `unique is True` by tego nie złapało: `db.create_all()` nadałby
    nienazwanemu ograniczeniu własną nazwę, różną od `uq_rdl_user` z pliku
    SQL, i schemat lokalny rozjechałby się z produkcyjnym po cichu."""
    from sqlalchemy import UniqueConstraint

    from modules.reports.models_uklad import UkladDashboardu
    ograniczenia = [c for c in UkladDashboardu.__table__.constraints
                    if isinstance(c, UniqueConstraint)]
    assert len(ograniczenia) == 1, 'model ma mieć dokładnie jedno ograniczenie unikalności'
    ograniczenie = ograniczenia[0]
    assert ograniczenie.name == 'uq_rdl_user'
    assert [kolumna.name for kolumna in ograniczenie.columns] == ['user_id']


def test_model_deklaruje_kaskade_na_kluczu_obcym_pod_nazwa_z_migracji():
    from modules.reports.models_uklad import UkladDashboardu
    klucze = list(UkladDashboardu.__table__.c.user_id.foreign_keys)
    assert len(klucze) == 1
    assert klucze[0].ondelete == "CASCADE"
    assert klucze[0].column.table.name == "users"
    assert klucze[0].constraint.name == "fk_rdl_user"


def test_model_nie_pozwala_na_pusty_uklad_w_kolumnie():
    from modules.reports.models_uklad import UkladDashboardu
    assert UkladDashboardu.__table__.c.uklad.nullable is False


def test_model_ma_kolumne_updated_at():
    from modules.reports.models_uklad import UkladDashboardu
    assert UkladDashboardu.__table__.c.updated_at.nullable is False
