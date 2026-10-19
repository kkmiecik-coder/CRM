# -*- coding: utf-8 -*-
"""
Zamówienia w API tabletu kierownika hali (kontrakt: docs/api-mobile-kierownik.md §5.1).

`lista()` składa odpowiedź `GET /manager/orders`; `zamowienie_krotko`, `pozycja_krotko` i `klient` to klocki
współdzielone z kartą zamówienia (§5.2). Wszystkie DTO budujemy od zera, pole po polu — żadnych kwot, e-maili,
telefonów ani ulicy klienta (biała lista: `biala_lista.ZAKAZANE_KLUCZE`).

Zapytania (stała liczba, bez N+1): strona `order_id` jednym zapytaniem, zamówienia z pozycjami (`selectinload`),
trasy po `order_id IN`, statystyki jednym agregatem na całym przefiltrowanym zbiorze.
"""
import hashlib
import math
from datetime import datetime, time, timedelta

from sqlalchemy import String, case, cast, func, or_
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import routes, weryfikacja
from modules.production.models import ProductionOrder, ProductionProduct, get_local_now
from modules.production.priorytety.services import kolejka, widok
from modules.production.services import archiwum_zamowien, order_timeline_service, product_history_service
from modules.production.utils.cache import make_weak_etag

# Wersja kształtu odpowiedzi: wchodzi do ETagu, więc zmiana DTO unieważnia pamięć podręczną tabletów.
KSZTALT_ZAMOWIEN = 1

WIDOKI = ('active', 'archive', 'all')
NA_STRONE_DOMYSLNIE = 50
NA_STRONE_MAKSIMUM = 100

# Statusy dozwolone w filtrze `status` — wartości ENUM kolumny (te same, co w bazie).
STATUSY = tuple(ProductionProduct.__table__.c.current_status.type.enums)

# Zamówienie w tym statusie nie wchodzi do liczników `sztuk` i `m3` (pozycje anulowane liczą się tylko w `pozycji`).
_ANULOWANE = 'anulowane'


class BladParametru(ValueError):
    """Zły parametr zapytania; komunikat jest zdaniem po polsku do pokazania (odpowiedź 400 `dane_niepoprawne`)."""


def _data(surowa, nazwa):
    tekst = (surowa or '').strip()
    if not tekst:
        return None
    try:
        return datetime.strptime(tekst, '%Y-%m-%d').date()
    except ValueError:
        raise BladParametru(u'Parametr %s musi być datą w formacie RRRR-MM-DD.' % nazwa)


def _liczba(surowa, nazwa, domyslna, minimum, maksimum=None):
    tekst = (surowa or '').strip()
    if not tekst:
        return domyslna
    try:
        wartosc = int(tekst)
    except ValueError:
        raise BladParametru(u'Parametr %s musi być liczbą całkowitą.' % nazwa)
    if wartosc < minimum or (maksimum is not None and wartosc > maksimum):
        zakres = u'od %d' % minimum if maksimum is None else u'od %d do %d' % (minimum, maksimum)
        raise BladParametru(u'Parametr %s musi być liczbą %s.' % (nazwa, zakres))
    return wartosc


def wczytaj_parametry(args):
    """Parametry zapytania (`request.args`) → argumenty `lista()`; zły parametr = `BladParametru`."""
    widok = (args.get('view') or 'active').strip()
    if widok not in WIDOKI:
        raise BladParametru(u'Parametr view musi mieć wartość: %s.' % u', '.join(WIDOKI))
    status = (args.get('status') or '').strip() or None
    if status is not None and status not in STATUSY:
        raise BladParametru(u'Nieznany status pozycji: %s.' % status)
    od = _data(args.get('completed_from'), 'completed_from')
    do = _data(args.get('completed_to'), 'completed_to')
    if od is not None and do is not None and od > do:
        raise BladParametru(u'Data completed_from nie może być późniejsza niż completed_to.')
    return {
        'view': widok,
        'search': (args.get('search') or '').strip() or None,
        'status': status,
        'page': _liczba(args.get('page'), 'page', 1, 1),
        'per_page': _liczba(args.get('per_page'), 'per_page', NA_STRONE_DOMYSLNIE, 1, NA_STRONE_MAKSIMUM),
        'completed_from': od,
        'completed_to': do,
    }


