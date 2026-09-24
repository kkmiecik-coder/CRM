# -*- coding: utf-8 -*-
"""Deduplikacja klientów sprzedażowych.

KASKADA: e-mail -> NIP -> telefon. Nigdy sama nazwa.

Pokrycie zmierzone na produkcji 21.09.2026: e-mail ma 93,3% zamówień
(224 z 3324 go nie mają). NIP jest dla firm pewniejszy niż e-mail, bo przeżywa
zmianę adresu. Nazwa jest wykluczona jako klucz: w arkuszu sprzedażowym 49
duplikatów bierze się wyłącznie z wielkości liter, a samo nazwisko i imię
z nazwiskiem (np. „Szablonowy" i „Jan Szablonowy") to dwa wpisy tego samego
klienta — dopasowanie po nazwie scalałoby różne osoby i rozdzielało tę samą.

Zamówienie bez żadnego z trzech kluczy dostaje własnego klienta z flagą
`needs_merge`. Ta sama flaga trafia też na już ZNALEZIONY rekord, gdy klucz,
który chcemy mu dopisać, należy już do INNEGO klienta — `email_norm` /
`nip_norm` / `phone_norm` mają w modelu tylko `index=True`, bez unikalności,
więc ciche dopisanie scaliłoby dwie różne tożsamości (typowy przypadek:
wspólny telefon recepcji firmy trafia do dwóch osobnych klientów B2B).
`needs_merge` znaczy więc dziś: „brak wszystkich trzech kluczy" ALBO
„klucze są niejednoznaczne" — w obu przypadkach sens jest ten sam, człowiek
musi na to spojrzeć. Automat zawsze zostawi resztki; bez ręcznego scalania
statystyka powracających po roku zacznie kłamać.

SESJA PRZEKAZYWANA JAWNIE
=========================
Każda funkcja sięgająca do bazy przyjmuje `sesja` z domyślną wartością
`db.session`. Powód: `ingest.zapisz_zamowienia` pracuje od 22.09.2026 na
WŁASNEJ sesji, żeby commit i rollback analityki nie dotykały transakcji
produkcji (patrz docstring `modules/reports/ingest.py`). `Model.query` idzie
przez rejestr `scoped_session`, czyli zawsze przez `db.session`, więc
wewnątrz tego modułu używamy `sesja.query(Model)`. Domyślna wartość
zachowuje dotychczasowe zachowanie dla `scripts/backfill_sales_tables.py`,
`scripts/uzupelnij_sales_braki.py` i testów, które wołają te funkcje wprost.
"""

import re
from typing import Optional

from extensions import db
from modules.reports.models_sales import SalesClient

_TYLKO_CYFRY = re.compile(r'\D+')
# Najkrótszy sensowny numer krajowy ma 9 cyfr. Cokolwiek krótszego to śmieć
# w kolumnie, a nie numer — dopasowanie po nim scalałoby przypadkowe rekordy.
_MIN_CYFR_TELEFONU = 9


def norm_email(wartosc: Optional[str]) -> Optional[str]:
    if not wartosc:
        return None
    oczyszczony = wartosc.strip().lower()
    return oczyszczony or None


def norm_nip(wartosc: Optional[str]) -> Optional[str]:
    if not wartosc:
        return None
    cyfry = _TYLKO_CYFRY.sub('', wartosc)
    return cyfry or None


def norm_phone(wartosc: Optional[str]) -> Optional[str]:
    if not wartosc:
        return None
    cyfry = _TYLKO_CYFRY.sub('', str(wartosc))
    # Zdejmij prefiks krajowy w obu zapisach: +48 i 0048.
    if cyfry.startswith('0048'):
        cyfry = cyfry[4:]
    elif cyfry.startswith('48') and len(cyfry) > 9:
        cyfry = cyfry[2:]
    if len(cyfry) < _MIN_CYFR_TELEFONU:
        return None
    return cyfry


def _sesja(sesja=None):
    """Podana sesja albo współdzielona `db.session`. Patrz docstring modułu."""
    return sesja if sesja is not None else db.session


