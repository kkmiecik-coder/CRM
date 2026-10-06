# -*- coding: utf-8 -*-
"""
Porządek listy Lakierni (spec 2026-10-04, ustalenie 15 i sekcja 3.2 „Lista Lakierni”; decyzje Konrada 5.10).

Lakiernia nie ma stołu: tablet pokazuje pełną listę `GET /api/mobile/stations/painting/orders`, a pracownik wybiera
sam. Listę układa serwer PO WYKOŃCZENIU — cała grupa wykończenia w jednym ciągu (jedno rozrobione wiadro), grupy
w kolejności najpilniejszej pozycji, w grupie po randze, doróbki pierwsze (doróbka ciągnie swoją grupę na początek).
Pozostałe stanowiska: lista bez zmian (kolejność z SQL, po randze).

O tym, które stanowisko ma taką listę, decyduje kod stanowiska — `ustawienia.STANOWISKA_BEZ_STOLU` (jedno miejsce:
porządek listy i brak stołu). Nie ma na to klucza w `prod_config`: decyzja jest stała, zmiana = zmiana kodu.

Czyste funkcje: żadnych zapytań i żadnego `db.session` — pracują na pozycjach już wczytanych (listy tabletu mają
`joinedload` zamówienia). Ranga pozycji to pamięć podręczna z ostatniego `kolejka.utrwal()`, więc tagi terminowe
działają tu z opóźnieniem do najbliższego przeliczenia — jak na monitorach.
"""
from datetime import datetime

from modules.production.priorytety.services import ustawienia
from modules.production.services.station_catalog import STATION_PENDING_STATUS

# Pozycja bez rangi (zamówienie jeszcze nieprzeliczone) idzie na koniec — jak `COALESCE(priority_rank, 999999)` w SQL.
_BEZ_RANGI = 999999
_LAKIEROWANE = 'lakierowane'


def _norma(wartosc):
    """Wartość pola wykończenia do klucza grupy: bez spacji na brzegach, małymi literami; pusty napis = brak."""
    if wartosc is None:
        return None
    tekst = str(wartosc).strip().lower()
    return tekst or None


def klucz_grupy_wykonczenia(item):
    """
    Grupa wykończenia pozycji: (rodzaj, typ koloru, kolor, połysk). Ten sam podział na partie, który lakiernik zna
    z sortowania „Partia” w appce 1.7.3 (`batchKeyOf`): połysk liczy się TYLKO dla lakierowanych — dla pozostałych
    jest pusty. Brak wartości to osobna wartość klucza, nie „pasuje do wszystkiego”.
    """
    rodzaj = _norma(item.parsed_finish_type)
    polysk = _norma(item.parsed_finish_gloss) if rodzaj == _LAKIEROWANE else None
    return (rodzaj, _norma(item.parsed_finish_color_type), _norma(item.parsed_finish_color), polysk)


def grupa_wykonczenia_json(item):
    """Grupa wykończenia w DTO pozycji Lakierni — appka rysuje separator grupy z tego pola, nie z własnego klucza."""
    rodzaj, typ_koloru, kolor, polysk = klucz_grupy_wykonczenia(item)
    return {'rodzaj': rodzaj, 'typ_koloru': typ_koloru, 'kolor': kolor, 'polysk': polysk}


def nazwa_grupy_wykonczenia(item):
    """Nazwa grupy wykończenia dla ludzi (zakładka Stanowiska, monitor Lakierni): „lakierowane · bezbarwny · mat” —
    pola klucza grupy w kolejności, brak wartości pomijany."""
    czesci = [czesc for czesc in klucz_grupy_wykonczenia(item) if czesc]
    return u' · '.join(czesci) or u'bez wykończenia'


def _numer(item):
    order = getattr(item, 'order', None)
    return (order.internal_order_number if order is not None else None) or ''


def _klucz_pozycji(item):
    """Pilność pozycji na liście Lakierni: doróbki pierwsze (starsza wcześniej), dalej ranga (brak na końcu), numer
    zamówienia, id."""
    dorobka = item.original_product_id is not None
    return (0 if dorobka else 1,
            (item.created_at or datetime.max) if dorobka else datetime.min,
            item.priority_rank if item.priority_rank is not None else _BEZ_RANGI,
            _numer(item), item.id)


def _klucz_reszty(item):
    """Dzisiejszy klucz listy (ranga, numer zamówienia, id) — dla pozycji w innych statusach."""
    return (item.priority_rank if item.priority_rank is not None else _BEZ_RANGI, _numer(item), item.id)


def _klucz_nazwy_grupy(grupa):
    """Rozjemca grup o równej pilności: rodzaj, typ koloru, kolor, połysk alfabetycznie; brak wartości na końcu."""
    return tuple((wartosc is None, wartosc or '') for wartosc in grupa)


def porzadek_listy(station_code, items):
    """
    Kolejność pozycji listy tabletu. Stanowisko ze stołem → `items` bez zmian (TA SAMA lista, kolejność z SQL).

    Lakiernia (spec 3.2 „Lista Lakierni”):
    1. pozycje w statusie Lakierni dzielą się na grupy wykończenia (`klucz_grupy_wykonczenia`);
    2. grupy idą w kolejności NAJPILNIEJSZEJ pozycji w grupie (`_klucz_pozycji`: grupa z doróbką przed każdą bez
       doróbki; kilka takich — po najstarszej doróbce), przy remisie po nazwie grupy;
    3. w grupie pozycje po pilności; cała grupa w jednym ciągu, bez limitu liczby pozycji — także gdy w środku stoją
       pozycje mniej pilne niż pierwsza pozycja następnej grupy (świadomie: jedno rozrobione wiadro);
    4. pozostałe pozycje zamówień z listy (inne statusy — appka pokazuje je jako kontekst) na końcu, po
       dzisiejszym kluczu.
    Wynik jest deterministyczny dla tych samych danych (dwa tablety, odświeżanie co 30 s).
    """
    if station_code not in ustawienia.STANOWISKA_BEZ_STOLU:
        return items
    status = STATION_PENDING_STATUS[station_code]
    grupy, reszta = {}, []
    for item in items:
        if item.current_status == status:
            grupy.setdefault(klucz_grupy_wykonczenia(item), []).append(item)
        else:
            reszta.append(item)
    for pozycje in grupy.values():
        pozycje.sort(key=_klucz_pozycji)
    wynik = []
    for grupa in sorted(grupy, key=lambda g: (_klucz_pozycji(grupy[g][0]), _klucz_nazwy_grupy(g))):
        wynik.extend(grupy[grupa])
    wynik.extend(sorted(reszta, key=_klucz_reszty))
    return wynik
