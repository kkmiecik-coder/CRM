# -*- coding: utf-8 -*-
"""
deploy.sh: bramka migracji i środowisko CLI takie samo jak gunicorna.

Dwie rzeczy, których pilnują te testy:

1. CLI Flaska z python-dotenv sam wczytuje .env, a gunicorn nie. Bez
   FLASK_SKIP_DOTENV=1 klucz sesji wpisany do .env na serwerze przepuszczał
   `flask migrate` przez bramkę, po czym gunicorn po restarcie nie wstawał (502).

2. Nieudany `flask migrate` przerywa deploy PRZED restartem ORAZ cofa kod na
   dysku do poprzedniego HEAD. Gunicorn bez --preload importuje app.py przy
   każdym nowym workerze, więc nowy, niedziałający kod na dysku mógłby położyć
   serwer bez niczyjego restartu.

Skrypt uruchamiamy jako KOPIĘ w katalogu tymczasowym: ścieżki serwera i PATH
podmieniamy, a git, pip, flask i sudo to zaślepki zapisujące wywołania. Każda
podmiana musi trafić dokładnie raz — inaczej test przerywa się, zanim cokolwiek
uruchomi (nigdy nie wołamy prawdziwego sudo ani supervisorctl).
"""

import os
import shutil
import stat
import subprocess
import sys

import pytest


KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASH = shutil.which('bash')

pytestmark = pytest.mark.skipif(
    BASH is None or sys.platform.startswith('win'),
    reason='deploy.sh uruchamiamy tylko pod bashem na Linuksie (kontener testów)',
)

STARY_HEAD = 'a' * 40
NOWY_HEAD = 'b' * 40

ZASLEPKA_GIT = r'''#!/bin/bash
echo "git $*" >> "$ZAPIS"
case "$1" in
    rev-parse) cat "$STAN_HEAD" ;;
    fetch) ;;
    reset)
        if [ "$3" = "origin/main" ]; then
            echo "$NOWY_HEAD" > "$STAN_HEAD"
        else
            echo "$3" > "$STAN_HEAD"
        fi
        ;;
esac
exit 0
'''

ZASLEPKA_FLASK = r'''#!/bin/bash
echo "flask $1 FLASK_SKIP_DOTENV=${FLASK_SKIP_DOTENV:-} FLASK_APP=${FLASK_APP:-}" >> "$ZAPIS"
if [ "$1" = "migrate" ] && [ -f "$MIGRACJA_PADA" ]; then
    exit 1
fi
exit 0
'''

ZASLEPKA_SUDO = '#!/bin/bash\necho "sudo $*" >> "$ZAPIS"\nexit 0\n'
ZASLEPKA_PIP = '#!/bin/bash\nexit 0\n'


