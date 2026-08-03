"""Testy scalania historii produktu (product_history_service)."""
import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services import product_history_service as phs


def _evt(station, delta, after, minute, device='dev-1', user=None, source='mobile'):
    return SimpleNamespace(
        station_code=station, delta=delta, quantity_done_after=after,
        created_at=datetime(2026, 7, 29, 8, minute, 0),
        device_id=device, user_id=user, source=source,
    )


def test_150_odbic_zwija_sie_do_jednej_grupy():
    events = [_evt('assembly', 1, i + 1, i % 60) for i in range(150)]
    out = phs.aggregate_station_events(events)
    assert len(out) == 1
    g = out[0]
    assert g['kind'] == 'work'
    assert g['station_code'] == 'assembly'
    assert g['total'] == 150
    assert g['event_count'] == 150
    assert len(g['entries']) == 150


def test_grupa_ma_zakres_czasu_i_urzadzenia():
    events = [_evt('assembly', 1, 1, 10, device='dev-1'),
              _evt('assembly', 1, 2, 40, device='dev-2')]
    g = phs.aggregate_station_events(events)[0]
    assert g['first_at'] == datetime(2026, 7, 29, 8, 10, 0)
    assert g['last_at'] == datetime(2026, 7, 29, 8, 40, 0)
    assert g['at'] == g['last_at']
    assert set(g['device_ids']) == {'dev-1', 'dev-2'}


def test_cofniecie_sztuk_jest_osobnym_wpisem_poza_grupa():
    events = [_evt('formatting', 2, 2, 10), _evt('formatting', -1, 1, 20)]
    out = phs.aggregate_station_events(events)
    kinds = sorted(e['kind'] for e in out)
    assert kinds == ['reject', 'work']
    work = next(e for e in out if e['kind'] == 'work')
    reject = next(e for e in out if e['kind'] == 'reject')
    assert work['total'] == 2          # cofnięcie NIE zmniejsza sumy grupy
    assert reject['delta'] == -1


def test_rozne_stanowiska_daja_rozne_grupy():
    events = [_evt('assembly', 1, 1, 10), _evt('gluing', 1, 1, 20)]
    out = phs.aggregate_station_events(events)
    assert {g['station_code'] for g in out} == {'assembly', 'gluing'}


def test_pusta_lista_daje_pusty_wynik():
    assert phs.aggregate_station_events([]) == []


def test_etykieta_uzytkownika_to_imie_i_nazwisko():
    assert phs.actor_label('user', user_name='Anna Kowalska') == 'Anna Kowalska (panel)'


def test_etykieta_urzadzenia_to_nazwa_tabletu():
    assert phs.actor_label('device', device_name='tablet ST-2') == 'tablet ST-2'


def test_etykieta_urzadzenia_bez_nazwy_wpada_na_stanowisko():
    assert phs.actor_label('device', station_code='assembly') == 'Składanie - lite'


def test_etykieta_systemu_pokazuje_powod_dla_auto_skip():
    assert phs.actor_label('system', source='auto_skip') == 'System (pominięto automatycznie)'


def test_etykieta_systemu_bez_zrodla():
    assert phs.actor_label('system') == 'System'


def test_etykieta_systemu_dla_panelu_stanowiskowego_bez_logowania():
    # Poprawka 2: source='web' przy actor_type='system' to panel stanowiskowy
    # chroniony walidacją IP (nie logowaniem) — inna etykieta niż automat.
    assert phs.actor_label('system', source='web') == 'Panel stanowiskowy (bez logowania)'


def test_merge_sortuje_malejaco_po_czasie():
    status = [{'kind': 'status', 'at': datetime(2026, 7, 29, 9, 0, 0)}]
    work = [{'kind': 'work', 'at': datetime(2026, 7, 29, 11, 0, 0)}]
    out = phs.merge_history(status, work)
    assert [e['at'].hour for e in out] == [11, 9]


def test_zmiana_statusu_z_panelu_jest_recznie():
    entry = {'kind': 'status', 'event_type': 'status_change',
             'actor_type': 'user', 'source': 'web'}
    assert phs.is_manual_status_change(entry) is True


def test_zmiana_statusu_z_tabletu_nie_jest_recznie():
    entry = {'kind': 'status', 'event_type': 'status_change',
             'actor_type': 'device', 'source': 'mobile'}
    assert phs.is_manual_status_change(entry) is False


