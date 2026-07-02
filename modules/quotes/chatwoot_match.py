# -*- coding: utf-8 -*-
# Dopasowanie kontaktow OLX z Chatwoota do klientow CRM po STALYM ID KUPUJACEGO.
#
# Most tworzy identyfikator kontaktu jako "olx-{id_kupujacego}-{id_watku}"
# (integrations/chat_bridge/channels/olx.py). Id watku zmienia sie z kazda nowa rozmowa,
# a id kupujacego jest stale. Dopasowujemy wiec po samym prefiksie "olx-{id_kupujacego}",
# zeby w panelu pokazac pelna historie wycen kupujacego niezaleznie od watku.
#
# Modul jest celowo czysty (tylko `re`) — bez importow Flaska/bazy — zeby dalo sie go
# testowac w izolacji i uzywac zarowno w routerze, jak i w testach jednostkowych.
import re

# Caly identyfikator OLX: "olx-<cyfry>" z opcjonalnym "-<cyfry>" (id watku). Wielkosc liter bez znaczenia.
_OLX_ID_RE = re.compile(r'^\s*(olx-\d+)(?:-\d+)?\s*$', re.IGNORECASE)


def olx_buyer_prefix(identifier):
    """Wyluskuje staly prefiks kupujacego z identyfikatora kontaktu OLX.

    'olx-5028153-25066393520' -> 'olx-5028153'
    'olx-5028153'             -> 'olx-5028153'
    Zwraca None dla wszystkiego, co nie jest identyfikatorem OLX (allegro-..., e-mail, puste).
    """
    if not identifier:
        return None
    m = _OLX_ID_RE.match(identifier)
    if not m:
        return None
    return m.group(1).lower()


def name_matches_olx_prefix(name, prefix):
    """Czy nazwa klienta w CRM zawiera prefiks kupujacego OLX jako caly numer.

    Zakotwiczenie (?!\\d) chroni przed sytuacja, w ktorej 'olx-5028153' zlapaloby
    'olx-50281539' (inny, dluzszy numer kupujacego).
    """
    if not name or not prefix:
        return False
    return re.search(re.escape(prefix) + r'(?!\d)', name, re.IGNORECASE) is not None
