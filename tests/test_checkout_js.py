# -*- coding: utf-8 -*-
"""
Skrypty ścieżki zamawiania — sprawdzenia strukturalne na źródle.

W tym repozytorium nie ma runtime'u JS (obraz testowy jest bez node'a), więc
te testy świadomie NIE deklarują zachowania w przeglądarce. Sprawdzają
własności, które da się odczytać ze źródła, a których utrata już raz kosztowała
klienta fałszywy komunikat — konwencja tests/test_sawmill_ui_actions.py.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_MODAL = os.path.join(KORZEN, 'modules', 'quotes', 'static', 'js',
                        'client_accept_modal.js')


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def _blok(zrodlo, naglowek):
    """Ciało funkcji zadeklarowanej na najwyższym poziomie pliku."""
    poczatek = zrodlo.index(naglowek)
    reszta = zrodlo[poczatek:]
    koniec = reszta.index('\n}\n')
    return reszta[:koniec]


class TestBrakPowtorkiGdyZamowienieIstnieje:
    """Odpowiedź `zamowienie_utworzone` = zamówienie JEST. Przycisk nie wraca."""

    def test_flaga_sprawdzana_przed_dopuszczeniem_powtorki(self):
        blok = _blok(_zrodlo(JS_MODAL), 'async function handleFinalSubmit()')

        assert 'zamowienie_utworzone' in blok, \
            'handleFinalSubmit ignoruje informację, że zamówienie powstało'
        # Powtórka jest odblokowywana dokładnie w jednym miejscu i musi stać
        # PO sprawdzeniu obu flag — inaczej klient zamówi drugi raz.
        assert blok.count('mozliwaPowtorka = true') == 1
        assert blok.index('zamowienie_utworzone') < blok.index('mozliwaPowtorka = true')
        assert blok.index('result.niepewne') < blok.index('mozliwaPowtorka = true')

    def test_ekran_koncowy_mowi_ze_zamowienie_zostalo_zlozone(self):
        zrodlo = _zrodlo(JS_MODAL)
        blok = _blok(zrodlo, 'function pokazZamowienieBezZapisu(')

        # Nagłówek „Nie wiemy, czy zamówienie zostało złożone" byłby tu
        # kłamstwem — wiemy, że zostało.
        assert 'Nie wiemy' not in blok
        assert 'Zamówienie zostało złożone' in blok
        # Ekran ma odbierać prawo do powtórki — robi to wspólna funkcja.
        assert 'pokazEkranBezPowtorki(' in blok
        wspolny = _blok(zrodlo, 'function pokazEkranBezPowtorki(')
        assert 'zablokujPrzyciskiZamawiania()' in wspolny

    def test_ekran_niepewnosci_dalej_nie_rozstrzyga(self):
        # Kontrola negatywna: stary stan „nie wiemy" nie może przejąć nowego
        # komunikatu ani odwrotnie.
        blok = _blok(_zrodlo(JS_MODAL), 'function pokazNiepewnosc(')
        assert 'Nie wiemy, czy zamówienie zostało złożone' in blok


JS_WYCENA = os.path.join(KORZEN, 'modules', 'quotes', 'static', 'js',
                         'client_quote.js')


def _obiekt(zrodlo, nazwa):
    """Ciało literału obiektu `const <nazwa> = {` ... `\\n};`."""
    poczatek = zrodlo.index('const %s = {' % nazwa)
    reszta = zrodlo[poczatek:]
    koniec = reszta.index('\n};')
    return reszta[:koniec]


def _metody(cialo_obiektu):
    """Nazwy metod zadeklarowanych wprost w literale obiektu (wcięcie 4 spacje)."""
    return set(re.findall(r'^    (?:async )?(\w+)\s*\(', cialo_obiektu, re.MULTILINE))


class TestWywolaniaThisWObiekcieInit:
    """Regresja: `this.syncAcceptButtons()` w `init.disableInteractions()`.

    Metoda żyje na obiekcie `render`, więc `this` w `init` nie miało jej skąd
    wziąć. TypeError leciał do `catch` w `loadQuoteData` i KAŻDA zaakceptowana
    wycena witała klienta czerwonym „Nie udało się wczytać wyceny. Odśwież
    stronę." — w chwili, w której klient ma wydać pieniądze.
    """

    def test_kazde_this_w_init_wskazuje_na_metode_init(self):
        zrodlo = _zrodlo(JS_WYCENA)
        init = _obiekt(zrodlo, 'init')
        zadeklarowane = _metody(init)
        assert 'loadQuoteData' in zadeklarowane, 'zmieniła się struktura pliku'

        wolane = set(re.findall(r'this\.(\w+)\s*\(', init))
        brakujace = sorted(wolane - zadeklarowane)

        assert not brakujace, \
            'init woła przez this metody, których nie ma na init: %s' % brakujace

    def test_disableinteractions_korzysta_z_render(self):
        init = _obiekt(_zrodlo(JS_WYCENA), 'init')
        # Kotwica na DEFINICJI metody (wcięcie 4 spacje), nie na jej wywołaniu.
        blok = init[init.index('\n    disableInteractions() {'):]
        blok = blok[:blok.index('\n    }')]

        assert 'render.syncAcceptButtons()' in blok
        assert 'this.syncAcceptButtons' not in blok

    def test_syncacceptbuttons_mieszka_na_render(self):
        # Kontrola pozytywna dla obu testów wyżej: gdyby metoda przeniosła się
        # na init, poprawka „render." stałaby się błędna.
        zrodlo = _zrodlo(JS_WYCENA)
        assert 'syncAcceptButtons' in _metody(_obiekt(zrodlo, 'render'))


JS_PANEL = os.path.join(KORZEN, 'modules', 'baselinker', 'static', 'js',
                        'baselinker.js')


class TestEkranPrzetwarzania:
    """Trzeci stan bez powtórki: inne żądanie właśnie składa to zamówienie."""

    def test_flaga_w_toku_sprawdzana_przed_dopuszczeniem_powtorki(self):
        blok = _blok(_zrodlo(JS_MODAL), 'async function handleFinalSubmit()')

        assert 'result.w_toku' in blok, \
            'handleFinalSubmit wpuszcza powtórkę na próbie, która trwa'
        assert blok.index('result.w_toku') < blok.index('mozliwaPowtorka = true')

    def test_ekran_przetwarzania_nie_straszy_niepewnoscia(self):
        zrodlo = _zrodlo(JS_MODAL)
        blok = _blok(zrodlo, 'function pokazPrzetwarzanie(')

        # Zamówienie jest w trakcie składania — „nie wiemy" byłoby tu
        # niepotrzebnym straszeniem, ale powtórki dalej być nie może.
        assert 'Nie wiemy' not in blok
        assert 'przetwarzane' in blok
        assert 'pokazEkranBezPowtorki(' in blok


class TestWstepneZaznaczenieOdbioru:
    """Formularz nie może przeczyć danym dostawy zapisanym na kliencie.

    Serwer odrzuca sprzeczność („kurier" w formularzu przy znaczniku odbioru
    na kliencie), bo nie wolno mu jej rozstrzygnąć za klienta. Modal musi więc
    wracać do klienta w tym stanie, w jakim jego dane naprawdę są.
    """

    def test_obie_sciezki_autouzupelniania_ustawiaja_odbior(self):
        zrodlo = _zrodlo(JS_MODAL)

        assert 'function ustawOdbiorZDanychKlienta(' in zrodlo
        for funkcja in ('function fillFormWithExistingData(',
                        'function fillFormWithClientData('):
            blok = _blok(zrodlo, funkcja)
            assert 'ustawOdbiorZDanychKlienta(' in blok, \
                '%s nie zaznacza odbioru osobistego z danych klienta' % funkcja

    def test_znacznik_rozpoznawany_tak_samo_jak_na_serwerze(self):
        blok = _blok(_zrodlo(JS_MODAL), 'function adresToOdbiorOsobisty(')

        # Ta sama para wariantów co checkout_config._ZNACZNIKI_ODBIORU.
        assert 'odbiór osobisty' in blok
        assert 'odbior osobisty' in blok


class TestPanelNieNazywaZamowieniaBledem:
    """N4 po stronie panelu: komunikat serwera rozstrzyga, czy zamówienie jest."""

    def test_komunikat_serwera_nie_jest_poprzedzany_slowem_blad(self):
        zrodlo = _zrodlo(JS_PANEL)
        poczatek = zrodlo.index("console.error('[Baselinker] ❌ Błąd tworzenia zamówienia:'")
        blok = zrodlo[poczatek:poczatek + 1200]

        assert 'Błąd podczas tworzenia zamówienia' not in blok, \
            'handlowiec czyta „błąd" i klika drugi raz — przy zamówieniu, ' \
            'które JUŻ istnieje, to drugie realne zamówienie'
        assert 'zamowienie_utworzone' in blok

    def test_odmowa_z_wyjsciem_proponuje_odpiecie(self):
        zrodlo = _zrodlo(JS_PANEL)
        poczatek = zrodlo.index("console.error('[Baselinker] ❌ Błąd tworzenia zamówienia:'")
        blok = zrodlo[poczatek:poczatek + 1200]

        assert 'mozna_odpiac' in blok
        assert 'zaproponujOdpiecieZamowienia(' in blok

    def test_odpiecie_wymaga_potwierdzenia(self):
        # Kasuje jedyny ślad wiążący wycenę z realnym zamówieniem — nie może
        # wykonać się jednym przypadkowym kliknięciem.
        zrodlo = _zrodlo(JS_PANEL)
        poczatek = zrodlo.index('async zaproponujOdpiecieZamowienia(')
        blok = zrodlo[poczatek:zrodlo.index('\n    }', poczatek)]

        assert 'window.confirm(' in blok
        assert 'detach-order' in blok
