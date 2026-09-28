# -*- coding: utf-8 -*-
"""
Województwo zamówienia z kodu pocztowego — filtr listy Logistyki (runda 2, spec 2.5).

Jedno źródło prawdy: PostcodeToStateMapper z modules/reports/utils.py — te same zakresy dwóch
pierwszych cyfr kodu co kolumna „Region” w eksporcie Routimo i Analiza sprzedażowa. Tu tylko
opcje filtra (16 województw: identyfikator bez polskich znaków i nazwa kanoniczna ze
STATE_NORMALIZATION, oraz „Zagranica” i „Bez województwa”) i warunek SQL.

Znane ograniczenie mapy kodów (spec 2.5; poprawa poza zakresem, decyzja Konrada): prefiksy
24, 69, 88, 89 nie mają województwa (trafiają do „Bez województwa”), a prefiks obejmujący
dwa województwa (np. 27, 96) mapa przypisuje jednemu.

Warunek SQL bierze dwa pierwsze znaki kodu po usunięciu myślnika i spacji (REPLACE/SUBSTR —
SQLite w testach, MySQL na produkcji). Mapa w Pythonie usuwa WSZYSTKIE nie-cyfry, więc kod
z literami przed cyframi (np. „PL-35-310”) SQL wrzuca do „Bez województwa” — świadome
przybliżenie (podpowiedź przy filtrze: „wg kodu pocztowego, w przybliżeniu”).
"""
import unicodedata

from sqlalchemy import and_, func, or_

from modules.production.models import ProductionOrder

ZAGRANICA = 'zagranica'
BEZ_WOJEWODZTWA = 'bez_wojewodztwa'
POZOSTALE = ((ZAGRANICA, u'Zagranica'), (BEZ_WOJEWODZTWA, u'Bez województwa'))
# Kraj dostawy „Polska”: PL albo pusty — jak delivery.zmien_adres i eksport Routimo.
KRAJ_POLSKA = ('', 'PL')

_dane = None   # (województwa, prefiksy wg identyfikatora) — liczone raz na proces


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
        lista, po_ident = [], {}
        for klucz, zakresy in PostcodeToStateMapper.POSTCODE_RANGES.items():
            ident = _identyfikator(klucz)
            nazwa = PostcodeToStateMapper.STATE_NORMALIZATION.get(klucz) or klucz.capitalize()
            lista.append((ident, nazwa))
            po_ident[ident] = tuple('%02d' % n for od, do in zakresy for n in range(od, do + 1))
        _dane = (tuple(lista), po_ident)
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


def nieznane(identyfikatory):
    """Identyfikatory spoza opcji filtra — GET /orders odpowiada na nie 422."""
    znane = {ident for ident, _ in opcje()}
    return [i for i in identyfikatory if i not in znane]


def _prefiks_kodu():
    kod = func.coalesce(ProductionOrder.delivery_postcode, '')
    return func.substr(func.replace(func.replace(kod, '-', ''), ' ', ''), 1, 2)


def _kraj():
    return func.upper(func.trim(func.coalesce(ProductionOrder.delivery_country_code, '')))


def warunek(identyfikatory):
    """
    Warunek SQL na zamówienie z KTÓREJKOLWIEK wybranej opcji (OR). Opcje są rozłączne i razem
    obejmują każde zamówienie: Zagranica (kraj niepusty i inny niż PL), województwo (PL albo
    pusty kraj + prefiks z mapy), Bez województwa (PL albo pusty kraj + prefiks spoza mapy:
    pusty/NULL kod, śmieci, 24/69/88/89). Pusta lista albo nieznany identyfikator → ValueError
    (API sprawdza wcześniej przez nieznane() i odpowiada 422).
    """
    wybrane = list(dict.fromkeys(identyfikatory))
    zle = nieznane(wybrane)
    if zle or not wybrane:
        raise ValueError(u'Nieznany filtr województwa: {}'.format(', '.join(zle)))
    kraj, prefiks = _kraj(), _prefiks_kodu()
    w_polsce = kraj.in_(KRAJ_POLSKA)
    warunki = []
    z_mapy = sorted({p for i in wybrane for p in prefiksy(i)})
    if z_mapy:
        warunki.append(and_(w_polsce, prefiks.in_(z_mapy)))
    if ZAGRANICA in wybrane:
        warunki.append(kraj.notin_(KRAJ_POLSKA))
    if BEZ_WOJEWODZTWA in wybrane:
        wszystkie = sorted({p for ident, _ in wojewodztwa() for p in prefiksy(ident)})
        warunki.append(and_(w_polsce, prefiks.notin_(wszystkie)))
    return or_(*warunki)
