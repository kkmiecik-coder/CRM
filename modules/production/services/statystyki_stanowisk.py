# -*- coding: utf-8 -*-
"""
Wspólna definicja liczb stanowiska i listy Lakierni: zakładka Stanowiska w panelu (`stations_api`) oraz tablet
kierownika hali (`kierownik/services/stanowiska.py`) czytają je stąd, żeby oba pokazywały te same liczby.

Same ZWYKŁE odczyty: bez blokad, bez zapisów, bez commitów i bez dopełniania stołu.
"""
from datetime import date, datetime

from sqlalchemy.orm import joinedload

from extensions import db
from modules.production.models import ProductionItem
from modules.production.services.station_catalog import STATION_PENDING_STATUS

# Kolumna daty domknięcia per stanowisko. Pobierana niżej przez getattr w try/except AttributeError, więc literówka
# w nazwie NIE wywali odczytu — pokaże ciche zero ukończonych (pilnuje tego tests/test_stanowiska_tab_krawedzie.py).
KOLUMNA_DOMKNIECIA = {
    'cutting': 'cutting_completed_at',
    'assembly': 'assembly_completed_at',
    'gluing': 'gluing_completed_at',
    'formatting': 'formatting_completed_at',
    'edges': 'edges_completed_at',
    'painting': 'painting_completed_at',
    'packaging': 'packaging_completed_at',
}


def dni_do_terminu(termin, dzis):
    """Dni do terminu z daty ISO (kafel widoku) albo None."""
    if not termin:
        return None
    try:
        return (date.fromisoformat(termin[:10]) - dzis).days
    except ValueError:
        return None


def statystyki(kod, dzis):
    """
    Liczby stanowiska `kod`: `{"total_pending", "today_completed", "today_volume"}` — pozycje czekające w statusie
    stanowiska oraz pozycje domknięte na nim od północy dnia `dzis` i ich objętość (m³ × sztuki, bez zaokrąglenia).
    Kod spoza `STATION_PENDING_STATUS` → KeyError.
    """
    total_pending = ProductionItem.query.filter_by(current_status=STATION_PENDING_STATUS[kod]).count()
    dzis_od = datetime.combine(dzis, datetime.min.time())
    try:
        kolumna = getattr(ProductionItem, KOLUMNA_DOMKNIECIA[kod])
        today_completed = ProductionItem.query.filter(kolumna >= dzis_od).count()
        today_volume = (db.session.query(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity))
                        .filter(kolumna >= dzis_od).scalar() or 0.0)
    except AttributeError:
        # Kolumny nie ma jeszcze w modelu — zero ukończonych.
        today_completed = 0
        today_volume = 0.0
    return {'total_pending': total_pending, 'today_completed': today_completed,
            'today_volume': float(today_volume)}


def lista_lakierni(dzis, limit):
    """Pierwsze `limit` pozycji listy Lakierni w kolejności tabletu (spec 3.2 „Lista Lakierni”) z nazwą grupy."""
    from modules.production.priorytety.services import lista
    pozycje = (ProductionItem.query
               .options(joinedload(ProductionItem.order), joinedload(ProductionItem.configuration))
               .filter(ProductionItem.current_status == STATION_PENDING_STATUS['painting'])
               .order_by(ProductionItem.id).all())
    wynik = []
    for p in lista.porzadek_listy('painting', pozycje)[:limit]:
        konfiguracja = p.configuration
        termin = p.deadline_date.isoformat() if p.deadline_date else None
        wynik.append({
            'product_id': p.id,
            'short_id': p.short_product_id,
            'order_id': p.order_id,
            'numer': p.order.internal_order_number if p.order else None,
            'gwiazdki': int((p.order.priority_stars if p.order else 0) or 0),
            'dorobka': p.original_product_id is not None,
            'termin': termin,
            'dni_do_terminu': dni_do_terminu(termin, dzis),
            'grupa': lista.nazwa_grupy_wykonczenia(p),
            'material': {'gatunek': konfiguracja.species if konfiguracja else None,
                         'klasa': konfiguracja.wood_class if konfiguracja else None,
                         'grubosc_cm': float(p.parsed_thickness_cm) if p.parsed_thickness_cm is not None else None},
        })
    return wynik
