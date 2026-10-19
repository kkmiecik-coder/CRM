# -*- coding: utf-8 -*-
"""
Trakownia na tablecie kierownika hali — rejestr zleceń w m³ (kontrakt: docs/api-mobile-kierownik.md §8.3 i §8.4).

Kierownik ma dostać środek między dwoma istniejącymi widokami trakowni: tablet trakowni nie widzi deklaracji w ogóle
(`serializers.DEVICE_FORBIDDEN_FIELDS`), panel biura widzi wszystko, także cenę za m³ i notatki rozliczenia. Tutaj:
deklaracje, pomiary i różnice (m³ oraz procent) TAK; pieniądze (`price_per_m3`, `declared_value`, `difference_value`)
i `settlement_notes` NIE. To była jawna decyzja użytkownika.

Dlatego DTO budujemy od zera, pole po polu, po polsku, i nie wołamy serializatorów trakowni (`serialize_order_for_panel`
zawiera pieniądze, więc nie ma jak go „odchudzić" bezpiecznie — nowa kolumna w modelu nie ma prawa sama wejść do
odpowiedzi). Liczby biorą się z tych samych funkcji co w panelu: `compute_differences` (różnica, procent i odchyłka
względem tego samego progu z ustawień), `STATUS_LABELS`, `sawmill_dashboard_stats` i `build_protocol_context` (średnie
z protokołu). `difference_value` liczy się wewnątrz `compute_differences`, ale nigdy nie jest odczytywane.

To CZYSTE ODCZYTY: bez blokad i bez commitów. Jedyny zapis żądania to znacznik kontaktu urządzenia w
`require_device_token`.
"""
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from extensions import db
from modules.production.kierownik.services import zamowienia as zam
from modules.production.models import ProductionWorker, get_local_now
from modules.production.sawmill.models import (
    ALL_STATUSES, OPEN_STATUSES, SawmillDelivery, SawmillLog, SawmillOrder,
)
from modules.production.sawmill.services.exports import (
    STATUS_LABELS, build_protocol_context, sawmill_dashboard_stats,
)
from modules.production.sawmill.services.orders import compute_differences, order_totals
from modules.production.sawmill.services.settings import get_sawmill_settings
from modules.production.utils.cache import make_weak_etag

# Wersja kształtu odpowiedzi: wchodzi do ETagu, więc zmiana DTO unieważnia pamięć podręczną tabletów.
KSZTALT_TRAKOWNI = 1

# Bez filtrów lista pokazuje otwarte zlecenia oraz dostawy z tylu ostatnich dni (kontrakt §8.3).
OKNO_DOMYSLNE_DNI = 90

_M3 = Decimal('0.0001')
_CM = Decimal('0.1')


class BladParametru(zam.BladParametru):
    """Zły parametr zapytania; komunikat jest zdaniem po polsku do pokazania (odpowiedź 400 `dane_niepoprawne`)."""


# ── parametry ────────────────────────────────────────────────────────────────────────────────────────────────────

def _data(surowa, nazwa):
    tekst = (surowa or '').strip()
    if not tekst:
        return None
    try:
        return datetime.strptime(tekst, '%Y-%m-%d').date()
    except ValueError:
        raise BladParametru(u'Parametr %s musi być datą w formacie RRRR-MM-DD.' % nazwa)


def wczytaj_parametry(args):
    """Parametry zapytania (`request.args`) → argumenty `lista()`; zły parametr = `BladParametru`."""
    status = (args.get('status') or '').strip() or None
    if status is not None and status not in ALL_STATUSES:
        raise BladParametru(u'Nieznany status zlecenia: %s.' % status)
    date_from, date_to = _data(args.get('date_from'), 'date_from'), _data(args.get('date_to'), 'date_to')
    if date_from is not None and date_to is not None and date_from > date_to:
        raise BladParametru(u'Data date_from nie może być późniejsza niż date_to.')
    return {
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
        'q': (args.get('q') or '').strip() or None,
        'only_deviation': (args.get('only_deviation') or '').strip() == '1',
    }


# ── liczby ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _m3(wartosc):
    """Objętość do 4 miejsc (kontrakt §2) jako liczba JSON; None zostaje None."""
    if wartosc is None:
        return None
    return float(Decimal(str(wartosc)).quantize(_M3, rounding=ROUND_HALF_UP))


def _cm(wartosc):
    if wartosc is None:
        return None
    return float(Decimal(str(wartosc)).quantize(_CM, rounding=ROUND_HALF_UP))


