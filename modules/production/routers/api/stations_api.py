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

from datetime import date
from flask import jsonify, render_template
from flask_login import login_required, current_user
from extensions import db

from ...services import statystyki_stanowisk
from . import api_bp, logger, get_local_now

# Ile kafli kolejki (i pozycji listy Lakierni) pokazuje karta stanowiska.
LIMIT_KAFLI_ZAKLADKI = 15


def _z_terminem(kafle, dzis):
    for kafel in kafle:
        kafel['dni_do_terminu'] = statystyki_stanowisk.dni_do_terminu(kafel.get('termin'), dzis)
    return kafle


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
                wynik[kod] = {'kolejka': statystyki_stanowisk.lista_lakierni(dzis, LIMIT_KAFLI_ZAKLADKI)}
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

        from ...services.station_catalog import STATION_ORDER

        # Dane dla każdego stanowiska
        stations_data = {}
        stations = list(STATION_ORDER)
        dzis = date.today()
        priorytety = _priorytety_stanowisk(stations, dzis)

        for station in stations:
            statystyki = statystyki_stanowisk.statystyki(station, dzis)

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
                'stats': statystyki,
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


@api_bp.route('/stations-tab-queue/<kod>')
@login_required
def stations_tab_queue(kod):
    """
    Rozwinięcie „Pokaż wszystkie” w zakładce Stanowiska: WSZYSTKIE wiersze kolejki stanowiska (zakładka pokazuje
    pierwsze `LIMIT_KAFLI_ZAKLADKI`) jako HTML tych samych wierszy co w zakładce (wspólne makro
    `components/_stanowiska_kolejka.html`). Stanowisko ze stołem: kolejka z `widok.kolejka_stanowiska` bez kafli
    leżących na stole i odłożonych; Lakiernia: lista po wykończeniu (bez stołu, więc wiersze bez przycisku „Na stół”).
    Do `LIMIT_KOLEJKI_MAX` wierszy, jak `GET /priorytety/kolejka`. Czysty odczyt: bez blokad, zapisów i dopełniania
    stołu (jak `stations-tab-content`). Nieznany kod → 404.
    """
    from ...priorytety.services import ustawienia, widok
    from ...services.station_catalog import STATION_ORDER

    if kod not in STATION_ORDER:
        return jsonify({'success': False, 'error': 'Nie ma takiego stanowiska.'}), 404
    try:
        dzis = date.today()
        if kod in ustawienia.STANOWISKA_BEZ_STOLU:
            kafle = statystyki_stanowisk.lista_lakierni(dzis, widok.LIMIT_KOLEJKI_MAX)
            jednostka, ma_stol = None, False
        else:
            kolejka = widok.kolejka_stanowiska(kod, limit=widok.LIMIT_KOLEJKI_MAX)
            kafle = _z_terminem(kolejka['kafle'], dzis)
            jednostka, ma_stol = kolejka['jednostka'], True
        html = render_template('components/stations-tab-queue-rows.html',
                               kafle=kafle, station_key=kod, jednostka=jednostka, ma_stol=ma_stol)
        return jsonify({'success': True, 'html': html, 'wierszy': len(kafle)})
    except Exception as e:
        db.session.rollback()       # zwykły odczyt: nic do cofnięcia poza zepsutą migawką sesji
        logger.error("Błąd AJAX stations-tab-queue", extra={
            'user_id': current_user.id,
            'station': kod,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': 'Nie udało się wczytać kolejki stanowiska.'}), 500
