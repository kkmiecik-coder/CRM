"""
Synchronizacja widgetu changelog z GitHub.
Parsuje conventional commits z `git log`, mapuje na sekcje widgetu, tworzy ChangelogEntry.
"""

import re
import subprocess
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Regex Conventional Commits: type(scope)?: description
# Obsługuje breaking change przez "!" przed dwukropkiem.
_CONVENTIONAL_RE = re.compile(
    r'^(?P<type>[a-z]+)'
    r'(?:\((?P<scope>[a-z0-9_-]+)\))?'
    r'(?P<breaking>!)?'
    r':\s+'
    r'(?P<description>.+?)$',
    re.IGNORECASE
)


def parse_commit(message: str) -> Optional[dict]:
    """
    Parsuje pierwszą linię conventional commit message.

    Returns:
        dict z kluczami {'type', 'scope', 'description', 'breaking'} lub None jeśli nie pasuje.
        'breaking' = True jeśli użyto '!' lub w body jest 'BREAKING CHANGE:'.
        'scope' = '' jeśli brak.
    """
    if not message or not message.strip():
        return None

    # Pierwsza linia decyduje o typie/scope/opisie
    first_line = message.split('\n', 1)[0].strip()
    match = _CONVENTIONAL_RE.match(first_line)
    if not match:
        return None

    breaking = bool(match.group('breaking'))

    # Sprawdź też BREAKING CHANGE: w body (zgodnie ze standardem)
    if not breaking and 'BREAKING CHANGE:' in message:
        breaking = True

    return {
        'type': match.group('type').lower(),
        'scope': (match.group('scope') or '').lower(),
        'description': match.group('description').strip(),
        'breaking': breaking,
    }