def _liczba(wartosc):
    return float(wartosc) if wartosc is not None else None


def _czas(wartosc):
    return wartosc.isoformat() if wartosc is not None else None


def _sumy_zlecen(order_ids):
    """
    {order_id: (liczba kłód, suma m³ jako Decimal)} jednym zapytaniem. To `orders.order_totals` dla wielu zleceń naraz
    (te same filtry: bez soft-skasowanych, `coalesce(sum, 0)`, ta sama konwersja przez `str`), żeby lista nie wołała
    bazy raz na zlecenie. Brak kłód = (0, Decimal('0')), jak w `order_totals`.
    """
    sumy = {order_id: (0, Decimal('0')) for order_id in order_ids}
    if not order_ids:
        return sumy
    wiersze = (db.session.query(SawmillLog.order_id, func.count(SawmillLog.id),
                                func.coalesce(func.sum(SawmillLog.volume_m3), 0))
               .filter(SawmillLog.order_id.in_(order_ids))
               .filter(SawmillLog.is_deleted.is_(False))
               .group_by(SawmillLog.order_id).all())
    for order_id, liczba, objetosc in wiersze:
        sumy[order_id] = (int(liczba), Decimal(str(objetosc)))
    return sumy


# ── DTO ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _dto_zlecenia(order, liczba_klod, zmierzone, roznice):
    """
    Zlecenie z §8.3 z gotowych liczb. `roznice` to wynik `compute_differences`: z niego czytamy tylko metry,
    procent i odchyłkę (klucz `difference_value` zostaje poza odpowiedzią).
    """
    dostawa = order.delivery
    return {
        'id': order.id,
        'numer': order.order_number,
        'status': order.status,
        'status_etykieta': STATUS_LABELS.get(order.status, order.status),
        'gatunek': order.species.name if order.species else None,
        'dostawca': dostawa.supplier.name if dostawa and dostawa.supplier else None,
        'faktura': dostawa.invoice_number if dostawa else None,
        'data_dostawy': dostawa.delivery_date.isoformat() if dostawa and dostawa.delivery_date else None,
        'zadeklarowane_m3': _liczba(order.declared_volume_m3),
        'zadeklarowane_klody': order.declared_logs_count,
        'uzgodnione_m3': _liczba(order.agreed_volume_m3),
        'zmierzone_m3': _m3(zmierzone),
        'klody': liczba_klod,
        'roznica_m3': _liczba(roznice['difference_m3']),
        'roznica_proc': _liczba(roznice['difference_pct']),
        'odchylka': bool(roznice['is_deviation']),
        'roznica_w_toku': bool(roznice['differences_pending']),
        'notatki': order.notes,
        'rozpoczeto': _czas(order.started_at),
        'zakonczono': _czas(order.completed_at),
    }


def _prog_odchylki():
    return get_sawmill_settings().get('deviation_threshold_pct', 5.0)


def _zapytanie():
    return (SawmillOrder.query
            .options(joinedload(SawmillOrder.delivery).joinedload(SawmillDelivery.supplier),
                     joinedload(SawmillOrder.species)))


def _podsumowanie():
    """Cztery liczby kafelka trakowni plus postęp otwartych zleceń: ten sam agregat co dashboard biura."""
    stat = sawmill_dashboard_stats()
    return {
        'otwarte': stat['open_orders'],
        'klody_dzis': stat['logs_today'],
        'm3_dzis': _m3(stat['volume_today_m3']),
        'do_rozliczenia': stat['to_settle'],
        'postep_proc': stat['progress_pct'],
    }


# ── lista (§8.3) ─────────────────────────────────────────────────────────────────────────────────────────────────

