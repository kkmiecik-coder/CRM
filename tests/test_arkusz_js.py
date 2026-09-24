# -*- coding: utf-8 -*-
"""Siatka arkusza po stronie przegladarki.

W repozytorium NIE MA testu uruchamiajacego JavaScript — obraz testowy jest
bez node'a. Sprawdzamy wiec strukture zrodla: konwencja tests/test_checkout_js.py
i tests/test_reports_kolory_frontu.py. Ze siatka naprawde sie scala, przewija
i chodzi klawiatura, dowodzi wylacznie krok „obejrzyj w przegladarce"
z tego zadania.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_ARKUSZA = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'arkusz.js')


def zrodlo():
    with open(JS_ARKUSZA, encoding='utf-8') as plik:
        return plik.read()


def test_js_pobiera_dane_z_adresu_podanego_w_data_atrybucie():
    js = zrodlo()
    assert 'dataset.urlDane' in js
    assert 'fetch(' in js
    # Adres NIE jest sklejany na sztywno — inaczej zmiana prefiksu blueprintu
    # zepsulaby arkusz po cichu.
    assert "'/reports/api/arkusz/dane'" not in js


def test_js_nie_formatuje_ani_nie_liczy_wartosci_biznesowych():
    # Wszystkie liczby przychodza z serwera jako gotowy tekst.
    js = zrodlo()
    assert 'toFixed' not in js
    assert 'Intl.NumberFormat' not in js
    assert 'toLocaleString' not in js


def test_js_tworzy_jedno_tbody_na_zamowienie():
    js = zrodlo()
    assert "createElement('tbody')" in js
    assert 'ark-zamowienie' in js


def test_js_ustawia_rowspan_z_liczby_wierszy_a_nie_liczy_jej_sam():
    js = zrodlo()
    assert 'rowSpan' in js
    assert 'zamowienie.wierszy' in js


def test_js_pomija_rowspan_dla_zamowienia_jednopozycyjnego():
    # Makieta: zamowienie 50839911 ma jedna pozycje i nie ma atrybutu
    # rowspan wcale (nie rowspan="1").
    assert 'wierszy > 1' in zrodlo()


def test_js_oznacza_komorki_poziomu_zamowienia_klasa_ord():
    assert "'ord'" in zrodlo()


@pytest.mark.parametrize('klasa', ['calc', 'prod', 'pusta'])
def test_js_nadaje_klasy_rodzajow_komorek(klasa):
    assert f"'{klasa}'" in zrodlo()


def test_js_uzywa_monospace_i_wyrownania_dla_kolumn_liczbowych():
    js = zrodlo()
    assert 'kolumna.liczbowa' in js
    assert "'m'" in js
    assert "'num'" in js


def test_js_zamraza_dwie_pierwsze_kolumny():
    js = zrodlo()
    assert 'zamrozona-1' in js
    assert 'zamrozona-2' in js
    # Przesuniecie drugiej zamrozonej kolumny to SZEROKOSC pierwszej —
    # wymiar ukladu, ktorego serwer nie zna.
    assert 'offsetWidth' in js


def test_js_ustawia_zastepcza_wysokosc_pod_wirtualizacje():
    js = zrodlo()
    assert 'containIntrinsicSize' in js
    assert 'WYSOKOSC_WIERSZA' in js


def test_js_buduje_klucz_zmiany_w_formacie_poziom_id_pole():
    # NIEZMIENNIK MIEDZYPANELOWY: ten sam napis produkuje serwis zapisu
    # (Zadanie 10) i po nim odnajduje komorke wynik wysylki. Rozjazd
    # oznaczalby „zapisano" nad komorka, ktorej nikt nie zapisal.
    js = zrodlo()
    assert 'function klucz(' in js
    assert "poziom + ':' + id + ':' + nazwa" in js


@pytest.mark.parametrize('klawisz', ['ArrowUp', 'ArrowDown', 'ArrowLeft',
                                     'ArrowRight', 'Tab', 'Enter'])
def test_js_obsluguje_nawigacje_klawiatura(klawisz):
    assert f"'{klawisz}'" in zrodlo()


def test_js_wiesza_podpowiedz_kolumny_na_naglowku():
    # „Data platnosci" jest przy imporcie PRZYBLIZENIEM — BaseLinker nie
    # zwraca daty wplaty w getOrders. Uzytkownik ma to zobaczyc na kolumnie,
    # a nie odkryc przy uzgadnianiu raportu.
    js = zrodlo()
    assert 'kolumna.podpowiedz' in js
    assert 'ma-podpowiedz' in js


def test_js_zablokowana_komorka_tlumaczy_sie_i_mowi_jak_zdjac_blokade():
    # Milczaco nieklikalna komorka wyglada jak blad aplikacji.
    js = zrodlo()
    assert 'function zablokuj(' in js
    assert "'zablokowana'" in js
    assert 'aria-label' in js
    assert 'ponowne pobranie tego zamówienia' in js
    assert 'tylko administrator' in js


def test_js_doczytuje_kolejna_strone_przy_przewinieciu():
    js = zrodlo()
    assert "'scroll'" in js
    assert 'stronicowanie.wiecej' in js
    assert 'stronicowanie.offset' in js


def test_js_odswieza_dane_po_zmianie_okna_szukajki_i_filtru():
    js = zrodlo()
    for identyfikator in ('ark-szukaj', 'ark-okno', 'ark-filtry', 'ark-kolumny'):
        assert identyfikator in js, identyfikator
    # Szukajka bez opoznienia strzelalaby zapytaniem na kazda litere.
    assert 'OPOZNIENIE_SZUKANIA' in js
    # Filtr to ten sam komponent, co na dashboardzie i w Eksploratorze.
    assert 'FiltrWymiaru' in js


def test_js_synchronizuje_adres_przegladarki():
    # Adres arkusza ma sie dac zapisac w zakladkach — tak samo jak adres
    # Eksploratora.
    assert 'replaceState' in zrodlo()


def test_js_nie_wstawia_danych_przez_innerhtml():
    # Dane pochodza od klienta (nazwa klienta, uwagi) i trafiaja do DOM-u.
    # textContent zamyka cala klase bledow XSS jednym warunkiem.
    js = zrodlo()
    assert 'innerHTML' not in js
    assert 'textContent' in js


def test_js_wstawia_wartosci_prosto_z_payloadu():
    js = zrodlo()
    assert '.pola[' in js
    assert '.surowe[' in js


def test_js_pokazuje_komunikat_gdy_api_oddaje_blad():
    js = zrodlo()
    assert 'pokazBlad' in js
    assert 'komunikat' in js
    # Wygasla sesja oddaje 401 z JSON-em; uzytkownik ma zobaczyc, ze ma sie
    # zalogowac, a nie wieczny pusty arkusz.
    assert '401' in js


def test_js_pokazuje_stan_pusty_gdy_brak_zamowien():
    js = zrodlo()
    assert 'Brak zamówień w tym oknie dat' in js


def test_js_wystawia_swoje_wnetrze_dla_kolejnych_zadan():
    # Zadania 9, 12 i 15 dopisuja do tego samego pliku i musza miec sie
    # czego zlapac.
    js = zrodlo()
    assert 'window.Arkusz' in js
    for nazwa in ('wczytaj', 'klucz', 'komorkaPoKluczu', 'opisKolumny', 'pokazBlad'):
        assert nazwa in js, nazwa


def test_js_oznacza_stan_ladowania_dla_czytnikow_ekranu():
    js = zrodlo()
    assert "aria-busy" in js


# ===== poprawka z przegladu Zadania 8 [KRYTYCZNE] =======================
# #ark-cialo w arkusz.html siedzi teraz na <table>, nie na <tbody>
# (patrz tests/test_arkusz_widok.py::test_id_ark_cialo_siedzi_na_tabeli_nie_na_tbody).
# `cialo` w tym pliku wskazuje wiec na CALA tabele, wlacznie z <thead>: JS
# NIE WOLNO czyscic wszystkich jej dzieci przy kazdym swiezym pobraniu,
# bo zniknalby razem z nimi naglowek. Musi usuwac WYLACZNIE bloki
# <tbody class="ark-zamowienie">.

def test_js_czysci_tylko_bloki_zamowien_a_nie_wszystkie_dzieci_ciala():
    js = zrodlo()
    assert 'function wyczyscCialo(' in js
    poczatek = js.index('function wyczyscCialo(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert "querySelectorAll('tbody.ark-zamowienie')" in funkcja
    # Ten wzorzec czyscil KAZDE dziecko #ark-cialo — gdy #ark-cialo bylo
    # samym <tbody> to bylo bezpieczne, ale odkad siedzi na <table>,
    # ten sam kod wywalalby <thead> przy pierwszym swiezym pobraniu danych.
    assert 'while (cialo.firstChild)' not in js


def test_js_odswiezenie_od_zera_woła_czyszczenie_ciala():
    js = zrodlo()
    poczatek = js.index('function przyjmij(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'wyczyscCialo()' in funkcja


# ===== poprawki z przegladu zadan 7+8 (fala „arkusz-front") ==============

def test_js_domraza_druga_kolumne_po_doladowaniu_fontow():
    # [WAZNE] nr 4: `zamrozDrugaKolumne()` liczy przesuniecie drugiej
    # zamrozonej kolumny z FAKTYCZNEJ szerokosci pierwszej w chwili
    # wywolania. Fonty IBM Plex doladuja sie asynchronicznie
    # (`font-display: swap` w analiza.css) PO pierwszym, synchronicznym
    # wywolaniu (przy starcie) — gdy podmieni sie font, przegladarka
    # przelicza layout, ale nic bez tego nasluchu nie przeliczyloby
    # przesuniecia na nowo, wiec druga kolumna zostawalaby na starej
    # pozycji („nie trzyma pozycji" — zaobserwowane recznie).
    js = zrodlo()
    assert 'document.fonts' in js
    poczatek = js.index('.fonts.ready.then(')
    fragment = js[poczatek:poczatek + 40]
    assert 'zamrozDrugaKolumne' in fragment


def test_js_nr_baselinkera_dostaje_monospace_bez_wyrownania_do_prawej():
    # [WAZNE] nr 5: makieta pokazuje „Nr BaseLinker" czcionka monospace
    # ('m'), ale BEZ 'num' — to identyfikator (same cyfry), nie wielkosc
    # liczbowa, wiec nie wyrownuje sie do prawej i nie dostaje separatora
    # tysiecy. Serwer rozstrzyga to osobna flaga 'monospace'
    # (arkusz_service._opis_kolumny), rozlaczna z 'liczbowa'.
    js = zrodlo()
    assert 'kolumna.monospace' in js
    poczatek = js.index("if (kolumna.liczbowa) { komorka.classList.add('m', 'num'); }")
    fragment = js[poczatek:poczatek + 200]
    assert 'kolumna.monospace' in fragment
    assert "classList.add('m'); }" in fragment


# ===== SLEDZENIE ZMIAN (Zadanie 9) =====================================

def test_js_trzyma_wartosci_pierwotne_i_zbior_zmian():
    # Wzorzec z modules/settings/static/js/settings.js: mapy originalValues
    # i changedRecords. Ta sama konwencja, inne nazwy (kod po polsku).
    js = zrodlo()
    assert 'oryginalne' in js
    assert 'zmienione' in js


def test_js_kasuje_zmiane_gdy_wartosc_wraca_do_pierwotnej():
    # settings.js:238 — trackChange usuwa rekord ze zbioru zmian, gdy
    # wszystkie pola wrocily do oryginalu. Bez tego licznik rosnie, a zapis
    # wysyla do BaseLinkera wartosc, ktora sie nie zmienila.
    js = zrodlo()
    assert 'zmienione.delete(' in js


def test_js_oznacza_zmieniona_komorke_i_pokazuje_poprzednia_wartosc():
    js = zrodlo()
    assert 'edytowana' in js
    assert "'was'" in js


def test_js_edycja_scalonej_komorki_to_jeden_klucz():
    """Komorka poziomu zamowienia dzieli rowspan miedzy wszystkie pozycje,
    ale MUSI dostac jeden klucz (`zamowienie:<id>:<pole>`), nie po jednym
    na kazda pozycje pod spodem — inaczej serwis zapisu (Zadanie 10)
    zamienilby jeden UPDATE na sales_orders w wiele niezaleznych zapisow
    tej samej komorki.

    CZEGO TEN TEST NIE GWARANTUJE: pakiet NIE URUCHAMIA JS (patrz naglowek
    pliku), wiec nie da sie tu dowiesc, ze dwie edycje tej samej scalonej
    komorki w przegladarce NAPRAWDE koncza sie jednym wpisem w mapie
    `zmienione` — to sprawdza wylacznie krok „obejrzyj w przegladarce"
    z zadania. Test sprawdza najblizszy mozliwy dowod zrodlowy: funkcja
    rysujaca wiersz tworzy komorke poziomu 'zamowienie' WYLACZNIE
    w pierwszym wierszu bloku i zawsze z id CALEGO zamowienia — a nie
    identyfikatorem pozycji, ktory rozjechalby klucz miedzy wierszami.

    Poprzednia wersja tego testu szukala w calym pliku wylacznie slowa
    „JEDEN" — ktore zyje TYLKO w komentarzu (patrz `ustawZmiane`) i test
    zostalby zielony nawet po usunieciu ponizszej logiki, dopoki ktos nie
    skasowalby przy okazji i tego komentarza (znalezisko z przegladu:
    test_js_edycja_scalonej_komorki_to_jeden_klucz przechodzil na slowie
    z komentarza).
    """
    js = zrodlo()
    poczatek = js.index('function rysujWiersz(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    # Komorka poziomu zamowienia rysuje sie TYLKO w pierwszym wierszu bloku
    # — usuniecie tej strazy dodaloby drugie (trzecie, czwarte…) wywolanie
    # rysujKomorke(...'zamowienie'...) w kolejnych wierszach tej samej
    # pozycji, z osobnym <td> i tym samym kluczem nadpisujacym poprzedni.
    assert 'if (!pierwszy) { return; }' in funkcja
    # ...i to jedyne wywolanie niesie id CALEGO zamowienia, nie pozycji —
    # gdyby ktos podmienil je na `pozycja.id`, klucz zmienialby sie razem
    # z tym, ktora pozycja akurat siedzi w pierwszym wierszu bloku.
    assert "rysujKomorke(kolumna, indeks, zamowienie, 'zamowienie'," in funkcja
    assert 'zamowienie.id, zamowienie.wierszy' in funkcja


@pytest.mark.parametrize('forma', ['zmieniona komórka', 'zmienione komórki',
                                   'zmienionych komórek'])
def test_js_licznik_zmian_odmienia_sie_po_polsku(forma):
    assert forma in zrodlo()


@pytest.mark.parametrize('forma', ['zamówieniu', 'zamówieniach'])
def test_js_licznik_odmienia_takze_zamowienia(forma):
    assert forma in zrodlo()


def test_js_licznik_liczy_komorki_i_zamowienia_osobno():
    js = zrodlo()
    assert 'ark-licznik-zmian' in js
    assert 'zamowieniaZeZmianami' in js


# ===== POPRAWKA Z DOMKNIECIA PLANU C, ZNALEZISKO 2 (Mono na cyfry) =====

def test_js_licznik_i_pasek_kontekstowy_owijaja_cyfry_w_span_m():
    # Zasada projektu: „IBM Plex Mono na KAZDA cyfre" — rowniez tam, gdzie
    # tekst powstaje jako zdanie sklejone ze zwyklych stringow (licznik
    # zmian i pasek kontekstowy), nie tylko w komorkach siatki. Bez tego
    # cyfry licznika/paska renderowaly sie w IBM Plex Sans (zmierzone przez
    # getComputedStyle) — CSS ma regule `.ark .m` gotowa do uzycia, brakowalo
    # tylko owiniecia w JS.
    js = zrodlo()
    assert 'function ustawTekstZCyframi(' in js
    poczatek = js.index('function ustawTekstZCyframi(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert "cyfry.className = 'm'" in funkcja


@pytest.mark.parametrize('funkcja_wolajaca', ['odswiezStan', 'odswiezStanPorazki', 'pokazBlad'])
def test_js_licznik_i_pasek_kontekstowy_uzywaja_owijania_cyfr(funkcja_wolajaca):
    # Zdefiniowanie ustawTekstZCyframi() nie wystarczy — kazde miejsce,
    # ktore wypelnia #ark-licznik-zmian albo #ark-kontekst, musi jej
    # NAPRAWDE uzywac zamiast gołego .textContent =, inaczej cyfry w tej
    # konkretnej galezi dalej wpadlyby w Sans.
    js = zrodlo()
    poczatek = js.index(f'function {funkcja_wolajaca}(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'ustawTekstZCyframi(' in funkcja
    # Zaden z dwoch elementow nie dostaje juz golego .textContent = z tresc
    # zawierajaca cyfry w tej funkcji (pusty string w schowajBlad() to inna
    # sprawa — nie ma tam czego owijac).
    assert 'licznik.textContent = ' not in funkcja
    assert 'pasek.textContent = ' not in funkcja


def test_js_wlacza_bursztynowy_stan_narzedziownika():
    js = zrodlo()
    assert 'ark-brudny' in js


def test_js_nie_wpisuje_czerwieni_przy_niezapisanych_zmianach():
    # Kolory stanu niezapisanego siedza w CSS (.ark-brudny), nie w JS.
    # Ten test pilnuje, ze JS nie obchodzi tego wlasnym stylem.
    js = zrodlo()
    assert '#B33A2B' not in js
    assert '#C4472F' not in js


def test_js_pasek_kontekstowy_rozdziela_zmiany_bl_i_crm():
    js = zrodlo()
    assert 'polecą do BaseLinkera' in js
    assert 'zostaną tylko w CRM' in js
    assert 'Zamknięcie karty teraz spowoduje utratę zmian' in js
    assert 'wymaga potwierdzenia' in js


@pytest.mark.parametrize('napis', ['Zapisz i wyślij do BaseLinkera', 'Zapisz'])
def test_js_etykieta_przycisku_zapisu_mowi_prawde(napis):
    # Spec 5.4: uzytkownik nie powinien odkrywac dopiero z dialogu,
    # ze rusza dane poza CRM-em.
    assert napis in zrodlo()


def test_js_odrzuc_zmiany_przywraca_wartosci_pierwotne():
    js = zrodlo()
    assert 'odrzucZmiany' in js
    assert 'ark-odrzuc' in js


def test_js_ctrl_z_cofa_ostatnia_zmiane_w_obrebie_sesji():
    js = zrodlo()
    assert 'historia' in js
    assert 'ctrlKey' in js
    assert "'z'" in js


def test_js_ostrzega_przed_zamknieciem_karty_z_niezapisanymi_zmianami():
    # settings.js:741 robi dokladnie to samo.
    js = zrodlo()
    assert 'beforeunload' in js
    assert 'returnValue' in js


@pytest.mark.parametrize('typ', ['wybor', 'logiczna', 'data', 'kwota', 'liczba'])
def test_js_edytor_dopasowuje_sie_do_typu_kolumny(typ):
    assert f"'{typ}'" in zrodlo()


# ===== POPRAWKA Z DOMKNIECIA PLANU C, ZNALEZISKO 1 (polski przecinek) ===

def test_js_edytor_kwoty_i_liczby_nie_uzywa_input_number():
    # input[type="number"] dopuszcza WYLACZNIE kropke jako separator
    # dziesietny — przy polskim przecinku .value zwraca PUSTY string
    # ('badInput') i wpisana kwota po cichu znika (zmierzone na
    # paid_cash: pole pokazuje „0,", zapis nie dochodzi do skutku).
    # Kolumny 'kwota'/'liczba' musza wiec dostawac input tekstowy.
    js = zrodlo()
    poczatek = js.index('function edytor(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert "pole.type = 'number'" not in funkcja
    assert "kolumna.typ === 'kwota' || kolumna.typ === 'liczba'" in funkcja
    assert "pole.type = 'text'" in funkcja


def test_js_normalizuje_polski_przecinek_na_kropke_przed_wyslaniem():
    # Serwer (arkusz_zapis.na_wartosc) dokumentuje wprost format wejscia:
    # kropka dziesietna, przecinek odrzuca swiadomie. Przegladarka MUSI
    # wiec sama zamienic przecinek na kropke, zanim wartosc trafi do
    # payloadu zapisu — inaczej „10,50" wpisane po polsku ladowaloby sie
    # do Decimal('10,50') po stronie serwera i konczylo bledem walidacji.
    js = zrodlo()
    assert 'function znormalizujWartosc(' in js
    poczatek = js.index('function znormalizujWartosc(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert "kolumna.typ === 'kwota' || kolumna.typ === 'liczba'" in funkcja
    assert "replace(',', '.')" in funkcja
    # ...i zatwierdzEdycje() musi jej NAPRAWDE uzywac, nie tylko definiowac
    # funkcje obok.
    poczatek_z = js.index('function zatwierdzEdycje(')
    funkcja_z = js[poczatek_z:js.index('\n  }', poczatek_z)]
    assert 'znormalizujWartosc(pole.value, kolumna)' in funkcja_z


def test_js_normalizacja_nie_rusza_przecinka_w_zwyklym_tekscie():
    # Kolumna 'tekst' (np. Uwagi) moze zawierac przecinek jako zwykly znak
    # interpunkcyjny — znormalizujWartosc() nie wolno go tam zamieniac na
    # kropke. Warunek w funkcji musi byc zawezony do typow liczbowych,
    # nie zamieniac przecinka bezwarunkowo.
    js = zrodlo()
    poczatek = js.index('function znormalizujWartosc(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    # Zamiana stoi w bloku warunkowym po typie kolumny — nie jest goła,
    # bezwarunkowa linijka na poczatku funkcji.
    assert funkcja.index("kolumna.typ === 'kwota'") < funkcja.index("replace(',', '.')")
    assert funkcja.index('if (kolumna') < funkcja.index("replace(',', '.')")


def test_js_waliduje_dlugosc_przed_wyslaniem():
    # Limit 200 znakow na admin_comments jest po stronie CRM, PRZED wysylka
    # do BaseLinkera (spec 9). Rejestr niesie limit dla kazdej kolumny.
    js = zrodlo()
    assert 'max_dlugosc' in js
    assert 'maxLength' in js


def test_js_escape_anuluje_edycje_bez_zapisu():
    js = zrodlo()
    assert "'Escape'" in js
    assert 'anulujEdycje' in js


def test_js_stopka_podpowiada_cofanie():
    assert 'Cofnij zmianę: Ctrl+Z' in zrodlo()


# ===== POPRAWKI Z PRZEGLADU ZADANIA 9 ====================================

def test_js_przyjmij_odtwarza_zmiany_po_przeladowaniu_siatki():
    # [KRYTYCZNE] Szukajka, zmiana okna dat i zmiana filtra wolaja
    # wczytaj(true) -> przyjmij(), ktore rysuja siatke OD ZERA. Bez
    # ponownego nalozenia `zmienione` na nowo narysowane komorki niezapisana
    # edycja przezywa w mapie, ale znika z ekranu — komorka traci klase
    # 'edytowana', pokazuje stara wartosc, a dataset.surowa jest puste,
    # mimo ze licznik i bursztynowy narzedziownik dalej twierdza, ze cos
    # jest zmienione.
    js = zrodlo()
    poczatek = js.index('function przyjmij(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'wstawTbody' in funkcja
    assert 'odtworzZmianyPoPrzeladowaniu()' in funkcja


def test_js_funkcja_odtwarzania_zmian_maluje_widoczne_komorki():
    js = zrodlo()
    assert 'function odtworzZmianyPoPrzeladowaniu(' in js
    poczatek = js.index('function odtworzZmianyPoPrzeladowaniu(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    # Kazda zmiana z mapy wraca na komorke: surowa wartosc i przemalowanie.
    assert 'zmienione.forEach(' in funkcja
    assert 'komorka.dataset.surowa = zmiana.jest' in funkcja
    assert 'malujKomorke(komorka, zmiana)' in funkcja
    assert 'odswiezStan()' in funkcja


# ===== poprawka z przegladu fali 3, [WAZNE] 3 (niezapisane zmiany znikaly
# bez ostrzezenia) ========================================================

def test_js_przeladowanie_nie_kasuje_niezapisanych_zmian_bez_ostrzezenia():
    # KRYTYCZNY dowod regresji: `odtworzZmianyPoPrzeladowaniu` NIE WOLNO juz
    # wywolywac `zmienione.delete(...)` ani `delete oryginalne[...]` dla
    # komorki, ktorej nie ma na nowo narysowanej siatce (inne okno dat,
    # szukajka albo filtr). Stara wersja robila dokladnie to — uzytkownik
    # tracil niezapisana prace jednym klikinciem, bez zadnego komunikatu.
    # Ten test PADAL na kodzie sprzed poprawki (funkcja zawierala oba te
    # wywolania) i przechodzi po niej (zmiana zostaje w mapie, patrz
    # docstring `odtworzZmianyPoPrzeladowaniu` w zrodle).
    js = zrodlo()
    poczatek = js.index('function odtworzZmianyPoPrzeladowaniu(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'zmienione.delete(' not in funkcja
    assert 'delete oryginalne[' not in funkcja
    # Jedyna reakcja na brak komorki to pominiecie malowania (nie ma czego
    # malowac) — bez zadnej formy kasowania stanu.
    assert 'if (!komorka) { return; }' in funkcja


def test_js_odswiezstan_liczy_zmiany_ukryte_poza_biezacym_widokiem():
    # Naprawa: uzytkownik dostaje OSTRZEZENIE zamiast cichej utraty pracy.
    # Liczba komorek z `zmienione`, ktorych nie ma na ekranie, jest liczona
    # NA BIEZACO w odswiezStan() (ta sama petla, co juz i tak sprawdza kazda
    # komorke przez komorkaPoKluczu) — nie osobnym, potencjalnie
    # nieaktualnym licznikiem.
    js = zrodlo()
    poczatek = js.index('function odswiezStan(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'var ukryte = 0;' in funkcja
    assert 'if (!komorka) { ukryte += 1; }' in funkcja
    assert 'nic nie zginęło' in funkcja
    assert 'poza bieżącym widokiem' in funkcja


def test_js_ostrzezenie_o_ukrytych_zmianach_jest_bursztynowe_nie_czerwone():
    # „Bursztyn, nie czerwień" (zasada projektu, arkusz.css:90-91): ostrzezenie
    # o zmianach poza widokiem idzie do TEGO SAMEGO paska #ark-kontekst, w
    # galezi, ktora NIE dodaje klasy 'ark-kontekst--blad' (czerwien jest
    # zarezerwowana dla bledow BaseLinkera — patrz pokazBlad). Warunek na
    # wejsciu do tej galezi wprost WYKLUCZA klase bledu.
    js = zrodlo()
    poczatek = js.index('function odswiezStan(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    pozycja_warunku = funkcja.index(
        "if (komorek && !pasek.classList.contains('ark-kontekst--blad'))")
    pozycja_tekstu = funkcja.index('nic nie zginęło')
    # Tekst ostrzezenia siedzi WEWNATRZ galezi strzezonej warunkiem, ktory
    # WYKLUCZA klase bledu (czerwien jest zarezerwowana dla bledow BaseLinkera
    # — patrz pokazBlad). Miedzy warunkiem a tekstem NIE MA dodania tej klasy.
    assert pozycja_warunku < pozycja_tekstu
    assert "classList.add('ark-kontekst--blad')" not in funkcja[pozycja_warunku:pozycja_tekstu]


def test_js_cofnij_odtwarza_wpis_w_zmienione_gdy_go_brak():
    # [WAZNE] Scenariusz: uzytkownik recznie wpisuje z powrotem wartosc
    # oryginalna (co poprawnie kasuje wpis w `zmienione` przez rownosc
    # surowych wartosci), a potem odpala Ctrl+Z. Stara wersja robila
    # `zmienione.get(...)` i modyfikowala wpis TYLKO gdy juz istnial w
    # mapie — po powrocie do oryginalu wpisu juz nie bylo, wiec `if (wpis)`
    # cicho nic nie robil: dataset.surowa wracalo do starej wartosci, ale
    # komorka wizualnie sie nie zmieniala i wpis nie wracal do `zmienione`.
    js = zrodlo()
    poczatek = js.index('function cofnij(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'zmienione.set(ostatnia.klucz' in funkcja
    # Odtworzony wpis musi dostac etykiete/metode/wrazliwosc na nowo
    # z rejestru kolumn, nie tylko surowe jest/jestTekst.
    assert 'opisKolumny(' in funkcja


def test_js_historia_nie_czyta_textcontent_scalonej_komorki():
    # [WAZNE] W chwili wywolania ustawZmiane komorka zawiera jeszcze edytor
    # (<input>/<select>) — jego wartosc NIE jest textContentem (input daje
    # pusty napis). Przy drugiej edycji tej samej komorki bez powrotu do
    # oryginalu czytanie textContent byloby jeszcze gorsze: sklejenie starych
    # fragmentow bez separatora ('A'+'B'='AB'). Poprawny tekst „przed" to
    # jestTekst istniejacego wpisu w `zmienione`, a przy pierwszej edycji —
    # dataset.tekstPierwotny.
    js = zrodlo()
    poczatek = js.index('function ustawZmiane(')
    funkcja = js[poczatek:js.index('\n  }', poczatek)]
    assert 'komorka.textContent' not in funkcja
    assert 'jestTekst' in funkcja
    assert 'komorka.dataset.tekstPierwotny' in funkcja


def test_js_globalny_ctrl_z_pomija_pola_formularza():
    # [WAZNE] Globalny keydown na document przechwytywal Ctrl+Z bez
    # sprawdzenia fokusu — w otwartym edytorze komorki kasowalo to
    # wlasnie wpisywana wartosc, a w szukajce cofalo zmiane w jakiejs
    # komorce zamiast wpisanej frazy.
    js = zrodlo()
    assert "cel.closest('.ark-edytor')" in js
    assert "cel.matches('input, select, textarea')" in js


# ===== DIALOG I PORAZKA CZESCIOWA (Zadanie 12) =========================

def test_js_pokazuje_dialog_przed_wysylka_do_baselinkera():
    js = zrodlo()
    assert 'pokazDialog' in js
    assert 'idaDoBl()' in js


def test_js_dialog_nie_pojawia_sie_dla_zmian_wylacznie_crm():
    # Zmiana, ktora nie wychodzi poza CRM, nie wymaga potwierdzenia —
    # inaczej dialog stalby sie klikaniem na pamiec.
    js = zrodlo()
    assert 'idaDoBl().length' in js


def test_js_dialog_wypelnia_wiersz_pieciu_komorkami():
    # Naglowki stoja w szablonie; JS wypelnia wiersze w tej samej kolejnosci:
    # zamowienie, pole, bylo, bedzie, metoda API.
    js = zrodlo()
    assert 'ark-dialog-lista' in js
    assert 'wierszDialogu' in js
    for pole in ('zmiana.numerBl', 'zmiana.etykieta', 'zmiana.byloTekst',
                 'zmiana.jestTekst', 'zmiana.metoda'):
        assert pole in js, pole


def test_js_dialog_oznacza_pola_wrazliwe():
    js = zrodlo()
    assert 'wrazliwe' in js
    assert 'wrażliwe' in js


def test_js_dialog_ostrzega_o_skutkach_zmiany_pola_wrazliwego():
    js = zrodlo()
    assert 'ark-dialog-ostrzezenie' in js
    assert 'powiadomienie do klienta' in js


def test_js_dialog_pokazuje_co_zostaje_w_crm():
    js = zrodlo()
    assert 'zostajaWCrm()' in js
    assert 'ark-dialog-crm-lista' in js


def test_js_etykieta_przycisku_wysylki_liczy_zmiany():
    assert 'i zapisz pozostałe' in zrodlo()


def test_js_dialog_pamieta_nie_pytaj_ponownie_w_tej_sesji():
    js = zrodlo()
    assert 'ark-dialog-niepytaj' in js
    assert 'niePytajWTejSesji' in js


def test_js_dialog_zamyka_sie_escapem_i_anuluj():
    js = zrodlo()
    assert 'ark-dialog-anuluj' in js
    assert "'Escape'" in js


def test_js_wysyla_zmiany_na_adres_z_data_atrybutu():
    js = zrodlo()
    assert 'dataset.urlZapis' in js
    assert "'POST'" in js
    assert 'zmiany: paczka' in js


def test_js_wysyla_wartosc_pierwotna_komorki():
    # Straznik optymistyczny: serwer odrzuci zmiane, jesli w bazie jest juz
    # co innego. Bez tego pola dwie osoby w tym samym arkuszu nadpisywalyby
    # sie po cichu.
    js = zrodlo()
    assert 'bylo: zmiana.bylo' in js


def test_js_wynik_trafia_do_komorki_po_kluczu():
    # NIEZMIENNIK MIEDZYPANELOWY: serwer oddaje wynik z kluczem
    # poziom:id:nazwa, przegladarka po tym samym kluczu odnajduje komorke.
    js = zrodlo()
    assert 'komorkaPoKluczu(wynik.klucz)' in js


def test_js_oznacza_zapisane_komorki_na_czysto():
    js = zrodlo()
    assert 'oznaczZapisane' in js
    assert "'zapisana'" in js


def test_js_zostawia_odrzucone_komorki_brudne_z_bledem():
    js = zrodlo()
    assert 'oznaczOdrzucone' in js
    assert "'odrzucona'" in js
    assert 'wynik.blad' in js


def test_js_wstawia_wiersz_bledu_pod_odrzucona_komorke():
    js = zrodlo()
    assert 'ark-wiersz-bledu' in js
    assert 'colSpan' in js


def test_js_narzedziownik_pokazuje_zapis_czesciowy():
    js = zrodlo()
    assert 'ark-porazka' in js
    assert 'nie przeszła' in js


def test_js_przycisk_zmienia_sie_na_ponow_wysylke():
    assert 'Ponów wysyłkę' in zrodlo()


def test_js_odrzuc_nieudana_czysci_tylko_nieudane():
    js = zrodlo()
    assert 'Odrzuć nieudaną' in js
    assert 'odrzucNieudane' in js


def test_js_stopka_wymienia_zapisane_pola():
    js = zrodlo()
    assert 'zapisane:' in js


def test_js_stopka_nie_obiecuje_nieistniejacego_logu():
    # Makieta mowi „Log wysylek do BaseLinkera dostepny w Ustawieniach →
    # Integracje". Takiego ekranu w aplikacji NIE MA i nie budujemy go tutaj.
    js = zrodlo()
    assert 'Ustawieniach' not in js
    assert 'popraw wartość albo odrzuć' in js


def test_js_czerwien_tylko_dla_bledow():
    # Klasy stanu siedza w CSS. JS nie wpisuje kolorow.
    js = zrodlo()
    assert '#FBE3DD' not in js
    assert '#EAF6EE' not in js


# ===== poprawki z przegladu Zadania 12 =================================

def test_js_wiersz_bledu_trafia_na_koniec_bloku_zamowienia():
    # KRYTYCZNE: wstawienie wiersza bledu ZARAZ ZA wierszem komorki
    # (insertBefore(wiersz, wierszKomorki.nextSibling)) wsuwalo go W SRODEK
    # zakresu rowspan komorki poziomu zamowienia (np. odrzucone paid_amount,
    # rowspan=4 przy 4 pozycjach) — ostatni wiersz pozycji tracil wtedy
    # kolumny zamowienia i renderowal sie przesuniety, pod zlymi naglowkami
    # (zmierzone: zamowienie id=3292, wood_species na x=-10 zamiast x=985).
    # Wiersz bledu musi isc na KONIEC <tbody> bloku zamowienia — poza
    # zasieg jakiegokolwiek rowspana.
    js = zrodlo()
    poczatek = js.index('function oznaczOdrzucone')
    koniec = js.index('function usunWierszBledu')
    fragment = js[poczatek:koniec]
    assert "komorka.closest('tbody').appendChild(wiersz)" in fragment
    assert 'insertBefore' not in fragment
    assert '.nextSibling' not in fragment


def test_js_usun_wiersz_bledu_szuka_po_kluczu_nie_po_sasiedztwie():
    # Skoro wiersz bledu stoi teraz na koncu bloku (patrz test wyzej),
    # usunWierszBledu NIE MOZE juz polegac na `.closest('tr').nextSibling`
    # — to trafialoby przypadkiem w cudzy wiersz bledu albo w nic. Musi
    # odnajdywac SWOJ wiersz po kluczu komorki, ktorego ten wiersz dotyczy.
    js = zrodlo()
    poczatek = js.index('function usunWierszBledu')
    koniec = js.index('function odrzucNieudane')
    fragment = js[poczatek:koniec]
    assert "komorka.closest('tr').nextSibling" not in fragment
    assert 'data-dla-klucza' in fragment
    assert 'komorka.dataset.klucz' in fragment
    # I miejsce, gdzie ten atrybut jest nadawany przy tworzeniu wiersza.
    assert 'wiersz.dataset.dlaKlucza' in js


def test_js_malujkomorke_zdejmuje_klase_zapisana_przy_edycji():
    # [WAZNE]: klasa 'zapisana' (zielony akcent) nigdy nie byla zdejmowana.
    # arkusz.css ma `.ark-tabela td.zapisana` PO `.ark-tabela td.edytowana`
    # przy tej samej specyficznosci (oba tla z !important), wiec przy
    # ponownej edycji juz raz zapisanej komorki wygrywal ZIELONY — komorka
    # z NIEZAPISANA zmiana wygladala jak zapisana. Lamie to wiazaca zasade
    # „bursztyn dla niezapisanych zmian".
    js = zrodlo()
    poczatek = js.index('function malujKomorke')
    koniec = js.index('\n  }', poczatek)
    fragment = js[poczatek:koniec]
    assert "classList.remove('zapisana')" in fragment


def test_js_powrot_po_udanym_ponowieniu_resetuje_etykiete_odrzuc_i_chowa_blad():
    # [WAZNE] x2: wczesny return w odswiezStanPorazki (w pelni udane
    # ponowienie, !odrzucone.length) resetowal tylko etykiete #ark-zapisz.
    # #ark-odrzuc zostawal przy myslacej 'Odrzuć nieudaną', a czerwony pasek
    # #ark-kontekst z OSTATNIM bledem BaseLinkera zostawal widoczny mimo ze
    # bledu juz nie ma — i po cichu gasil bursztynowy pasek kontekstowy dla
    # WSZYSTKICH kolejnych zmian do konca sesji (odswiezStan() ma straz
    # `!pasek.classList.contains('ark-kontekst--blad')`).
    js = zrodlo()
    poczatek = js.index('function odswiezStanPorazki')
    poczatek_galezi = js.index('if (!odrzucone.length)', poczatek)
    koniec_galezi = js.index('return;', poczatek_galezi) + len('return;')
    fragment = js[poczatek_galezi:koniec_galezi]
    assert "'Odrzuć zmiany'" in fragment
    assert 'schowajBlad()' in fragment


def test_js_odrzucnieudane_resetuje_etykiete_i_nie_nadpisuje_zapisz():
    # [WAZNE] x3:
    # 1) etykieta #ark-odrzuc ('Odrzuć nieudaną') nigdy nie wracala do
    #    'Odrzuć zmiany' — po odrzucNieudane() klasa ark-porazka znika,
    #    wiec kolejne klikniecie #ark-odrzuc wywoluje juz odrzucZmiany()
    #    (kasuje WSZYSTKO bez potwierdzenia), a przycisk dalej klamie,
    #    ze odrzuca „te jedna nieudana".
    # 2) czerwony pasek bledu nie byl gaszony (schowajBlad()).
    # 3) odrzucNieudane() BEZWARUNKOWO nadpisywal etykiete #ark-zapisz na
    #    'Zapisz' PO tym, jak odswiezStan() juz poprawnie ja ustawil —
    #    jesli w arkuszu zostawala jeszcze zmiana idaca do BL, przycisk
    #    klamal, ze klikniecie nie wyśle nic do BaseLinkera.
    js = zrodlo()
    poczatek = js.index('function odrzucNieudane')
    koniec = js.index('\n  }', poczatek)
    fragment = js[poczatek:koniec]
    assert "getElementById('ark-odrzuc').textContent = 'Odrzuć zmiany'" in fragment
    assert 'schowajBlad()' in fragment
    assert "getElementById('ark-zapisz').textContent = 'Zapisz'" not in fragment


def test_js_pasek_bledu_wymienia_numer_zamowienia():
    # [WAZNE]: pasek komunikatu porazki nie podawal numeru zamowienia —
    # makieta BladCzesciowy.dc.html: „Zamowienie 50827145, pole Zaplacono
    # — BaseLinker odrzucil setOrderPayment: ...". Przy 200 zamowieniach na
    # ekranie user nie wiedzial, KTORE nie przeszlo.
    js = zrodlo()
    assert 'numerBlPoKluczu' in js
    poczatek = js.index('function odswiezStanPorazki')
    # UWAGA: `przycisk.textContent = ` wystepuje w tej funkcji DWA razy —
    # raz we wczesnym powrocie ('Zapisz' przy pelnym sukcesie), raz nizej
    # ('Ponów wysyłkę' przy porazce, dopiero PO zbudowaniu paska bledu).
    # Szukamy DRUGIEGO wystapienia, zeby fragment objal caly kod paska.
    koniec = js.index("przycisk.textContent = 'Ponów", poczatek)
    fragment = js[poczatek:koniec]
    assert "'Zamówienie '" in fragment
    assert 'numerBlPoKluczu(w.klucz)' in fragment


def test_js_fokus_dialogu_nie_przewija_do_dolu():
    # [WAZNE]: .ark-dialog ma `overflow: auto` i
    # `max-height: calc(100vh - 48px)` (arkusz.css) — zwykle .focus() na
    # przycisku w STOPCE dialogu (#ark-dialog-anuluj) przewija dialog do
    # samego dolu (zmierzone przy 40 zmianach: scrollTop=1035 przy
    # scrollHeight=1707). User widzial stopke z przyciskami zamiast tytulu
    # i listy zmian.
    js = zrodlo()
    assert "focus({ preventScroll: true })" in js


def test_js_numer_zamowienia_w_dialogu_crm_dostaje_klase_m():
    # [WAZNE]: numer zamowienia w pudelku „Zostaje tylko w CRM" renderowal
    # sie IBM Plex Sans zamiast Mono — makieta ma tu class="m", jak kazda
    # inna cyfra w arkuszu.
    js = zrodlo()
    poczatek = js.index('function pokazDialog')
    koniec = js.index('function zamknijDialog')
    fragment = js[poczatek:koniec]
    assert "pole.className = 'm'" in fragment


# ===== MENU NARZEDZIOWNIKA (Zadanie 15) ================================

def test_js_eksport_pobiera_widok_jednym_klknieciem():
    # Po wypadnieciu Routimo zostala jedna pozycja, wiec „Eksport" jest
    # zwyklym przyciskiem, nie rozwijanym menu.
    js = zrodlo()
    assert 'dataset.urlEksport' in js
    assert 'adresEksportu' in js


def test_js_nie_ma_zadnego_sladu_po_eksporcie_routimo():
    # Decyzja uzytkownika 22.09.2026: trasowka nie wchodzi do arkusza.
    # Stary eksport zostaje przy starej zakladce, nietkniety.
    assert 'routimo' not in zrodlo().lower()


def test_js_menu_wiecej_ma_pobieranie_i_dotychczasowa_tabele():
    js = zrodlo()
    assert 'Pobierz zamówienia z BaseLinkera' in js
    assert 'Dotychczasowa tabela' in js


def test_js_stara_tabela_otwiera_sie_w_nowej_karcie():
    # Decyzja uzytkownika 22.09.2026: „przycisk, ktory otworzy ta tabele
    # w nowej karcie".
    js = zrodlo()
    assert 'dataset.urlStaraTabela' in js
    assert "'_blank'" in js
    assert 'noopener' in js


def test_js_pobieranie_wola_endpoint_i_odswieza_siatke():
    js = zrodlo()
    assert 'dataset.urlPobierz' in js
    assert 'pobierzZamowienia' in js


def test_js_pobieranie_mowi_o_limicie_archiwum():
    # BaseLinker nie oddaje zamowien starszych niz 3 miesiace — uzytkownik
    # ma o tym wiedziec PRZED klinieciem, a nie z bledu 400.
    assert '92 dni' in zrodlo()


def test_js_menu_sa_schowane_przy_niezapisanych_zmianach():
    # Regula z makiety ArkuszZmiany.dc.html rozszerzona na trzy kontrolki:
    # pobranie zamowien nadpisaloby wiersze pod reka uzytkownika, a eksport
    # dalby plik niezgodny z tym, co widac na ekranie.
    js = zrodlo()
    assert 'ark-chowany' in js or 'ark-brudny' in js
    assert 'ark-eksport' in js
    assert 'ark-wiecej' in js


def test_js_pobieranie_pokazuje_ostrzezenie_o_niepelnym_zapisie():
    # ZNALEZISKO z przegladu: `zapisz_zamowienia` moze zapisac czesciowo
    # (np. 5 ze 120 zamowien wywraca sie przy upsercie) i oddaje to
    # w `stat['ostrzezenie']` (ingest.py), ktore endpoint /api/arkusz/pobierz
    # przekazuje dalej w `zapis.ostrzezenie`. Alert liczacy tylko
    # `pobranych`/`zapis.nowe`/`zapis.zaktualizowane` te informacje gubil —
    # uzytkownik czytal sam sukces, a arkusz i sumy w stopce byly ubozsze
    # niz BaseLinker. Musi trafic do `pokazBlad` (czerwien — to realny
    # blad zapisu, nie niezapisana zmiana).
    js = zrodlo()
    poczatek = js.index('function pobierzZamowienia')
    koniec = js.index('window.Arkusz = {')
    fragment = js[poczatek:koniec]
    assert 'dane.zapis && dane.zapis.ostrzezenie' in fragment


# ===== dialog liczy sie na serwerze (fala 4, Zadanie 16) ================
# Spec 5.3 pkt 1: dialog musi wymienic IMIENNIE kazde pole lecace do
# BaseLinkera, LACZNIE z polami DOROZUMIANYMI (ktorych zaznaczone komorki
# same nie niosa — setOrderPayment podmienia cala platnosc naraz). Serwer to
# juz liczy (arkusz_zapis.pozycje_potwierdzenia) — dialog przestaje skladac
# liste wylacznie z lokalnej mapy `zmienione` i dociaga ja z nowego
# endpointu PRZED pokazaniem sie.

def test_js_pokazdialog_jest_asynchroniczny_i_pyta_serwer_najpierw():
    js = zrodlo()
    poczatek = js.index('function pokazDialog')
    koniec = js.index('function zamknijDialog')
    fragment = js[poczatek:koniec]
    assert 'fetch(adresPotwierdzenia()' in fragment
    assert "'POST'" in fragment
    assert 'zmiany: paczkaZmian()' in fragment
    assert 'dane.pozycje' in fragment


def test_js_adres_potwierdzenia_nie_jest_zaszyty_na_sztywno():
    # Ta sama zasada co przy /api/arkusz/dane (test_js_pobiera_dane...):
    # zaden adres API nie jest sklejany na sztywno w kodzie.
    js = zrodlo()
    assert 'function adresPotwierdzenia' in js
    assert "'/reports/api/arkusz/potwierdzenie'" not in js
    # Endpoint nie ma wlasnego atrybutu data-url-... w szablonie — adres
    # wyprowadza sie z adresu zapisu (ten sam blueprint, siostrzana trasa).
    poczatek = js.index('function adresPotwierdzenia')
    koniec = js.index('\n  }', poczatek)
    fragment = js[poczatek:koniec]
    assert 'dataset.urlZapis' in fragment


def test_js_paczka_zmian_jest_wspolna_dla_podgladu_i_zapisu():
    # Jedno miejsce budowania „bylo/jest" z mapy zmienione — inaczej dwa
    # zadania mogłyby po cichu rozjechać się co do tego, co niosą.
    js = zrodlo()
    assert 'function paczkaZmian' in js
    poczatek = js.index('function paczkaZmian')
    koniec = js.index('\n  }', poczatek)
    fragment = js[poczatek:koniec]
    assert 'bylo: zmiana.bylo' in fragment

    poczatek_dialog = js.index('function pokazDialog')
    koniec_dialog = js.index('function zamknijDialog')
    assert 'paczkaZmian()' in js[poczatek_dialog:koniec_dialog]

    poczatek_zapisu = js.index('function wyslijZmiany')
    koniec_zapisu = js.index('function przyjmijWynik')
    assert 'paczkaZmian()' in js[poczatek_zapisu:koniec_zapisu]


def test_js_dialog_nie_pokazuje_sie_gdy_serwer_nie_odpowie():
    # [WAZNE]: bez pelnej listy z serwera dialog klamalby, ze pokazuje
    # wszystko, co poleci do BaseLinkera. `ark-przyciemnienie`/`ark-dialog`
    # smia sie odkryc WYLACZNIE w galezi sukcesu (po odpowiedz.json()),
    # nigdy w .catch — inaczej uzytkownik moglby wyslac zmiany „w ciemno".
    js = zrodlo()
    poczatek = js.index('function pokazDialog')
    koniec = js.index('function zamknijDialog')
    fragment = js[poczatek:koniec]
    poczatek_catch = fragment.index('.catch(')
    koniec_catch = fragment.index('.then(', poczatek_catch)
    fragment_catch = fragment[poczatek_catch:koniec_catch]
    assert "ark-przyciemnienie').hidden = false" not in fragment_catch
    assert "ark-dialog').hidden = false" not in fragment_catch
    assert 'pokazBlad(' in fragment_catch
    # Sama galaz sukcesu MUSI natomiast pokazywac dialog — dowod, ze test
    # wyzej naprawde sprawdza katch, a nie caly fragment.
    assert "ark-przyciemnienie').hidden = false" in fragment
    assert "ark-dialog').hidden = false" in fragment


def test_js_dialog_odblokowuje_przycisk_zapisz_po_kazdym_wyniku():
    # Guard przed podwojnym zapytaniem (klikniecie „Zapisz" w trakcie
    # trwajacego pobierania podgladu) musi puscic przycisk zarowno po
    # sukcesie, jak i po porazce — inaczej jedna nieudana proba blokuje
    # zapis na reszte sesji.
    js = zrodlo()
    poczatek = js.index('function pokazDialog')
    koniec = js.index('function zamknijDialog')
    fragment = js[poczatek:koniec]
    assert 'pobieranieDialogu = true' in fragment
    assert 'pobieranieDialogu = false' in fragment
    assert 'if (pobieranieDialogu) { return; }' in fragment


def test_js_dialog_buduje_wiersze_z_odpowiedzi_serwera_nie_z_lokalnej_mapy():
    js = zrodlo()
    assert 'function wierszZPozycji' in js
    poczatek = js.index('function wierszZPozycji')
    koniec = js.index('\n  }', poczatek)
    fragment = js[poczatek:koniec]
    for pole in ('pozycja.zamowienie', 'pozycja.etykieta', 'pozycja.bylo',
                 'pozycja.bedzie', 'pozycja.metoda', 'pozycja.dorozumiane'):
        assert pole in fragment, pole
    # „wrazliwe" nie przychodzi z /api/arkusz/potwierdzenie (ladunek
    # BaseLinkera go nie niesie) — dialog bierze je z opisu kolumny, ktory
    # arkusz juz ma w pamieci z /api/arkusz/dane.
    assert 'opisKolumny(pozycja.nazwa)' in fragment

    poczatek_dialog = js.index('function pokazDialog')
    koniec_dialog = js.index('function zamknijDialog')
    assert 'dane.pozycje.map(wierszZPozycji)' in js[poczatek_dialog:koniec_dialog]


def test_js_dialog_oznacza_pola_dorozumiane_bursztynem_nie_czerwienia():
    # Spec: wiersze dorozumiane ida NA TA SAMA liste co reszta (NIE ukryte),
    # ale wizualnie odroznione i podpisane, zeby user rozumial dlaczego tam
    # sa. Bursztyn, nie czerwien — to nie jest blad.
    js = zrodlo()
    assert 'function znacznikDorozumiane' in js
    assert 'dokłada BaseLinker' in js
    poczatek = js.index('function znacznikDorozumiane')
    koniec = js.index('\n  }', poczatek)
    fragment = js[poczatek:koniec]
    # Ten sam odcien bursztynu, ktorego arkusz.css juz uzywa gdzie indziej
    # dla stanu „niezapisane" (.ark-licznik/.ark-kontekst) — zaden nowy,
    # niepowiazany kolor.
    assert '#7A4E05' in fragment
    assert '#D98A16' in fragment or 'warn-line' in fragment
    assert '#FBE3DD' not in fragment and '#EAF6EE' not in fragment

    poczatek_wiersz = js.index('function wierszDialogu')
    koniec_wiersz = js.index('function znacznikDorozumiane')
    fragment_wiersz = js[poczatek_wiersz:koniec_wiersz]
    assert 'zmiana.dorozumiane' in fragment_wiersz
    assert 'znacznikDorozumiane()' in fragment_wiersz


def test_js_etykieta_przycisku_wysylki_liczy_prawdziwe_edycje_nie_wiersze_serwera():
    # Guzik „Wyslij N zmian" ma liczyc EDYCJE uzytkownika, nie wiersze
    # dialogu — pole dorozumiane nie jest „zmiana", ktora ktos wpisal, wiec
    # nie ma wchodzic do tej liczby.
    js = zrodlo()
    poczatek = js.index('function pokazDialog')
    koniec = js.index('function zamknijDialog')
    fragment = js[poczatek:koniec]
    assert "'Wyślij ' + idaDoBl().length" in fragment


# ===== ZAMÓWIENIA POZA SPRZEDAŻĄ (partia E, punkt E5) ====================

def test_js_wyszarza_zamowienie_poza_sprzedaza_zdaniem_z_serwera():
    """Zdanie ze statusem składa SERWER (`poza_sprzedaza`); przeglądarka nie
    trzyma własnej listy statusów, tylko wiesza klasę i wstawia tekst."""
    js = zrodlo()
    assert 'zamowienie.poza_sprzedaza' in js
    assert "classList.add('poza-sprzedaza')" in js
    assert "'ark-wiersz-statusu'" in js
    assert 'napisStatusu.textContent = zamowienie.poza_sprzedaza' in js
    # Żadnych numerów statusów BaseLinkera w przeglądarce.
    for numer in ('138625', '105112'):
        assert numer not in js


def test_js_wiersz_statusu_stoi_przed_wierszami_zamowienia():
    """Wiersz statusu MUSI wejść do bloku przed pierwszym wierszem zamówienia
    — rowspan komórek zamówienia liczy się od tamtego wiersza w dół i nie
    może objąć wiersza statusu (ten sam błąd, co przy wierszu błędu)."""
    js = zrodlo()
    wstaw = js[js.index('function wstawTbody'):js.index('function rysujWiersz')]
    assert wstaw.index('blok.appendChild(wierszStatusu)') < wstaw.index('rysujWiersz(zamowienie')
    assert "komorkaStatusu.colSpan = stan.kolumny.length" in wstaw
