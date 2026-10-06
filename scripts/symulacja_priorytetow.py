# -*- coding: utf-8 -*-
"""Symulacja nowego systemu priorytetów na danych z bazy — tylko odczyt, bez Flaska.

PO CO
=====
Spec `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` zmienia kolejkę
każdego stanowiska (drabina: trasy, gwiazdki, tagi terminowe; w szczeblu grupowanie po
materiale; stół stanowiska; Formatowanie i Pakowanie zamówieniowe). Zanim to wdrożymy,
chcemy zobaczyć na PRAWDZIWYCH danych:

  1. jak wyglądałaby dzisiejsza kolejka każdego stanowiska po nowemu i jak bardzo różni się
     od obecnej (ranga `priority_rank`),
  2. ile zamówień dostałoby tagi „Po terminie”, „Blisko terminu”, „Rozpoczęte”,
  3. co leżałoby na stole (K kafli) i co Formatowanie/Pakowanie widziałoby jako niekompletne,
  4. jak dziś wygląda hala w historii: czy pracownicy omijają pilniejsze pozycje („cherry
     picking”), jak bardzo pozycje jednego zamówienia rozjeżdżają się w czasie przed
     Formatowaniem i Pakowaniem (to jest obawa Konrada z 4.10),
  5. ile zdarzeń dziennie generują stanowiska (do zwymiarowania sygnałów realtime).

BEZPIECZEŃSTWO
==============
  * Skrypt NIE importuje aplikacji (żadnego `create_app()`): import uruchomiłby migracje
    gałęzi na bazie, do której się podłączy, a modele ORM gałęzi mają kolumny, których
    produkcja jeszcze nie ma. Używa gołego SQLAlchemy Core + PyMySQL z venv.
  * Wyłącznie SELECT. Na MySQL dodatkowo `SET SESSION TRANSACTION READ ONLY`.
  * Kolumny i tabele wykrywa (information_schema przez inspector) i omija brakujące —
    działa na produkcji sprzed logistyki (bez tras, bez `override_delivery_method`) i na kopii
    z gałęzi.
  * Raport nie zawiera nazw klientów ani adresów — tylko numery zamówień i pozycji.
    Można go wkleić do sesji Claude bez czyszczenia.

URUCHOMIENIE (serwer produkcyjny, katalog aplikacji)
====================================================
    FLASK_SKIP_DOTENV=1 venv/bin/python scripts/symulacja_priorytetow.py \
        --out /tmp/symulacja-priorytetow.md --json /tmp/symulacja-priorytetow.json

    # albo z jawnym adresem bazy (kopia produkcji):
    venv/bin/python scripts/symulacja_priorytetow.py --db-url mysql+pymysql://u:h@127.0.0.1/baza --out raport.md

Lokalnie (Docker): docker compose exec app python scripts/symulacja_priorytetow.py --out /tmp/s.md

Opcje:
    --dni 60          okno historii (dni wstecz) dla analizy omijania i rozrzutu
    --k 2             miejsca na stole stanowiska
    --blisko 3        próg „Blisko terminu” w dniach roboczych (decyzja Konrada 5.10: 3)
    --top 25          ile pozycji kolejki wypisać per stanowisko
    --gwiazdki plik   CSV `numer,gwiazdki` — symulacja gwiazdek biura (domyślnie wszystkie 0)
    --drabina lista   kolejność szczebli, np. "trasy,g5,po_terminie,g4,rozpoczete,blisko_terminu,g3,g2,g1,g0"
    --dzis YYYY-MM-DD data „dziś” (domyślnie dzisiaj; przydatne na kopii bazy sprzed dni)
"""
import argparse
import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, inspect, text

# --- stałe (lustro station_catalog / sposoby; skrypt celowo nie importuje aplikacji) ---------------------------
STATION_ORDER = ('cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting', 'packaging')
STATION_LABELS = {
    'cutting': 'Wycinanie - mikro', 'assembly': 'Składanie - lite', 'gluing': 'Sklejanie',
    'formatting': 'Formatowanie', 'edges': 'Krawędzie', 'painting': 'Lakiernia', 'packaging': 'Pakowanie',
}
STATION_PENDING = {
    'cutting': ('czeka_na_wyciecie',), 'assembly': ('czeka_na_skladanie',), 'gluing': ('czeka_na_sklejanie',),
    'formatting': ('czeka_na_formatowanie',), 'edges': ('czeka_na_krawedzie', 'czeka_na_wykanczanie'),
    'painting': ('czeka_na_lakiernie',), 'packaging': ('czeka_na_pakowanie',),
}
# Etap pozycji wg statusu: do porównań „wcześniej / dalej”. Formatowanie = 2, Pakowanie = 5, po spakowaniu = 6.
STAGE_OF_STATUS = {
    'czeka_na_wyciecie': 0, 'czeka_na_skladanie': 0, 'czeka_na_sklejanie': 1, 'czeka_na_formatowanie': 2,
    'czeka_na_krawedzie': 3, 'czeka_na_wykanczanie': 3, 'czeka_na_lakiernie': 4, 'czeka_na_logistyke': 4.5,
    'czeka_na_pakowanie': 5, 'spakowane': 6, 'zweryfikowane': 6, 'zaladowane': 6, 'dostarczone': 6,
}
STAGE_OF_STATION = {'cutting': 0, 'assembly': 0, 'gluing': 1, 'formatting': 2, 'edges': 3, 'painting': 4, 'packaging': 5}
ORDER_UNIT_STATIONS = ('formatting', 'packaging')   # kafel = zamówienie
ACTIVE_STATUSES = tuple(s for s, st in STAGE_OF_STATUS.items() if st < 6)
# Kolejność po decyzjach Konrada 5.10: „Blisko terminu” nad „Rozpoczęte”.
DRABINA_DOMYSLNA = ['trasy', 'g5', 'po_terminie', 'g4', 'blisko_terminu', 'rozpoczete', 'g3', 'g2', 'g1', 'g0']
TAGI = ('po_terminie', 'blisko_terminu', 'rozpoczete')


