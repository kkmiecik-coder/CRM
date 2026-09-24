# -*- coding: utf-8 -*-
"""Trasy nowej zakładki „Analiza sprzedażowa".

Osobny plik, a nie dopiski do `routers.py` — tamten ma 4790 linii i obsługuje
starą zakładkę, która w tym planie zostaje nietknięta. Blueprint jest ten sam
(`reports`, prefiks `/reports`), więc adresy wyglądają spójnie.
"""

import json
from datetime import date, datetime, time

from flask import jsonify, render_template, request, session

from modules.users.decorators import require_module_access

from . import reports_bp
from .analiza_service import (
    ETYKIETY_MIAR, JEDNOSTKI_MIAR, KARTY_KUBELKOWE,
    MIARY_PANELU, MIARY_PRZESTAWIENIA, NAZWA_SEGMENTU_BAZY, WYMIAR_WYKONCZENIA,
    blok_wykluczen,
    dane_dashboardu, dane_eksploratora,
    do_json, dzis_lokalnie, etykieta_z_jednostka, naglowki_kolumn_kart,
    nazwa_zakresu, opcje_przelacznika, opis_okresu, opis_z_etykietami,
    pola_wykluczen, wartosci_wykluczen, wartosci_wymiaru,
    wymiar_wyjscia_karty_kubelkowej, wymiary_karty_kubelkowej,
)
from .arkusz_service import (
    DOMYSLNY_LIMIT, MAKS_LIMIT, dane_arkusza, etykieta_okna, kolumny_arkusza,
    kolumny_z_adresu, moze_wysylac_do_bl, parsuj_okno, wiersze_eksportu,
)
from .explorer import PRZESTAWIENIE_MIESIAC
from .fields import POLA, wymiary, wymiary_proste
from .filters import (
    KOMUNIKAT_OSTATNIEJ_WARTOSCI, filtr_z_wykluczen, parsuj_filtr, parsuj_wykluczenia,
    zapisz_filtr,
)
from .ingest import zapisz_zamowienia
from .service import get_reports_service
from .uklad import (
    KATALOG, MAKS_KAFELKOW, BladUkladu, katalog_do_json, parsuj_uklad, uklad_do_json,
)
from .uklad_service import przywroc_domyslny, uklad_uzytkownika, zapisz_uklad

# Zaporowa górna granica okresu. Dashboard liczy siedem agregatów na zapytanie;
# przy dziesięciu latach naraz szereg miesięczny puchnie do 120 punktów i wykres
# przestaje cokolwiek znaczyć, a zapytanie przestaje być tanie.
_MAKS_DNI_OKRESU = 1100

# Zaporowa DOLNA granica. `poprzedni_okres` odejmuje od `od` dlugosc okresu
# bez sprawdzenia, czy jest od czego odejmowac — przy dacie bliskiej `date.min`
# leci OverflowError „date value out of range" i uzytkownik dostaje 500
# (zmierzone: ?od=0001-01-01&do=0001-12-31). Sprzedazy sprzed 2000 roku
# w tej bazie nie ma i nie bedzie, wiec granica niczego sensownego nie ucina.
_NAJWCZESNIEJSZA_DATA = date(2000, 1, 1)

# Zaporowa długość okna pobierania. BaseLinker przenosi zamówienia starsze
# niż 3 miesiące do ARCHIWUM, którego `getOrders` nie widzi ŻADNYM parametrem
# — `date_from` jest po cichu przycinane do najstarszego znanego zamówienia.
# Okno dłuższe niż kwartał nie przyniosłoby więcej danych, za to zajęłoby
# kilkadziesiąt wywołań API na nic.
MAKS_DNI_POBIERANIA = 92


