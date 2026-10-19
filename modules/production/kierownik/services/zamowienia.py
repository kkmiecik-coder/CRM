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
from modules.production.priorytety.services import kolejka
from modules.production.services import archiwum_zamowien, order_timeline_service
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
    if not pozycje:
        return {'kod': 'w_produkcji', 'etykieta': u'W produkcji'}
    status, napis = weryfikacja.etap(aktywne)
    if status in sposoby.STATUSY_PO_SPAKOWANIU or status == _ANULOWANE:
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