# ── klocki DTO ──────────────────────────────────────────────────────────────────────────────────────────────────

def _liczba_lub_none(wartosc):
    return float(wartosc) if wartosc is not None else None


def _tekst(wartosc):
    return (wartosc or '').strip() or None


def klient(order):
    """Odbiorca w skrócie: imię i nazwisko z adresu dostawy (a gdy go brak, nazwa klienta), firma, miasto."""
    return {
        'nazwa': _tekst(order.delivery_fullname) or _tekst(order.client_name),
        'firma': _tekst(order.delivery_company),
        'miasto': _tekst(order.delivery_city),
    }


def objetosc_m3(pozycja):
    """m³ pozycji = objętość sztuki × liczba sztuk, do 4 miejsc."""
    return round(float(pozycja.volume_m3 or 0) * int(pozycja.quantity or 0), 4)


def pozycja_krotko(pozycja):
    """Pozycja zamówienia na liście (§5.1)."""
    return {
        'product_id': pozycja.id,
        'short_product_id': pozycja.short_product_id,
        'nazwa': pozycja.original_product_name,
        'wymiary': {
            'dlugosc_cm': _liczba_lub_none(pozycja.parsed_length_cm),
            'szerokosc_cm': _liczba_lub_none(pozycja.parsed_width_cm),
            'grubosc_cm': _liczba_lub_none(pozycja.parsed_thickness_cm),
        },
        'sztuk': int(pozycja.quantity or 0),
        'status': pozycja.current_status,
        'status_etykieta': pozycja.status_display_name,
        'm3': objetosc_m3(pozycja),
        'dorobka': pozycja.is_rework,
    }


def _status_zbiorczy(pozycje):
    """Jeden status, gdy wszystkie pozycje mają ten sam; inaczej `status: None` i napis „Różne (x/n)” (jak panel)."""
    napis = order_timeline_service.order_status_badge(pozycje)['label']
    statusy = {p.current_status for p in pozycje}
    return {'status': next(iter(statusy)) if len(statusy) == 1 else None, 'etykieta': napis}


def _etap_logistyki(pozycje):
    """
    Etap zamówienia jak w Logistyce: po spakowaniu etap najbardziej zaległej pozycji (`weryfikacja.etap`, napisy
    z panelu), przed spakowaniem jedno słowo „W produkcji” (stanowisko pokazują pozycje i status zbiorczy).
    """
    aktywne = [p for p in pozycje if p.current_status != _ANULOWANE]
    if not aktywne:
        # Zamówienie bez żadnej aktywnej pozycji (usunięte albo w całości anulowane) to „Anulowane” (§5.1).
        return {'kod': _ANULOWANE, 'etykieta': u'Anulowane'}
    status, napis = weryfikacja.etap(aktywne)
    if status in sposoby.STATUSY_PO_SPAKOWANIU:
        return {'kod': status, 'etykieta': napis}
    return {'kod': 'w_produkcji', 'etykieta': u'W produkcji'}


def termin_zamowienia(pozycje):
    """(termin, dni do terminu) — najbliższy termin aktywnej pozycji; ujemne dni = po terminie."""
    termin = kolejka.termin_zamowienia(pozycje)
    if termin is None:
        return None, None
    return termin, (termin - get_local_now().date()).days


