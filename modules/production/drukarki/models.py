# -*- coding: utf-8 -*-
"""Modele agenta druku v2. Token agenta jest w bazie wyłącznie jako SHA-256 (pokazywany raz przy parowaniu)."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text

from extensions import db


class PrintAgent(db.Model):
    __tablename__ = 'prod_print_agents'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    token_sha256 = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = Column(Integer, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    version = Column(String(40), nullable=True)
    # JSON: stan każdej drukarki zgłoszony przez agenta.
    printers_state = Column(Text, nullable=True)
    push_connected = Column(Boolean, nullable=False, default=False, server_default='0')


class PrintAgentConfig(db.Model):
    __tablename__ = 'prod_print_agent_config'

    agent_id = Column(Integer, ForeignKey('prod_print_agents.id', ondelete='CASCADE'), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    data = Column(Text, nullable=False)  # JSON
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_source = Column(Enum('crm', 'agent', name='print_agent_config_source'), nullable=False, default='crm')
    updated_by = Column(String(100), nullable=True)


class PrintAgentConfigChange(db.Model):
    __tablename__ = 'prod_print_agent_config_changes'
    __table_args__ = (Index('ix_prod_print_agent_config_changes_agent', 'agent_id', 'id'),)

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey('prod_print_agents.id', ondelete='CASCADE'), nullable=False)
    version = Column(Integer, nullable=False)
    base_version = Column(Integer, nullable=True)
    source = Column(Enum('crm', 'agent', name='print_agent_config_change_source'), nullable=False)
    actor = Column(String(100), nullable=True)
    data_before = Column(Text, nullable=True)
    data_after = Column(Text, nullable=True)
    overwrote_version = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PrintAgentCommand(db.Model):
    __tablename__ = 'prod_print_agent_commands'
    __table_args__ = (Index('ix_prod_print_agent_commands_agent_status', 'agent_id', 'status'),)

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey('prod_print_agents.id', ondelete='CASCADE'), nullable=False)
    kind = Column(Enum('kalibracja', name='print_agent_command_kind'), nullable=False)
    printer = Column(String(20), nullable=False)
    status = Column(Enum('pending', 'done', 'failed', name='print_agent_command_status'),
                    nullable=False, default='pending')
    result = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    done_at = Column(DateTime, nullable=True)


class PrintAgentRelease(db.Model):
    """Wydanie agenta (plik trzymany poza repo), wzór MobileAppRelease; is_active=False = wycofane."""
    __tablename__ = 'prod_print_agent_releases'

    id = Column(Integer, primary_key=True)
    version_name = Column(String(20), nullable=False, unique=True)
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    release_notes = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    uploaded_by_user_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    @classmethod
    def latest_active(cls):
        """Najnowsze aktywne wydanie (wg numeru wersji, nie id) albo None; deleguje do serwisu wydań."""
        from modules.production.drukarki.services import wydania  # import lokalny: serwis importuje ten moduł
        return wydania.najnowsze()