def test_zmiana_priorytetu_z_panelu_nie_jest_recznie():
    # Poprawka 4b: plakietka "ręcznie" dotyczy WYŁĄCZNIE zmian statusu —
    # pojedyncza, ręczna zmiana priorytetu (ta która przetrwa filtr masowej
    # renumeracji) nie ma dostawać mylącej plakietki tak jakby to była
    # zmiana statusu.
    entry = {'kind': 'status', 'event_type': 'priority_change',
             'actor_type': 'user', 'source': 'web'}
    assert phs.is_manual_status_change(entry) is False


def test_praca_stanowiska_nigdy_nie_jest_recznie():
    entry = {'kind': 'work', 'actor_type': 'user', 'source': 'web'}
    assert phs.is_manual_status_change(entry) is False


def test_last_device_id_wskazuje_urzadzenie_z_pozniejszym_zdarzeniem():
    # dev-1 domyka stanowisko jako drugi (minuta 40) — flow ma wskazać JEGO,
    # nie dev-2 (minuta 10), mimo że dev-2 był pierwszy na liście device_ids
    events = [_evt('assembly', 1, 1, 10, device='dev-2'),
              _evt('assembly', 1, 2, 40, device='dev-1')]
    g = phs.aggregate_station_events(events)[0]
    assert g['last_device_id'] == 'dev-1'
    assert set(g['device_ids']) == {'dev-1', 'dev-2'}


def test_last_device_id_niezalezny_od_kolejnosci_wejscia_zdarzen():
    # zdarzenia przychodzą odwrotnie do chronologii (późniejsze jako pierwsze
    # na liście) — wynik ma być identyczny jak przy kolejności chronologicznej
    events = [_evt('assembly', 1, 2, 40, device='dev-1'),
              _evt('assembly', 1, 1, 10, device='dev-2')]
    g = phs.aggregate_station_events(events)[0]
    assert g['last_device_id'] == 'dev-1'
    assert set(g['device_ids']) == {'dev-1', 'dev-2'}


def test_grupa_niesie_source_ostatniego_zdarzenia():
    # Poprawka 6: source ostatniego zdarzenia grupy musi przetrwać agregację
    # analogicznie do last_device_id/last_user_id — inaczej ginie jedyny
    # sygnał, że produkt przeskoczył stanowisko automatycznie.
    events = [_evt('finishing', 1, 1, 10, device=None, source='auto_skip'),
              _evt('finishing', 1, 2, 40, device=None, source='auto_skip')]
    g = phs.aggregate_station_events(events)[0]
    assert g['last_source'] == 'auto_skip'


def test_grupa_niesie_source_ostatniego_a_nie_pierwszego_zdarzenia():
    # dwa zdarzenia o różnym source w tej samej grupie — last_source ma
    # wskazywać źródło NAJPÓŹNIEJSZEGO (last_at), tak jak last_device_id.
    events = [_evt('finishing', 1, 1, 10, device='dev-1', source='mobile'),
              _evt('finishing', 1, 2, 40, device=None, source='auto_skip')]
    g = phs.aggregate_station_events(events)[0]
    assert g['last_source'] == 'auto_skip'


def test_cofniecie_niesie_source():
    events = [_evt('formatting', -1, 1, 20, device=None, source='auto_skip')]
    out = phs.aggregate_station_events(events)
    assert out[0]['source'] == 'auto_skip'


def test_grupa_auto_skip_daje_etykiete_systemu_pominal_automatycznie():
    # Integracja poprawki 6: grupa złożona wyłącznie z odbić auto_skip (bez
    # device/user) ma dostać w build_product_history etykietę czytelną dla
    # człowieka — sedno incydentu, dla którego funkcja audytu powstała.
    events = [_evt('finishing', 1, 1, 10, device=None, user=None, source='auto_skip'),
              _evt('finishing', 1, 2, 40, device=None, user=None, source='auto_skip')]
    station_entries = phs.aggregate_station_events(events)
    for entry in station_entries:
        device_id, user_id, source = (
            entry['last_device_id'], entry['last_user_id'], entry['last_source'])
        actor_type = 'device' if device_id else ('user' if user_id else 'system')
        entry['actor_label'] = phs.actor_label(
            actor_type, station_code=entry['station_code'], source=source)
    assert station_entries[0]['actor_label'] == 'System (pominięto automatycznie)'
