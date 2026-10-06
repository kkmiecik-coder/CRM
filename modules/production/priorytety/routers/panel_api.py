# -*- coding: utf-8 -*-
"""
API panelu biura priorytetów produkcji — /production/api/priorytety/* (spec 2026-10-04, sekcje 7.1–7.3, 9.3–9.4, 10).

Router jest cienki: waliduje ciało, pilnuje kolejności commit → blokada → zapis → commit → przeliczenie rang
i mapuje błędy na `{"success": false, "error": "<kod>", "message": "<po polsku>"}`. Logika siedzi w serwisach
pakietu (`drabina`, `gwiazdki`, `kolejka`, `ustawienia`, `widok`). Serwisy nie commitują — commituje router.

Kontrola dostępu jak w Logistyce i Trakowni (`guard`, uzasadnienie kolejności i leniwego odwołania do dekoratora:
sawmill/routers/panel_api.py:53). Ustawienia i ręczne przeliczenie dodatkowo `admin_required` (spec 7.3).

Treści wyjątków (`str(e)`, `raport['error']` z przeliczenia) nie trafiają do odpowiedzi — tylko do logu.
"""
from functools import wraps

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import OperationalError

import modules.users.decorators as user_decorators
from extensions import db
from modules.logging import get_structured_logger
# Moduły, nie nazwy: testy podmieniają `routes.zablokuj_trasy`, `drabina.uzupelnij`, `kolejka.utrwal`.
from modules.production.logistics.services import routes
from modules.production.models import ProductionOrder
from modules.production.priorytety import priorytety_panel_bp, stale
from modules.production.priorytety.models import PriorityRung
from modules.production.priorytety.services import drabina, gwiazdki, kolejka, stol, sygnaly, ustawienia, widok
from modules.production.services import blokady_zamowien, config_service

logger = get_structured_logger('production.priorytety.panel_api')

KOMUNIKAT_BLAD_SERWERA = u'Nie udało się zapisać zmian. Spróbuj ponownie za chwilę.'
# Kody odmów `drabina.BladDrabiny` (K1) → kody panelu (plan K2, Doprecyzowania p. 12).
KODY_DRABINY = {'brak_szczebla': 'szczebel_nieznany', 'pozycja_poza_zakresem': 'pozycja_niepoprawna'}


def guard(f):
    """Login + dostęp do modułu `production`, oba sprawdzane w chwili żądania; brak sesji → 401 JSON, brak modułu →
    403 JSON. Kolejność (moduł na zewnątrz) i leniwe odwołanie: sawmill/routers/panel_api.py:53."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        checked = user_decorators.require_module_access('production', as_json=True)(
            login_required(f))
        return checked(*args, **kwargs)
    return wrapped


def admin_required(f):
    """
    `common_api.admin_required` (403 JSON „Brak uprawnień administratora”) wołany LENIWIE, w chwili żądania — bez
    kopii. Import na górze modułu robiłby cykl: `modules.production` ładuje modele priorytetów, pakiet priorytetów
    ten router, a `modules.production.routers` importuje `apply_security` z niedokończonego `modules.production`.
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        from modules.production.routers.api.common_api import admin_required as admin_common
        return admin_common(f)(*args, **kwargs)
    return wrapped


def _user_id():
    """Id zalogowanego użytkownika. Czytać PRZED pierwszym commitem żądania (commit wygasza atrybuty ORM, a ich
    dociągnięcie po commicie to zwykły odczyt przed blokadą)."""
    return getattr(current_user, 'id', None)


def _blad(kod, komunikat, status, **pola):
    """Odmowa w formacie panelu: kod maszynowy, komunikat po polsku i ewentualne pola dodatkowe (`pole`, `nieznane`)."""
    tresc = {'success': False, 'error': kod, 'message': komunikat}
    tresc.update(pola)
    return jsonify(tresc), status


class _Odmowa(Exception):
    """Odmowa zapisu wykryta pod blokadą: router robi rollback i odpowiada `_blad(kod, komunikat, status)`."""

    def __init__(self, kod, komunikat, status):
        super(_Odmowa, self).__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


def _liczba(wartosc):
    """Liczba całkowita z JSON-a, ale nie bool (True to w Pythonie także int)."""
    return isinstance(wartosc, int) and not isinstance(wartosc, bool)


