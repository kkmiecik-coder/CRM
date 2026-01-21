"""
System automatycznych migracji bazy danych.

Migracje są wykonywane automatycznie przy starcie aplikacji.
Każda migracja jest wykonywana tylko raz (śledzone w tabeli schema_migrations).

Konwencja nazewnictwa:
- SQL: 001_nazwa_migracji.sql
- Python: 001_nazwa_migracji.py (musi mieć funkcję run_migration())

Numeracja musi być sekwencyjna (001, 002, 003...).
"""

from .migration_service import MigrationService

__all__ = ['MigrationService']
