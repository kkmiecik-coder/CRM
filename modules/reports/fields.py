# -*- coding: utf-8 -*-
"""Rejestr pól Analizy sprzedażowej.

JEDNA deklaracja steruje wszystkim naraz: wyglądem kolumny w arkuszu i jej
oznaczeniem, edytowalnością, potrzebą potwierdzenia przed wysyłką, metodą API
BaseLinkera przy zapisie, zawartością eksportu oraz listą wymiarów i miar
w Eksploratorze.

Stan poprzedni, którego to unika: lista statusów wpisana na sztywno w HTML
(reports.html:1163), lista gatunków powtórzona w dwóch miejscach szablonu
z niespójną wielkością liter, mapa kolumn do sortowania ręcznie wyliczona
w 44 wpisach (table_sorting.js:167). Dodanie kolumny wymagało zmian w siedmiu
plikach; teraz wymaga jednego wpisu tutaj.

Moduł celowo nie importuje niczego z Flaska ani z modeli — dzięki temu da się
go czytać i testować bez podnoszenia aplikacji.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Poziom(Enum):
    """Czy pole opisuje całe zamówienie, czy pojedynczą pozycję."""
    ZAMOWIENIE = 'zamowienie'
    POZYCJA = 'pozycja'


class Zrodlo(Enum):
    """Skąd bierze się wartość i dokąd wraca przy zapisie."""
    BL = 'bl'                # z BaseLinkera; zapis wraca do BL
    CRM = 'crm'              # tylko u nas; BaseLinker tego pola nie ma
    WYLICZANE = 'wyliczane'  # pochodna innych kolumn
    PRODUKCJA = 'produkcja'  # z modułu production; wyłącznie odczyt


class Porzadek(Enum):
    """Porządek WŁASNY wartości wymiaru — mocniejszy niż porządek po sprzedaży.

    Listy wartości wymiaru (popover porównania, filtr Eksploratora) są domyślnie
    ułożone malejąco po netto: na górze stoi to, co użytkownik najpewniej
    wybierze. Dla kanału czy opiekuna to trafne, ale dla DATY bez sensu —
    zgłoszenie użytkownika 23.09.2026: „jak kliknę »Porównanie« i mam datę,
    to daty są w losowej kolejności". Wymiar, który ma własny porządek,
    deklaruje go tutaj i lista układa się po nim, nie po obrocie.

    MALEJACO to „od najnowszej / największej", ROSNACO — odwrotnie. Zdania
    o ucięciu listy (`analiza_service._OPISY_UCIECIA`) są napisane pod TE
    dwa znaczenia, więc nowa wartość wymaga też nowego zdania.
    """
    MALEJACO = 'malejaco'
    ROSNACO = 'rosnaco'


@dataclass(frozen=True)
class SetOrderFields:
    """Zapis przez metodę BL setOrderFields. `klucz` to nazwa parametru API."""
    klucz: str


@dataclass(frozen=True)
class SetOrderCustomField:
    """Zapis przez setOrderFields, ale do custom_extra_fields[id]."""
    id_pola: str


@dataclass(frozen=True)
class SetOrderPayment:
    """Zapis przez metodę BL setOrderPayment (kwota wpłaty i jej data)."""
    klucz: str


@dataclass(frozen=True)
class SetOrderStatus:
    """Zapis przez metodę BL setOrderStatus."""


@dataclass(frozen=True)
class SetOrderProductFields:
    """Zapis przez setOrderProductFields — poziom POZYCJI, nie zamówienia."""
    klucz: str


# Jednostki miar — po polsku, dokładnie tak, jak mają się pokazać na ekranie.
# Trzymamy je jako stałe, a nie jako gołe napisy w kilkunastu miejscach: ten
# sam napis widzi użytkownik w nagłówku kolumny Eksploratora, w podpisie karty
# dashboardu i w tekście, który składa JavaScript.
ZLOTY = 'zł'
METR_SZESCIENNY = 'm³'
METR_KWADRATOWY = 'm²'
SZTUKI = 'szt.'
ZLOTY_ZA_M3 = 'zł/m³'
PROCENT = '%'


@dataclass(frozen=True)
class Pole:
    etykieta: str
    poziom: Poziom
    zrodlo: Zrodlo
    zapis: Optional[object] = None      # jeden z Set* powyżej; tylko dla Zrodlo.BL
    wrazliwe: bool = False              # zmiana rusza dokumenty poza CRM-em
    edytowalne: bool = True
    wymiar: bool = False                # nadaje się na oś w Eksploratorze
    miara: bool = False                 # nadaje się na wartość
    max_dlugosc: Optional[int] = None   # limit narzucony przez API BL
    # Jednostka wartości — to, co użytkownik ma przeczytać obok liczby.
    # Dla miary OBOWIĄZKOWA (niezmiennik niżej): bez niej powstaje kolumna
    # liczb, o której nie wiadomo, czy to złotówki, sztuki, czy metry
    # sześcienne. Właśnie tak wyglądała karta „Klienci według: liczba
    # zamówień" — kolumna złotówek czytana jako liczba klientów.
    jednostka: Optional[str] = None
    # Wymiar ZŁOŻONY: nazwy kolumn, po których grupujemy naraz. None = wymiar
    # zwykły, mający własną kolumnę. Makieta karty „Objętość i cena" pokazuje
    # „Gatunek · technologia · klasa", czyli trzy kolumny czytane jako jedna oś.
    skladniki: Optional[Tuple[str, ...]] = None
    # Porządek WŁASNY wartości — patrz `Porzadek`. None = układamy po sprzedaży,
    # malejąco, bo wtedy na górze stoi to, co użytkownik najpewniej wybierze.
    porzadek: Optional[Porzadek] = None

    def __post_init__(self):
        # Niezmiennik pilnowany też testem, ale lepiej wywalić się przy imporcie
        # niż wyprodukować kolumnę, która wygląda na edytowalną, a nie ma dokąd
        # wysłać zapisu.
        if self.zrodlo is not Zrodlo.BL and self.zapis is not None:
            raise ValueError(f"{self.etykieta}: {self.zrodlo} nie może mieć zapisu do BL")
        if self.wrazliwe and self.zapis is None:
            raise ValueError(f"{self.etykieta}: wrażliwe, ale nic nie wysyła")
        # Miara bez jednostki to liczba, której nie da się zinterpretować.
        # Wywalamy się przy imporcie, a nie dopiero na ekranie użytkownika.
        if self.miara and not self.jednostka:
            raise ValueError(f"{self.etykieta}: miara musi mieć jednostkę")
        # Porządek dotyczy LISTY WARTOŚCI wymiaru, więc na polu, które wymiarem
        # nie jest, nie miałby czego uporządkować — i nikt by się nie dowiedział,
        # że deklaracja jest martwa.
        if self.porzadek is not None and not self.wymiar:
            raise ValueError(f"{self.etykieta}: porządek własny bez wymiar=True")
        if self.skladniki is not None:
            # Wymiar złożony nie ma własnej kolumny. Gdyby dało się go oznaczyć
            # jako edytowalny albo jako miarę, arkusz Planu C wyrenderowałby
            # kolumnę, której nie ma w bazie.
            if not self.wymiar:
                raise ValueError(f"{self.etykieta}: składniki bez wymiar=True")
            if len(self.skladniki) < 2:
                raise ValueError(f"{self.etykieta}: wymiar złożony ma mieć co najmniej dwie kolumny")
            if self.zrodlo is not Zrodlo.WYLICZANE:
                raise ValueError(f"{self.etykieta}: wymiar złożony nie ma własnej kolumny, "
                                 f"więc jego źródło to WYLICZANE")
            if self.miara or self.edytowalne:
                raise ValueError(f"{self.etykieta}: wymiar złożony nie jest ani miarą, "
                                 f"ani kolumną do edycji")


_Z = Poziom.ZAMOWIENIE
_P = Poziom.POZYCJA
_BL, _CRM, _W, _PROD = Zrodlo.BL, Zrodlo.CRM, Zrodlo.WYLICZANE, Zrodlo.PRODUKCJA

# UWAGA: kolejność wpisów = domyślna kolejność kolumn w arkuszu.
POLA: Dict[str, Pole] = {
    # --- identyfikacja zamówienia ---
    # Porządek własny: daty mają iść po sobie, nie po obrocie. NAJNOWSZE NA
    # GÓRZE, bo porównanie robi się najczęściej do czegoś świeżego.
    'date_created':          Pole('Data', _Z, _BL, edytowalne=False, wymiar=True,
                                  porzadek=Porzadek.MALEJACO),
    'baselinker_order_id':   Pole('Nr BaseLinker', _Z, _BL, edytowalne=False),
    'internal_order_number': Pole('Nr wewnętrzny', _Z, _BL,
                                  zapis=SetOrderFields('extra_field_1'), max_dlugosc=50),

    # --- klient i dostawa ---
    'customer_name':     Pole('Klient', _Z, _BL, zapis=SetOrderFields('delivery_fullname'),
                              wrazliwe=True, max_dlugosc=156),
    'email':             Pole('E-mail', _Z, _BL, zapis=SetOrderFields('email'), max_dlugosc=150),
    'phone':             Pole('Telefon', _Z, _BL, zapis=SetOrderFields('phone'), max_dlugosc=100),
    'delivery_address':  Pole('Ulica i numer', _Z, _BL, zapis=SetOrderFields('delivery_address'),
                              wrazliwe=True, max_dlugosc=156),
    # max_dlugosc=20, nie 100 — kolumna sales_orders.delivery_postcode to
    # VARCHAR(20) (2026-09-22-sales-tabele.sql). Szerszy limit w rejestrze
    # niż w bazie przepuszczałby przez walidator wartość, którą MySQL utnie.
    'delivery_postcode': Pole('Kod pocztowy', _Z, _BL, zapis=SetOrderFields('delivery_postcode'),
                              wrazliwe=True, max_dlugosc=20),
    'delivery_city':     Pole('Miejscowość', _Z, _BL, zapis=SetOrderFields('delivery_city'),
                              wrazliwe=True, max_dlugosc=100),
    'delivery_state':    Pole('Województwo', _Z, _BL, zapis=SetOrderFields('delivery_state'),
                              wymiar=True, max_dlugosc=35),

    # --- kto i skąd ---
    'caretaker':     Pole('Opiekun', _Z, _BL, zapis=SetOrderCustomField('105623'), wymiar=True),
    # Etykieta z makiety (Main.dc.html:175, Eksplorator.dc.html). „Kanał
    # BaseLinkera" było nazwą techniczną; użytkownik czyta „Kanał sprzedaży".
    'order_source':  Pole('Kanał sprzedaży', _Z, _BL, edytowalne=False, wymiar=True),
    'client_origin': Pole('Pochodzenie klienta', _Z, _CRM, wymiar=True),

    # --- logistyka ---
    'delivery_method': Pole('Sposób odbioru', _Z, _BL, zapis=SetOrderFields('delivery_method'),
                            wrazliwe=True, wymiar=True, max_dlugosc=30),
    'own_transport':   Pole('Transport własny', _Z, _CRM, wymiar=True),
    'delivery_cost':   Pole('Koszt kuriera brutto', _Z, _BL,
                            zapis=SetOrderFields('delivery_price'), wrazliwe=True, miara=True,
                            jednostka=ZLOTY),

    # --- pieniądze ---
    'price_type':    Pole('Typ ceny', _Z, _BL, zapis=SetOrderCustomField('106169'), wymiar=True),
    'payment_method':Pole('Forma płatności', _Z, _BL, zapis=SetOrderFields('payment_method'),
                          wrazliwe=True, wymiar=True, max_dlugosc=30),
    'paid_amount':   Pole('Zapłacono', _Z, _BL, zapis=SetOrderPayment('payment_done'),
                          wrazliwe=True, miara=True, jednostka=ZLOTY),
    'payment_date':  Pole('Data płatności', _Z, _BL, zapis=SetOrderPayment('payment_date')),
    'balance_due':   Pole('Saldo', _Z, _W, edytowalne=False, miara=True, jednostka=ZLOTY),
    # Rozbicie wpłat na kasę i dwa rachunki. BaseLinker zna tylko jedną
    # zbiorczą kwotę payment_done, więc te sześć kolumn nie ma tam odpowiednika.
    'advance_cash':  Pole('Zaliczka gotówka', _Z, _CRM, miara=True, jednostka=ZLOTY),
    'advance_wp':    Pole('Zaliczka WP', _Z, _CRM, miara=True, jednostka=ZLOTY),
    'advance_loza':  Pole('Zaliczka Łoza', _Z, _CRM, miara=True, jednostka=ZLOTY),
    'paid_cash':     Pole('Zapłacono gotówką', _Z, _CRM, miara=True, jednostka=ZLOTY),
    'paid_wp':       Pole('Zapłacono WP', _Z, _CRM, miara=True, jednostka=ZLOTY),
    'paid_loza':     Pole('Zapłacono Łoza', _Z, _CRM, miara=True, jednostka=ZLOTY),

    # --- stan ---
    'current_status': Pole('Status', _Z, _BL, zapis=SetOrderStatus(), wrazliwe=True, wymiar=True),
    'picked_up':      Pole('Odebrane', _Z, _CRM, wymiar=True),
    'notes':          Pole('Uwagi', _Z, _BL, zapis=SetOrderFields('admin_comments'),
                           max_dlugosc=200),

    # --- sumy zamówienia (wyliczane z pozycji) ---
    # UWAGA: miara=False celowo — te kolumny nie mają odpowiednika w SalesOrder
    # (ani wyliczenia w serwisie), więc getattr(SalesOrder, nazwa) w Eksploratorze
    # wywaliłby się AttributeError. Wrócą jako miary, gdy dostaną kolumnę
    # (backfill/serwis) albo wyliczenie po stronie serwisu agregatów.
    'order_amount_net': Pole('Kwota netto zamówienia', _Z, _W, edytowalne=False,
                             jednostka=ZLOTY),
    'total_m3':         Pole('TTL m³', _Z, _W, edytowalne=False,
                             jednostka=METR_SZESCIENNY),

    # --- produkcja (tylko odczyt, źródłem jest moduł production) ---
    'gluing_done_at':     Pole('Sklejone', _Z, _PROD, edytowalne=False),
    'formatting_done_at': Pole('Docięte', _Z, _PROD, edytowalne=False),
    'packaging_done_at':  Pole('Spakowane', _Z, _PROD, edytowalne=False),
    'logistics_done_at':  Pole('Zeszło z produkcji', _Z, _PROD, edytowalne=False),
    # miara=False celowo (patrz uwaga wyżej przy order_amount_net/total_m3) —
    # lead_time_days też nie ma kolumny/wyliczenia w serwisie.
    'lead_time_days':     Pole('Czas realizacji (dni)', _Z, _W, edytowalne=False),

    # --- pozycja: konfiguracja produktu ---
    # Te siedem kolumn parser czyta z NAZWY produktu w BL, a setOrderProductFields
    # nazwy nie ustawia. Poprawka w BaseLinkerze jest więc niemożliwa i pola
    # są z definicji CRM-owe.
    'wood_species': Pole('Gatunek', _P, _CRM, wymiar=True),
    'technology':   Pole('Technologia', _P, _CRM, wymiar=True),
    'wood_class':   Pole('Klasa', _P, _CRM, wymiar=True),
    'finish_state': Pole('Wykończenie', _P, _CRM, wymiar=True),
    'length_cm':    Pole('Długość cm', _P, _CRM),
    'width_cm':     Pole('Szerokość cm', _P, _CRM),
    # Grubość to liczba i ma własny porządek: rosnąco, od najcieńszej deski.
    # Ułożona po sprzedaży dawała listę „4, 2, 6, 3, 5" — nie do przejrzenia,
    # kiedy szuka się konkretnego wymiaru surowca.
    'thickness_cm': Pole('Grubość cm', _P, _CRM, wymiar=True,
                         porzadek=Porzadek.ROSNACO),
    'group_type':   Pole('Grupa', _P, _CRM, wymiar=True),
    'product_type': Pole('Rodzaj', _P, _CRM, wymiar=True),

    # --- pozycja: wymiar złożony (nie jest kolumną bazy) ---
    # Jeden wpis rejestru rozwijany na trzy kolumny. Karta „Objętość i cena"
    # i Eksplorator dostają go automatycznie, bo iterują po wymiary().
    # UWAGA dla Planu C: to NIE jest kolumna arkusza — siatka ma pomijać wpisy
    # z `skladniki is not None`.
    'konfiguracja': Pole('Gatunek · technologia · klasa', _P, _W, edytowalne=False,
                         wymiar=True,
                         skladniki=('wood_species', 'technology', 'wood_class')),

    # --- pozycja: ilości i ceny ---
    # Z TEGO wpisu bierze jednostkę miara „szt." pulpitu (przełącznik
    # „zł / szt. / zł + szt." na kafelkach, 24.09.2026): suma `quantity`
    # pozycji bez usług (`aggregates.sztuki_bez_uslug`, klucz `sztuki`
    # w `analiza_service.JEDNOSTKI_MIAR`). Osobnego wpisu dla tej sumy celowo
    # nie ma: każdy wpis tego rejestru jest kolumną arkusza, a suma sztuk
    # nie jest kolumną żadnego zamówienia ani pozycji — jest agregatem
    # pulpitu, tak jak objętość pulpitu jest sumą `total_volume`.
    'quantity':    Pole('Ilość', _P, _BL, zapis=SetOrderProductFields('quantity'),
                        wrazliwe=True, miara=True, jednostka=SZTUKI),
    'price_gross': Pole('Cena brutto', _P, _BL, zapis=SetOrderProductFields('price_brutto'),
                        wrazliwe=True, miara=True, jednostka=ZLOTY),
    'price_net':        Pole('Cena netto', _P, _W, edytowalne=False, miara=True,
                             jednostka=ZLOTY),
    'value_gross':      Pole('Wartość brutto', _P, _W, edytowalne=False, miara=True,
                             jednostka=ZLOTY),
    'value_net':        Pole('Wartość netto', _P, _W, edytowalne=False, miara=True,
                             jednostka=ZLOTY),
    'volume_per_piece': Pole('Objętość 1 szt.', _P, _W, edytowalne=False,
                             jednostka=METR_SZESCIENNY),
    'total_volume':     Pole('Objętość TTL', _P, _W, edytowalne=False, miara=True,
                             jednostka=METR_SZESCIENNY),
    'total_surface_m2': Pole('Powierzchnia m²', _P, _W, edytowalne=False, miara=True,
                             jednostka=METR_KWADRATOWY),
    'price_per_m3':     Pole('Cena za m³', _P, _W, edytowalne=False, miara=True,
                             jednostka=ZLOTY_ZA_M3),
}


def wymiary() -> List[str]:
    """Nazwy pól, po których wolno grupować w Eksploratorze."""
    return [n for n, p in POLA.items() if p.wymiar]


def wymiary_proste() -> List[str]:
    """Wymiary mające własną kolumnę — tylko po nich wolno filtrować.

    Wartość wymiaru złożonego to krotka trzech kolumn i nie przechodzi przez
    format filtra w adresie (`?filtr=pole:wartość`), więc selektor filtra
    i endpoint wartości wymiaru biorą listę stąd, nie z `wymiary()`.
    """
    return [n for n, p in POLA.items() if p.wymiar and p.skladniki is None]


def miary() -> List[str]:
    """Nazwy pól, które wolno sumować."""
    return [n for n, p in POLA.items() if p.miara]


def pola_poziomu(poziom: Poziom) -> Dict[str, Pole]:
    return {n: p for n, p in POLA.items() if p.poziom is poziom}