def zamowienie_krotko(order, pozycje, trasa, zakonczono=None):
    """
    Zamówienie na liście (§5.1) bez listy `pozycje[]` (dokłada ją `lista()`); karta zamówienia (§5.2) bierze stąd
    resztę pól.
    `pozycje` — wszystkie pozycje zamówienia w kolejności z zamówienia; `trasa` — `Route` albo None; `zakonczono` —
    data zakończenia, tylko dla zamówienia archiwalnego (wtedy `ranga` jest null, bo archiwum nie stoi w kolejce).
    """
    termin, dni = termin_zamowienia(pozycje)
    sposob = sposoby.normalizuj(order.override_delivery_method)
    zliczane = [p for p in pozycje if p.current_status != _ANULOWANE]
    return {
        'order_id': order.id,
        'numer': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'quote_number': order.quote_number,
        'zrodlo': order.order_source_display,
        'klient': klient(order),
        'sposob': sposob,
        'sposob_etykieta': sposoby.etykieta(sposob),
        'termin': termin.isoformat() if termin else None,
        'dni_do_terminu': dni,
        'gwiazdki': int(order.priority_stars or 0),
        'ranga': order.priority_rank if zakonczono is None else None,
        'status_zbiorczy': _status_zbiorczy(pozycje),
        'etap_logistyki': _etap_logistyki(pozycje),
        'trasa': {'id': trasa.id, 'nazwa': trasa.name, 'status': trasa.status} if trasa is not None else None,
        'zakonczono': zakonczono.isoformat() if zakonczono else None,
        'pozycji': len(pozycje),
        'sztuk': sum(int(p.quantity or 0) for p in zliczane),
        'm3': round(sum(objetosc_m3(p) for p in zliczane), 4),
    }


def pozycje_w_kolejnosci(order):
    """Pozycje zamówienia w kolejności z zamówienia (numer w zamówieniu, potem id)."""
    return sorted(order.products, key=lambda p: (p.product_sequence_in_order or 0, p.id))


# ── zbiór zamówień ──────────────────────────────────────────────────────────────────────────────────────────────

def _wzorzec(tekst):
    """Fragment do LIKE ze znakami wieloznacznymi (%, _) traktowanymi jak zwykłe znaki (escape = `\\`)."""
    return u'%' + tekst.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + u'%'


def _warunek_szukania(tekst):
    """Te same pola co zakładka Produkty plus odbiorca z dostawy; pozycje przez EXISTS (cały order zostaje na liście)."""
    def ilike(kolumna):
        return kolumna.ilike(_wzorzec(tekst), escape='\\')

    return or_(
        ilike(ProductionOrder.client_name),
        ilike(ProductionOrder.internal_order_number),
        ilike(ProductionOrder.client_order_number),
        ilike(ProductionOrder.quote_number),
        ilike(cast(ProductionOrder.baselinker_order_id, String)),
        ilike(ProductionOrder.delivery_fullname),
        ilike(ProductionOrder.delivery_company),
        ProductionOrder.products.any(or_(
            ilike(ProductionProduct.original_product_name),
            ilike(ProductionProduct.short_product_id),
        )),
    )


def _zbior(widok, search, status, od, do, wdrozenie):
    """
    (zapytanie `order_id` + `completed_at`, podzapytanie archiwum) przefiltrowanego zbioru zamówień.
    Archiwum to dokładnie to samo zapytanie co zakładka Produkty (`archiwum_zamowien.zapytanie_archiwum`):
    `archive` łączy z nim (zakres dat siedzi w nim), `active` bierze zamówienia, których w nim nie ma,
    `all` dołącza je zewnętrznie, żeby archiwalne miały datę zakończenia.
    """
    od_dt = datetime.combine(od, time.min) if (od and widok == 'archive') else None
    do_dt = datetime.combine(do + timedelta(days=1), time.min) if (do and widok == 'archive') else None
    arch = archiwum_zamowien.zapytanie_archiwum(od_dt, do_dt, None, wdrozenie).subquery()
    na_ion = arch.c.ion == ProductionOrder.internal_order_number
    zapytanie = db.session.query(ProductionOrder.id.label('order_id'), arch.c.completed_at.label('completed_at'))
    if widok == 'archive':
        zapytanie = zapytanie.join(arch, na_ion)
    else:
        zapytanie = zapytanie.outerjoin(arch, na_ion)
        if widok == 'active':
            zapytanie = zapytanie.filter(arch.c.ion.is_(None))
    if status:
        zapytanie = zapytanie.filter(ProductionOrder.products.any(ProductionProduct.current_status == status))
    if search:
        zapytanie = zapytanie.filter(_warunek_szukania(search))
    return zapytanie, arch


