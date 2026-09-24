# -*- coding: utf-8 -*-
"""Wysyłka pól arkusza do BaseLinkera — budowa ładunku i klient API.

JEDNO MIEJSCE Z `requests` DLA ZAPISU ZWROTNEGO
===============================================
Stary serwis raportów (`modules/reports/service.py`) rozmawia z BaseLinkerem
wyłącznie w trybie odczytu (`getOrders`). Zapis jest osobną odpowiedzialnością
i siedzi tutaj, żeby dało się go podmienić atrapą w teście — w całym pakiecie
nie ma ani jednego wywołania prawdziwego API.

CO API NAPRAWDĘ PRZYJMUJE (zweryfikowane w dokumentacji 22.09.2026)
===================================================================
  setOrderFields          order_id + pola wprost + custom_extra_fields{id: wartość}
  setOrderProductFields   order_id + order_product_id + price_brutto / quantity
  setOrderPayment         order_id + payment_done (float) + payment_date (UNIXTIME)
  setOrderStatus          order_id + status_id (int)
"""

import json
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

import requests
from flask import current_app

from modules.reports.analiza_service import dzis_lokalnie
from modules.reports.fields import POLA
from modules.reports.service import STATUSY_BASELINKER

# Status idzie OSTATNI, bo BaseLinker odpala na nim automatyzacje — etykiety,
# faktury, powiadomienia do klienta. Mają zobaczyć już poprawione dane.
KOLEJNOSC_METOD = ('setOrderFields', 'setOrderProductFields',
                   'setOrderPayment', 'setOrderStatus')

_VAT = Decimal('1.23')

# Jedyne dwa oznaczenia typu ceny, przy których wolno policzyć `payment_done`.
# Kolumna w bazie to ENUM('netto','brutto',''), więc trzecia wartość — pusty
# napis — jest legalna i znaczy „nie wiadomo". Patrz `_platnosc_brutto`.
_TYPY_CENY = ('netto', 'brutto')

# Odwrócona mapa statusów. `current_status` jest w rejestrze tekstem, a API
# przyjmuje identyfikator. Statusu spoza tej mapy („Status 417343", 131 wierszy
# na produkcji) nie da się wysłać — walidacja odrzuca go już przy edycji,
# bo lista `opcje` kolumny bierze się z tego samego słownika.
_IDENTYFIKATORY_STATUSOW = {nazwa: numer for numer, nazwa in STATUSY_BASELINKER.items()}


class BladBaselinkera(Exception):
    """API odmówiło albo nie odpowiedziało. Kończy się `odrzucone` w wyniku."""


def _na_float(wartosc) -> float:
    return float(wartosc if wartosc is not None else 0)


# OSŁONA ZAKRESU (przegląd Zadania 11, [WAŻNE]): druga linia obrony, obok
# walidacji w `arkusz_zapis.na_wartosc` (ta sama para granic, duplikat
# literału zamiast importu — ten moduł nie ma powodu zależności od warstwy
# widoku arkusza). Data spoza rozsądnego okna (rok 1, rok 9999) na
# niektórych platformach (Windows) nie daje sensownego unixtime, tylko
# wywala `datetime.timestamp()` błędem systemowym („year 0 is out of
# range") — bez tej osłony taki wyjątek szedł nieopakowany prosto do
# interfejsu.
_NAJWCZESNIEJSZA_DATA_PLATNOSCI = date(2000, 1, 1)
_NAJPOZNIEJSZA_DATA_PLATNOSCI = date(2100, 1, 1)


def _na_unixtime(wartosc) -> int:
    """Data na unixtime. BaseLinker przyjmuje w `payment_date` liczbę.

    BRAK DATY = ODMOWA, NIE ZERO (domknięcie Planu C). Stare `return 0`
    wysyłało do BaseLinkera 1970-01-01 — datę, której nikt nie wpisał.
    `data_platnosci_efektywna` zamknęła główną drogę do tego zera (edycja
    samej kwoty przy `payment_date IS NULL` bierze dziś datę dzisiejszą),
    ale została druga, osiągalna z arkusza: `sales_orders.payment_date`
    jest `nullable=True`, więc WYCZYSZCZENIE komórki „Data płatności"
    przechodzi walidację jako `None` i wracało tu jako zero.

    DLACZEGO ODMOWA, A NIE POMINIĘCIE KLUCZA: `setOrderPayment` podmienia
    całą płatność naraz (patrz `buduj_ladunek` — „ZAWSZE obie wartości"),
    a tego, czy BaseLinker potraktuje brak `payment_date` jako „zostaw, co
    było", czy jako zero, nie da się sprawdzić bez prawdziwego zapisu na
    zamówieniu produkcyjnym. Zgadywanie o zachowaniu API to ta sama klasa
    błędu, co zgadywanie typu ceny niżej. Data jest więc WYMAGANA razem
    z kwotą, a jej brak kończy się czytelną odmową.
    """
    if wartosc is None:
        raise BladBaselinkera(
            'wpłaty w BaseLinkerze nie da się zapisać bez daty płatności — '
            'wpisz datę w kolumnie „{}" razem z kwotą'.format(
                POLA['payment_date'].etykieta))
    if not (_NAJWCZESNIEJSZA_DATA_PLATNOSCI <= wartosc <= _NAJPOZNIEJSZA_DATA_PLATNOSCI):
        raise BladBaselinkera(
            'data płatności „{}" jest poza dopuszczalnym zakresem'.format(
                wartosc.isoformat()))
    return int(datetime.combine(wartosc, time.min).timestamp())


