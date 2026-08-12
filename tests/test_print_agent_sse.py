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


class _PingujacyStream:
    """Strumień, który regularnie przysyła pingi — jak żywy broker."""
    def __init__(self, odstep):
        self.odstep = odstep
        self.timeouts_requested = []

    def read_line(self, timeout):
        self.timeouts_requested.append(timeout)
        time.sleep(self.odstep)
        return b'data: {}'


def test_nigdy_nie_przerywamy_czytania_w_pol():
    """Regresja z produkcji 12.08.2026: kanał push padał równo co 60 s.

    Przerwany timeoutem readline() TRWALE psuje bufor strumienia (kolejne
    czytania rzucają "cannot read from timed out object"). Przycinanie limitu
    czytania do deadline'u zapasowego pollingu oznaczało więc wymuszony timeout
    przy każdym oknie — czyli zabijanie zdrowego połączenia co minutę.

    Limit czytania musi być ZAWSZE pełnym limitem ciszy: wtedy timeout zdarza
    się tylko wtedy, gdy i tak zrywamy połączenie.
    """
    stream = _PingujacyStream(odstep=0.2)

    print_agent.wait_for_signal(stream, time.monotonic() + 0.5, _CFG_CALY_DZIEN)

    assert stream.timeouts_requested, 'strumień nie był w ogóle czytany'
    assert set(stream.timeouts_requested) == {print_agent.SSE_PING_TIMEOUT_SECONDS}, (
        'limit czytania został przycięty — to psuje bufor przy każdym oknie pollingu'
    )


def test_deadline_konczy_czekanie_na_najblizszej_ramce():
    """Deadline dotrzymujemy z dokładnością do jednego odstępu między pingami —
    zegar sprawdzamy MIĘDZY ramkami, nie przerywając czytania."""
    stream = _PingujacyStream(odstep=0.2)
    start = time.monotonic()

    outcome = print_agent.wait_for_signal(stream, time.monotonic() + 0.5, _CFG_CALY_DZIEN)

    assert outcome == 'poll', 'koniec okna czekania to nie awaria brokera'
    assert time.monotonic() - start < 2, 'czekanie nie zakończyło się na kolejnej ramce'


def test_cisza_dluzsza_niz_limit_pinga_zamyka_polaczenie():
    # sleep_scale=0: nie chcemy czekać w teście realnych 40 s ciszy.
    stream = _FakeStream(sleep_scale=0)
    # Deadline daleko → decyduje limit ciszy, a brak pinga to realna awaria.
    outcome = print_agent.wait_for_signal(stream, time.monotonic() + 3600, _CFG_CALY_DZIEN)

    assert outcome == 'closed'
    assert stream.timeouts_requested == [print_agent.SSE_PING_TIMEOUT_SECONDS]


def test_limit_czytania_nie_dziedziczy_limitu_nawiazania_polaczenia(monkeypatch):
    """Regresja z produkcji 12.08.2026: kanał push rozpadał się co 5 sekund.

    http.client dla odpowiedzi bez Content-Length (a taki jest strumień SSE)
    „przekazuje gniazdo odpowiedzi” i ustawia conn.sock = None. Ustawianie
    limitu czytania przez conn.sock po cichu nic nie robiło, więc gniazdo
    zostawało z limitem od nawiązywania połączenia — krótszym niż odstęp
    między pingami brokera.

    Test używa CELOWO różnych wartości obu limitów. Poprzednia wersja
    ustawiała je na tę samą liczbę i przechodziła mimo błędu.
    """
    import socket as socket_mod
    import threading

    monkeypatch.setattr(print_agent, 'SSE_CONNECT_TIMEOUT_SECONDS', 1)
    monkeypatch.setattr(print_agent, 'SSE_PING_TIMEOUT_SECONDS', 30)

    CISZA_SEKUND = 3          # dłużej niż limit nawiązania, krócej niż limit ciszy

    def broker(sock):
        conn, _ = sock.accept()
        conn.recv(4096)
        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n')
        conn.sendall(b'data: {"connect":{"ping":25}}\n\n')
        time.sleep(CISZA_SEKUND)
        conn.sendall(b'data: {"channel":"print:agent","pub":{"data":{"kind":"print"}}}\n\n')
        time.sleep(30)

    srv = socket_mod.socket()
    srv.setsockopt(socket_mod.SOL_SOCKET, socket_mod.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    threading.Thread(target=broker, args=(srv,), daemon=True).start()

    stream = print_agent.open_sse(f'http://127.0.0.1:{port}/connection/uni_sse', 'token')
    start = time.monotonic()
    outcome = print_agent.wait_for_signal(stream, time.monotonic() + 20, _CFG_CALY_DZIEN)
    elapsed = time.monotonic() - start
    stream.close()

    assert outcome == 'signal', 'cisza krótsza niż limit ciszy nie może zrywać kanału'
    assert elapsed >= CISZA_SEKUND - 0.5, 'połączenie padło przed nadejściem ramki'


def test_limit_nawiazania_polaczenia_krotszy_niz_limit_ciszy():
    """Zawieszony broker (przyjmuje TCP, milczy) nie może zablokować pętli
    agenta — a razem z nią zapasowego pollingu — na czas limitu ciszy."""
    assert print_agent.SSE_CONNECT_TIMEOUT_SECONDS < print_agent.SSE_PING_TIMEOUT_SECONDS
    assert print_agent.SSE_CONNECT_TIMEOUT_SECONDS <= 10


def test_agent_oproznia_kolejke_a_nie_pobiera_jednej_porcji(monkeypatch):
    """Regresja z produkcji 12.08.2026: etykieta czekała 85 s przy sprawnym pushu.

    /jobs oddaje najwyżej jobs_limit zadań, a CRM wysyła JEDEN sygnał na całe
    zlecenie — także takie na 20 etykiet. Pobranie jednej porcji i pójście spać
    zostawiało resztę do następnego obudzenia, a kolejny sygnał szedł na
    dociągnięcie zaległości, więc zadanie, które go wywołało, stawało się nową
    zaległością.
    """
    cfg = {'jobs_limit': 10, 'request_timeout': 5, 'printer_ip': '127.0.0.1',
           'printer_port': 9100, 'printer_timeout': 5}
    porcje = [
        {'jobs': [{'id': i, 'short_product_id': 'X', 'zpl_payload': '^XA^XZ',
                   'requested_at': None} for i in range(10)]},          # pełna
        {'jobs': [{'id': 100, 'short_product_id': 'X', 'zpl_payload': '^XA^XZ',
                   'requested_at': None}]},                             # resztka
        {'jobs': []},
    ]
    pobrania = []
    wydrukowane = []

    monkeypatch.setattr(print_agent, 'fetch_jobs', lambda c: (pobrania.append(1), porcje.pop(0))[1])
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda c, z: wydrukowane.append(z))
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})

    assert print_agent.run_once(cfg) is True
    assert len(pobrania) == 2, 'po pełnej porcji agent musi wrócić po resztę bez czekania'
    assert len(wydrukowane) == 11


