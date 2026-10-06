# modules/production/routers/api/stations_api.py
"""
Stations tab content endpoints.
Extracted from api_routers.py.

Zakładka Stanowiska jest CZYTELNIKIEM priorytetów (krok K4b, spec 7.2): pokazuje to samo, co tablet — stół,
odłożone, niekompletne (Formatowanie, Pakowanie) i pierwsze 15 kafli kolejki każdego stanowiska — z tych samych
funkcji `priorytety/services/widok.py`, które stoją za `GET /production/api/priorytety/stoly` i `/kolejka`.
Lakiernia nie ma stołu: zamiast kolejki pokazuje pierwsze 15 pozycji listy po wykończeniu (`lista.porzadek_listy`,
ta sama funkcja co tablet). Same zwykłe odczyty: bez blokad, bez zapisów i BEZ dopełniania stołu (dopełnia
wyłącznie `GET desk` tabletu, spec 5.2).
"""

from datetime import datetime, date
from flask import jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy.orm import joinedload

from . import api_bp, logger, ProductionItem, get_local_now

# Ile kafli kolejki (i pozycji listy Lakierni) pokazuje karta stanowiska.
LIMIT_KAFLI_ZAKLADKI = 15


def _dni_do_terminu(termin, dzis):
    """Dni do terminu z daty ISO (kafel widoku) albo None."""
    if not termin:
        return None
    try:
        return (date.fromisoformat(termin[:10]) - dzis).days
    except ValueError:
        return None


def _z_terminem(kafle, dzis):
    for kafel in kafle:
        kafel['dni_do_terminu'] = _dni_do_terminu(kafel.get('termin'), dzis)
    return kafle


def _lista_lakierni(dzis):
    """Pierwsze pozycje listy Lakierni w kolejności tabletu (spec 3.2 „Lista Lakierni”) z nazwą grupy."""
    from ...priorytety.services import lista
    from ...services.station_catalog import STATION_PENDING_STATUS
    pozycje = (ProductionItem.query
               .options(joinedload(ProductionItem.order), joinedload(ProductionItem.configuration))
               .filter(ProductionItem.current_status == STATION_PENDING_STATUS['painting'])
               .order_by(ProductionItem.id).all())
    wynik = []
    for p in lista.porzadek_listy('painting', pozycje)[:LIMIT_KAFLI_ZAKLADKI]:
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
            'dni_do_terminu': _dni_do_terminu(termin, dzis),
            'grupa': lista.nazwa_grupy_wykonczenia(p),
            'material': {'gatunek': konfiguracja.species if konfiguracja else None,
                         'klasa': konfiguracja.wood_class if konfiguracja else None,
                         'grubosc_cm': float(p.parsed_thickness_cm) if p.parsed_thickness_cm is not None else None},
        })
    return wynik


def _priorytety_stanowisk(stations, dzis):
    """
    Stół, odłożone, niekompletne i kolejka każdego stanowiska ze stołem + lista Lakierni. Wyjątek warstwy
    priorytetów (np. brak tabel w oknie wdrożenia) nie kładzie zakładki: (None, log ERROR) — sekcje znikają,
    reszta danych zostaje.
    """
    from ...priorytety.services import ustawienia, widok
    try:
        stoly = {s['stanowisko']: s for s in widok.stoly_panelu()}
        wynik = {}
        for kod in stations:
            if kod in ustawienia.STANOWISKA_BEZ_STOLU:
                wynik[kod] = {'kolejka': _lista_lakierni(dzis)}
                continue
            kolejka = widok.kolejka_stanowiska(kod, limit=LIMIT_KAFLI_ZAKLADKI)
            stol = stoly.get(kod)
            if stol is None:
                continue
            wynik[kod] = {
                'tryb': stol['tryb'],
                'jednostka': stol['jednostka'],
                'stol': _z_terminem(stol['stol'], dzis),
                'odlozone': _z_terminem(stol['odlozone'], dzis),
                'widma': stol.get('widma', []),
                'niekompletne': kolejka['niekompletne'],
                'kolejka': _z_terminem(kolejka['kafle'], dzis),
                'stats': {'na_stole': len(stol['stol']), 'miejsca': stol['miejsca'],
                          'odlozone': len(stol['odlozone']), 'limit_odlozen': stol['limit_odlozen'],
                          'kolejka_dalej': stol['kolejka_dalej']},
            }
        return wynik
    except Exception as e:
        db.session.rollback()       # zwykły odczyt: nic do cofnięcia poza zepsutą migawką sesji
        logger.error("Zakładka Stanowiska: stół i kolejka niedostępne", extra={'error': str(e)})
        return None