def _kolejnosc(widok, arch):
    if widok == 'active':
        # Ranga rosnąco, zamówienia bez rangi na końcu (MySQL nie ma NULLS LAST).
        return (case((ProductionOrder.priority_rank.is_(None), 1), else_=0),
                ProductionOrder.priority_rank.asc(), ProductionOrder.id.asc())
    if widok == 'archive':
        return (case((arch.c.completed_at.is_(None), 1), else_=0),
                arch.c.completed_at.desc(), ProductionOrder.id.desc())
    return (ProductionOrder.id.desc(),)


def statystyki(zbior, widok, arch):
    """
    Liczniki na CAŁYM przefiltrowanym zbiorze (nie na stronie), po pozycjach tych zamówień.
    `pozycji` liczy wszystkie pozycje, `sztuk` i `m3` bez anulowanych (także w `wg_statusu`, gdzie wiersz
    „anulowane” ma `sztuk` i `m3` równe 0, żeby suma wierszy zgadzała się z liczbami ogólnymi). `*_do_spakowania`
    (tylko `active`) to licznik zakładki Produkty: niespakowane sztuki (`quantity - quantity_done_packaging`)
    pozycji spoza `STATUSY_PO_SPAKOWANIU` i anulowanych. `sredni_czas_realizacji_dni` (tylko `archive`) z
    `archiwum_zamowien.statystyki_archiwum`.
    """
    ids = zbior.order_by(None).subquery()
    objetosc = func.coalesce(ProductionProduct.volume_m3, 0)
    pozostalo = ProductionProduct.quantity - ProductionProduct.quantity_done_packaging
    wiersze = db.session.query(
        ProductionProduct.current_status,
        func.count(ProductionProduct.id),
        func.coalesce(func.sum(ProductionProduct.quantity), 0),
        func.coalesce(func.sum(objetosc * ProductionProduct.quantity), 0),
        func.coalesce(func.sum(case((pozostalo > 0, pozostalo), else_=0)), 0),
        func.coalesce(func.sum(case((pozostalo > 0, objetosc * pozostalo), else_=0)), 0),
    ).filter(
        ProductionProduct.order_id.in_(db.session.query(ids.c.order_id))
    ).group_by(ProductionProduct.current_status).all()

    wg_statusu = {}
    pozycji = sztuk = 0
    m3 = 0.0
    do_spakowania_szt = 0
    do_spakowania_m3 = 0.0
    nieliczone = sposoby.STATUSY_PO_SPAKOWANIU + (_ANULOWANE,)
    for status, ile, szt, objetosc_sumy, pozostalo_szt, pozostalo_m3 in sorted(
            wiersze, key=lambda w: STATUSY.index(w[0]) if w[0] in STATUSY else len(STATUSY)):
        liczy_sie = status != _ANULOWANE
        wg_statusu[status] = {
            'pozycji': int(ile),
            'sztuk': int(szt) if liczy_sie else 0,
            'm3': round(float(objetosc_sumy), 4) if liczy_sie else 0.0,
        }
        pozycji += int(ile)
        if liczy_sie:
            sztuk += int(szt)
            m3 += float(objetosc_sumy)
        if status not in nieliczone:
            do_spakowania_szt += int(pozostalo_szt)
            do_spakowania_m3 += float(pozostalo_m3)

    wynik = {
        'zamowien': db.session.query(func.count()).select_from(ids).scalar() or 0,
        'pozycji': pozycji,
        'sztuk': sztuk,
        'm3': round(m3, 4),
        'wg_statusu': wg_statusu,
    }
    if widok == 'active':
        wynik['sztuk_do_spakowania'] = do_spakowania_szt
        wynik['m3_do_spakowania'] = round(do_spakowania_m3, 4)
    elif widok == 'archive':
        wiersze_archiwum = zbior.order_by(None).with_entities(
            ProductionOrder.id, arch.c.completed_at, arch.c.created_at, arch.c.products_count,
            arch.c.quantity, arch.c.volume, arch.c.value).all()
        wynik['sredni_czas_realizacji_dni'] = \
            archiwum_zamowien.statystyki_archiwum(wiersze_archiwum)['archive']['avg_realization_days']
    return wynik


