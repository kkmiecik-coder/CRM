# -*- coding: utf-8 -*-
"""
API zakładki Logistyka — /production/api/logistics/*

Kontrola dostępu jak w Trakowni (sawmill/routers/panel_api.py:53, tam pełne
uzasadnienie kolejności i leniwego odwołania do dekoratora).
"""
from functools import wraps

from flask import current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp, sposoby, wojewodztwa
from modules.production.logistics.services import bl_sync, delivery, geocoding, lista, paczki, routes
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


def _zapis_pod_blokada():
    """
    (I1) Początek zapisu zamówień z panelu (sposób dostawy, „Wydane klientowi”, adres):
    commit, potem blokada tras. Wołać PO walidacji ciała żądania, a PRZED pierwszym
    odczytem zamówień i pozycji.

    DLACZEGO: MySQL pracuje na REPEATABLE READ, a migawka transakcji powstaje przy
    pierwszym zwykłym odczycie — tu już w before_request (np. enforce_session_validity),
    czyli przed blokadą. FOR UPDATE na wierszu blokady tej migawki nie odświeża, więc
    zwykły SELECT zamówień po blokadzie widziałby stan sprzed commitu piszącego, na
    którego blokadę żądanie czekało (np. przepakowanie z hurtu) i decydował na nim.
    Commit kończy tamtą transakcję, blokada jest pierwszym poleceniem nowej, a pierwszy
    zwykły odczyt po niej tworzy migawkę już POD blokadą. Między tymi dwoma krokami
    żadnych odczytów — także atrybutów ORM, które commit właśnie wygasił (ich
    dociągnięcie to zwykły SELECT, czyli migawka znów sprzed blokady).
    """
    db.session.commit()
    routes.zablokuj_trasy()


@logistics_panel_bp.route('/tab-content', methods=['GET'])
@guard
def tab_content():
    return render_template('logistics/tab_content.html', magazyn=geocoding.MAGAZYN,
                           carto_basemaps_key=_klucz_carto_basemaps(),
                           # Runda 2 (spec 2.5): opcje filtra województw z jednego źródła.
                           opcje_wojewodztw=wojewodztwa.wojewodztwa(),
                           opcje_pozostale=wojewodztwa.POZOSTALE)


@logistics_panel_bp.route('/orders', methods=['GET'])
@guard
def orders():
    zamkniete = request.args.get('zamkniete') == '1'
    q = (request.args.get('q') or '').strip() or None
    if zamkniete and not q:
        return _blad(u'Wyszukiwanie zamkniętych zamówień wymaga frazy.', 422)
    # (runda 2, spec 2.5) Województwa: parametr wielokrotny (?woj=a&woj=b), pusta wartość
    # = brak filtra, nieznany identyfikator = 422 (jak inne złe parametry listy).
    woj = list(dict.fromkeys(w for w in request.args.getlist('woj') if w))
    if wojewodztwa.nieznane(woj):
        return _blad(u'Nieznany filtr województwa.', 422)
    # Krok 4.3 (spec 11): filtry Weryfikacji; nieznana wartość = 422 jak inne złe parametry listy.
    stan = request.args.get('stan') or None
    if stan is not None and stan not in lista.STANY_WERYFIKACJI:
        return _blad(u'Nieznany filtr weryfikacji.', 422)
    wstrzymane = bl_sync.wstrzymane_do()
    return jsonify({
        'success': True,
        'orders': lista.pobierz(sposob=request.args.get('sposob') or None,
                                etap=request.args.get('etap') or None,
                                q=q, zamkniete=zamkniete, woj=woj or None, stan=stan),
        'liczniki': lista.liczniki(),
        'weryfikacja': lista.liczniki_weryfikacji(),
        'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
        'bez_lokalizacji': geocoding.bez_lokalizacji(),
        'geokoder_dziala': geocoding.geokoder_dziala(),
        # UF3: null albo {"zrobione": k, "wszystkie": N} — postęp „Zlokalizuj teraz”.
        'geokoder_postep': geocoding.postep(),
    })


def _kod_mysql(blad):
    """Kod błędu MySQL z OperationalError (np. 1213 = zakleszczenie) albo None."""
    argumenty = getattr(getattr(blad, 'orig', None), 'args', None) or ()
    return argumenty[0] if argumenty else None


