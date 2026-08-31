# -*- coding: utf-8 -*-
"""
Watchdog porzuconej rozmowy.

_do_handoff odpala się dziś tylko z jawnej decyzji modelu, z limitu tur albo
z twardych reguł — NIGDY z bezczynności. Skutek z audytu: rozmowy kończą się
w statusie 'pending' z botem jako ostatnim mówiącym i nikt ich nie przejmuje.
"""
import pro_watchdog as w


def _rozmowa(conv_id, last_msg_type, minut_temu, teraz=1_000_000):
    return {"id": conv_id, "inbox_id": "5", "last_msg_type": last_msg_type,
            "last_msg_ts": teraz - minut_temu * 60}


class TestZnajdzPorzucone:
    def test_rozmowa_z_botem_na_koncu_po_progu_jest_porzucona(self):
        rozmowy = [_rozmowa(1, "outgoing", 25)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [1]

    def test_rozmowa_swiezsza_niz_prog_nie_jest_porzucona(self):
        rozmowy = [_rozmowa(1, "outgoing", 5)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_ostatnia_wiadomosc_klienta_nie_jest_porzuceniem(self):
        # Klient napisal i czeka — to zadanie kolejki, nie watchdoga.
        rozmowy = [_rozmowa(1, "incoming", 60)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_brak_znacznika_czasu_nie_wywraca(self):
        rozmowy = [{"id": 1, "inbox_id": "5", "last_msg_type": "outgoing",
                    "last_msg_ts": None}]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []

    def test_wiele_rozmow_zwracanych_w_kolejnosci(self):
        rozmowy = [_rozmowa(7, "outgoing", 30), _rozmowa(9, "outgoing", 45)]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [7, 9]

    def test_prawdziwe_api_chatwoota_zwraca_typ_liczbowy_nie_string(self):
        # core.chatwoot._cw_conversations_by_status (a wiec i cw_pending_conversations)
        # niesie last_msg_type PROSTO z pola Chatwoota "message_type": to LICZBA
        # (0=incoming, 1=outgoing), NIE string — patrz sweeper.py/hot_lead_sweeper.py,
        # ktore z tego powodu sprawdzaja OBIE postacie ("in (0, "incoming")" itp.).
        # Test string-owej wersci wyzej sam w sobie NIE wykryje, gdyby ta funkcja
        # dzialala tylko na stringu "outgoing" i w produkcji nigdy nie odpalala.
        rozmowy = [{"id": 3, "inbox_id": "5", "last_msg_type": 1,
                    "last_msg_ts": 1_000_000 - 25 * 60}]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == [3]

    def test_prawdziwy_typ_liczbowy_incoming_nie_jest_porzuceniem(self):
        rozmowy = [{"id": 4, "inbox_id": "5", "last_msg_type": 0,
                    "last_msg_ts": 1_000_000 - 60 * 60}]
        assert w.znajdz_porzucone(rozmowy, teraz=1_000_000, prog_minut=20) == []