@api_bp.route('/stations-tab-content')
@login_required
def stations_tab_content():
    """
    AJAX endpoint dla zawartości taba Stanowiska: stół, odłożone, niekompletne i kolejka każdego stanowiska
    (to samo co tablet) oraz dzisiejsze wykonania.
    """
    try:
        logger.info("AJAX: Ładowanie zawartości stations-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem
        from ...services.station_catalog import STATION_ORDER, STATION_PENDING_STATUS

        # Dane dla każdego stanowiska
        stations_data = {}
        stations = list(STATION_ORDER)
        dzis = date.today()
        priorytety = _priorytety_stanowisk(stations, dzis)

        for station in stations:
            status = STATION_PENDING_STATUS[station]

            # Statystyki stanowiska
            total_pending = ProductionItem.query.filter_by(current_status=status).count()

            # Dzisiejsze wykonania
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())

            # Kolumna daty domknięcia per stanowisko. Pobierana niżej przez
            # getattr w try/except AttributeError, więc literówka w nazwie
            # NIE wywali endpointu — pokaże ciche zero ukończonych.
            completed_field_map = {
                'cutting': 'cutting_completed_at',
                'assembly': 'assembly_completed_at',
                'gluing': 'gluing_completed_at',
                'formatting': 'formatting_completed_at',
                'edges': 'edges_completed_at',
                'painting': 'painting_completed_at',
                'packaging': 'packaging_completed_at'
            }

            field_name = completed_field_map[station]

            # Sprawdź czy pole istnieje w modelu
            try:
                completed_field = getattr(ProductionItem, field_name)
                today_completed = ProductionItem.query.filter(
                    completed_field >= today_start
                ).count()

                today_volume = db.session.query(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity))\
                                       .filter(completed_field >= today_start)\
                                       .scalar() or 0.0
            except AttributeError:
                # Pole nie istnieje jeszcze w modelu - zwróć 0
                today_completed = 0
                today_volume = 0.0

            dane = {
                'name': {
                    'cutting': 'Wycinanie - mikro',
                    'assembly': 'Składanie - lite',
                    'gluing': 'Sklejanie',
                    'formatting': 'Formatowanie',
                    'edges': 'Krawędzie',
                    'painting': 'Lakiernia',
                    'packaging': 'Pakowanie'
                }[station],
                'icon': {
                    'cutting': '🪚',
                    'assembly': '🔧',
                    'gluing': '🧲',
                    'formatting': '📐',
                    'edges': '✨',
                    'painting': '🎨',
                    'packaging': '📦'
                }[station],
                'stats': {
                    'total_pending': total_pending,
                    'today_completed': today_completed,
                    'today_volume': float(today_volume)
                },
                'kolejka': [],
                'blad_priorytetow': priorytety is None,
            }
            sekcje = (priorytety or {}).get(station)
            if sekcje is not None:
                statystyki = sekcje.pop('stats', {})
                dane.update(sekcje)
                dane['stats'].update(statystyki)
            stations_data[station] = dane

        # Renderuj komponent (kolejność kart = kolejność wstawiania = STATION_ORDER; jsonify sortuje klucze `data`)
        rendered_html = render_template('components/stations-tab-content.html',
                              stations_data=stations_data)

        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': stations_data,
            'last_updated': get_local_now().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX stations-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