def _zapisz_zmiane_sposobu(ids, sposob, przepakowanie_decyzja, user_id):
    """
    Cały zapis zmiany sposobu dostawy w jednej transakcji: blokada tras, blokady zamówień, pętla, commit.
    Zwraca (zmienione, przepakowanie, bledy, usunieto) — listy liczone od zera przy każdym wywołaniu, więc
    funkcję wolno wywołać drugi raz po rollbacku (jedno ponowienie po 1213, patrz `delivery_method`).
    """
    # Blokada globalna tras PRZED pierwszym zapisem (fix-1, Ruling A7) — kolejność
    # „trasa najpierw": bez tego pętla niżej mogłaby trzymać blokady wierszy pozycji
    # zamówienia O1 i czekać na blokadę trasy, podczas gdy zatwierdzenie trasy
    # (trzymające jej blokadę) czekałoby na podbicie tych samych pozycji — zakleszczenie.
    # (I1) Także przed odczytem zamówień — patrz _zapis_pod_blokada.
    _zapis_pod_blokada()
    # Spec 8.7: wiersze zamówień FOR UPDATE rosnąco po id (jak hurt statusu i cron), potem zwykły odczyt
    # z pozycjami. Migawka powstaje dopiero teraz, więc decyzja „w całości spakowane” widzi wszystko, co
    # zatwierdzono przed blokadami (np. Weryfikację albo deklarację paczek). Pozycji nie blokujemy: pisarze
    # pozycji (ZAKOŃCZ, wejście do pakowania, doróbka, Weryfikacja, hurt) biorą od kroku 4.4a najpierw wiersz
    # zamówienia, więc blokada zamówienia wyklucza ich z tego zamówienia, zanim sięgną po pozycje.
    db.session.query(ProductionOrder.id).filter(ProductionOrder.id.in_(ids)) \
        .order_by(ProductionOrder.id).with_for_update().all()

    zmienione, przepakowanie, bledy, usunieto = [], [], [], []
    # selectinload: pozycje wszystkich zamówień jednym zapytaniem, nie zamówienie
    # po zamówieniu (hurt do LIMIT_HURTU zamówień, a pozycji potrzebuje każda zmiana).
    # populate_existing: obiekty z sesji (np. z wcześniejszych odczytów) nadpisujemy stanem spod blokad.
    for order in (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).order_by(ProductionOrder.id)
                  .populate_existing().all()):
        try:
            wynik = delivery.ustaw_sposob_dostawy(order, sposob, user_id=user_id,
                                                  przepakowanie=przepakowanie_decyzja)
        except delivery.LogistykaBlad as e:
            wpis = {'order_id': order.id, 'komunikat': e.komunikat}
            wpis.update(e.dane or {})
            bledy.append(wpis)
            continue
        if wynik['zmieniono']:
            zmienione.append(order.id)
        if wynik['przepakowanie']:
            przepakowanie.append(order.id)
        if wynik.get('usunieto_z_trasy'):
            usunieto.append({'order_id': order.id, 'trasa': wynik['usunieto_z_trasy']})
    db.session.commit()
    return zmienione, przepakowanie, bledy, usunieto


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
    # Spec 8.7: decyzja logistyka o zamówieniach w całości spakowanych. Brak pola albo null = brak decyzji;
    # każda inna wartość niż true/false to błąd (1, "tak", [] itd. nie przechodzą za decyzję).
    przepakowanie_decyzja = dane.get('przepakowanie')
    if przepakowanie_decyzja is not None and not isinstance(przepakowanie_decyzja, bool):
        return _blad(u'Pole przepakowanie musi mieć wartość true albo false.', 422)
    # PRZED _zapis_pod_blokada: po commicie current_user.id to zwykły SELECT (migawka sprzed blokady).
    user_id = _user_id()

    # Jedno automatyczne ponowienie po zakleszczeniu 1213 (I1b), zostawione jako zabezpieczenie. Zmiana
    # sposobu na zamówieniu z pozycją w ruchu na stanowisku zakleszczała się, gdy stanowisko najpierw zapisywało
    # pozycję, potem zamówienie (spec 8.7, „Współbieżność”); od kroku 4.4a stanowiska, doróbka, Weryfikacja
    # i hurt biorą wiersz zamówienia przed pozycjami (wyścigi MySQL: 0 × 1213), więc ponowienie obejmuje już tylko
    # ścieżki spoza tej zasady (np. ręczna synchronizacja z force_update). Żądanie jest bezpieczne do powtórzenia: decyzja jest jawna
    # w ciele (`przepakowanie`), a druga próba decyduje na nowym stanie spod nowych blokad — zamówienie,
    # które dopiero się spakowało, dostanie `wymaga_decyzji_przepakowania`, a nie zmianę wbrew regule.
    # Najwyżej jedna próba więcej: drugie 1213 i każdy inny błąd idą dalej do globalnego handlera (500).
    try:
        zmienione, przepakowanie, bledy, usunieto = _zapisz_zmiane_sposobu(
            ids, sposob, przepakowanie_decyzja, user_id)
    except OperationalError as e:
        if _kod_mysql(e) != 1213:
            raise
        db.session.rollback()
        logger.warning("Logistyka: zakleszczenie 1213 przy zmianie sposobu dostawy, ponawiam raz", extra={
            'user_id': user_id, 'sposob': sposob, 'zamowien': len(ids)})
        zmienione, przepakowanie, bledy, usunieto = _zapisz_zmiane_sposobu(
            ids, sposob, przepakowanie_decyzja, user_id)
    logger.info("Logistyka: zmiana sposobu dostawy", extra={
        'user_id': user_id, 'sposob': sposob, 'zmienione': len(zmienione),
        'bledy': len(bledy)})

    bl_sync.po_zmianie(zmienione)
    odswiezone = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(ProductionOrder.id.in_(ids)).all())
    punkty = geocoding.geo_zamowien(ids)
    trasy = routes.trasy_zamowien(ids)
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    okno = lista.okno_weryfikacji()   # jedno na cały hurt (plakietka BEZ PACZEK), liczone na żądanie
    return jsonify({'success': True, 'zmienione': zmienione, 'przepakowanie': przepakowanie,
                    'bledy': bledy, 'usunieto_z_trasy': usunieto,
                    'orders': [lista.serializuj(o, punkty.get(o.id), trasy.get(o.id),
                                                pakunki.get(o.id, []), okno)
                              for o in odswiezone]})