def test_niepelna_porcja_konczy_cykl(monkeypatch):
    """Nie odpytujemy w kółko, gdy kolejka jest już pusta."""
    cfg = {'jobs_limit': 10, 'request_timeout': 5, 'printer_ip': '127.0.0.1',
           'printer_port': 9100, 'printer_timeout': 5}
    pobrania = []

    def fetch(c):
        pobrania.append(1)
        return {'jobs': [{'id': 1, 'short_product_id': 'X', 'zpl_payload': '^XA^XZ',
                          'requested_at': None}]}

    monkeypatch.setattr(print_agent, 'fetch_jobs', fetch)
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda c, z: None)
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})

    print_agent.run_once(cfg)
    assert len(pobrania) == 1


def test_oproznianie_kolejki_ma_bezpiecznik(monkeypatch):
    """Kolejka rosnąca szybciej niż drukarka nie może zablokować pętli głównej."""
    cfg = {'jobs_limit': 2, 'request_timeout': 5, 'printer_ip': '127.0.0.1',
           'printer_port': 9100, 'printer_timeout': 5}
    pobrania = []

    def fetch(c):
        pobrania.append(1)
        return {'jobs': [{'id': 1, 'short_product_id': 'X', 'zpl_payload': '^XA^XZ',
                          'requested_at': None}] * 2}          # zawsze pełna porcja

    monkeypatch.setattr(print_agent, 'fetch_jobs', fetch)
    monkeypatch.setattr(print_agent, 'send_to_printer', lambda c, z: None)
    monkeypatch.setattr(print_agent, 'ack_jobs', lambda c, r: {'updated': len(r)})

    assert print_agent.run_once(cfg) is True
    assert len(pobrania) == print_agent._MAX_BATCHES_PER_CYCLE


def test_maly_rozjazd_zegarow_nie_straszy_w_logu():
    """Zegar huba idzie ułamek sekundy za serwerem — wiek wychodzi ujemny."""
    from datetime import datetime, timedelta
    przyszlosc = (datetime.utcnow() + timedelta(seconds=0.8)).isoformat()
    assert print_agent._describe_job_age(przyszlosc) == ' (czekało 0.0s)'


def test_duzy_rozjazd_zegarow_jest_widoczny():
    from datetime import datetime, timedelta
    daleko = (datetime.utcnow() + timedelta(seconds=600)).isoformat()
    assert 'req ' in print_agent._describe_job_age(daleko)


def test_czas_reakcji_pokazywany_w_milisekundach():
    assert print_agent._format_reaction(0.089) == '89 ms'
    assert print_agent._format_reaction(1.34) == '1.3 s'


def test_wiek_zadania_ponizej_sekundy_ma_ulamki():
    """Po migracji requested_at na DATETIME(3) ułamki sekundy nie giną w bazie,
    a po wdrożeniu pusha cała interesująca skala jest właśnie poniżej sekundy."""
    from datetime import datetime, timedelta
    swieze = (datetime.utcnow() - timedelta(seconds=0.12)).isoformat()
    opis = print_agent._describe_job_age(swieze)
    assert 'czekało 0.1' in opis


def test_wiek_zadania_w_sekundach_i_minutach():
    from datetime import datetime, timedelta
    assert 'czekało 45.0s' in print_agent._describe_job_age(
        (datetime.utcnow() - timedelta(seconds=45)).isoformat())
    assert 'czekało 7m' in print_agent._describe_job_age(
        (datetime.utcnow() - timedelta(seconds=444)).isoformat())


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
