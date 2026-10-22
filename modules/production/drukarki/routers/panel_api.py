# -*- coding: utf-8 -*-
"""
Panel zakładki „Drukarki” — /production/api/drukarki/*. Cienki router nad serwisami `drukarki/services`.

Dostęp: zalogowany z modułem `production` (`guard`) — podgląd, Ponów, Anuluj, wydruk próbny; reszta tylko admin
(`admin_required`, oba dekoratory z devices_panel). Każdy zapis commituje, a sygnały realtime idą dopiero po commicie.
"""
import json

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from extensions import db
from modules.logging import get_structured_logger
from modules.production.drukarki import stale
from modules.production.drukarki.models import PrintAgent, PrintAgentCommand, PrintAgentConfig, PrintAgentRelease
from modules.production.drukarki.services import agenci, kolejka, konfiguracja, stan, wydania
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.production.routers.api import print_agent_api
from modules.production.routers.devices_panel import admin_required, guard
from modules.production.services import print_queue_service, realtime_service

# Szablony leżą w modules/production/templates.
drukarki_panel_bp = Blueprint('drukarki_panel', __name__, template_folder='../../templates')
logger = get_structured_logger('production.drukarki_panel')

NA_STRONE = 50


def _blad(kod, status, **reszta):
    return jsonify({'error': kod, **reszta}), status


def _cialo():
    cialo = request.get_json(silent=True)
    return cialo if isinstance(cialo, dict) else {}


def _iso(czas):
    return czas.isoformat() + 'Z' if czas else None


def _aktor_id():
    """Id zalogowanego — czytać przed commitem (commit wygasza atrybuty ORM)."""
    return getattr(current_user, 'id', None)


def _zatwierdz_i_wyslij(*sygnaly):
    """Commit, potem sygnały (`publish` nie rzuca, więc błąd sygnału nie psuje zatwierdzonego zapisu)."""
    db.session.commit()
    for sygnal in sygnaly:
        sygnal()


def _sygnal_agenta(dane):
    return lambda: realtime_service.publish(realtime_service.CHANNEL_PRINT_AGENT, dane)


def _aktywny_albo_409():
    aktywny = agenci.aktywny_v2()
    if aktywny is None:
        return None, _blad('brak_aktywnego_agenta', 409)
    return aktywny, None


@drukarki_panel_bp.errorhandler(Exception)
def _blad_serwera(e):
    if isinstance(e, HTTPException):
        return e
    db.session.rollback()
    logger.error('Panel drukarek: błąd', extra={'endpoint': request.endpoint, 'error_type': type(e).__name__,
                                               'error': str(e)})
    return _blad('blad_serwera', 500)


# ── zakładka, stan, lista zadań ───────────────────────────────────────────────────────────────────────────────────

# Karta „Drukarka etykiet” przeniesiona z Konfiguracji: ustawienia starego agenta i trybu bez agenta (TCP), zapis
# jak dotąd przez POST /production/api/update-configs. Domyślne wartości jak EXPECTED w config_api; token starego
# agenta nie ma domyślnej wartości. Przesunięć tu nie ma — edytuje je tylko dokument konfiguracji (PUT /konfiguracja).
USTAWIENIA_STAREGO_AGENTA = (
    ('LABEL_PRINTER_IP', '192.168.100.199'),
    ('LABEL_PRINTER_PORT', '9100'),
    ('LABEL_PRINTER_TIMEOUT_SECONDS', '3'),
    ('LABEL_PRINTER_RETRY_COUNT', '1'),
    ('LABEL_PRINTER_ALLOWED_STATIONS', 'formatting,packaging'),
    ('LABEL_PRINTER_USE_AGENT', 'false'),
    ('LABEL_PRINTER_AGENT_TOKEN', None),
)


def _czy_admin():
    """Ta sama reguła co `common_api.admin_required`, które pilnuje końcówek admina."""
    return (getattr(current_user, 'role', None) or '').lower() in ('admin', 'administrator')


