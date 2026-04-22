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


def sync_commits(commits: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Główna logika sync. Filtruje, parsuje, tworzy ChangelogEntry + items + tracking.
    Idempotentna: wywołanie z tymi samymi SHA daje no-op.

    Args:
        commits: [{'sha': str, 'message': str}, ...]

    Returns:
        {'created': bool, 'version': str|None, 'items_count': int, 'skipped': int}

    Raises:
        RuntimeError przy braku SYSTEM_USER_ID w configu lub nieistniejącym userze.
    """
    from flask import current_app
    from extensions import db
    from ..models import ChangelogEntry, ChangelogItem, ChangelogSyncedCommit
    from ...calculator.models import User  # User jest w modules.calculator.models w tym projekcie

    if not commits:
        return {'created': False, 'version': None, 'items_count': 0, 'skipped': 0}

    # Walidacja systemowego usera
    config = current_app.config.get('CHANGELOG_SYNC', {})
    system_user_id = config.get('SYSTEM_USER_ID')
    if not system_user_id:
        raise RuntimeError('CHANGELOG_SYNC.SYSTEM_USER_ID nie ustawione w configu')

    system_user = User.query.get(system_user_id)
    if not system_user:
        raise RuntimeError(f'CHANGELOG_SYNC.SYSTEM_USER_ID={system_user_id} nie istnieje w users')

    all_input_shas = [c['sha'] for c in commits]

    # Filtr 1: pomijamy SHA już zsynchronizowane
    known_shas = set(
        row.commit_sha for row in
        ChangelogSyncedCommit.query.filter(
            ChangelogSyncedCommit.commit_sha.in_(all_input_shas)
        ).all()
    )
    new_commits = [c for c in commits if c['sha'] not in known_shas]
    skipped_known = len(commits) - len(new_commits)

    if not new_commits:
        logger.info(f'[changelog-sync] No-op: wszystkie {len(commits)} commitów już znane')
        return {'created': False, 'version': None, 'items_count': 0, 'skipped': skipped_known}

    # Filtr 2 + 3: parse + filter typów
    parsed_items = []  # [(commit, parsed_dict), ...]
    skipped_unparsable = 0
    skipped_filtered = 0
    for c in new_commits:
        parsed = parse_commit(c['message'])
        if parsed is None:
            skipped_unparsable += 1
            logger.warning(f"[changelog-sync] Pominięto nie-conventional: {c['sha'][:7]} '{c['message'][:60]}'")
            continue
        if parsed['type'] in SKIPPED_TYPES:
            skipped_filtered += 1
            continue
        if parsed['type'] not in TYPE_TO_SECTION:
            skipped_unparsable += 1
            logger.warning(f"[changelog-sync] Nieznany typ '{parsed['type']}' w {c['sha'][:7]}")
            continue
        parsed_items.append((c, parsed))

    total_skipped = skipped_known + skipped_unparsable + skipped_filtered

    if not parsed_items:
        # Mimo że nic do entry, zapisujemy SHA żeby nie przetwarzać ich ponownie
        try:
            for c in new_commits:
                db.session.add(ChangelogSyncedCommit(commit_sha=c['sha'], entry_id=None))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        logger.info(f'[changelog-sync] No entry created. Skipped: {total_skipped}')
        return {'created': False, 'version': None, 'items_count': 0, 'skipped': total_skipped}

    # Oblicz next version
    parsed_only = [p for _, p in parsed_items]
    next_version = compute_next_version(parsed_only)

    # Transakcja: utwórz entry + items + tracking
    try:
        entry = ChangelogEntry(
            version=next_version,
            is_visible=True,
            created_by=system_user_id,
        )
        db.session.add(entry)
        db.session.flush()  # żeby mieć entry.id

        for sort_order, (commit, parsed) in enumerate(parsed_items):
            section = TYPE_TO_SECTION[parsed['type']]
            scope_label = map_scope(parsed['scope'])
            text = f'[{scope_label}] {parsed["description"]}' if scope_label else parsed['description']
            db.session.add(ChangelogItem(
                entry_id=entry.id,
                section_type=section,
                item_text=text,
                sort_order=sort_order,
            ))

        # Wszystkie SHA z input (także odfiltrowane) → tracking
        for c in new_commits:
            db.session.add(ChangelogSyncedCommit(commit_sha=c['sha'], entry_id=entry.id))

        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('[changelog-sync] Błąd zapisu entry, rollback')
        raise

    logger.info(
        f'[changelog-sync] Utworzono v{next_version}: {len(parsed_items)} items, '
        f'skipped={total_skipped}'
    )
    return {
        'created': True,
        'version': next_version,
        'items_count': len(parsed_items),
        'skipped': total_skipped,
    }
