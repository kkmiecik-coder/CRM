# -*- coding: utf-8 -*-
"""Agenci druku v2: parowanie, tokeny, ostatni kontakt i przełącznik obsługi drukarki (okres przejściowy).

Token pokazujemy raz przy parowaniu; w bazie leży wyłącznie jego SHA-256. Czas „ostatniego kontaktu”
liczy zegar serwera. Funkcje nie commitują — commit należy do wołającego (router)."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from extensions import db
from modules.production.drukarki import stale
from modules.production.drukarki.models import PrintAgent, PrintAgentConfig
from modules.production.drukarki.services import konfiguracja
from modules.production.models import ProductionConfig

PREFIKS_TOKENU = 'wpa_'
KLUCZ_OBSLUGI = 'DRUKARKA_OBSLUGA_%s'
KLUCZ_OBSLUGI_OD = 'DRUKARKA_OBSLUGA_%s_OD'
OBSLUGA = ('stary', 'nowy')


def _skrot(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _nowy_token():
    return PREFIKS_TOKENU + secrets.token_urlsafe(32)


def sparuj(nazwa, user_id):
    """Zakłada agenta i jego konfigurację (wersja 1). Zwraca (agent, token jawny) — token tylko teraz."""
    token = _nowy_token()
    agent = PrintAgent(name=(nazwa or '').strip()[:100] or 'Agent druku', token_sha256=_skrot(token),
                       created_by_user_id=user_id)
    db.session.add(agent)
    db.session.flush()
    db.session.add(PrintAgentConfig(
        agent_id=agent.id, version=1, data=json.dumps(konfiguracja.domyslna(), ensure_ascii=False),
        updated_at=datetime.utcnow(), updated_source='crm', updated_by='user:%s' % user_id))
    db.session.flush()
    return agent, token


def agent_z_tokenu(token):
    """Agent nieunieważniony o tym tokenie albo None; porównanie skrótów stałoczasowe."""
    if not token or not isinstance(token, str):
        return None
    skrot = _skrot(token)
    agent = PrintAgent.query.filter(PrintAgent.token_sha256 == skrot, PrintAgent.revoked_at.is_(None)).first()
    if agent is None or not hmac.compare_digest(agent.token_sha256, skrot):
        return None
    return agent


def uniewaznij(agent_id, user_id):
    agent = PrintAgent.query.get(agent_id)
    if agent is not None and agent.revoked_at is None:
        agent.revoked_at = datetime.utcnow()
        db.session.flush()
    return agent


def nowy_token(agent_id, user_id):
    """Wymienia token agenta (stary przestaje działać od razu). Zwraca nowy token jawny."""
    agent = PrintAgent.query.get(agent_id)
    if agent is None or agent.revoked_at is not None:
        raise ValueError('Nie ma takiego aktywnego agenta.')
    token = _nowy_token()
    agent.token_sha256 = _skrot(token)
    db.session.flush()
    return token


def kontakt(agent, wersja, drukarki, push):
    agent.last_seen_at = datetime.utcnow()
    agent.version = (wersja or '')[:40] or None
    agent.printers_state = json.dumps(drukarki or [], ensure_ascii=False)
    agent.push_connected = bool(push)


def czy_online(agent, teraz=None):
    if agent is None or agent.last_seen_at is None:
        return False
    teraz = teraz or datetime.utcnow()
    return teraz - agent.last_seen_at <= timedelta(seconds=stale.AGENT_CISZA_S)


def _nazwy(lista):
    return {d.get('nazwa') for d in lista if isinstance(d, dict)} if isinstance(lista, list) else set()


def ma_drukarke(agent, drukarka):
    """True, gdy agent ma drukarkę w dokumencie konfiguracji w CRM I zgłosił ją w ostatnim /kontakt.

    Samo wpisanie w CRM nie wystarcza: agent pobiera zadania tylko drukarek ze swojej lokalnej konfiguracji,
    a zgłasza dokładnie te. Bez tego warunku przełączenie na „nowy” zostawiłoby etykiety bez odbiorcy."""
    if agent is None:
        return False
    konf = PrintAgentConfig.query.filter_by(agent_id=agent.id).first()
    try:
        w_konfiguracji = _nazwy(json.loads(konf.data).get('drukarki')) if konf is not None and konf.data else set()
    except (ValueError, AttributeError):
        w_konfiguracji = set()
    try:
        zgloszone = _nazwy(json.loads(agent.printers_state)) if agent.printers_state else set()
    except ValueError:
        zgloszone = set()
    return drukarka in w_konfiguracji and drukarka in zgloszone


def aktywny_v2():
    """Nieunieważniony agent, który kiedykolwiek się odezwał (o najświeższym kontakcie); inaczej None."""
    return (PrintAgent.query.filter(PrintAgent.revoked_at.is_(None), PrintAgent.last_seen_at.isnot(None))
            .order_by(PrintAgent.last_seen_at.desc(), PrintAgent.id.desc()).first())


def obsluga(drukarka):
    """'stary' albo 'nowy' — który agent obsługuje drukarkę. Czyta prod_config wprost (bez pamięci podręcznej)."""
    wiersz = ProductionConfig.query.filter_by(config_key=KLUCZ_OBSLUGI % drukarka).first()
    return 'nowy' if wiersz is not None and (wiersz.config_value or '').strip() == 'nowy' else 'stary'


def ustaw_obsluge(drukarka, wartosc, user_id):
    if drukarka not in stale.ROLE:
        raise ValueError('Nieznana drukarka: %s.' % drukarka)
    if wartosc not in OBSLUGA:
        raise ValueError('Obsługa drukarki: stary albo nowy.')
    klucz = KLUCZ_OBSLUGI % drukarka
    wiersz = ProductionConfig.query.filter_by(config_key=klucz).first()
    if wiersz is None:
        db.session.add(ProductionConfig(
            config_key=klucz, config_value=wartosc, config_type='string',
            config_description='Który agent druku obsługuje drukarkę %s (stary|nowy)' % drukarka))
    else:
        wiersz.config_value = wartosc
    db.session.flush()


def oznacz_przelaczenie(drukarka, teraz=None):
    """Zapisuje chwilę przełączenia drukarki na nowego agenta (zegar serwera, ISO UTC). Nie commituje."""
    klucz = KLUCZ_OBSLUGI_OD % drukarka
    wartosc = (teraz or datetime.utcnow()).isoformat()
    wiersz = ProductionConfig.query.filter_by(config_key=klucz).first()
    if wiersz is None:
        db.session.add(ProductionConfig(
            config_key=klucz, config_value=wartosc, config_type='string',
            config_description='Chwila przełączenia drukarki %s na nowego agenta (UTC, ISO)' % drukarka))
    else:
        wiersz.config_value = wartosc
    db.session.flush()


def przelaczanie_trwa(drukarka, teraz=None):
    """True, gdy od przełączenia drukarki na nowego agenta minęło mniej niż `stale.PRZELACZANIE_S` s."""
    wiersz = ProductionConfig.query.filter_by(config_key=KLUCZ_OBSLUGI_OD % drukarka).first()
    if wiersz is None or not (wiersz.config_value or '').strip():
        return False
    try:
        od = datetime.fromisoformat(wiersz.config_value.strip())
    except ValueError:
        return False
    return (teraz or datetime.utcnow()) - od < timedelta(seconds=stale.PRZELACZANIE_S)