# --- narzędzia ---------------------------------------------------------------------------------------------------
def _data(v):
    """DATE z bazy → date (SQLite oddaje tekst)."""
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()


def _czas(v):
    """DATETIME z bazy → datetime (SQLite oddaje tekst)."""
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v)
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def _liczba(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def dodaj_dni_robocze(d, n):
    out = d
    while n > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            n -= 1
    return out


def _mediana(xs):
    return round(statistics.median(xs), 1) if xs else None


def _p90(xs):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(0.9 * (len(s) - 1)))], 1)


def _godziny(td):
    return td.total_seconds() / 3600.0


# --- odczyt bazy --------------------------------------------------------------------------------------------------
def polacz(db_url):
    engine = create_engine(db_url, future=False)
    return engine


def _kolumny(engine, tabela):
    insp = inspect(engine)
    if not insp.has_table(tabela):
        return None
    return {c['name'] for c in insp.get_columns(tabela)}


def _select(conn, tabela, chce, gdzie='', params=None):
    """SELECT tylko istniejących kolumn; brakujące wracają jako None."""
    kol = _kolumny(conn.engine, tabela)
    if kol is None:
        return [], None
    wybrane = [c for c in chce if c in kol]
    sql = 'SELECT ' + ', '.join(wybrane) + ' FROM ' + tabela + (' ' + gdzie if gdzie else '')
    wiersze = conn.execute(text(sql), params or {}).fetchall()
    out = []
    for w in wiersze:
        m = dict(zip(wybrane, w))
        for c in chce:
            m.setdefault(c, None)
        out.append(m)
    return out, kol


def wczytaj(engine, dzis, dni):
    """Czyta wszystko, czego potrzebuje symulacja i historia. Tylko SELECT."""
    od = datetime(dzis.year, dzis.month, dzis.day) - timedelta(days=dni)
    dane = {'braki': []}
    with engine.connect() as conn:
        if conn.engine.dialect.name == 'mysql':
            try:
                conn.execute(text('SET SESSION TRANSACTION READ ONLY'))
            except Exception as e:  # noqa: BLE001 — brak uprawnień nie przerywa odczytu
                dane['braki'].append('SET SESSION TRANSACTION READ ONLY: %s' % str(e)[:80])

        zam, kol_z = _select(conn, 'prod_orders', [
            'id', 'internal_order_number', 'payment_date', 'created_at', 'delivery_method',
            'override_delivery_method', 'baselinker_status_id'])
        dane['zamowienia'] = {z['id']: z for z in zam}
        dane['logistyka_kolumny'] = 'override_delivery_method' in (kol_z or set())

        kol_p = _kolumny(engine, 'prod_products') or set()
        edges_col = 'edges_completed_at' if 'edges_completed_at' in kol_p else 'finishing_completed_at'
        dane['edges_col'] = edges_col
        poz, _ = _select(conn, 'prod_products', [
            'id', 'order_id', 'short_product_id', 'product_sequence_in_order', 'current_status', 'deadline_date',
            'priority_rank', 'is_priority', 'quantity', 'parsed_length_cm', 'parsed_width_cm', 'parsed_thickness_cm',
            'parsed_finish_type', 'configuration_id', 'created_at', 'original_product_id', 'cut_to_size',
            'parsed_edge_processing', 'cutting_completed_at', 'assembly_completed_at', 'gluing_completed_at',
            'formatting_completed_at', edges_col, 'painting_completed_at', 'packaging_completed_at',
            'quantity_done_cutting', 'quantity_done_assembly', 'quantity_done_gluing', 'quantity_done_formatting',
            'quantity_done_edges', 'quantity_done_finishing', 'quantity_done_painting', 'quantity_done_packaging'])
        for p in poz:
            p['edges_completed_at'] = p.get(edges_col)
            if p.get('quantity_done_edges') is None:
                p['quantity_done_edges'] = p.get('quantity_done_finishing')
        dane['pozycje'] = poz
        for brak in ('original_product_id', 'cut_to_size'):
            if brak not in kol_p:
                dane['braki'].append('prod_products.%s (brak kolumny — doróbki/docięcie nierozpoznane)' % brak)

        konf, _ = _select(conn, 'prod_configurations', ['id', 'species', 'technology', 'wood_class'])
        dane['konfiguracje'] = {k['id']: k for k in konf}

        trasy, kol_t = _select(conn, 'prod_routes', ['id', 'name', 'date_from', 'status'])
        przyst, _ = _select(conn, 'prod_route_stops', ['route_id', 'order_id'])
        dane['trasy'] = {t['id']: t for t in trasy} if kol_t else {}
        dane['przystanki'] = {s['order_id']: s['route_id'] for s in przyst} if kol_t else {}
        dane['logistyka_tabele'] = kol_t is not None

        zd, kol_e = _select(conn, 'prod_station_events',
                            ['production_item_id', 'station_code', 'delta', 'created_at', 'source'],
                            'WHERE created_at >= :od', {'od': od})
        dane['zdarzenia'] = zd if kol_e else []
    dane['dzis'] = dzis
    dane['dni'] = dni
    return dane