def _przelicz_po_zapisie():
    """
    Przeliczenie rang PO commicie routera (spec 9.3; warunek wstępny `kolejka.utrwal`: `db.session` bez
    niezatwierdzonych zapisów). Porażka nie cofa zapisu (spec 10) — panel dostaje 'nieudane', cron nadrobi.
    Tekst błędu z raportu idzie wyłącznie do logu (niesie SQL z parametrami).
    """
    try:
        raport = kolejka.utrwal_po_commicie()
    except Exception as e:      # siatka: utrwal_po_commicie nie rzuca
        logger.error('Priorytety: przeliczenie po zapisie panelu rzuciło wyjątek', extra={'error': str(e)})
        return 'nieudane'
    if not raport or not raport.get('success'):
        logger.error('Priorytety: przeliczenie po zapisie panelu nieudane',
                     extra={'error': (raport or {}).get('error')})
        return 'nieudane'
    return 'ok'


def _zapis_z_ponowieniem(zapis, opis):
    """
    Woła `zapis()` (commit → blokada → zapis → commit) i zwraca (wynik, None) albo (None, odpowiedź błędu).
    Jedno ponowienie całego zapisu po zakleszczeniu MySQL 1213, jak w hurcie (`products_api.bulk_action`); drugie
    1213 i każdy inny błąd → rollback i 500 `blad_serwera` bez treści wyjątku. Odmowy (`_Odmowa`,
    `drabina.BladDrabiny`, `stol.BladStolu`) → rollback (blokada nie może wisieć do teardown) i odpowiedź z kodem.
    """
    for proba in (1, 2):
        try:
            return zapis(), None
        except _Odmowa as e:
            db.session.rollback()
            return None, _blad(e.kod, e.komunikat, e.status)
        except drabina.BladDrabiny as e:
            db.session.rollback()
            return None, _blad(KODY_DRABINY.get(e.kod, e.kod), e.komunikat, e.status)
        except stol.BladStolu as e:
            db.session.rollback()
            return None, _blad(e.kod, e.komunikat, e.status)
        except gwiazdki.BladGwiazdek as e:     # siatka: router waliduje wcześniej
            db.session.rollback()
            return None, _blad('gwiazdki_niepoprawne', e.komunikat, 400)
        except OperationalError as e:
            db.session.rollback()
            if proba == 1 and blokady_zamowien.kod_mysql(e) == 1213:
                logger.warning('Priorytety: zakleszczenie 1213, ponawiam zapis raz', extra={'zapis': opis})
                continue
            logger.error('Priorytety: błąd bazy przy zapisie panelu', extra={'zapis': opis, 'error': str(e)})
            return None, _blad('blad_serwera', KOMUNIKAT_BLAD_SERWERA, 500)
        except Exception as e:
            db.session.rollback()
            logger.error('Priorytety: błąd zapisu panelu', extra={'zapis': opis, 'error': str(e)})
            return None, _blad('blad_serwera', KOMUNIKAT_BLAD_SERWERA, 500)
    return None, _blad('blad_serwera', KOMUNIKAT_BLAD_SERWERA, 500)


# ── drabina ──────────────────────────────────────────────────────────────────────────────────────────────────

def _samonaprawa():
    """
    Dopisanie brakujących szczebli (spec 4.4: trasa bez szczebla w oknie wdrożenia, brak szczebla stałego) — tylko
    gdy czegoś brakuje. Commit (koniec migawki), blokada tras, `drabina.uzupelnij` (sprawdza braki pod blokadą),
    commit. Bez przeliczenia rang: `policz` liczy już trasę bez szczebla w miejscu domyślnym, czyli tam, gdzie
    wstawia ją `uzupelnij`. Porażka nie psuje odczytu. Zwraca (liczba dopisanych, ostrzeżenia).
    """
    if not widok.brak_szczebli():
        return 0, []
    user_id = _user_id()
    try:
        db.session.commit()
        routes.zablokuj_trasy()
        dopisane = drabina.uzupelnij(user_id=user_id)
        db.session.commit()
        return dopisane, []
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: samonaprawa drabiny nieudana', extra={'error': str(e)})
        return 0, [{'kod': 'samonaprawa_nieudana',
                    'message': u'Nie udało się dopisać brakujących szczebli drabiny. Spróbuj odświeżyć.'}]