def lista(view, search, status, page, per_page, completed_from, completed_to):
    """Odpowiedź `GET /manager/orders` (§5.1): zamówienia strony, statystyki całego zbioru, stronicowanie."""
    wdrozenie = weryfikacja.data_wdrozenia()
    zbior, arch = _zbior(view, search, status, completed_from, completed_to, wdrozenie)
    lacznie = zbior.order_by(None).count()
    wiersze = (zbior.order_by(*_kolejnosc(view, arch))
               .limit(per_page).offset((page - 1) * per_page).all())
    ids = [w.order_id for w in wiersze]
    zakonczono = {w.order_id: w.completed_at for w in wiersze}

    zamowienia = []
    if ids:
        order_by_id = {o.id: o for o in ProductionOrder.query.options(
            selectinload(ProductionOrder.products)).filter(ProductionOrder.id.in_(ids)).all()}
        trasy = routes.trasy_zamowien(ids)
        for order_id in ids:
            order = order_by_id[order_id]
            pozycje = pozycje_w_kolejnosci(order)
            dane = zamowienie_krotko(order, pozycje, trasy.get(order_id), zakonczono.get(order_id))
            dane['pozycje'] = [pozycja_krotko(p) for p in pozycje]
            zamowienia.append(dane)

    return {
        'view': view,
        'zamowienia': zamowienia,
        'statystyki': statystyki(zbior, view, arch),
        'strona': {'page': page, 'per_page': per_page, 'lacznie': lacznie,
                   'stron': max(1, int(math.ceil(lacznie / float(per_page))))},
    }


# ── karta zamówienia (§5.2) ─────────────────────────────────────────────────────────────────────────────────────

# Kody stanowisk po wejściu (Wycinanie albo Składanie), w kolejności procesu. Te same klucze, których używa
# `order_timeline_service.product_in_route`.
_STANOWISKA_WSPOLNE = ('gluing', 'formatting', 'edges', 'painting', 'packaging')

# Wejście do procesu wg technologii (jak `getStationsForProduct` w web: mikrowczep → Wycinanie, lity → Składanie;
# bez technologii, czyli stare dane, oba).
_WEJSCIE_WG_TECHNOLOGII = {'mikrowczep': ('cutting',), 'lity': ('assembly',)}
_WEJSCIE_NIEZNANE = ('cutting', 'assembly')

# Etykiety kształtu jak w modalu pozycji w panelu (products-module.js, SHAPE_LABELS).
_KSZTALTY = {
    'rectangular': u'Prostokątny', 'circle': u'Okrągły', 'round': u'Okrągły', 'oval': u'Owal',
    'polygon': u'Wielokąt', 'parallelogram': u'Równoległobok', 'triangle_right': u'Trójkąt',
    'triangle_equilateral': u'Trójkąt', 'triangle_isosceles': u'Trójkąt', 'triangle_custom': u'Trójkąt',
    'trapezoid_symmetric': u'Trapez', 'trapezoid_asymmetric': u'Trapez', 'trapezoid_custom': u'Trapez',
    'custom': u'Niestandardowy',
}

# Rodzaje obróbki krawędzi w obu zapisach spotykanych w bazie (parser: po polsku, wycena: po angielsku).
_OBROBKI_KRAWEDZI = {
    'zaokrąglenie': u'Zaokrąglenie', 'round': u'Zaokrąglenie',
    'fazowanie': u'Fazowanie', 'chamfer': u'Fazowanie',
    'mixed': u'Zaokrąglenie i fazowanie',
}


def _wielka(tekst):
    tekst = _tekst(tekst)
    return tekst[:1].upper() + tekst[1:] if tekst else None


def _znany(tekst):
    """Pole konfiguracji; `unknown` to wartość zastępcza `find_or_create` (brak danych), nie nazwa."""
    tekst = _tekst(tekst)
    return None if tekst is None or tekst.lower() == 'unknown' else tekst