# --- model zamówienia / pozycji ----------------------------------------------------------------------------------
def _przygotuj(dane, gwiazdki, blisko_dni):
    """Dokleja do pozycji i zamówień pola pochodne: etap, termin, tagi, materiał."""
    dzis = dane['dzis']
    prog_blisko = dodaj_dni_robocze(dzis, blisko_dni)
    po_zam = defaultdict(list)
    for p in dane['pozycje']:
        p['etap'] = STAGE_OF_STATUS.get(p['current_status'])
        p['aktywna'] = p['current_status'] in ACTIVE_STATUSES
        p['termin'] = _data(p['deadline_date'])
        p['dorobka'] = p.get('original_product_id') is not None
        k = dane['konfiguracje'].get(p.get('configuration_id')) or {}
        p['gatunek'] = (k.get('species') or '?')
        p['klasa'] = (k.get('wood_class') or '?')
        p['technologia'] = (k.get('technology') or '?')
        p['dl'] = _liczba(p.get('parsed_length_cm')) or 0.0
        p['sz'] = _liczba(p.get('parsed_width_cm')) or 0.0
        p['gr'] = _liczba(p.get('parsed_thickness_cm')) or 0.0
        po_zam[p['order_id']].append(p)
    dane['pozycje_zamowienia'] = po_zam

    aktywne = {}
    for oid, z in dane['zamowienia'].items():
        akt = [p for p in po_zam.get(oid, []) if p['aktywna']]
        if not akt:
            continue
        terminy = [p['termin'] for p in akt if p['termin']]
        z['termin'] = min(terminy) if terminy else None
        etapy = [p['etap'] for p in po_zam.get(oid, []) if p['etap'] is not None and p['current_status'] != 'anulowane']
        z['rozpoczete'] = any(e >= 2 for e in etapy) and any(e < 2 for e in etapy) \
            or any(e >= 5 for e in etapy) and any(e < 5 for e in etapy)
        z['po_terminie'] = bool(z['termin'] and z['termin'] < dzis)
        z['blisko_terminu'] = bool(z['termin'] and dzis <= z['termin'] <= prog_blisko)
        z['gwiazdki'] = int(gwiazdki.get(str(z['internal_order_number']), 0) or 0)
        rid = dane['przystanki'].get(oid)
        tr = dane['trasy'].get(rid) if rid else None
        z['trasa'] = tr if tr and tr.get('status') in ('robocza', 'zatwierdzona') else None
        z['numer'] = str(z['internal_order_number'] or oid)
        aktywne[oid] = z
    dane['aktywne'] = aktywne
    return dane


def _drabina(dane, lista):
    """Lista szczebli → słownik klucz→pozycja. 'trasy' rozwija się na trasy robocze/zatwierdzone po date_from."""
    trasy = sorted((t for t in dane['trasy'].values() if t.get('status') in ('robocza', 'zatwierdzona')),
                   key=lambda t: (str(t.get('date_from') or ''), t['id']))
    rozw = []
    for s in lista:
        if s == 'trasy':
            rozw.extend('trasa:%s' % t['id'] for t in trasy)
        else:
            rozw.append(s)
    return {s: i + 1 for i, s in enumerate(rozw)}, rozw


def _szczebel(z, poz):
    if z['trasa']:
        return poz.get('trasa:%s' % z['trasa']['id'], poz.get('g0', 99)), 'trasa %s' % z['trasa']['name']
    kand = [(poz.get('g%d' % z['gwiazdki'], 99), 'g%d' % z['gwiazdki'])]
    for t in TAGI:
        if z.get(t):
            kand.append((poz.get(t, 99), t))
    return min(kand)


def _klucz_zamowienia(z, poz):
    pozycja, _ = _szczebel(z, poz)
    return (pozycja, -z['gwiazdki'], z['termin'] or date.max, z['numer'])


# --- symulacja kolejek stanowisk --------------------------------------------------------------------------------
def kolejka_pozycji(dane, station, poz_szczebli):
    """Nowa kolejność pozycji na stanowisku pozycyjnym (spec 3.2) + obecna (priority_rank)."""
    statusy = STATION_PENDING[station]
    pozycje = [p for p in dane['pozycje'] if p['current_status'] in statusy and p['order_id'] in dane['aktywne']]
    obecna = sorted(pozycje, key=lambda p: (p['priority_rank'] if p['priority_rank'] is not None else 999999,
                                            dane['aktywne'][p['order_id']]['numer'], p['id']))
    poz_obecna = {p['id']: i + 1 for i, p in enumerate(obecna)}

    # Grupa materiału w obrębie szczebla = (gatunek, klasa, grubość); grupy w kolejności najbliższego terminu w grupie,
    # w grupie termin przed długością (wariant A2 z symulacji na produkcji, decyzja Konrada 5.10: ten sam spadek
    # przezbrojeń co grupowanie po samym materiale, a rozrzut pozycji zamówienia p90 28→15 miejsc na Składaniu).
    min_termin_grupy = {}
    for p in pozycje:
        z = dane['aktywne'][p['order_id']]
        szcz, _ = _szczebel(z, poz_szczebli)
        kl = (szcz, p['gatunek'], p['klasa'], p['gr'])
        t = z['termin'] or date.max
        if kl not in min_termin_grupy or t < min_termin_grupy[kl]:
            min_termin_grupy[kl] = t

    def klucz(p):
        z = dane['aktywne'][p['order_id']]
        szcz, _ = _szczebel(z, poz_szczebli)
        return (0 if p['dorobka'] else 1, _czas(p.get('created_at')) or datetime.max if p['dorobka'] else datetime.min,
                szcz, -z['gwiazdki'], 0 if z['rozpoczete'] else 1,
                min_termin_grupy[(szcz, p['gatunek'], p['klasa'], p['gr'])], p['gatunek'], p['klasa'], -p['gr'],
                z['termin'] or date.max, -p['dl'], -p['sz'], z['numer'], p['product_sequence_in_order'] or 0)

    nowa = sorted(pozycje, key=klucz)
    wiersze = []
    for i, p in enumerate(nowa):
        z = dane['aktywne'][p['order_id']]
        szcz, nazwa = _szczebel(z, poz_szczebli)
        wiersze.append({
            'nowa': i + 1, 'obecna': poz_obecna[p['id']], 'pozycja': p['short_product_id'], 'zamowienie': z['numer'],
            'wymiary': '%gx%gx%g' % (p['dl'], p['sz'], p['gr']), 'material': '%s %s' % (p['gatunek'], p['klasa']),
            'technologia': p['technologia'], 'sztuk': p.get('quantity'),
            'termin': z['termin'].isoformat() if z['termin'] else None, 'szczebel': szcz, 'szczebel_nazwa': nazwa,
            'tagi': [t for t in TAGI if z.get(t)], 'gwiazdki': z['gwiazdki'], 'dorobka': p['dorobka'],
            'ranga_dzis': p['priority_rank'],
        })
    return wiersze


