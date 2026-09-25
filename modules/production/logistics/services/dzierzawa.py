# -*- coding: utf-8 -*-
"""
Dzierżawa „jeden wykonawca na cały serwer” w tabeli prod_config.

Gunicorn ma kilka workerów (procesów). Wątek w tle uruchomiony w każdym z nich
osobno przekroczyłby limity usług zewnętrznych (Base.: 100 zapytań/min na konto,
Nominatim: 1 zapytanie/s). Dzierżawa to wiersz prod_config z chwilą ważności
w ISO; przejmuje ją warunkowy UPDATE (atomowy w MySQL), odnawia porównanie
z poprzednią wartością. Proces, który padł, oddaje ją sam po `czas_s`.

Klucze: 'logistyka_bl_dzierzawa' (wysyłka do Base., etap 1),
'logistyka_geo_dzierzawa' (geokodowanie, etap 2). Obok nich zwykła wartość
pomocnicza przez `zapisz()`: 'logistyka_geo_postep' (postęp geokodera, JSON).

`updated_at = updated_at` w każdym UPDATE: kolumna prod_config.updated_at ma
w MySQL ON UPDATE CURRENT_TIMESTAMP (migracja 2026-08-11-07). Przejęcie,
odnowienie i zwolnienie dzierżawy (co ~1,5 s w czasie pracy dopychacza)
podbijałyby ją, a MAX(prod_config.updated_at) wchodzi do ETagu podsumowania
stanowiska tabletu (mobile_api) i unieważnia cache konfiguracji
(worker_service) — tablety dostawałyby pełne odpowiedzi zamiast 304, a cache
konfiguracji byłby czyszczony w kółko. Jawne przypisanie bieżącej wartości
wyłącza auto-aktualizację w MySQL; w SQLite (testy) jest nieszkodliwe. Surowe
UPDATE-y nie wyzwalają też ORM-owego onupdate modelu ProductionConfig.
"""
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.models import ProductionConfig, get_local_now

ZERO = '1970-01-01T00:00:00'


def _iso(chwila):
    return chwila.replace(microsecond=0).isoformat()


def wiersz(klucz):
    """Wiersz prod_config; tworzy go, jeśli migracja go nie założyła (testy, świeża baza)."""
    rekord = ProductionConfig.query.filter_by(config_key=klucz).first()
    if rekord is None:
        db.session.add(ProductionConfig(
            config_key=klucz, config_value=ZERO, config_type='string',
            config_description=u'Logistyka: stan pracy w tle'))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        rekord = ProductionConfig.query.filter_by(config_key=klucz).first()
    return rekord


def przejmij(klucz, czas_s, teraz=None):
    """Znacznik ważności przy sukcesie, None gdy dzierżawę trzyma ktoś inny."""
    teraz = teraz or get_local_now()
    wiersz(klucz)
    nowa = _iso(teraz + timedelta(seconds=czas_s))
    wynik = db.session.execute(
        text('UPDATE prod_config SET config_value = :nowa, updated_at = updated_at '
             'WHERE config_key = :klucz AND config_value < :teraz'),
        {'nowa': nowa, 'klucz': klucz, 'teraz': _iso(teraz)})
    db.session.commit()
    return nowa if wynik.rowcount == 1 else None


def odnow(klucz, znacznik, czas_s, teraz=None):
    """Przedłuża własną dzierżawę; None, gdy ktoś ją przejął (nasza wygasła)."""
    teraz = teraz or get_local_now()
    nowa = _iso(teraz + timedelta(seconds=czas_s))
    if nowa == znacznik:
        return znacznik
    wynik = db.session.execute(
        text('UPDATE prod_config SET config_value = :nowa, updated_at = updated_at '
             'WHERE config_key = :klucz AND config_value = :stara'),
        {'nowa': nowa, 'klucz': klucz, 'stara': znacznik})
    db.session.commit()
    return nowa if wynik.rowcount == 1 else None


def zwolnij(klucz, znacznik):
    db.session.execute(
        text('UPDATE prod_config SET config_value = :zero, updated_at = updated_at '
             'WHERE config_key = :klucz AND config_value = :znacznik'),
        {'zero': ZERO, 'klucz': klucz, 'znacznik': znacznik})
    db.session.commit()


def zapisz(klucz, wartosc):
    """
    Bezwarunkowy zapis wartości pomocniczej pracy w tle (np. postęp geokodera,
    'logistyka_geo_postep' — zapisywany po każdym zamówieniu). Surowy UPDATE
    z `updated_at = updated_at` z tego samego powodu co dzierżawa (ETag tabletów,
    patrz docstring modułu). Wiersz tworzy leniwie `wiersz()`.
    """
    wiersz(klucz)
    db.session.execute(
        text('UPDATE prod_config SET config_value = :w, updated_at = updated_at '
             'WHERE config_key = :k'),
        {'w': wartosc, 'k': klucz})
    db.session.commit()
