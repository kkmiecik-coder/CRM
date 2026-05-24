"""Test buildera notatki użytkownika (po rozdzieleniu numeru wyceny)."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.baselinker.service import BaselinkerService


def _service():
    svc = BaselinkerService.__new__(BaselinkerService)
    svc.logger = MagicMock()
    return svc


def _quote(quote_number, notes):
    q = MagicMock()
    q.quote_number = quote_number
    q.notes = notes
    return q


def test_returns_only_notes_when_present():
    result = _service()._build_user_comments(_quote("226/04/26/W", "Pilne, klient czeka"))
    assert result == "Pilne, klient czeka"


def test_returns_empty_string_when_no_notes():
    result = _service()._build_user_comments(_quote("226/04/26/W", None))
    assert result == ""


def test_returns_empty_when_notes_whitespace_only():
    result = _service()._build_user_comments(_quote("226/04/26/W", "   "))
    assert result == ""


def test_truncates_notes_over_200_chars():
    long_note = "x" * 250
    result = _service()._build_user_comments(_quote("226/04/26/W", long_note))
    assert len(result) == 200
    assert result.endswith("...")


def test_does_not_include_quote_number_prefix():
    result = _service()._build_user_comments(_quote("226/04/26/W", "uwaga"))
    assert "Wycena" not in result
    assert "226/04/26/W" not in result
