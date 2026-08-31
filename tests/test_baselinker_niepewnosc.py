# -*- coding: utf-8 -*-
"""
Kiedy naprawdę „nie wiemy, czy zamówienie powstało".

Ten jeden bool decyduje o tym, czy klient dostanie przycisk „spróbuj ponownie",
czy zostanie zablokowany z prośbą o kontakt — i czy do biura poleci alarm.
Dotąd zapalał go KAŻDY requests.RequestException, w tym nieudane nawiązanie
połączenia i błąd DNS: przy nich żądanie na pewno nie wyszło, więc blokada
była czystą stratą (utracone zamówienie plus telefon do biura).

Blokujemy wyłącznie wtedy, gdy BaseLinker MÓGŁ zobaczyć nasze żądanie.
Wątpliwości rozstrzygamy na korzyść blokady: pomyłka w tę stronę kosztuje
telefon, pomyłka w drugą — drugie realne zamówienie.
"""
import os
import sys

import requests
from urllib3.exceptions import NewConnectionError, ProtocolError

try:                                     # urllib3 >= 2.0
    from urllib3.exceptions import NameResolutionError
except ImportError:                      # urllib3 1.x (obraz testowy)
    # Rozpoznawanie po stronie serwisu idzie po NAZWIE klasy właśnie dlatego,
    # że ta klasa istnieje tylko w nowszym urllib3 — a produkcja i obraz
    # testowy mogą mieć różne wersje. Podstawiamy własną o tej samej nazwie.
    class NameResolutionError(NewConnectionError):
        def __init__(self, host, conn=None, reason=None):
            Exception.__init__(self, 'nie udało się rozwiązać %s' % host)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.baselinker.service import (  # noqa: E402
    _zadanie_moglo_dojsc_do_baselinkera as moglo_dojsc,
)


class TestZadanieNaPewnoNieWyszlo:
    """Zamówienia NA PEWNO nie ma — klient może spróbować jeszcze raz."""

    def test_connect_timeout(self):
        # Nie zdążyliśmy nawiązać połączenia, więc nic nie wysłaliśmy.
        assert moglo_dojsc(requests.exceptions.ConnectTimeout()) is False

    def test_blad_dns(self):
        blad = requests.exceptions.ConnectionError(
            NameResolutionError('api.baselinker.com', None, Exception('brak DNS')))
        assert moglo_dojsc(blad) is False

    def test_odmowa_polaczenia(self):
        blad = requests.exceptions.ConnectionError(
            NewConnectionError(None, 'Connection refused'))
        assert moglo_dojsc(blad) is False

    def test_blad_konfiguracji_adresu(self):
        assert moglo_dojsc(requests.exceptions.MissingSchema()) is False
        assert moglo_dojsc(requests.exceptions.InvalidURL()) is False

    def test_wyjatek_sprzed_wysylki(self):
        # np. ValueError z braku konfiguracji API albo błąd składania danych
        assert moglo_dojsc(ValueError('Brak konfiguracji API Baselinker')) is False


class TestNieWiemy:
    """Żądanie mogło dojść — druga próba mogłaby dołożyć drugie zamówienie."""

    def test_read_timeout(self):
        # Żądanie poszło, odpowiedź nie wróciła — zamówienie mogło powstać.
        assert moglo_dojsc(requests.exceptions.ReadTimeout()) is True

    def test_zerwane_polaczenie_w_trakcie(self):
        # ProtocolError leci także wtedy, gdy całe żądanie zdążyło wyjść.
        blad = requests.exceptions.ConnectionError(
            ProtocolError('Connection aborted', Exception('reset by peer')))
        assert moglo_dojsc(blad) is True

    def test_blad_http_od_brzegu_baselinkera(self):
        # 502/504 od proxy: żądanie dotarło do infrastruktury BaseLinkera.
        assert moglo_dojsc(requests.exceptions.HTTPError()) is True

    def test_nieznany_wyjatek_requests_traktujemy_jako_niepewny(self):
        # Domyślnie po bezpiecznej stronie: nieznany błąd transportu blokuje.
        assert moglo_dojsc(requests.exceptions.RequestException()) is True

    def test_zwykly_connection_error_bez_rozpoznanej_przyczyny(self):
        # Bez śladu, że to awaria NAWIĄZYWANIA połączenia, nie zgadujemy.
        assert moglo_dojsc(requests.exceptions.ConnectionError('coś padło')) is True


class TestOdpornoscRozpoznawania:
    def test_cykl_w_lancuchu_wyjatkow_nie_zawiesza(self):
        # Łańcuch przyczyn bywa cykliczny (__context__ w obie strony) —
        # obchodzenie go nie może zapętlić żądania klienta.
        pierwszy = requests.exceptions.ConnectionError('a')
        drugi = Exception('b')
        pierwszy.__cause__ = drugi
        drugi.__cause__ = pierwszy

        assert moglo_dojsc(pierwszy) is True
