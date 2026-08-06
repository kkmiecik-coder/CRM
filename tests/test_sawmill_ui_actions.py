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

def test_formularz_recznego_pomiaru_ma_wszystkie_piec_wymiarow_i_czas():
    js = _js()
    blok = js.split('function manualLogFormHtml')[1].split('function collectManualLogPayload')[0]
    for pole in ('butt_d1_cm', 'butt_d2_cm', 'top_d1_cm', 'top_d2_cm',
                 'length_cm', 'measured_at'):
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
