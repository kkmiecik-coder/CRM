"""Testy klasyfikacji strumienia SSE w print-agencie.

Agent jest poza pakietem aplikacji (stdlib-only skrypt na hubie biura),
więc ładujemy go z pliku.
"""
import importlib.util
import os
import sys
import time
from datetime import time as dtime

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

_AGENT_PATH = os.path.join(REPO_ROOT, 'tools', 'print_agent', 'print_agent.py')
_spec = importlib.util.spec_from_file_location('print_agent_under_test', _AGENT_PATH)
print_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(print_agent)


@pytest.mark.parametrize('line', [
    'data: {}',
    'data: {}\n',
    'data:{}',
    'data: ',
])
def test_ping_nie_budzi_agenta(line):
    assert print_agent.classify_sse_line(line) == 'ping'


def test_ramka_powitalna_nie_jest_sygnalem():
    line = 'data: {"connect":{"client":"c09d1965","version":"6.9.1 OSS","subs":{},"ping":25}}'
    assert print_agent.classify_sse_line(line) == 'connect'


@pytest.mark.parametrize('line', [
    '',
    '\n',
    ': keep-alive',
    'event: message',
    'id: 42',
])
def test_szum_protokolu_nie_budzi_agenta(line):
    assert print_agent.classify_sse_line(line) == 'noise'


def test_publikacja_jest_sygnalem():
    line = 'data: {"pub":{"data":{"kind":"print","count":2}},"channel":"print:agent"}'
    assert print_agent.classify_sse_line(line) == 'signal'


def test_nieznana_ramka_jest_sygnalem():
    """Nie parsujemy protokołu Centrifugo — cokolwiek innego niż ping i connect
    ma obudzić agenta. Zmiana formatu push po stronie brokera nie może uciszyć
    drukarki."""
    line = 'data: {"cos_nowego_w_kolejnej_wersji":{"x":1}}'
    assert print_agent.classify_sse_line(line) == 'signal'


def test_niesparsowalny_json_jest_sygnalem():
    """Fałszywe obudzenie kosztuje jedno puste zapytanie. Przespany sygnał
    kosztuje minutę czekania operatora przy drukarce."""
    assert print_agent.classify_sse_line('data: {niedomkniety') == 'signal'


def test_bajty_sa_dekodowane():
    assert print_agent.classify_sse_line(b'data: {}') == 'ping'
    assert print_agent.classify_sse_line(b'data: {"pub":{}}') == 'signal'


class _FakeStream:
    """Strumień, który milczy — czekanie kończy się timeoutem po pełnym limicie,
    tak jak zrobiłoby to prawdziwe gniazdo."""
    def __init__(self, sleep_scale=1.0):
        self.timeouts_requested = []
        self._sleep_scale = sleep_scale

    def read_line(self, timeout):
        self.timeouts_requested.append(timeout)
        time.sleep(timeout * self._sleep_scale)
        raise TimeoutError('brak danych')


_CFG_CALY_DZIEN = {
    'workdays_start': dtime(0, 0), 'workdays_end': dtime(23, 59),
    'saturday_start': dtime(0, 0), 'saturday_end': dtime(23, 59),
}


def test_czekanie_na_push_nie_zjada_okna_pollingu():
    """Gdyby broker zamilkł, a limit czytania był dłuższy niż okno zapasowego
    pollingu, etykieta czekałaby DŁUŻEJ niż gdyby pusha w ogóle nie było."""
    stream = _FakeStream()
    deadline = time.monotonic() + 2
    start = time.monotonic()

    outcome = print_agent.wait_for_signal(stream, deadline, _CFG_CALY_DZIEN)

    assert outcome == 'poll', 'koniec okna czekania to nie awaria brokera'
    assert time.monotonic() <= deadline + 1, 'przekroczony deadline zapasowego pollingu'
    # Limit pojedynczego czytania musi być przycięty do czasu do deadline'u,
    # a nie ustawiony na pełny limit ciszy (40 s).
    assert max(stream.timeouts_requested) <= 2.0
    assert time.monotonic() - start < 5


def test_cisza_dluzsza_niz_limit_pinga_zamyka_polaczenie():
    # sleep_scale=0: nie chcemy czekać w teście realnych 40 s ciszy.
    stream = _FakeStream(sleep_scale=0)
    # Deadline daleko → decyduje limit ciszy, a brak pinga to realna awaria.
    outcome = print_agent.wait_for_signal(stream, time.monotonic() + 3600, _CFG_CALY_DZIEN)

    assert outcome == 'closed'
    assert stream.timeouts_requested == [print_agent.SSE_PING_TIMEOUT_SECONDS]


def test_limit_nawiazania_polaczenia_krotszy_niz_limit_ciszy():
    """Zawieszony broker (przyjmuje TCP, milczy) nie może zablokować pętli
    agenta — a razem z nią zapasowego pollingu — na czas limitu ciszy."""
    assert print_agent.SSE_CONNECT_TIMEOUT_SECONDS < print_agent.SSE_PING_TIMEOUT_SECONDS
    assert print_agent.SSE_CONNECT_TIMEOUT_SECONDS <= 10


def test_czas_reakcji_pokazywany_w_milisekundach():
    assert print_agent._format_reaction(0.089) == '89 ms'
    assert print_agent._format_reaction(1.34) == '1.3 s'


def test_wiek_zadania_ponizej_rozdzielczosci_nie_jest_pokazywany():
    """requested_at to DATETIME bez ułamków sekundy — dla świeżych zadań wiek
    zawyżał o prawie sekundę i log kłamał (90 ms pokazywane jako 0,9 s)."""
    from datetime import datetime, timedelta
    swieze = (datetime.utcnow() - timedelta(seconds=0.5)).isoformat()
    assert print_agent._describe_job_age(swieze) == ''


def test_wiek_zadania_powyzej_rozdzielczosci_jest_przyblizony():
    from datetime import datetime, timedelta
    stare = (datetime.utcnow() - timedelta(seconds=45)).isoformat()
    opis = print_agent._describe_job_age(stare)
    assert 'czekało ~' in opis and 's)' in opis
    assert '~' in opis, 'wiek z kolejki jest znany tylko z dokładnością do sekundy'


def test_reakcja_tylko_dla_zadan_z_sygnalu():
    """Przy pollingu czas reakcji nic nie znaczy — zadanie mogło czekać całe okno."""
    assert 'reakcja' in print_agent._describe_timing(time.monotonic(), None)
    assert 'reakcja' not in print_agent._describe_timing(None, None)


def test_backoff_reconnectu_rosnie_i_ma_sufit():
    delays = [print_agent._reconnect_delay(n) for n in range(1, 10)]
    assert delays[0] < delays[3], 'backoff musi rosnąć'
    assert max(delays) <= print_agent.SSE_RECONNECT_MAX_SECONDS + 3, 'sufit backoffu przekroczony'


def test_backoff_ma_jitter():
    """Bez jittera wszystkie klienty wracają do brokera w tej samej chwili."""
    probes = {print_agent._reconnect_delay(5) for _ in range(20)}
    assert len(probes) > 1
