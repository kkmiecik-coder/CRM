# -*- coding: utf-8 -*-
"""
API agenta druku v2 (`/api/print-agent/v2`). Autoryzacja: `Authorization: Bearer <token agenta>`; w bazie leży
tylko SHA-256 tokenu. Każdy handler commituje po sukcesie, a przy wyjątku robi rollback i oddaje 500
`blad_serwera` (serwisy drukarek tylko flushują). Sygnały realtime idą dopiero po commicie.
"""
import json
from datetime import datetime
from functools import wraps

from flask import Blueprint, g, jsonify, request, send_file, url_for

from extensions import db
from modules.logging import get_structured_logger
from modules.production.drukarki import stale
from modules.production.drukarki.models import PrintAgentCommand, PrintAgentConfig, PrintAgentRelease
from modules.production.drukarki.services import agenci, kolejka, konfiguracja, stan, wydania
from modules.production.services import realtime_service

logger = get_structured_logger('production.print_agent_v2')

agent_druku_v2_bp = Blueprint('agent_druku_v2', __name__)

MAKS_LIMIT = 50


def _blad(kod, status, **reszta):
    return jsonify({'error': kod, **reszta}), status


def _agent_endpoint(view):
    """Bearer → g.agent (401 `nieznany_agent`), commit po sukcesie, rollback + 500 po wyjątku."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        naglowek = request.headers.get('Authorization', '')
        token = naglowek[len('Bearer '):].strip() if naglowek.startswith('Bearer ') else ''
        g.po_commicie = []
        try:
            g.agent = agenci.agent_z_tokenu(token)
            if g.agent is None:
                return _blad('nieznany_agent', 401)
            odpowiedz = view(*args, **kwargs)
            db.session.commit()
        except Exception as e:  # noqa: BLE001 - każdy błąd = rollback i 500, agent ponowi
            db.session.rollback()
            # Token nie trafia do logu: zapisujemy tylko typ błędu, jego treść i nazwę endpointu.
            logger.error('Błąd API agenta druku v2', extra={'endpoint': request.endpoint,
                                                            'error_type': type(e).__name__, 'error': str(e)})
            return _blad('blad_serwera', 500)
        for po in g.po_commicie:
            try:
                po()
            except Exception as e:  # noqa: BLE001 - dane są już zatwierdzone, hak nie może zrobić z tego 500
                logger.exception('Błąd haka po commicie API agenta druku v2',
                                 extra={'endpoint': request.endpoint, 'error_type': type(e).__name__})
        return odpowiedz
    return wrapper


def _dane_json():
    dane = request.get_json(silent=True)
    return dane if isinstance(dane, dict) else {}


def _tekst(wartosc, maks):
    return str(wartosc)[:maks] if wartosc is not None else ''


def _drukarki_z_ciala(surowe):
    """Stan drukarek zgłoszony przez agenta: tylko słowniki z nazwą, pola ucięte do rozsądnej długości."""
    wynik = []
    if isinstance(surowe, list):
        for d in surowe[:20]:
            if isinstance(d, dict) and d.get('nazwa'):
                wynik.append({'nazwa': _tekst(d.get('nazwa'), 40), 'stan': _tekst(d.get('stan'), 40),
                              'opis': _tekst(d.get('opis'), 300)})
    return wynik


@agent_druku_v2_bp.route('/kontakt', methods=['POST'])
@_agent_endpoint
def kontakt():
    # Import lokalny: print_agent_api importuje serwisy drukarek, a tu potrzebujemy tylko jego sprzątania.
    from modules.production.routers.api import print_agent_api

    dane = _dane_json()
    wersja = _tekst(dane.get('wersja'), 40)
    # Najpierw wszystkie odczyty, które mogą zrobić rollback (najnowsze() robi go przy błędzie bazy), dopiero
    # potem zapis kontaktu: rollback nie może zabrać zapisu „agent żyje”.
    konf = PrintAgentConfig.query.filter_by(agent_id=g.agent.id).first()
    wersja_konfiguracji = konf.version if konf is not None else None
    aktualizacja = None
    wydanie = wydania.najnowsze()
    if wydanie is not None and wersja:
        try:
            nowsze = wydania.czy_nowsza(wydanie.version_name, wersja)
        except ValueError:
            nowsze = False  # agent z wersją spoza X.Y.Z (np. dev) nie dostaje oferty
        if nowsze:
            aktualizacja = {'wersja': wydanie.version_name, 'sha256': wydanie.sha256,
                            'rozmiar': wydanie.file_size_bytes,
                            'url': url_for('agent_druku_v2.plik_wydania', wersja=wydanie.version_name)}
    polecenia = [{'id': p.id, 'rodzaj': p.kind, 'drukarka': p.printer} for p in
                 PrintAgentCommand.query.filter_by(agent_id=g.agent.id, status='pending')
                 .order_by(PrintAgentCommand.id).all()]
    # Stan sprzed kontaktu liczymy z zapisu agenta i jego dotychczasowej żywotności (zegar serwera).
    stary_stan = stan.stany_efektywne(g.agent.printers_state, agenci.czy_online(g.agent))
    agenci.kontakt(g.agent, wersja, _drukarki_z_ciala(dane.get('drukarki')), bool(dane.get('push')))
    db.session.flush()
    nowy_stan = stan.stany_efektywne(g.agent.printers_state, True)
    g.po_commicie.append(lambda: stan.po_zmianie_stanu(stary_stan, nowy_stan))
    # Kontakt zatwierdzamy PRZED sprzątaniem kolejki: błąd sprzątania nie może go cofnąć.
    db.session.commit()
    try:
        print_agent_api._expire_stale_pending()  # throttling 60 s per worker, commit tylko gdy coś wygasło
    except Exception as e:  # noqa: BLE001 - kontakt już zatwierdzony; sprzątanie wróci przy kolejnym kontakcie
        db.session.rollback()
        logger.warning('Sprzątanie kolejki druku po kontakcie agenta v2 nie powiodło się',
                       extra={'error_type': type(e).__name__, 'error': str(e)})
    return jsonify({
        'wersja_konfiguracji': wersja_konfiguracji,
        'aktualizacja': aktualizacja,
        'polecenia': polecenia,
    })


@agent_druku_v2_bp.route('/zadania/pobierz', methods=['POST'])
@_agent_endpoint
def pobierz_zadania():
    dane = _dane_json()
    limit = dane.get('limit', 10)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAKS_LIMIT:
        return _blad('bledny_limit', 400)
    drukarka = dane.get('drukarka')
    if drukarka not in stale.ROLE:
        return _blad('bledna_drukarka', 400)
    if agenci.obsluga(drukarka) == 'stary':
        return jsonify({'zadania': [], 'obsluga': 'stary'})
    if agenci.przelaczanie_trwa(drukarka):  # stary agent kończy jeszcze rozpoczętą partię
        return jsonify({'zadania': [], 'obsluga': 'przelaczanie'})
    zadania = kolejka.pobierz(g.agent.id, drukarka, limit)
    return jsonify({'zadania': [{
        'id': j.id, 'drukarka': j.printer, 'zpl': j.zpl_payload, 'kod': j.short_product_id,
        'stanowisko': j.station_code,
        'zlecono': j.requested_at.isoformat() if j.requested_at else None,
    } for j in zadania]})


@agent_druku_v2_bp.route('/zadania/<int:job_id>/wysylam', methods=['POST'])
@_agent_endpoint
def wysylam(job_id):
    if not kolejka.wysylam(g.agent.id, job_id):
        return _blad('nie_twoje_zadanie', 409)
    return jsonify({'ok': True})


@agent_druku_v2_bp.route('/zadania/wyniki', methods=['POST'])
@_agent_endpoint
def wyniki():
    wyniki_ciala = _dane_json().get('wyniki')
    if not isinstance(wyniki_ciala, list):
        return _blad('bledne_wyniki', 400)
    return jsonify({'zmienione': kolejka.wynik(g.agent.id, wyniki_ciala)})


@agent_druku_v2_bp.route('/konfiguracja', methods=['GET'])
@_agent_endpoint
def pobierz_konfiguracje():
    konf = PrintAgentConfig.query.filter_by(agent_id=g.agent.id).first()
    if konf is None:
        return _blad('brak_konfiguracji', 404)
    return jsonify({'wersja': konf.version, 'dane': json.loads(konf.data)})


@agent_druku_v2_bp.route('/konfiguracja', methods=['PUT'])
@_agent_endpoint
def zapisz_konfiguracje():
    aktywny = agenci.aktywny_v2()
    if aktywny is None or aktywny.id != g.agent.id:
        return _blad('agent_nieaktywny', 409)
    cialo = _dane_json()
    dane = cialo.get('dane')
    wersja_bazowa = cialo.get('wersja_bazowa')
    bledy = konfiguracja.waliduj(dane)
    if wersja_bazowa is not None and (not isinstance(wersja_bazowa, int) or isinstance(wersja_bazowa, bool)):
        bledy.append('Wersja bazowa konfiguracji musi być liczbą całkowitą.')
    if bledy:
        return _blad('bledna_konfiguracja', 400, bledy=bledy)
    try:
        wiersz, nadpisana = konfiguracja.zapisz(g.agent.id, dane, wersja_bazowa, 'agent', 'agent:%s' % g.agent.id)
    except ValueError:
        return _blad('brak_konfiguracji', 404)
    g.po_commicie.append(lambda: realtime_service.publish(realtime_service.CHANNEL_PRINT_AGENT,
                                                          {'kind': 'config'}))
    return jsonify({'wersja': wiersz.version, 'dane': json.loads(wiersz.data), 'nadpisano': nadpisana})


@agent_druku_v2_bp.route('/polecenia/<int:polecenie_id>/wynik', methods=['POST'])
@_agent_endpoint
def wynik_polecenia(polecenie_id):
    polecenie = PrintAgentCommand.query.filter_by(id=polecenie_id, agent_id=g.agent.id).first()
    if polecenie is None:
        return _blad('brak_polecenia', 404)
    if polecenie.status == 'pending':  # powtórka dla zamkniętego polecenia niczego nie zmienia
        dane = _dane_json()
        polecenie.status = 'done' if dane.get('ok') is True else 'failed'
        polecenie.result = _tekst(dane.get('opis'), 2000) or None
        polecenie.done_at = datetime.utcnow()
    return jsonify({'ok': True})


@agent_druku_v2_bp.route('/realtime-token', methods=['GET'])
@_agent_endpoint
def realtime_token():
    """Jak stary endpoint: krótkotrwały JWT do Centrifugo na ten sam kanał `print:agent` (503 = tylko polling)."""
    if not realtime_service.is_enabled():
        return jsonify({'enabled': False, 'reason': 'realtime disabled'}), 503
    try:
        token, ttl = realtime_service.issue_connection_token(
            'print-agent', [realtime_service.CHANNEL_PRINT_AGENT])
    except RuntimeError as e:
        logger.error('Nie udało się wystawić tokena realtime dla agenta v2', extra={'error': str(e)})
        return jsonify({'enabled': False, 'reason': 'misconfigured'}), 503
    return jsonify({'enabled': True, 'token': token, 'channel': realtime_service.CHANNEL_PRINT_AGENT,
                    'sse_url': realtime_service.sse_url(), 'expires_in': ttl})


@agent_druku_v2_bp.route('/wydania/<wersja>/plik', methods=['GET'])
@_agent_endpoint
def plik_wydania(wersja):
    wydanie = PrintAgentRelease.query.filter_by(version_name=wersja, is_active=True).first()
    if wydanie is None:
        return _blad('brak_wydania', 404)
    sciezka = wydania.sciezka_pliku(wydanie)
    if not sciezka.is_file():
        logger.error('Brak pliku aktywnego wydania agenta', extra={'wersja': wersja})
        return _blad('brak_pliku', 404)
    return send_file(str(sciezka), as_attachment=True, download_name=sciezka.name,
                     mimetype='application/octet-stream')
