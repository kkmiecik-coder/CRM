# -*- coding: utf-8 -*-
"""
Trasy tabletu kierownika hali — /api/mobile/manager/* (kontrakt: docs/api-mobile-kierownik.md).

Każda trasa: @require_device_token → @wymaga_kierownika (services/bramka.py); zapisy dodatkowo
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True). Kolejne trasy dopisują
następne zadania planu.
"""
import hashlib
import json

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.kierownik.services import bramka, raporty, stanowiska, trakownia, trasy, zamowienia
from modules.production.kierownik.services.bramka import blad, wymaga_kierownika
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA
from modules.production.models import ProductionOrder, ProductionProduct
from modules.production.priorytety.services import kolejka, stol, sygnaly
from modules.production.services import blokady_zamowien, worker_service, zmiana_statusu
from modules.production.services.mobile_api_service import require_device_token, with_idempotency
from modules.production.utils.cache import cached_json, if_none_match, make_weak_etag, no_store_json, not_modified

logger = get_structured_logger('production.kierownik.mobile_api')

kierownik_mobile_bp = Blueprint('kierownik_mobile', __name__)

# Listy mają słaby ETag i Cache-Control: private, max-age=15 (kontrakt §2).
MAX_AGE_LISTY = 15


@kierownik_mobile_bp.route('/orders', methods=['GET'])
@require_device_token
@wymaga_kierownika
def lista_zamowien():
    """Lista zamówień (bieżące, archiwum, wszystkie) ze statystykami na całym przefiltrowanym zbiorze (§5.1)."""
    try:
        parametry = zamowienia.wczytaj_parametry(request.args)
    except zamowienia.BladParametru as e:
        return blad('dane_niepoprawne', str(e), 400)
    etag = zamowienia.etag_listy(parametry)
    if if_none_match(etag):
        return not_modified(etag, max_age=MAX_AGE_LISTY)
    return cached_json(zamowienia.lista(**parametry), etag, max_age=MAX_AGE_LISTY)


@kierownik_mobile_bp.route('/orders/<int:order_id>', methods=['GET'])
@require_device_token
@wymaga_kierownika
def karta_zamowienia(order_id):
    """Karta zamówienia z pełnymi pozycjami, załącznikami i miejscem na stołach stanowisk (§5.2). `no-store`."""
    dane = zamowienia.karta(order_id)
    if dane is None:
        return blad('zamowienie_nieznane', u'Nie ma takiego zamówienia.', 404)
    return no_store_json(dane)


@kierownik_mobile_bp.route('/products/<int:product_id>/history', methods=['GET'])
@require_device_token
@wymaga_kierownika
def historia_pozycji(product_id):
    """Historia pozycji: przepływ po stanowiskach i oś zdarzeń od najnowszych (§5.3). `no-store`."""
    dane = zamowienia.historia(product_id)
    if dane is None:
        return blad('pozycja_nieznana', u'Nie ma takiej pozycji.', 404)
    return no_store_json(dane)


# --- Stanowiska (odczyty; kontrakt §7.1, §7.2, §7.5) ------------------------------------------------------------
# Same zwykłe odczyty: bez blokad, bez commitów i bez dopełniania stołu (to robi wyłącznie `GET desk` tabletów).

# Wersja kształtu przeglądu: wchodzi do ETagu, więc zmiana DTO unieważnia pamięć podręczną tabletów.
KSZTALT_PRZEGLADU_STANOWISK = 1


@kierownik_mobile_bp.route('/stations', methods=['GET'])
@require_device_token
@wymaga_kierownika
def przeglad_stanowisk():
    """Przegląd 7 stanowisk: nagłówki, liczniki i obsada bez list kafli (§7.1). Słaby ETag, `max-age=15`."""
    dane = stanowiska.przeglad()
    # Przegląd nie ma taniego agregatu, więc ETag to odcisk samej treści (bez znacznika `wyliczono`, który zmienia się
    # co żądanie). 304 oszczędza tablet, nie bazę.
    tresc = json.dumps({k: v for k, v in dane.items() if k != 'wyliczono'}, sort_keys=True, ensure_ascii=False)
    etag = make_weak_etag('kier-stan', KSZTALT_PRZEGLADU_STANOWISK, hashlib.md5(tresc.encode('utf-8')).hexdigest())
    if if_none_match(etag):
        return not_modified(etag, max_age=MAX_AGE_LISTY)
    return cached_json(dane, etag, max_age=MAX_AGE_LISTY)


