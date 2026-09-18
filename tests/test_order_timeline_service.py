"""Testy serwisu linii czasu produkcji (order_timeline_service)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services import order_timeline_service as ots


def _cfg(species='Dąb', technology='lity', wood_class='A/B'):
    return SimpleNamespace(species=species, technology=technology, wood_class=wood_class)


def _prod(status, cut_to_size=True, finish='lakierowane', edge=False,
          spid='25_05248_1', length=200, width=80, thickness=4, cfg=None):
    return SimpleNamespace(
        current_status=status,
        cut_to_size=cut_to_size,
        parsed_finish_type=finish,
        parsed_edge_processing=edge,
        short_product_id=spid,
        parsed_length_cm=length,
        parsed_width_cm=width,
        parsed_thickness_cm=thickness,
        configuration=cfg or _cfg(),
    )


# --- trasa produktu ---

def test_trasa_lakierowanego_z_krawedziami_ma_oba_stanowiska():
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='lakierowane', edge=True)
    assert ots.product_in_route(p, 'entry') is True
    assert ots.product_in_route(p, 'gluing') is True
    assert ots.product_in_route(p, 'formatting') is True
    assert ots.product_in_route(p, 'edges') is True
    assert ots.product_in_route(p, 'painting') is True
    assert ots.product_in_route(p, 'packaging') is True


def test_trasa_lakierowanego_bez_krawedzi_omija_krawedzie_ale_ma_lakiernie():
    """
    ZMIANA SEMANTYKI: dziś taki produkt MA kropkę „Wykańczanie". Po podziale
    nie ma prawa mieć kropki „Krawędzie" — nie ma tam czego robić.
    """
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='lakierowane', edge=False)
    assert ots.product_in_route(p, 'formatting') is True
    assert ots.product_in_route(p, 'edges') is False
    assert ots.product_in_route(p, 'painting') is True


def test_trasa_bez_dociecia_pomija_formatowanie_krawedzie_i_lakiernie():
    p = _prod('czeka_na_wyciecie', cut_to_size=False, finish='surowe')
    assert ots.product_in_route(p, 'formatting') is False
    assert ots.product_in_route(p, 'edges') is False
    assert ots.product_in_route(p, 'painting') is False
    assert ots.product_in_route(p, 'packaging') is True


def test_trasa_surowego_bez_krawedzi_omija_krawedzie_i_lakiernie():
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='surowe', edge=False)
    assert ots.product_in_route(p, 'formatting') is True
    assert ots.product_in_route(p, 'edges') is False
    assert ots.product_in_route(p, 'painting') is False


def test_trasa_surowego_z_krawedziami_ma_krawedzie_bez_lakierni():
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='surowe', edge=True)
    assert ots.product_in_route(p, 'edges') is True
    assert ots.product_in_route(p, 'painting') is False


def test_trasa_olejowanego_z_krawedziami_ale_bez_dociecia_nie_ma_zadnego_z_nich():
    """Skrót cut_to_size=False wygrywa ze wszystkim — tak jak w complete_task."""
    p = _prod('czeka_na_wyciecie', cut_to_size=False, finish='olejowane', edge=True)
    assert ots.product_in_route(p, 'edges') is False
    assert ots.product_in_route(p, 'painting') is False


def test_trasa_nie_zna_juz_kodu_finishing():
    """Jawny strażnik zamiast dzisiejszych asercji, które po rename stałyby się
    trywialnie prawdziwe (sekcja 10B specyfikacji)."""
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='lakierowane', edge=True)
    assert ots.product_in_route(p, 'finishing') is False
    assert 'finishing' not in ots.STATION_AT_STATUSES
    assert 'finishing' not in {st['key'] for st in ots.TIMELINE_STATIONS}


# --- kropki linii czasu po podziale wykańczania ---

def test_kropka_krawedzi_zastapila_wykanczanie():
    klucze = [st['key'] for st in ots.TIMELINE_STATIONS]
    assert klucze == ['entry', 'gluing', 'formatting', 'edges', 'painting', 'packaging']
    nazwy = {st['key']: st['name'] for st in ots.TIMELINE_STATIONS}
    assert nazwy['edges'] == 'Krawędzie'
    assert nazwy['painting'] == 'Lakiernia'


def test_klucze_obu_map_kropek_sa_zgodne():
    """
    _product_state (:98) indeksuje STATION_AT_STATUSES BEZ .get() — rozjazd
    kluczy daje KeyError i wywraca modal wyceny, a nie ciche pominięcie kropki.
    """
    assert set(ots.STATION_AT_STATUSES) == {st['key'] for st in ots.TIMELINE_STATIONS}


def test_kropka_krawedzi_lapie_status_kolejki():
    assert ots.STATION_AT_STATUSES['edges'] == {'czeka_na_krawedzie'}
    assert ots.STATION_STAGE['edges'] == 3


# --- porządek i etykiety statusów po podziale wykańczania ---

def test_krawedzie_stoja_w_porzadku_statusow_przed_lakiernia():
    assert (ots.STATUS_ORDINAL['czeka_na_formatowanie']
            < ots.STATUS_ORDINAL['czeka_na_krawedzie']
            < ots.STATUS_ORDINAL['czeka_na_lakiernie']
            < ots.STATUS_ORDINAL['czeka_na_logistyke'])
    assert 'czeka_na_wykanczanie' not in ots.STATUS_ORDINAL


def test_status_krawedzi_ma_nazwe_i_klase_badge():
    badge = ots.order_status_badge([_prod('czeka_na_krawedzie')])
    assert badge['label'] == 'Czeka na krawędzie'
    # Nazwa klasy CSS jest HISTORYCZNA i celowo nietknięta (decyzja P4):
    # stanowisko nazywa się dziś Krawędzie, ale selektor dalej brzmi
    # 'badge-finishing'. Tu pilnujemy wyłącznie tego, że nowy KLUCZ statusu
    # w ogóle trafia w mapę i nie spada na fallback 'badge-completed'
    # (order_timeline_service.py:178).
    assert badge['badge_class'] == 'badge-finishing'


# --- kolor kropki ---

def test_color_gray_when_none_arrived():
    products = [_prod('czeka_na_wyciecie'), _prod('czeka_na_wyciecie')]
    assert ots.station_color('edges', products) == 'gray'


def test_color_green_when_all_left():
    products = [_prod('spakowane'), _prod('spakowane')]
    assert ots.station_color('gluing', products) == 'green'


def test_color_yellow_when_one_currently_there():
    products = [_prod('czeka_na_sklejanie'), _prod('spakowane')]
    assert ots.station_color('gluing', products) == 'yellow'


def test_color_yellow_when_mixed_left_and_before_none_at():
    products = [_prod('czeka_na_formatowanie'), _prod('czeka_na_wyciecie')]
    assert ots.station_color('gluing', products) == 'yellow'


def test_color_none_hidden_when_no_product_routed():
    products = [_prod('czeka_na_wyciecie', cut_to_size=True, finish='surowe', edge=False)]
    routed = [p for p in products if ots.product_in_route(p, 'edges')]
    assert ots.station_color('edges', routed) is None


# --- payload + status zamówienia ---

def test_build_payload_hides_empty_stations_and_marks_active():
    products = [
        _prod('czeka_na_sklejanie', cut_to_size=False, finish='surowe', spid='25_1_1'),
    ]
    stations = ots.build_timeline_payload(products)
    keys = [s['code'] for s in stations]
    assert 'formatting' not in keys and 'edges' not in keys and 'painting' not in keys
    gluing = next(s for s in stations if s['code'] == 'gluing')
    assert gluing['color'] == 'yellow'
    assert gluing['active'] is True
    assert gluing['products_here'][0]['short_product_id'] == '25_1_1'


def test_products_here_only_on_active_station():
    products = [_prod('czeka_na_sklejanie', spid='25_1_1')]
    stations = ots.build_timeline_payload(products)
    entry = next(s for s in stations if s['code'] == 'entry')
    assert entry['active'] is False
    assert entry['products_here'] == []


def test_order_status_single():
    products = [_prod('czeka_na_sklejanie'), _prod('czeka_na_sklejanie')]
    badge = ots.order_status_badge(products)
    assert badge['label'] == 'Czeka na sklejanie'
    assert badge['badge_class'] == 'badge-gluing'


def test_order_status_mixed():
    products = [_prod('spakowane'), _prod('czeka_na_sklejanie'), _prod('czeka_na_wyciecie')]
    badge = ots.order_status_badge(products)
    assert badge['label'] == 'Różne (1/3)'
    assert badge['badge_class'] == 'badge-mixed'


def test_anulowane_excluded_from_timeline():
    products = [_prod('anulowane'), _prod('czeka_na_sklejanie', spid='25_1_2')]
    stations = ots.build_timeline_payload(products)
    gluing = next(s for s in stations if s['code'] == 'gluing')
    assert [p['short_product_id'] for p in gluing['products_here']] == ['25_1_2']


def test_format_dimension_polish_comma():
    assert ots.format_dimension(2.5) == '2,5'
    assert ots.format_dimension(180) == '180'
    assert ots.format_dimension(None) == '-'


def test_order_status_counts_cancelled_to_mirror_admin():
    # świadoma asymetria: badge liczy anulowane (jak panel admina), timeline ich nie liczy
    products = [_prod('spakowane'), _prod('anulowane')]
    badge = ots.order_status_badge(products)
    assert badge['label'] == 'Różne (1/2)'
    assert badge['badge_class'] == 'badge-mixed'