def _dopisz_klucz_jesli_wolny(klient: SalesClient, wartosc: Optional[str],
                              pole: str, sesja=None) -> None:
    """Dopisuje `wartosc` do `pole` klienta (`nip_norm` albo `phone_norm`),
    jeśli klient jeszcze go nie ma i wartość nie należy do INNEGO klienta.

    email_norm/nip_norm/phone_norm mają w modelu tylko `index=True`, bez
    unikalności, więc ciche dopisanie scaliłoby dwie różne tożsamości —
    typowy przypadek: wspólny telefon recepcji firmy trafia do dwóch
    osobnych klientów B2B. Przy kolizji zamiast dopisania oznaczamy klienta
    do ręcznego scalenia (`needs_merge`).
    """
    if not wartosc or getattr(klient, pole):
        return
    kolizja = _sesja(sesja).query(SalesClient).filter(
        getattr(SalesClient, pole) == wartosc, SalesClient.id != klient.id,
    ).first()
    if kolizja is None:
        setattr(klient, pole, wartosc)
        if pole == 'nip_norm':
            klient.client_kind = 'b2b'
    else:
        klient.needs_merge = True


def znajdz_lub_utworz_klienta(email: Optional[str], nip: Optional[str],
                              phone: Optional[str], nazwa: Optional[str],
                              sesja=None) -> SalesClient:
    """Zwraca istniejącego klienta albo dodaje nowego do sesji (bez commita).

    Commit należy do wołającego — backfill robi go zbiorczo co N zamówień.

    `sesja` — patrz docstring modułu. Domyślnie współdzielona `db.session`.
    """
    sesja = _sesja(sesja)
    e, n, t = norm_email(email), norm_nip(nip), norm_phone(phone)

    znaleziony = None
    if e:
        znaleziony = sesja.query(SalesClient).filter_by(email_norm=e).first()
    if znaleziony is None and n:
        znaleziony = sesja.query(SalesClient).filter_by(nip_norm=n).first()
    if znaleziony is None and t:
        znaleziony = sesja.query(SalesClient).filter_by(phone_norm=t).first()

    if znaleziony is not None:
        # Uzupełnij klucze, których rekord jeszcze nie miał — kolejne zamówienie
        # od tego samego klienta często przynosi dane, których brakowało.
        #
        # E-mail: kolizja jest tu NIEMOŻLIWA, sprawdzanie jej byłoby martwym
        # kodem. `znaleziony` jest szukany po e-mailu jako PIERWSZY (patrz
        # wyżej) — jeśli lookup po `e` coś zwrócił, to `znaleziony.email_norm
        # == e` i warunek `not znaleziony.email_norm` niżej jest fałszywy, więc
        # do tej gałęzi się nie wchodzi. Jeśli `znaleziony` pochodzi z lookupu
        # po NIP-ie albo telefonie (a `email_norm` jest u niego puste), to
        # znaczy, że lookup po `e` wcześniej nic nie zwrócił — czyli ŻADEN
        # klient w bazie nie ma dziś `email_norm == e`, więc zapytanie
        # o kolizję e-maila też nigdy nic by nie zwróciło.
        if e and not znaleziony.email_norm:
            znaleziony.email_norm = e
        # NIP i telefon: kolizja jest tu jak najbardziej możliwa — `znaleziony`
        # mógł zostać znaleziony po INNYM kluczu (np. po e-mailu), więc jego
        # nip_norm/phone_norm bywa puste, a wartość, którą chcemy dopisać,
        # może już należeć do innego klienta.
        _dopisz_klucz_jesli_wolny(znaleziony, n, 'nip_norm', sesja)
        _dopisz_klucz_jesli_wolny(znaleziony, t, 'phone_norm', sesja)
        return znaleziony

    nowy = SalesClient(
        email_norm=e,
        nip_norm=n,
        phone_norm=t,
        display_name=(nazwa or '').strip() or None,
        client_kind='b2b' if n else 'detal',
        needs_merge=not (e or n or t),
    )
    sesja.add(nowy)
    sesja.flush()   # nadaj id, żeby wołający mógł je przypiąć do zamówienia
    return nowy