def _odpowiedz_drabina(uzupelniono=0, ostrzezenia=(), **pola):
    dane = widok.drabina_panelu()
    tresc = {'success': True, 'uzupelniono': uzupelniono, 'szczeble': dane['szczeble'],
             'ostrzezenia': list(ostrzezenia) + dane['ostrzezenia']}
    tresc.update(pola)
    return jsonify(tresc)


@priorytety_panel_bp.route('/drabina', methods=['GET'])
@guard
def drabina_get():
    """Drabina: widoczne szczeble z licznikami zamówień w produkcji i ostrzeżeniem o datach tras."""
    try:
        uzupelniono, ostrzezenia = _samonaprawa()
        return _odpowiedz_drabina(uzupelniono, ostrzezenia)
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu drabiny', extra={'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać drabiny priorytetów.', 500)


def _cialo_przesuniecia():
    """(szczebel_id, pozycja, oczekiwane) z ciała `PUT /drabina/kolejnosc` albo None przy złym ciele."""
    dane = request.get_json(silent=True)
    if not isinstance(dane, dict):
        return None
    szczebel_id, pozycja, oczekiwane = dane.get('szczebel_id'), dane.get('pozycja'), dane.get('oczekiwane')
    if not _liczba(szczebel_id) or not _liczba(pozycja) or pozycja < 1:
        return None
    if oczekiwane is not None and (not isinstance(oczekiwane, list) or not all(_liczba(i) for i in oczekiwane)):
        return None
    return szczebel_id, pozycja, oczekiwane


@priorytety_panel_bp.route('/drabina/kolejnosc', methods=['PUT'])
@guard
def drabina_kolejnosc():
    """
    Przesunięcie szczebla tagu albo trasy na `pozycja` (indeks 1..n w WIDOCZNEJ drabinie, jak w `GET /drabina`).
    Opcjonalne `oczekiwane` — id widocznych szczebli w kolejności, którą widział klient; inna drabina pod blokadą →
    409 `drabina_zmieniona`. Kolejność: commit → blokada tras → odczyt bieżący szczebli → zapis → commit →
    przeliczenie rang (spec 9.4; CLAUDE.md „Trasy logistyki — jeden piszący naraz”).
    """
    cialo = _cialo_przesuniecia()
    if cialo is None:
        return _blad('dane_niepoprawne', u'Podaj szczebel_id i pozycję (liczby całkowite od 1).', 400)
    szczebel_id, pozycja, oczekiwane = cialo
    user_id = _user_id()            # przed commitem: commit wygasza atrybuty użytkownika

    def _przesun():
        db.session.commit()         # koniec migawki; następne zapytanie to blokada tras
        routes.zablokuj_trasy()
        widoczne = drabina.szczeble(aktualny=True)
        rung = next((s for s in widoczne if s.id == szczebel_id), None)
        if rung is None:
            ukryty = (PriorityRung.query.filter(PriorityRung.id == szczebel_id)
                      .with_for_update().populate_existing().first())
            if ukryty is None:
                raise _Odmowa('szczebel_nieznany', u'Nie ma takiego szczebla.', 404)
            raise _Odmowa('trasa_nieaktywna', u'Trasa tego szczebla nie jest już robocza ani zatwierdzona.', 409)
        if rung.kind == 'stars':
            raise _Odmowa('szczebel_staly', u'Szczebli gwiazdek nie można przesuwać.', 400)
        if oczekiwane is not None and oczekiwane != [s.id for s in widoczne]:
            raise _Odmowa('drabina_zmieniona',
                          u'Ktoś właśnie zmienił drabinę. Odśwież ją i przesuń szczebel jeszcze raz.', 409)
        if not 1 <= pozycja <= len(widoczne):
            raise _Odmowa('pozycja_niepoprawna', u'Podaj pozycję od 1 do {}.'.format(len(widoczne)), 400)
        zmiana = widoczne.index(rung) + 1 != pozycja
        if zmiana:
            drabina.przesun(rung.id, pozycja, user_id=user_id)
        db.session.commit()
        return zmiana

    zmiana, blad = _zapis_z_ponowieniem(_przesun, 'drabina')
    if blad is not None:
        return blad
    przeliczenie = _przelicz_po_zapisie() if zmiana else 'niepotrzebne'
    try:
        return _odpowiedz_drabina(przeliczenie=przeliczenie)
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu drabiny po zapisie', extra={'error': str(e)})
        return _blad('blad_serwera', u'Zapisano, ale nie udało się wczytać drabiny. Odśwież widok.', 500)