def kolejka_zamowien(dane, station, poz_szczebli, k):
    """Stanowisko zamówieniowe: kompletne na stół (K), niekompletne osobno (spec 5.6)."""
    etap = STAGE_OF_STATION[station]
    statusy = STATION_PENDING[station]
    zam_ids = {p['order_id'] for p in dane['pozycje'] if p['current_status'] in statusy and p['order_id'] in dane['aktywne']}
    wiersze = []
    for oid in zam_ids:
        z = dane['aktywne'][oid]
        akt = [p for p in dane['pozycje_zamowienia'][oid] if p['aktywna']]
        tutaj = [p for p in akt if p['current_status'] in statusy]
        wczesniej = [p for p in akt if p['etap'] is not None and p['etap'] < etap]
        rangi = [p['priority_rank'] for p in tutaj if p['priority_rank'] is not None]
        szcz, nazwa = _szczebel(z, poz_szczebli)
        wiersze.append({
            'zamowienie': z['numer'], 'klucz': _klucz_zamowienia(z, poz_szczebli), 'kompletne': not wczesniej,
            'na_stanowisku': len(tutaj), 'pozycji_aktywnych': len(akt),
            'brakuje': [{'pozycja': p['short_product_id'], 'status': p['current_status']} for p in wczesniej],
            'termin': z['termin'].isoformat() if z['termin'] else None, 'szczebel': szcz, 'szczebel_nazwa': nazwa,
            'tagi': [t for t in TAGI if z.get(t)], 'gwiazdki': z['gwiazdki'], 'ranga_dzis_min': min(rangi) if rangi else None,
        })
    wiersze.sort(key=lambda w: w['klucz'])
    for i, w in enumerate(wiersze):
        w['nowa'] = i + 1
        del w['klucz']
    obecna = sorted(wiersze, key=lambda w: (w['ranga_dzis_min'] if w['ranga_dzis_min'] is not None else 999999, w['zamowienie']))
    for i, w in enumerate(obecna):
        w['obecna'] = i + 1
    kompletne = [w for w in wiersze if w['kompletne']]
    niekompletne = [w for w in wiersze if not w['kompletne']]
    return {'wszystkie': wiersze, 'stol': kompletne[:k], 'niekompletne': niekompletne[:k],
            'kompletnych': len(kompletne), 'niekompletnych': len(niekompletne)}


def _rozrzut_pozycji(wiersze):
    """Mediana rozrzutu (ostatnia − pierwsza pozycja) pozycji jednego zamówienia w nowej kolejce."""
    poz = defaultdict(list)
    for w in wiersze:
        poz[w['zamowienie']].append(w['nowa'])
    roz = [max(v) - min(v) for v in poz.values() if len(v) > 1]
    return {'zamowien_wielopozycyjnych': len(roz), 'mediana': _mediana(roz), 'p90': _p90(roz)}


def _grupy_materialu(wiersze):
    licz = defaultdict(int)
    for w in wiersze:
        licz[(w['material'], w['wymiary'].split('x')[-1])] += 1
    top = sorted(licz.items(), key=lambda kv: -kv[1])[:8]
    return {'grup': len(licz), 'najwieksze': [{'material': m, 'grubosc': g, 'pozycji': n} for (m, g), n in top]}


