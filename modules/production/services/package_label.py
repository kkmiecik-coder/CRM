# -*- coding: utf-8 -*-
"""
Etykieta paczki 100x150 mm dla drukarki `wysylka` (logistyka etap 4, spec sekcja 6.3).

Czyste funkcje: dostają gotowe dane (DaneEtykietyPaczki) i zwracają ZPL. Z bazy
czytamy tylko przesunięcie z panelu. Dane paczki zbiera w kroku 4.2 serwis paczek.

Zasady druku (ustalone z Konradem 30.09 na wzorach z zamówienia 1450):
- tylko ASCII: emulacja ZPL drukarek Xprinter nie ma polskich znaków (z
  „ĄĆĘŁŃÓŚŹŻ" wyszło tylko Ó), więc litery zamieniamy jak na etykietach
  produktów, a resztę spoza ASCII usuwamy;
- odbiorca zanonimizowany i ZERO danych adresowych — pełne dane są w CRM pod
  kodem paczki;
- treść w marginesie 3 mm i nad y=1130: po kalibracji drukarka i tak zostawia
  kilka milimetrów luzu, a resztę wyrównuje przesunięcie z panelu.
"""
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from modules.production.models import ProductionConfig
from modules.production.services.label_print_service import _tekst_pola_zpl

SZEROKOSC = 800          # 100 mm przy 203 dpi (8 punktów na mm)
WYSOKOSC = 1200          # 150 mm
MARGINES = 24            # 3 mm
MAKS_WIERSZY = 14        # pozycji na etykiecie; przy większej liczbie 13 + „+ N pozycji"
# Znaków opisu pozycji razem z numerem wiersza i „...”. Dobrane z Konradem 2.10 na XP-410B
# (wydruk próbny 56–82 znaki): przy 60 zostaje wyraźny odstęp od kolumny „N szt.”,
# która jest wyrównana do prawej krawędzi (x=600..768), więc tekst może zachodzić za x=600.
MAKS_OPISU = 60
# Kopia sposoby.WAGA_KG_NA_M3 (logistyka etap 4) — test pilnuje zgodności. Import zamiast
# kopii ładowałby pakiet modules.production.logistics z jego routerami, a ten moduł ma
# zostać lekki (czytają go serwisy druku).
WAGA_KG_NA_M3 = 800

KLUCZ_PRZESUNIECIA_X = 'PACKAGE_LABEL_OFFSET_X_DOTS'
KLUCZ_PRZESUNIECIA_Y = 'PACKAGE_LABEL_OFFSET_Y_DOTS'
MAKS_PRZESUNIECIA = 120  # 15 mm — większe przesunięcie to źle założona rolka, nie kalibracja
# Prędkość druku w calach na sekundę (^PR). Test 30.09 na XP-410B: 3 cale/s daje wyraźnie
# lepszą czerń niż domyślne 6, a kod QR skanujemy telefonem. Ok. 2 s więcej na etykietę
# nie ma znaczenia przy pakowaniu.
PREDKOSC_DRUKU_CALE_S = 3
# Numer zamówienia klienta w stopce: dłuższy nie mieści się w jednej linii z adresem firmy (736 punktów).
MAKS_ZAMOWIENIA_KLIENTA = 15


@dataclass
class PozycjaEtykiety:
    gatunek: str
    technologia: str
    klasa: str
    dlugosc_cm: float
    szerokosc_cm: float
    grubosc_cm: float
    ilosc: int
    wykonczenie: Optional[str] = None      # None albo 'surowe' = nie dopisujemy


@dataclass
class DaneEtykietyPaczki:
    numer_zamowienia: str
    kod_paczki: str                        # 'P-<id>' — treść QR
    rodzaj: str                            # 'paczka' | 'paleta'
    numer: int                             # 1..z_ilu
    z_ilu: int
    sposob: str                            # gotowy tekst pasa, np. 'KURIER', 'TRASA: Rzeszow 07.10'
    odbiorca: Optional[str]                # pełna nazwa — anonimizuje generator
    pozycje: List[PozycjaEtykiety] = field(default_factory=list)
    typ_palety: Optional[str] = None       # 'eur' | 'niestandardowa'
    dlugosc_cm: Optional[int] = None       # wymiar palety niestandardowej
    szerokosc_cm: Optional[int] = None
    m3: float = 0.0
    spakowano: Optional[date] = None
    base_id: Optional[int] = None
    zamowienie_klienta: Optional[str] = None


def _ascii(tekst, maks):
    """Tekst pola ZPL: bez komend (^, ~), jedna linia, polskie litery zamienione,
    reszta spoza ASCII usunięta."""
    czysty = _tekst_pola_zpl(tekst or '', maks)
    return unicodedata.normalize('NFKD', czysty).encode('ascii', 'ignore').decode('ascii')


