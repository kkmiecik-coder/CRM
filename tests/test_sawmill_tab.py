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


def test_brak_dodawania_dostawcy_w_modalu_dostawy(client):
    """Formularz do dodania dostawcy został usunięty z modalu dostawy —
    dostawców dodaje się wyłącznie przez przycisk "Dostawcy" w pasku górnym
    (modal słownika). Select dostawcy w modalu dostawy zawiera wyłącznie listę
    istniejących dostawców."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    # Formularz inline nie istnieje
    inline_box = soup.select_one('#sawmill-inline-new-supplier')
    assert inline_box is None, (
        'Formularz inline do dodania dostawcy powinien być usunięty')

    # Przycisk "+ nowy dostawca" nie istnieje w modalu dostawy
    new_supplier_btn = soup.select_one('#sawmill-btn-new-supplier')
    assert new_supplier_btn is None, (
        'Przycisk "+ nowy dostawca" powinien być usunięty z modalu dostawy')

    # Select dostawcy istnieje i zawiera opcje
    supplier_select = soup.select_one('#sawmill-delivery-supplier')
    assert supplier_select is not None
    options = supplier_select.select('option')
    assert len(options) > 0, 'Select dostawcy musi zawierać co najmniej opcje placeholder'

    # W JS nie ma funkcji związanych z formularzem inline
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'toggleInlineNewSupplier' not in js, (
        'Funkcja toggleInlineNewSupplier powinna być usunięta')
    assert 'saveInlineSupplier' not in js, (
        'Funkcja saveInlineSupplier powinna być usunięta')


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


# ── Formatowanie — polski format kwot i objętości (trzecia tura poprawek) ─────

def test_funkcje_formatowania_polskiego_istnieja(client):
    """Formatowanie kwot i objętości na polski (spacja jako separator tysięcy,
    przecinek dziesiętny) — funkcje muszą być zdefiniowane w JS."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'function formatPolishNumber' in js, (
        'Brakuje funkcji formatPolishNumber do formatowania liczb na polski')
    assert 'function formatVolume' in js, (
        'Brakuje funkcji formatVolume do formatowania objętości (m³)')
    assert 'function formatCurrency' in js, (
        'Brakuje funkcji formatCurrency do formatowania kwot (zł)')
    # Formatowanie powinno używać Intl.NumberFormat z locale 'pl-PL'
    assert "'pl-PL'" in js, (
        "Brakuje Intl.NumberFormat z locale 'pl-PL' do polskiego formatowania")


def test_formatowanie_nie_dotyczy_wartosci_wysylanych_do_api(client):
    """Pola input[type="number"] i dane wysyłane do API (fetch body) muszą
    zawierać wartości maszynowe (z kropką), nie sformatowane na polski.
    Formatujesz wyłącznie wyświetlane wartości w DOM."""
    js = _read_static('static', 'js', 'sawmill.js')
    # Funkcja formatNum() i formatSigned() wciąż istnieją i zwracają .toFixed()
    assert 'function formatNum' in js
    assert 'function formatSigned' in js
    # W collectDeliveryItems() wartości z input.value nie są formatowane — tylko parsowane
    assert 'parseFloat(volumeInput.value)' in js, (
        'Wartości z pól input muszą być parsowane maszynowo')
    # Payload do POST/PATCH nie zawiera sformatowanych wartości
    assert 'JSON.stringify(payload)' in js, (
        'Payload do fetch musi być JSON.stringify, nie sformatowany')
    # updateItemPreview() używa formatCurrency() do wyświetlenia, ale nie do wysyłania
    assert 'formatCurrency' in js, (
        'updateItemPreview musi używać formatCurrency dla wyświetlenia')