def symuluj(dane, k=2, blisko_dni=2, gwiazdki=None, drabina=None, top=25):
    gwiazdki = gwiazdki or {}
    _przygotuj(dane, gwiazdki, blisko_dni)
    poz_szczebli, rozw = _drabina(dane, drabina or DRABINA_DOMYSLNA)
    akt = dane['aktywne']
    wyn = {
        'parametry': {'k': k, 'blisko_dni': blisko_dni, 'drabina': rozw, 'gwiazdki_z_pliku': len(gwiazdki),
                      'dzis': dane['dzis'].isoformat()},
        'srodowisko': {'logistyka_tabele': dane['logistyka_tabele'], 'logistyka_kolumny': dane['logistyka_kolumny'],
                       'braki': dane['braki'], 'tras_aktywnych': sum(1 for t in dane['trasy'].values()
                                                                     if t.get('status') in ('robocza', 'zatwierdzona'))},
        'zamowienia': {
            'aktywnych': len(akt),
            'pozycji_aktywnych': sum(1 for p in dane['pozycje'] if p['aktywna'] and p['order_id'] in akt),
            'po_statusie': dict(sorted(defaultdict_count(p['current_status'] for p in dane['pozycje']
                                                         if p['aktywna'] and p['order_id'] in akt).items())),
            'po_terminie': sum(1 for z in akt.values() if z['po_terminie']),
            'blisko_terminu': sum(1 for z in akt.values() if z['blisko_terminu']),
            'rozpoczete': sum(1 for z in akt.values() if z['rozpoczete']),
            'bez_terminu': sum(1 for z in akt.values() if not z['termin']),
            'na_trasie': sum(1 for z in akt.values() if z['trasa']),
            'z_dorobka': sum(1 for oid in akt if any(p['dorobka'] and p['aktywna'] for p in dane['pozycje_zamowienia'][oid])),
            'szczeble': dict(sorted(defaultdict_count(_szczebel(z, poz_szczebli)[1] for z in akt.values()).items())),
        },
        'stanowiska': {},
    }
    for st in STATION_ORDER:
        if st in ORDER_UNIT_STATIONS:
            kz = kolejka_zamowien(dane, st, poz_szczebli, k)
            wyn['stanowiska'][st] = {
                'jednostka': 'zamowienie', 'zamowien': len(kz['wszystkie']), 'kompletnych': kz['kompletnych'],
                'niekompletnych': kz['niekompletnych'], 'stol': kz['stol'], 'niekompletne': kz['niekompletne'],
                'kolejka': kz['wszystkie'][:top], 'kolejka_pelna': kz['wszystkie'][:200],
                'przesuniecie_top': _przesuniecie(kz['wszystkie'], top),
            }
        else:
            w = kolejka_pozycji(dane, st, poz_szczebli)
            wyn['stanowiska'][st] = {
                'jednostka': 'pozycja', 'pozycji': len(w), 'zamowien': len({x['zamowienie'] for x in w}),
                'stol': w[:k], 'kolejka': w[:top], 'kolejka_pelna': w[:200],
                'przesuniecie_top': _przesuniecie(w, top), 'rozrzut_zamowien': _rozrzut_pozycji(w),
                'grupy_materialu': _grupy_materialu(w),
            }
    return wyn


def defaultdict_count(it):
    d = defaultdict(int)
    for x in it:
        d[x] += 1
    return d


def _przesuniecie(wiersze, top):
    """Jak daleko od dzisiejszej czołówki są nowe pierwsze `top` kafli."""
    gora = wiersze[:top]
    if not gora:
        return {}
    roznice = [abs(w['nowa'] - w['obecna']) for w in gora]
    return {'mediana_przesuniecia': _mediana(roznice), 'max_przesuniecie': max(roznice),
            'w_dzisiejszej_czolowce': sum(1 for w in gora if w['obecna'] <= top), 'z': len(gora)}


# --- historia -----------------------------------------------------------------------------------------------------
def _wejscie_wyjscie(p, station):
    """(wejście, wyjście) pozycji na stanowisku z kolumn *_completed_at. None gdy nie da się ustalić."""
    c = {s: _czas(p.get('%s_completed_at' % s)) for s in STATION_ORDER}
    wyj = c[station]
    if station in ('cutting', 'assembly'):
        wej = _czas(p.get('created_at'))
    elif station == 'gluing':
        wej = max([x for x in (c['cutting'], c['assembly']) if x], default=None)
    elif station == 'formatting':
        wej = c['gluing']
    elif station == 'edges':
        wej = c['formatting']
    elif station == 'painting':
        wej = c['edges'] or c['formatting']
    else:  # packaging
        wej = max([x for x in (c['painting'], c['edges'], c['formatting'], c['gluing']) if x], default=None)
    return wej, wyj