# ── gwiazdki i przeliczenie ──────────────────────────────────────────────────────────────────────────────────

@priorytety_panel_bp.route('/zamowienia/gwiazdki', methods=['PUT'])
@guard
def zamowienia_gwiazdki():
    """
    Gwiazdki 0–5 hurtem: `{"order_ids": [int, ...], "gwiazdki": int}`. Zapisuje tylko zamówienia, którym wartość się
    zmienia. Kolejność (spec 9.2, 9.4): commit → zamówienia FOR UPDATE rosnąco po id → zapis i log → commit →
    przeliczenie rang. BEZ blokady tras (gwiazdki tras nie zmieniają).
    """
    dane = request.get_json(silent=True)
    if not isinstance(dane, dict):
        return _blad('dane_niepoprawne', u'Podaj order_ids i gwiazdki.', 400)
    order_ids, liczba_gwiazdek = dane.get('order_ids'), dane.get('gwiazdki')
    if not isinstance(order_ids, list) or not order_ids or not all(_liczba(i) for i in order_ids):
        return _blad('dane_niepoprawne', u'Podaj niepustą listę numerów zamówień (order_ids).', 400)
    if not _liczba(liczba_gwiazdek) or not 0 <= liczba_gwiazdek <= stale.GWIAZDKI_MAX:
        return _blad('gwiazdki_niepoprawne', u'Podaj liczbę gwiazdek od 0 do {}.'.format(stale.GWIAZDKI_MAX), 400)
    ids = sorted(set(order_ids))
    if len(ids) > stale.LIMIT_HURTU:
        return _blad('za_duzo_zamowien', u'Naraz można zmienić najwyżej {} zamówień.'.format(stale.LIMIT_HURTU),
                     400, limit=stale.LIMIT_HURTU)
    user_id = _user_id()            # przed commitem: commit wygasza atrybuty użytkownika
    # Zwykły odczyt przed commitem: tylko po to, żeby nie brać blokad, gdy nie ma żadnego zamówienia. Listę
    # nieznanych w odpowiedzi daje stan spod blokady (`wynik['brak']`).
    if not db.session.query(ProductionOrder.id).filter(ProductionOrder.id.in_(ids)).first():
        return _blad('zamowienie_nieznane', u'Nie ma takich zamówień.', 404, nieznane=ids)

    def _zapisz():
        db.session.commit()         # koniec migawki; następne zapytanie to blokada zamówień
        wynik = gwiazdki.ustaw(ids, liczba_gwiazdek, user_id=user_id)
        db.session.commit()
        return wynik

    wynik, blad = _zapis_z_ponowieniem(_zapisz, 'gwiazdki')
    if blad is not None:
        return blad
    przeliczenie = _przelicz_po_zapisie() if wynik['zmienione'] else 'niepotrzebne'
    return jsonify({'success': True, 'zmienione': sorted(wynik['zmienione']),
                    'bez_zmian': sorted(wynik['bez_zmian']), 'nieznane': sorted(wynik['brak']),
                    'przeliczenie': przeliczenie})


@priorytety_panel_bp.route('/przelicz', methods=['POST'])
@guard
@admin_required
def przelicz():
    """
    „Przelicz teraz” (admin): `kolejka.utrwal` na własnej sesji; wpis `przeliczenie` w logu robi sam `utrwal`.
    Router niczego nie zapisuje i nie commituje. Porażka → 500 `przeliczenie_nieudane` bez treści błędu.
    """
    user_id = _user_id()
    try:
        raport = kolejka.utrwal(zrodlo='panel', user_id=user_id)
    except Exception as e:      # siatka: utrwal nie rzuca
        logger.error('Priorytety: ręczne przeliczenie rzuciło wyjątek', extra={'error': str(e)})
        raport = None
    if not raport or not raport.get('success'):
        logger.error('Priorytety: ręczne przeliczenie nieudane', extra={'error': (raport or {}).get('error')})
        return _blad('przeliczenie_nieudane',
                     u'Nie udało się przeliczyć kolejki. Spróbuj ponownie za chwilę.', 500)
    return jsonify({'success': True, 'raport': {k: v for k, v in raport.items() if k != 'error'}})


