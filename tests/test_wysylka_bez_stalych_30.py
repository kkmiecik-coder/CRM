# -*- coding: utf-8 -*-
"""
Strażnicy: narzut na wysyłkę nie wraca do kodu.

Cały sens zmiany z 15.09.2026 polega na tym, że procent narzutu istnieje
WYŁĄCZNIE w bazie i w shipping_pricing.py. Te testy padają, gdy ktoś wpisze
go z powrotem do JS albo do szablonu — czyli dokładnie wtedy, gdy kalkulator
i bot zaczynają się rozjeżdżać.

Konwencja sprawdzeń na źródle jak w tests/test_checkout_js.py.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JS_CORE = os.path.join(KORZEN, 'modules', 'calculator', 'static', 'js',
                       'calculator-core.js')
JS_DELIVERY = os.path.join(KORZEN, 'modules', 'calculator', 'static', 'js',
                           'calculator-delivery.js')
SZABLON_MODALA = os.path.join(KORZEN, 'modules', 'calculator', 'templates',
                              'delivery_modal.html')
SZABLON_USTAWIEN = os.path.join(KORZEN, 'modules', 'settings', 'templates',
                                'settings_index.html')
ROUTERY_USTAWIEN = os.path.join(KORZEN, 'modules', 'settings', 'routers.py')


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def test_core_nie_ma_juz_mnoznika_pakowania():
    assert 'shippingPackingMultiplier' not in _zrodlo(JS_CORE), \
        'Mnożnik wrócił do calculator-core.js — narzut ma żyć tylko w bazie.'


def test_delivery_nie_ma_juz_wlasnej_marzy():
    zrodlo = _zrodlo(JS_DELIVERY)
    assert 'MARGIN_RATE' not in zrodlo, \
        'MARGIN_RATE wrócił do calculator-delivery.js.'
    assert 'shippingPackingMultiplier' not in zrodlo


def test_delivery_pyta_backend_o_przeliczenie():
    assert '/calculator/api/shipping-markup' in _zrodlo(JS_DELIVERY), \
        'Modal dostawy przestał pytać backend o ceny końcowe.'


def test_szablon_modala_nie_ma_wpisanego_procentu():
    zrodlo = _zrodlo(SZABLON_MODALA)
    assert not re.search(r'\+\s*30\s*%', zrodlo), \
        'W szablonie modala znów siedzi wpisane na sztywno "+30%".'


def test_delivery_nadal_zachowuje_cache_surowych_cen():
    """Cache MUSI trzymać ceny surowe — inaczej zmiana ustawień nie zadziała
    przez dobę na przeglądarce z ciepłym cache'em."""
    assert 'SHIPPING_CACHE_KEY' in _zrodlo(JS_DELIVERY)


def _metoda(zrodlo, naglowek):
    """Ciało metody klasy (wcięcie 4 spacje) o podanym nagłówku.

    Analogicznie do `_blok()` z tests/test_checkout_js.py, tylko dla metody
    wewnątrz klasy: tam funkcje top-level kończą się `\n}\n`, tu klamra
    zamykająca stoi w wcięciu metody (4 spacje), więc szukamy `\n    }\n`.
    """
    poczatek = zrodlo.index(naglowek)
    reszta = zrodlo[poczatek:]
    koniec = reszta.index('\n    }\n')
    return reszta[:koniec]


def _blok_catch(blok_metody, dopasowanie_catch):
    """Ciało `catch (error) { ... }` wewnątrz już wyodrębnionego bloku metody.

    Ten `catch` siedzi trzy poziomy głębiej niż nagłówek metody (metoda ->
    setTimeout(async () => {...}) -> try/catch), więc jego klamra domykająca
    stoi na wcięciu 12 spacji — szukamy `\n            }\n`, analogicznie do
    `_metoda()` powyżej, tylko na innym poziomie zagnieżdżenia.
    """
    reszta = blok_metody[dopasowanie_catch.end():]
    koniec = reszta.index('\n            }\n')
    return reszta[:koniec]


def _funkcja_top(zrodlo, naglowek):
    """Ciało funkcji zadeklarowanej na najwyższym poziomie pliku (wcięcie 0).

    Jak `_blok()` z tests/test_checkout_js.py: klamra zamykająca stoi bez
    wcięcia, więc szukamy `\n}\n` — inaczej niż `_metoda()` powyżej, która
    szuka klamry wciętej o 4 spacje (metoda wewnątrz klasy).
    """
    poczatek = zrodlo.index(naglowek)
    reszta = zrodlo[poczatek:]
    koniec = reszta.index('\n}\n')
    return reszta[:koniec]


