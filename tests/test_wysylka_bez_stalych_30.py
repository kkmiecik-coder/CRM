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


def test_wlasny_kurier_ma_straznik_kolejnosci_odpowiedzi_serwera():
    """Regresja: spóźniona odpowiedź z serwera nadpisuje this.markup świeżym
    wynikiem starszym.

    `clearTimeout` w `scheduleCustomMarkup` anuluje TIMER, który jeszcze nie
    wystartował — NIE anuluje zapytania do `/calculator/api/shipping-markup`,
    które już poleciało. Scenariusz: użytkownik robi pauzę >=300 ms (startuje
    żądanie A dla kwoty X), wpisuje dalej i znów robi pauzę (startuje żądanie
    B dla kwoty Y). Jeśli odpowiedź A wróci PO odpowiedzi B, callback bez
    numeru żądania nadpisałby `this.markup` starszym wynikiem — panel
    pokazałby cenę niepasującą do pola formularza, a `validateCustomForm()`
    zbudowałby z niej `customCarrier`, który trafia do zapisanej wyceny
    klienta.

    Sama obecność identyfikatora `this.customMarkupSeq` gdziekolwiek w pliku
    niczego nie dowodzi — musi być przydzielany do lokalnej zmiennej PRZED
    żądaniem i porównywany z powrotem z `this.customMarkupSeq` PO `await`,
    inaczej strażnik nic nie strażuje.
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

    po_await = blok[dopasowanie_await.end():]
    assert re.search(re.escape(zmienna) + r'\s*!==\s*this\.customMarkupSeq', po_await), \
        'po await brakuje porównania przydzielonego numeru z this.customMarkupSeq — ' \
        'spóźniona odpowiedź nadpisze this.markup, mimo że nie jest już aktualna'