def _ustawienia_starego_agenta():
    """{klucz: {'wartosc', 'domyslna', 'zmieniono'}} z prod_config; brak wiersza = wartość domyślna."""
    klucze = [k for k, _ in USTAWIENIA_STAREGO_AGENTA]
    wiersze = {c.config_key: c for c in ProductionConfig.query.filter(ProductionConfig.config_key.in_(klucze)).all()}
    wynik = {}
    for klucz, domyslna in USTAWIENIA_STAREGO_AGENTA:
        wiersz = wiersze.get(klucz)
        wartosc = wiersz.config_value if wiersz is not None and wiersz.config_value is not None else domyslna
        wynik[klucz] = {'wartosc': '' if wartosc is None else str(wartosc), 'domyslna': domyslna,
                        'zmieniono': _iso(wiersz.updated_at) if wiersz is not None else None}
    return wynik


@drukarki_panel_bp.route('/tab-content')
@guard
def tab_content():
    admin = _czy_admin()
    return render_template('components/printers-tab-content.html', is_admin=admin, role=stale.ROLE,
                           stary=_ustawienia_starego_agenta() if admin else None)


@drukarki_panel_bp.route('/stan')
@guard
def stan_panelu():
    migawka = stan.migawka()
    wiersz = ProductionConfig.query.filter_by(config_key=print_agent_api.KLUCZ_OSTATNI_KONTAKT).first()
    kontakt = (wiersz.config_value or '').strip() if wiersz is not None else ''
    migawka['stary_agent'] = {'ostatni_kontakt': kontakt + 'Z' if kontakt else None}
    return jsonify(migawka)


@drukarki_panel_bp.route('/zadania')
@guard
def zadania():
    zapytanie = LabelPrintJob.query
    drukarka = request.args.get('drukarka')
    if drukarka:
        zapytanie = zapytanie.filter(LabelPrintJob.printer == drukarka)
    stan_zadania = request.args.get('stan')
    if stan_zadania:
        zapytanie = zapytanie.filter(LabelPrintJob.status == stan_zadania)
    try:
        strona = max(1, int(request.args.get('strona', 1)))
    except ValueError:
        strona = 1
    razem = zapytanie.count()
    wiersze = (zapytanie.order_by(LabelPrintJob.id.desc()).offset((strona - 1) * NA_STRONE)
               .limit(NA_STRONE).all())
    return jsonify({
        'strona': strona, 'na_strone': NA_STRONE, 'razem': razem,
        'zadania': [{
            'id': j.id, 'czas': _iso(j.requested_at), 'drukarka': j.printer, 'kod': j.short_product_id,
            'stanowisko': j.station_code, 'kto': '%s:%s' % (j.requested_by_type, j.requested_by_id),
            'stan': j.status, 'blad': j.error_message,
        } for j in wiersze],
    })


# ── zadania: ponów, anuluj, wydruk próbny (każdy z dostępem do panelu produkcji) ─────────────────────────────────

@drukarki_panel_bp.route('/zadania/<int:job_id>/ponow', methods=['POST'])
@guard
def ponow(job_id):
    aktor = {'type': 'user', 'id': _aktor_id()}
    if db.session.get(LabelPrintJob, job_id) is None:
        return _blad('brak_zadania', 404)
    try:
        nowe = kolejka.ponow(job_id, aktor)
    except ValueError:
        db.session.rollback()
        return _blad('zadania_nie_mozna_ponowic', 409)
    nowe_id = nowe.id
    _zatwierdz_i_wyslij(lambda: realtime_service.publish_print_signal(1))
    return jsonify({'ok': True, 'id': nowe_id})


@drukarki_panel_bp.route('/zadania/<int:job_id>/anuluj', methods=['POST'])
@guard
def anuluj(job_id):
    aktor = {'type': 'user', 'id': _aktor_id()}
    if db.session.get(LabelPrintJob, job_id) is None:
        return _blad('brak_zadania', 404)
    if not kolejka.anuluj(job_id, aktor):
        db.session.rollback()
        return _blad('zadania_nie_mozna_anulowac', 409)
    db.session.commit()
    return jsonify({'ok': True})