def test_wlasny_kurier_ma_straznik_kolejnosci_odpowiedzi_serwera():
    """Regresja: spóźniona odpowiedź z serwera nadpisuje this.markup świeżym
    wynikiem starszym — sprawdzane OSOBNO w gałęzi sukcesu (try) i błędu
    (catch), bo to dwa niezależne strażniki i usunięcie dowolnego z nich ma
    wywalić ten test.

    `clearTimeout` w `scheduleCustomMarkup` anuluje TIMER, który jeszcze nie
    wystartował — NIE anuluje zapytania do `/calculator/api/shipping-markup`,
    które już poleciało. Scenariusz: użytkownik robi pauzę >=300 ms (startuje
    żądanie A dla kwoty X), wpisuje dalej i znów robi pauzę (startuje żądanie
    B dla kwoty Y). Jeśli odpowiedź A wróci PO odpowiedzi B, callback bez
    numeru żądania nadpisałby `this.markup` starszym wynikiem — panel
    pokazałby cenę niepasującą do pola formularza, a `validateCustomForm()`
    zbudowałby z niej `customCarrier`, który trafia do zapisanej wyceny
    klienta. Ten sam mechanizm psuje sprawę i wtedy, gdy to spóźnione
    zapytanie A skończy się BŁĘDEM: bez strażnika w gałęzi catch, jego
    `this.markup = null` wyzeruje cenę ustawioną już przez poprawną,
    nowszą odpowiedź B.

    Sama obecność identyfikatora `this.customMarkupSeq` gdziekolwiek w pliku
    niczego nie dowodzi — musi być przydzielany do lokalnej zmiennej PRZED
    żądaniem i porównywany z powrotem z `this.customMarkupSeq` PO `await`, W
    OBU gałęziach try/catch z osobna. Szukanie samego wystąpienia „gdziekolwiek
    po await" (jak w poprzedniej wersji tego testu) tego nie wychwytuje: guard
    obecny tylko w try (albo tylko w catch) i tak trafia w ten wspólny zakres,
    więc usunięcie jednego z nich zostawiało test zielonym.
    """
    zrodlo = _zrodlo(JS_DELIVERY)

    konstruktor = _metoda(zrodlo, 'constructor() {')
    assert 'this.customMarkupSeq = 0;' in konstruktor, \
        'DeliveryModal nie inicjuje licznika this.customMarkupSeq w konstruktorze'

    blok = _metoda(zrodlo, 'scheduleCustomMarkup(bruttoAmount) {')

    przydzial = re.search(r'(\w+)\s*=\s*\+\+this\.customMarkupSeq', blok)
    assert przydzial, \
        'scheduleCustomMarkup nie przydziela numeru żądania z this.customMarkupSeq'
    zmienna = przydzial.group(1)

    dopasowanie_await = re.search(r'await fetchShippingMarkup\(', blok)
    assert dopasowanie_await, \
        'zmieniło się wywołanie fetchShippingMarkup w scheduleCustomMarkup'

    dopasowanie_catch = re.search(r'catch \(error\) \{', blok)
    assert dopasowanie_catch, \
        'zmieniła się struktura try/catch w scheduleCustomMarkup'
    assert dopasowanie_await.end() < dopasowanie_catch.start(), \
        'await fetchShippingMarkup powinien być w bloku try, przed catch'

    wzorzec_straznika = re.escape(zmienna) + r'\s*!==\s*this\.customMarkupSeq'

    blok_try = blok[dopasowanie_await.end():dopasowanie_catch.start()]
    assert re.search(wzorzec_straznika, blok_try), \
        'w gałęzi try (po await, przed catch) brakuje porównania przydzielonego ' \
        'numeru z this.customMarkupSeq — spóźniona UDANA odpowiedź nadpisze ' \
        'this.markup, mimo że nie jest już aktualna'

    blok_catch = _blok_catch(blok, dopasowanie_catch)
    assert re.search(wzorzec_straznika, blok_catch), \
        'w gałęzi catch brakuje porównania przydzielonego numeru z ' \
        'this.customMarkupSeq — spóźniony BŁĄD starszego żądania wyzeruje ' \
        'this.markup, nadpisując poprawną cenę ustawioną już przez nowszą odpowiedź'


