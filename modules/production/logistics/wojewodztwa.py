# -*- coding: utf-8 -*-
"""
Województwo zamówienia z kodu pocztowego — filtr listy Logistyki (runda 2, spec 2.5;
uzupełniony rundą 2 poprawek, task 7).

Jedno źródło prawdy: PostcodeToStateMapper z modules/reports/utils.py — te same zakresy
dwucyfrowe (POSTCODE_RANGES) i wyjątki trzycyfrowe (POSTCODE_OVERRIDES) co kolumna „Region”
w eksporcie Routimo i Analiza sprzedażowa. Tu tylko opcje filtra (16 województw:
identyfikator bez polskich znaków i nazwa kanoniczna ze STATE_NORMALIZATION, oraz „Zagranica”
i „Bez województwa”) i warunek SQL.

Od task 7 KAŻDY dwucyfrowy prefiks 00–99 ma dokładnie jedno województwo — bez luk (dawniej
brakowało go dla 24, 69, 88, 89). Prefiks dwucyfrowy to okręg pocztowy, który miejscami
przecina granice województw — te miejscowości są wyjątkami trzycyfrowymi (np. 085 Ryki/Dęblin
to lubelskie, mimo że reszta prefiksu 08 to mazowieckie). Warunek SQL dopasowuje więc
województwo dwuetapowo, dokładnie jak PostcodeToStateMapper.get_state_from_postcode w
Pythonie: po zakresie dwucyfrowym z wykluczeniem WSZYSTKICH trzycyfrowych wyjątków (bo taki kod
należy do innego województwa niż reszta swojego prefiksu), plus osobno po wyjątkach
trzycyfrowych przypisanych do danego województwa.

Warunek SQL bierze dwa (p2) i trzy (p3) pierwsze znaki kodu po usunięciu myślnika i spacji
(REPLACE/SUBSTR — SQLite w testach, MySQL na produkcji). Mapa w Pythonie usuwa WSZYSTKIE
nie-cyfry, więc kod z literami przed cyframi (np. „PL-35-310”) SQL wrzuca do „Bez
województwa” — świadome przybliżenie (podpowiedź przy filtrze: „wg kodu pocztowego, w
przybliżeniu”).
"""
import unicodedata

from sqlalchemy import and_, func, or_

from modules.production.models import ProductionOrder

ZAGRANICA = 'zagranica'
BEZ_WOJEWODZTWA = 'bez_wojewodztwa'
POZOSTALE = ((ZAGRANICA, u'Zagranica'), (BEZ_WOJEWODZTWA, u'Bez województwa'))
# Kraj dostawy „Polska”: PL albo pusty — jak delivery.zmien_adres i eksport Routimo.
KRAJ_POLSKA = ('', 'PL')

_dane = None   # (województwa, prefiksy wg ident., wyjątki wg ident., wszystkie wyjątki) —
               # liczone raz na proces


def _identyfikator(nazwa):
    """'małopolskie' → 'malopolskie', 'łódzkie' → 'lodzkie' (ł nie rozkłada się w NFKD)."""
    tekst = nazwa.replace(u'ł', u'l').replace(u'Ł', u'L')
    return unicodedata.normalize('NFKD', tekst).encode('ascii', 'ignore').decode('ascii')


def _wczytaj():
    """
    Import leniwy: pakiet modules.reports przy imporcie ładuje swoje routery (pandas, eksport
    Routimo z modułu logistyki) — z poziomu modułu tworzyłby cykl z panelem logistyki
    (routimo.przygotuj_eksport importuje tę mapę tak samo, w funkcji).
    """
    global _dane
    if _dane is None:
        from modules.reports.utils import PostcodeToStateMapper
        lista, po_ident, ident_wg_klucza = [], {}, {}
        for klucz, zakresy in PostcodeToStateMapper.POSTCODE_RANGES.items():
            ident = _identyfikator(klucz)
            nazwa = PostcodeToStateMapper.STATE_NORMALIZATION.get(klucz) or klucz.capitalize()
            lista.append((ident, nazwa))
            po_ident[ident] = tuple('%02d' % n for od, do in zakresy for n in range(od, do + 1))
            ident_wg_klucza[klucz] = ident
        # Wyjątki trzycyfrowe pogrupowane wg województwa, do którego kierują (np. '085' →
        # 'lubelskie' mimo że prefiks '08' domyślnie to mazowieckie).
        po_ident_wyjatki = {}
        for kod3, klucz in PostcodeToStateMapper.POSTCODE_OVERRIDES.items():
            po_ident_wyjatki.setdefault(ident_wg_klucza[klucz], []).append(kod3)
        po_ident_wyjatki = {ident: tuple(sorted(kody)) for ident, kody in po_ident_wyjatki.items()}
        wszystkie_wyjatki = tuple(sorted(PostcodeToStateMapper.POSTCODE_OVERRIDES))
        _dane = (tuple(lista), po_ident, po_ident_wyjatki, wszystkie_wyjatki)
    return _dane


