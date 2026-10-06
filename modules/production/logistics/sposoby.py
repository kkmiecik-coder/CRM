# -*- coding: utf-8 -*-
"""
Sposoby dostawy — JEDYNE miejsce, które tłumaczy wartość
prod_orders.override_delivery_method na wszystko, co z niej wynika: tryb dla
tabletu, stare delivery_type, tekst do Base., status Base. po spakowaniu
i napis na plakietce/etykiecie.

Moduł celowo nie importuje niczego z aplikacji — czytają go models.py,
baselinker_status_sync.py i API mobilne, więc import z nich tworzyłby cykle.
"""

KURIER = 'kurier_baselinker'
TRANSPORT = 'transport_woodpower'
ODBIOR = 'odbior_osobisty'
SPOSOBY = (KURIER, TRANSPORT, ODBIOR)
# Wartość z panelu „Nie ustawiono” — cofnięcie wyboru (w bazie NULL, nie ten tekst).
BRAK = 'brak'

# Obiekt `transport.mode` w API mobilnym (kontrakt uzgodniony z appką).
MODE = {KURIER: 'kurier', TRANSPORT: 'wlasny', ODBIOR: 'odbior'}

# Stare pole `delivery_type` — tylko wartości, które znają dzisiejsze APK.
LEGACY_DELIVERY_TYPE = {KURIER: 'courier', TRANSPORT: 'transport_woodpower',
                        ODBIOR: 'personal_pickup'}

# Tekst pola „Metoda dostawy" w Base. — zawsze nadpisujemy (decyzja 24.09).
TEKST_BASE = {KURIER: 'Kurier', TRANSPORT: 'Transport WoodPower',
              ODBIOR: 'Odbiór osobisty'}

STATUS_PRODUKCJA_ZAKONCZONA = 138620
STATUS_SPAKOWANE = 138623
STATUS_PLANOWANA_TRASA = 417343
STATUS_CZEKA_NA_ODBIOR = 149777
STATUS_ODEBRANE = 149779
# Transport własny — stanowisko Dostawa (krok 4.4): „Załadowane - trans. WoodPower” po zakończeniu załadunku
# (status założony w Base. 30.09.2026), „Wysłane - trans. WoodPower” po „Ruszam”, „Dostarczona” po dostarczeniu.
STATUS_ZALADOWANE = 524520
STATUS_WYSLANE_TRANSPORT = 149763
STATUS_DOSTARCZONE_TRANSPORT = 149778

STATUS_PO_SPAKOWANIU = {KURIER: STATUS_SPAKOWANE, TRANSPORT: STATUS_PLANOWANA_TRASA,
                        ODBIOR: STATUS_CZEKA_NA_ODBIOR}

# Statusy pozycji „spakowane lub dalej” (logistyka etap 4, spec 4.1): produkcja zakończona, towar
# spakowany. Jedna stała na cały CRM — tam, gdzie kod pyta, czy pozycja wyszła z produkcji, a nie
# czy czeka dokładnie na weryfikację. W JS i szablonach — kopia listy z odsyłaczem tutaj.
# Uwaga: STATUS_PO_SPAKOWANIU (id statusów Base. wg sposobu dostawy) i STATUSY_PO_SPAKOWANIU (statusy
# pozycji) różnią się jedną literą, a znaczą co innego.
STATUSY_PO_SPAKOWANIU = ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')
# Statusy nadawane wyłącznie przez logistykę (Weryfikacja, „Wydane klientowi”, Dostawa w kroku 4.4) —
# hurtowa zmiana statusu ich nie oferuje, a deklaracja paczek po nich odmawia (409 order_verified).
STATUSY_LOGISTYCZNE = ('zweryfikowane', 'zaladowane', 'dostarczone')
# Tekst banera na tablecie pakowania przy przepakowaniu na kuriera (transport.repack_reason).
PRZEPAKUJ_NA_KURIERA = u'Przepakuj na kuriera'
# Baner po „Cofnij do pakowania” z panelu Logistyki (spec 8.7). Prefiks odróżnia baner panelu, który kolejna
# zmiana sposobu przepisuje, od powodu z Weryfikacji („Weryfikacja: …”), którego system nie nadpisuje.
PREFIKS_BANERA_LOGISTYKI = u'Logistyka: '


def baner_logistyki(sposob):
    """Tekst banera przepakowania z panelu; `sposob` None = „Nie ustawiono”."""
    s = normalizuj(sposob)
    if s is None:
        return PREFIKS_BANERA_LOGISTYKI + u'sposób dostawy do ustalenia'
    return PREFIKS_BANERA_LOGISTYKI + u'zmiana sposobu dostawy na ' + _ETYKIETA[s]


def baner_systemowy(tekst):
    """Baner, który system może nadpisać: brak, „Przepakuj na kuriera” albo baner panelu (spec 8.7)."""
    return not tekst or tekst == PRZEPAKUJ_NA_KURIERA or tekst.startswith(PREFIKS_BANERA_LOGISTYKI)


