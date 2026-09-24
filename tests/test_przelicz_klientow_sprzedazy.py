# -*- coding: utf-8 -*-
"""Jednorazowe przeliczenie denormalizacji klientów po partii E (punkt E5).

`orders_count`, `lifetime_net`, `first_order_at` i `last_order_at` liczyły
do 23.09.2026 także zamówienia anulowane i nieopłacone. Zapis bieżący
(`ingest._przelicz_klienta`) liczy już wyłącznie sprzedaż, ale dotyka tylko
klientów, których zamówienia właśnie przyszły z BaseLinkera — anulowane
zamówienie sprzed trzech miesięcy nie przyjdzie już nigdy. Stąd skrypt.
"""
import os
import shutil
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from przelicz_klientow_sprzedazy import przelicz_klientow  # noqa: E402

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _klient_z_licznikami_sprzed_partii_e():
    """Klient z dwoma zamówieniami, z których jedno anulowano — denormalizacja
    w stanie sprzed partii E, czyli z anulowanym w środku."""
    klient = SalesClient(display_name='Anna', orders_count=2,
                         lifetime_net=Decimal('1300.00'),
                         first_order_at=date(2026, 9, 1),
                         last_order_at=date(2026, 9, 10))
    tylko_anulowane = SalesClient(display_name='Ewa', orders_count=1,
                                  lifetime_net=Decimal('50.00'),
                                  first_order_at=date(2026, 9, 3),
                                  last_order_at=date(2026, 9, 3))
    zgodny = SalesClient(display_name='Jan', orders_count=1,
                         lifetime_net=Decimal('70.00'),
                         first_order_at=date(2026, 9, 4),
                         last_order_at=date(2026, 9, 4))
    db.session.add_all([klient, tylko_anulowane, zgodny])
    db.session.flush()
    for bl_id, klient_id, dzien, status, netto in (
            (1, klient.id, date(2026, 9, 1), 138625, '300.00'),
            (2, klient.id, date(2026, 9, 10), 138624, '1000.00'),
            (3, tylko_anulowane.id, date(2026, 9, 3), 138625, '50.00'),
            (4, zgodny.id, date(2026, 9, 4), 105113, '70.00')):
        zamowienie = SalesOrder(baselinker_order_id=bl_id, client_id=klient_id,
                                date_created=dzien, baselinker_status_id=status)
        db.session.add(zamowienie)
        db.session.flush()
        db.session.add(SalesOrderItem(order_id=zamowienie.id, value_net=Decimal(netto)))
    db.session.commit()
    return klient.id, tylko_anulowane.id, zgodny.id


def _stan(id_klienta):
    db.session.expire_all()
    k = SalesClient.query.get(id_klienta)
    return (k.orders_count, k.lifetime_net, k.first_order_at, k.last_order_at)


def test_proba_na_sucho_nic_nie_zapisuje_i_raportuje_roznice(app):
    with app.app_context():
        anna, ewa, jan = _klient_z_licznikami_sprzed_partii_e()
        przed = {k: _stan(k) for k in (anna, ewa, jan)}

        raport = przelicz_klientow(zapisz=False)

        assert {k: _stan(k) for k in (anna, ewa, jan)} == przed
        assert raport['klientow'] == 3
        assert raport['zmienionych'] == 2
        assert raport['bez_sprzedazy'] == 1          # Ewa wypada z kubełków
        assert raport['netto_przed'] == Decimal('1420.00')
        assert raport['netto_po'] == Decimal('1070.00')
        assert {z['id'] for z in raport['zmiany']} == {anna, ewa}


def test_zapis_przelicza_tylko_rozjechanych_i_liczy_wylacznie_sprzedaz(app):
    with app.app_context():
        anna, ewa, jan = _klient_z_licznikami_sprzed_partii_e()

        raport = przelicz_klientow(zapisz=True)

        assert raport['zmienionych'] == 2
        assert _stan(anna) == (1, Decimal('1000.00'), date(2026, 9, 10), date(2026, 9, 10))
        assert _stan(ewa) == (0, Decimal('0.00'), None, None)
        assert _stan(jan) == (1, Decimal('70.00'), date(2026, 9, 4), date(2026, 9, 4))


def test_drugi_przebieg_nie_ma_nic_do_zrobienia(app):
    with app.app_context():
        _klient_z_licznikami_sprzed_partii_e()
        przelicz_klientow(zapisz=True)
        assert przelicz_klientow(zapisz=True)['zmienionych'] == 0


KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRZELICZENIE_W_DEPLOYU = 'venv/bin/python scripts/przelicz_klientow_sprzedazy.py --apply'


def _deploy_sh():
    with open(os.path.join(KORZEN, 'deploy.sh'), encoding='utf-8') as plik:
        return plik.read()


