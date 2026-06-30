# -*- coding: utf-8 -*-
import importlib
footer = importlib.import_module("footer")


def test_olx_ma_adres_i_imie():
    f = footer.build_footer("olx", "Anna Paszkowska")
    assert f.startswith("Pozdrawiam,")
    assert "Anna Paszkowska" in f
    assert "Bachórz 14N" in f
    assert "woodpower.pl" in f


def test_allegro_msg_bez_adresu():
    f = footer.build_footer("allegro_msg", "Jan Kowalski")
    assert "Jan Kowalski" in f
    assert "Dział Obsługi Klienta" in f
    assert "Bachórz" not in f  # krotka stopka bez adresu


def test_allegro_dispute_taka_sama_jak_msg():
    assert footer.build_footer("allegro_dispute", "X") == footer.build_footer("allegro_msg", "X")


def test_kanaly_bez_stopki_zwracaja_pusty():
    assert footer.build_footer("mail", "Anna") == ""
    assert footer.build_footer("chat-live", "Anna") == ""
    assert footer.build_footer(None, "Anna") == ""


def test_brak_imienia_uzywa_fallbacku():
    assert "Zespół WoodPower" in footer.build_footer("olx", "")
    assert "Zespół WoodPower" in footer.build_footer("olx", None)
    assert "Zespół WoodPower" in footer.build_footer("olx", "   ")


def test_placeholder_zawsze_podmieniony():
    for ch in ("olx", "allegro_msg", "allegro_dispute"):
        assert "{agent}" not in footer.build_footer(ch, "Anna")