def trasa_stanowisk(pozycja):
    """
    Kody stanowisk, przez które pozycja idzie, w kolejności procesu. Wejście (Wycinanie albo Składanie) wynika z
    technologii, reszta z reguły osi czasu w webie (`order_timeline_service.product_in_route`, czyli
    `_should_skip_edges` i docięcie na wymiar) — to samo źródło, co kropki na osi czasu zamówienia.
    """
    konfiguracja = pozycja.configuration
    technologia = (_znany(konfiguracja.technology) if konfiguracja is not None else None) or u''
    wejscie = _WEJSCIE_WG_TECHNOLOGII.get(technologia.lower(), _WEJSCIE_NIEZNANE)
    return list(wejscie) + [kod for kod in _STANOWISKA_WSPOLNE
                            if order_timeline_service.product_in_route(pozycja, kod)]


def _opis_wykonczenia(pozycja):
    """„Olejowane, półmat, Brunat” — rodzaj, rodzaj koloru, połysk i kolor z pól pozycji; None, gdy brak danych."""
    czesci = [_wielka(pozycja.parsed_finish_type), _tekst(pozycja.parsed_finish_color_type),
              _tekst(pozycja.parsed_finish_gloss), _tekst(pozycja.parsed_finish_color)]
    czesci = [c for c in czesci if c]
    return u', '.join(czesci) or None


def _opis_krawedzi(pozycja):
    """
    „Zaokrąglenie R3 (A, B)” albo kilka grup po ukośniku: jak pole obróbki krawędzi w modalu pozycji w panelu.
    None, gdy pozycja nie ma obróbki krawędzi.
    """
    if not pozycja.parsed_edge_processing:
        return None
    from modules.calculator.services.edge_calculator import human_edge_label

    def grupa(rodzaj, promien, kat, litery):
        tekst = _OBROBKI_KRAWEDZI.get((rodzaj or u'').lower(), _wielka(rodzaj) or u'Obróbka')
        if promien:
            tekst += u' R%s' % promien
        if kat:
            tekst += u' %s°' % kat
        if litery:
            tekst += u' (%s)' % u', '.join(human_edge_label(l) for l in litery)
        return tekst

    grupy = [g for g in (pozycja.parsed_edges_groups or []) if isinstance(g, dict)]
    if grupy:
        return u' / '.join(grupa(g.get('type'), g.get('radius'), g.get('angle'), g.get('letters') or [])
                           for g in grupy)
    if pozycja.parsed_edge_type:
        return grupa(pozycja.parsed_edge_type, pozycja.parsed_edge_radius, pozycja.parsed_edge_angle,
                     pozycja.parsed_edge_letters or [])
    return u'Tak'


def pozycja_pelna(pozycja, razem=None):
    """
    Pozycja na karcie zamówienia (§5.2): specyfikacja opisowo, rysunki jak na tabletach stanowisk, wymiary, sztuki,
    zrobione sztuki na stanowiskach z trasy pozycji, status, termin, ranga, doróbka i uwagi produkcji.
    `razem` — liczba pozycji zamówienia (mianownik w „kolejnosc”); bez niej liczymy z `pozycja.order`.
    """
    konfiguracja = pozycja.configuration
    if razem is None:
        razem = len(pozycja.order.products) if pozycja.order is not None else 1
    trasa = trasa_stanowisk(pozycja)
    return {
        'product_id': pozycja.id,
        'short_product_id': pozycja.short_product_id,
        'nazwa': pozycja.original_product_name,
        'kolejnosc': u'%d/%d' % (pozycja.product_sequence_in_order or 0, razem),
        'specyfikacja': {
            'gatunek': _znany(konfiguracja.species) if konfiguracja is not None else None,
            'technologia': _wielka(_znany(konfiguracja.technology)) if konfiguracja is not None else None,
            'klasa': _znany(konfiguracja.wood_class) if konfiguracja is not None else None,
            'grubosc_cm': _liczba_lub_none(pozycja.parsed_thickness_cm),
            'wykonczenie': _opis_wykonczenia(pozycja),
            'krawedzie': _opis_krawedzi(pozycja),
            'ksztalt': _KSZTALTY.get(pozycja.shape, pozycja.shape) if pozycja.shape else None,
        },
        'shape_svg': pozycja.shape_svg,
        'edge_svg': pozycja.edge_svg,
        'wymiary': {
            'dlugosc_cm': _liczba_lub_none(pozycja.parsed_length_cm),
            'szerokosc_cm': _liczba_lub_none(pozycja.parsed_width_cm),
            'grubosc_cm': _liczba_lub_none(pozycja.parsed_thickness_cm),
        },
        'sztuk': int(pozycja.quantity or 0),
        'm3': objetosc_m3(pozycja),
        'zrobione': {kod: int(pozycja.get_quantity_done(kod) or 0) for kod in trasa},
        'trasa_stanowisk': trasa,
        'status': pozycja.current_status,
        'status_etykieta': pozycja.status_display_name,
        'termin': pozycja.deadline_date.isoformat() if pozycja.deadline_date else None,
        'ranga': pozycja.priority_rank,
        'dorobka': pozycja.is_rework,
        'oryginal_id': pozycja.original_product_id,
        'notatki_produkcji': _tekst(pozycja.production_notes),
    }