def test_show_i_showcustomform_uniewazniaja_oczekujace_zadanie():
    """Regresja (item 2 przeglądu): show() i showCustomForm() zerują
    this.markup przy każdym resecie stanu modala, ale strażnik z
    scheduleCustomMarkup broni tylko odpowiedzi już wysłanego żądania —
    nie samego resetu. Scenariusz: użytkownik otwiera formularz własnego
    kuriera, wpisuje kwotę (startuje żądanie), w ciągu 300 ms wraca do
    listy albo otwiera formularz ponownie. Bez anulowania timera i
    podbicia this.customMarkupSeq w OBU miejscach, spóźniona odpowiedź
    wciąż przejdzie test `numerZadania !== this.customMarkupSeq` w
    scheduleCustomMarkup i wpisze cudzy wynik do świeżo zresetowanego
    stanu."""
    zrodlo = _zrodlo(JS_DELIVERY)

    for naglowek in ('show(quotes, markupInfo = null) {', 'showCustomForm() {'):
        blok = _metoda(zrodlo, naglowek)
        assert 'clearTimeout(this.customMarkupTimer)' in blok, \
            '%s nie anuluje oczekującego timera scheduleCustomMarkup' % naglowek
        assert '++this.customMarkupSeq' in blok, \
            '%s nie podbija this.customMarkupSeq — spóźniona odpowiedź nadal ' \
            'zostanie uznana za aktualną' % naglowek


def test_podzakladka_wysylki_jest_podpieta_w_ustawieniach():
    """Literówka w url_for wywala CAŁĄ stronę Ustawień na 500, nie tylko tę
    podzakładkę — stąd osobny strażnik na parę szablon/router."""
    szablon = _zrodlo(SZABLON_USTAWIEN)
    assert "url_for('settings.calculator_shipping')" in szablon
    assert 'Wyliczanie wysyłki' in szablon
    assert "calculator_subtab == 'shipping'" in szablon


def test_router_ustawien_ma_trase_wysylki():
    zrodlo = _zrodlo(ROUTERY_USTAWIEN)
    assert "@settings_bp.route('/calculator/shipping')" in zrodlo
    assert 'def calculator_shipping(' in zrodlo


def test_formatpercent_nie_liczy_juz_procentu_sam():
    """Regresja (item 1 przeglądu): formatPercent liczył własną wersję tekstu
    (toFixed + zamiana kropki na przecinek) obok _procent() w
    shipping_pricing.py — przy remisie zaokrąglenia potrafiły się rozjechać
    (Python zaokrągla bankiersko, JS przez toFixed zawsze od zera). Jedynym
    źródłem tekstu ma być teraz backend, przez config.percent_label."""
    blok = _metoda(_zrodlo(JS_DELIVERY), 'formatPercent() {')
    assert 'toFixed' not in blok, \
        'formatPercent znów samodzielnie formatuje liczbę procentu'
    assert 'percent_label' in blok, \
        'formatPercent nie czyta percent_label z konfiguracji przysłanej przez backend'


def test_calculatedelivery_filtruje_oferty_z_cieplego_cache():
    """Regresja (item 2 przeglądu): cache wysyłki w localStorage trzyma
    surowe odpowiedzi GlobKuriera do 24h (SHIPPING_CACHE_TTL). Serwer
    odrzuca teraz ofertę bez liczbowej ceny u źródła (serializuj_oferty w
    shipping_service.py), ale ten filtr działa tylko przy świeżym zapytaniu
    do GlobKuriera — oferta zapisana w cache PRZED tą poprawką (albo cache
    ustawiony inną ścieżką) wciąż może go ominąć, więc modal musi filtrować
    też listę odczytaną z cache'u, nie tylko świeżo pobraną."""
    blok = _funkcja_top(_zrodlo(JS_DELIVERY), 'async function calculateDelivery() {')

    dopasowanie_filter = re.search(r'quotesList\s*=\s*quotesList\.filter\(', blok)
    assert dopasowanie_filter, \
        'calculateDelivery nie filtruje już listy ofert (cache lub świeży fetch) ' \
        'z ofert bez liczbowej ceny przed wysłaniem ich do przeliczenia'

    dopasowanie_pusta = re.search(r'quotesList\.length\s*===\s*0', blok)
    assert dopasowanie_pusta, 'zmieniła się struktura sprawdzenia pustej listy ofert'
    assert dopasowanie_filter.end() < dopasowanie_pusta.start(), \
        'filtr musi zadziałać PRZED sprawdzeniem pustej listy — inaczej komunikat ' \
        '"Brak dostępnych metod dostawy" nie pojawi się, gdy filtrowanie ją opróżniło'

    dopasowanie_markup = re.search(r'fetchShippingMarkup\(quotesList', blok)
    assert dopasowanie_markup, 'zmieniło się wywołanie fetchShippingMarkup w calculateDelivery'
    assert dopasowanie_filter.end() < dopasowanie_markup.start(), \
        'filtr musi zadziałać PRZED wysłaniem cen do przeliczenia'