@kierownik_mobile_bp.route('/stations/<kod>', methods=['GET'])
@require_device_token
@wymaga_kierownika
def pelne_stanowisko(kod):
    """Pełne stanowisko: stół, odłożone, widma, niekompletne i kolejka do `limit` kafli (§7.2). `no-store`."""
    if kod not in stanowiska.STATION_ORDER:
        return blad('stanowisko_nieznane', u'Nie ma takiego stanowiska.', 404)
    try:
        limit = stanowiska.wczytaj_limit(request.args.get('limit'))
    except stanowiska.BladLimitu as e:
        return blad('dane_niepoprawne', str(e), 400)
    dane = stanowiska.pelne(kod, limit, lagodnie=True)      # czysty odczyt: awaria priorytetów nie daje 500
    return no_store_json(dane)


@kierownik_mobile_bp.route('/workers/now', methods=['GET'])
@require_device_token
@wymaga_kierownika
def kto_teraz_pracuje():
    """„Kto teraz pracuje”: wszystkie stanowiska z obsadą, także puste (§7.5). `no-store`."""
    return no_store_json(stanowiska.obsada())


# --- Trasy transportu własnego (odczyty; kontrakt §8.1, §8.2) --------------------------------------------------------
# Czyste odczyty: bez przeliczania przebiegu (ORS) i bez commitów — panel tras robi to w samym GET, tablet kierownika nie.

@kierownik_mobile_bp.route('/routes', methods=['GET'])
@require_device_token
@wymaga_kierownika
def lista_tras():
    """Lista tras: aktywne (także robocze) i wykonane z ostatnich 30 dni, albo wg `status`/`od`/`do` (§8.1). Słaby ETag."""
    try:
        parametry = trasy.wczytaj_parametry(request.args)
    except trasy.BladParametru as e:
        return blad('dane_niepoprawne', str(e), 400)
    dane = trasy.lista(**parametry)
    etag = trasy.etag_listy(dane)
    if if_none_match(etag):
        return not_modified(etag, max_age=MAX_AGE_LISTY)
    return cached_json(dane, etag, max_age=MAX_AGE_LISTY)


@kierownik_mobile_bp.route('/routes/<int:route_id>', methods=['GET'])
@require_device_token
@wymaga_kierownika
def szczegoly_trasy(route_id):
    """Trasa z przystankami, stanami, punktami na mapie i ostatnim zapisanym przebiegiem (§8.2). ETag, `max-age=0`."""
    dane = trasy.szczegoly(route_id)
    if dane is None:
        return blad('trasa_nieznana', u'Nie ma takiej trasy.', 404)
    etag = trasy.etag_szczegolow(route_id, dane)
    if if_none_match(etag):
        return not_modified(etag, max_age=0)
    return cached_json(dane, etag, max_age=0)


# --- Trakownia (odczyty; kontrakt §8.3, §8.4) -------------------------------------------------------------------
# Deklaracje, pomiary i różnice w m³ oraz procentach; bez cen, wartości i notatek rozliczenia (services/trakownia.py).

@kierownik_mobile_bp.route('/sawmill/orders', methods=['GET'])
@require_device_token
@wymaga_kierownika
def lista_trakowni():
    """Zlecenia trakowni: otwarte i dostawy z 90 dni, albo wg filtrów (§8.3). Słaby ETag, `max-age=15`."""
    try:
        parametry = trakownia.wczytaj_parametry(request.args)
    except trakownia.BladParametru as e:
        return blad('dane_niepoprawne', str(e), 400)
    dane = trakownia.lista(**parametry)
    etag = trakownia.etag_listy(dane)
    if if_none_match(etag):
        return not_modified(etag, max_age=MAX_AGE_LISTY)
    return cached_json(dane, etag, max_age=MAX_AGE_LISTY)


@kierownik_mobile_bp.route('/sawmill/orders/<int:order_id>', methods=['GET'])
@require_device_token
@wymaga_kierownika
def zlecenie_trakowni(order_id):
    """Zlecenie trakowni z kłodami, pracownikami i średnimi (§8.4). `no-store`."""
    dane = trakownia.zlecenie(order_id)
    if dane is None:
        return blad('zlecenie_nieznane', u'Nie ma takiego zlecenia trakowni.', 404)
    return no_store_json(dane)