# ── kolejka i modal priorytetu (tylko odczyt, bez blokad) ────────────────────────────────────────────────────

def _limit_kolejki():
    """`limit` z adresu: liczba całkowita 1..LIMIT_KOLEJKI_MAX, domyślnie LIMIT_KOLEJKI; None przy złej wartości."""
    tekst = request.args.get('limit')
    if tekst is None:
        return widok.LIMIT_KOLEJKI
    tekst = tekst.strip()
    if not tekst.isdigit():
        return None
    limit = int(tekst)
    return limit if 1 <= limit <= widok.LIMIT_KOLEJKI_MAX else None


@priorytety_panel_bp.route('/kolejka', methods=['GET'])
@guard
def kolejka_get():
    """
    Bez parametrów: cała kolejka zamówień aktywnych po randze liczonej na żywo. `?stanowisko=S[&limit=L]`: podgląd
    kafli stanowiska S w kolejności, w jakiej wziąłby je stół (szczebel i ranga z kolumn, „Rozpoczęte” na żywo).
    """
    try:
        if 'stanowisko' not in request.args:
            return jsonify(dict({'success': True}, **widok.kolejka_zamowien()))
        kod = request.args.get('stanowisko', '')
        if kod not in widok.STANOWISKO_STATUSU.values():
            return _blad('stanowisko_nieznane', u'Nie ma takiego stanowiska.', 400)
        if kod in ustawienia.STANOWISKA_BEZ_STOLU:
            # Spec, ustalenie 15: Lakiernia pracuje z listy po wykończeniu, podglądu stołu dla niej nie ma.
            return _blad('stanowisko_bez_stolu', u'{} nie ma stołu: pracuje z pełnej listy.'.format(
                ustawienia.STANOWISKA_BEZ_STOLU[kod]), 400)
        limit = _limit_kolejki()
        if limit is None:
            return _blad('dane_niepoprawne',
                         u'Limit musi być liczbą całkowitą od 1 do {}.'.format(widok.LIMIT_KOLEJKI_MAX), 400)
        return jsonify(dict({'success': True}, **widok.kolejka_stanowiska(kod, limit)))
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu kolejki', extra={'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać kolejki.', 500)


@priorytety_panel_bp.route('/zamowienia/<int:order_id>/priorytet', methods=['GET'])
@guard
def zamowienie_priorytet(order_id):
    """Dane modalu priorytetu zamówienia: gwiazdki, szczebel, ranga, gdzie leży, historia zmian."""
    try:
        dane = widok.priorytet_zamowienia(order_id)
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu priorytetu zamówienia', extra={'order_id': order_id, 'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać priorytetu zamówienia.', 500)
    if dane is None:
        return _blad('zamowienie_nieznane', u'Nie ma takiego zamówienia.', 404)
    return jsonify(dict({'success': True}, **dane))


# ── stoły stanowisk (krok K3; spec 5.3, 5.7, 5.8, 7.2) ───────────────────────────────────────────────────────

@priorytety_panel_bp.route('/stoly', methods=['GET'])
@guard
def stoly_get():
    """Stół i odłożone każdego stanowiska ze stołem — to samo, co widzi tablet. Bez dopełniania i bez blokad."""
    try:
        return jsonify({'success': True, 'stanowiska': widok.stoly_panelu()})
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu stołów', extra={'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać stołów stanowisk.', 500)


@priorytety_panel_bp.route('/odlozenia', methods=['GET'])
@guard
def odlozenia_get():
    """Otwarte odłożenia wszystkich stanowisk, najdłużej leżące pierwsze (plakietki i lista w modalu priorytetu)."""
    try:
        return jsonify({'success': True, 'odlozenia': widok.odlozenia_panelu()})
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu odłożeń', extra={'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać odłożeń.', 500)