def test_deploy_przelicza_klientow_po_migracjach_a_przed_restartem():
    """Weryfikacja partii E (Z1): kubełki i konwersja karty „Klienci według"
    liczyły anulowane i nieopłacone, dopóki ktoś nie uruchomił tego skryptu
    ręcznie — żadna migracja ani krok wdrożenia go nie wołał. Teraz woła go
    `deploy.sh` przy KAŻDYM wdrożeniu (skrypt jest idempotentny, drugi
    przebieg nic nie zmienia): po migracjach, bo liczy z tabel `sales_*`,
    i przed restartem, żeby nowy kod od pierwszego żądania czytał
    przeliczoną denormalizację."""
    skrypt = _deploy_sh()
    migracje = skrypt.index('venv/bin/flask migrate')
    przeliczenie = skrypt.index(PRZELICZENIE_W_DEPLOYU)
    restart = skrypt.index('supervisorctl restart')
    assert migracje < przeliczenie < restart


def test_nieudane_przeliczenie_klientow_nie_przerywa_deployu():
    """Decyzja dyspozytora (23.09): krok jest BEST-EFFORT, jak `pip install`
    i `sync-changelog` w tym samym pliku. Analityka nie może blokować
    wdrożeń reszty CRM (tablety hali, produkcja) — błąd zostawia ostrzeżenie
    w logu deployu, a restart idzie dalej. Liczniki poprawi kolejne
    wdrożenie albo ręczne uruchomienie skryptu."""
    skrypt = _deploy_sh()
    przeliczenie = skrypt.index(PRZELICZENIE_W_DEPLOYU)
    restart = skrypt.index('supervisorctl restart')
    krok = skrypt[przeliczenie:restart]
    assert f'{PRZELICZENIE_W_DEPLOYU} 2>&1 || echo' in skrypt
    assert 'exit 1' not in krok
    # Zawieszony skrypt też nie może trzymać locka deployu bez końca — także
    # taki, który ignoruje SIGTERM: `-k` dobija go SIGKILL-em (weryfikacja E8, Z4).
    assert f'timeout -k 10 300 {PRZELICZENIE_W_DEPLOYU}' in skrypt
    assert f'if ! {PRZELICZENIE_W_DEPLOYU}' not in skrypt


def test_zapasowy_deploy_z_workflow_tez_przelicza_klientow():
    """Weryfikacja E8 (Z5): `.github/workflows/deploy.yml` (ręczny fallback)
    po `git reset` od razu restartował — bez migracji i bez przeliczenia
    klientów. Teraz robi to samo co deploy.sh: migracje przed restartem
    (blokujące, `set -e`), potem przeliczenie best-effort z tym samym
    `timeout -k 10 300` i ostrzeżeniem, potem restart."""
    with open(os.path.join(KORZEN, '.github', 'workflows', 'deploy.yml'),
              encoding='utf-8') as plik:
        workflow = plik.read()
    assert 'set -e' in workflow
    migracje = workflow.index('venv/bin/flask migrate')
    przeliczenie = workflow.index(
        f'timeout -k 10 300 {PRZELICZENIE_W_DEPLOYU} 2>&1 || echo "[recount-warn]')
    restart = workflow.index('supervisorctl restart')
    assert migracje < przeliczenie < restart
    # Migracja nie jest best-effort: bez `|| ...` przerywa deploy przez `set -e`.
    linia_migracji = workflow[migracje:].splitlines()[0]
    assert '||' not in linia_migracji


# Podmiany, które zamykają kopię deploy.sh w katalogu tymczasowym. Każda MUSI
# trafić dokładnie raz — inaczej kopia mogłaby sięgnąć po prawdziwy git,
# sudo albo katalog aplikacji, więc test wtedy pada, zamiast cokolwiek odpalać.
_PODMIANY_DEPLOYU = (
    'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
    'LOCK_FILE="/tmp/crm-deploy.lock"',
    'APP_DIR="/home/woodpower-crm/htdocs/crm.woodpower.pl"',
)


def _zaslepka(sciezka, *wiersze):
    """Wykonywalny skrypt basha z podanych wierszy."""
    with open(sciezka, 'w', encoding='utf-8', newline='\n') as plik:
        plik.write('\n'.join(('#!/bin/bash',) + wiersze) + '\n')
    os.chmod(sciezka, 0o755)