# --- Raporty (odczyty; kontrakt §8.5, §8.6, §8.7) ----------------------------------------------------------------
# Wspólny zakres dat (`raporty.zakres`): oba końce albo żaden, domyślnie dziś, najwyżej 92 dni, inaczej 400
# `zakres_niepoprawny`. Czyste odczyty, `no-store`: zakres „dziś" zmienia się co chwilę, a dalsze zakresy appka może
# sama trzymać po swojej stronie.

def _zakres_raportu():
    """(start, koniec, None) albo (None, None, odpowiedź 400 `zakres_niepoprawny`)."""
    try:
        start, koniec = raporty.zakres(request.args)
    except raporty.BladZakresu as e:
        return None, None, blad('zakres_niepoprawny', str(e), 400)
    return start, koniec, None


@kierownik_mobile_bp.route('/reports/stations', methods=['GET'])
@require_device_token
@wymaga_kierownika
def raport_stanowisk():
    """Przerób stanowisk w zakresie: sztuki, m³, pozycje, zamówienia, cofnięcia i kolejka teraz (§8.5). `no-store`."""
    start, koniec, odmowa = _zakres_raportu()
    if odmowa is not None:
        return odmowa
    return no_store_json(raporty.stanowiska(start, koniec))


@kierownik_mobile_bp.route('/reports/workers', methods=['GET'])
@require_device_token
@wymaga_kierownika
def raport_pracownikow():
    """Wydajność pracowników w zakresie, opcjonalnie na jednym stanowisku procesu (`station`) (§8.6). `no-store`."""
    start, koniec, odmowa = _zakres_raportu()
    if odmowa is not None:
        return odmowa
    try:
        dane = raporty.pracownicy(start, koniec, request.args.get('station'))
    except raporty.BladParametru as e:
        return blad('dane_niepoprawne', str(e), 400)
    return no_store_json(dane)


@kierownik_mobile_bp.route('/reports/daily', methods=['GET'])
@require_device_token
@wymaga_kierownika
def raport_dzien_po_dniu():
    """Przerób dzień po dniu: każdy dzień zakresu, także z zerami, i wszystkie 7 stanowisk (§8.7). `no-store`."""
    start, koniec, odmowa = _zakres_raportu()
    if odmowa is not None:
        return odmowa
    return no_store_json(raporty.dzien_po_dniu(start, koniec))


# --- Zapisy -----------------------------------------------------------------------------------------------------

MAX_POZYCJI_W_ZADANIU = 20
OPIS_ZMIANY_STATUSU = u'zmiana statusu przez kierownika hali'
# Statusy ustawiane z tabletu kierownika (kontrakt §4.1). Zbiór panelu (`zmiana_statusu.DOZWOLONE_STATUSY`) zostaje
# bez zmian, ale zawiera jeszcze stare `w_realizacji`: pozycja w tym statusie nie stoi w żadnej kolejce stanowiska
# (brak sygnału, kafla na stole i wiersza w kolejce), więc z tabletu go nie oferujemy.
STATUSY_KIEROWNIKA = zmiana_statusu.DOZWOLONE_STATUSY - {'w_realizacji'}