@logistics_panel_bp.route('/orders/<int:order_id>/handed-over', methods=['POST'])
@guard
def handed_over(order_id):
    # (I1) Pod blokadą tras i na stanie spod niej — bez tego wydanie mogło zapaść na
    # stanie sprzed równoległej zmiany sposobu (np. na kuriera z przepakowaniem).
    _zapis_pod_blokada()
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
    trasy = routes.trasy_zamowien([order_id])
    return jsonify({'success': True,
                    'order': lista.serializuj(order, punkty.get(order_id), trasy.get(order_id))})


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
    dane = request.get_json(silent=True) or {}
    if not isinstance(dane, dict):
        return _blad(u'Nieprawidłowe dane żądania.', 422)
    # (I1) zmien_adres czyta pola zamówienia przed _przystanek_do_zmiany — zamówienie
    # wczytujemy dopiero pod blokadą tras (patrz _zapis_pod_blokada).
    _zapis_pod_blokada()
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
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
    trasy = routes.trasy_zamowien([order_id])
    return jsonify({'success': True, 'zmieniono': zmieniono,
                    'order': lista.serializuj(order, punkty.get(order_id), trasy.get(order_id))})


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
    trasy = routes.trasy_zamowien([order_id])
    return jsonify({'success': True, 'order': lista.serializuj(order, punkt, trasy.get(order_id))})


@logistics_panel_bp.route('/orders/<int:order_id>/geo/reset', methods=['POST'])
@guard
def order_geo_reset(order_id):
    order = _zamowienie_albo_404(order_id)
    if order is None:
        return _blad(u'Nie ma takiego zamówienia.', 404)
    try:
        geocoding.resetuj(order)
    except delivery.LogistykaBlad as e:
        db.session.rollback()
        return _blad(e.komunikat, e.status)
    db.session.commit()
    trasy = routes.trasy_zamowien([order_id])
    return jsonify({'success': True, 'order': lista.serializuj(order, None, trasy.get(order_id))})
