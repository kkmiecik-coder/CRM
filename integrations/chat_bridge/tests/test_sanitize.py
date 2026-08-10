# -*- coding: utf-8 -*-
# Testy sanitizera tresci wychodzacych: wycinanie podpisu Chatwoota i wykrywanie
# danych kontaktowych, ktorych regulamin Allegro zabrania (ostrzezenie z 10.08.2026).
# Korpus negatywny to prawdziwe zdania z kolejki mostu — ceny, wymiary i terminy
# NIE moga byc brane za numer telefonu.
import importlib

sanitize = importlib.import_module("sanitize")

# Podpis, ktory Chatwoot doklejal do wiadomosci (queue 919, kanal allegro_msg).
PODPIS = (
    "**Anna Paszkowska**\n"
    "Specjalista ds. Obsługi Klienta\n"
    "WoodPower\n"
    "anna.paszkowska@woodpower.pl: mailto:anna.paszkowska@woodpower.pl\n"
    "+48 793 911 916: tel:+48793911916\n"
    "woodpower.pl: https://woodpower.pl\n"
    "Facebook: https://www.facebook.com/profile.php?id=100078058417309"
)


# --- strip_signature -------------------------------------------------------

def test_wycina_podpis_po_standardowym_separatorze():
    tekst = "fv w panelu klienta do pobrania\n\n--\n\n" + PODPIS
    assert sanitize.strip_signature(tekst) == "fv w panelu klienta do pobrania"


def test_wycina_podpis_gdy_separator_ma_wiodaca_spacje():
    # Realny wariant z OLX (queue 909): tekst agenta konczyl sie spacja.
    tekst = "Wymiar nalezy wskazac \n\n --\n\n" + PODPIS
    assert sanitize.strip_signature(tekst) == "Wymiar nalezy wskazac"


def test_zostawia_myslnik_ktory_nie_jest_podpisem():
    tekst = "wymiary do potwierdzenia\n\n--\n\nreszta ustalen bez zmian"
    assert sanitize.strip_signature(tekst) == tekst


def test_wycina_podpis_przy_koncach_linii_crlf():
    # Realne wiadomosci z Chatwoota maja CRLF (queue 905/914) — separator to "--\r\n".
    tekst = "narożniki tez ?\r\n\r\n--\r\n\r\n" + PODPIS
    assert sanitize.strip_signature(tekst) == "narożniki tez ?"


def test_wycina_podpis_przy_crlf_i_wiodacej_spacji():
    tekst = "pozostajemy do dyspozycji.\r\n\r\n --\r\n\r\n" + PODPIS
    assert sanitize.strip_signature(tekst) == "pozostajemy do dyspozycji."


def test_tekst_bez_separatora_bez_zmian():
    tekst = "ok to docinamy wg ww wymiarów"
    assert sanitize.strip_signature(tekst) == tekst


def test_tnie_od_ostatniego_separatora():
    tekst = "pierwsza czesc\n\n--\n\ndruga czesc\n\n--\n\n" + PODPIS
    assert sanitize.strip_signature(tekst) == "pierwsza czesc\n\n--\n\ndruga czesc"


def test_pusty_tekst_nie_wywraca():
    assert sanitize.strip_signature("") == ""
    assert sanitize.strip_signature(None) == ""


# --- find_violations: co MA byc zlapane --------------------------------------

def _typy(tekst):
    return sorted({t for t, _ in sanitize.find_violations(tekst)})


def test_lapie_adres_email():
    assert _typy("proszę napisać na anna.paszkowska@woodpower.pl") == ["mail"]


def test_lapie_link_http():
    assert _typy("cennik jest tu https://woodpower.pl/blaty-debowe") == ["link"]


def test_lapie_gola_domene():
    assert _typy("wszystko widać na woodpower.pl") == ["link"]


def test_lapie_telefon_z_kierunkowym():
    assert _typy("proszę dzwonić +48 793 911 916") == ["telefon"]