def _zalaczniki(order):
    """Załączniki zamówienia: dziś najwyżej jeden plik z Base. (`attachment_file_*`)."""
    url = _tekst(order.attachment_file_url)
    if url is None:
        return []
    return [{'nazwa': _tekst(order.attachment_file_name) or url.rsplit('/', 1)[-1], 'url': url}]


def _data_zakonczenia(order):
    """Data zakończenia zamówienia archiwalnego (to samo wyrażenie co w liście archiwum); None, gdy bieżące."""
    if not order.internal_order_number:
        return None
    wiersz = (archiwum_zamowien.zapytanie_archiwum(None, None, None, weryfikacja.data_wdrozenia())
              .filter(ProductionOrder.internal_order_number == order.internal_order_number).first())
    return wiersz.completed_at if wiersz is not None else None


def karta(order_id):
    """
    Odpowiedź `GET /manager/orders/<id>` (§5.2): wszystkie pola zamówienia z listy (bez skróconych `pozycje[]`),
    notatki, załączniki, miejsce na stołach stanowisk i pozycje pełne. None, gdy zamówienia nie ma. Same odczyty.
    """
    order = (ProductionOrder.query
             .options(selectinload(ProductionOrder.products).selectinload(ProductionProduct.configuration))
             .filter(ProductionOrder.id == order_id).first())
    if order is None:
        return None
    pozycje = pozycje_w_kolejnosci(order)
    trasa = routes.trasy_zamowien([order.id]).get(order.id)
    dane = zamowienie_krotko(order, pozycje, trasa, _data_zakonczenia(order))
    dane.update({
        'notatki': _tekst(order.order_notes),
        'zalaczniki': _zalaczniki(order),
        'na_stanowiskach': widok.lokalizacja_na_stolach(order.id),
        'pozycje': [pozycja_pelna(p, len(pozycje)) for p in pozycje],
    })
    return {'zamowienie': dane}


# ── historia pozycji (§5.3) ─────────────────────────────────────────────────────────────────────────────────────

# Rodzaje zdarzeń pozycji (`prod_product_events.event_type`) w nazwach kontraktu.
_RODZAJE_ZDARZEN = {'status_change': 'status', 'priority_change': 'priorytet', 'rework': 'dorobka',
                    'logistics': 'logistyka'}


def _etykieta_statusu(kod, podreczna):
    """Etykieta statusu z tego samego źródła co reszta API (`status_display_name`); kod, gdy go nie znamy."""
    if not kod:
        return None
    if kod not in podreczna:
        podreczna[kod] = ProductionProduct(current_status=kod).status_display_name
    return podreczna[kod]


def _kiedy(wpis):
    return datetime.fromisoformat(wpis['kiedy'])


def _wpis_zdarzenia(wpis, etykiety):
    rodzaj = _RODZAJE_ZDARZEN.get(wpis.get('event_type'), wpis.get('event_type'))
    wynik = {'kiedy': wpis['at'], 'rodzaj': rodzaj}
    if rodzaj == 'status':
        wynik.update({'z': wpis['old_value'], 'z_etykieta': _etykieta_statusu(wpis['old_value'], etykiety),
                      'na': wpis['new_value'], 'na_etykieta': _etykieta_statusu(wpis['new_value'], etykiety)})
    else:
        for klucz, pole in (('z', 'old_value'), ('na', 'new_value')):
            if wpis.get(pole) is not None:
                wynik[klucz] = wpis[pole]
        if _tekst(wpis.get('note')):
            wynik['opis'] = _tekst(wpis['note'])
    wynik.update({'kto': wpis['actor_label'], 'zrodlo': wpis['source']})
    return wynik