def _zapisz_wykonywalny(sciezka, tresc):
    with open(sciezka, 'w', encoding='utf-8', newline='\n') as f:
        f.write(tresc)
    os.chmod(sciezka, os.stat(sciezka).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _podmien_raz(tresc, stare, nowe):
    if tresc.count(stare) != 1:
        pytest.fail(f'deploy.sh zmienił się: {stare!r} występuje {tresc.count(stare)} razy '
                    '— popraw podmiany w teście, zanim cokolwiek uruchomisz')
    return tresc.replace(stare, nowe)


@pytest.fixture()
def srodowisko(tmp_path):
    """Katalog aplikacji z venv/bin/{flask,pip}, katalog zaślepek i kopia deploy.sh."""
    katalog_app = tmp_path / 'app'
    (katalog_app / 'venv' / 'bin').mkdir(parents=True)
    zaslepki = tmp_path / 'bin'
    zaslepki.mkdir()

    _zapisz_wykonywalny(zaslepki / 'git', ZASLEPKA_GIT)
    _zapisz_wykonywalny(zaslepki / 'sudo', ZASLEPKA_SUDO)
    _zapisz_wykonywalny(katalog_app / 'venv' / 'bin' / 'flask', ZASLEPKA_FLASK)
    _zapisz_wykonywalny(katalog_app / 'venv' / 'bin' / 'pip', ZASLEPKA_PIP)

    with open(os.path.join(KORZEN, 'deploy.sh'), encoding='utf-8') as f:
        skrypt = f.read()

    blokada = tmp_path / 'crm-deploy.lock'
    skrypt = _podmien_raz(
        skrypt,
        'export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
        f'export PATH="{zaslepki}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"',
    )
    skrypt = _podmien_raz(skrypt, 'LOCK_FILE="/tmp/crm-deploy.lock"', f'LOCK_FILE="{blokada}"')
    skrypt = _podmien_raz(skrypt, 'APP_DIR="/home/woodpower-crm/htdocs/crm.woodpower.pl"',
                          f'APP_DIR="{katalog_app}"')
    kopia = tmp_path / 'deploy.sh'
    _zapisz_wykonywalny(kopia, skrypt)

    stan_head = tmp_path / 'head'
    stan_head.write_text(STARY_HEAD + '\n', encoding='utf-8')

    return {
        'skrypt': kopia,
        'zapis': tmp_path / 'wywolania.log',
        'stan_head': stan_head,
        'migracja_pada': tmp_path / 'migracja_pada',
        'blokada': blokada,
    }


def _uruchom(srodowisko, migracja_pada):
    if migracja_pada:
        srodowisko['migracja_pada'].write_text('1', encoding='utf-8')

    env = {k: v for k, v in os.environ.items() if not k.startswith('FLASK_')}
    env.update({
        'ZAPIS': str(srodowisko['zapis']),
        'STAN_HEAD': str(srodowisko['stan_head']),
        'NOWY_HEAD': NOWY_HEAD,
        'MIGRACJA_PADA': str(srodowisko['migracja_pada']),
    })
    wynik = subprocess.run([BASH, str(srodowisko['skrypt'])], env=env,
                           capture_output=True, text=True, timeout=60)
    wywolania = srodowisko['zapis'].read_text(encoding='utf-8').splitlines()
    head_na_koniec = srodowisko['stan_head'].read_text(encoding='utf-8').strip()
    return wynik, wywolania, head_na_koniec


def test_nieudana_migracja_cofa_kod_i_nie_restartuje(srodowisko):
    wynik, wywolania, head = _uruchom(srodowisko, migracja_pada=True)

    assert wynik.returncode == 1, wynik.stdout + wynik.stderr
    assert '[MIGRATION FAILED]' in wynik.stdout
    # Najpierw pobranie nowego kodu, potem powrót do starego.
    resety = [w for w in wywolania if w.startswith('git reset')]
    assert resety == ['git reset --hard origin/main', f'git reset --hard {STARY_HEAD}']
    assert head == STARY_HEAD
    # Ani chown logów, ani restartu supervisora.
    assert [w for w in wywolania if w.startswith('sudo')] == []
    assert not srodowisko['blokada'].exists()


def test_udana_migracja_restartuje_bez_cofania(srodowisko):
    wynik, wywolania, head = _uruchom(srodowisko, migracja_pada=False)

    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    assert 'Deploy complete!' in wynik.stdout
    assert [w for w in wywolania if w.startswith('git reset')] == ['git reset --hard origin/main']
    assert head == NOWY_HEAD
    assert 'sudo /usr/bin/supervisorctl restart crm_woodpower' in wywolania


@pytest.mark.parametrize('migracja_pada', [True, False])
def test_kazda_komenda_flask_ma_wylaczony_dotenv(srodowisko, migracja_pada):
    _, wywolania, _ = _uruchom(srodowisko, migracja_pada=migracja_pada)

    komendy_flask = [w for w in wywolania if w.startswith('flask ')]
    assert [w.split()[1] for w in komendy_flask] == ['sync-changelog', 'migrate']
    for wiersz in komendy_flask:
        assert 'FLASK_SKIP_DOTENV=1' in wiersz.split(), wiersz
        assert 'FLASK_APP=app.py' in wiersz.split(), wiersz


# ----------------------------------------------------------------------------
# Mechanizm: CLI Flaska czyta .env, dopóki FLASK_SKIP_DOTENV go nie wyłączy
# ----------------------------------------------------------------------------

APLIKACJA_ZNACZNIKA = '''
import os
from flask import Flask

app = Flask(__name__)


@app.cli.command('znacznik')
def znacznik():
    print('ZNACZNIK=' + os.environ.get('ZNACZNIK_Z_DOTENV', 'brak'))
'''


def _znacznik_z_cli(katalog, **dodatkowe_env):
    env = {k: v for k, v in os.environ.items() if not k.startswith('FLASK_')}
    env.pop('ZNACZNIK_Z_DOTENV', None)
    env.update({'FLASK_APP': 'aplikacja_znacznika.py'}, **dodatkowe_env)
    wynik = subprocess.run([sys.executable, '-m', 'flask', 'znacznik'], cwd=str(katalog),
                           env=env, capture_output=True, text=True, timeout=60)
    assert wynik.returncode == 0, wynik.stdout + wynik.stderr
    return wynik.stdout.strip().splitlines()[-1]


def test_cli_flaska_czyta_env_a_flask_skip_dotenv_to_wylacza(tmp_path):
    # Dowód na W1 i na to, że poprawka działa z zainstalowaną wersją Flaska:
    # bez FLASK_SKIP_DOTENV zmienna z .env dociera do komendy CLI.
    (tmp_path / 'aplikacja_znacznika.py').write_text(APLIKACJA_ZNACZNIKA, encoding='utf-8')
    (tmp_path / '.env').write_text('ZNACZNIK_Z_DOTENV=z_pliku\n', encoding='utf-8')

    assert _znacznik_z_cli(tmp_path) == 'ZNACZNIK=z_pliku'
    assert _znacznik_z_cli(tmp_path, FLASK_SKIP_DOTENV='1') == 'ZNACZNIK=brak'
