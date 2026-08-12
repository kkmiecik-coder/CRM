"""Testy klasyfikacji strumienia SSE w print-agencie.

Agent jest poza pakietem aplikacji (stdlib-only skrypt na hubie biura),
więc ładujemy go z pliku.
"""
import importlib.util
import os
import sys

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


def test_backoff_reconnectu_rosnie_i_ma_sufit():
    delays = [print_agent._reconnect_delay(n) for n in range(1, 10)]
    assert delays[0] < delays[3], 'backoff musi rosnąć'
    assert max(delays) <= print_agent.SSE_RECONNECT_MAX_SECONDS + 3, 'sufit backoffu przekroczony'


def test_backoff_ma_jitter():
    """Bez jittera wszystkie klienty wracają do brokera w tej samej chwili."""
    probes = {print_agent._reconnect_delay(5) for _ in range(20)}
    assert len(probes) > 1