def wojewodztwa():
    """16 województw: ((identyfikator, nazwa kanoniczna), …) w kolejności mapy (alfabet)."""
    return _wczytaj()[0]


def opcje():
    """Wszystkie opcje filtra: 16 województw, „Zagranica”, „Bez województwa”."""
    return wojewodztwa() + POZOSTALE


def prefiksy(identyfikator):
    """Dwucyfrowe prefiksy kodu województwa ('35', …, '39'); dla pozostałych opcji ()."""
    return _wczytaj()[1].get(identyfikator, ())


def wyjatki(identyfikator):
    """Trzycyfrowe kody kierujące do TEGO województwa mimo innego domyślnego prefiksu
    dwucyfrowego ('085', … dla 'lubelskie'); dla województw bez wyjątków i pozostałych opcji
    ()."""
    return _wczytaj()[2].get(identyfikator, ())


def _wszystkie_wyjatki():
    """Wszystkie trzycyfrowe kody wyjątków (z dowolnego województwa) — do wykluczenia z
    dopasowania po samym dwucyfrowym zakresie, bo taki kod należy do INNEGO województwa niż
    reszta swojego prefiksu."""
    return _wczytaj()[3]


def nieznane(identyfikatory):
    """Identyfikatory spoza opcji filtra — GET /orders odpowiada na nie 422."""
    znane = {ident for ident, _ in opcje()}
    return [i for i in identyfikatory if i not in znane]


def _kod_czysty():
    kod = func.coalesce(ProductionOrder.delivery_postcode, '')
    return func.replace(func.replace(kod, '-', ''), ' ', '')


def _prefiks2():
    return func.substr(_kod_czysty(), 1, 2)


def _prefiks3():
    return func.substr(_kod_czysty(), 1, 3)


def _kraj():
    return func.upper(func.trim(func.coalesce(ProductionOrder.delivery_country_code, '')))


def warunek(identyfikatory):
    """
    Warunek SQL na zamówienie z KTÓREJKOLWIEK wybranej opcji (OR). Opcje są rozłączne i razem
    obejmują każde zamówienie: Zagranica (kraj niepusty i inny niż PL), województwo (PL albo
    pusty kraj + prefiks dwucyfrowy z mapy BEZ trzycyfrowych wyjątków, LUB trzycyfrowy wyjątek
    przypisany do tego województwa), Bez województwa (PL albo pusty kraj + prefiks spoza mapy:
    pusty/NULL kod, śmieci — po task 7 każdy prefiks dwucyfrowy 00–99 ma już województwo).
    Pusta lista albo nieznany identyfikator → ValueError (API sprawdza wcześniej przez
    nieznane() i odpowiada 422).

    Wykluczanie wyjątków w klauzuli zakresu używa PEŁNEJ listy wyjątków (nie tylko tych spod
    prefiksów wybranych województw) — to bezpieczne uproszczenie: kod spoza prefiksów
    wybranych województw i tak nie trafi w `p2 IN z_mapy`, więc dodatkowe wykluczenie go nie
    zmienia, a jedna wspólna lista jest prostsza niż liczenie wyjątków osobno na każdą
    kombinację wybranych województw.
    """
    wybrane = list(dict.fromkeys(identyfikatory))
    zle = nieznane(wybrane)
    if zle or not wybrane:
        raise ValueError(u'Nieznany filtr województwa: {}'.format(', '.join(zle)))
    kraj, p2, p3 = _kraj(), _prefiks2(), _prefiks3()
    w_polsce = kraj.in_(KRAJ_POLSKA)
    warunki = []
    z_mapy = sorted({p for i in wybrane for p in prefiksy(i)})
    z_wyjatkow = sorted({k for i in wybrane for k in wyjatki(i)})
    if z_mapy:
        warunek_zakresu = p2.in_(z_mapy)
        wszystkie_wyjatki = _wszystkie_wyjatki()
        if wszystkie_wyjatki:
            warunek_zakresu = and_(warunek_zakresu, p3.notin_(wszystkie_wyjatki))
        warunki.append(and_(w_polsce, warunek_zakresu))
    if z_wyjatkow:
        warunki.append(and_(w_polsce, p3.in_(z_wyjatkow)))
    if ZAGRANICA in wybrane:
        warunki.append(kraj.notin_(KRAJ_POLSKA))
    if BEZ_WOJEWODZTWA in wybrane:
        wszystkie = sorted({p for ident, _ in wojewodztwa() for p in prefiksy(ident)})
        warunki.append(and_(w_polsce, p2.notin_(wszystkie)))
    return or_(*warunki)