def tekst_ascii(tekst, maks):
    """Publiczne _ascii: napis pasa sposobu dostawy składa serwis paczek
    (logistics/services/paczki_druk.py) i porównuje go z zapisanym na paczce."""
    return _ascii(tekst, maks)


def anonimizuj_odbiorce(nazwa):
    """„Dariusz Kowalczyk" → „Dar*** Kow***": dwa pierwsze słowa, z każdego 3 znaki."""
    slowa = _ascii(nazwa, 200).split()[:2]
    return ' '.join(s[:3] + ('***' if len(s) > 3 else '') for s in slowa)


def _wymiar(wartosc):
    liczba = float(wartosc or 0)
    return str(int(liczba)) if liczba == int(liczba) else '%.1f' % liczba


def opis_rodzaju(dane):
    if dane.rodzaj == 'paleta':
        if dane.typ_palety == 'eur':
            return 'PALETA EUR 120x80'
        if dane.dlugosc_cm and dane.szerokosc_cm:
            return 'PALETA %dx%d' % (int(dane.dlugosc_cm), int(dane.szerokosc_cm))
        return 'PALETA'
    return 'PACZKA'


def _wiersz_pozycji(numer, pozycja):
    opis = '%d. %s %s %s %sx%sx%s cm' % (
        numer, (pozycja.gatunek or '').capitalize(), pozycja.technologia or '',
        pozycja.klasa or '', _wymiar(pozycja.dlugosc_cm), _wymiar(pozycja.szerokosc_cm),
        _wymiar(pozycja.grubosc_cm))
    if pozycja.wykonczenie and pozycja.wykonczenie.strip().lower() != 'surowe':
        opis += ', ' + pozycja.wykonczenie.strip()
    return _ascii(opis, MAKS_OPISU)


class _Zpl:
    """Składa etykietę 100x150; każde pole dostaje przesunięcie z panelu (bez ^LH,
    bo ^LH nie przyjmuje wartości ujemnych). Współrzędne nigdy nie schodzą poniżej 0."""

    def __init__(self, przesuniecie):
        self.dx, self.dy = przesuniecie
        self.linie = ['^XA', '^PR%d' % PREDKOSC_DRUKU_CALE_S, '^CI0',
                      '^PW%d' % SZEROKOSC, '^LL%d' % WYSOKOSC, '^LH0,0']

    def pole(self, x, y, tresc):
        self.linie.append('^FO%d,%d%s' % (max(0, x + self.dx), max(0, y + self.dy), tresc))

    def gotowe(self):
        return '\n'.join(self.linie + ['^XZ']) + '\n'