def historia(dane):
    dzis = dane['dzis']
    od = datetime(dzis.year, dzis.month, dzis.day) - timedelta(days=dane['dni'])
    do = datetime(dzis.year, dzis.month, dzis.day) + timedelta(days=1)
    wyn = {'okno_dni': dane['dni'], 'od': od.date().isoformat(), 'omijanie': {}, 'rozrzut_zamowien': {}, 'zdarzenia': {}}

    # Omijanie pilniejszych: dla każdego zakończenia na stanowisku, ile pozycji o WCZEŚNIEJSZYM terminie
    # (innego zamówienia) czekało wtedy na tym stanowisku.
    for st in STATION_ORDER:
        przebiegi = []   # (wejście, wyjście|None, termin, order_id, id)
        for p in dane['pozycje']:
            if p['current_status'] == 'anulowane':
                continue
            # Wycinanie i Składanie są równoległe wg technologii — pozycja lita nigdy nie czeka na Wycinaniu.
            if st == 'cutting' and p.get('technologia') != 'mikrowczep':
                continue
            if st == 'assembly' and p.get('technologia') != 'lity':
                continue
            wej, wyj = _wejscie_wyjscie(p, st)
            if wej is None:
                continue
            if wyj is not None and wyj <= wej:   # auto_skip / system — nie było pracy na stanowisku
                continue
            if wyj is None and p.get('etap') != STAGE_OF_STATION[st]:
                continue   # bez zakończenia i nie czeka dziś na tym stanowisku (pominięte / cofnięte) — nie było w kolejce
            if wyj is not None and wyj < od:
                continue   # zakończone przed oknem — nie mogło czekać w żadnej chwili okna
            przebiegi.append((wej, wyj, _data(p.get('deadline_date')), p['order_id'], p['id']))
        zakonczenia = [x for x in przebiegi if x[1] is not None and od <= x[1] < do]
        if not zakonczenia:
            wyn['omijanie'][st] = {'zakonczen': 0}
            continue
        z_ominieciem = 0
        wyraznie = 0
        liczby = []
        czekajacych = []
        for wej, wyj, termin, oid, pid in zakonczenia:
            t = wyj
            pend = [x for x in przebiegi if x[0] <= t and (x[1] is None or x[1] > t) and x[3] != oid]
            czekajacych.append(len(pend))
            if termin is None:
                continue
            om = [x for x in pend if x[2] is not None and x[2] < termin]
            liczby.append(len(om))
            if om:
                z_ominieciem += 1
            if any((termin - x[2]).days >= 3 for x in om):
                wyraznie += 1
        n = len([x for x in zakonczenia if x[2] is not None])
        wyn['omijanie'][st] = {
            'zakonczen': len(zakonczenia), 'z_terminem': n,
            'udzial_z_ominieciem_pilniejszego': round(z_ominieciem / n, 2) if n else None,
            'udzial_z_ominieciem_o_3_dni_i_wiecej': round(wyraznie / n, 2) if n else None,
            'mediana_ominietych': _mediana(liczby), 'mediana_czekajacych_w_chwili_zakonczenia': _mediana(czekajacych),
        }

    # Rozrzut pozycji jednego zamówienia przed stanowiskiem zamówieniowym (obawa z 4.10).
    for st in ORDER_UNIT_STATIONS:
        per_zam = defaultdict(list)
        for p in dane['pozycje']:
            if p['current_status'] == 'anulowane':
                continue
            wej, _ = _wejscie_wyjscie(p, st)
            if wej is not None:
                per_zam[p['order_id']].append(wej)
        rozrzuty = []
        czekanie_na_ostatnia = []
        for oid, wejscia in per_zam.items():
            if len(wejscia) < 2 or not (od <= max(wejscia) < do):
                continue
            rozrzuty.append(_godziny(max(wejscia) - min(wejscia)))
        if rozrzuty:
            wyn['rozrzut_zamowien'][st] = {
                'zamowien': len(rozrzuty), 'mediana_h': _mediana(rozrzuty), 'p90_h': _p90(rozrzuty),
                'udzial_ponad_24h': round(sum(1 for r in rozrzuty if r > 24) / len(rozrzuty), 2),
                'udzial_ponad_72h': round(sum(1 for r in rozrzuty if r > 72) / len(rozrzuty), 2),
            }
        else:
            wyn['rozrzut_zamowien'][st] = {'zamowien': 0}

    # Zdarzenia stanowiskowe (liczniki sztuk): ile dziennie, ile z tabletów.
    per_st = defaultdict(lambda: {'zdarzen': 0, 'mobile': 0, 'dni': set()})
    for e in dane['zdarzenia']:
        s = per_st[e['station_code']]
        s['zdarzen'] += 1
        if e.get('source') == 'mobile':
            s['mobile'] += 1
        c = _czas(e.get('created_at'))
        if c:
            s['dni'].add(c.date())
    for st, s in per_st.items():
        dni = max(len(s['dni']), 1)
        wyn['zdarzenia'][st] = {'zdarzen': s['zdarzen'], 'z_tabletow': s['mobile'], 'dni_z_aktywnoscia': len(s['dni']),
                                'srednio_dziennie': round(s['zdarzen'] / dni, 1)}
    return wyn


