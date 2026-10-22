# -*- coding: utf-8 -*-
"""Stan drukarek dla tabletów: migawka z ostatniego kontaktu agenta v2 i sygnały „stan się zmienił”.

Funkcje tylko czytają bazę; sygnały realtime wołamy PO commicie (robi to router agenta)."""
import json
from datetime import datetime

import pytz

from modules.production.drukarki import stale
from modules.production.drukarki.services import agenci
from modules.production.models import LabelPrintJob
from modules.production.services import realtime_service

# Zadania, które jeszcze czekają na wydruk (kolejka widziana przez operatora).
STATUSY_W_KOLEJCE = ('pending', 'claimed', 'sending')

_NAZWY_ROL = {'etykiety': 'Drukarka etykiet', 'wysylka': 'Drukarka paczek'}
_OPISY_STANU = {
    'brak_papieru': 'brak etykiet',
    'otwarta_klapa': 'otwarta klapa',
    'offline': 'nie odpowiada',
    'pauza': 'wstrzymana',
    'blad': 'błąd',
    'nieznany': 'stan nieznany',
}
KOMUNIKAT_AGENT_OFFLINE = 'Agent druku nie odpowiada'
KOMUNIKAT_STARY_AGENT = 'Drukarkę obsługuje stary agent'
KOMUNIKAT_NIEZGLOSZONA = '%s: agent druku jej nie obsługuje'


def komunikat(stan, rola):
    """Tekst banera dla stanu drukarki; pusty dla `gotowa`."""
    opis = _OPISY_STANU.get(stan)
    if opis is None:
        return ''
    return '%s: %s' % (_NAZWY_ROL.get(rola, 'Drukarka'), opis)


def stanowiska_drukarki(nazwa):
    """Kody stanowisk, których tablety mają widzieć stan drukarki."""
    if nazwa == 'wysylka':
        return ['packaging']
    if nazwa == 'etykiety':
        # Import lokalny: label_print_service ciągnie generatory ZPL, a tu potrzebujemy tylko listy stanowisk.
        from modules.production.services import label_print_service
        return list(label_print_service._load_config()['allowed_stations'])
    return []


def _zgloszone(printers_state):
    """Zgłoszone przez agenta stany: {nazwa: stan}. Przyjmuje tekst JSON albo listę."""
    try:
        lista = json.loads(printers_state) if isinstance(printers_state, str) else printers_state
    except ValueError:
        return {}
    wynik = {}
    for d in lista if isinstance(lista, list) else []:
        if isinstance(d, dict) and d.get('nazwa'):
            wynik[d['nazwa']] = d.get('stan')
    return wynik


def _stan_drukarki(rola, zgloszone, online, obsluga):
    """(stan, komunikat) jednej drukarki. Kolejność: stary agent > agent martwy > zgłoszony stan."""
    if obsluga == 'stary':
        return 'nieznany', KOMUNIKAT_STARY_AGENT
    if not online:
        return 'nieznany', KOMUNIKAT_AGENT_OFFLINE
    if rola not in zgloszone:
        # Agent jej nie zgłosił, czyli nie ma jej w swojej konfiguracji i nie pobiera jej zadań. Nie wolno
        # pokazać „gotowa”, bo etykiety po cichu czekałyby w kolejce do wygaśnięcia.
        return 'nieznany', KOMUNIKAT_NIEZGLOSZONA % _NAZWY_ROL.get(rola, 'Drukarka')
    stan = zgloszone.get(rola)
    if stan not in stale.STANY_DRUKARKI:
        stan = 'nieznany'
    # XP-410B nie ma odczytu stanu: agent żywy, zgłosił ją i brak zgłoszonej awarii (offline = nieudane
    # połączenie) = gotowa.
    if rola == 'wysylka' and stan == 'nieznany':
        stan = 'gotowa'
    return stan, komunikat(stan, rola)


def stany_efektywne(printers_state, online):
    """{nazwa: stan} obu drukarek tak, jak zobaczy je tablet — do porównania przed i po kontakcie agenta."""
    zgloszone = _zgloszone(printers_state)
    return {rola: _stan_drukarki(rola, zgloszone, online, agenci.obsluga(rola))[0] for rola in stale.ROLE}


def _poczatek_dnia_utc(teraz_utc):
    """Początek bieżącego dnia lokalnego (Europe/Warsaw) jako naiwny czas UTC — jak `printed_at`."""
    strefa = pytz.timezone('Europe/Warsaw')
    lokalnie = pytz.utc.localize(teraz_utc).astimezone(strefa)
    polnoc = strefa.localize(datetime(lokalnie.year, lokalnie.month, lokalnie.day))
    return polnoc.astimezone(pytz.utc).replace(tzinfo=None)


def _iso(czas):
    return czas.isoformat() + 'Z' if czas else None


def migawka(teraz=None):
    """Stan agenta i obu drukarek. `teraz` = naiwny czas UTC (zegar serwera)."""
    teraz = teraz or datetime.utcnow()
    agent = agenci.aktywny_v2()
    online = agenci.czy_online(agent, teraz)
    zgloszone = _zgloszone(agent.printers_state) if agent is not None and agent.printers_state else {}
    poczatek = _poczatek_dnia_utc(teraz)

    drukarki = []
    for rola in stale.ROLE:
        obsluga = agenci.obsluga(rola)
        stan, tekst = _stan_drukarki(rola, zgloszone, online, obsluga)
        drukarki.append({
            'nazwa': rola,
            'rola': stale.ROLE[rola],
            'stan': stan,
            'komunikat': tekst,
            # Serwer nie śledzi momentu zmiany stanu; dla ciszy agenta „od” to jego ostatni kontakt.
            'od': _iso(agent.last_seen_at) if agent is not None and not online and obsluga == 'nowy' else None,
            'obsluga': obsluga,
            'w_kolejce': LabelPrintJob.query.filter(
                LabelPrintJob.printer == rola, LabelPrintJob.status.in_(STATUSY_W_KOLEJCE)).count(),
            'dzis': LabelPrintJob.query.filter(
                LabelPrintJob.printer == rola, LabelPrintJob.status == 'printed',
                LabelPrintJob.printed_at >= poczatek).count(),
        })
    return {
        'agent': None if agent is None else {
            'online': online, 'ostatni_kontakt': _iso(agent.last_seen_at),
            'wersja': agent.version, 'push': bool(agent.push_connected)},
        'drukarki': drukarki,
    }


def po_zmianie_stanu(stary, nowy):
    """Sygnał `{"kind": "printers"}` na kanały stanowisk drukarek, których stan się zmienił.

    `stary` i `nowy` to {nazwa: stan} (patrz `stany_efektywne`). Wołać PO commicie."""
    kody = []
    for nazwa in stale.ROLE:
        if stary.get(nazwa) != nowy.get(nazwa):
            for kod in stanowiska_drukarki(nazwa):
                if kod not in kody:
                    kody.append(kod)
    for kod in kody:
        realtime_service.publish(realtime_service.channel_station(kod), {'kind': 'printers'})
    return kody