@drukarki_panel_bp.route('/wydruk-probny/<drukarka>', methods=['POST'])
@guard
def wydruk_probny(drukarka):
    try:
        job = print_queue_service.wydruk_probny(drukarka, {'type': 'user', 'id': _aktor_id()})
    except print_queue_service.NieznanaDrukarka:
        return _blad('nieznana_drukarka', 404)
    return jsonify({'ok': True, 'id': job.id})


# ── agenci (admin) ────────────────────────────────────────────────────────────────────────────────────────────────

def _agent_json(a):
    return {'id': a.id, 'nazwa': a.name, 'utworzono': _iso(a.created_at), 'uniewazniony': a.revoked_at is not None,
            'ostatni_kontakt': _iso(a.last_seen_at), 'wersja': a.version, 'online': agenci.czy_online(a)}


@drukarki_panel_bp.route('/agenci', methods=['GET'])
@guard
@admin_required
def lista_agentow():
    """Lista agentów — bez tokenów (w bazie jest tylko skrót, jawny token widać raz przy parowaniu)."""
    return jsonify({'agenci': [_agent_json(a) for a in PrintAgent.query.order_by(PrintAgent.id).all()]})


@drukarki_panel_bp.route('/agenci', methods=['POST'])
@guard
@admin_required
def sparuj():
    agent, token = agenci.sparuj(_cialo().get('nazwa'), _aktor_id())
    odpowiedz = {**_agent_json(agent), 'token': token}
    db.session.commit()
    return jsonify(odpowiedz), 201


@drukarki_panel_bp.route('/agenci/<int:agent_id>/token', methods=['POST'])
@guard
@admin_required
def nowy_token(agent_id):
    try:
        token = agenci.nowy_token(agent_id, _aktor_id())
    except ValueError:
        return _blad('brak_agenta', 404)
    db.session.commit()
    return jsonify({'id': agent_id, 'token': token})


@drukarki_panel_bp.route('/agenci/<int:agent_id>/uniewaznij', methods=['POST'])
@guard
@admin_required
def uniewaznij(agent_id):
    if agenci.uniewaznij(agent_id, _aktor_id()) is None:
        return _blad('brak_agenta', 404)
    db.session.commit()
    return jsonify({'ok': True})


# ── konfiguracja aktywnego agenta (admin) ─────────────────────────────────────────────────────────────────────────

@drukarki_panel_bp.route('/konfiguracja', methods=['GET'])
@guard
@admin_required
def pobierz_konfiguracje():
    aktywny, blad = _aktywny_albo_409()
    if blad:
        return blad
    konf = PrintAgentConfig.query.filter_by(agent_id=aktywny.id).first()
    if konf is None:
        return _blad('brak_konfiguracji', 404)
    return jsonify({'wersja': konf.version, 'dane': json.loads(konf.data), 'zrodlo': konf.updated_source,
                    'zapisano': _iso(konf.updated_at)})


@drukarki_panel_bp.route('/konfiguracja', methods=['PUT'])
@guard
@admin_required
def zapisz_konfiguracje():
    aktywny, blad = _aktywny_albo_409()
    if blad:
        return blad
    cialo = _cialo()
    dane = cialo.get('dane')
    wersja_bazowa = cialo.get('wersja_bazowa')
    bledy = konfiguracja.waliduj(dane)
    if wersja_bazowa is not None and (not isinstance(wersja_bazowa, int) or isinstance(wersja_bazowa, bool)):
        bledy.append('Wersja bazowa konfiguracji musi być liczbą całkowitą.')
    if bledy:
        return _blad('bledna_konfiguracja', 400, bledy=bledy)
    try:
        wiersz, nadpisana = konfiguracja.zapisz(aktywny.id, dane, wersja_bazowa, 'crm', 'user:%s' % _aktor_id())
    except ValueError:
        db.session.rollback()
        return _blad('brak_konfiguracji', 404)
    odpowiedz = {'wersja': wiersz.version, 'dane': json.loads(wiersz.data), 'nadpisano': nadpisana}
    _zatwierdz_i_wyslij(_sygnal_agenta({'kind': 'config'}))
    return jsonify(odpowiedz)