# --- raport -------------------------------------------------------------------------------------------------------
def raport_md(wyn, hist, db_opis):
    L = []
    P = wyn['parametry']
    L.append('# Symulacja priorytetów produkcji — %s' % P['dzis'])
    L.append('')
    L.append('- Baza: %s' % db_opis)
    L.append('- Parametry: stół K=%d, „Blisko terminu” %d dni rob., gwiazdek z pliku: %d, historia %d dni' %
             (P['k'], P['blisko_dni'], P['gwiazdki_z_pliku'], hist['okno_dni']))
    L.append('- Drabina: %s' % ' > '.join(P['drabina']))
    S = wyn['srodowisko']
    L.append('- Tabele logistyki: %s; kolumny logistyki na zamówieniu: %s; tras roboczych/zatwierdzonych: %d' %
             ('są' if S['logistyka_tabele'] else 'brak', 'są' if S['logistyka_kolumny'] else 'brak', S['tras_aktywnych']))
    for b in S['braki']:
        L.append('- Uwaga: %s' % b)
    L.append('')
    Z = wyn['zamowienia']
    L.append('## 1. Co jest dziś w produkcji')
    L.append('')
    L.append('| Miara | Wartość |')
    L.append('|---|---|')
    for k, v in (('zamówień aktywnych', Z['aktywnych']), ('pozycji aktywnych', Z['pozycji_aktywnych']),
                 ('po terminie', Z['po_terminie']), ('blisko terminu', Z['blisko_terminu']),
                 ('rozpoczęte (Formatowanie/Pakowanie czeka)', Z['rozpoczete']), ('bez terminu', Z['bez_terminu']),
                 ('na trasie roboczej/zatwierdzonej', Z['na_trasie']), ('z doróbką', Z['z_dorobka'])):
        L.append('| %s | %s |' % (k, v))
    L.append('')
    L.append('Pozycje po statusie: ' + ', '.join('%s %d' % kv for kv in Z['po_statusie'].items()))
    L.append('')
    L.append('Zamówienia po szczeblu drabiny: ' + ', '.join('%s %d' % kv for kv in Z['szczeble'].items()))
    L.append('')
    L.append('## 2. Kolejki stanowisk po nowemu')
    L.append('')
    L.append('„Dziś #” = miejsce w dzisiejszej kolejce (ranga). Przesunięcie liczone dla nowej czołówki.')
    for st in STATION_ORDER:
        d = wyn['stanowiska'][st]
        L.append('')
        L.append('### %s (%s)' % (STATION_LABELS[st], 'kafel = zamówienie' if d['jednostka'] == 'zamowienie' else 'kafel = pozycja'))
        L.append('')
        if d['jednostka'] == 'pozycja':
            L.append('Pozycji: %d z %d zamówień. Rozrzut pozycji jednego zamówienia w nowej kolejce (mediana/p90 miejsc): %s / %s '
                     '(zamówień wielopozycyjnych: %d). Grup materiał+grubość: %d.' %
                     (d['pozycji'], d['zamowien'], d['rozrzut_zamowien']['mediana'], d['rozrzut_zamowien']['p90'],
                      d['rozrzut_zamowien']['zamowien_wielopozycyjnych'], d['grupy_materialu']['grup']))
            if d['grupy_materialu']['najwieksze']:
                L.append('Największe grupy: ' + ', '.join('%s %s cm ×%d' % (g['material'], g['grubosc'], g['pozycji'])
                                                           for g in d['grupy_materialu']['najwieksze']))
            pt = d['przesuniecie_top']
            if pt:
                L.append('Nowa czołówka %d: mediana przesunięcia %s miejsc, max %d; %d z nich jest też w dzisiejszej czołówce.' %
                         (pt['z'], pt['mediana_przesuniecia'], pt['max_przesuniecie'], pt['w_dzisiejszej_czolowce']))
            L.append('')
            L.append('Na stole (K=%d): %s' % (P['k'], ', '.join('%s (%s)' % (w['pozycja'], w['wymiary']) for w in d['stol']) or '—'))
            L.append('')
            L.append('| # | Dziś # | Pozycja | Zam. | Wymiary | Materiał | Techn. | Termin | Szczebel | Tagi |')
            L.append('|---|---|---|---|---|---|---|---|---|---|')
            for w in d['kolejka']:
                L.append('| %d | %d | %s%s | %s | %s | %s | %s | %s | %s | %s |' % (
                    w['nowa'], w['obecna'], w['pozycja'], ' (doróbka)' if w['dorobka'] else '', w['zamowienie'], w['wymiary'],
                    w['material'], w['technologia'], w['termin'] or '—', w['szczebel_nazwa'], ', '.join(w['tagi']) or '—'))
        else:
            L.append('Zamówień czekających: %d, w tym kompletnych %d, niekompletnych %d (czekają na pozycje z wcześniejszych stanowisk).' %
                     (d['zamowien'], d['kompletnych'], d['niekompletnych']))
            pt = d['przesuniecie_top']
            if pt:
                L.append('Nowa czołówka %d: mediana przesunięcia %s miejsc, max %d; %d z nich jest też w dzisiejszej czołówce.' %
                         (pt['z'], pt['mediana_przesuniecia'], pt['max_przesuniecie'], pt['w_dzisiejszej_czolowce']))
            L.append('')
            L.append('Na stole (K=%d, tylko kompletne): %s' % (P['k'], ', '.join(w['zamowienie'] for w in d['stol']) or '—'))
            if d['niekompletne']:
                L.append('')
                L.append('Niekompletne (do K): ' + '; '.join('%s %d/%d, brakuje: %s' % (
                    w['zamowienie'], w['na_stanowisku'], w['pozycji_aktywnych'],
                    ', '.join('%s@%s' % (b['pozycja'], b['status']) for b in w['brakuje'][:4]) +
                    (' …' if len(w['brakuje']) > 4 else '')) for w in d['niekompletne']))
            L.append('')
            L.append('| # | Dziś # | Zam. | Kompletne | Na stan./aktywnych | Termin | Szczebel | Tagi |')
            L.append('|---|---|---|---|---|---|---|---|')
            for w in d['kolejka']:
                L.append('| %d | %d | %s | %s | %d/%d | %s | %s | %s |' % (
                    w['nowa'], w['obecna'], w['zamowienie'], 'tak' if w['kompletne'] else 'NIE', w['na_stanowisku'],
                    w['pozycji_aktywnych'], w['termin'] or '—', w['szczebel_nazwa'], ', '.join(w['tagi']) or '—'))
    L.append('')
    L.append('## 3. Historia (ostatnie %d dni, od %s)' % (hist['okno_dni'], hist['od']))
    L.append('')
    L.append('### 3.1 Omijanie pilniejszych pozycji')
    L.append('')
    L.append('Dla każdego zakończenia: ile pozycji innego zamówienia o wcześniejszym terminie czekało wtedy na tym stanowisku. '
             'Wejście na stanowisko = zakończenie poprzedniego (z kolumn `*_completed_at`); pozycje zakończone „w tej samej '
             'chwili” co wejście (auto-pominięcie) wyłączone.')
    L.append('')
    L.append('| Stanowisko | Zakończeń | Z pominięciem pilniejszego | …o ≥3 dni | Mediana pominiętych | Mediana czekających |')
    L.append('|---|---|---|---|---|---|')
    for st in STATION_ORDER:
        o = hist['omijanie'].get(st, {})
        if not o.get('zakonczen'):
            L.append('| %s | 0 | — | — | — | — |' % STATION_LABELS[st])
            continue
        L.append('| %s | %d | %s | %s | %s | %s |' % (
            STATION_LABELS[st], o['zakonczen'],
            _proc(o['udzial_z_ominieciem_pilniejszego']), _proc(o['udzial_z_ominieciem_o_3_dni_i_wiecej']),
            o['mediana_ominietych'], o['mediana_czekajacych_w_chwili_zakonczenia']))
    L.append('')
    L.append('### 3.2 Rozrzut pozycji jednego zamówienia przed stanowiskiem zamówieniowym')
    L.append('')
    L.append('Czas między wejściem pierwszej i ostatniej pozycji zamówienia na stanowisko (zamówienia ≥2 pozycji, których ostatnia '
             'pozycja weszła w oknie). To jest dzisiejsza miara „ile Formatowanie/Pakowanie czeka na komplet”.')
    L.append('')
    L.append('| Stanowisko | Zamówień | Mediana h | p90 h | >24 h | >72 h |')
    L.append('|---|---|---|---|---|---|')
    for st in ORDER_UNIT_STATIONS:
        r = hist['rozrzut_zamowien'].get(st, {})
        if not r.get('zamowien'):
            L.append('| %s | 0 | — | — | — | — |' % STATION_LABELS[st])
            continue
        L.append('| %s | %d | %s | %s | %s | %s |' % (STATION_LABELS[st], r['zamowien'], r['mediana_h'], r['p90_h'],
                                                     _proc(r['udzial_ponad_24h']), _proc(r['udzial_ponad_72h'])))
    L.append('')
    L.append('### 3.3 Zdarzenia stanowiskowe (zmiany liczników)')
    L.append('')
    if hist['zdarzenia']:
        L.append('| Stanowisko | Zdarzeń | Z tabletów | Dni z aktywnością | Średnio dziennie |')
        L.append('|---|---|---|---|---|')
        for st, s in sorted(hist['zdarzenia'].items()):
            L.append('| %s | %d | %d | %d | %s |' % (STATION_LABELS.get(st, st), s['zdarzen'], s['z_tabletow'],
                                                   s['dni_z_aktywnoscia'], s['srednio_dziennie']))
    else:
        L.append('Brak zdarzeń w oknie (tabela pusta albo nie istnieje).')
    L.append('')
    L.append('## 4. Jak czytać')
    L.append('')
    L.append('- Bez gwiazdek i tras nowa kolejka różni się od dzisiejszej głównie tagami terminowymi i grupowaniem po materiale; '
             'plik `--gwiazdki` pozwala zasymulować decyzje biura.')
    L.append('- Duży rozrzut pozycji zamówienia w nowej kolejce Sklejania przy małym rozrzucie historycznym oznacza, że grupowanie '
             'po materiale wydłuży czekanie Formatowania — wtedy tag „Rozpoczęte” musi stać wysoko albo trzeba ograniczyć '
             'grupowanie do bloków.')
    L.append('- Wysoki udział „z pominięciem pilniejszego” to miara dzisiejszego wybierania łatwych pozycji; po wdrożeniu stołu '
             'ta sama miara powinna spaść do odłożeń z powodem.')
    return '\n'.join(L) + '\n'


