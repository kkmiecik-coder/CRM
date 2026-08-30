# -*- coding: utf-8 -*-
"""
Inwariant I2: nic nie idzie dalej bez potwierdzenia klienta.

Stary silnik miał flagę awaiting_confirm — mówiła, ŻE potwierdzenie było, ale nie
mówiła, CZEGO dotyczyło. Rozmowa #2016 z audytu: klient zmienił grubość, potwierdził
podsumowanie, a w CRM wylądowała wycena sprzed zmiany. Dlatego potwierdzamy PODPIS
TREŚCI: każda zmiana pozycji po potwierdzeniu unieważnia je automatycznie.
"""
import hashlib
import json
import time

from core.db import db

# Pola, które klient realnie potwierdza. Cokolwiek spoza tej listy (notatki robocze,
# znaczniki wewnętrzne) NIE MOŻE unieważniać zgody.
_POLA_ISTOTNE = ("id", "produkt", "dlugosc", "szerokosc", "grubosc", "ilosc",
                 "selected_variant", "finishing_id", "edges", "otwory")


def podpis(pozycje):
    """Stabilny odcisk tego, co klient potwierdza."""
    istotne = [
        {k: p.get(k) for k in _POLA_ISTOTNE if k in p}
        for p in sorted(pozycje or [], key=lambda x: str(x.get("id")))
    ]
    material = json.dumps(istotne, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def sprawdz_cytat(cytat, ostatnia_wiadomosc_klienta):
    """Czy cytat dosłownie występuje w ostatniej wiadomości klienta.

    To jest zabezpieczenie przed zgodą, której nie było: model nie może
    wymyślić potwierdzenia, bo musi wskazać fragment realnego tekstu.
    """
    fragment = (cytat or "").strip().lower()
    tekst = (ostatnia_wiadomosc_klienta or "").strip().lower()
    if not fragment or not tekst:
        return False
    return fragment in tekst


def _biezace_pozycje():
    from bots_pro import stan
    return stan.pozycje()


def _stan_potwierdzenia():
    """(potwierdzony_podpis, cytat) dla bieżącej rozmowy."""
    from bots_pro import stan
    polaczenie = db()
    wiersz = polaczenie.execute(
        "SELECT potwierdzony_podpis, potwierdzenie_cytat FROM pro_stan WHERE conv_id=?",
        (stan.conv_id(),)).fetchone()
    polaczenie.close()
    if not wiersz:
        return (None, None)
    return (wiersz["potwierdzony_podpis"], wiersz["potwierdzenie_cytat"])


def potwierdz(cytat_klienta):
    """Rejestruje zgodę klienta na aktualne pozycje."""
    from bots_pro import stan
    ostatnia = stan.ostatnia_wiadomosc_klienta()
    if not sprawdz_cytat(cytat_klienta, ostatnia):
        return {"ok": False, "error": "CYTAT_SPOZA_WIADOMOSCI",
                "wskazowka": "Podaj dosłowny fragment ostatniej wiadomości klienta. "
                             "Jeśli klient nie potwierdził — nie wołaj tego narzędzia."}

    biezacy = podpis(_biezace_pozycje())
    polaczenie = db()
    polaczenie.execute(
        "INSERT INTO pro_stan(conv_id, potwierdzony_podpis, potwierdzenie_cytat, "
        "potwierdzenie_ts) VALUES(?,?,?,?) "
        "ON CONFLICT(conv_id) DO UPDATE SET potwierdzony_podpis=excluded.potwierdzony_podpis, "
        "potwierdzenie_cytat=excluded.potwierdzenie_cytat, "
        "potwierdzenie_ts=excluded.potwierdzenie_ts",
        (stan.conv_id(), biezacy, cytat_klienta, time.time()))
    polaczenie.commit()
    polaczenie.close()
    return {"ok": True, "podpis": biezacy}


def sprawdz_bramke():
    """Czy wolno zapisać wycenę albo podać link do zamówienia."""
    zapisany, cytat = _stan_potwierdzenia()
    if not zapisany:
        return {"ok": False, "error": "BRAK_POTWIERDZENIA",
                "wskazowka": "Najpierw wyślij podsumowanie i poczekaj, aż klient je potwierdzi."}

    if zapisany != podpis(_biezace_pozycje()):
        return {"ok": False, "error": "POTWIERDZENIE_NIEAKTUALNE",
                "wskazowka": "Dane zmieniły się po potwierdzeniu. Wyślij nowe podsumowanie "
                             "i poproś o ponowne potwierdzenie."}

    return {"ok": True, "cytat": cytat}