@drukarki_panel_bp.route('/konfiguracja/historia', methods=['GET'])
@guard
@admin_required
def historia_konfiguracji():
    aktywny, blad = _aktywny_albo_409()
    if blad:
        return blad
    return jsonify({'historia': konfiguracja.historia(aktywny.id)})


# ── kalibracja, wydania, przełącznik obsługi (admin) ──────────────────────────────────────────────────────────────

@drukarki_panel_bp.route('/kalibracja/<drukarka>', methods=['POST'])
@guard
@admin_required
def kalibracja(drukarka):
    if drukarka not in stale.ROLE:
        return _blad('nieznana_drukarka', 404)
    aktywny, blad = _aktywny_albo_409()
    if blad:
        return blad
    polecenie = PrintAgentCommand(agent_id=aktywny.id, kind='kalibracja', printer=drukarka,
                                  created_by_user_id=_aktor_id())
    db.session.add(polecenie)
    db.session.flush()
    polecenie_id = polecenie.id
    _zatwierdz_i_wyslij(_sygnal_agenta({'kind': 'command'}))
    return jsonify({'ok': True, 'id': polecenie_id}), 201


def _wydanie_json(r):
    return {'id': r.id, 'wersja': r.version_name, 'sha256': r.sha256, 'rozmiar': r.file_size_bytes,
            'notatki': r.release_notes, 'wgrano': _iso(r.uploaded_at), 'aktywne': bool(r.is_active)}


@drukarki_panel_bp.route('/wydania', methods=['GET'])
@guard
@admin_required
def lista_wydan():
    wiersze = PrintAgentRelease.query.order_by(PrintAgentRelease.id.desc()).all()
    return jsonify({'wydania': [_wydanie_json(r) for r in wiersze]})


@drukarki_panel_bp.route('/wydania', methods=['POST'])
@guard
@admin_required
def wgraj_wydanie():
    aktywuj = (request.form.get('aktywne') or '').strip().lower() in ('1', 'true', 'tak', 'on')
    try:
        wydanie = wydania.wgraj(request.files.get('plik'), request.form.get('wersja'),
                                request.form.get('notatki'), _aktor_id(), aktywuj)
    except ValueError as e:
        db.session.rollback()
        return _blad('bledne_wydanie', 400, komunikat=str(e))
    odpowiedz = _wydanie_json(wydanie)
    db.session.commit()
    return jsonify(odpowiedz), 201


@drukarki_panel_bp.route('/wydania/<int:release_id>/aktywne', methods=['PATCH'])
@guard
@admin_required
def aktywne_wydanie(release_id):
    aktywne = _cialo().get('aktywne')
    if not isinstance(aktywne, bool):
        return _blad('bledne_pole_aktywne', 400)
    wydanie = db.session.get(PrintAgentRelease, release_id)
    if wydanie is None:
        return _blad('brak_wydania', 404)
    wydanie.is_active = aktywne
    odpowiedz = _wydanie_json(wydanie)
    db.session.commit()
    return jsonify(odpowiedz)


@drukarki_panel_bp.route('/obsluga/<drukarka>', methods=['PUT'])
@guard
@admin_required
def ustaw_obsluge(drukarka):
    if drukarka not in stale.ROLE:
        return _blad('nieznana_drukarka', 404)
    wartosc = _cialo().get('agent')
    if wartosc not in agenci.OBSLUGA:
        return _blad('bledny_agent', 400)
    poprzednia = agenci.obsluga(drukarka)
    if wartosc == 'nowy':
        aktywny = agenci.aktywny_v2()
        if not agenci.czy_online(aktywny):
            return _blad('nowy_agent_offline', 409)
        if not agenci.ma_drukarke(aktywny, drukarka):
            return _blad('drukarka_poza_konfiguracja', 409)
    agenci.ustaw_obsluge(drukarka, wartosc, _aktor_id())
    if poprzednia == 'stary' and wartosc == 'nowy':
        agenci.oznacz_przelaczenie(drukarka)  # nowy agent odczeka, aż stary dokończy partię
    _zatwierdz_i_wyslij(lambda: realtime_service.publish_print_signal(0))
    return jsonify({'drukarka': drukarka, 'obsluga': wartosc})