# Szacunek wagi drewna (logistyka etap 4, spec 7.1): podpowiedź paczek na tablecie pakowania,
# podsumowanie trasy i eksport Routimo liczą z tej samej gęstości (etykieta paczki ma kopię
# w package_label — test pilnuje zgodności).
WAGA_KG_NA_M3 = 800
# Podpowiedź na tablecie pakowania: szacunek powyżej progu → paleta EUR, do progu → paczka.
PROG_PALETY_KG = 40

NIE_USTAWIONO = 'Nie ustawiono'
_ETYKIETA = {KURIER: 'Kurier', TRANSPORT: 'Transport WoodPower', ODBIOR: 'Odbiór osobisty'}


def normalizuj(wartosc):
    """Wartość z bazy albo z żądania → jedna z SPOSOBY albo None."""
    if wartosc is None:
        return None
    w = str(wartosc).strip()
    return w if w in SPOSOBY else None


def etykieta(sposob, nazwa_trasy=None):
    """Napis dla człowieka: plakietka tabletu, linia „Dostawa:" na etykiecie, lista."""
    s = normalizuj(sposob)
    if s is None:
        return NIE_USTAWIONO
    if s == TRANSPORT and nazwa_trasy:
        return nazwa_trasy
    return _ETYKIETA[s]


def legacy_delivery_type(sposob):
    """Brak sposobu → 'courier': stare APK pokażą „KURIER" (świadomie, okres przejściowy)."""
    return LEGACY_DELIVERY_TYPE.get(normalizuj(sposob), 'courier')


def transport_payload(order, trasa=None):
    """
    Obiekt `transport` API mobilnego. ZAWSZE słownik, nigdy None — brak obiektu
    oznacza dla appki stary backend sprzed etapu 1 logistyki. (`mode = null` od kroku 4.6 nie blokuje już
    pakowania po stronie serwera.)
    `trasa` dochodzi w etapie 3; do tego czasu pola trip_* są puste.

    `repack_required` znaczy w API WYŁĄCZNIE „przepakuj na kuriera” (patrz _przepakowanie_na_kuriera).
    Nowa appka pokazuje baner, gdy jest `repack_reason`, a stara nie zna tego pola i przy każdym
    `repack_required = true` pokazuje na sztywno „PRZEPAKUJ NA KURIERA”. Baner z Weryfikacji
    („Weryfikacja: …”) i z panelu („Logistyka: …”) idzie więc tylko w `repack_reason`, żeby stara appka
    nie wydała pakowaczowi błędnego polecenia. Kolumna `prod_orders.repack_required` i logika CRM bez zmian.
    """
    sposob = normalizuj(getattr(order, 'override_delivery_method', None)) if order is not None else None
    pojazd = getattr(trasa, 'vehicle', None) if trasa is not None else None
    data = getattr(trasa, 'date_from', None) if trasa is not None else None
    return {
        'mode': MODE.get(sposob),
        'trip_name': trasa.name if trasa is not None else None,
        'trip_date': data.isoformat() if data is not None else None,
        'vehicle_name': pojazd.name if pojazd is not None else None,
        'repack_required': _przepakowanie_na_kuriera(order),
        'repack_reason': _tekst_przepakowania(order),
    }


def _przepakowanie_na_kuriera(order):
    """
    Czy baner dotyczy kuriera: `repack_required` jest prawdą, a powód jest pusty (stare przepakowanie sprzed
    kroku 4.3) albo równy „Przepakuj na kuriera”. Baner z Weryfikacji i z panelu to NIE jest przepakowanie
    na kuriera — dla starej appki (zna tylko `repack_required`) zostaje wtedy False.
    """
    if order is None or not getattr(order, 'repack_required', False):
        return False
    powod = getattr(order, 'repack_reason', None)
    return not powod or powod == PRZEPAKUJ_NA_KURIERA


def _tekst_przepakowania(order):
    """
    Tekst banera na tablecie pakowania (logistyka etap 4, spec 8.4 i 8.7): powód z Weryfikacji, z panelu
    Logistyki albo przepakowania na kuriera. Stare repack_required bez tekstu (sprzed kroku 4.3) → tekst
    domyślny. Bez przepakowania — None. Nowa appka pokazuje baner, gdy jest ten tekst; stara tylko przy
    `repack_required`, dlatego `repack_required` w API oznacza wyłącznie przepakowanie na kuriera.
    """
    if order is None or not getattr(order, 'repack_required', False):
        return None
    return getattr(order, 'repack_reason', None) or PRZEPAKUJ_NA_KURIERA


def podpowiedz(order):
    """Sposób, który sugeruje metoda dostawy z Base. — tylko podpowiedź dla logistyka."""
    tekst = (getattr(order, 'delivery_method', None) or '').lower()
    if getattr(order, 'is_personal_pickup', False):
        return ODBIOR
    if 'transport' in tekst and ('woodpower' in tekst or 'wood power' in tekst
                                 or 'własny' in tekst or 'wlasny' in tekst or 'nasz' in tekst):
        return TRANSPORT
    return KURIER