def generate_package_label_zpl(dane, przesuniecie=(0, 0)):
    """ZPL etykiety paczki. Układ zatwierdzony na wzorze 30.09 (spec 6.3)."""
    z = _Zpl(przesuniecie)
    numer = _ascii(dane.numer_zamowienia, 8)
    czcionka_numeru = '^A0N,140,120' if len(numer) <= 5 else '^A0N,110,90'

    # 1. Nagłówek: numer zamówienia + czarny kafel rodzaju i numeru paczki
    z.pole(32, 24, '^A0N,28,28^FDZAMOWIENIE^FS')
    z.pole(32, 54, '%s^FD%s^FS' % (czcionka_numeru, numer))
    z.pole(440, 24, '^GB328,166,166^FS')
    z.pole(440, 40, '^FB328,1,0,C^A0N,52,52^FR^FD%s^FS'
           % ('PALETA' if dane.rodzaj == 'paleta' else 'PACZKA'))
    z.pole(440, 100, '^FB328,1,0,C^A0N,84,84^FR^FD%d / %d^FS' % (int(dane.numer), int(dane.z_ilu)))

    # 2. Pas sposobu dostawy (biały na czarnym)
    z.pole(32, 204, '^GB736,72,72^FS')
    z.pole(32, 216, '^FB736,1,0,C^A0N,52,52^FR^FD%s^FS' % _ascii(dane.sposob, 26))

    # 3. Odbiorca — tylko zanonimizowana nazwa, bez żadnych danych adresowych
    z.pole(32, 292, '^A0N,26,26^FDODBIORCA^FS')
    z.pole(32, 322, '^A0N,46,44^FD%s^FS' % anonimizuj_odbiorce(dane.odbiorca))
    z.pole(32, 378, '^GB736,3,3^FS')

    # 4. QR i opis paczki
    kod = _ascii(dane.kod_paczki, 20)
    m3 = float(dane.m3 or 0)
    sztuk = sum(int(p.ilosc or 0) for p in dane.pozycje)
    z.pole(24, 390, '^BQN,2,11^FDLA,%s^FS' % kod)
    z.pole(330, 406, '^A0N,56,52^FD%s^FS' % kod)
    z.pole(330, 472, '^A0N,36,34^FD%s^FS' % opis_rodzaju(dane))
    z.pole(330, 516, '^A0N,32,30^FDWaga szac.: ok. %d kg^FS' % round(m3 * WAGA_KG_NA_M3))
    z.pole(330, 556, '^A0N,32,30^FD%d poz. / %d szt. / %s m3^FS'
           % (len(dane.pozycje), sztuk, ('%.3f' % m3).replace('.', ',')))
    if dane.spakowano:
        z.pole(330, 596, '^A0N,28,28^FDSpakowano: %s^FS' % dane.spakowano.strftime('%d.%m.%Y'))
    z.pole(32, 640, '^GB736,3,3^FS')

    # 5. Zawartość całego zamówienia
    z.pole(32, 652, '^A0N,28,28^FDZAWARTOSC ZAMOWIENIA^FS')
    widoczne = (dane.pozycje if len(dane.pozycje) <= MAKS_WIERSZY
                else dane.pozycje[:MAKS_WIERSZY - 1])
    y = 690
    for numer_wiersza, pozycja in enumerate(widoczne, 1):
        z.pole(32, y, '^A0N,27,25^FD%s^FS' % _wiersz_pozycji(numer_wiersza, pozycja))
        z.pole(600, y, '^FB168,1,0,R^A0N,27,25^FD%d szt.^FS' % int(pozycja.ilosc or 0))
        y += 28
    reszta = dane.pozycje[len(widoczne):]
    if reszta:
        z.pole(32, y, '^A0N,27,25^FD+ %d pozycji (%d szt.) - pelna lista w CRM^FS'
               % (len(reszta), sum(int(p.ilosc or 0) for p in reszta)))

    # 6. Stopka. Numer Base. to liczba z bazy — int() pilnuje formatu pola.
    base = '%d' % int(dane.base_id) if dane.base_id else '-'
    z.pole(32, 1100, '^GB736,2,2^FS')
    z.pole(32, 1108, '^A0N,22,22^FDBase.: %s   Zam. klienta: %s   WoodPower, Bachorz 14N^FS'
           % (base, _ascii(dane.zamowienie_klienta or '-', MAKS_ZAMOWIENIA_KLIENTA)))
    return z.gotowe()


def generate_test_label_zpl(przesuniecie=(0, 0)):
    """Etykieta próbna drukarki paczek: ramka 3 mm od krawędzi, bieżące przesunięcie, QR.
    Po kalibracji i dobrym przesunięciu ramka ma równy odstęp od wszystkich krawędzi."""
    z = _Zpl(przesuniecie)
    z.pole(MARGINES, MARGINES, '^GB%d,%d,4^FS' % (SZEROKOSC - 2 * MARGINES, WYSOKOSC - 2 * MARGINES))
    z.pole(60, 80, '^A0N,64,60^FDWYDRUK PROBNY^FS')
    z.pole(60, 160, '^A0N,36,34^FDDrukarka paczek 100x150^FS')
    z.pole(60, 230, '^A0N,30,28^FDRamka: 3 mm od kazdej krawedzi.^FS')
    z.pole(60, 270, '^A0N,30,28^FDNierowno? Popraw przesuniecie w panelu^FS')
    z.pole(60, 310, '^A0N,30,28^FD(8 punktow = 1 mm) i drukuj ponownie.^FS')
    z.pole(60, 370, '^A0N,30,28^FDPrzesuniecie teraz: X=%d, Y=%d^FS' % przesuniecie)
    z.pole(60, 440, '^BQN,2,11^FDLA,P-TEST^FS')
    z.pole(60, 1100, '^A0N,28,28^FDDol tresci (y=1100)^FS')
    return z.gotowe()


def _przesuniecie_z_tekstu(surowe):
    try:
        wartosc = int(str(surowe).strip())
    except (TypeError, ValueError):
        return 0
    return max(-MAKS_PRZESUNIECIA, min(MAKS_PRZESUNIECIA, wartosc))


def wczytaj_przesuniecie():
    """(dx, dy) w punktach z prod_config. Brak klucza albo śmieci = 0, poza zakresem =
    przycięte do ±MAKS_PRZESUNIECIA (panel waliduje zapis, ale ręczna zmiana w bazie
    nie może zepsuć druku)."""
    wiersze = {
        c.config_key: c.config_value
        for c in ProductionConfig.query.filter(
            ProductionConfig.config_key.in_((KLUCZ_PRZESUNIECIA_X, KLUCZ_PRZESUNIECIA_Y))).all()
    }
    return (_przesuniecie_z_tekstu(wiersze.get(KLUCZ_PRZESUNIECIA_X)),
            _przesuniecie_z_tekstu(wiersze.get(KLUCZ_PRZESUNIECIA_Y)))
