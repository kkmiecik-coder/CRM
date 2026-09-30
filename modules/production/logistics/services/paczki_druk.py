# -*- coding: utf-8 -*-
"""
Etykiety paczek (logistyka etap 4, krok 4.2, spec 6.3 i 7): dane etykiety z bazy i druk na
drukarce 'wysylka'. ZPL składa package_label (krok 4.1), kolejkuje print_queue_service.

Funkcje NIE commitują. Sygnał dla agenta druku idzie PO commicie wołającego
(print_queue_service.zaplanuj_sygnal_po_commicie).
"""
from modules.production.logistics import sposoby
from modules.production.logistics.services.routes import trasa_dla_tabletu
from modules.production.models import LabelPrintJob
from modules.production.services import package_label, print_queue_service
from modules.production.services.label_print_service import _format_finish_label

NAPISY = {sposoby.KURIER: 'KURIER', sposoby.ODBIOR: 'ODBIOR OSOBISTY',
          sposoby.TRANSPORT: 'TRANSPORT WOODPOWER'}
NIE_USTAWIONO = 'NIE USTAWIONO'
# Tyle znaków mieści pas sposobu dostawy (package_label: _ascii(dane.sposob, 26)).
MAKS_NAPISU = 26
# 'TRASA: ' + nazwa + ' dd.mm' = 26 — przy długiej nazwie ucinamy nazwę, nie datę.
MAKS_NAZWY_TRASY = 13


def napis_sposobu(order, trasa=None):
    """
    Tekst pasa sposobu dostawy (spec 6.3, pkt 2), już w ASCII i przycięty. Ten sam napis
    trafia na etykietę i do prod_packages.label_delivery_text — panel Logistyki porównuje
    go z dzisiejszym („etykiety paczek sprzed zmiany”).

    `trasa` — trasa, z której liczymy napis „TRASA: …”, albo None. Funkcja NIE sprawdza jej
    statusu, robi to wołający:
    - przy druku (`drukuj_etykiety`) to trasa AKTYWNA zamówienia (robocza/zatwierdzona,
      `routes.trasa_dla_tabletu`) albo None; trasa wykonana już nie jedzie, więc nie trafia
      na etykietę;
    - przy porównaniu w panelu (`lista._etykiety_paczek_sprzed_zmiany`) zamówienie OTWARTE dostaje
      to samo (tylko aktywna), a zamówienie ZAMKNIĘTE w Logistyce trasę w dowolnym statusie, także
      wykonaną (`routes.trasy_zamowien`): etykieta była drukowana, gdy trasa była aktywna, więc
      porównujemy z napisem „TRASA: …”, a nie z „TRANSPORT WOODPOWER”, inaczej każde zamówienie
      dowiezione trasą świeciłoby ikoną na zawsze.
    """
    sposob = sposoby.normalizuj(getattr(order, 'override_delivery_method', None))
    if sposob == sposoby.TRANSPORT and trasa is not None:
        data = trasa.date_from.strftime('%d.%m') if trasa.date_from else ''
        napis = u'TRASA: %s %s' % (package_label.tekst_ascii(trasa.name, MAKS_NAZWY_TRASY), data)
    else:
        napis = NAPISY.get(sposob, NIE_USTAWIONO)
    return package_label.tekst_ascii(napis, MAKS_NAPISU)


def _cecha(konfiguracja, nazwa):
    # find_or_create zapisuje 'unknown' dla nieparsowalnych nazw — na etykiecie puste pole.
    wartosc = getattr(konfiguracja, nazwa, None) if konfiguracja is not None else None
    return '' if wartosc in (None, '', 'unknown') else wartosc


def _aktywne(order):
    return sorted((p for p in order.products if p.current_status != 'anulowane'),
                  key=lambda p: (p.product_sequence_in_order or 0, p.id or 0))


def dane_etykiety(order, paczka, z_ilu, napis):
    """DaneEtykietyPaczki (krok 4.1) dla jednej paczki: cała zawartość zamówienia (bez
    przypisania pozycji do paczek — spec 2 pkt 5), odbiorca osoba → firma → klient
    (anonimizuje generator), wymiar tylko palety niestandardowej (EUR ma go w nazwie)."""
    aktywne = _aktywne(order)
    spakowane = [p.packaging_completed_at for p in aktywne if p.packaging_completed_at]
    niestandardowa = paczka.pallet_type == 'niestandardowa'
    return package_label.DaneEtykietyPaczki(
        numer_zamowienia=order.internal_order_number or '',
        kod_paczki=paczka.kod,
        rodzaj=paczka.kind,
        numer=paczka.seq,
        z_ilu=z_ilu,
        sposob=napis,
        odbiorca=order.delivery_fullname or order.delivery_company or order.client_name,
        pozycje=[package_label.PozycjaEtykiety(
            gatunek=_cecha(p.configuration, 'species'),
            technologia=_cecha(p.configuration, 'technology'),
            klasa=_cecha(p.configuration, 'wood_class'),
            dlugosc_cm=float(p.parsed_length_cm or 0),
            szerokosc_cm=float(p.parsed_width_cm or 0),
            grubosc_cm=float(p.parsed_thickness_cm or 0),
            ilosc=int(p.quantity or 0),
            wykonczenie=_format_finish_label(p) or None) for p in aktywne],
        typ_palety=paczka.pallet_type,
        dlugosc_cm=paczka.length_cm if niestandardowa else None,
        szerokosc_cm=paczka.width_cm if niestandardowa else None,
        m3=sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne),
        spakowano=max(spakowane).date() if spakowane else None,
        base_id=order.baselinker_order_id,
        zamowienie_klienta=order.client_order_number,
    )


def drukuj_etykiety(order, paczki, z_ilu, stanowisko, aktor, teraz):
    """
    Kolejkuje etykiety `paczki` na drukarkę 'wysylka' z BIEŻĄCYMI danymi zamówienia
    (sposób dostawy, trasa aktywna, zawartość) i zapisuje stan druku paczek. `z_ilu` —
    liczba paczek aktualnej deklaracji (mianownik „2 / 3”). Zwraca liczbę zadań.
    """
    napis = napis_sposobu(order, trasa_dla_tabletu(order.id))
    przesuniecie = package_label.wczytaj_przesuniecie()
    for paczka in paczki:
        zpl = package_label.generate_package_label_zpl(
            dane_etykiety(order, paczka, z_ilu, napis), przesuniecie)
        print_queue_service.zakolejkuj_zpl(
            LabelPrintJob.DRUKARKA_WYSYLKA, zpl, paczka.kod, stanowisko, aktor,
            baselinker_order_id=order.baselinker_order_id, package_id=paczka.id)
        paczka.label_printed_at = teraz
        paczka.label_print_count = (paczka.label_print_count or 0) + 1
        paczka.label_delivery_text = napis
    if paczki:
        print_queue_service.zaplanuj_sygnal_po_commicie(len(paczki))
    return len(paczki)
