"""
Usuwa kolumnę `pesel` z tabeli partner_applications.

DLACZEGO: PESEL został kiedyś wycofany z całego modułu Akademii Partnera —
nie ma go w formularzu rekrutacyjnym, w szablonie NDA, w modelu
PartnerApplication ani w walidatorach. W bazie została jednak kolumna
`pesel VARCHAR(11) NOT NULL` BEZ wartości domyślnej. Skutek: model wstawiał
wiersz bez tej kolumny, a MySQL w trybie strict odrzucał CAŁY insert błędem
1364 "Field 'pesel' doesn't have a default value". Formularz rekrutacyjny nie
przyjął ani jednego zgłoszenia od 2026-05-26 — kandydat wypełniał wszystko,
podpisywał NDA i na ostatnim kroku dostawał błąd.

DLACZEGO DROP, a nie zmiana na NULL: numer PESEL to dana wrażliwa, potrzebna
dopiero na etapie umowy, a nie rekrutacji. Skoro żadna część systemu jej już
nie czyta, trzymanie PESEL-i historycznych kandydatów jest zbędnym ryzykiem.
Ta migracja kasuje je bezpowrotnie — świadomie i bez kopii zapasowej, bo kopia
danych, których nie chcemy trzymać, mija się z celem.

DLACZEGO PYTHON, a nie .sql: MySQL nie zna `DROP COLUMN IF EXISTS`, a na
świeżym środowisku (lokalny Docker postawiony z modeli) kolumny `pesel` nigdy
nie było — goły ALTER wywaliłby się wtedy błędem 1091. MigrationService pomija
tylko błędy typu "duplicate column"/"already exists", więc 1091 by przeszedł
dalej i wysypał migrację. Stąd ręczne sprawdzenie przed wykonaniem.

Sprawdzenie robimy przez SHOW COLUMNS, a nie information_schema — część
hostingów blokuje dostęp do information_schema, SHOW COLUMNS działa wszędzie.
"""


def run_migration(db):
    # Brak tabeli = środowisko przed utworzeniem schematu; nie ma czego usuwać
    try:
        columns = db.session.execute(
            db.text("SHOW COLUMNS FROM partner_applications LIKE 'pesel'")
        ).fetchall()
    except Exception:
        db.session.rollback()
        return

    if not columns:
        # Kolumny nie ma — świeże środowisko postawione z modeli. No-op.
        return

    db.session.execute(
        db.text("ALTER TABLE partner_applications DROP COLUMN pesel")
    )
    db.session.commit()
