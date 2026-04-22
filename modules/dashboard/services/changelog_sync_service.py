"""
Synchronizacja widgetu changelog z GitHub.
Parsuje conventional commits z `git log`, mapuje na sekcje widgetu, tworzy ChangelogEntry.
"""

import re
import subprocess
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

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


# Typ commita → sekcja widgetu (klucz section_type w ChangelogItem)
TYPE_TO_SECTION = {
    'feat': 'added',
    'fix': 'fixed',
    'style': 'improved',
    'perf': 'improved',
}

# Typy które są pomijane (nie trafiają do widgetu)
SKIPPED_TYPES = {'chore', 'docs', 'ci', 'build', 'test', 'refactor'}

# Scope → polska nazwa modułu w prefixie [Moduł]
SCOPE_LABELS = {
    'production': 'Produkcja',
    'clients': 'Klienci',
    'calculator': 'Wycena',
    'quotes': 'Oferty',
    'packaging': 'Pakowanie',
    'edge': 'Wykończenie',
    'finish': 'Wykończenie',
    'auth': 'Logowanie',
    'dashboard': 'Dashboard',
    'users': 'Użytkownicy',
}


def map_scope(scope: str) -> str:
    """Mapuje scope na czytelną nazwę modułu. Pusty scope → pusty string."""
    if not scope:
        return ''
    return SCOPE_LABELS.get(scope.lower(), scope.capitalize())


def _bump_version(version: str, level: str) -> str:
    """Bumpuje wersję semver. level ∈ {'major','minor','patch'}."""
    parts = [int(x) for x in version.split('.')]
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts[0], parts[1], parts[2]

    if level == 'major':
        return f'{major + 1}.0.0'
    if level == 'minor':
        return f'{major}.{minor + 1}.0'
    if level == 'patch':
        return f'{major}.{minor}.{patch + 1}'
    raise ValueError(f'Nieznany poziom bump: {level}')


def compute_next_version(parsed_commits: List[Dict[str, Any]]) -> str:
    """
    Oblicza następną wersję na podstawie najwyższego typu w paczce.

    parsed_commits: lista dict-ów z parse_commit() (po filtracji typów pomijanych).
    Zwraca string typu '1.5.1'. Obsługuje konflikt — jeśli wersja zajęta, próbuje patcha.
    """
    from ..models import ChangelogEntry

    has_breaking = any(c['breaking'] for c in parsed_commits)
    has_feat = any(c['type'] == 'feat' for c in parsed_commits)

    if has_breaking:
        level = 'major'
    elif has_feat:
        level = 'minor'
    else:
        level = 'patch'

    # Znajdź najnowszą wersję (numerycznie, nie alfabetycznie)
    all_entries = ChangelogEntry.query.all()
    if not all_entries:
        latest_version = '0.0.0'
    else:
        # Sortowanie po (major, minor, patch) numerycznie
        def key(e):
            parts = [int(x) for x in e.version.split('.')]
            while len(parts) < 3:
                parts.append(0)
            return tuple(parts[:3])
        latest_version = max(all_entries, key=key).version

    candidate = _bump_version(latest_version, level)

    # Konflikt: jeśli kandydat istnieje, próbuj kolejnych patchy
    existing_versions = {e.version for e in all_entries}
    attempts = 0
    while candidate in existing_versions:
        attempts += 1
        if attempts > 100:
            raise RuntimeError(f'Nie znaleziono wolnej wersji po 100 próbach od {candidate}')
        candidate = _bump_version(candidate, 'patch')

    return candidate


def read_git_log(
    repo_path: str,
    rev_range: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict[str, str]]:
    """
    Czyta commity z git log używając subprocess.

    Args:
        repo_path: ścieżka do lokalnego repo (z REPO_PATH w configu)
        rev_range: zakres typu 'OLD..NEW'. Jeśli None, czyta wszystkie commity (z limitem).
        limit: maksymalna liczba commitów (np. 200). None = bez limitu.

    Returns:
        lista [{'sha': str, 'message': str}, ...] w kolejności od najnowszego.

    Raises:
        RuntimeError jeśli git log zawiedzie.
    """
    cmd = ['git', '-C', repo_path, 'log', '--no-merges', '--format=%H|%s']
    if rev_range:
        cmd.append(rev_range)
    if limit:
        cmd.append(f'-n{limit}')

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f'git log failed: {e.stderr.strip()}') from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f'git log timeout po 30s') from e
    except FileNotFoundError as e:
        raise RuntimeError(f'git binary nieznaleziony albo zły repo_path: {repo_path}') from e

    commits = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        sha, _, message = line.partition('|')
        if sha and message:
            commits.append({'sha': sha.strip(), 'message': message.strip()})

    return commits
