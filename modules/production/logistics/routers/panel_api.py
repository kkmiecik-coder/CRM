# -*- coding: utf-8 -*-
"""
API zakładki Logistyka — /production/api/logistics/*

Kontrola dostępu jak w Trakowni (sawmill/routers/panel_api.py:53, tam pełne
uzasadnienie kolejności i leniwego odwołania do dekoratora).
"""
from functools import wraps

from flask import current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp, sposoby
from modules.production.logistics.services import bl_sync, delivery, geocoding, lista
from modules.production.models import ProductionOrder

logger = get_structured_logger('production.logistics.panel_api')
LIMIT_HURTU = 500

CARTO_BASEMAPS_KEY_CONFIG = 'CARTO_BASEMAPS_KEY'

# Ostrzeżenie o braku klucza CARTO najwyżej raz na proces (moduł-poziom
# flaga) — tab-content renderuje się przy każdym wejściu w zakładkę Logistyka,
# a mapa działa dalej bez klucza (kafelki ze znakiem wodnym „API KEY
# REQUIRED"), więc to nie jest alarm CRITICAL jak brak PRODUCTION_CRON_SECRET
# (cron_auth.py) — mapa nie przestaje działać, tylko brzydziej wygląda.
_carto_key_ostrzezono = False


def _klucz_carto_basemaps():
    """Klucz CARTO Basemaps z config/core.json — bez wartości domyślnej w kodzie.

    Repo jest publiczne, więc klucz nigdy nie trafia do kodu ani do testów —
    wyłącznie do config/core.json (jak PRODUCTION_CRON_SECRET, CEIDG_JWT_TOKEN).
    Pusty/brak pola nie blokuje mapy — logistics-map.js dokłada ?key= do
    adresu kafelków tylko, gdy klucz jest niepusty.
    """
    global _carto_key_ostrzezono
    klucz = current_app.config.get(CARTO_BASEMAPS_KEY_CONFIG)
    if not isinstance(klucz, str) or not klucz.strip():
        if not _carto_key_ostrzezono:
            _carto_key_ostrzezono = True
            logger.warning("Brak CARTO_BASEMAPS_KEY w config/core.json - kafelki mapy "
                           "logistyki beda ze znakiem wodnym CARTO 'API KEY REQUIRED'")
        return ''
    return klucz.strip()


def guard(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        checked = user_decorators.require_module_access('production', as_json=True)(
            login_required(f))
        return checked(*args, **kwargs)
    return wrapped


def _user_id():
    return getattr(current_user, 'id', None)


def _blad(komunikat, status):
    return jsonify({'success': False, 'error': komunikat}), status


@logistics_panel_bp.route('/tab-content', methods=['GET'])
@guard
def tab_content():
    return render_template('logistics/tab_content.html', magazyn=geocoding.MAGAZYN,
                           carto_basemaps_key=_klucz_carto_basemaps())


@logistics_panel_bp.route('/orders', methods=['GET'])
@guard
def orders():
    zamkniete = request.args.get('zamkniete') == '1'
    q = (request.args.get('q') or '').strip() or None
    if zamkniete and not q:
        return _blad(u'Wyszukiwanie zamkniętych zamówień wymaga frazy.', 422)
    wstrzymane = bl_sync.wstrzymane_do()
    return jsonify({
        'success': True,
        'orders': lista.pobierz(sposob=request.args.get('sposob') or None,
                                etap=request.args.get('etap') or None,
                                q=q, zamkniete=zamkniete),
        'liczniki': lista.liczniki(),
        'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
        'bez_lokalizacji': geocoding.bez_lokalizacji(),
        'geokoder_dziala': geocoding.geokoder_dziala(),
        # UF3: null albo {"zrobione": k, "wszystkie": N} — postęp „Zlokalizuj teraz”.
        'geokoder_postep': geocoding.postep(),
    })


@logistics_panel_bp.route('/orders/delivery-method', methods=['POST'])
@guard
def delivery_method():
    dane = request.get_json(silent=True) or {}
    if not isinstance(dane, dict):
        # Tablica albo skalar w ciele JSON — bez tego .get() rzuca AttributeError (500).
        return _blad(u'Nieprawidłowe dane żądania.', 422)
    ids = dane.get('order_ids')
    # 'brak' = „Nie ustawiono” — cofnięcie pomyłki (delivery.ustaw_sposob_dostawy).
    sposob = (sposoby.BRAK if dane.get('sposob') == sposoby.BRAK
              else sposoby.normalizuj(dane.get('sposob')))
    if not isinstance(ids, list) or not ids or len(ids) > LIMIT_HURTU:
        return _blad(u'Podaj od 1 do {} zamówień.'.format(LIMIT_HURTU), 422)
    # bool jest podklasą int w Pythonie — bez wyłączenia [True] przeszłoby jako id=1.
    # Bez tej walidacji element inny niż int (np. dict, string) trafia surowy do
    # ProductionOrder.id.in_(ids) i SQLAlchemy rzuca ProgrammingError z bazy (500,
    # szum w Sentry) zamiast czystego 422 tego endpointu dla złych danych wejściowych.
    if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
        return _blad(u'Identyfikatory zamówień muszą być liczbami całkowitymi.', 422)
    if sposob is None:
        return _blad(u'Nieznany sposób dostawy.', 422)

    zmienione, przepakowanie, bledy = [], [], []
    # selectinload: pozycje wszystkich zamówień jednym zapytaniem, nie zamówienie
    # po zamówieniu (hurt do LIMIT_HURTU zamówień, a pozycji potrzebuje każda zmiana).
    for order in (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).all()):
        try:
            wynik = delivery.ustaw_sposob_dostawy(order, sposob, user_id=_user_id())
        except delivery.LogistykaBlad as e:
            bledy.append({'order_id': order.id, 'komunikat': e.komunikat})
            continue
        if wynik['zmieniono']:
            zmienione.append(order.id)
        if wynik['przepakowanie']:
            przepakowanie.append(order.id)
    db.session.commit()
    logger.info("Logistyka: zmiana sposobu dostawy", extra={
        'user_id': _user_id(), 'sposob': sposob, 'zmienione': len(zmienione),
        'bledy': len(bledy)})

    bl_sync.po_zmianie(zmienione)
    odswiezone = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).all())
    punkty = geocoding.geo_zamowien(ids)
    return jsonify({'success': True, 'zmienione': zmienione, 'przepakowanie': przepakowanie,
                    'bledy': bledy,
                    'orders': [lista.serializuj(o, punkty.get(o.id)) for o in odswiezone]})


