# -*- coding: utf-8 -*-
"""Wydania agenta druku (Task 5): zapis pliku, SHA-256, wersje X.Y.Z porównywane liczbowo."""
import hashlib
import io
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from extensions import db
from modules.production.drukarki import models as m_drukarki
from modules.production.drukarki.services import wydania
from tests.logistyka_fixtures import app  # noqa: F401


@pytest.fixture(autouse=True)
def _tabele(app, tmp_path):
    app.instance_path = str(tmp_path)
    db.metadata.create_all(bind=db.engine, tables=[m_drukarki.PrintAgentRelease.__table__])


def _plik(tresc=b'MZ-instalator'):
    return FileStorage(stream=io.BytesIO(tresc), filename='setup.exe')


def test_wgraj_liczy_sha_i_rozmiar(app):
    tresc = b'MZ' + b'x' * 5000
    r = wydania.wgraj(_plik(tresc), '2.0.1', ' notatki ', 3, True)
    assert r.id is not None and r.is_active is True
    assert r.sha256 == hashlib.sha256(tresc).hexdigest()
    assert r.file_size_bytes == len(tresc)
    assert r.file_path == 'agent_releases/agent-druku-2.0.1.exe'
    assert r.release_notes == 'notatki' and r.uploaded_by_user_id == 3
    assert wydania.sciezka_pliku(r).read_bytes() == tresc
    assert not [p for p in Path(app.instance_path, 'agent_releases').iterdir() if p.name.startswith('.upload')]


def test_domyslnie_nieaktywne_i_pomijane_przez_najnowsze(app):
    wydania.wgraj(_plik(), '1.0.0', '', 1, True)
    wydania.wgraj(_plik(), '1.1.0', '', 1, False)
    assert wydania.najnowsze().version_name == '1.0.0'


def test_wersja_porownywana_liczbowo(app):
    assert wydania.czy_nowsza('2.10.0', '2.9.0')
    assert not wydania.czy_nowsza('2.9.0', '2.10.0')
    assert not wydania.czy_nowsza('1.0.0', '1.0.0')
    wydania.wgraj(_plik(), '2.10.0', '', 1, True)
    wydania.wgraj(_plik(), '2.9.0', '', 1, True)  # wyższe id, niższa wersja
    assert wydania.najnowsze().version_name == '2.10.0'


def test_duplikat_wersji_odrzucony(app):
    wydania.wgraj(_plik(), '1.0.0', '', 1, True)
    with pytest.raises(ValueError, match='już istnieje'):
        wydania.wgraj(_plik(b'inny'), '1.0.0', '', 1, True)


@pytest.mark.parametrize('zla', ['1.0', 'v1.0.0', '1.0.0-beta', '', '1.0.0.0'])
def test_zly_format_wersji(app, zla):
    with pytest.raises(ValueError):
        wydania.wgraj(_plik(), zla, '', 1, True)


def test_pusty_plik_odrzucony_bez_sladu(app):
    with pytest.raises(ValueError, match='pusty'):
        wydania.wgraj(_plik(b''), '1.0.0', '', 1, True)
    assert list(Path(app.instance_path, 'agent_releases').iterdir()) == []


def test_blad_bazy_usuwa_plik(app, monkeypatch):
    def pada():
        raise RuntimeError('baza')
    monkeypatch.setattr(db.session, 'flush', pada)
    with pytest.raises(RuntimeError):
        wydania.wgraj(_plik(), '1.0.0', '', 1, True)
    db.session.rollback()
    assert list(Path(app.instance_path, 'agent_releases').iterdir()) == []


def test_najnowsze_puste(app):
    assert wydania.najnowsze() is None