@priorytety_panel_bp.route('/stoly/<kod>/wyslij', methods=['POST'])
@guard
def stol_wyslij(kod):
    """
    „Wyślij na stanowisko” (spec 5.7): `{"order_id": int}` — kładzie na stół stanowiska `kod` kafle zamówienia,
    które są teraz w jego statusie (ponad K, źródło `biuro`); odłożony kafel wraca na stół. Kolejność: commit →
    blokada stanowiska → odczyt bieżący zamówienia i pozycji (FOR SHARE) → zapis wierszy stołu → commit → sygnał
    `station:<kod>`. Bez blokad X zamówień. Jedno ponowienie po 1213. Stanowisko sprawdza serwis
    (`stol.wymagaj_stolu`): nieznany kod → 400 `stanowisko_nieznane`, Lakiernia → 409 `stanowisko_bez_stolu`.
    """
    dane = request.get_json(silent=True)
    order_id = dane.get('order_id') if isinstance(dane, dict) else None
    if not _liczba(order_id):
        return _blad('dane_niepoprawne', u'Podaj numer zamówienia (order_id).', 400)
    user_id = _user_id()            # przed commitem: commit wygasza atrybuty użytkownika

    def _wyslij():
        db.session.commit()         # koniec migawki; następne zapytanie to blokada stanowiska
        wynik = stol.wyslij(kod, order_id, user_id)
        db.session.commit()
        return wynik

    wynik, blad = _zapis_z_ponowieniem(_wyslij, 'wyslij')
    if blad is not None:
        return blad
    zmieniono = bool(wynik['wyslane'] or wynik['przywrocone'])
    if zmieniono:
        sygnaly.wyslij(kod)         # po commicie: tablety stanowiska dociągają stół
    return jsonify(dict({'success': True, 'stanowisko': kod,
                         'wynik': 'wyslano' if zmieniono else 'juz_na_stole'}, **wynik))


@priorytety_panel_bp.route('/stoly/<kod>/zdejmij', methods=['POST'])
@guard
def stol_zdejmij(kod):
    """
    „Zdejmij ze stołu” (spec 5.7): `{"unit_key": "p:123" | "o:45"}` — usuwa wiersz stołu (leżący albo odłożony);
    kafel wraca do kolejki stanowiska. Kolejność i blokady jak „Wyślij”. 404 `brak_kafla`, gdy kafla już nie ma.
    """
    dane = request.get_json(silent=True)
    klucz = dane.get('unit_key') if isinstance(dane, dict) else None
    user_id = _user_id()

    def _zdejmij():
        db.session.commit()         # koniec migawki; następne zapytanie to blokada stanowiska
        wynik = stol.zdejmij_przez_biuro(kod, klucz, user_id)
        db.session.commit()
        return wynik

    wynik, blad = _zapis_z_ponowieniem(_zdejmij, 'zdejmij')
    if blad is not None:
        return blad
    sygnaly.wyslij(kod)
    return jsonify(dict({'success': True, 'stanowisko': kod}, **wynik))


# ── start stołów (spec 5.8) ──────────────────────────────────────────────────────────────────────────────────

@priorytety_panel_bp.route('/start', methods=['GET'])
@guard
def start_get():
    """
    Podgląd startu stołów: dla każdego stanowiska ze stołem kafle ROZPOCZĘTE — „to wejdzie na stół” — z liczbą.
    Bez zapisu i bez blokad. Biuro ogląda go dzień wcześniej i w dniu startu, poprawia „Wyślij” i „Zdejmij”.
    """
    try:
        stanowiska = []
        for kod in widok.stanowiska_ze_stolem():
            kafle = stol.rozpoczete_na_stanowisku(kod)
            stanowiska.append({
                'stanowisko': kod, 'nazwa': widok.station_label(kod), 'tryb': ustawienia.tryb(kod),
                'jednostka': ustawienia.jednostka(kod), 'miejsca': ustawienia.miejsca(kod),
                'liczba': len(kafle), 'na_stole': sum(1 for kafel in kafle if kafel['na_stole']),
                'kafle': kafle,
            })
        return jsonify({'success': True, 'stanowiska': stanowiska})
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd podglądu startu stołów', extra={'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać podglądu startu stołów.', 500)


