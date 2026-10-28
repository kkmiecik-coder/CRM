# -*- coding: utf-8 -*-
"""Stałe agenta druku v2. Nazwy drukarek są wspólne z LabelPrintJob.DRUKARKI i konfiguracją agenta."""

# Nazwa roli drukarki (klucz = LabelPrintJob.printer) -> opis w panelu.
ROLE = {
    'etykiety': 'Drukarka etykiet 60×40',
    'wysylka': 'Drukarka paczek 100×150',
}

# Agent bez kontaktu dłużej niż tyle sekund jest uznawany za martwy (zegar serwera).
AGENT_CISZA_S = 120

# Dzierżawa zadania pobranego przez agenta, w sekundach (zegar serwera).
DZIERZAWA_S = 120

# Stany drukarki raportowane przez agenta.
STANY_DRUKARKI = ('gotowa', 'offline', 'brak_papieru', 'otwarta_klapa', 'pauza', 'blad', 'nieznany')