def test_wiersz_pozycji_dostawy_rozprowadza_sie_na_cala_szerokosc(client):
    """Cztery główne kolumny pozycji dostawy (Gatunek, Dekl. obj., Liczba kłód,
    Cena/m³) mają rozprowadzać się równomiernie na dostępną szerokość,
    natomiast kolumna wartości i przycisk usunięcia zostają przy prawej
    krawędzi. Układ używa czystego Bootstrapa 5 (col, col-auto)."""
    template = _read_static('templates', 'sawmill', 'tab_content.html')

    # Cztery pola pozycji dostawy powinny mieć klasę 'col'
    # (bez numeru, żeby dzieliły szerokość równomiernie)
    col_count = template.count('<div class="col">')
    assert col_count >= 4, (
        f'Szablon powinien mieć przynajmniej 4 kolumny class="col" '
        f'dla czterech pól pozycji (gatunek, dekl. obj., liczba, cena). '
        f'Znaleziono: {col_count}')

    js = _read_static('static', 'js', 'sawmill.js')
    css = _read_static('static', 'css', 'sawmill.css')

    # Kolumny kwoty i kosza mają STAŁĄ szerokość, niezależną od treści — inaczej
    # wpisywanie kwoty przesuwa wszystkie pozostałe kolumny i pola uciekają
    # spod kursora. Szerokość nadaje klasa, nie atrybut style.
    for klasa in ('sawmill-item-value-col', 'sawmill-item-actions-col'):
        assert klasa in template, (
            f'Szablon musi używać klasy {klasa} do nadania stałej szerokości kolumnie.')
        assert klasa in js, (
            f'buildItemRow() musi używać klasy {klasa} — inaczej wiersze dodane '
            f'przyciskiem "+ dodaj kolejną" będą miały inny układ niż pierwszy.')
        assert f'.{klasa}' in css, (
            f'Klasa {klasa} musi mieć definicję szerokości w sawmill.css.')

    # Szerokość ma być zdefiniowana WYŁĄCZNIE w CSS. Atrybut style w wierszu
    # pozycji tworzyłby trzecie źródło prawdy (szablon + JS + arkusz), przy
    # którym zmiana wartości wymaga poprawki w trzech miejscach.
    assert 'style="width:' not in template, (
        'Szerokości kolumn nie definiuj atrybutem style w szablonie — użyj klasy z sawmill.css.')
    assert 'style=\\"width:' not in js and 'style="width:' not in js, (
        'Szerokości kolumn nie definiuj atrybutem style w buildItemRow() — użyj klasy z sawmill.css.')


# ── Modal edycji zlecenia i dostawy ──────────────────────────────────────────

