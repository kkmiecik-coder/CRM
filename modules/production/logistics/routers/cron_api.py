# -*- coding: utf-8 -*-
"""
Cron logistyki — co godzinę z crontaba serwera:
    scripts/cron_endpoint.sh POST /production/api/logistics/cron

Endpoint NIE wykonuje długiej pracy: sync worker gunicorna ma 30 s na żądanie.
Przenosi osierocone `czeka_na_logistyke` do pakowania, raz (znacznik w prod_config) przestawia
pozycje już wydanych zamówień na `dostarczone` (okno wdrożenia kroku 4.3), przelicza cykl zamówień
(szybkie, w bazie) i uruchamia w tle dopychacz Base. oraz geokoder adresów. Na końcu faza priorytetów produkcji:
dopisuje brakujące szczeble drabiny i przelicza rangi (`_priorytety`).
"""
import traceback

from flask import current_app, jsonify

from cron_auth import cron_secret_required
from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import logistics_panel_bp
from modules.production.logistics.services import bl_sync, delivery, geocoding

logger = get_structured_logger('production.logistics.cron')


def _priorytety():
    """
    Faza priorytetów produkcji (spec 2026-10-04, 9.3) — PO fazach logistyki i PO uruchomieniu wątków w tle, we
    własnym try/except: błąd priorytetów nie może zatrzymać dopychacza Base. ani geokodera, a fazy logistyki są już
    zatwierdzone. Zwraca (liczba dopisanych szczebli, raport `kolejka.utrwal`) albo (None, None) po błędzie.

    1. `drabina.uzupelnij()` — brakujące szczeble (trasy sprzed wdrożenia), pod blokadą tras; commit osobnej
       transakcji zwalnia blokadę przed przeliczeniem.
    2. `kolejka.utrwal()` — rangi na własnej sesji. Co godzinę, bo tagi „Po terminie” i „Blisko terminu” zmieniają
       się z datą, bez żadnego zdarzenia. Nieudane przeliczenie to raport z `success: False`, nie wyjątek.

    Import lokalny: pakiet priorytetów sięga do logistyki, a ten moduł ładuje się razem z nią (cykl importów).
    """
    try:
        from modules.production.priorytety.services import drabina, kolejka
        uzupelnione = drabina.uzupelnij()
        db.session.commit()
        if uzupelnione:
            logger.info('CRON: dopisane szczeble drabiny priorytetów', extra={'szczeble': uzupelnione})
        return uzupelnione, kolejka.utrwal()
    except Exception as e:
        db.session.rollback()
        logger.error('CRON: błąd fazy priorytetów', extra={
            'error': str(e), 'traceback': traceback.format_exc()})
        return None, None


def _sygnaly_stanowisk(porzuc=False):
    """
    Sygnały `station:<kod>` zaplanowane przez fazy crona (priorytety produkcji, spec 2026-10-04, 5.4): wysyłka PO
    commicie fazy albo — po błędzie i rollbacku — porzucenie planu. Własny try/except: sygnał jest dodatkiem i nie
    może przerwać crona. Import lokalny: pakiet priorytetów sięga do logistyki (cykl importów).
    """
    try:
        from modules.production.priorytety.services import sygnaly
        if porzuc:
            sygnaly.porzuc()
        else:
            sygnaly.wyslij()
    except Exception as e:
        logger.error('CRON: błąd sygnałów stanowisk', extra={'error': str(e)})