def _uruchom_kopie_deployu(katalog, kod_migracji, kod_przeliczenia,
                           cialo_przeliczenia=(), krotki_timeout=None):
    """Kopia deploy.sh na zaślepkach: git, sudo i venv/bin/* tylko zapisują
    swoje wywołanie do dziennika i wychodzą z zadanym kodem.

    `cialo_przeliczenia` to dodatkowe wiersze zaślepki `venv/bin/python` przed
    jej `exit`, a `krotki_timeout` podmienia `timeout -k 10 300` (dokładnie
    raz) na krótszy — żeby sprawdzić dobijanie procesu bez czekania 5 minut."""
    import subprocess

    dziennik = os.path.join(katalog, 'wywolania.log')
    zaslepki = os.path.join(katalog, 'bin')
    aplikacja = os.path.join(katalog, 'app')
    venv = os.path.join(aplikacja, 'venv', 'bin')
    os.makedirs(zaslepki)
    os.makedirs(venv)

    licznik = os.path.join(katalog, 'licznik')
    # Kolejne `git rev-parse` dają różne rewizje, więc krok changeloga też idzie.
    _zaslepka(os.path.join(zaslepki, 'git'),
              f'echo "git $*" >> "{dziennik}"',
              'if [ "$1" = "rev-parse" ]; then',
              f'  n=$(cat "{licznik}" 2>/dev/null || echo 0); n=$((n+1))',
              f'  echo $n > "{licznik}"; echo "rewizja$n"',
              'fi',
              'exit 0')
    _zaslepka(os.path.join(zaslepki, 'sudo'), f'echo "sudo $*" >> "{dziennik}"', 'exit 0')
    _zaslepka(os.path.join(venv, 'pip'), f'echo "pip $*" >> "{dziennik}"', 'exit 0')
    _zaslepka(os.path.join(venv, 'flask'),
              f'echo "flask $*" >> "{dziennik}"',
              f'if [ "$1" = "migrate" ]; then exit {kod_migracji}; fi',
              'exit 0')
    _zaslepka(os.path.join(venv, 'python'),
              f'echo "python $*" >> "{dziennik}"', *cialo_przeliczenia,
              f'exit {kod_przeliczenia}')

    skrypt = _deploy_sh()
    zamiany = (
        f'export PATH="{zaslepki}:/usr/bin:/bin"',
        f'LOCK_FILE="{os.path.join(katalog, "deploy.lock")}"',
        f'APP_DIR="{aplikacja}"',
    )
    for stare, nowe in zip(_PODMIANY_DEPLOYU, zamiany):
        assert skrypt.count(stare) == 1, stare
        skrypt = skrypt.replace(stare, nowe)
    if krotki_timeout:
        assert skrypt.count('timeout -k 10 300 ') == 1
        skrypt = skrypt.replace('timeout -k 10 300 ', krotki_timeout + ' ')
    kopia = os.path.join(katalog, 'deploy.sh')
    with open(kopia, 'w', encoding='utf-8', newline='\n') as plik:
        plik.write(skrypt)

    wynik = subprocess.run(['bash', kopia], capture_output=True, text=True, timeout=60)
    with open(dziennik, encoding='utf-8') as plik:
        wywolania = plik.read()
    return wynik, wywolania


_BASH = shutil.which('bash') if os.name != 'nt' else None


@pytest.mark.skipif(_BASH is None, reason='symulacja deploy.sh wymaga basha (kontener)')
def test_kopia_deployu_restartuje_mimo_bledu_przeliczenia(tmp_path):
    wynik, wywolania = _uruchom_kopie_deployu(str(tmp_path), kod_migracji=0,
                                              kod_przeliczenia=1)
    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    assert 'python scripts/przelicz_klientow_sprzedazy.py --apply' in wywolania
    assert 'sudo /usr/bin/supervisorctl restart crm_woodpower' in wywolania
    assert '[recount-warn]' in wynik.stdout
    assert 'Deploy complete!' in wynik.stdout


@pytest.mark.skipif(_BASH is None, reason='symulacja deploy.sh wymaga basha (kontener)')
def test_kopia_deployu_dobija_przeliczenie_gluche_na_sigterm(tmp_path):
    """Weryfikacja E8 (Z4). Samo `timeout N` wysyła SIGTERM i czeka, aż proces
    się skończy — zaślepka z `trap '' TERM` trzymała lock deployu do własnego
    końca. Z `-k` po czasie przychodzi SIGKILL. Kopia ma `timeout -k 1 2`
    zamiast `-k 10 300`, a zaślepka śpi 30 s głucha na SIGTERM: deploy ma
    skończyć się w kilka sekund, z ostrzeżeniem i z restartem."""
    import time
    start = time.monotonic()
    wynik, wywolania = _uruchom_kopie_deployu(
        str(tmp_path), kod_migracji=0, kod_przeliczenia=0,
        cialo_przeliczenia=("trap '' TERM", 'sleep 30'), krotki_timeout='timeout -k 1 2')
    trwalo = time.monotonic() - start
    assert trwalo < 15, f'deploy czekał {trwalo:.1f} s na proces głuchy na SIGTERM'
    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    assert '[recount-warn]' in wynik.stdout
    assert 'sudo /usr/bin/supervisorctl restart crm_woodpower' in wywolania


@pytest.mark.skipif(_BASH is None, reason='symulacja deploy.sh wymaga basha (kontener)')
def test_kopia_deployu_dalej_przerywa_na_nieudanej_migracji(tmp_path):
    """Kontrast: best-effort dotyczy wyłącznie przeliczenia. Nieudana migracja
    dalej przerywa wdrożenie PRZED restartem, a przeliczenie się nie odpala."""
    wynik, wywolania = _uruchom_kopie_deployu(str(tmp_path), kod_migracji=1,
                                              kod_przeliczenia=0)
    assert wynik.returncode == 1
    assert 'flask migrate' in wywolania
    assert 'przelicz_klientow_sprzedazy' not in wywolania
    assert 'supervisorctl restart' not in wywolania