@priorytety_panel_bp.route('/start/przygotuj', methods=['POST'])
@guard
@admin_required
def start_przygotuj():
    """
    „Przygotuj stoły” (admin, po zakończeniu zmiany): kafle rozpoczęte każdego stanowiska ze stołem stają się
    wierszami stołu `start`. Stanowisko po stanowisku, KAŻDE W OSOBNEJ TRANSAKCJI (commit → blokada stanowiska →
    odczyt bieżący → INSERT → commit → sygnał): jedna transakcja na wszystkie trzymałaby blokady S na zamówieniach
    całej hali. Idempotentne — po błędzie wystarczy wywołać jeszcze raz; stanowiska zrobione przed błędem zostają
    (odpowiedź 500 podaje je w `stanowiska`, a pechowe w `nieudane`).
    """
    user_id = _user_id()            # przed pierwszym commitem: commit wygasza atrybuty użytkownika
    wyniki = []
    for kod in widok.stanowiska_ze_stolem():
        def _przygotuj(kod=kod):
            db.session.commit()     # koniec migawki; następne zapytanie to blokada stanowiska
            wynik = stol.przygotuj_start(kod, user_id)
            db.session.commit()
            return wynik

        wynik, blad = _zapis_z_ponowieniem(_przygotuj, 'start_stolow')
        if blad is not None:
            logger.error('Priorytety: przygotowanie stołów przerwane', extra={'stanowisko': kod})
            return _blad('blad_serwera', KOMUNIKAT_BLAD_SERWERA, 500, stanowiska=wyniki, nieudane=kod)
        if wynik['dodane']:
            sygnaly.wyslij(kod)     # po commicie stanowiska
        wyniki.append(dict({'stanowisko': kod}, **wynik))
    return jsonify({'success': True, 'stanowiska': wyniki})


# ── ustawienia (admin) ───────────────────────────────────────────────────────────────────────────────────────

@priorytety_panel_bp.route('/ustawienia', methods=['GET'])
@guard
@admin_required
def ustawienia_get():
    """Stoły stanowisk (tryb, miejsca, jednostka, limit odłożeń), próg „Blisko terminu”, minimalna wersja appki,
    typ dni terminu (spec 8.6)."""
    try:
        return jsonify(dict({'success': True}, **ustawienia.odczyt_panelu()))
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu ustawień', extra={'error': str(e)})
        return _blad('blad_serwera', u'Nie udało się wczytać ustawień.', 500)


@priorytety_panel_bp.route('/ustawienia', methods=['PUT'])
@guard
@admin_required
def ustawienia_put():
    """
    Zapis dowolnego podzbioru ustawień — jedyna droga zapisu kluczy priorytetów i `DEADLINE_DAY_TYPE`. Walidacja
    całości przed zapisem (jedno złe pole = nic się nie zmienia), zapis jedną transakcją, unieważnienie pamięci
    podręcznej `config_service` tego procesu, przeliczenie rang po commicie tylko przy zmianie progu „Blisko
    terminu”. Bez blokad: zapis dotyka wyłącznie `prod_config` i logu bez zamówienia.
    """
    zmiany, blad = ustawienia.waliduj(request.get_json(silent=True))
    if blad is None:
        # Stan wynikowy (żądanie + baza): stół nie włącza się przy progu wersji 0 (K4-poprawka-1).
        try:
            blad = ustawienia.sprawdz_prog_wersji(zmiany)
        except Exception as e:
            db.session.rollback()
            logger.error('Priorytety: błąd odczytu ustawień przed zapisem', extra={'error': str(e)})
            return _blad('blad_serwera', KOMUNIKAT_BLAD_SERWERA, 500)
    if blad is not None:
        kod, pole, komunikat = blad
        return _blad(kod, komunikat, 400, **({'pole': pole} if pole is not None else {}))
    user_id = _user_id()
    try:
        zmienione = ustawienia.zapisz(zmiany, user_id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd zapisu ustawień', extra={'error': str(e)})
        return _blad('blad_serwera', KOMUNIKAT_BLAD_SERWERA, 500)
    config_service.invalidate_config_cache()
    przeliczenie = _przelicz_po_zapisie() if stale.KLUCZ_BLISKO in zmienione else 'niepotrzebne'
    try:
        stan = ustawienia.odczyt_panelu()
    except Exception as e:
        db.session.rollback()
        logger.error('Priorytety: błąd odczytu ustawień po zapisie', extra={'error': str(e)})
        return _blad('blad_serwera', u'Zapisano, ale nie udało się wczytać ustawień. Odśwież widok.', 500)
    return jsonify(dict({'success': True, 'zmienione': zmienione, 'przeliczenie': przeliczenie}, **stan))
