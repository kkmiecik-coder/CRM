# -*- coding: utf-8 -*-
"""
Brakujące akcje w UI trakowni — protokół PDF i ręczne dopisanie pomiaru.

Backend obu ścieżek istniał od dawna (GET /orders/<id>/protocol.pdf,
POST /orders/<id>/logs), ale grep po szablonach i JS trakowni nie znajdował
ani jednego odwołania — czyli dla użytkownika panelu te ścieżki po prostu
nie istniały. Nie mamy tu przeglądarki (żadnego renderowania DOM ani
wykonania JS), więc te testy świadomie NIE deklarują zachowania
interaktywnego — sprawdzają wyłącznie, że odwołania do obu endpointów
faktycznie są w źródle sawmill.js, w miejscach, które je uruchamiają
(akcje wiersza tabeli / modal szczegółów zlecenia).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAWMILL_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'sawmill', 'static', 'js', 'sawmill.js',
)


def _js():
    with open(SAWMILL_JS, encoding='utf-8') as f:
        return f.read()


# ── Protokół PDF (spec, sekcja 9: Szczegóły / Protokół PDF / Rozlicz) ───────

def test_akcje_wiersza_maja_link_do_protokolu_pdf():
    js = _js()
    assert '/protocol.pdf' in js, u'brak odwołania do GET /orders/<id>/protocol.pdf w sawmill.js'
    assert 'protocolPdfLinkHtml' in js


def test_link_do_protokolu_otwiera_nowa_karte():
    """Wymaganie: „otwierający protokół w nowej karcie" — target=_blank."""
    js = _js()
    blok = js.split('function protocolPdfLinkHtml')[1].split('\n\n')[0]
    assert 'target="_blank"' in blok


def test_link_do_protokolu_jest_wywolywany_w_wierszu_zlecenia():
    """Musi być faktycznie użyty przy renderowaniu wiersza, nie tylko zdefiniowany."""
    js = _js()
    blok = js.split('function renderOrderRow')[1].split('function ')[0]
    assert 'protocolPdfLinkHtml(o.id)' in blok


# ── Ręczne dopisanie pomiaru (spec, sekcja 6 — droga druga ratunku dla 409) ──

def test_formularz_recznego_pomiaru_ma_oba_wymiary_i_czas():
    js = _js()
    blok = js.split('function manualLogFormHtml')[1].split('function collectManualLogPayload')[0]
    for pole in ('mid_circumference_cm', 'length_cm', 'measured_at'):
        assert pole in blok, u'brak pola {} w formularzu ręcznego pomiaru'.format(pole)


def test_recznie_dodany_pomiar_woła_post_logs():
    js = _js()
    assert "orders/' + orderId + '/logs'" in js
    assert "method: 'POST'" in js


def test_submit_manual_log_jest_wystawiony_na_window_sawmill():
    """Funkcja musi być dostępna z atrybutu onclick w dynamicznie generowanym HTML."""
    js = _js()
    assert 'submitManualLog: submitManualLog' in js
    assert 'Sawmill.submitManualLog(' in js


def test_formularz_recznego_pomiaru_jest_w_szczegolach_zlecenia():
    """Ma siedzieć w modalu szczegółów (renderDetailsBody), nie gdzie indziej."""
    js = _js()
    blok = js.split('function renderDetailsBody')[1].split('function renderDetailsFooter')[0]
    assert 'manualLogFormHtml(o.id)' in blok


# ── Różnice widoczne dopiero po zakończeniu zlecenia ────────────────────────

def test_wiersz_listy_deleguje_roznice_do_diff_cells():
    """
    renderOrderRow nie może formatować różnic samodzielnie — inaczej stan
    „czeka na zakończenie" trzeba by obsłużyć w dwóch miejscach i jedno
    z nich zostałoby pominięte przy następnej zmianie.
    """
    js = _js()
    blok = js.split('function renderOrderRow')[1].split('function renderAuditItem')[0]
    assert 'diffCellsHtml(o)' in blok
    assert 'difference_m3' not in blok, u'renderOrderRow formatuje różnicę samodzielnie'


def test_puste_roznice_maja_wyjasnienie_zamiast_samego_myslnika():
    """
    Sam myślnik jest nieodróżnialny od braku danych — musi mieć title,
    inaczej admin nie wie, czy różnica jest zerowa, czy jeszcze nieznana.
    """
    js = _js()
    blok = js.split('function diffCellsHtml')[1].split('function renderOrderRow')[0]
    assert 'o.differences_pending' in blok
    assert 'PENDING_TITLE' in blok
    assert 'zakończeniu zlecenia' in js


def test_flaga_odchylenia_nie_renderuje_sie_przy_oczekujacej_roznicy():
    """Flaga siedzi w gałęzi PO sprawdzeniu differences_pending, nie przed nim."""
    js = _js()
    blok = js.split('function diffCellsHtml')[1].split('function renderOrderRow')[0]
    assert blok.index('o.differences_pending') < blok.index('sawmill-flag-icon')


# ── Historia audytu po polsku ───────────────────────────────────────────────

def test_kazda_akcja_audytu_ma_polska_etykiete():
    """
    Historię czytają ludzie z biura — kod z bazy (order_reopen) nie może
    trafiać na ekran surowy. Test pilnuje SYNCHRONIZACJI: dodanie akcji do
    AUDIT_ACTIONS bez etykiety w JS ma tu paść, a nie ujawnić się dopiero
    użytkownikowi.
    """
    from modules.production.sawmill.models import AUDIT_ACTIONS
    js = _js()
    blok = js.split('var AUDIT_LABELS = {')[1].split('};')[0]
    for action in sorted(AUDIT_ACTIONS):
        assert action + ':' in blok, u'brak polskiej etykiety dla akcji {}'.format(action)


def test_etykiety_audytu_nie_zawieraja_podkreslen_z_kodow():
    """Etykieta ma być zdaniem po polsku, nie przepisanym kodem akcji."""
    js = _js()
    blok = js.split('var AUDIT_LABELS = {')[1].split('};')[0]
    for linia in blok.strip().splitlines():
        if ':' not in linia:
            continue
        etykieta = linia.split(':', 1)[1].strip().strip(",").strip("'")
        assert '_' not in etykieta, u'etykieta wygląda na kod: {}'.format(etykieta)


def test_audyt_pokazuje_nazwisko_zamiast_numeru_uzytkownika():
    js = _js()
    blok = js.split('function renderAuditItem')[1].split('function renderDetailsBody')[0]
    assert 'a.user_name' in blok
    assert blok.index('a.user_name') < blok.index('a.user_id'), \
        u'numer użytkownika jest sprawdzany przed nazwiskiem'
