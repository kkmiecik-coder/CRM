# -*- coding: utf-8 -*-
"""
scripts/cron_endpoint.sh: wpis crontaba woła endpoint CRON z sekretem z core.json.

Po usunięciu wartości zapasowej sekretu (cron_auth.py) każdy wpis crontaba
musi wysłać PRODUCTION_CRON_SECRET. Skrypt czyta go z config/core.json, a curl
dostaje nagłówek przez stdin, więc sekret nie ląduje ani w crontabie, ani
w argumentach procesu (widocznych w `ps`).

curl jest zaślepką zapisującą argumenty i stdin — żadnego ruchu sieciowego.
"""

import json
import os
import secrets
import shutil
import stat
import subprocess
import sys

import pytest


KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKRYPT = os.path.join(KORZEN, 'scripts', 'cron_endpoint.sh')
SH = shutil.which('sh')

pytestmark = pytest.mark.skipif(
    SH is None or sys.platform.startswith('win'),
    reason='skrypt crona uruchamiamy tylko pod sh na Linuksie (kontener testów)',
)

ZASLEPKA_CURL = r'''#!/bin/sh
printf '%s\n' "$@" > "$ARGUMENTY"
cat > "$WEJSCIE"
printf '{"success": true}\n%s' "$KOD_HTTP"
'''


@pytest.fixture()
def srodowisko(tmp_path):
    zaslepki = tmp_path / 'bin'
    zaslepki.mkdir()
    curl = zaslepki / 'curl'
    curl.write_text(ZASLEPKA_CURL, encoding='utf-8', newline='\n')
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (tmp_path / 'app' / 'config').mkdir(parents=True)
    return tmp_path


def _core_json(srodowisko, **pola):
    (srodowisko / 'app' / 'config' / 'core.json').write_text(json.dumps(pola), encoding='utf-8')


def _uruchom(srodowisko, *argumenty, kod_http='200'):
    env = dict(os.environ)
    env.update({
        'PATH': f"{srodowisko / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}",
        'KATALOG_APLIKACJI': str(srodowisko / 'app'),
        'ADRES': 'https://crm.example.test',
        'ARGUMENTY': str(srodowisko / 'argumenty.txt'),
        'WEJSCIE': str(srodowisko / 'wejscie.txt'),
        'KOD_HTTP': kod_http,
    })
    return subprocess.run([SH, SKRYPT, *argumenty], env=env,
                          capture_output=True, text=True, timeout=30)


def _curl_wywolany(srodowisko):
    return (srodowisko / 'argumenty.txt').exists()


def test_sekret_idzie_przez_stdin_a_nie_w_argumentach(srodowisko):
    sekret = secrets.token_hex(32)
    _core_json(srodowisko, PRODUCTION_CRON_SECRET=sekret)

    wynik = _uruchom(srodowisko, 'GET', '/production/api/sync-cron')

    assert wynik.returncode == 0, wynik.stderr
    argumenty = (srodowisko / 'argumenty.txt').read_text(encoding='utf-8').splitlines()
    wejscie = (srodowisko / 'wejscie.txt').read_text(encoding='utf-8')
    assert 'https://crm.example.test/production/api/sync-cron' in argumenty
    assert argumenty[argumenty.index('-X') + 1] == 'GET'
    assert argumenty[argumenty.index('-H') + 1] == '@-'
    assert wejscie == f'X-Cron-Secret: {sekret}\n'
    assert all(sekret not in a for a in argumenty)
    # Ani w logu, ani na stderr.
    assert sekret not in wynik.stdout and sekret not in wynik.stderr
    assert 'OK' in wynik.stdout


@pytest.mark.parametrize('pola', [
    {},
    {'PRODUCTION_CRON_SECRET': ''},
    {'PRODUCTION_CRON_SECRET': '   '},
    {'PRODUCTION_CRON_SECRET': None},
])
def test_brak_sekretu_konczy_sie_bledem_bez_zapytania(srodowisko, pola):
    _core_json(srodowisko, **pola)

    wynik = _uruchom(srodowisko, 'GET', '/production/api/sync-cron')

    assert wynik.returncode == 1
    assert 'PRODUCTION_CRON_SECRET' in wynik.stderr
    assert not _curl_wywolany(srodowisko)


def test_brak_pliku_konfiguracji_konczy_sie_bledem(srodowisko):
    wynik = _uruchom(srodowisko, 'GET', '/production/api/sync-cron')

    assert wynik.returncode == 1
    assert not _curl_wywolany(srodowisko)


def test_odpowiedz_inna_niz_200_to_blad(srodowisko):
    _core_json(srodowisko, PRODUCTION_CRON_SECRET=secrets.token_hex(32))

    wynik = _uruchom(srodowisko, 'GET', '/reports/api/cron/sync-statuses', kod_http='403')

    assert wynik.returncode == 1
    assert 'HTTP 403' in wynik.stderr


def test_bez_argumentow_pokazuje_uzycie(srodowisko):
    _core_json(srodowisko, PRODUCTION_CRON_SECRET=secrets.token_hex(32))

    wynik = _uruchom(srodowisko)

    assert wynik.returncode == 1
    assert 'Użycie' in wynik.stderr
    assert not _curl_wywolany(srodowisko)
