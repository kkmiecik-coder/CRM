"""In-memory heartbeat tracking for station tablets."""
from datetime import datetime, timedelta

# In-memory store: { station_name: last_seen_datetime }
_station_heartbeats = {}

HEARTBEAT_TIMEOUT_SECONDS = 60


def record_heartbeat(station_name: str):
    """Record that a station tablet just checked in."""
    _station_heartbeats[station_name] = datetime.now()


def is_station_active(station_name: str) -> bool:
    """Check if station tablet has heartbeated within timeout."""
    last_seen = _station_heartbeats.get(station_name)
    if last_seen is None:
        return False
    return (datetime.now() - last_seen).total_seconds() < HEARTBEAT_TIMEOUT_SECONDS


def get_station_status(station_name: str) -> dict:
    """Get station heartbeat status for dashboard display."""
    last_seen = _station_heartbeats.get(station_name)
    active = is_station_active(station_name)
    return {
        'active': active,
        'last_seen': last_seen.isoformat() if last_seen else None,
        'status_label': 'Aktywne' if active else 'Niedostępne'
    }


def get_all_statuses() -> dict:
    """Get heartbeat status for all known stations."""
    station_names = ['cutting', 'assembly', 'completion', 'gluing', 'formatting', 'finishing', 'packaging']
    return {name: get_station_status(name) for name in station_names}