def test_lapie_telefon_grupowany():
    assert _typy("793 911 916") == ["telefon"]
    assert _typy("793-911-916") == ["telefon"]


def test_lapie_telefon_ciagiem():
    assert _typy("numer to 793911916") == ["telefon"]


def test_zwraca_wykryty_fragment():
    trafienia = sanitize.find_violations("napisz na biuro@woodpower.pl")
    assert trafienia == [("mail", "biuro@woodpower.pl")]


def test_ten_sam_fragment_raportowany_raz():
    # Zapis "adres: mailto:adres" w podpisie dawalby dwa identyczne trafienia.
    trafienia = sanitize.find_violations("biuro@woodpower.pl: mailto:biuro@woodpower.pl")
    assert trafienia == [("mail", "biuro@woodpower.pl")]


# --- find_violations: czego NIE wolno ruszac ---------------------------------

def test_link_do_allegro_jest_dozwolony():
    assert sanitize.find_violations("oferta: https://allegro.pl/oferta/blat-debowy-1234") == []
    assert sanitize.find_violations("allegrolokalnie.pl/oferta/x") == []


def test_kwoty_nie_sa_telefonem():
    assert sanitize.find_violations("**Dąb Lity A/B 200×30×4 cm | Surowe | 1 szt. 594.83 PLN brutto**") == []
    assert sanitize.find_violations("koszt wysyłki ok 75 zł, kwoty brutto") == []
    assert sanitize.find_violations("**Dąb Mikrowczep A/B 253×80×2.7 cm | 1 szt. 1068.00 PLN**") == []


def test_wymiary_i_terminy_nie_sa_telefonem():
    assert sanitize.find_violations("poprawa, czyli wymiar ma byc: 63x15x1.9 cm surowy ?") == []
    assert sanitize.find_violations("Zanotowane w zamówieniu: wysyłka po 24.08") == []
    assert sanitize.find_violations("na 15.09. na pewno zdążymy :)") == []
    assert sanitize.find_violations("Termin realizacji około 7 dni roboczych") == []


def test_identyfikatory_nie_sa_telefonem():
    assert sanitize.find_violations("nr zamówienia 793911916 jest w systemie") == []
    assert sanitize.find_violations("REGON 380878805") == []
    assert sanitize.find_violations("NIP 813-37-87-635 · KRS 0000743306") == []


def test_kod_pocztowy_nie_jest_telefonem():
    assert sanitize.find_violations("hala produkcyjna: 36-068 Bachórz") == []


def test_czysta_tresc_bez_trafien():
    assert sanitize.find_violations("ok to docinamy wg ww wymiarów") == []
    assert sanitize.find_violations("") == []
    assert sanitize.find_violations(None) == []


# --- sanitize_outgoing: bramkowanie po kanale --------------------------------

def test_allegro_zwraca_trafienia_i_tekst_bez_podpisu():
    tekst, trafienia = sanitize.sanitize_outgoing("allegro_msg", "cennik: woodpower.pl\n\n--\n\n" + PODPIS)
    assert tekst == "cennik: woodpower.pl"
    assert [t for t, _ in trafienia] == ["link"]


def test_allegro_dispute_tez_kontrolowane():
    _, trafienia = sanitize.sanitize_outgoing("allegro_dispute", "mail: biuro@woodpower.pl")
    assert [t for t, _ in trafienia] == ["mail"]


def test_olx_ma_wyciety_podpis_ale_zero_blokad():
    tekst, trafienia = sanitize.sanitize_outgoing("olx", "cennik: woodpower.pl\n\n--\n\n" + PODPIS)
    assert tekst == "cennik: woodpower.pl"
    assert trafienia == []


def test_kanaly_spoza_mostu_bez_zmian():
    tekst, trafienia = sanitize.sanitize_outgoing("mail", "kontakt: biuro@woodpower.pl")
    assert tekst == "kontakt: biuro@woodpower.pl"
    assert trafienia == []
