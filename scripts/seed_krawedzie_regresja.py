"""
Dane testowe dla regresji wizualnej Krawędzi (sesja apki Android).

Wstawia do kolejki Krawedzi po jednej sztuce na kazda sciezke renderowania,
ktorej dotad nikt nie widzial na ekranie. Cztery z pieciu to ISTNIEJACE wiersze
— tylko przestawiamy im status, wiec nie fabrykujemy danych tam, gdzie prawdziwe
juz sa. Piata (pelna degeneracja) nie wystepuje w produkcji w ogole, wiec
powstaje jako NOWY wiersz, nie przez psucie istniejacego.

TYLKO DEV. Skrypt przestawia statusy i tworzy wiersz — nie uruchamiac na
produkcji. Id-ki ponizej pochodza z kopii produkcji z 2026-09-16; po ponownym
imporcie bazy zgadzaja sie dalej, po przebudowie od zera juz nie.

Uruchamianie (z katalogu repo):
    docker compose exec app python3 scripts/seed_krawedzie_regresja.py
    docker compose exec app python3 scripts/seed_krawedzie_regresja.py --revert

--revert przywraca oryginalne statusy, odbicia i daty domkniecia oraz kasuje
utworzony wiersz. Stan zapamietuje pomocnicza tabela _seed_krawedzie_kopia,
zeby cofanie nie zgadywalo.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from modules.production.models import ProductionProduct

STATUS_KRAWEDZIE = 'czeka_na_krawedzie'

# id -> po co ta pozycja jest w kolejce
DO_PRZESTAWIENIA = {
    754:  'kolo (circle, fazowanie KD, 95x95) — walec z dwiema obreczami',
    1428: 'wielokat (polygon) z niepustym shape_svg — rysunek z serwera',
    6:    'pusty plan obrobki przy zachowanych wymiarach (125x110x2.5) — karta NIE OBRABIAJ NA OKO',
    2608: 'quantity 15 — stopka dwurzedowa',
}

# Marker wiersza tworzonego przez ten skrypt — po nim go kasujemy przy --revert.
MARKER = 'REGRESJA-WIZUALNA-degeneracja'
WZORZEC_ID = 6  # pusty plan i brak svg — wystarczy wyzerowac wymiary


def _tabela_stanu():
    """Pomocnicza tabela na oryginalny stan, zeby --revert nie zgadywal."""
    db.session.execute(db.text("""
        CREATE TABLE IF NOT EXISTS _seed_krawedzie_kopia (
            produkt_id    INT NOT NULL PRIMARY KEY,
            stary_status  VARCHAR(40) NOT NULL,
            stare_odbicia INT NOT NULL,
            stara_data    DATETIME NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """))


def seed():
    _tabela_stanu()

    for pid, opis in DO_PRZESTAWIENIA.items():
        p = db.session.get(ProductionProduct, pid)
        if p is None:
            print(f'  ! brak pozycji id={pid} — pomijam ({opis})')
            continue
        if p.current_status != STATUS_KRAWEDZIE:
            db.session.execute(
                db.text('INSERT IGNORE INTO _seed_krawedzie_kopia VALUES (:i, :s, :o, :d)'),
                {'i': pid, 's': p.current_status,
                 'o': p.quantity_done_edges or 0, 'd': p.edges_completed_at},
            )
            p.current_status = STATUS_KRAWEDZIE
            # Pozycje sciagniete ze 'spakowane' niosa historyczne odbicia
            # (quantity_done_edges == quantity, ustawiony edges_completed_at).
            # W kolejce wygladalyby na zrobione i wyrenderowalyby sie inaczej
            # niz prawdziwa praca do zrobienia — czyli minelyby sie z celem testu.
            p.quantity_done_edges = 0
            p.edges_completed_at = None
        print(f'  + {p.short_product_id:10} {opis}')

    istnieje = ProductionProduct.query.filter_by(production_notes=MARKER).first()
    if istnieje is None:
        wzor = db.session.get(ProductionProduct, WZORZEC_ID)
        zdegenerowany = ProductionProduct(
            order_id=wzor.order_id,
            configuration_id=wzor.configuration_id,
            short_product_id=f'{wzor.short_product_id.split("_")[0]}_99',
            product_sequence_in_order=99,
            original_product_name='[REGRESJA] pusty plan, brak wymiarow, brak SVG',
            # Pelna degeneracja: plan pusty, wymiary nieuzyteczne, zadnego SVG.
            parsed_edge_processing=True,
            parsed_edge_type=None,
            parsed_edge_letters=None,
            parsed_edges_groups=None,
            parsed_length_cm=None,
            parsed_width_cm=None,
            parsed_thickness_cm=None,
            edge_svg=None,
            shape_svg=None,
            shape='rectangular',
            quantity=1,
            current_status=STATUS_KRAWEDZIE,
            production_notes=MARKER,
        )
        db.session.add(zdegenerowany)
        print(f'  + {zdegenerowany.short_product_id:10} pelna degeneracja panelu (NOWY wiersz)')
    else:
        print(f'  = {istnieje.short_product_id:10} pelna degeneracja — juz istnieje, pomijam')

    db.session.commit()


def revert():
    wiersze = db.session.execute(
        db.text('SELECT produkt_id, stary_status, stare_odbicia, stara_data '
                'FROM _seed_krawedzie_kopia')
    ).fetchall()
    for pid, stary, odbicia, data in wiersze:
        p = db.session.get(ProductionProduct, pid)
        if p is not None:
            p.current_status = stary
            p.quantity_done_edges = odbicia
            p.edges_completed_at = data
            print(f'  - {p.short_product_id:10} status {stary}, odbicia {odbicia}')

    usuniete = ProductionProduct.query.filter_by(production_notes=MARKER).all()
    for p in usuniete:
        print(f'  - {p.short_product_id:10} kasuje wiersz utworzony przez skrypt')
        db.session.delete(p)

    db.session.execute(db.text('DROP TABLE IF EXISTS _seed_krawedzie_kopia'))
    db.session.commit()


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        if '--revert' in sys.argv:
            print('COFANIE:')
            revert()
        else:
            print('SEED kolejki Krawedzi:')
            seed()

        ile = ProductionProduct.query.filter_by(current_status=STATUS_KRAWEDZIE).count()
        print(f'\nKolejka Krawedzi liczy teraz {ile} pozycji.')