def zbuduj_indeks_leadow(sesja=None) -> dict:
    """Wczytuje CAŁĄ tabelę `leads` RAZ i zwraca mapę znormalizowanych
    kluczy -> listy id leadów, osobno dla e-maila, NIP-u i telefonu.

    ZNALEZISKO WAŻNE (przegląd Zadania 4, dedup.py:169): `dowiaz_lead`
    wczytywało całą tabelę `leads` do Pythona aż 3x NA ZAMÓWIENIE (e-mail ->
    NIP -> telefon) i powtarzało to przy KAŻDYM zamówieniu klienta bez
    `lead_id`. Zmierzone w kontenerze na realnym zrzucie: 20-77 ms na jedno
    wczytanie (leads=3616, z e-mailem 1475), czyli ~6-20 s doklejone do
    synchronizacji 100 zamówień — a od Zadania 4 ta ścieżka wisi też na
    torze krytycznym produkcji (zaczep w `SyncService`), nie tylko na
    ręcznym „Pobierz zamówienia" w arkuszu.

    Tę funkcję wywołujemy RAZ na całą paczkę (`zapisz_zamowienia`), a wynik
    przekazujemy do `dowiaz_lead` jako `indeks`. Grupowanie po znormalizowanym
    kluczu w Pythonie (zamiast per-rekordowego porównania w `_znajdz`) daje
    identyczny wynik: kolizja dwóch leadów o tym samym znormalizowanym
    e-mailu (21 przypadków w `leads`, spec §3.4) nadal ląduje jako lista
    dwuelementowa, czyli niejednoznaczność, dokładnie tak jak wcześniej.
    """
    # Import lokalny: modules.clients sięga pośrednio do modules.reports,
    # import na poziomie modułu zamknąłby cykl. Ten sam wzorzec, co
    # w modules/reports/analytics.py:198.
    from modules.clients.models import Client

    aktywna = _sesja(sesja)

    def _mapa(kolumna, normalizator):
        mapa: dict = {}
        kandydaci = (aktywna.query(Client.id, kolumna)
                     .filter(kolumna.isnot(None), kolumna != '')
                     .all())
        for id_leada, surowa_wartosc in kandydaci:
            klucz = normalizator(surowa_wartosc)
            if klucz:
                mapa.setdefault(klucz, []).append(id_leada)
        return mapa

    return {
        'email': _mapa(Client.email, norm_email),
        'nip': _mapa(Client.invoice_nip, norm_nip),
        'phone': _mapa(Client.phone, norm_phone),
    }


def dowiaz_lead(klient: SalesClient, indeks: Optional[dict] = None,
                sesja=None) -> Optional[int]:
    """Ustawia `klient.lead_id`, jeśli da się jednoznacznie wskazać leada.

    Kaskada jest ta sama, co przy deduplikacji kupujących: e-mail -> NIP ->
    telefon, nigdy sama nazwa. Klucze z `leads` normalizujemy tymi samymi
    funkcjami, bo tamta tabela ich nie normalizuje — trzyma e-maile
    z wielkimi literami i spacjami, a telefony z prefiksem +48.

    NIEJEDNOZNACZNOŚĆ ZNACZY „NIE WIĄŻEMY". W `leads` 21 e-maili występuje
    wielokrotnie (spec §3.4). Wybór „pierwszego lepszego" byłby
    niedeterministyczny, a zły lead kłamie na karcie konwersji trwale
    i po cichu. Klient dostaje wtedy `needs_merge` — dokładnie tak samo,
    jak przy kolizji klucza w `_dopisz_klucz_jesli_wolny`.

    `indeks` — mapa z `zbuduj_indeks_leadow()`. Gdy nie podano (wywołanie
    pojedyncze, jak w testach albo w `scripts/uzupelnij_sales_braki.py`),
    funkcja buduje ją ad-hoc dla tego jednego klienta — zachowanie identyczne
    jak przed Zadaniem 4. `zapisz_zamowienia` buduje ją RAZ na paczkę i
    przekazuje tutaj, żeby nie odpytywać `leads` osobno na każde zamówienie.

    Zwraca `lead_id` (także ten, który już był) albo None. Nie commituje.
    """
    if klient.lead_id is not None:
        return klient.lead_id

    mapa = indeks if indeks is not None else zbuduj_indeks_leadow(sesja)

    trafienia = mapa['email'].get(klient.email_norm, []) if klient.email_norm else []
    if not trafienia and klient.nip_norm:
        trafienia = mapa['nip'].get(klient.nip_norm, [])
    if not trafienia and klient.phone_norm:
        trafienia = mapa['phone'].get(klient.phone_norm, [])

    if len(trafienia) == 1:
        klient.lead_id = trafienia[0]
        return klient.lead_id
    if len(trafienia) > 1:
        klient.needs_merge = True
    return None