def _parsuj_date(tekst, domyslna: date) -> date:
    if not tekst:
        return domyslna
    try:
        return datetime.strptime(tekst, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError(f"'{tekst}' nie jest datą w formacie RRRR-MM-DD")


def parsuj_okres(argumenty):
    """Okres z parametrów zapytania. Domyślnie bieżący miesiąc.

    „Dziś" bierzemy z zegara POLSKIEGO, nie z zegara serwera: kontener chodzi
    na UTC, więc między północą a drugą w nocy domyślny okres rozjeżdżałby się
    z tym, co wylicza przeglądarka użytkownika.
    """
    dzis = dzis_lokalnie()
    od = _parsuj_date(argumenty.get('od'), dzis.replace(day=1))
    do = _parsuj_date(argumenty.get('do'), dzis)
    if od > do:
        raise ValueError('początek okresu jest późniejszy niż koniec')
    if od < _NAJWCZESNIEJSZA_DATA:
        raise ValueError('początek okresu jest wcześniejszy niż '
                         f'{_NAJWCZESNIEJSZA_DATA.isoformat()}')
    if (do - od).days > _MAKS_DNI_OKRESU:
        raise ValueError(f'okres dłuższy niż {_MAKS_DNI_OKRESU} dni')
    return od, do


def _wykluczenia_z_adresu(argumenty, surowo: bool = True):
    """Wykluczenia pozycji z parametru `wyklucz` (partia E, punkt E4).

    Zwraca parę (wykluczenia, obecne): odznaczone wartości i wartości obecne
    w danych, z których zbudowano pola wyboru. Bazę pytamy tylko wtedy, gdy
    parametr w ogóle jest — pulpit bez wykluczeń nie płaci za nie ani jednym
    zapytaniem.

    `surowo=False` to strona HTML: zły parametr w adresie nie jest tam
    błędem (nieaktualna zakładka ma pokazać pulpit), tylko jest ignorowany.
    Na API leci ValueError z komunikatem po polsku — trasa oddaje 400.
    """
    tekst = argumenty.get('wyklucz')
    if not tekst or not tekst.strip():
        return None, None
    obecne = wartosci_wykluczen()
    try:
        return parsuj_wykluczenia(tekst, obecne), obecne
    except ValueError:
        if surowo:
            raise
        return None, obecne


def _blad_wykluczen(blad):
    return jsonify({'error': 'zle_wykluczenia', 'komunikat': str(blad)}), 400


@reports_bp.route('/api/analytics')
@require_module_access('reports', as_json=True)
def api_analytics():
    """Komplet danych pulpitu w jednym żądaniu.

    Układ kafelków czytamy Z BAZY, a NIE z parametrów zapytania. Gdyby
    przychodził z adresu, limit dwudziestu kafelków dałoby się obejść ręcznie
    spreparowanym adresem, a ten endpoint jest osiągalny dla każdego, kto ma
    dostęp do modułu. Układ w bazie jest z definicji ograniczony walidacją
    zapisu.

    Parametry `?kanal=`, `?opiekun=` itd., którymi do 23.09.2026 sterowało się
    wymiarem karty, są po cichu ignorowane — tak samo jak każdy inny nieznany
    parametr. Wymiar jest dziś częścią ZAPISANEGO układu, a nie adresu.
    """
    try:
        od, do = parsuj_okres(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zly_okres', 'komunikat': str(blad)}), 400

    try:
        porownanie = parsuj_filtr(request.args.get('porownanie'))
    except ValueError as blad:
        return jsonify({'error': 'zly_filtr', 'komunikat': str(blad)}), 400

    try:
        wykluczenia, obecne = _wykluczenia_z_adresu(request.args)
    except ValueError as blad:
        return _blad_wykluczen(blad)

    # `uklad_uzytkownika(None)` daje układ domyślny — serwis obsługuje to
    # wprost, więc odczyt nie potrzebuje tu osobnej straży (inaczej niż zapis).
    uklad, pominietych = uklad_uzytkownika(_zalogowany())
    return jsonify(do_json(dane_dashboardu(od, do, uklad, porownanie=porownanie,
                                           pominietych=pominietych,
                                           wykluczenia=wykluczenia, obecne=obecne)))


@reports_bp.route('/api/wartosci-wymiaru')
@require_module_access('reports', as_json=True)
def api_wartosci_wymiaru():
    """Wartości jednego wymiaru w okresie — lista do popovera filtra.

    Z wykluczeniami pulpitu, jeśli są (`?wyklucz=`, partia E8, punkt 4f) —
    ta sama walidacja i ten sam 400 co na `/api/analytics`.
    """
    try:
        od, do = parsuj_okres(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zly_okres', 'komunikat': str(blad)}), 400
    try:
        wykluczenia, obecne = _wykluczenia_z_adresu(request.args)
    except ValueError as blad:
        return _blad_wykluczen(blad)

    try:
        dane = wartosci_wymiaru(request.args.get('wymiar') or '', od, do,
                                filtr=filtr_z_wykluczen(wykluczenia, obecne or {}))
    except ValueError as blad:
        return jsonify({'error': 'zly_wymiar', 'komunikat': str(blad)}), 400

    return jsonify(do_json(dane))


def _wymiary_kafelka(nazwa_typu):
    """Opcje selektora „według" dla tego typu, z etykietami.

    Karty kubełkowe mają pseudo-wymiar (`liczba_zamowien`, `wiek_zamowienia`),
    którego w rejestrze pól NIE MA — jego etykieta mieszka w
    `analiza_service.KARTY_KUBELKOWE`. Stąd dwie drogi, a nie jedna.
    """
    if nazwa_typu in KARTY_KUBELKOWE:
        return wymiary_karty_kubelkowej(nazwa_typu)
    return [{'nazwa': n, 'etykieta': POLA[n].etykieta} for n in wymiary()]


def _kontekst_kafelkow(od, do, filtr_wyjsc=''):
    """Zmienne, których potrzebują makra `analiza/_kafelki.html`.

    JEDNO miejsce dla strony i dla obu endpointów fragmentów (`/api/kafelek`,
    `/api/siatka`). Kafelek przyniesiony fragmentem ma być co do znaku tym
    samym kafelkiem, który renderuje strona — trzy osobno sklejane słowniki
    rozjechałyby się przy pierwszej zmianie i użytkownik dostawałby po zmianie
    wymiaru kartę wyglądającą inaczej niż przed nią.
    """
    return {
        # Opcje selektora „według", PER TYP: karty kubełkowe mają własną,
        # węższą listę, reszta — cały rejestr wymiarów.
        'wymiary_kafelka': {klucz: _wymiary_kafelka(klucz)
                            for klucz, typ in KATALOG.items() if typ.wymiarowy},
        # Szerokość kafelka wynika z TYPU (rozstrzygnięcie 2 planu). Szablon
        # dostaje ją gotową, zamiast importować katalog — Jinja nie ma po co
        # znać dataclassy.
        'szerokosci': {klucz: typ.szerokosc for klucz, typ in KATALOG.items()},
        # Nazwy typów z katalogu (te same, co w oknie „Dodaj statystykę").
        # Szablon bierze z nich nazwę dostępną kafelka, który nie ma
        # widocznego tytułu (KPI) — patrz makro `nazwa_kafelka`.
        'nazwy_typow': {klucz: typ.nazwa for klucz, typ in KATALOG.items()},
        # Jednostki wypisuje SZABLON, z tego samego rejestru, z którego
        # bierze je payload — nagłówek kolumny stoi w szkielecie od pierwszej
        # klatki, zanim przyjdą dane (spec 6.2).
        'jednostki': JEDNOSTKI_MIAR,
        # Nazwy miar („Netto", „Sztuki") — z tego samego rejestru, co dymki
        # wykresów w payloadzie. Szablon podpisuje nimi kolumny i legendy
        # wariantów przełącznika „zł / szt. / zł + szt." (24.09.2026), zamiast
        # wpisywać drugi raz te same słowa.
        'etykiety_miar': ETYKIETY_MIAR,
        'naglowki_kolumn': naglowki_kolumn_kart(),
        # Przekrój wyjść kafelków BEZ wymiaru (KPI, Statystyki, Lejek) do
        # Eksploratora. Dawniej brały wymiar karty kanałów, ale od Planu D tej
        # karty może być kilka albo wcale — więc wyjście niesie domyślny wymiar
        # kanałów Z KATALOGU, a nie napis wpisany sześć razy w szablon.
        'wymiar_kanalu_domyslny': KATALOG['kanal'].domyslny_wymiar,
        # Wymiar wyjścia karty kubełkowej: jej własny, a przy kubełkach
        # (pseudo-wymiar, którego Eksplorator nie zna) — pierwszy z katalogu.
        'wymiar_wyjscia_kubelkowej': wymiar_wyjscia_karty_kubelkowej,
        # Wymiar, przy którym karta wykończeń ma podsekcję „Cena za m³
        # z wykończeniem" — ta sama stała, która decyduje o liczeniu jej.
        'wymiar_wykonczenia': WYMIAR_WYKONCZENIA,
        # Opcje przełącznika „zł / szt. / zł + szt." dla (typ, wymiar) albo
        # None (24.09.2026). TA SAMA funkcja, z której powstaje klucz
        # `przelaczniki` payloadu — przełącznik narysowany przez serwer
        # w nagłówku kafelka i dane, którymi przeglądarka go obsługuje, mają
        # jedno źródło. Sam kontekst niczego nie rysuje; znaczniki dokłada
        # szablon kafelka.
        'opcje_przelacznika': opcje_przelacznika,
        'od': od, 'do': do,
        # Wykluczenia pozycji (partia E, punkt E4) jako zwykły filtr — tak
        # rozumie je Eksplorator, do którego prowadzą stopki kafelków. None,
        # gdy wykluczeń nie ma: `url_for` pomija wtedy parametr w ogóle.
        'filtr_wyjsc': filtr_wyjsc or None,
    }


def _filtr_wyjsc(wykluczenia, obecne) -> str:
    """Wykluczenia jako napis filtra w adresie wyjść do Eksploratora."""
    return zapisz_filtr(filtr_z_wykluczen(wykluczenia, obecne or {}))


@reports_bp.route('/analiza')
@require_module_access('reports')
def analiza():
    """Pulpit Analizy sprzedażowej.

    Szkielet renderuje się po stronie serwera Z UKŁADU UŻYTKOWNIKA, dane
    dociąga `analiza.js` jednym żądaniem do `/reports/api/analytics`.

    Zły parametr w adresie NIE jest tu błędem: nieaktualna zakładka ma pokazać
    pulpit za bieżący miesiąc, a nie stronę błędu. Dotyczy to także parametrów
    `?kanal=`, `?opiekun=` itd., którymi do 23.09.2026 sterowało się wymiarem
    karty — dziś wymiar jest częścią ZAPISANEGO układu, a nie adresu, więc te
    parametry są po prostu ignorowane.
    """
    try:
        od, do = parsuj_okres(request.args)
    except ValueError:
        od, do = parsuj_okres({})
    # Zły filtr w adresie nie jest tu błędem: nieaktualna zakładka ma pokazać
    # dashboard bez segmentu, a nie stronę błędu. Twarda walidacja zostaje
    # na API, gdzie konsumentem jest kod.
    try:
        porownanie = parsuj_filtr(request.args.get('porownanie'))
    except ValueError:
        porownanie = None
    # Pola wyboru rysuje serwer z wartości OBECNYCH W DANYCH, więc bazę pytamy
    # zawsze — także bez parametru. Zły parametr jest ignorowany (patrz
    # `_wykluczenia_z_adresu`).
    wykluczenia, obecne = _wykluczenia_z_adresu(request.args, surowo=False)
    if obecne is None:
        obecne = wartosci_wykluczen()
    stan_wykluczen = blok_wykluczen(wykluczenia, filtr_z_wykluczen(wykluczenia, obecne))

    uklad, pominietych = uklad_uzytkownika(_zalogowany())

    return render_template(
        'analiza/dashboard.html',
        uklad=uklad,
        # Katalog do modalu „Dodaj statystykę". ensure_ascii=False, bo
        # `app.config['JSON_AS_ASCII']` we Flasku 2.0.3 jest domyślnie True
        # i „Sprzedaż netto" wyszłaby w źródle jako ż — ta sama poprawka,
        # co przy `kolumny_wszystkie` w trasie arkusza.
        katalog_json=json.dumps(katalog_do_json(), ensure_ascii=False),
        # Układ ZAPISANY, czyli punkt odniesienia licznika zmian w trybie
        # edycji (przegląd gałęzi, W1). Ta sama postać, co w kolumnie bazy.
        uklad_zapisany_json=json.dumps(uklad_do_json(uklad), ensure_ascii=False),
        maks_kafelkow=MAKS_KAFELKOW,
        pominietych=pominietych,
        wymiary_filtra=[{'nazwa': n, 'etykieta': POLA[n].etykieta} for n in wymiary_proste()],
        okres_klucz=nazwa_zakresu(od, do),
        okres_opis=opis_okresu(od, do),
        porownanie=zapisz_filtr(porownanie),
        # Wykluczenia pozycji: pola wyboru, znormalizowany parametr adresu
        # (punkt startu stanu w analiza.js) i napisy pierwszej klatki — te same,
        # które potem przychodzą w payloadzie.
        pola_wykluczen=pola_wykluczen(wykluczenia, obecne),
        wyklucz=stan_wykluczen['tekst'],
        wykluczenia=stan_wykluczen,
        nazwa_segmentu_bazy=stan_wykluczen['opis'] or NAZWA_SEGMENTU_BAZY,
        komunikat_ostatniej_wartosci=KOMUNIKAT_OSTATNIEJ_WARTOSCI,
        **_kontekst_kafelkow(od, do, stan_wykluczen['filtr']),
    )


# Odpowiedź dla sesji, za którą nie stoi już żaden użytkownik w bazie (konto
# usunięte po zalogowaniu). Dekorator sprawdza to samo, ale wcześniej, więc
# to jest okno wyścigu, a nie ścieżka codzienna. Ten sam kod błędu, co przy
# braku sesji w dekoratorze — przeglądarka ma JEDNĄ obsługę „wygasłej sesji".
#
# Treść jest NEUTRALNA wobec akcji, bo wspólna dla obu endpointów: zapisu
# układu i przywrócenia domyślnego — a przywrócenie to nie zapis.
_BEZ_UZYTKOWNIKA = {'error': 'unauthorized',
                    'komunikat': 'Sesja wygasła — zaloguj się ponownie, '
                                 'żeby zmienić układ pulpitu.'}

# Odpowiedź na żądanie zmieniające układ, które nie jest JSON-em (patrz
# `api_uklad_domyslny`). Przeglądarka użytkownika tego nie zobaczy — analiza.js
# zawsze wysyła JSON — więc komunikat mówi wprost, czego brakuje.
_TYLKO_JSON = {'error': 'zle_zadanie',
               'komunikat': 'Żądanie zmiany układu musi być wysłane jako JSON '
                            '(nagłówek Content-Type: application/json).'}


def _instancja_z_adresu(argumenty):
    """Instancja kafelka z parametrów zapytania. Rzuca `BladUkladu` PO POLSKU.

    Walidacja jest DOSŁOWNIE tą samą, co przy zapisie układu — parametry
    składamy w jednopozycyjny układ i puszczamy przez `uklad.parsuj_uklad`.
    Druga, równoległa kopia reguł rozjechałaby się z pierwszą przy pierwszej
    zmianie katalogu, a endpoint jest osiągalny dla każdego, kto ma dostęp do
    modułu: `getattr(SalesOrder, nazwa)` na wymiarze spoza listy kończy się
    pięćsetką. Z tego samego źródła bierze się też reguła, że karta należności
    przyjmuje wyłącznie kolumny poziomu ZAMÓWIENIA (saldo żyje na zamówieniu,
    więc join z pozycjami zwielokrotniłby je przez ich liczbę) i że wartość
    z adresu trafia do komunikatu co najwyżej ucięta.
    """
    pozycja = {'typ': argumenty.get('typ'), 'wymiar': argumenty.get('wymiar') or None}
    return parsuj_uklad({'uklad': [pozycja]})[0]


@reports_bp.route('/api/kafelek')
@require_module_access('reports', as_json=True)
def api_kafelek():
    """Jeden kafelek: gotowy szkielet z serwera plus jego dane.

    Istnieje po to, żeby zmiana wymiaru, dodanie kafelka i anulowanie edycji
    działały BEZ przeładowania strony, a mimo to znaczniki kafelków nadal
    generował serwer. Gdyby budował je JavaScript, powstałoby drugie źródło
    prawdy o wyglądzie całego pulpitu.

    `html` to CZYSTY SZKIELET — zero danych. Wszystkie wartości (w tym wolny
    tekst z BaseLinkera) wchodzą dopiero w kroku rysowania, przez textContent,
    dokładnie tak jak przy pełnym ładowaniu strony.

    JEDEN kafelek na żądanie. Nie da się tym endpointem poprosić o listę, więc
    limit dwudziestu kafelków zostaje nietknięty. Układu użytkownika endpoint
    NIE czyta i niczego nie zapisuje — to jest podgląd, nie zapis.
    """
    try:
        od, do = parsuj_okres(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zly_okres', 'komunikat': str(blad)}), 400
    try:
        instancja = _instancja_z_adresu(request.args)
    except BladUkladu as blad:
        return jsonify({'error': 'zly_kafelek', 'komunikat': str(blad)}), 400
    try:
        porownanie = parsuj_filtr(request.args.get('porownanie'))
    except ValueError as blad:
        return jsonify({'error': 'zly_filtr', 'komunikat': str(blad)}), 400
    try:
        wykluczenia, obecne = _wykluczenia_z_adresu(request.args)
    except ValueError as blad:
        return _blad_wykluczen(blad)

    return jsonify({
        'klucz': instancja.klucz,
        'html': render_template('analiza/_kafelek_jeden.html', inst=instancja,
                                **_kontekst_kafelkow(od, do,
                                                     _filtr_wyjsc(wykluczenia, obecne))),
        'dane': do_json(dane_dashboardu(od, do, [instancja], porownanie=porownanie,
                                        wykluczenia=wykluczenia, obecne=obecne)),
    })


@reports_bp.route('/api/siatka')
@require_module_access('reports', as_json=True)
def api_siatka():
    """Cała siatka kafelków z ZAPISANEGO układu, jako gotowy szkielet.

    Wołają ją „Anuluj" i „Przywróć domyślny" (tryb edycji) — obie muszą wrócić
    do stanu zapisanego, a odtwarzanie go z kopii DOM-u w JavaScripcie byłoby
    trzecią ścieżką budowania tego samego widoku.

    `html` to wynik `_siatka.html` — TEGO SAMEGO pliku, który włącza strona,
    razem z opakowaniem `<div class="an-siatka" id="an-siatka">`. Przeglądarka
    podmienia więc cały węzeł siatki, a nie jego zawartość.

    Kafelka „+ Dodaj statystykę" tu NIE MA: należy do trybu edycji i dokłada
    go strona. Inaczej po anulowaniu edycji w siatce byłyby dwa.
    """
    try:
        od, do = parsuj_okres(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zly_okres', 'komunikat': str(blad)}), 400
    # Siatka to sam szkielet, ale jej stopki prowadzą do Eksploratora —
    # z wykluczeniami, jeśli są (partia E, punkt E4).
    try:
        wykluczenia, obecne = _wykluczenia_z_adresu(request.args)
    except ValueError as blad:
        return _blad_wykluczen(blad)
    uklad, pominietych = uklad_uzytkownika(_zalogowany())
    return jsonify({
        'html': render_template('analiza/_siatka.html', uklad=uklad,
                                **_kontekst_kafelkow(od, do,
                                                     _filtr_wyjsc(wykluczenia, obecne))),
        'pominietych': pominietych,
        # Nowy punkt odniesienia licznika zmian — po „Odrzuć" i „Przywróć
        # domyślny" zapisany jest dokładnie ten układ, a nie to, co było na
        # ekranie przed chwilą (przegląd gałęzi, W1).
        'uklad': uklad_do_json(uklad),
    })


@reports_bp.route('/api/uklad', methods=['POST'])
@require_module_access('reports', as_json=True)
def api_uklad_zapisz():
    """Zapis prywatnego układu pulpitu.

    Układ jest WYŁĄCZNIE prywatny (rozstrzygnięcie 3 planu), więc bramka jest
    ta sama, co do samej zakładki — nie ma tu czego dzielić na role. Nikt nie
    zapisuje cudzego układu: użytkownik bierze się z SESJI, nie z ciała żądania.

    Kolejność jest celowa: najpierw walidacja, potem użytkownik, na końcu
    zapis. Zły układ odbija się, zanim cokolwiek dotknie bazy.
    """
    try:
        nowy = parsuj_uklad(request.get_json(silent=True))
    except BladUkladu as blad:
        return jsonify({'error': 'zly_uklad', 'komunikat': str(blad)}), 400

    uzytkownik = _zalogowany()
    if uzytkownik is None:
        return jsonify(_BEZ_UZYTKOWNIKA), 401

    zapisz_uklad(uzytkownik, nowy)
    # `uklad` = to, co serwer NAPRAWDĘ zapisał (po walidacji). Przeglądarka
    # bierze z tego nowy punkt odniesienia licznika zmian, a nie z ekranu.
    return jsonify({'zapisano': True, 'kafelkow': len(nowy),
                    'uklad': uklad_do_json(nowy)})


@reports_bp.route('/api/uklad/domyslny', methods=['POST'])
@require_module_access('reports', as_json=True)
def api_uklad_domyslny():
    """Przywrócenie układu domyślnego = SKASOWANIE wiersza.

    Nie zapisujemy w nim dzisiejszej listy domyślnej: zapisana kopia zamroziłaby
    użytkownikowi układ z dnia kliknięcia, a przyszła zmiana układu domyślnego
    już by go nie dosięgła.

    WYMAGAMY JSON-a, choć ciało nic nie niesie (przegląd gałęzi, D4). Żądanie
    bez ciała da się wysłać zwykłym formularzem z obcej strony, a ciasteczko
    `remember_token` nie ma ustawionego SameSite — w przeglądarce, która nie
    traktuje jego braku jak Lax, cudza strona mogłaby skasować komuś prywatny
    układ. `Content-Type: application/json` formularz nie ustawi bez zapytania
    wstępnego CORS, na które ten serwer nie odpowiada zgodą. analiza.js
    wysyła `{}` z tym nagłówkiem.
    """
    if not request.is_json:
        return jsonify(_TYLKO_JSON), 400
    uzytkownik = _zalogowany()
    if uzytkownik is None:
        return jsonify(_BEZ_UZYTKOWNIKA), 401
    przywrocono = przywroc_domyslny(uzytkownik)
    # `uklad` = to, co serwer OD TERAZ podaje (odczyt po skasowaniu wiersza,
    # ta sama droga co /api/siatka). Przeglądarka bierze z tego punkt
    # odniesienia licznika zmian od razu — nie czeka na siatkę, która może
    # nie przyjść (502 w trakcie restartu). Bez tego ekran i serwer
    # rozjeżdżały się, a „Zapisz układ" nic nie wysyłał (weryfikacja
    # poprawek, znalezisko 2).
    uklad, _ = uklad_uzytkownika(uzytkownik)
    return jsonify({'przywrocono': przywrocono, 'uklad': uklad_do_json(uklad)})


def _zalogowany():
    """Zalogowany użytkownik albo None. Dekorator już sprawdził, że jest."""
    from modules.users.models import User
    email = session.get('user_email')
    return User.query.filter_by(email=email).first() if email else None


@reports_bp.route('/arkusz')
@require_module_access('reports')
def arkusz():
    """Arkusz wewnętrzny — pełne okno, bez sidebara.

    Zły parametr w adresie NIE jest tu błędem: nieaktualna zakładka
    w przeglądarce ma pokazać arkusz za bieżący miesiąc, a nie stronę błędu.
    Twarda walidacja zostaje na `/api/arkusz/dane`, gdzie konsumentem jest
    kod. Ta sama zasada, co na trasach dashboardu i Eksploratora.
    """
    try:
        od, do, preset = parsuj_okno(request.args)
    except ValueError:
        od, do, preset = parsuj_okno({})
    try:
        wybrane = kolumny_z_adresu(request.args.get('kolumny'))
    except ValueError:
        wybrane = kolumny_z_adresu(None)

    wszystkie = kolumny_arkusza()

    return render_template(
        'analiza/arkusz.html',
        okno={'od': od.isoformat(), 'do': do.isoformat(), 'preset': preset},
        etykieta_okna=etykieta_okna(od, do, preset),
        # ODCHYLENIE od briefu: przekazujemy JUZ ZSERIALIZOWANY napis JSON,
        # nie surowa liste. Domyslny filtr Jinjy `|tojson` szanuje
        # `app.config['JSON_AS_ASCII']`, ktore we Flasku 2.0.3 domyslnie
        # jest `True` — etykiety typu „Zapłacono Łoza" wyszlyby w zrodle
        # strony jako `Zapłacono Łoza`. Okienko „Kolumny"
        # (Zadanie 8) dostaloby poprawny JSON po stronie JS (JSON.parse
        # rozumie `\uXXXX`), ale test strukturalny na zrodle HTML i tak
        # ma prawo oczekiwac czytelnego polskiego tekstu. `json.dumps(...,
        # ensure_ascii=False)` daje UTF-8 wprost; apostrof/cudzyslow w
        # wartosci i tak ucieka domyslny autoescaping Jinjy przy wstawieniu
        # w atrybut '...', wiec `|safe` nie jest potrzebne.
        kolumny_wszystkie=json.dumps(wszystkie, ensure_ascii=False),
        kolumny_wybrane=wybrane,
        # Ten sam zestaw wymiarow, co w popoverze filtra na dashboardzie
        # i w Eksploratorze. Wymiary zlozone sa z niego wykluczone — ich
        # wartosc to krotka kolumn i nie przechodzi przez format filtra.
        # Ta sama poprawka ensure_ascii=False co wyzej — „Województwo",
        # „Kanał sprzedaży" itd. maja polskie znaki.
        wymiary_filtra=json.dumps(
            [{'nazwa': n, 'etykieta': POLA[n].etykieta} for n in wymiary_proste()],
            ensure_ascii=False),
        # Licznik sklada serwer, zeby szablon nie liczyl niczego sam.
        licznik_kolumn='{}/{}'.format(len(wybrane), len(wszystkie)),
        moze_wysylac=moze_wysylac_do_bl(_zalogowany()),
    )


@reports_bp.route('/eksplorator')
@require_module_access('reports')
def eksplorator():
    """Jedno wyjście ze wszystkich kart dashboardu.

    Parametry idą z adresu, żeby widok dało się zapisać w zakładkach
    (spec §6.3). Zły parametr nie jest tu błędem — wracamy do domyślnego,
    tak samo jak na dashboardzie.
    """
    try:
        od, do = parsuj_okres(request.args)
    except ValueError:
        od, do = parsuj_okres({})

    dozwolone = set(wymiary())
    wymiar = request.args.get('wymiar')
    if wymiar not in dozwolone:
        wymiar = 'order_source'
    kolumny = request.args.get('przestawienie')
    if kolumny != PRZESTAWIENIE_MIESIAC and kolumny not in dozwolone:
        kolumny = PRZESTAWIENIE_MIESIAC
    miara = request.args.get('miara')
    if miara not in MIARY_PRZESTAWIENIA:
        miara = 'netto'
    # Zły filtr w adresie nie jest tu błędem — tak samo jak zły wymiar.
    try:
        filtr = parsuj_filtr(request.args.get('filtr'))
    except ValueError:
        filtr = None

    return render_template(
        'analiza/eksplorator.html',
        od=od, do=do, wymiar=wymiar, kolumny=kolumny, miara=miara,
        # Ten sam opis, co odda /api/eksplorator i co pokazuje chip segmentu
        # na dashboardzie — z etykietami po polsku, nie z kodami BaseLinkera.
        filtr_tekst=zapisz_filtr(filtr), filtr_opis=opis_z_etykietami(filtr),
        wymiary_filtra=[{'nazwa': n, 'etykieta': POLA[n].etykieta}
                        for n in wymiary_proste()],
        etykieta_wymiaru=POLA[wymiar].etykieta,
        etykieta_kolumn='miesiąc' if kolumny == PRZESTAWIENIE_MIESIAC
                        else POLA[kolumny].etykieta,
        os_czasowa=kolumny == PRZESTAWIENIE_MIESIAC,
        wymiary_dostepne=[{'nazwa': n, 'etykieta': POLA[n].etykieta} for n in wymiary()],
        # Nazwa miary i jej jednostka OSOBNO: szablon stawia jednostkę
        # w osobnym, wyciszonym elemencie, żeby nagłówek dało się przeczytać
        # jako „Śr. zamówienie" plus „zł", a nie jako jeden ciąg.
        miary_przestawienia=[{'nazwa': m, 'etykieta': ETYKIETY_MIAR[m],
                              'jednostka': JEDNOSTKI_MIAR[m]}
                             for m in MIARY_PRZESTAWIENIA],
        miary_panelu=[{'nazwa': m, 'etykieta': ETYKIETY_MIAR[m],
                       'jednostka': JEDNOSTKI_MIAR[m]} for m in MIARY_PANELU],
        etykieta_miary=etykieta_z_jednostka(miara),
    )


@reports_bp.route('/api/eksplorator')
@require_module_access('reports', as_json=True)
def api_eksplorator():
    """Panel miar i panel przestawienia dla jednego wymiaru."""
    try:
        od, do = parsuj_okres(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zly_okres', 'komunikat': str(blad)}), 400

    wymiar = request.args.get('wymiar') or 'order_source'
    kolumny = request.args.get('przestawienie') or PRZESTAWIENIE_MIESIAC
    miara = request.args.get('miara') or 'netto'

    dozwolone = set(wymiary())
    if wymiar not in dozwolone:
        return jsonify({'error': 'zly_wymiar',
                        'komunikat': f"'{wymiar}' nie jest wymiarem w rejestrze pól"}), 400
    if kolumny != PRZESTAWIENIE_MIESIAC and kolumny not in dozwolone:
        return jsonify({'error': 'zle_przestawienie',
                        'komunikat': f"'{kolumny}' nie nadaje się na kolumny"}), 400
    if miara not in MIARY_PRZESTAWIENIA:
        return jsonify({'error': 'zla_miara',
                        'komunikat': f"'{miara}' nie jest miarą przestawienia"}), 400

    try:
        filtr = parsuj_filtr(request.args.get('filtr'))
    except ValueError as blad:
        return jsonify({'error': 'zly_filtr', 'komunikat': str(blad)}), 400

    return jsonify(do_json(
        dane_eksploratora(wymiar, kolumny, miara, od, do, filtr=filtr)))


def _stronicowanie(argumenty):
    """(offset, limit) przycięte do sensownego zakresu. NIGDY nie rzuca.

    Zły `offset` albo `limit` w adresie to nieaktualna zakładka, a nie
    intencja użytkownika — przycinamy po cichu, zamiast wyświetlać błąd.
    Twarda walidacja zostaje na oknie dat i na liście kolumn, czyli tam,
    gdzie zła wartość zmienia WYNIK, a nie tylko jego kawałek.
    """
    def _liczba(nazwa, domyslna):
        try:
            return int(argumenty.get(nazwa, domyslna))
        except (TypeError, ValueError):
            return domyslna

    # Górna granica jest tak samo konieczna jak dolna: Python `int` jest
    # nieograniczony, więc `?offset=` z dziesiątkami cyfr trafiłoby wprost do
    # `LIMIT ..., ...` i MySQL odrzuciłby całe zapytanie błędem 1064 (poza
    # zakresem BIGINT) — SQLite tego nie łapie, więc testy na nim są ślepe.
    # 10**9 to daleko więcej niż jakiekolwiek sensowne stronicowanie kiedykolwiek
    # osiągnie, a mieści się bez problemu w BIGINT.
    offset = min(10**9, max(0, _liczba('offset', 0)))
    limit = min(MAKS_LIMIT, max(1, _liczba('limit', DOMYSLNY_LIMIT)))
    return offset, limit


@reports_bp.route('/api/arkusz/dane')
@require_module_access('reports', as_json=True)
def api_arkusz_dane():
    """Dane jednego ekranu arkusza: kolumny, okno, zamówienia, podsumowanie."""
    try:
        od, do, preset = parsuj_okno(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zle_okno', 'komunikat': str(blad)}), 400

    try:
        filtr = parsuj_filtr(request.args.get('filtr'))
    except ValueError as blad:
        return jsonify({'error': 'zly_filtr', 'komunikat': str(blad)}), 400

    try:
        kolumny = kolumny_z_adresu(request.args.get('kolumny'))
    except ValueError as blad:
        return jsonify({'error': 'zla_kolumna', 'komunikat': str(blad)}), 400

    offset, limit = _stronicowanie(request.args)

    return jsonify(do_json(dane_arkusza(
        od, do, preset=preset, kolumny=kolumny,
        szukaj=request.args.get('szukaj'), filtr=filtr,
        offset=offset, limit=limit)))


@reports_bp.route('/api/arkusz/zapisz', methods=['POST'])
@require_module_access('reports', as_json=True)
def api_arkusz_zapisz():
    """Zapis zmian z arkusza. Kolumny CRM lokalnie, kolumny BL przez API."""
    from .arkusz_zapis import BladWalidacji, parsuj_zmiany, zapisz
    from .bl_zapis import klient_z_konfiguracji

    try:
        zmiany = parsuj_zmiany(request.get_json(silent=True))
    except BladWalidacji as blad:
        return jsonify({'error': 'zle_zmiany', 'komunikat': str(blad)}), 400

    return jsonify(do_json(zapisz(zmiany, _zalogowany(),
                                  klient_bl=klient_z_konfiguracji())))


@reports_bp.route('/api/arkusz/potwierdzenie', methods=['POST'])
@require_module_access('reports', as_json=True)
def api_arkusz_potwierdzenie():
    """Podgląd tego, co NAPRAWDĘ poleci do BaseLinkera — spec §5.3 punkt 1.

    Osobne wywołanie od zapisu: dialog potwierdzenia musi pokazać się PRZED
    wysłaniem zmian (`api_arkusz_zapisz`), więc nie może czekać na jego
    wynik. Przyjmuje dokładnie to samo ciało („zmiany") i przechodzi przez tę
    samą walidację (`parsuj_zmiany`) — różni się tym, co robi z wynikiem:
    `pozycje_potwierdzenia` NIC nie zapisuje, tylko liczy ładunek, ŁĄCZNIE
    z polami DOROZUMIANYMI, których zaznaczone komórki same nie niosą
    (`setOrderPayment` podmienia całą płatność naraz — patrz docstring
    `arkusz_zapis.pozycje_potwierdzenia`).
    """
    from .arkusz_zapis import BladWalidacji, parsuj_zmiany, pozycje_potwierdzenia

    try:
        zmiany = parsuj_zmiany(request.get_json(silent=True))
    except BladWalidacji as blad:
        return jsonify({'error': 'zle_zmiany', 'komunikat': str(blad)}), 400

    return jsonify({'pozycje': do_json(pozycje_potwierdzenia(zmiany))})


@reports_bp.route('/api/arkusz/eksport')
@require_module_access('reports', as_json=True)
def api_arkusz_eksport():
    """Eksport widoku arkusza do CSV — dokładnie to, co widać na ekranie."""
    import csv
    import io

    from flask import Response

    try:
        od, do, _ = parsuj_okno(request.args)
    except ValueError as blad:
        return jsonify({'error': 'zle_okno', 'komunikat': str(blad)}), 400
    try:
        filtr = parsuj_filtr(request.args.get('filtr'))
    except ValueError as blad:
        return jsonify({'error': 'zly_filtr', 'komunikat': str(blad)}), 400
    try:
        kolumny = kolumny_z_adresu(request.args.get('kolumny'))
    except ValueError as blad:
        return jsonify({'error': 'zla_kolumna', 'komunikat': str(blad)}), 400

    bufor = io.StringIO()
    # BOM i średnik: Excel po polsku inaczej rozjeżdża kolumny i kaleczy
    # polskie znaki. Ta sama konwencja, co w eksporcie Eksploratora.
    bufor.write('﻿')
    zapis = csv.writer(bufor, delimiter=';', lineterminator='\n')
    for wiersz in wiersze_eksportu(od, do, kolumny=kolumny,
                                   szukaj=request.args.get('szukaj'), filtr=filtr):
        zapis.writerow(wiersz)

    nazwa = f'arkusz_sprzedazy_{od.isoformat()}_{do.isoformat()}.csv'
    return Response(bufor.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename="{nazwa}"'})


def _okno_pobierania(dane):
    """Zakres dat do pobrania z BaseLinkera. Rzuca ValueError z komunikatem PO POLSKU.

    Walidacja jest tu rozpisana na sześć osobnych warunków celowo. Przegląd
    Planu B znalazł trzy błędy dające 500 i wszystkie trzy były w walidacji
    wejścia: niesparsowana data trafiająca do SQL-a, pusta wartość i brak
    dolnej granicy zakresu.
    """
    if not isinstance(dane, dict):
        raise ValueError('podaj zakres dat: pola „od" i „do" w formacie RRRR-MM-DD')
    if not dane.get('od') or not dane.get('do'):
        raise ValueError('podaj zakres dat: pola „od" i „do" w formacie RRRR-MM-DD')

    od = _parsuj_date(dane.get('od'), None)
    do = _parsuj_date(dane.get('do'), None)

    if od > do:
        raise ValueError('początek zakresu jest późniejszy niż koniec')
    if od < _NAJWCZESNIEJSZA_DATA:
        raise ValueError('początek zakresu jest wcześniejszy niż '
                         f'{_NAJWCZESNIEJSZA_DATA.isoformat()}')
    if do > dzis_lokalnie():
        raise ValueError('koniec zakresu jest w przyszłości')
    if (do - od).days + 1 > MAKS_DNI_POBIERANIA:
        raise ValueError(f'zakres dłuższy niż {MAKS_DNI_POBIERANIA} dni — '
                         'BaseLinker nie udostępnia starszych zamówień przez API, '
                         'bo trafiają do archiwum')
    return od, do


@reports_bp.route('/api/arkusz/pobierz', methods=['POST'])
@require_module_access('reports', as_json=True)
def api_arkusz_pobierz():
    """Pobranie zamówień z BaseLinkera wyłącznie do analityki.

    Decyzja użytkownika 22.09.2026: „Pobieranie tutaj = zapis tylko do
    analityki". Ten endpoint NIE dotyka ani modułu produkcji, ani starej
    tabeli `baselinker_reports_orders` — pisze wyłącznie do `sales_*`.
    """
    try:
        od, do = _okno_pobierania(request.get_json(silent=True) or {})
    except ValueError as blad:
        return jsonify({'error': 'zly_zakres', 'komunikat': str(blad)}), 400

    pobranie = get_reports_service().fetch_orders_from_date_range(
        datetime.combine(od, time.min),
        datetime.combine(do, time.max),
        get_all_statuses=False,
    )
    if not pobranie.get('success'):
        # 502, nie 500: to nie my się wywaliliśmy, tylko usługa zewnętrzna.
        # Front rozróżnia te dwa przypadki w komunikacie dla użytkownika.
        return jsonify({'error': 'blad_baselinkera',
                        'komunikat': pobranie.get('error')
                                     or 'BaseLinker nie odpowiedział'}), 502

    zamowienia = pobranie.get('orders') or []
    return jsonify({
        'pobranych': len(zamowienia),
        'zapis': do_json(zapisz_zamowienia(zamowienia, zrodlo='analiza')),
        'od': od.isoformat(),
        'do': do.isoformat(),
    })