def lista(status=None, date_from=None, date_to=None, q=None, only_deviation=False):
    """
    `GET /manager/sawmill/orders`. Filtry jak w panelu (`panel_api.orders_list`): status, data dostawy od–do, numer
    zlecenia albo faktury i „tylko odchyłki” (po wyliczeniu różnic, bo zależą od sumy pomiarów i progu z ustawień).

    Bez `status`, `date_from`, `date_to` i `q` lista jest ograniczona do zleceń otwartych oraz dostaw z ostatnich
    90 dni. Każdy z tych czterech filtrów zdejmuje okno: status i zakres dat mają znaczyć dokładnie to, o co proszono,
    a szukanie po numerze nie może gubić starszych zleceń. `only_deviation` samo okna nie zdejmuje.
    """
    prog = _prog_odchylki()
    zapytanie = _zapytanie().join(SawmillDelivery)
    if status:
        zapytanie = zapytanie.filter(SawmillOrder.status == status)
    if date_from:
        zapytanie = zapytanie.filter(SawmillDelivery.delivery_date >= date_from)
    if date_to:
        zapytanie = zapytanie.filter(SawmillDelivery.delivery_date <= date_to)
    if q:
        zapytanie = zapytanie.filter(or_(SawmillOrder.order_number.contains(q, autoescape=True),
                                         SawmillDelivery.invoice_number.contains(q, autoescape=True)))
    if not (status or date_from or date_to or q):
        od = get_local_now().date() - timedelta(days=OKNO_DOMYSLNE_DNI)
        zapytanie = zapytanie.filter(or_(SawmillOrder.status.in_(OPEN_STATUSES), SawmillDelivery.delivery_date >= od))

    zlecenia = zapytanie.order_by(SawmillOrder.id.desc()).all()
    sumy = _sumy_zlecen([z.id for z in zlecenia])
    wiersze = []
    for zlecenie in zlecenia:
        liczba, zmierzone = sumy[zlecenie.id]
        roznice = compute_differences(zlecenie, zmierzone, prog)
        if only_deviation and not roznice['is_deviation']:
            continue
        wiersze.append(_dto_zlecenia(zlecenie, liczba, zmierzone, roznice))

    return {
        'zlecenia': wiersze,
        'podsumowanie': _podsumowanie(),
        'prog_odchylki_proc': float(prog),
    }


# ── karta (§8.4) ─────────────────────────────────────────────────────────────────────────────────────────────────

def _pracownicy(logi):
    """{id pracownika: {id, nazwa}} dla pracowników z kłód, JEDNYM zapytaniem (nie raz na kłodę)."""
    ids = {l.worker_id for l in logi if l.worker_id is not None}
    if not ids:
        return {}
    return {p.id: {'id': p.id, 'nazwa': p.short_name}
            for p in ProductionWorker.query.filter(ProductionWorker.id.in_(ids)).all()}


def zlecenie(order_id):
    """
    `GET /manager/sawmill/orders/<id>`: zlecenie jak na liście, średnie z protokołu i kłody w kolejności `lp`
    (numer kłody nadany przez serwer), bez skasowanych. `None`, gdy nie ma takiego zlecenia.

    `pracownik` to profil z tabletu, który zmierzył kłodę (`SawmillLog.worker_id`); dla pomiarów sprzed profili,
    wpisów z panelu i pracowników, których już nie ma, jest `None`.
    """
    order = _zapytanie().filter(SawmillOrder.id == order_id).first()
    if order is None:
        return None
    liczba, zmierzone = order_totals(order.id)
    roznice = compute_differences(order, zmierzone, _prog_odchylki())
    logi = (SawmillLog.query.filter_by(order_id=order.id, is_deleted=False)
            .order_by(SawmillLog.sequence_no).all())
    # Średnie z tego samego miejsca co protokół PDF (średnica i długość: to, co pracownik zmierzył).
    kontekst = build_protocol_context(order, order.delivery, logi, liczba, zmierzone, roznice)
    pracownicy = _pracownicy(logi)
    return {
        'zlecenie': _dto_zlecenia(order, liczba, zmierzone, roznice),
        'srednie': {
            'm3': _m3(kontekst['avg_volume_m3']),
            'srednica_cm': _cm(kontekst['avg_diameter_cm']),
            'dlugosc_cm': _cm(kontekst['avg_length_cm']),
        },
        'klody': [{
            'id': l.id,
            'lp': l.sequence_no,
            'srednica_cm': _liczba(l.mid_diameter_cm),
            'dlugosc_cm': _liczba(l.length_cm),
            'm3': _m3(l.volume_m3),
            'zmierzono': _czas(l.measured_at),
            'pracownik': pracownicy.get(l.worker_id),
        } for l in logi],
    }


# ── ETag ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def etag_listy(dane):
    """Słaby ETag listy: odcisk treści (zmiana czegokolwiek, co widzi kierownik, zmienia ETag)."""
    tekst = json.dumps(dane, sort_keys=True, ensure_ascii=False, default=str)
    return make_weak_etag('kier-trakownia', KSZTALT_TRAKOWNI, hashlib.md5(tekst.encode('utf-8')).hexdigest()[:20])
