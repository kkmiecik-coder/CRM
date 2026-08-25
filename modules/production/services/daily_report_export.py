# -*- coding: utf-8 -*-
"""
Eksport dziennego raportu produkcji do XLSX.

Warstwa czysto prezentacyjna: przyjmuje dict z daily_report_service.zbierz_dane()
i zwraca bajty pliku. Zero SQL, zero Flaska — dzięki temu układ arkusza da się
testować bez bazy, na ręcznie złożonym diccie.

DWIE ZASADY, KTÓRE WYGLĄDAJĄ NA DROBIAZG, A NIE SĄ:

1. Pusta komórka to NIE zero. `None` znaczy „nie dotyczy" (trakownia nie ma
   kolejki, pracownik bez atrybucji nie ma tempa), zero znaczy „policzone
   i wyszło zero". openpyxl zapisuje None jako pustą komórkę i o to chodzi.
   Ta sama zasada obowiązuje w eksporcie trakowni.

2. W nagłówkach piszemy „Różnica", nigdy Δ. Arkusz trafia do księgowości,
   która nie musi znać notacji technicznej. Wymaganie właściciela projektu,
   pilnowane testem.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from .station_catalog import STATION_LABELS

NAGLOWKI_STANOWISKA = (
    'Stanowisko', 'Sztuki', 'm³', 'Wartość netto', 'Cofnięcia',
    'W kolejce (szt.)', 'W kolejce (m³)',
)

_KLUCZE_STANOWISKA = (
    'etykieta', 'sztuki', 'm3', 'wartosc_netto', 'cofniecia',
    'kolejka_szt', 'kolejka_m3',
)

NAGLOWKI_LUDZIE = (
    'Pracownik', 'Stanowiska', 'Sztuki (wkład)', 'm³ (wkład)',
    'Zdarzenia', 'Godziny', 'm³/h',
)

_KLUCZE_LUDZIE = (
    'nazwa', 'stanowiska', 'sztuki', 'm3', 'zdarzenia', 'godziny', 'tempo',
)

# Etykiety koszyków terminów — kolejność od najpilniejszego.
_ETYKIETY_TERMINOW = (
    ('po_terminie', 'Po terminie'),
    ('dzis', 'Termin dziś'),
    ('1_2_dni', 'Termin za 1–2 dni'),
    ('3_7_dni', 'Termin za 3–7 dni'),
    ('8_dni_plus', 'Termin za 8+ dni'),
    ('bez_terminu', 'Bez terminu'),
)


def nazwa_pliku(dzien):
    """
    Nazwa załącznika — czysto ASCII.

    Polskie znaki w nagłówku Content-Disposition rwą odpowiedź (WSGI koduje
    nagłówki w latin-1); w repo jest na to osobny test regresyjny.
    """
    return f'Raport_produkcji_{dzien.isoformat()}.xlsx'


def _pogrub_naglowek(ws):
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')


def _dopasuj_szerokosci(ws, naglowki):
    for idx, naglowek in enumerate(naglowki, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = \
            max(14, len(naglowek) + 2)
    ws.freeze_panes = 'A2'


def _arkusz_dzien(ws, dane):
    """
    Podsumowanie w układzie pionowym etykieta → wartość.

    Pionowo, bo bloki mają różne jednostki: sztuki, m³, złotówki, procenty
    i godziny nie zmieszczą się sensownie w jednej siatce kolumn.
    """
    ws.append(['Raport produkcji', dane['dzien'].strftime('%d.%m.%Y')])
    ws.append([])

    wykonanie = dane['wykonanie']
    ludzie = dane['ludzie']
    trakownia = dane['trakownia']

    bloki = (
        ('WYKONANIE', (
            ('Sztuki (netto)', wykonanie['sztuki']),
            ('m³', round(wykonanie['m3'], 3)),
            ('Wartość netto (zł)', round(wykonanie['wartosc_netto'], 2)),
            ('Pozycji dotkniętych', wykonanie['pozycje']),
            ('Zamówień dotkniętych', wykonanie['zamowienia']),
            ('Cofnięcia (szt.)', wykonanie['cofniecia']),
        )),
        ('LUDZIE', (
            ('Pracowników z pracą', ludzie['osoby']),
            ('Osobogodziny', ludzie['godziny']),
            ('Pokrycie atrybucją (%)', ludzie['pokrycie_proc']),
        )),
        ('TRAKOWNIA', (
            ('Kłody', trakownia['klody']),
            ('m³', round(trakownia['m3'], 3)),
        )),
        ('ZOSTAŁO', tuple(
            [('W kolejce (szt.)', sum(s['kolejka_szt'] or 0 for s in dane['stanowiska'])),
             ('W kolejce (m³)', round(sum(s['kolejka_m3'] or 0
                                          for s in dane['stanowiska']), 3))]
            + [(etykieta, dane['terminy'][klucz])
               for klucz, etykieta in _ETYKIETY_TERMINOW]
        )),
    )

    for tytul, pozycje in bloki:
        ws.append([tytul])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        for etykieta, wartosc in pozycje:
            ws.append([etykieta, wartosc])
        ws.append([])

    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 18


def _arkusz_stanowiska(ws, dane):
    """
    Wiersz na stanowisko produkcyjne, potem trakownia, na końcu SUMA.

    Trakownia jest tu wierszem arkusza, ale NIE jest stanowiskiem w modelu:
    agregat zwraca ją osobnym blokiem, bo nie ma statusów kolejki ani wartości
    sprzedaży. Wiersz składamy tutaj, na poziomie prezentacji — dzięki temu
    agregat nie musi udawać, że hala ma osiem stanowisk.
    """
    ws.append(list(NAGLOWKI_STANOWISKA))
    _pogrub_naglowek(ws)

    for wiersz in dane['stanowiska']:
        ws.append([wiersz.get(klucz) for klucz in _KLUCZE_STANOWISKA])

    # Kłody w kolumnie „Sztuki", m³ w swojej. Wartość netto i obie kolumny
    # kolejki zostają PUSTE — trakownia ich nie ma i zero byłoby kłamstwem.
    trakownia = dane['trakownia']
    ws.append([STATION_LABELS['sawmill'], trakownia['klody'],
               round(trakownia['m3'], 3), None, None, None, None])

    ws.append([
        'SUMA',
        sum(w['sztuki'] for w in dane['stanowiska']),
        round(sum(w['m3'] for w in dane['stanowiska']), 3),
        round(sum(w['wartosc_netto'] or 0 for w in dane['stanowiska']), 2),
        sum(w['cofniecia'] for w in dane['stanowiska']),
        sum(w['kolejka_szt'] or 0 for w in dane['stanowiska']),
        round(sum(w['kolejka_m3'] or 0 for w in dane['stanowiska']), 3),
    ])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    _dopasuj_szerokosci(ws, NAGLOWKI_STANOWISKA)


def _arkusz_ludzie(ws, dane):
    ws.append(list(NAGLOWKI_LUDZIE))
    _pogrub_naglowek(ws)

    for wiersz in dane['ludzie']['wiersze']:
        ws.append([wiersz.get(klucz) for klucz in _KLUCZE_LUDZIE])

    # Wiersz obowiązkowy, także gdy wynosi zero: bez niego suma tego arkusza
    # nie zgadza się z sumą arkusza „Stanowiska" i raport wygląda na zepsuty.
    nieprzypisane = dane['ludzie']['nieprzypisane']
    ws.append(['Nieprzypisane', '', nieprzypisane['sztuki'], nieprzypisane['m3'],
               None, None, None])
    for cell in ws[ws.max_row]:
        cell.font = Font(italic=True)

    _dopasuj_szerokosci(ws, NAGLOWKI_LUDZIE)


def build_daily_xlsx(dane):
    """
    Buduje trzyarkuszowy raport z dictu zbierz_dane(). Zwraca bajty pliku.

    Args:
        dane: dict o kontrakcie daily_report_service.zbierz_dane()

    Returns:
        bytes: zawartość pliku .xlsx
    """
    wb = Workbook()

    ws_dzien = wb.active
    ws_dzien.title = 'Dzień'
    _arkusz_dzien(ws_dzien, dane)

    _arkusz_stanowiska(wb.create_sheet('Stanowiska'), dane)
    _arkusz_ludzie(wb.create_sheet('Ludzie'), dane)

    strumien = io.BytesIO()
    wb.save(strumien)
    return strumien.getvalue()
