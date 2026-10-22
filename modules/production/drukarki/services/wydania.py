# -*- coding: utf-8 -*-
"""Wydania agenta druku (instalator .exe trzymany w instance/agent_releases/, wzór: APK tabletów)."""
import hashlib
import os
import re
import secrets
from pathlib import Path

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from modules.production.drukarki.models import PrintAgentRelease

KATALOG = 'agent_releases'
MAKS_ROZMIAR_B = 200 * 1024 * 1024
_WZOR_WERSJI = re.compile(r'^\d+\.\d+\.\d+$')


def _krotka(wersja: str):
    if not isinstance(wersja, str) or not _WZOR_WERSJI.match(wersja):
        raise ValueError(f'Wersja musi mieć format X.Y.Z (otrzymano: {wersja!r})')
    return tuple(int(c) for c in wersja.split('.'))


def czy_nowsza(a: str, b: str) -> bool:
    """True, gdy wersja a jest wyższa od b (porównanie liczbowe, nie tekstowe)."""
    return _krotka(a) > _krotka(b)


def najnowsze():
    """Aktywne wydanie o najwyższej wersji (krotka liczb) albo None; błąd bazy nie wywraca pytania agenta."""
    try:
        aktywne = PrintAgentRelease.query.filter_by(is_active=True).all()
    except SQLAlchemyError:
        db.session.rollback()
        return None
    najlepsze = None
    for r in aktywne:
        try:
            k = _krotka(r.version_name)
        except ValueError:
            continue  # wiersz spoza formatu nie bierze udziału w porównaniu
        if najlepsze is None or k > najlepsze[0]:
            najlepsze = (k, r)
    return najlepsze[1] if najlepsze else None


def sciezka_pliku(release: PrintAgentRelease) -> Path:
    return Path(current_app.instance_path) / release.file_path


def wgraj(plik, wersja: str, notatki: str, user_id: int, aktywuj: bool = False) -> PrintAgentRelease:
    """Zapisuje instalator i rejestruje wydanie (flush, bez commitu). ValueError dla błędów walidacji."""
    wersja = (wersja or '').strip()
    _krotka(wersja)
    if plik is None or not getattr(plik, 'filename', None):
        raise ValueError('Brak pliku instalatora')
    if PrintAgentRelease.query.filter_by(version_name=wersja).first() is not None:
        raise ValueError(f'Wersja {wersja} już istnieje')

    katalog = Path(current_app.instance_path) / KATALOG
    katalog.mkdir(parents=True, exist_ok=True)
    nazwa = f'agent-druku-{wersja}.exe'
    docelowa = katalog / nazwa
    if docelowa.exists():
        raise ValueError(f'Plik {nazwa} już istnieje na dysku, sprawdź katalog ręcznie')

    tmp = katalog / f'.upload-{secrets.token_hex(8)}.exe'
    try:
        plik.save(str(tmp))
        rozmiar = tmp.stat().st_size
        if rozmiar == 0:
            raise ValueError('Plik instalatora jest pusty')
        if rozmiar > MAKS_ROZMIAR_B:
            raise ValueError(f'Plik instalatora ({rozmiar} B) przekracza limit {MAKS_ROZMIAR_B} B')
        h = hashlib.sha256()
        with open(tmp, 'rb') as f:
            for blok in iter(lambda: f.read(1024 * 1024), b''):
                h.update(blok)
        os.replace(str(tmp), str(docelowa))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    release = PrintAgentRelease(
        version_name=wersja, file_path=f'{KATALOG}/{nazwa}', file_size_bytes=rozmiar,
        sha256=h.hexdigest(), release_notes=(notatki or '').strip() or None,
        uploaded_by_user_id=user_id, is_active=bool(aktywuj))
    try:
        db.session.add(release)
        db.session.flush()
    except BaseException:
        docelowa.unlink(missing_ok=True)  # plik bez wiersza w bazie byłby sierotą
        raise
    return release