@logistics_panel_bp.route('/orders/<int:order_id>/handed-over', methods=['POST'])
@guard
def handed_over(order_id):
    order = ProductionOrder.query.get(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    try:
        delivery.wydaj_klientowi(order, user_id=_user_id())
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    db.session.commit()
    bl_sync.po_zmianie([order.id])
    order = ProductionOrder.query.get(order_id)
    punkty = geocoding.geo_zamowien([order_id])
    return jsonify({'success': True, 'order': lista.serializuj(order, punkty.get(order_id))})


def _zamowienie_albo_404(order_id):
    return ProductionOrder.query.get(order_id)


@logistics_panel_bp.route('/orders/<int:order_id>/address', methods=['PUT'])
@guard
def order_address(order_id):
    """
    Poprawka adresu dostawy (dwuklik w adres na liście). Do Base. idzie w tle
    (znacznik bl_address_pending → dopychacz), punkt na mapie liczy od nowa
    geokoder — oba tylko uruchamiamy, żadnej długiej pracy w żądaniu.
    """
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    dane = request.get_json(silent=True) or {}
    if not isinstance(dane, dict):
        return _blad(u'Nieprawidłowe dane żądania.', 422)
    try:
        zmieniono = delivery.zmien_adres(order, dane.get('adres'), dane.get('kod'),
                                         dane.get('miasto'), user_id=_user_id())
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    db.session.commit()
    if zmieniono:
        logger.info("Logistyka: zmiana adresu dostawy", extra={
            'user_id': _user_id(), 'order_id': order_id})
        bl_sync.po_zmianie([order_id])
        geocoding.uruchom_w_tle(current_app._get_current_object())
    order = ProductionOrder.query.options(selectinload(ProductionOrder.products)).get(order_id)
    punkty = geocoding.geo_zamowien([order_id])
    return jsonify({'success': True, 'zmieniono': zmieniono,
                    'order': lista.serializuj(order, punkty.get(order_id))})


@logistics_panel_bp.route('/geocode', methods=['GET'])
@guard
def geocode_status():
    """
    Lekki stan geokodera dla przycisku „Zlokalizuj teraz” — odpytywany co ~1,5 s,
    póki przebieg trwa (pełna lista co 10 s byłaby za ciężka i za rzadka).
    """
    return jsonify({
        'success': True,
        'geokoder_dziala': geocoding.geokoder_dziala(),
        'geokoder_postep': geocoding.postep(),
        'bez_lokalizacji': geocoding.bez_lokalizacji(),
    })


@logistics_panel_bp.route('/geocode', methods=['POST'])
@guard
def geocode():
    """„Zlokalizuj teraz” — tylko uruchamia wątek w tle (timeout gunicorna 30 s)."""
    uruchomiono = geocoding.uruchom_w_tle(current_app._get_current_object())
    return jsonify({'success': True, 'uruchomiono': bool(uruchomiono)}), 202


@logistics_panel_bp.route('/orders/<int:order_id>/geo', methods=['PUT'])
@guard
def order_geo(order_id):
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    dane = request.get_json(silent=True) or {}
    if not isinstance(dane, dict):
        # Tablica albo skalar w ciele JSON — bez tego .get() rzuca AttributeError (500).
        return _blad(u'Nieprawidłowe dane żądania.', 422)
    try:
        punkt = geocoding.ustaw_recznie(order, dane.get('lat'), dane.get('lng'))
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    try:
        db.session.commit()
    except IntegrityError:
        # Geokoder w tle mógł w międzyczasie wstawić ten sam wiersz (INSERT z SELECT
        # ... FOR UPDATE) — commit tego żądania trafia w duplicate key. Ponawiamy raz:
        # ustaw_recznie() na świeżo odczytanym wierszu robi UPDATE, nie INSERT.
        db.session.rollback()
        try:
            punkt = geocoding.ustaw_recznie(order, dane.get('lat'), dane.get('lng'))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _blad(u'Nie udało się zapisać lokalizacji, spróbuj ponownie.', 409)
    return jsonify({'success': True, 'order': lista.serializuj(order, punkt)})


@logistics_panel_bp.route('/orders/<int:order_id>/geo/reset', methods=['POST'])
@guard
def order_geo_reset(order_id):
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    geocoding.resetuj(order)
    db.session.commit()
    return jsonify({'success': True, 'order': lista.serializuj(order, None)})