def _zapis_z_ponowieniem(akcja):
    """
    Szkielet zapisu kierownika (spec 4.2, wzór `dostawa_api._zapis`): `akcja(kierownik_id) -> (Response, status)`.

    Kolejność jednej próby: kierownik (`bramka.kierownik`, pierwszy identyfikator z X-Worker-Ids) → przedłużenie jego
    sesji (`touch_sessions`: pracownicy są pierwszymi blokadami transakcji, jak w Dostawie i Weryfikacji) → id jako
    zwykła LICZBA → `commit` → `akcja`. Akcja zaczyna od blokady (serwis: blokada tras w
    `zablokuj_zamowienia_i_pozycje`; serwisy stołu: `stol.zablokuj_stanowisko`) i do niej NIE WOLNO nic czytać:
    po commicie wszystkie obiekty sesji są wygasłe, więc dotknięcie atrybutu ORM (kierownika, urządzenia) byłoby
    zwykłym SELECT-em, czyli odczytem spoza blokad, a w REPEATABLE READ otwierałoby migawkę sprzed czekania na
    blokadę. Stąd `kierownik_id` jako liczba, a `device_id` odczytany przed pierwszym commitem. Commit przed akcją
    nie psuje `with_idempotency`: wpis idempotencji dekorator dodaje i commituje po handlerze, w transakcji akcji;
    skutek uboczny — przedłużenie sesji kierownika zostaje zapisane także przy odmowie akcji.

    Jedno automatyczne ponowienie po zakleszczeniu MySQL 1213, WEWNĄTRZ handlera: dekorator idempotencji widzi jeden
    wynik i zapisuje jeden wpis. Rollback, porzucenie planów z tej próby (sygnały stanowisk i przeliczenie rang —
    akcja planuje je zanim handler wypchnie zapisy) i CAŁA sekwencja od nowa, więc decyzja zapada na nowym stanie.
    `flush` w środku `try` wypycha zapisy akcji przed oddaniem wyniku — inaczej zakleszczenie przy flushu w commicie
    dekoratora wypadłoby poza ponowieniem. Drugie 1213 i każdy inny błąd bazy idą dalej (dekorator: rollback i 500,
    wpis niezapamiętany).
    """
    device_id = g.device.device_id          # przed pierwszym commitem: potem obiekt urządzenia jest wygasły
    for proba in (1, 2):
        pracownik, odmowa = bramka.kierownik()
        if odmowa is not None:
            return odmowa
        kierownik_id = pracownik.id
        g.worker_ids = [kierownik_id]       # aktor zdarzeń pozycji (listener product_events) — liczby, nie obiekty
        worker_service.touch_sessions([kierownik_id], device_id=device_id)
        db.session.commit()
        try:
            odpowiedz = akcja(kierownik_id)
            db.session.flush()
            return odpowiedz
        except OperationalError as e:
            if proba == 2 or blokady_zamowien.kod_mysql(e) != 1213:
                raise
            db.session.rollback()
            sygnaly.porzuc()
            kolejka.porzuc_zaplanowane()
            logger.warning('Kierownik: zakleszczenie 1213, ponawiam raz', extra={
                'endpoint': request.endpoint, 'device_id': device_id, 'worker_id': kierownik_id})


def _wczytaj_zmiane_statusu(dane):
    """
    ((lista identyfikatorów bez powtórzeń w kolejności żądania, status), None) albo (None, odpowiedź błędu
    `dane_niepoprawne` | `status_niedozwolony`). Walidacja przed jakimkolwiek zapisem i przed `_zapis_z_ponowieniem`:
    odrzucone żądanie nie dotyka bazy. Identyfikatory to liczby całkowite JSON (bez bool, ułamków i napisów); limit
    20 liczy się po usunięciu powtórzeń.
    """
    if not isinstance(dane, dict):
        return None, blad('dane_niepoprawne', u'Żądanie musi być obiektem JSON z polami product_ids i status.', 400)
    surowe = dane.get('product_ids')
    if not isinstance(surowe, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in surowe):
        return None, blad('dane_niepoprawne', u'Pole product_ids musi być listą identyfikatorów pozycji.', 400)
    ids = list(dict.fromkeys(surowe))
    if not 1 <= len(ids) <= MAX_POZYCJI_W_ZADANIU:
        return None, blad('dane_niepoprawne', u'Wybierz od 1 do %d pozycji.' % MAX_POZYCJI_W_ZADANIU, 400)
    status = dane.get('status')
    if not isinstance(status, str) or not status:
        return None, blad('dane_niepoprawne', u'Brakuje nowego statusu.', 400)
    if status not in STATUSY_KIEROWNIKA:
        return None, blad('status_niedozwolony', u'Tego statusu nie można ustawić z tabletu kierownika.', 400,
                          dozwolone=sorted(STATUSY_KIEROWNIKA))
    return (ids, status), None


def _pozycja_po_zapisie(pozycja):
    return {'product_id': pozycja.id, 'order_id': pozycja.order_id, 'status': pozycja.current_status,
            'status_etykieta': pozycja.status_display_name}