def _proc(v):
    return '—' if v is None else '%d%%' % round(v * 100)


# --- wejście ------------------------------------------------------------------------------------------------------
def _db_url(args):
    if args.db_url:
        return args.db_url
    sciezka = args.core or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'core.json')
    with open(sciezka, encoding='utf-8') as f:
        return json.load(f)['DATABASE_URI']


def _opis_bazy(url):
    """Adres bazy bez hasła i użytkownika do nagłówka raportu."""
    try:
        schemat, reszta = url.split('://', 1)
        if '@' in reszta:
            reszta = reszta.split('@', 1)[1]
        return schemat + '://' + reszta
    except Exception:  # noqa: BLE001
        return 'nieznana'


def _wczytaj_gwiazdki(sciezka):
    if not sciezka:
        return {}
    out = {}
    with open(sciezka, encoding='utf-8', newline='') as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip() or row[0].strip().lower() in ('numer', 'nr', 'zamowienie'):
                continue
            try:
                out[row[0].strip()] = max(0, min(5, int(row[1])))
            except ValueError:
                continue
    return out


def zbuduj_parser():
    p = argparse.ArgumentParser(description='Symulacja nowych priorytetów produkcji na danych z bazy (tylko odczyt).')
    p.add_argument('--db-url', help='adres bazy (domyślnie DATABASE_URI z config/core.json)')
    p.add_argument('--core', help='ścieżka do core.json (domyślnie config/core.json obok skryptu)')
    p.add_argument('--out', default='symulacja-priorytetow.md', help='plik raportu Markdown')
    p.add_argument('--json', help='plik z pełnym wynikiem (kolejki do 200 kafli na stanowisko)')
    p.add_argument('--dni', type=int, default=60)
    p.add_argument('--k', type=int, default=2)
    p.add_argument('--blisko', type=int, default=3)
    p.add_argument('--top', type=int, default=25)
    p.add_argument('--gwiazdki', help='CSV numer,gwiazdki')
    p.add_argument('--drabina', help='lista szczebli po przecinku (domyślnie: %s)' % ','.join(DRABINA_DOMYSLNA))
    p.add_argument('--dzis', help='YYYY-MM-DD')
    return p


def uruchom(engine, args, db_opis):
    dzis = _data(args.dzis) if args.dzis else date.today()
    dane = wczytaj(engine, dzis, args.dni)
    drabina = [s.strip() for s in args.drabina.split(',')] if args.drabina else None
    wyn = symuluj(dane, k=args.k, blisko_dni=args.blisko, gwiazdki=_wczytaj_gwiazdki(args.gwiazdki),
                  drabina=drabina, top=args.top)
    hist = historia(dane)
    md = raport_md(wyn, hist, db_opis)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(md)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump({'symulacja': wyn, 'historia': hist}, f, ensure_ascii=False, indent=1, default=str)
    return wyn, hist, md


def main():
    args = zbuduj_parser().parse_args()
    url = _db_url(args)
    engine = polacz(url)
    wyn, hist, md = uruchom(engine, args, _opis_bazy(url))
    print(md.split('## 2.')[0])
    print('Raport zapisany: %s%s' % (args.out, (' i %s' % args.json) if args.json else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
