# -*- coding: utf-8 -*-
"""Test trasy HTML zakładki Trakownia w panelu produkcji.

Testy w tym pliku sprawdzają wyłącznie to, co da się zweryfikować bez
przeglądarki: obecność/pozycję elementów w wyrenderowanym przez Jinja
tab_content.html (przez klienta testowego Flaska) oraz — tam, gdzie dany
fragment UI jest budowany w JS-ie (modale słownikowe) — obecność
odpowiednich fragmentów w źródle static/js/sawmill.js. To drugie nie
zastępuje testu przeglądarkowego, ale broni tego, że pola/etykiety/funkcje
faktycznie są w kodzie, a nie że zostały po cichu usunięte przy kolejnej
zmianie.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from tests.sawmill_fixtures import BASE, app, client  # noqa: F401

SAWMILL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'sawmill',
)


def _read_static(*parts):
    with open(os.path.join(SAWMILL_DIR, *parts), encoding='utf-8') as f:
        return f.read()


def test_zakladka_sie_renderuje(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Nowa dostawa' in html
    assert 'Różnica m³' in html
    # Symbol delty jest zakazany w całym interfejsie — nieczytelny dla biura.
    assert 'Δ' not in html


def test_zakladka_ma_wszystkie_przyciski_gorne(client):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    for etykieta in ('Nowa dostawa', 'Dostawcy', 'Gatunki', 'Eksport XLSX'):
        assert etykieta in html


def test_zakladka_ma_filtr_odchylen(client):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert 'only_deviation' in html or 'tylko odchylenia' in html.lower()


# ── Uwagi właściciela: układ paska górnego i filtrów (punkty 1–2) ───────────

def test_eksport_xlsx_w_wierszu_filtrow_a_nowa_dostawa_w_pasku_gornym(client):
    """Eksport XLSX stoi teraz w wierszu filtrów (przy prawej krawędzi),
    a "+ Nowa dostawa" zajęło zwolnione miejsce w pasku górnym (po prawej,
    Dostawcy/Gatunki zostają po lewej)."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    toolbar = soup.select_one('.sawmill-toolbar')
    filters = soup.select_one('.sawmill-filters')
    assert toolbar is not None
    assert filters is not None

    assert toolbar.select_one('#sawmill-btn-new-delivery') is not None
    assert toolbar.select_one('#sawmill-btn-suppliers') is not None
    assert toolbar.select_one('#sawmill-btn-species') is not None
    assert toolbar.select_one('#sawmill-btn-export') is None, (
        'Eksport XLSX powinien stać w wierszu filtrów, nie w górnym pasku')

    assert filters.select_one('#sawmill-btn-export') is not None
    assert filters.select_one('#sawmill-btn-new-delivery') is None, (
        '"+ Nowa dostawa" powinno być przeniesione z filtrów do paska górnego')


# ── Modal "Nowa dostawa" (punkty 3–7) ────────────────────────────────────────

def test_dodaj_kolejna_w_naglowku_sekcji_pozycji(client):
    """"+ dodaj kolejną" stoi w wierszu nagłówka "Pozycje dostawy"
    (space-between: nagłówek z lewej, przycisk z prawej), nie samotnie pod
    tabelą pozycji jak wcześniej."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    add_btn = soup.select_one('#sawmill-btn-add-item')
    assert add_btn is not None

    header_row = add_btn.find_parent('div', class_='d-flex')
    assert header_row is not None
    assert 'justify-content-between' in header_row.get('class', [])
    heading = header_row.find('h6')
    assert heading is not None and 'Pozycje dostawy' in heading.get_text()


def test_usun_pozycje_disabled_przy_jednej_pozycji(client):
    """Przycisk "Usuń pozycję" jest zawsze widoczny (nie ma go pod
    style="display:none") — przy jednej (jedynej, startowej) pozycji jest
    tylko disabled, żeby układ nie skakał przy dodawaniu/usuwaniu wierszy."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    rows = soup.select('#sawmill-delivery-items .sawmill-item-row')
    assert len(rows) == 1, 'Szablon startowo renderuje dokładnie jedną pozycję dostawy'

    remove_btn = rows[0].select_one('.sawmill-item-remove')
    assert remove_btn is not None
    assert remove_btn.has_attr('disabled')
    assert 'display:none' not in remove_btn.get('style', '').replace(' ', ''), (
        'Przycisk ma być disabled, a nie ukryty przez display:none')


