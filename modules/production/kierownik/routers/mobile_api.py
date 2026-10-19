# -*- coding: utf-8 -*-
"""
Trasy tabletu kierownika hali — /api/mobile/manager/* (kontrakt: docs/api-mobile-kierownik.md).

Każda trasa: @require_device_token → @wymaga_kierownika (services/bramka.py); zapisy dodatkowo
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA, require_operation_id=True). Kolejne trasy dopisują
następne zadania planu.
"""
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.kierownik.services import bramka, zamowienia
from modules.production.kierownik.services.bramka import blad, wymaga_kierownika
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA
from modules.production.services import blokady_zamowien, worker_service, zmiana_statusu
from modules.production.services.mobile_api_service import require_device_token, with_idempotency
from modules.production.utils.cache import cached_json, if_none_match, no_store_json, not_modified

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


# --- Zapisy -----------------------------------------------------------------------------------------------------

MAX_POZYCJI_W_ZADANIU = 500
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
    from modules.production.priorytety.services import kolejka, sygnaly
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
    500 liczy się po usunięciu powtórzeń.
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
    from modules.production.priorytety.services import kolejka, sygnaly
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
