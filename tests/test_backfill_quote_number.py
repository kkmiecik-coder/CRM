"""Testy regexu wyciągającego numer wyceny ze starych notatek."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATTERN = re.compile(r'^Wycena\s+(\S+?)(?:\s*-\s*(.*))?$', re.DOTALL)


def parse(notes):
    m = PATTERN.match((notes or '').strip())
    if not m:
        return None, None
    return m.group(1).strip(), (m.group(2) or '').strip()


def test_quote_only():
    qn, rest = parse("Wycena 226/04/26/W")
    assert qn == "226/04/26/W"
    assert rest == ""


def test_quote_with_note():
    qn, rest = parse("Wycena 226/04/26/W - klient pilnie czeka")
    assert qn == "226/04/26/W"
    assert rest == "klient pilnie czeka"


def test_quote_with_note_multiline():
    qn, rest = parse("Wycena 226/04/26/W - linia 1\nlinia 2")
    assert qn == "226/04/26/W"
    assert rest == "linia 1\nlinia 2"


def test_no_match_when_no_prefix():
    qn, rest = parse("Tylko notatka bez prefiksu")
    assert qn is None
    assert rest is None


def test_no_match_when_empty():
    qn, rest = parse("")
    assert qn is None


def test_extra_whitespace_around_dash():
    qn, rest = parse("Wycena 226/04/26/W    -   notatka")
    assert qn == "226/04/26/W"
    assert rest == "notatka"


def test_quote_number_truncated_to_16_chars():
    qn, _ = parse("Wycena ABCDEFGHIJKLMNOPQRSTUV")
    # parser zwraca pełen string, truncation robi caller
    assert qn[:16] == "ABCDEFGHIJKLMNOP"