def test_modal_edycji_istnieje_z_obydwoma_zestawami_pol(client):
    """Jeden modal edycji obejmuje pola zlecenia (PATCH /orders/<id>) i pola
    dostawy (PATCH /deliveries/<id>) — patrz panel_api.py."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')

    modal = soup.select_one('#sawmillEditModal')
    assert modal is not None, 'Brak modalu edycji zlecenia/dostawy'

    for field_id in ('sawmill-edit-species', 'sawmill-edit-declared-volume',
                      'sawmill-edit-logs-count', 'sawmill-edit-price',
                      'sawmill-edit-order-notes'):
        assert modal.select_one('#' + field_id) is not None, (
            'Brakuje pola zlecenia w modalu edycji: ' + field_id)

    for field_id in ('sawmill-edit-invoice-number', 'sawmill-edit-invoice-date',
                      'sawmill-edit-delivery-date', 'sawmill-edit-delivery-notes'):
        assert modal.select_one('#' + field_id) is not None, (
            'Brakuje pola dostawy w modalu edycji: ' + field_id)

    assert modal.select_one('#sawmill-btn-confirm-edit') is not None


def test_modal_edycji_rozdziela_wizualnie_zlecenie_i_dostawe(client):
    """Pola zlecenia i pola dostawy muszą stać w osobnych blokach — edycja
    dostawy dotyka rodzeństwa (wszystkich zleceń tej samej dostawy), więc
    użytkownik musi to widzieć PRZED zapisem (ostrzeżenie w
    #sawmill-edit-delivery-warning, wypełniane w JS)."""
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    soup = BeautifulSoup(html, 'html.parser')
    modal = soup.select_one('#sawmillEditModal')

    order_section = modal.select_one('.sawmill-edit-order-section')
    delivery_section = modal.select_one('.sawmill-edit-delivery-section')
    assert order_section is not None
    assert delivery_section is not None

    # Pola zlecenia stoją w sekcji zlecenia, nie w sekcji dostawy (i odwrotnie).
    assert order_section.select_one('#sawmill-edit-declared-volume') is not None
    assert delivery_section.select_one('#sawmill-edit-declared-volume') is None
    assert delivery_section.select_one('#sawmill-edit-invoice-number') is not None
    assert order_section.select_one('#sawmill-edit-invoice-number') is None

    assert delivery_section.select_one('#sawmill-edit-delivery-warning') is not None, (
        'Sekcja dostawy musi mieć element na ostrzeżenie, ile zleceń dotyczy zmiana')

    # Szerokość/wygląd sekcji dostawy definiowany klasą, nie atrybutem style
    # (jedno źródło prawdy dla wymiarów — patrz test dla wiersza pozycji dostawy).
    assert 'style="width:' not in str(delivery_section)


def test_css_definiuje_wyglad_sekcji_dostawy_w_edycji(client):
    css = _read_static('static', 'css', 'sawmill.css')
    assert '.sawmill-edit-delivery-section' in css


def test_js_ma_przycisk_edycji_zawsze_z_wylaczeniem_dla_rozliczonego(client):
    """Przycisk edycji jest w każdym wierszu — dla statusu 'settled' ma być
    disabled z title tłumaczącym dlaczego (PATCH na settled zwraca 409;
    nie wolno dać otworzyć modalu, wypełnić go i dostać błąd dopiero przy
    zapisie)."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'function editButtonHtml' in js
    assert "o.status === 'settled'" in js
    assert 'disabled' in js
    assert 'Sawmill.openEditModal' in js


def test_js_ma_walidacje_dodatniej_objetosci_w_edycji(client):
    """Deklarowana objętość musi być dodatnia — backend odrzuca 0 i wartości
    ujemne kodem 422 (dzielenie w compute_differences), walidacja po stronie
    przeglądarki daje komunikat przy polu bez podróży do serwera."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'function validateEditForm' in js
    assert 'volume <= 0' in js


def test_js_nie_wysyla_wyliczonej_wartosci_w_payloadzie_edycji(client):
    """declared_value liczy WYŁĄCZNIE serwer (declared_volume_m3 × price_per_m3
    przy każdym zapisie) — payload PATCH /orders/<id> nie może zawierać
    declared_value, backend by go i tak zignorował."""
    js = _read_static('static', 'js', 'sawmill.js')
    import re
    match = re.search(r'function collectEditOrderPayload\(\).*?\n    \}', js, re.DOTALL)
    assert match, 'Nie znaleziono collectEditOrderPayload() w sawmill.js'
    assert 'declared_value' not in match.group(0)


def test_js_obsluguje_czesciowy_zapis_edycji_bez_ciszy(client):
    """Modal wysyła dwa niezależne żądania (PATCH zlecenia, PATCH dostawy).
    Gdy pierwsze przejdzie, a drugie padnie, submitEdit() musi odświeżyć
    listę (żeby zapisana część była widoczna) i pokazać jawny komunikat —
    cichy stan częściowo zapisany jest zakazany przez brief."""
    js = _read_static('static', 'js', 'sawmill.js')
    assert 'function submitEdit' in js
    import re
    match = re.search(r'function submitEdit\(\).*?\n    \}', js, re.DOTALL)
    assert match, 'Nie znaleziono submitEdit() w sawmill.js'
    body = match.group(0)
    assert 'loadOrders' in body, (
        'Po udanym PATCH zlecenia i nieudanym PATCH dostawy lista musi się odświeżyć')
    assert 'editOrderSaved' in body


def test_szablon_i_buildItemRow_maju_identyczne_klasy_kolumn(client):
    """Szablon i funkcja buildItemRow() w sawmill.js muszą mieć identyczne
    klasy Bootstrap dla kolumn — inaczej pierwszy wiersz pozycji będzie
    wyglądał inaczej niż dodane później. To tanie zabezpieczenie przed
    rozjazdem tych dwóch miejsc."""
    template = _read_static('templates', 'sawmill', 'tab_content.html')
    js = _read_static('static', 'js', 'sawmill.js')

    # Ekstrahujemy strukturę klas z szablonu
    # (szukamy sekwencji <div class="col..."> w wierszu #sawmill-delivery-items)
    import re
    template_match = re.search(
        r'<div id="sawmill-delivery-items">.*?<div class="sawmill-item-row.*?</div>\s*</div>',
        template, re.DOTALL)
    assert template_match, 'Nie znaleziono szablonu wiersza pozycji w tab_content.html'

    template_cols = re.findall(r'<div class="([^"]+)">', template_match.group(0))
    # Filtrujemy do samych klas kolumn (pomijamy klasę 'sawmill-item-row row g-2...')
    template_col_classes = [c for c in template_cols if c.startswith('col')]

    # Ekstrahujemy strukturę klas z buildItemRow()
    build_row_match = re.search(
        r'function buildItemRow\(\).*?return row;',
        js, re.DOTALL)
    assert build_row_match, 'Nie znaleziono buildItemRow() w sawmill.js'

    build_col_classes = re.findall(r'class="([^"]+)">', build_row_match.group(0))
    # Filtrujemy do samych klas kolumn (pomijamy 'btn', 'form-label', itp.)
    build_col_classes = [c for c in build_col_classes if c.startswith('col')]

    assert template_col_classes == build_col_classes, (
        f'Klasy kolumn się nie zgadzają:\n'
        f'Szablon: {template_col_classes}\n'
        f'buildItemRow(): {build_col_classes}\n'
        f'Zarówno szablon jak i funkcja muszą mieć identyczną strukturę '
        f'(col, col, col, col, col-auto text-end, col-auto)')