def _zmien_status(ids, status, kierownik_id):
    """
    Akcja zapisu `POST /products/status` (spec 4.2 p. 3-5), wołana po commicie szkieletu: serwis `zmien_status`
    (jego pierwszy odczyt to zwykły odczyt samych kolumn id i order_id pozycji — kolumn niezmiennych, tak samo
    w panelu — a pierwsza BLOKADA to blokada tras) nie commituje i nie cofa transakcji, więc rollback przy odmowie
    jest tutaj. DTO pozycji budujemy wyłącznie ze ścieżki sukcesu: po rollbacku obiekty są wygasłe.

    `nieznane` serwisu znaczy „nie ma ich wśród zablokowanych pozycji”: obejmuje identyfikator, którego nie ma
    w bazie, pozycję usuniętą między odczytem id a blokadą i pozycję bez zamówienia (`order_id` NULL), której
    blokada po zamówieniach nie wczytuje. Dla appki to jedno: wiersz znika z widoku (kontrakt §6).
    """
    wynik = zmiana_statusu.zmien_status(ids, status, worker_id=kierownik_id, opis=OPIS_ZMIANY_STATUSU)
    if wynik is None:
        db.session.rollback()
        return blad('pozycje_nieznane', u'Nie ma już tych pozycji. Odśwież listę.', 404)
    if not wynik['success']:
        komunikat = wynik['error']
        db.session.rollback()
        return blad('trasa_w_drodze', komunikat, 409)

    zmienione, odmowione = wynik['processed_count'], wynik['failed_count']
    komunikat = u'Zmieniono status %d pozycji.' % zmienione
    if odmowione:
        komunikat += u' Odmówiono: %d.' % odmowione
    cialo = {
        'message': komunikat,
        'zmienione': zmienione,
        'odmowione': odmowione,
        'odmowy': list(wynik['errors']),
        'pozycje': [_pozycja_po_zapisie(p) for p in wynik['pozycje']],
        'zdjete_ze_stolow': list(wynik['zdjete_stanowiska']),
        'nieznane': list(wynik['nieznane']),
    }
    # Handler nie commituje (robi to with_idempotency), więc tylko PLANUJE: sygnały dla stanowisk, z których zeszły
    # kafle, i dla stanowiska, któremu doszła praca, oraz przeliczenie rang — wykona je dekorator po udanym commicie.
    sygnaly.zaplanuj(*(list(wynik['zdjete_stanowiska']) + [wynik['nowe_stanowisko']]))
    kolejka.zaplanuj_po_commicie()
    return jsonify(cialo), 200


@kierownik_mobile_bp.route('/products/status', methods=['POST'])
@require_device_token
@wymaga_kierownika
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True)
def zmiana_statusu_pozycji():
    """Zmiana statusu pozycji (§6): ta sama operacja co hurt w panelu. Odmowy 4xx nie są zapamiętywane."""
    wczytane, odmowa = _wczytaj_zmiane_statusu(request.get_json(silent=True))
    if odmowa is not None:
        return odmowa
    ids, status = wczytane
    return _zapis_z_ponowieniem(lambda kierownik_id: _zmien_status(ids, status, kierownik_id))


# --- Stół stanowiska: „Na stół” i „Zdejmij ze stołu” (kontrakt §7.3, §7.4) ---------------------------------------------
# Kierownik jest tu pisarzem stołu (CLAUDE.md, „Stół stanowiska — dwie klasy pisarzy”): po commicie szkieletu pierwszym
# odczytem transakcji jest `stol.zablokuj_stanowisko` (woła ją sam serwis), potem zamówienie i jego pozycje
# `FOR SHARE`, wiersz stołu odczytem bieżącym po pełnym kluczu unikalnym. Żadnych blokad X zamówień i pozycji, żadnej
# blokady tras. Stan stanowiska w odpowiedzi czytamy zwykłymi odczytami PO tych blokadach, w tej samej transakcji.

def _poloz_na_stol(kod, order_id, kierownik_id, device_pk):
    """Akcja zapisu `POST …/desk` wołana po commicie szkieletu. Odmowa serwisu to rollback i błąd kontraktu."""
    try:
        wynik = stol.wyslij(kod, order_id, None, worker_id=kierownik_id, device_id=device_pk)
    except stol.BladStolu as e:
        db.session.rollback()
        return blad(e.kod, e.komunikat, e.status)
    db.session.flush()
    zmieniono = bool(wynik['wyslane'] or wynik['przywrocone'])
    # Zamówienie jest już w sesji (zablokowane przez serwis), więc numer do komunikatu zwykle nie kosztuje SQL-a.
    numer = stol.numer_zamowienia(db.session.get(ProductionOrder, order_id))
    stanowisko_gen = stol.nazwa_w_dopelniaczu(kod)
    if zmieniono:
        # Handler nie commituje (robi to with_idempotency), więc tylko PLANUJE sygnał; dekorator wyśle go po commicie.
        sygnaly.zaplanuj(kod)
    cialo = {
        'message': (u'Zamówienie {} jest na stole {}.' if zmieniono else u'Zamówienie {} już leży na stole {}.').format(
            numer, stanowisko_gen),
        'wynik': 'wyslano' if zmieniono else 'juz_na_stole',
        'wyslane': list(wynik['wyslane']),
        'przywrocone': list(wynik['przywrocone']),
        'juz_na_stole': list(wynik['juz_na_stole']),
        'stanowisko': stanowiska.pelne(kod, stanowiska.LIMIT_DOMYSLNY),
    }
    return jsonify(cialo), 200