def _wpisy_pracy(wpis):
    """Grupa pracy stanowiska (zwinięta przez serwis historii) z powrotem na pojedyncze odbicia; cofnięcie to jeden wpis."""
    if wpis['kind'] == 'reject':
        return [{'kiedy': wpis['at'], 'rodzaj': 'praca', 'stanowisko': wpis['station_code'],
                 'zmiana': wpis['delta'], 'kto': wpis['actor_label'], 'zrodlo': wpis['source']}]
    # Kto fizycznie pracował przy stanowisku (profile pracowników); bez nich nazwa urządzenia albo „System”.
    kto = u', '.join(wpis.get('workers') or []) or wpis['actor_label']
    return [{'kiedy': pod['at'], 'rodzaj': 'praca', 'stanowisko': wpis['station_code'], 'zmiana': pod['delta'],
             'kto': kto, 'zrodlo': pod.get('source')} for pod in wpis['entries']]


def historia(product_id):
    """
    Odpowiedź `GET /manager/products/<id>/history` (§5.3): przepływ (kto domknął które stanowisko) i oś zdarzeń od
    najnowszych — zmiany statusu i inne zdarzenia pozycji oraz odbicia sztuk na stanowiskach (każde osobno, także
    cofnięcia). Dane z `product_history_service`, przepisane na pola kontraktu. None, gdy pozycji nie ma.
    """
    if db.session.query(ProductionProduct.id).filter(ProductionProduct.id == product_id).first() is None:
        return None
    surowa = product_history_service.build_product_history(product_id)
    etykiety = {}
    wpisy = []
    for wpis in surowa['history']:
        if wpis['kind'] == 'status':
            wpisy.append(_wpis_zdarzenia(wpis, etykiety))
        else:
            wpisy.extend(_wpisy_pracy(wpis))
    wpisy.sort(key=_kiedy, reverse=True)
    return {
        'product_id': product_id,
        'przeplyw': {kod: {'zakonczono': f['completed_at'], 'kto': f['actor_label'],
                           'pracownicy': list(f['workers'])} for kod, f in surowa['flow'].items()},
        'historia': wpisy,
    }


def etag_listy(parametry):
    """
    Słaby ETag listy: parametry (zahaszowane, bo `search` to dowolny tekst), dzień (zmienia `dni_do_terminu`) oraz
    jeden lekki agregat po pozycjach, zamówieniach i trasach — ostatnia zmiana, liczba wierszy, suma rang i
    zamknięć, które mogą zmienić się bez `updated_at`.
    """
    def skalar(zapytanie):
        return zapytanie.scalar_subquery()

    agregat = db.session.query(
        skalar(db.session.query(func.max(ProductionProduct.updated_at))),
        skalar(db.session.query(func.count(ProductionProduct.id))),
        skalar(db.session.query(func.max(ProductionOrder.updated_at))),
        skalar(db.session.query(func.count(ProductionOrder.id))),
        skalar(db.session.query(func.coalesce(func.sum(ProductionOrder.priority_rank), 0))),
        skalar(db.session.query(func.max(ProductionOrder.logistics_closed_at))),
        skalar(db.session.query(func.max(Route.updated_at))),
        skalar(db.session.query(func.count(Route.id))),
        skalar(db.session.query(func.count(RouteStop.id))),
    ).one()
    # Czasy w ISO (bez spacji — ETag ich nie dopuszcza).
    agregat = [wartosc.isoformat() if hasattr(wartosc, 'isoformat') else wartosc for wartosc in agregat]
    odcisk = hashlib.md5(repr(sorted((k, str(v)) for k, v in parametry.items())).encode('utf-8')).hexdigest()[:12]
    return make_weak_etag('kier-zam', KSZTALT_ZAMOWIEN, odcisk, get_local_now().date().isoformat(), *agregat)