def _platnosc_brutto(kwota_netto, typ_ceny) -> float:
    """Kwota, jaką BaseLinker ma zobaczyć w `payment_done`.

    PUŁAPKA: `sales_orders.paid_amount` trzyma kwotę NETTO — tak mapował
    backfill (`paid_amount_net` ze starej tabeli) i tak mapuje zapis
    przyrostowy. BaseLinker chce kwoty, którą widzi klient, czyli brutto
    dla zamówień oznaczonych jako brutto. Wysłanie netto zaniżyłoby wpłatę
    o 23% i zamieniło opłacone zamówienie w niedopłacone.

    BRAK OZNACZENIA TYPU CENY = ODMOWA, NIE DOMYSŁ (domknięcie Planu C).
    Reszta CRM-u czyta brak oznaczenia jak „brutto" (`ingest.typ_ceny`,
    `service.kwota_netto`) i przy ODCZYCIE to jest w porządku: tak są
    policzone wszystkie dane historyczne, więc zmiana domyślności
    rozjechałaby szeregi czasowe. Przy ZAPISIE ta sama domyślność mnoży
    kwotę przez 1,23 na podstawie zgadywania — i wysyła wynik do systemu,
    z którego idą faktury. Konsekwencje są niesymetryczne: zła liczba
    w odczycie psuje wykres, zła liczba w zapisie to realne pieniądze.

    Zmierzone 22.09.2026 na `woodpower_crm_local`: 2913 zamówień „brutto",
    408 „netto", 3 bez oznaczenia (pusty napis, żadnego NULL-a). Odmowa
    kosztuje więc trzy zamówienia, a komunikat mówi wprost, co zrobić —
    kolumna „Typ ceny" jest edytowalna i sama wraca do BaseLinkera
    (`SetOrderCustomField('106169')`), a `setOrderFields` idzie w paczce
    PRZED `setOrderPayment` (patrz KOLEJNOSC_METOD), więc uzupełnienie
    typu ceny i wpłaty da się zapisać za jednym razem.

    KWANTYZACJA DO GROSZA (przegląd Zadania 11, [WAŻNE]): `paid_amount`
    powstaje przez dzielenie kwoty brutto przez 1,23 i zaokrąglenie do
    2 miejsc (`service.kwota_netto()`) — więc każda kwota, która przeszła
    synchronizację, po pomnożeniu z powrotem przez 1,23 daje ogon
    (813,01 * 1,23 = 1000,0023). Bez kwantyzacji BaseLinker dostawał
    wpłatę różną od kwoty zamówienia o grosze i pokazywał je jako
    nie-do-końca-opłacone.
    """
    typ = (typ_ceny or '').strip().lower()
    if typ not in _TYPY_CENY:
        raise BladBaselinkera(
            'zamówienie nie ma oznaczonego typu ceny, więc nie wiadomo, czy '
            'wpłata jest netto, czy brutto — uzupełnij kolumnę „{}" '
            '(netto albo brutto) i zapisz wpłatę jeszcze raz'.format(
                POLA['price_type'].etykieta))
    kwota = Decimal(str(kwota_netto if kwota_netto is not None else 0))
    wynik = kwota if typ == 'netto' else kwota * _VAT
    return float(wynik.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def data_platnosci_efektywna(pola: List[Tuple[Dict, object]], zamowienie) -> Optional[date]:
    """Data, która POJEDZIE w `setOrderPayment` — i którą trzeba dopisać
    lokalnie, gdy w bazie jej nie było (patrz `arkusz_zapis._wyslij_grupe`).

    PUŁAPKA (przegląd Zadania 11, [KRYTYCZNE]): `payment_date` jest NULL
    dokładnie na zamówieniach jeszcze nieopłaconych — `ingest.py` ustawia ją
    WYŁĄCZNIE, gdy jest wpłata. To nie jest przypadek brzegowy: to jest
    GŁÓWNY scenariusz „ktoś wpisuje „Zapłacono" po raz pierwszy". Stara
    wersja brała wtedy `zamowienie.payment_date` (czyli `None`) i
    `_na_unixtime(None)` dawało `0` = 1970-01-01 — sfabrykowaną datę, której
    użytkownik nie wpisał i nie autoryzował. Gdy kwota naprawdę się zmienia
    i baza nie ma daty, bierzemy DZISIEJSZĄ — nigdy zero.
    """
    zmienione = {kolumna['nazwa']: wartosc for kolumna, wartosc in pola}
    if 'payment_date' in zmienione:
        return zmienione['payment_date']
    if zamowienie.payment_date is not None:
        return zamowienie.payment_date
    if 'paid_amount' in zmienione:
        return dzis_lokalnie()
    return None


def buduj_ladunek(metoda: str, pola: List[Tuple[Dict, object]],
                  zamowienie, pozycja=None) -> Dict[str, object]:
    """Ładunek jednego wywołania API.

    `pola` to lista par (opis kolumny z rejestru, wartość po zmianie).
    Wartości pól, które NIE zostały zmienione, a są wymagane przez metodę,
    dobieramy z bazy — patrz `setOrderPayment`.
    """
    ladunek: Dict[str, object] = {'order_id': zamowienie.baselinker_order_id}

    if metoda == 'setOrderFields':
        dodatkowe = {}
        for kolumna, wartosc in pola:
            if kolumna['id_pola_bl']:
                dodatkowe[kolumna['id_pola_bl']] = '' if wartosc is None else str(wartosc)
            else:
                ladunek[kolumna['klucz_bl']] = (
                    _na_float(wartosc) if kolumna['liczbowa']
                    else ('' if wartosc is None else str(wartosc)))
        if dodatkowe:
            ladunek['custom_extra_fields'] = dodatkowe
        return ladunek

    if metoda == 'setOrderProductFields':
        ladunek['order_product_id'] = pozycja.bl_order_product_id
        for kolumna, wartosc in pola:
            klucz = kolumna['klucz_bl']
            ladunek[klucz] = (int(wartosc) if klucz == 'quantity'
                              else _na_float(wartosc))
        return ladunek

    if metoda == 'setOrderPayment':
        # ZAWSZE obie wartości. Dokumentacja mówi wprost: „The value changes
        # the current payment in the order (not added to the previous value)".
        # Wysłanie samej daty wyzerowałoby kwotę wpłaty.
        zmienione = {kolumna['nazwa']: wartosc for kolumna, wartosc in pola}
        kwota = zmienione.get('paid_amount', zamowienie.paid_amount)
        data = data_platnosci_efektywna(pola, zamowienie)
        ladunek['payment_done'] = _platnosc_brutto(kwota, zamowienie.price_type)
        ladunek['payment_date'] = _na_unixtime(data)
        return ladunek

    if metoda == 'setOrderStatus':
        nazwa_statusu = pola[0][1]
        identyfikator = _IDENTYFIKATORY_STATUSOW.get(nazwa_statusu)
        if identyfikator is None:
            raise BladBaselinkera(
                f'statusu „{nazwa_statusu}" nie ma w słowniku BaseLinkera')
        ladunek['status_id'] = identyfikator
        return ladunek

    raise BladBaselinkera(f"nieznana metoda API: {metoda}")


class KlientBL:
    """Cienka warstwa nad API BaseLinkera. Jedna metoda, jedno wywołanie."""

    def __init__(self, api_key: Optional[str] = None,
                 endpoint: Optional[str] = None, timeout: int = 30):
        self.api_key = api_key
        self.endpoint = endpoint or 'https://api.baselinker.com/connector.php'
        self.timeout = timeout

    def wyslij(self, metoda: str, ladunek: Dict) -> None:
        """Jedno wywołanie. Sukces = cisza, porażka = BladBaselinkera."""
        if not self.api_key:
            raise BladBaselinkera('brak konfiguracji API BaseLinkera '
                                  '(klucz w config/core.json)')
        try:
            odpowiedz = requests.post(
                self.endpoint,
                headers={'X-BLToken': self.api_key,
                         'Content-Type': 'application/x-www-form-urlencoded'},
                data={'method': metoda, 'parameters': json.dumps(ladunek)},
                timeout=self.timeout,
            )
            odpowiedz.raise_for_status()
            wynik = odpowiedz.json()
        except BladBaselinkera:
            raise
        except Exception as blad:
            raise BladBaselinkera(f'BaseLinker nie odpowiedział: {blad}')

        if wynik.get('status') != 'SUCCESS':
            raise BladBaselinkera('{} — {}'.format(
                wynik.get('error_code') or 'ERROR',
                wynik.get('error_message') or 'BaseLinker odrzucił zmianę'))


def klient_z_konfiguracji() -> KlientBL:
    """Klient zbudowany z `config/core.json` (sekcja API_BASELINKER)."""
    konfiguracja = current_app.config.get('API_BASELINKER', {}) or {}
    return KlientBL(api_key=konfiguracja.get('api_key'),
                    endpoint=konfiguracja.get('endpoint'))