def _zdejmij_ze_stolu(kod, unit_key, kierownik_id, device_pk):
    """Akcja zapisu `POST …/desk/remove` wołana po commicie szkieletu. Odmowa serwisu to rollback i błąd kontraktu."""
    try:
        wynik = stol.zdejmij_przez_biuro(kod, unit_key, None, worker_id=kierownik_id, device_id=device_pk)
    except stol.BladStolu as e:
        db.session.rollback()
        return blad(e.kod, e.komunikat, e.status)
    db.session.flush()
    stanowisko_gen = stol.nazwa_w_dopelniaczu(kod)
    if wynik['product_id'] is not None:
        # Kafel pozycji nazywamy jej skróconym numerem, jak w komunikatach stołu (`pozycja_poza_stanowiskiem`).
        pozycja = db.session.get(ProductionProduct, wynik['product_id'])
        kafel = u'pozycji {}'.format((pozycja.short_product_id if pozycja is not None else None)
                                     or u'#%d' % wynik['product_id'])
    else:
        kafel = u'zamówienia {}'.format(stol.numer_zamowienia(db.session.get(ProductionOrder, wynik['order_id'])))
    sygnaly.zaplanuj(kod)
    if wynik['odlozony']:
        miejsce = u'z odłożonych na {}'.format(stol.nazwa_w_miejscowniku(kod))
    else:
        miejsce = u'ze stołu {}'.format(stanowisko_gen)
    cialo = {
        'message': u'Zdjęto kafel {} {}.'.format(kafel, miejsce),
        'unit_key': wynik['unit_key'],
        'order_id': wynik['order_id'],
        'product_id': wynik['product_id'],
        'odlozony': wynik['odlozony'],
        'stanowisko': stanowiska.pelne(kod, stanowiska.LIMIT_DOMYSLNY),
    }
    return jsonify(cialo), 200


@kierownik_mobile_bp.route('/stations/<kod>/desk', methods=['POST'])
@require_device_token
@wymaga_kierownika
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True)
def na_stol(kod):
    """„Na stół” (§7.3): kafle zamówienia, które jest teraz na stanowisku, idą na jego stół (`zrodlo='biuro'`)."""
    if kod not in stanowiska.STATION_ORDER:
        return blad('stanowisko_nieznane', u'Nie ma takiego stanowiska.', 404)
    dane = request.get_json(silent=True)
    order_id = dane.get('order_id') if isinstance(dane, dict) else None
    if isinstance(order_id, bool) or not isinstance(order_id, int):
        return blad('dane_niepoprawne', u'Podaj numer zamówienia (order_id).', 400)
    device_pk = g.device.id             # przed commitem szkieletu: potem obiekt urządzenia jest wygasły
    return _zapis_z_ponowieniem(lambda kierownik_id: _poloz_na_stol(kod, order_id, kierownik_id, device_pk))


@kierownik_mobile_bp.route('/stations/<kod>/desk/remove', methods=['POST'])
@require_device_token
@wymaga_kierownika
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True)
def zdejmij_ze_stolu(kod):
    """„Zdejmij ze stołu” (§7.4): usuwa kafel ze stołu albo z odłożonych; pozycja wraca do kolejki stanowiska."""
    if kod not in stanowiska.STATION_ORDER:
        return blad('stanowisko_nieznane', u'Nie ma takiego stanowiska.', 404)
    dane = request.get_json(silent=True)
    unit_key = dane.get('unit_key') if isinstance(dane, dict) else None
    if not isinstance(unit_key, str):
        return blad('dane_niepoprawne', u'Podaj klucz kafla (unit_key) z listy stołu.', 400)
    device_pk = g.device.id
    return _zapis_z_ponowieniem(lambda kierownik_id: _zdejmij_ze_stolu(kod, unit_key, kierownik_id, device_pk))
