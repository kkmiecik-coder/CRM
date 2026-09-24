# -*- coding: utf-8 -*-
"""Agregaty dashboardu Analizy sprzedażowej.

Uzupełnienie `aggregates.py` o liczby, których tamten moduł nie dostarcza:
szereg miesięczny pod wykres trendu, kubełki klientów, konwersję lead -> klient,
lejek wycen, ostrzeżenie o wiarygodności salda i sumę kosztu kuriera.

DLACZEGO OSOBNY PLIK, A NIE DOPISKI DO aggregates.py
====================================================
`aggregates.py` jest dorobkiem Planu A i ma własny komplet testów. Dokładanie
do niego funkcji potrzebnych wyłącznie dashboardowi mieszałoby dwa cykle życia.
Tutaj importujemy stamtąd to, co musi być wspólne — listę grup bez objętości
i konwersję na Decimal — zamiast je przepisywać. Przepisana lista wykluczeń to
dokładnie ta klasa błędu, którą Plan A zamknął.

DIALEKT SQL
===========
Grupowanie po miesiącu idzie przez `db.extract('year'|'month', kolumna)`.
SQLAlchemy 1.4 kompiluje to do `EXTRACT(year FROM x)` na MySQL-u i do
`CAST(STRFTIME('%Y', x) AS INTEGER)` na SQLite, więc jeden zapis działa
i w teście, i na produkcji. Testy jadą na SQLite, więc MySQL-a nie sprawdzają —
weryfikacja na kontenerze `db` jest osobnym krokiem planu.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from extensions import db
# Świadomie importujemy nazwy prywatne z aggregates: lista grup wykluczonych
# z objętości MUSI być jedna dla całego modułu. Duplikat oznaczałby, że dodanie
# nowej grupy usługowej poprawia KPI, a psuje wykres trendu.
from modules.reports.aggregates import (
    _GRUPY_BEZ_OBJETOSCI, _sztuki, _zero, sztuki_bez_uslug,
)
from modules.reports.filters import (
    warunek_sprzedazy, warunki_pozycji, warunki_zamowienia,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
# Nazwy województw normalizuje JEDNA klasa w całym module — ta sama, której
# używa import z BaseLinkera (`ingest.py`) i stara zakładka (`service.py`).
# Druga mapa nazw znaczyłaby, że mapa na dashboardzie potrafi nie rozpoznać
# województwa, które import właśnie zapisał.
from modules.reports.utils import PostcodeToStateMapper

# Kolejność kubełków jest stała i wynika z makiety, nie z danych.
_KUBELKI_KLIENTOW: Tuple[Tuple[str, int, int], ...] = (
    ('1 zam.', 1, 1),
    ('2–3', 2, 3),
    ('4–9', 4, 9),
    ('10+', 10, 1000000),
)

# Zamówienie starsze niż tyle dni z dodatnim saldem trafia do ostrzeżenia.
_PROG_STAREGO_SALDA_DNI = 90

# Nazwy miesięcy mieszkają TUTAJ, bo to najniższa warstwa, którą importują
# i serwis dashboardu, i Eksplorator. Dwie kopie tej krotki znaczyłyby, że
# wykres i przestawienie mogą kiedyś podpisać ten sam miesiąc inaczej.
MIESIACE_SKROT: Tuple[str, ...] = (
    'STY', 'LUT', 'MAR', 'KWI', 'MAJ', 'CZE',
    'LIP', 'SIE', 'WRZ', 'PAŹ', 'LIS', 'GRU',
)
MIESIACE_MALE: Tuple[str, ...] = (
    'sty', 'lut', 'mar', 'kwi', 'maj', 'cze',
    'lip', 'sie', 'wrz', 'paź', 'lis', 'gru',
)


def _objetosc_bez_uslug():
    """Suma objętości z pominięciem pozycji usługowych (np. suszenia)."""
    return db.func.sum(
        db.case(
            (SalesOrderItem.group_type.in_(_GRUPY_BEZ_OBJETOSCI), 0),
            else_=SalesOrderItem.total_volume,
        )
    )


def kolejne_miesiace(od: date, do: date) -> List[Tuple[int, int]]:
    """Wszystkie pary (rok, miesiąc) od `od` do `do` włącznie, po kolei.

    Publiczna, bo tej samej osi potrzebuje panel przestawienia (Zadanie 11).
    Oś zbudowana z danych zamiast z zakresu sklejałaby niesąsiadujące miesiące
    i pokazywała wzrost, którego nie było.
    """
    pary = []
    rok, miesiac = od.year, od.month
    while (rok, miesiac) <= (do.year, do.month):
        pary.append((rok, miesiac))
        if miesiac == 12:
            rok, miesiac = rok + 1, 1
        else:
            miesiac += 1
    return pary


def _procent(licznik: int, mianownik: int) -> Decimal:
    if not mianownik:
        return Decimal('0')
    return (Decimal(licznik) * 100 / Decimal(mianownik)).quantize(Decimal('0.1'))


def szereg_miesieczny(od: date, do: date, filtr=None) -> List[Dict[str, object]]:
    """Sprzedaż w rozbiciu na miesiące, z ciągłą osią.

    Miesiąc bez zamówień wraca jako wiersz z zerami. Dziura w osi skleiłaby
    marzec z majem i pokazała wzrost, którego nie było.

    `filtr` zawęża szereg — potrzebuje go druga seria wykresu trendu przy
    włączonym segmencie porównawczym (Zadanie 10). `filtr=None` daje dokładnie
    to samo, co przed jego wprowadzeniem.

    `sztuki` (24.09.2026) niesie słupki trybów „szt." i „zł + szt."
    przełącznika na kafelku KPI — w tym samym zapytaniu co netto.
    """
    rok = db.extract('year', SalesOrder.date_created)
    miesiac = db.extract('month', SalesOrder.date_created)

    wiersze = (
        db.session.query(
            rok.label('rok'),
            miesiac.label('miesiac'),
            db.func.sum(SalesOrderItem.value_net).label('netto'),
            _objetosc_bez_uslug().label('objetosc'),
            sztuki_bez_uslug().label('sztuki'),
            db.func.count(db.func.distinct(SalesOrder.id)).label('zamowienia'),
        )
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
        .group_by(rok, miesiac)
        .all()
    )

    znalezione = {
        (int(w.rok), int(w.miesiac)): {
            'rok': int(w.rok),
            'miesiac': int(w.miesiac),
            'netto': _zero(w.netto),
            'objetosc': _zero(w.objetosc),
            'sztuki': _sztuki(w.sztuki),
            'zamowienia': int(w.zamowienia or 0),
        }
        for w in wiersze
    }

    return [
        znalezione.get(para, {'rok': para[0], 'miesiac': para[1],
                              'netto': Decimal('0'), 'objetosc': Decimal('0'),
                              'sztuki': 0, 'zamowienia': 0})
        for para in kolejne_miesiace(od, do)
    ]


def klienci_wg_liczby_zamowien() -> List[Dict[str, object]]:
    """Kubełki klientów po liczbie zamówień w CAŁEJ historii.

    Bez parametru okresu celowo: karta odpowiada na pytanie „ilu mamy klientów
    powracających", a nie „ilu kupiło w tym miesiącu". Liczby biorą się
    z denormalizacji `orders_count` / `lifetime_net`, utrzymywanej przez backfill
    i synchronizację.

    Denormalizacja liczy WYŁĄCZNIE sprzedaż (partia E, punkt E5 — patrz
    `ingest._przelicz_klienta`): klient, którego jedyne zamówienie anulowano,
    ma `orders_count = 0` i odpada tu warunkiem `>= 1`. Zapis zamówienia
    przelicza tylko jego klienta, więc resztę przelicza
    `scripts/przelicz_klientow_sprzedazy.py`, wołany przez `deploy.sh` przy
    każdym wdrożeniu (lokalnie — ręcznie).

    SZTUKI (24.09.2026, tryb „szt." koła klientów). Denormalizacja sztuk nie
    ma, więc liczymy je z pozycji — TĄ SAMĄ definicją, którą
    `ingest.liczniki_klientow` liczy `lifetime_net`: pozycje zamówień klienta
    (`SalesOrder.client_id`) z całej historii, tylko sprzedaż (E5), bez usług
    (jak w każdej innej sumie sztuk). Kubełek wyznacza ten sam
    `orders_count`, więc oba kawałki koła mówią o tych samych klientach.
    Różnić się mogą tylko ŚWIEŻOŚCIĄ: netto jest z denormalizacji, sztuki
    z pozycji na żywo — po przeliczeniu klientów (deploy) obie strony stoją
    na tym samym stanie (sprawdzone na kopii produkcji 24.09.2026: suma
    `value_net` pozycji w kubełku == suma świeżo przeliczonego `lifetime_net`).

    KOSZT: podzapytanie przechodzi całą historię pozycji, bo kubełki są
    z całej historii — ok. 13 ms na kopii produkcji wobec 1,5 ms bez sztuk.
    Tańsze byłoby dopiero trzymanie sumy sztuk w denormalizacji klienta
    (kolumna obok `lifetime_net`, liczona w `ingest.liczniki_klientow`).

    Nadal JEDNO zapytanie: sztuki wchodzą podzapytaniem zgrupowanym po
    kliencie (jeden wiersz na klienta), dołączonym zewnętrznie. Złączenie
    wprost z pozycjami zwielokrotniłoby `lifetime_net` i liczbę klientów
    przez liczbę pozycji — ta sama pułapka co przy saldzie. Wykluczeń
    użytkownika (E4) sztuki kubełków nie dostają, tak jak nie dostaje ich
    netto kubełków — mówi o tym dopisek pod kartą.
    """
    kubelek = db.case(
        (SalesClient.orders_count <= 1, _KUBELKI_KLIENTOW[0][0]),
        (SalesClient.orders_count <= 3, _KUBELKI_KLIENTOW[1][0]),
        (SalesClient.orders_count <= 9, _KUBELKI_KLIENTOW[2][0]),
        else_=_KUBELKI_KLIENTOW[3][0],
    )
    sztuki_klienta = (
        db.session.query(SalesOrder.client_id.label('client_id'),
                         sztuki_bez_uslug().label('sztuki'))
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(SalesOrder.client_id.isnot(None), warunek_sprzedazy())
        .group_by(SalesOrder.client_id)
        .subquery()
    )

    wiersze = (
        db.session.query(
            kubelek.label('kubelek'),
            db.func.count(SalesClient.id).label('klienci'),
            db.func.sum(SalesClient.lifetime_net).label('netto'),
            db.func.sum(sztuki_klienta.c.sztuki).label('sztuki'),
        )
        .outerjoin(sztuki_klienta, sztuki_klienta.c.client_id == SalesClient.id)
        .filter(SalesClient.orders_count >= 1)
        .group_by(kubelek)
        .all()
    )

    znalezione = {w.kubelek: (int(w.klienci or 0), _zero(w.netto), _sztuki(w.sztuki))
                  for w in wiersze}
    pusty = (0, Decimal('0'), 0)
    return [
        {'kubelek': etykieta,
         'klienci': znalezione.get(etykieta, pusty)[0],
         'netto': znalezione.get(etykieta, pusty)[1],
         'sztuki': znalezione.get(etykieta, pusty)[2]}
        for etykieta, _, _ in _KUBELKI_KLIENTOW
    ]


def nowi_klienci(od: date, do: date, filtr=None) -> int:
    """Klienci, których pierwsze zamówienie wpadło w okres.

    JEDYNE źródło tej liczby w całym module — karta „Nowi w okresie" na
    dashboardzie i kolumna „Nowi klienci" w Eksploratorze (`_klienci_okresu`
    w `analiza_service.py`) wołają tę samą funkcję, zamiast liczyć osobno.

    To NIE jest samo `SELECT COUNT(*) ... WHERE first_order_at BETWEEN`:
    `sales_clients.first_order_at` to pole DENORMALIZOWANE i bywa
    rozjechane z `sales_orders` — znalezisko z produkcji 22.09.2026, klient
    „TEST Weryfikacja" miał `first_order_at` i `orders_count=1` ustawione
    ręcznie, ale ANI JEDNEGO wiersza w `sales_orders`. Samo pole liczyło go
    jako nowego (dashboard: 381), Eksplorator — bo szedł przez `SalesOrder`
    — nie (380). JOIN z `SalesOrder` jest więc częścią definicji, nie
    optymalizacją: odrzuca klienta, za którym nie stoi żadne realne
    zamówienie, niezależnie od tego, co mówi denormalizacja.

    `filtr` zawęża do zamówień pasujących do filtra (jak w Eksploratorze);
    bez niego (dashboard) liczy po całej sprzedaży.
    """
    return int(
        db.session.query(db.func.count(db.func.distinct(SalesClient.id)))
        .join(SalesOrder, SalesOrder.client_id == SalesClient.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                SalesClient.first_order_at >= od, SalesClient.first_order_at <= do,
                *warunki_zamowienia(filtr))
        .scalar() or 0
    )


def konwersja_lead_klient() -> Dict[str, object]:
    """Ilu kupujących miało wcześniej wycenę.

    UWAGA: liczymy przez DOPASOWANIE E-MAILA, nie przez `sales_clients.lead_id`.
    Spec §3.1 przewiduje tę kolumnę, ale nikt jej dziś nie zapisuje (znalezisko
    z finalnego przeglądu Planu A), więc oparta na niej karta pokazywałaby stałe
    0,0%. Zwracamy `dowiazanych_lead_id` osobno — gdy Plan C doda pisarza, obie
    liczby powinny się zejść i wtedy da się przełączyć źródło.
    """
    # Import lokalny: modules.clients sięga pośrednio do modules.reports,
    # import na poziomie modułu zamknąłby cykl.
    from modules.clients.models import Client

    # KUPUJĄCY = klient z co najmniej jednym zamówieniem, które liczy się do
    # sprzedaży (partia E, punkt E5). Klient, którego jedyne zamówienie
    # anulowano, zostaje w `sales_clients` z `orders_count = 0` — nie kupił,
    # więc nie wchodzi do mianownika. Ten sam warunek co w kubełkach
    # (`klienci_wg_liczby_zamowien`), więc mianownik konwersji równa się
    # sumie kubełków na tej samej karcie.
    kupujacy = SalesClient.orders_count >= 1

    wszyscy = int(db.session.query(db.func.count(SalesClient.id))
                  .filter(kupujacy).scalar() or 0)

    maile_leadow = (
        db.session.query(db.func.lower(db.func.trim(Client.email)))
        .filter(Client.email.isnot(None), Client.email != '')
    )
    z_leada = int(
        db.session.query(db.func.count(SalesClient.id))
        .filter(kupujacy,
                SalesClient.email_norm.isnot(None),
                SalesClient.email_norm != '',
                SalesClient.email_norm.in_(maile_leadow))
        .scalar() or 0
    )
    dowiazanych = int(
        db.session.query(db.func.count(SalesClient.id))
        .filter(kupujacy, SalesClient.lead_id.isnot(None))
        .scalar() or 0
    )

    return {'klientow': wszyscy, 'z_leada': z_leada,
            'procent': _procent(z_leada, wszyscy),
            'dowiazanych_lead_id': dowiazanych}


# --- LEJEK WYCENA -> ZAMÓWIENIE ---------------------------------------------

# Pięć stopni lejka, od najszerszego. Klucz jedzie do payloadu, etykieta
# na kartę — jedno i drugie mieszka TUTAJ, obok zapytania, które je liczy.
# Etykieta trzymana z dala od definicji stopnia to najkrótsza droga do karty,
# która podpisuje liczbę inaczej, niż ją policzyła.
STOPNIE_LEJKA: Tuple[Tuple[str, str], ...] = (
    ('utworzone', 'Wyceny utworzone'),
    ('zaakceptowane', 'Zaakceptowane'),
    ('zamowione', 'Zamówione'),
    ('oplacone', 'Opłacone'),
    ('w_realizacji', 'W realizacji'),
)

# Wymiary, w których przekroju wolno obejrzeć lejek. To NAZWY Z REJESTRU PÓL
# (fields.POLA) — etykietę dokłada z rejestru analiza_service, żeby „Opiekun"
# znaczył na tej karcie to samo, co na każdej innej.
#
# Podział MUSI dać się odczytać z SAMEJ WYCENY. Stopień pierwszy to wyceny,
# z których większość nigdy nie stała się zamówieniem, więc grupowanie po
# kolumnie `sales_orders` wrzuciłoby trzy czwarte z nich do jednego wiersza
# „(brak)". Stąd `caretaker` to autor wyceny (`quotes.user_id` -> `users`),
# a `order_source` to `quotes.source`, czyli kanał, którym przyszło zapytanie.
WYMIARY_LEJKA: Tuple[str, ...] = ('caretaker', 'order_source')

# Etykiety podziału — WŁASNE, celowo INNE niż te z rejestru pól.
#
# Rejestr podpisuje `caretaker` jako „Opiekun", a `order_source` jako „Kanał
# sprzedaży", bo opisuje kolumny ZAMÓWIENIA. Lejek grupuje po kolumnach
# WYCENY i są to inne zbiory wartości — zmierzone na produkcji 23.09.2026:
#
#   quotes.source:            OLX 1795, E-mail 1147, Telefon 941, (puste) 323,
#                             Osobiście 193, Asystent AI 70, (nazwa partnera) 63, ...
#   sales_orders.order_source: personal 1271, shop 1158, allegro 841, olx 53
#
# Jedyna nazwa, która brzmi w obu tak samo, to OLX — i tam stoi 1795 wobec 53.
# Pod wspólną etykietą „Kanał sprzedaży" ktoś zestawiłby te dwie liczby i
# wyliczyłby trzyprocentową konwersję z dwóch RÓŻNYCH wymiarów. Niezmiennik,
# na którym ten projekt potknął się już dwa razy (raz „Sklep" wobec „shop"
# w dwóch panelach Eksploratora, raz karta „Sprzedaż netto" wypisująca metry
# sześcienne), brzmi: TA SAMA ETYKIETA ZNACZY WSZĘDZIE TO SAMO. Skoro liczby
# są inne, podpis też musi być inny.
ETYKIETY_LEJKA: Dict[str, str] = {
    'caretaker': 'Autor wyceny',
    'order_source': 'Źródło wyceny',
}


def _numer_z_wyceny():
    """Numer zamówienia zapisany na wycenie, przycięty ze spacji.

    `quotes.base_linker_order_id` to VARCHAR i bywa pusty — raz jako NULL,
    raz jako '', a w teorii też jako ' '. COALESCE + TRIM robi z trzech
    przypadków jeden, więc porównanie niżej ma z czym pracować.
    """
    from modules.calculator.models import Quote
    return db.func.trim(db.func.coalesce(Quote.base_linker_order_id, ''))


def _dowiazanie_po_numerze(kolumna):
    """Złączenie wyceny z zamówieniem — PO TEKŚCIE, nie po liczbie.

    Po stronie wyceny numer jest VARCHAR-em, po stronie `sales_orders`
    i `prod_orders` liczbą. Rzutowanie napisu na liczbę wywraca się na każdej
    wartości nieliczbowej (MySQL obcina ją po cichu z ostrzeżeniem, SQLite
    daje 0 i skleja wszystkie śmieci z zamówieniem numer zero), więc rzutujemy
    w DRUGĄ stronę: liczbę na tekst. Pusty numer po stronie wyceny nie trafia
    wtedy w nic, bo żaden numer zamówienia nie jest pustym napisem.

    CAST po stronie zamówienia wyłącza indeks, ale MySQL 8 robi wtedy
    złączenie haszujące i całość kosztuje tyle co nic (zmierzone na
    produkcyjnym zrzucie: 4611 wycen wobec 3324 zamówień i 1554 zleceń
    produkcyjnych — 0,68 s wobec 0,69 s dla samego `SELECT 1`).
    NIE wolno tego zamienić na skorelowane EXISTS w liście SELECT: ta sama
    robota liczy się wtedy 4,1 s, bo MySQL wykonuje podzapytanie raz na wycenę.
    """
    return db.cast(kolumna, db.String) == _numer_z_wyceny()


def _dowiazanie_do_sprzedazy():
    """Złączenie wyceny z zamówieniem, które LICZY SIĘ do sprzedaży.

    Warunek stały z `filters.warunek_sprzedazy` siedzi w ON, nie w WHERE:
    złączenie jest zewnętrzne i wycena dowiązana do zamówienia anulowanego
    ma zostać w lejku (stopnie 1–3 opisują WYCENĘ), tylko bez odpowiednika
    w sprzedaży. Bez tego anulowane zamówienie z saldem ≤ 0 liczyło się
    w stopniu „Opłacone" (partia E, punkt E5).
    """
    return db.and_(_dowiazanie_po_numerze(SalesOrder.baselinker_order_id),
                   warunek_sprzedazy())


def _imie_i_nazwisko(imie, nazwisko) -> str:
    """Autor wyceny jako jeden napis. Sklejamy w Pythonie, nie w SQL-u.

    `CONCAT` i `||` to dwa różne zapisy w MySQL-u i w SQLite, a przy okazji
    normalizujemy tu białe znaki: w bazie siedzi imię i nazwisko z dwiema
    spacjami między nimi i bez tego byłoby osobnym wierszem karty.
    """
    return ' '.join('{} {}'.format(imie or '', nazwisko or '').split())


def _mediana(wartosci: List[int]) -> Optional[Decimal]:
    """Mediana liczona W PYTHONIE, nie w SQL-u.

    MySQL nie ma funkcji mediany, a obejście przez funkcję okna nie działa
    na SQLite, na którym jadą testy — zapytanie przechodziłoby w testach
    i wywracało się na produkcji. Próbka to najwyżej kilkaset par (wyceny
    z numerem zamówienia dowiązane do sprzedaży), więc policzenie jej
    w Pythonie nic nie kosztuje i działa identycznie na obu silnikach.
    """
    if not wartosci:
        return None
    posortowane = sorted(wartosci)
    srodek = len(posortowane) // 2
    if len(posortowane) % 2:
        surowa = Decimal(posortowane[srodek])
    else:
        surowa = (Decimal(posortowane[srodek - 1]) + Decimal(posortowane[srodek])) / 2
    return surowa.quantize(Decimal('0.1'))


def _podzial_lejka(nazwa: str, poczatek: datetime,
                   koniec: datetime) -> List[Dict[str, object]]:
    """Wyceny i zamówienia w rozbiciu na wartości jednego wymiaru.

    Zwraca PEŁNĄ listę, posortowaną malejąco po liczbie wycen — zwinięcie
    ogona w „Pozostałe (N)" należy do warstwy widoku, tak samo jak przy
    kartach wymiarowych.

    Liczba wycen jest tu równie ważna jak konwersja: handlowiec z jedną wyceną
    i jednym zamówieniem ma 100% skuteczności i bez próbki obok wyglądałby
    na najlepszego w firmie.
    """
    from modules.calculator.models import Quote
    from modules.users.models import User

    okres = (Quote.created_at >= poczatek, Quote.created_at <= koniec)
    miary = (db.func.count(Quote.id),
             db.func.sum(db.case((_numer_z_wyceny() != '', 1), else_=0)))

    if nazwa == 'caretaker':
        klucze = (User.first_name, User.last_name)
        wiersze = (
            db.session.query(*klucze, *miary)
            .select_from(Quote)
            # OUTER, nie INNER: wycena bez autora (albo z użytkownikiem,
            # którego już nie ma) ma wpaść do wiersza „(brak)", a nie zniknąć
            # z lejka — inaczej suma podziału nie zgadzałaby się ze stopniem
            # pierwszym i karta przeczyłaby sama sobie.
            .outerjoin(User, User.id == Quote.user_id)
            .filter(*okres).group_by(*klucze).all()
        )
        surowe = [(_imie_i_nazwisko(w[0], w[1]), w[2], w[3]) for w in wiersze]
    elif nazwa == 'order_source':
        wiersze = (
            db.session.query(Quote.source, *miary)
            .filter(*okres).group_by(Quote.source).all()
        )
        surowe = [(w[0], w[1], w[2]) for w in wiersze]
    else:
        raise ValueError("'{}' nie jest wymiarem podziału lejka".format(nazwa))

    # NULL i pusty napis znaczą to samo („nie wiadomo"), a w bazie żyją obok
    # siebie — bez scalenia karta pokazałaby dwa wiersze „(brak)".
    zebrane: Dict[object, List[int]] = {}
    for wartosc, wycen, zamowione in surowe:
        klucz = wartosc if wartosc not in (None, '') else None
        biezace = zebrane.setdefault(klucz, [0, 0])
        biezace[0] += int(wycen or 0)
        biezace[1] += int(zamowione or 0)

    wynik = [{'wartosc': klucz, 'wycen': liczby[0], 'zamowione': liczby[1],
              'konwersja': _procent(liczby[1], liczby[0])}
             for klucz, liczby in zebrane.items()]
    wynik.sort(key=lambda w: (-w['wycen'], str(w['wartosc'] or '')))
    return wynik


def lejek_wycen(od: date, do: date, podzialy: Tuple[str, ...] = ()) -> Dict[str, object]:
    """Pięć stopni lejka wycena -> zamówienie za okres, plus statystyki wycen.

    OKRES DOTYCZY WYCENY, NIE ZAMÓWIENIA. Wszystkie pięć stopni liczy się
    z jednego zbioru: wycen UTWORZONYCH w okresie. Stopnie 2-5 mówią więc,
    co się z nimi stało DO DZIŚ — wycena z początku miesiąca bywa opłacona
    po jego końcu. Karta musi to napisać wprost, bo inaczej czytelnik odejmie
    stopień trzeci od drugiego i zobaczy „stracone" tam, gdzie jest „jeszcze
    nierozstrzygnięte".

    Stopnie 4 i 5 NIE SĄ ZAGNIEŻDŻONE jeden w drugim: zamówienie wchodzi na
    produkcję po zaliczce, więc bywa „w realizacji" nie będąc „opłacone"
    (zmierzone na wrześniu 2026: 42 opłacone przy 55 w realizacji). Każdy
    stopień liczy się wobec stopnia PIERWSZEGO i tylko tak wolno go czytać.
    """
    from modules.calculator.models import Quote
    from modules.production.models import ProductionOrder
    from modules.reports.ingest import _jest_tabela

    # Quote.created_at to DateTime, a `do` to data — bez domknięcia do 23:59:59
    # wyceny z ostatniego dnia okresu wypadłyby z licznika.
    poczatek = datetime.combine(od, time.min)
    koniec = datetime.combine(do, time.max)
    okres = (Quote.created_at >= poczatek, Quote.created_at <= koniec)
    ma_numer = _numer_z_wyceny() != ''

    # Stopień „W realizacji" zależy od `prod_orders`, a ta tabela bywa
    # niepodłączona (moduł produkcji jeszcze nie wdrożony, testy bramki
    # uprawnień bez fixture produkcji — patrz ten sam mechanizm i to samo
    # uzasadnienie w `sprzedaz_wg_wojewodztw` niżej w tym pliku). Sprawdzamy
    # ISTNIENIE tabeli przez `_jest_tabela`, nie łapiemy wyjątku zapytania:
    # gdy `prod_orders` NA PRODUKCJI istnieje, a zapytanie padnie z innego
    # powodu, błąd ma polecieć dalej, a nie zamienić się w cichą zerową kartę.
    ma_produkcje = _jest_tabela('prod_orders')
    # Produkcja NIE dowiaduje się o anulowaniu: zlecenie w `prod_orders`
    # zostaje, a status tam stoi dalej (weryfikacja partii E, Z4 — wycena 3934
    # dowiązana do anulowanego BL 46680062 liczyła się w sierpniu 2026 jako
    # „w realizacji"). Stąd drugie złączenie z `sales_orders` — BEZ warunku
    # sprzedaży: zlecenie się nie liczy, gdy zamówienie o tym numerze JEST
    # w sprzedaży, ale poza nią (warunek E5). Zamówienie, którego w tabeli
    # sprzedaży nie ma wcale (sprzed jej zakresu), liczy się jak dotąd — nie
    # wiemy o nim nic, co by je wykluczało. `SalesOrder.id` niżej to złączenie
    # Z warunkiem sprzedaży, więc „jest w tabeli, a nie ma go w sprzedaży"
    # to `zamowienie_bez_warunku.id IS NOT NULL AND SalesOrder.id IS NULL`.
    zamowienie_bez_warunku = db.aliased(SalesOrder)
    kolumna_w_realizacji = (
        db.func.sum(db.case((db.and_(
            ProductionOrder.id.isnot(None),
            db.or_(zamowienie_bez_warunku.id.is_(None), SalesOrder.id.isnot(None)),
        ), 1), else_=0))
        if ma_produkcje else db.literal(0)
    )

    # Jedno zapytanie na wszystkie pięć stopni i obie średnie. Złączenia
    # zewnętrzne nie powielają wierszy, bo `baselinker_order_id` jest UNIQUE
    # i w `sales_orders`, i w `prod_orders`.
    zapytanie = (
        db.session.query(
            db.func.count(Quote.id),
            db.func.sum(db.case((Quote.acceptance_date.isnot(None), 1), else_=0)),
            db.func.sum(db.case((ma_numer, 1), else_=0)),
            db.func.sum(db.case(
                (db.and_(SalesOrder.id.isnot(None), SalesOrder.balance_due <= 0), 1),
                else_=0)),
            kolumna_w_realizacji,
            # Ile wycen z numerem w ogóle DAŁO SIĘ dowiązać do sprzedaży.
            # Różnica wobec stopnia „Zamówione" jest prawdziwa (zamówienia
            # spoza zakresu tabeli sprzedaży) i karta ma ją pokazać, a nie
            # zamieść — inaczej „Opłacone" wygląda na spadek konwersji.
            db.func.sum(db.case((SalesOrder.id.isnot(None), 1), else_=0)),
            db.func.avg(Quote.total_price),
            # Średnia po wycenach, które trafiły do BaseLinkera. `case` bez
            # `else_` daje NULL, a AVG NULL-e pomija — czyli dokładnie to,
            # o co chodzi: średnia z podzbioru, nie średnia z zerami.
            db.func.avg(db.case((ma_numer, Quote.total_price))),
        )
        .select_from(Quote)
        .outerjoin(SalesOrder, _dowiazanie_do_sprzedazy())
    )
    if ma_produkcje:
        zapytanie = zapytanie.outerjoin(
            ProductionOrder, _dowiazanie_po_numerze(ProductionOrder.baselinker_order_id)
        ).outerjoin(
            zamowienie_bez_warunku,
            _dowiazanie_po_numerze(zamowienie_bez_warunku.baselinker_order_id))
    licznik = zapytanie.filter(*okres).one()

    utworzone = int(licznik[0] or 0)
    stopnie = []
    for indeks, (klucz, etykieta) in enumerate(STOPNIE_LEJKA):
        liczba = int(licznik[indeks] or 0)
        stopnie.append({'klucz': klucz, 'etykieta': etykieta, 'liczba': liczba,
                        'udzial': _procent(liczba, utworzone)})

    # Czas od wyceny do zamówienia. `SalesOrder.date_created` jest datą,
    # `Quote.created_at` chwilą — stąd `.date()` przed odejmowaniem.
    pary = (
        db.session.query(Quote.created_at, SalesOrder.date_created)
        .select_from(Quote)
        .join(SalesOrder, _dowiazanie_do_sprzedazy())
        .filter(*okres)
        .all()
    )
    dni = [(zamowienie - wycena.date()).days for wycena, zamowienie in pary
           if wycena is not None and zamowienie is not None]

    zamowione = stopnie[2]['liczba']
    return {
        'stopnie': stopnie,
        # Skróty do stopni 1 i 3. Do payloadu NIE jadą (tam jest sama lista
        # stopni), ale czytają je testy i `_uwaga_lejka` — bez nich każde
        # z tych miejsc musiałoby wiedzieć, pod którym indeksem siedzi
        # „Zamówione".
        'wycen': utworzone,
        'zamienionych': zamowione,
        'procent': _procent(zamowione, utworzone),
        'dopasowanych': int(licznik[5] or 0),
        'srednia_wycena': _zero(licznik[6]).quantize(Decimal('0.01')),
        'srednia_zamowiona': _zero(licznik[7]).quantize(Decimal('0.01')),
        'mediana_dni': _mediana(dni),
        'mediana_probka': len(dni),
        'podzial': {nazwa: _podzial_lejka(nazwa, poczatek, koniec)
                    for nazwa in podzialy},
    }


def ostrzezenie_salda(na_dzien: date, filtr=None) -> Dict[str, object]:
    """Ile starego salda wisi na zamówieniach, które są wciąż w produkcji.

    Na produkcji 21.09.2026: 596 tys. zł „należności" starszych niż 90 dni,
    z czego 50 zamówień ma status „W produkcji — surowe". To nie są należności,
    tylko rekordy, których nikt nie domknął w BaseLinkerze. Karta należności musi
    to pokazywać, zamiast podawać sumę jako wskaźnik.

    `filtr` (wykluczenia pozycji z pulpitu, partia E, punkt E4) wchodzi przez
    `warunki_zamowienia` — tak samo jak w kubełkach wieku tej samej karty,
    więc ostrzeżenie mówi o tym samym zbiorze zamówień, co kubełki nad nim.
    """
    granica = na_dzien - timedelta(days=_PROG_STAREGO_SALDA_DNI)
    wiersz = (
        db.session.query(
            db.func.count(SalesOrder.id),
            db.func.sum(SalesOrder.balance_due),
        )
        .filter(
            SalesOrder.balance_due > 0,
            SalesOrder.date_created < granica,
            db.func.lower(SalesOrder.current_status).like('%produkcj%'),
            # Warunek stały (partia E, punkt E5) — ostrzeżenie dotyczy salda
            # z karty należności, a ta liczy wyłącznie sprzedaż. Dokłada go
            # `warunki_zamowienia` na końcu listy, także przy pustym filtrze.
            *warunki_zamowienia(filtr),
        )
        .one()
    )
    return {'zamowienia': int(wiersz[0] or 0), 'saldo': _zero(wiersz[1])}


def suma_kosztu_kuriera(od: date, do: date, filtr=None) -> Decimal:
    """Koszt kuriera pobrany od klienta, brutto. Liczony RAZ na zamówienie.

    Zapytanie idzie po samym `SalesOrder`, więc filtr wchodzi przez
    `warunki_zamowienia` — warunek po polu pozycji trafi tam jako `EXISTS`
    i nie powieli kosztu przez liczbę pozycji.
    """
    return _zero(
        db.session.query(db.func.sum(SalesOrder.delivery_cost))
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_zamowienia(filtr))
        .scalar()
    )


# --- MAPA WOJEWÓDZTW --------------------------------------------------------

# Identyfikatory obszarów SVG, w kolejności z `analiza/_mapa_polski.html`.
# Są BEZ POLSKICH ZNAKÓW i małymi literami, bo takie stoją w atrybutach `id`
# ścieżek — a stara zakładka szuka ich przez `document.getElementById(id)`
# (reports.js). Zmiana któregokolwiek z nich rozspaja mapę na OBU zakładkach.
IDENTYFIKATORY_WOJEWODZTW: Tuple[str, ...] = (
    'zachodniopomorskie', 'pomorskie', 'warminsko-mazurskie', 'podlaskie',
    'lubuskie', 'wielkopolskie', 'kujawsko-pomorskie', 'mazowieckie',
    'dolnoslaskie', 'lodzkie', 'lubelskie', 'opolskie', 'slaskie',
    'swietokrzyskie', 'malopolskie', 'podkarpackie',
)

# Odwzorowanie identyfikator SVG -> nazwa kanoniczna z bazy.
#
# NIE JEST TO TRZECIA MAPA NAZW. Bierzemy ją WPROST z `STATE_NORMALIZATION`
# w `modules/reports/utils.py`, bo tamta mapa już zna dokładnie te formy bez
# ogonków („slaskie" -> „Śląskie", „warminsko-mazurskie" ->
# „Warmińsko-Mazurskie") i to ona decyduje, jak nazwa ląduje w bazie przy
# imporcie z BaseLinkera. Przepisana tutaj rozjechałaby się przy pierwszej
# poprawce po tamtej stronie — a objawem byłoby województwo, które na mapie
# jest białe, choć w tabeli ma sprzedaż.
#
# Brak klucza to błąd programistyczny, nie stan danych — łapie go
# `tests/test_analiza_mapa.py`, zanim ktokolwiek uruchomi aplikację.
WOJEWODZTWA: Dict[str, str] = {
    klucz: PostcodeToStateMapper.STATE_NORMALIZATION[klucz]
    for klucz in IDENTYFIKATORY_WOJEWODZTW
}

# Droga powrotna: nazwa z bazy -> identyfikator obszaru SVG.
IDENTYFIKATORY_PO_NAZWIE: Dict[str, str] = {
    nazwa: klucz for klucz, nazwa in WOJEWODZTWA.items()
}

# Miary dymka, w kolejności wyświetlania. To NAZWY MIAR dashboardu (te same,
# które podpisuje `analiza_service.ETYKIETY_MIAR` i którym jednostkę nadaje
# `JEDNOSTKI_MIAR`), a nie nazwy kolumn — dzięki temu „Klienci" w dymku znaczy
# dokładnie to samo, co „Klienci" w kafelku KPI i w Eksploratorze.
MIARY_MAPY: Tuple[str, ...] = (
    'netto', 'objetosc', 'zamowienia', 'klienci', 'w_produkcji',
)


def identyfikator_wojewodztwa(surowa) -> Optional[str]:
    """Wartość `sales_orders.delivery_state` -> identyfikator obszaru SVG.

    `None` znaczy „nie ma takiego obszaru na mapie" i jest odpowiedzią na dwa
    różne pytania naraz: na pustą wartość (296 zamówień na całej bazie) i na
    wartość, której nie da się rozpoznać (w bazie siedzi jedno „Dol" — ucięty
    zapis z BaseLinkera). Oba przypadki MUSZĄ być widoczne poza mapą, a nie
    po cichu wliczone do żadnego województwa.
    """
    if surowa is None or not str(surowa).strip():
        return None
    return IDENTYFIKATORY_PO_NAZWIE.get(
        PostcodeToStateMapper.normalize_state_name(str(surowa)))


def _puste_statystyki() -> Dict[str, object]:
    return {'netto': Decimal('0'), 'objetosc': Decimal('0'), 'sztuki': 0,
            'zamowienia': 0, 'klienci': 0, 'w_produkcji': 0}


def _dolicz(cel: Dict[str, object], wiersz) -> None:
    cel['netto'] += _zero(wiersz.netto)
    cel['objetosc'] += _zero(wiersz.objetosc)
    cel['sztuki'] += _sztuki(wiersz.sztuki)
    cel['zamowienia'] += int(wiersz.zamowienia or 0)
    cel['klienci'] += int(wiersz.klienci or 0)
    # Kolumna `w_produkcji` nie zawsze jedzie w zapytaniu — patrz komentarz
    # „BRAK TABELI `prod_orders`" w `sprzedaz_wg_wojewodztw`. `getattr` z
    # domyślną wartością zamiast `wiersz.w_produkcji` jest tu celowe: wiersz
    # bez tej etykiety nie ma takiego atrybutu wcale (nie ma go z wartością
    # None), więc zwykłe odwołanie rzuciłoby AttributeError.
    cel['w_produkcji'] += int(getattr(wiersz, 'w_produkcji', 0) or 0)


def sprzedaz_wg_wojewodztw(od: date, do: date, filtr=None) -> Dict[str, object]:
    """Komplet statystyk mapy: sprzedaż i produkcja w rozbiciu na województwa.

    Zwraca `{'obszary': {identyfikator: statystyki}, 'poza_mapa': [...]}`.
    W `obszary` jest ZAWSZE szesnaście pozycji — województwo bez ani jednego
    zamówienia wraca z zerami, bo mapa musi je narysować tak czy inaczej,
    a dziura w słowniku zmusiłaby przeglądarkę do zgadywania.

    JEDNO ZAPYTANIE NA PIĘĆ MIAR. Złączenie zewnętrzne z `prod_orders` NIE
    powiela pozycji, bo `baselinker_order_id` jest tam UNIQUE — to samo
    założenie, na którym stoi lejek wycen (patrz `lejek_wycen`). Gdyby
    przestało być prawdą, `SUM(value_net)` zacząłby zawyżać, więc pilnuje
    go osobny test.

    OBJĘTOŚĆ WYKLUCZA USŁUGI (`_objetosc_bez_uslug`), tak samo jak KPI
    i wszystkie karty. Zmierzone na zrzucie produkcji 22.09.2026: bez tego
    wykluczenia Podkarpackie ma 49,40 m³ zamiast 49,06, a zamówienia bez
    województwa — 273,20 m³ zamiast 63,33, bo suszenie usługowe liczy metry
    sześcienne w polu ilości.

    NETTO I OBJĘTOŚĆ IDĄ Z POZYCJI, a liczba zamówień i klientów z zamówienia
    (przez `COUNT(DISTINCT)`). Salda ta karta nie pokazuje w ogóle — właśnie
    dlatego, że jest polem zamówienia powielonym na pozycjach i jedyny
    poprawny sposób na nie to osobne zapytanie.

    BRAK TABELI `prod_orders`: dymek mapy jest częścią bramki uprawnień
    modułu Analizy (test `/reports/api/analytics` wymaga tylko odpowiedzi
    200, nie danych produkcji), a fixture tego testu — i każdy inny kontekst
    bez zainicjalizowanego modułu produkcji — świadomie nie zakłada
    `prod_orders`. Ten sam problem rozwiązuje już `_jest_tabela('prod_orders')`
    w `arkusz_service._dane_produkcji` (patrz jej docstring) i tu robimy
    dokładnie to samo, tym samym mechanizmem, zamiast dopisywać drugi sposób
    sprawdzania tego samego faktu. WAŻNE: to jest sprawdzenie ISTNIENIA
    tabeli przez `inspect().has_table`, nie ogólny `try/except` na zapytaniu
    — jeśli `prod_orders` NA PRODUKCJI istnieje, a zapytanie padnie z innego
    powodu (zły typ, brak uprawnień w bazie), wyjątek leci dalej i karta
    NIE pokaże cicho zera zamiast prawdziwej liczby.
    """
    from modules.production.models import ProductionOrder
    from modules.reports.ingest import _jest_tabela

    ma_produkcje = _jest_tabela('prod_orders')

    kolumny = [
        SalesOrder.delivery_state.label('wojewodztwo'),
        db.func.sum(SalesOrderItem.value_net).label('netto'),
        _objetosc_bez_uslug().label('objetosc'),
        # Tryb „szt." kartogramu (24.09.2026) — w tym samym zapytaniu.
        sztuki_bez_uslug().label('sztuki'),
        db.func.count(db.func.distinct(SalesOrder.id)).label('zamowienia'),
        db.func.count(db.func.distinct(SalesOrder.client_id)).label('klienci'),
    ]
    if ma_produkcje:
        kolumny.append(db.func.count(db.func.distinct(
            ProductionOrder.baselinker_order_id)).label('w_produkcji'))

    zapytanie = (
        db.session.query(*kolumny)
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
    )
    if ma_produkcje:
        zapytanie = zapytanie.outerjoin(
            ProductionOrder,
            ProductionOrder.baselinker_order_id == SalesOrder.baselinker_order_id)
    wiersze = (
        zapytanie
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
        .group_by(SalesOrder.delivery_state)
        .all()
    )

    obszary = {klucz: _puste_statystyki() for klucz in IDENTYFIKATORY_WOJEWODZTW}
    poza_mapa: Dict[str, Dict[str, object]] = {}

    for wiersz in wiersze:
        klucz = identyfikator_wojewodztwa(wiersz.wojewodztwo)
        if klucz is None:
            # Klucz słownika to wartość SUROWA — etykietę po polsku („(brak)")
            # dokłada warstwa widoku, tak samo jak w wierszach kart.
            surowa = wiersz.wojewodztwo or ''
            _dolicz(poza_mapa.setdefault(surowa, _puste_statystyki()), wiersz)
        else:
            # Scalenie dwóch zapisów tej samej nazwy (np. „Śląskie" i
            # „śląskie") sumuje też liczniki DISTINCT, więc klient obecny
            # w obu policzyłby się dwa razy. Na zrzucie produkcji 22.09.2026
            # każda nazwa kanoniczna występuje dokładnie raz, więc dziś to
            # nie ma jak wystąpić — ale gdy wystąpi, zawyży o pojedyncze
            # sztuki, a nie o rząd wielkości.
            _dolicz(obszary[klucz], wiersz)

    lista_poza = [dict(statystyki, wartosc=surowa)
                  for surowa, statystyki in poza_mapa.items()]
    lista_poza.sort(key=lambda p: (-p['netto'], str(p['wartosc'])))
    return {'obszary': obszary, 'poza_mapa': lista_poza}
