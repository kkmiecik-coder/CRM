# -*- coding: utf-8 -*-
# Kontrola tresci WYCHODZACYCH na OLX/Allegro.
#
# Powod: 10.08.2026 Allegro przyslalo ostrzezenie o linkach do stron www w tresci
# wiadomosci. Zrodlem byl natywny podpis Chatwoota (flaga channel_api_signature_enabled
# u agenta) — OLX i Allegro to skrzynki typu "api", wiec jedno klikniecie w polu
# odpowiedzi doklejalo do wiadomosci mail, telefon i linki. Most jest ostatnia linia
# obrony: podpis wycina, a na Allegro nie wypuszcza tresci z danymi kontaktowymi.
#
# Modul jest czysty (bez I/O i zaleznosci od env) — jak footer.py.
import re

# Separator, po ktorym Chatwoot dokleja podpis (linia samego "--", biale znaki dowolne).
# \r jest tu obowiazkowe: realne wiadomosci z Chatwoota maja konce linii CRLF,
# wiec linia separatora to "--\r" (queue 905/914).
_SEPARATOR = re.compile(r"(?m)^[ \t\r]*--[ \t\r]*$")

# Znaczniki, po ktorych poznajemy, ze ogon po separatorze to podpis firmowy,
# a nie tresc agenta. Bez tego "--" uzyte jako zwykly myslnik kasowaloby tekst.
_MARKERY_PODPISU = ("mailto:", "tel:", "http", "sp. z o.o.")

_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def strip_signature(text):
    """Usuwa blok podpisu doklejony przez Chatwoota (wszystko od ostatniej linii
    "--" w dol), ale tylko gdy ogon rzeczywiscie wyglada na podpis."""
    if not text:
        return ""
    trafienia = list(_SEPARATOR.finditer(text))
    if not trafienia:
        return text
    ostatni = trafienia[-1]
    ogon = text[ostatni.end():]
    if not _wyglada_na_podpis(ogon):
        return text
    return text[:ostatni.start()].rstrip()


def _wyglada_na_podpis(ogon):
    """Czy ogon po separatorze to stopka firmowa (dane kontaktowe), a nie tresc."""
    niski = ogon.lower()
    if any(m in niski for m in _MARKERY_PODPISU):
        return True
    return bool(_MAIL.search(ogon))


# --- wykrywanie danych kontaktowych -----------------------------------------

# Linki: pelny URL oraz gola domena z zamknietej listy TLD (zeby liczby i skroty
# w rodzaju "sp. z o.o." nie byly brane za adres).
_TLD = "pl|com|eu|net|org|de|shop|store|info"
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_DOMENA = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:%s)\b(?:/[^\s]*)?" % _TLD, re.I)

# Linki na Allegro dozwolone — wlasna oferta to nie jest sprzedaz poza serwisem.
_HOSTY_DOZWOLONE = ("allegro.pl", "allegrolokalnie.pl", "allegro.com")

# Telefon: z kierunkowym (+48 / 0048) albo 9 cyfr — grupowanych lub ciagiem.
# Lookaround pilnuje, zeby nie wycinac kawalka dluzszej liczby (KRS, ID oferty).
_TEL_KIERUNKOWY = re.compile(r"(?:\+|00)\s?48[\s.\-]?\d{3}[\s.\-]?\d{3}[\s.\-]?\d{3}")
_TEL_9_CYFR = re.compile(r"(?<!\d)\d{3}[\s.\-]?\d{3}[\s.\-]?\d{3}(?!\d)")

# Jednostki i waluty tuz za liczba = to kwota albo wymiar, nie numer telefonu.
_JEDNOSTKI = re.compile(r"^\s*(?:zł|zl|pln|eur|usd|gr|cm|mm|m|szt|kg|dni)\b", re.I)

# Slowa, po ktorych 9 cyfr to identyfikator, nie telefon.
_ID_DOKLADNE = ("nr", "id", "regon", "nip", "krs")
_ID_PREFIKSY = ("ofert", "zamów", "zamow")


def find_violations(text):
    """Dane kontaktowe zabronione w wiadomosciach na Allegro:
    [(typ, fragment)] dla typ in {"mail", "link", "telefon"}; [] gdy czysto."""
    if not text:
        return []
    trafienia = []
    reszta = text
    # Maile zdejmujemy pierwsze — inaczej domena z adresu poszlaby drugi raz jako link.
    for m in _MAIL.finditer(text):
        trafienia.append(("mail", m.group(0)))
    reszta = _zamaskuj(reszta, _MAIL)
    for wzor in (_URL, _DOMENA):
        for m in wzor.finditer(reszta):
            if not _host_dozwolony(m.group(0)):
                trafienia.append(("link", m.group(0)))
        reszta = _zamaskuj(reszta, wzor)
    for m in _TEL_KIERUNKOWY.finditer(reszta):
        trafienia.append(("telefon", m.group(0)))
    reszta = _zamaskuj(reszta, _TEL_KIERUNKOWY)
    for m in _TEL_9_CYFR.finditer(reszta):
        if _JEDNOSTKI.match(reszta[m.end():]):
            continue  # kwota albo wymiar
        if _po_slowie_identyfikatora(reszta[:m.start()]):
            continue  # numer oferty/zamowienia, NIP, REGON
        trafienia.append(("telefon", m.group(0)))
    return _bez_powtorzen(trafienia)


def _bez_powtorzen(trafienia):
    """Ten sam fragment potrafi wystapic kilka razy (podpis ma "adres: mailto:adres") —
    agentowi pokazujemy kazdy raz jeden, w kolejnosci wykrycia."""
    widziane, wynik = set(), []
    for pozycja in trafienia:
        if pozycja in widziane:
            continue
        widziane.add(pozycja)
        wynik.append(pozycja)
    return wynik


def _zamaskuj(text, wzor):
    """Podmienia trafienia wzorca na spacje — dlugosc tekstu bez zmian, wiec
    kolejne wzorce widza te same pozycje, ale juz nie te same znaki."""
    return wzor.sub(lambda m: " " * len(m.group(0)), text)


def _host_dozwolony(fragment):
    host = re.sub(r"^https?://", "", fragment, flags=re.I).split("/")[0].lower()
    host = host.split("?")[0].strip(".")
    return any(host == d or host.endswith("." + d) for d in _HOSTY_DOZWOLONE)


def _po_slowie_identyfikatora(przed):
    slowa = re.split(r"[\s:#]+", przed.lower().strip())
    if not slowa:
        return False
    ostatnie = slowa[-1]
    return ostatnie in _ID_DOKLADNE or ostatnie.startswith(_ID_PREFIKSY)


# --- wejscie dla workera -----------------------------------------------------

# Kanaly obslugiwane przez most — maja wlasna stopke z footer.py, wiec podpis
# Chatwoota jest tam zawsze zbednym duplikatem.
_KANALY_MOSTU = ("olx", "allegro_msg", "allegro_dispute")
# Kanaly, na ktorych dane kontaktowe blokuja wysylke (regulamin Allegro).
_KANALY_BLOKOWANE = ("allegro_msg", "allegro_dispute")


def sanitize_outgoing(channel, text):
    """(tekst bez podpisu, trafienia). Trafienia tylko dla kanalow Allegro —
    na OLX stopka mostu i tak zawiera adres firmy."""
    if channel not in _KANALY_MOSTU:
        return (text or ""), []
    czysty = strip_signature(text)
    if channel not in _KANALY_BLOKOWANE:
        return czysty, []
    return czysty, find_violations(czysty)