@logistics_panel_bp.route('/cron', methods=['POST'])
@cron_secret_required
def cron():
    """
    Przelicza cykl logistyki zamówień i uruchamia w tle dopychacz Base. oraz geokoder adresów.
    Fazy bazodanowe (przeniesienie osieroconych, dostarcz_wydane, przelicz_otwarte) idą w osobnych
    transakcjach: fazy 1 i 3 blokują zamówienia rosnąco po id, faza 2 (dostarcz_wydane) nie bierze blokad
    zamówień, a w jednej transakcji ich suma nie zachowałaby kolejności blokad.
    """
    try:
        # Najpierw produkty zapisane przez stary kod w oknie wdrożenia (patrz
        # delivery.przenies_osierocone_z_logistyki) — przelicz_otwarte widzi je już
        # w pakowaniu.
        przeniesione = delivery.przenies_osierocone_z_logistyki()
        # Każda faza crona w OSOBNEJ transakcji (logistyka etap 4, krok 4.4a). Przeniesienie osieroconych (faza 1)
        # i przelicz_otwarte (faza 3) blokują zamówienia rosnąco po id, ale w jednej transakcji ich suma nie jest
        # rosnąca (trzymalibyśmy zamówienie 100 z pierwszej fazy, prosząc o 50 z trzeciej), a to cykl z hurtową
        # zmianą statusu (MySQL 1213). Faza 2 (dostarcz_wydane) nie bierze blokad zamówień (zwykły odczyt,
        # zapis pozycji po PK), więc jej blokady wierszy pozycji, wzięte bez blokady zamówienia, siedziałyby w jednej
        # transakcji z blokadami zamówień fazy 3 w odwróconej kolejności (pozycja przed zamówieniem),
        # czyli odwrotnie niż pisarze stanowisk i panelu, którzy biorą zamówienie najpierw. Commit po fazie
        # zwalnia jej blokady przed następną. Skutek uboczny: błąd późniejszej fazy (500) nie cofa wcześniejszej, co jest bezpieczne — każda jest
        # idempotentna, a dostarcz_wydane commituje razem ze swoim znacznikiem jednorazowości.
        db.session.commit()
        # Priorytety produkcji (spec 2026-10-04, 5.4): przeniesienie zaplanowało sygnały dla tabletów (Pakowanie
        # dostało pracę, z innych stanowisk zszedł kafel) — wysyłamy je po commicie tej fazy.
        _sygnaly_stanowisk()
        if przeniesione:
            logger.warning('CRON: produkty w czeka_na_logistyke przeniesione do pakowania', extra={
                'przeniesione': przeniesione})
        # Okno wdrożenia kroku 4.3: pozycje już wydanych odbiorów osobistych przestawiamy na
        # 'dostarczone' dopiero po restarcie (migracja tego nie robi — stary kod nie zna wartości
        # ENUM, patrz delivery.dostarcz_wydane). JEDNORAZOWO: po pierwszym udanym przebiegu w
        # prod_config zostaje znacznik `logistyka_wydane_dostarczone` i kolejne przebiegi zwracają 0
        # bez pytania o pozycje — inaczej co godzinę przestawialibyśmy na 'dostarczone' pozycje wydanego
        # zamówienia, które wróciły z doróbki i są znów spakowane, choć klient ich nie odebrał.
        wydane_dostarczone = delivery.dostarcz_wydane()
        db.session.commit()  # osobna transakcja tej fazy (patrz wyżej)
        if wydane_dostarczone:
            logger.info('CRON: pozycje wydanych zamówień przestawione na dostarczone', extra={
                'pozycje': wydane_dostarczone})
        przeliczone = delivery.przelicz_otwarte()
        db.session.commit()
        uruchomiony = bl_sync.uruchom_w_tle(current_app._get_current_object())
        geokoder = geocoding.uruchom_w_tle(current_app._get_current_object())
        szczeble_uzupelnione, priorytety_utrwalone = _priorytety()
        wstrzymane = bl_sync.wstrzymane_do()
        return jsonify({
            'success': True,
            'przeniesione_z_logistyki': przeniesione,
            'wydane_dostarczone': wydane_dostarczone,
            'przeliczone': przeliczone,
            'dopychacz_uruchomiony': bool(uruchomiony),
            'geokoder_uruchomiony': bool(geokoder),
            'base_wstrzymane_do': wstrzymane.isoformat() if wstrzymane else None,
            'szczeble_uzupelnione': szczeble_uzupelnione,
            'priorytety_utrwalone': priorytety_utrwalone,
        })
    except Exception as e:
        db.session.rollback()
        _sygnaly_stanowisk(porzuc=True)
        logger.error('CRON: błąd przeliczania logistyki', extra={
            'error': str(e), 'traceback': traceback.format_exc()})
        return jsonify({'success': False, 'error': str(e)}), 500