def test_dostawca_select_bez_input_group(client):
    """Select dostawcy w modalu dostawy nie jest już w Bootstrapowym
    .input-group razem z przyciskiem "+ nowy" — w tej kombinacji renderował
    się (Safari) jako wąski, pozbawiony tekstu ~50px kikut zamiast selecta na
    pełną szerokość kolumny."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    supplier_select = soup.select_one('#sawmill-delivery-supplier')
    assert supplier_select is not None
    assert 'form-select' in supplier_select.get('class', [])
    assert supplier_select.find_parent('div', class_='input-group') is None, (
        'Select dostawcy nie może być dzieckiem .input-group')


def test_brak_zagniezdzonego_modalu_dostawcy(client):
    """"+ nowy" przy dostawcy nie otwiera już zagnieżdżonego modalu Bootstrapa
    (który renderował się pod przyciemnieniem tła własnego overlaya — jedynym
    wyjściem był Escape). Zamiast tego rozwija formularz inline wewnątrz
    modalu dostawy, więc w DOM jest tylko JEDEN modal na raz."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    inline_box = soup.select_one('#sawmill-inline-new-supplier')
    assert inline_box is not None
    assert inline_box.find_parent(id='sawmillDeliveryModal') is not None, (
        'Formularz inline musi być wewnątrz modalu dostawy, nie osobnym modalem')

    # sawmillDictModal (słowniki) dalej istnieje jako osobny modal — służy do
    # zarządzania CAŁYM słownikiem, nie tylko dodania jednej pozycji — ale
    # przycisk "+ nowy dostawca" w modalu dostawy nie może go już otwierać.
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'toggleInlineNewSupplier' in js
    assert (
        "'sawmill-btn-new-supplier').addEventListener('click', "
        "function () { openDictModal"
    ) not in js, '"+ nowy" nie może już otwierać zagnieżdżonego modalu słownika'


# ── Modale słownikowe: Dostawcy / Gatunki (punkty 8–9) ───────────────────────
#
# Treść tych modali jest budowana w JS-ie (DICT_FIELDS/renderDictBody w
# sawmill.js), nie w Jinja — testy sprawdzają więc bezpośrednio źródło JS.

def test_formularz_dostawcy_ma_wszystkie_pola_backendu(client):
    """POST/PATCH /suppliers przyjmuje osiem pól (patrz SUPPLIER_FIELDS w
    panel_api.py) — formularz musi je wszystkie wystawiać, inaczej zostają
    puste na zawsze, mimo że trafiają na protokół PDF idący do dostawcy."""
    js = _read_static('static', 'js', 'sawmill.js')
    for field in ('nip', 'address_street', 'address_zip', 'address_city',
                  'contact_person', 'phone', 'email', 'notes'):
        assert "field: '" + field + "'" in js, 'brakuje pola dostawcy w formularzu: ' + field
    for label in ('NIP', 'Ulica i numer', 'Kod pocztowy', 'Miasto',
                  'Osoba kontaktowa', 'Telefon', 'E-mail', 'Notatki'):
        assert label in js, 'brakuje polskiej etykiety pola: ' + label


def test_formularz_gatunku_ma_wszystkie_pola_backendu(client):
    """POST/PATCH /species przyjmuje name, short_code i sort_order."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert "field: 'short_code'" in js
    assert "field: 'sort_order'" in js
    assert 'Kolejność sortowania' in js


def test_slowniki_maja_edycje(client):
    """Edycja istniejącej pozycji (dostawcy i gatunku) przez PATCH — endpoint
    istniał od dawna, ale UI nie miało do niego żadnej drogi dojścia (dawało
    się tylko dodawać i miękko usuwać)."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'function editDictItem' in js
    assert 'function submitDictForm' in js
    assert "method: 'PATCH'" in js


def test_slownik_tlumaczy_miekkie_usuniecie_i_pozwala_przywrocic(client):
    """Kosz w modalach słownikowych usuwa miękko (is_active = 0) — historyczne
    zlecenia muszą dalej wskazywać na istniejący wiersz. UI musi to
    tłumaczyć użytkownikowi i dawać możliwość przywrócenia, bo sprawdzenie
    duplikatu nazwy po stronie backendu nie filtruje is_active (po
    dezaktywacji nie da się dodać nowej pozycji o tej samej nazwie)."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'dezaktyw' in js.lower()
    assert 'przywr' in js.lower()
    assert 'function restoreDictItem' in js
