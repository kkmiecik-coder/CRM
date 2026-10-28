# -*- coding: utf-8 -*-
"""Koniec okresu przejściowego agenta druku (23.10.2026): stare API odpowiada 410, przełącznika obsługi nie ma,
sprzątanie kolejki siedzi w pakiecie drukarek, a migracja usuwa klucze starego agenta z prod_config."""
import os

import pytest
from flask import Flask

from migrations.migration_service import MigrationService
from modules.production.drukarki import stale
from modules.production.drukarki.services import agenci, kolejka
from modules.production.routers.api import print_agent_api

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRACJA = os.path.join(KORZEN, 'migrations', '2026-10-23-agent-druku-koniec-przejscia.sql')
KLUCZE_STAREGO = ('LABEL_PRINTER_AGENT_TOKEN', 'DRUKARKA_OBSLUGA_etykiety_OD', 'DRUKARKA_OBSLUGA_wysylka_OD',
                  'STARY_AGENT_OSTATNI_KONTAKT')
# Zostają w bazie do późniejszej migracji: stary kod w oknie wdrożenia czyta brak wiersza jako 'stary'.
KLUCZE_ZOSTAJA = ('DRUKARKA_OBSLUGA_etykiety', 'DRUKARKA_OBSLUGA_wysylka')
ODMOWA = {'error': 'stary_agent_wylaczony',
          'komunikat': 'Stary agent druku został wyłączony — etykiety drukuje nowy agent (zakładka Drukarki).'}


# ── stare API: 410 bez tokenu i bez bazy ──────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def stary_klient():
    """Goła apka bez SQLAlchemy: każdy dostęp do bazy w handlerze wywróciłby żądanie."""
    app = Flask(__name__)
    app.register_blueprint(print_agent_api.print_agent_bp, url_prefix='/api/print-agent')
    return app.test_client()


@pytest.mark.parametrize('metoda,sciezka', [('get', '/jobs'), ('get', '/jobs?limit=10&printers=etykiety'),
                                            ('post', '/ack'), ('get', '/realtime-token')])
@pytest.mark.parametrize('naglowki', [{}, {'Authorization': 'Bearer dawny-token'}], ids=['bez_tokenu', 'z_tokenem'])
def test_stare_api_odpowiada_410(stary_klient, metoda, sciezka, naglowki):
    r = getattr(stary_klient, metoda)('/api/print-agent' + sciezka, headers=naglowki,
                                      **({'json': {'results': [{'id': 1, 'success': True}]}} if metoda == 'post' else {}))
    assert r.status_code == 410
    assert r.get_json() == ODMOWA


def test_modul_starego_api_bez_logiki_starego_agenta():
    for nazwa in ('require_agent_token', '_get_agent_token', '_query_agent_token', '_drukarki_z_zapytania',
                  '_zmien_oczekujace', '_expire_stale_pending', '_zapisz_kontakt_starego', 'KLUCZ_OSTATNI_KONTAKT'):
        assert not hasattr(print_agent_api, nazwa), nazwa


def test_bez_przelacznika_obslugi():
    for nazwa in ('obsluga', 'ustaw_obsluge', 'oznacz_przelaczenie', 'przelaczanie_trwa', 'ma_drukarke',
                  'KLUCZ_OBSLUGI', 'KLUCZ_OBSLUGI_OD', 'OBSLUGA'):
        assert not hasattr(agenci, nazwa), nazwa
    assert not hasattr(stale, 'PRZELACZANIE_S')


# ── sprzątanie kolejki: throttling przeniesiony do kolejka.wygas_z_throttlingiem ─────────────────────────────────

@pytest.fixture()
def wywolania_wygas(monkeypatch):
    """Te testy pilnują throttle'u (JAK CZĘSTO sprzątanie rusza), nie tego, co zmienia — to robi kolejka.wygas."""
    wywolania = []

    def _wygas(teraz=None):
        wywolania.append(1)
        return {'claimed_do_pending': 0, 'sending_do_unknown': 0, 'expired': 0}

    monkeypatch.setattr(kolejka, 'wygas', _wygas)
    monkeypatch.setattr(kolejka, '_ostatnie_wygaszanie', None)
    return wywolania


def test_sprzatanie_nie_powtarza_sie_w_kolko(wywolania_wygas):
    """Agent woła /kontakt co kilka sekund, a TTL to godzina — sprzątanie przy każdym kontakcie to marnotrawstwo."""
    for _ in range(10):
        kolejka.wygas_z_throttlingiem()
    assert len(wywolania_wygas) == 1


def test_swiezy_worker_sprzata_od_razu(wywolania_wygas):
    """time.monotonic() bywa liczone od startu procesu — zero jako „dawno temu” uciszałoby pierwszą minutę."""
    assert kolejka.wygas_z_throttlingiem() == 0
    assert len(wywolania_wygas) == 1


def test_sprzatanie_po_uplywie_throttle(wywolania_wygas, monkeypatch):
    kolejka.wygas_z_throttlingiem()
    monkeypatch.setattr(kolejka, '_ostatnie_wygaszanie',
                        kolejka._ostatnie_wygaszanie - kolejka.ODSTEP_WYGASZANIA_S - 1)
    kolejka.wygas_z_throttlingiem()
    assert len(wywolania_wygas) == 2


def test_force_omija_throttle(wywolania_wygas):
    kolejka.wygas_z_throttlingiem()
    kolejka.wygas_z_throttlingiem(force=True)
    assert len(wywolania_wygas) == 2


# ── migracja ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_migracja_usuwa_klucze_starego_agenta():
    sql = open(MIGRACJA, encoding='utf-8').read()
    assert 'DELIMITER' not in sql
    instrukcje = MigrationService.split_statements(sql)
    assert len(instrukcje) == 1
    instrukcja = instrukcje[0]
    assert instrukcja.lstrip().startswith('DELETE FROM prod_config WHERE config_key IN')
    for klucz in KLUCZE_STAREGO:
        assert "'%s'" % klucz in instrukcja, klucz
    for klucz in KLUCZE_ZOSTAJA:
        assert "'%s'" % klucz not in instrukcja, klucz
    assert MigrationService(None)._match(os.path.basename(MIGRACJA))
