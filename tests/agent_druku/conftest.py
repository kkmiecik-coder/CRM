"""Pakiet agenta druku v2 leży w tools/agent_druku — dodajemy go do ścieżki importu."""
import os
import sys

_KATALOG_AGENTA = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'agent_druku'))
if _KATALOG_AGENTA not in sys.path:
    sys.path.insert(0, _KATALOG_AGENTA)
