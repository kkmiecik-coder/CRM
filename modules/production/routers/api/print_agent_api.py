"""
Dawne API starego agenta druku (`/api/print-agent/jobs`, `/ack`, `/realtime-token`) — wyłączone 23.10.2026.

Etykiety drukuje wyłącznie agent druku v2 (`modules/production/drukarki/routers/agent_api.py`, prefiks
`/api/print-agent/v2`, zakładka Drukarki w panelu produkcji). Blueprint zostaje zarejestrowany, żeby stary agent,
gdyby ktoś go jeszcze uruchomił, dostał czytelną odmowę 410 zamiast 404. Odmowa nie sprawdza tokenu i nie dotyka
bazy.
"""
from flask import Blueprint, jsonify

print_agent_bp = Blueprint('print_agent', __name__)

ODMOWA = {
    'error': 'stary_agent_wylaczony',
    'komunikat': 'Stary agent druku został wyłączony — etykiety drukuje nowy agent (zakładka Drukarki).',
}


def _odmowa():
    return jsonify(ODMOWA), 410


@print_agent_bp.route('/jobs', methods=['GET'])
def list_jobs():
    return _odmowa()


@print_agent_bp.route('/ack', methods=['POST'])
def ack_jobs():
    return _odmowa()


@print_agent_bp.route('/realtime-token', methods=['GET'])
def realtime_token():
    return _odmowa()
