# Device Heartbeat & Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać endpoint `POST /api/mobile/v1/devices/heartbeat`, zapisywać telemetrię (bateria/temp/wersja/IP) do `prod_devices`, i wyświetlać dane przy kafelkach stanowisk w dashboardzie produkcji. Wycofać in-memory heartbeat (`station_heartbeat.py`).

**Architecture:** Tablet Android (`crm_prod_app`, `HeartbeatWorker`) bije co 15 min do nowego endpointa Flask z JWT. Backend zapisuje pola na `ProductionDevice`. Helper `get_devices_telemetry()` czyta z DB i zasila template w 3 routerach. Próg "Aktywne" = ostatnie 20 min. DESYNC = APK starszy od max w flocie.

**Tech Stack:** Flask + SQLAlchemy + PyMySQL, Jinja2, Bootstrap 5 (istniejące tooltipy), FontAwesome (już używane).

**Spec:** `docs/superpowers/specs/2026-05-21-device-heartbeat-telemetry-design.md`

---

## File Structure

**Modify:**
- `modules/production/models.py` — dodać 5 kolumn telemetrii do `ProductionDevice`
- `modules/production/services/mobile_api_service.py` — nowy helper `get_devices_telemetry()` + funkcja walidująca payload heartbeat
- `modules/production/routers/mobile_api.py` — nowy route `POST /devices/heartbeat`
- `modules/production/routers/main_routers.py:126` — podmiana `get_all_statuses()` → `get_devices_telemetry()`
- `modules/production/routers/api/dashboard_api.py:843, 1060` — to samo
- `modules/production/templates/components/dashboard-tab-content.html` — dodać blok ikon telemetrii przy badge dla 6 stanowisk
- `modules/production/static/css/production-panel.css` — style `.il-station-telemetry` i `.tel-*`

**Delete:**
- `modules/production/services/station_heartbeat.py`

**Create (test):**
- `tests/test_device_telemetry.py` — unit testy dla `get_devices_telemetry()` i walidatora payload (pure functions, bez Flask app context)

**SQL (puszczane manualnie przez usera):**
- Plik `docs/superpowers/specs/2026-05-21-device-heartbeat-telemetry.sql` ze schematem ALTER

---

## Task 1: Migracja SQL (plik dla usera)

**Files:**
- Create: `docs/superpowers/specs/2026-05-21-device-heartbeat-telemetry.sql`

- [ ] **Step 1: Zapisz plik SQL z migracją**

```sql
-- 2026-05-21 Device Heartbeat & Telemetry
-- Dodaje kolumny telemetrii do prod_devices.
-- Reusujemy istniejące last_ip (VARCHAR(45)) i app_version (VARCHAR(32))
-- dla IP i app_version_name — nie dodajemy duplikatów.
-- User puszcza ręcznie przez phpMyAdmin PRZED deployem kodu
-- (lokalnie: woodpower_crm_local, prod: produkcyjna baza).

ALTER TABLE prod_devices
  ADD COLUMN last_heartbeat_at DATETIME NULL,
  ADD COLUMN last_battery_pct SMALLINT NULL,
  ADD COLUMN last_battery_charging BOOLEAN NULL,
  ADD COLUMN last_temperature_c FLOAT NULL,
  ADD COLUMN last_app_version_code INT NULL,
  ADD INDEX idx_prod_devices_last_heartbeat (last_heartbeat_at);
```

- [ ] **Step 2: Commit (sam plik SQL, bez puszczania)**

```bash
git add -f docs/superpowers/specs/2026-05-21-device-heartbeat-telemetry.sql
git commit -m "docs(production): SQL migracji heartbeata urządzeń"
```

- [ ] **Step 3: Poinformuj usera o puszczeniu SQL**

Wypisz do usera:
> Plik SQL gotowy: `docs/superpowers/specs/2026-05-21-device-heartbeat-telemetry.sql`. Puść go w phpMyAdmin lokalnie (woodpower_crm_local) przed kolejnymi taskami. Na prod puścimy przed deployem — zgodnie z `feedback_db_operations.md`.

Czekaj na potwierdzenie usera, że lokalna migracja przeszła.

---

## Task 2: Dodanie kolumn do modelu `ProductionDevice`

**Files:**
- Modify: `modules/production/models.py:856-873`

- [ ] **Step 1: Dodaj kolumny do modelu**

W klasie `ProductionDevice`, **po linii** `is_active = Column(Boolean, ...)` (~linia 873), wstaw:

```python
    last_heartbeat_at = Column(DateTime, nullable=True, index=True)
    last_battery_pct = Column(SmallInteger, nullable=True)
    last_battery_charging = Column(Boolean, nullable=True)
    last_temperature_c = Column(Float, nullable=True)
    last_app_version_code = Column(Integer, nullable=True)
```

- [ ] **Step 2: Upewnij się że importy są kompletne**

Sprawdź na górze `modules/production/models.py` że są zaimportowane:
- `SmallInteger`, `Float` z `sqlalchemy`
- `Integer`, `DateTime`, `Boolean` (już są)

Jeśli `SmallInteger` lub `Float` brakuje, dodaj do existing `from sqlalchemy import ...`.

- [ ] **Step 3: Smoke test importu**

Run:
```bash
python3 -c "from modules.production.models import ProductionDevice; print([c.name for c in ProductionDevice.__table__.columns if 'last_' in c.name or 'battery' in c.name or 'temperature' in c.name or 'app_version' in c.name])"
```

Expected output zawiera:
`['last_ip', 'last_seen_at', 'app_version', 'last_heartbeat_at', 'last_battery_pct', 'last_battery_charging', 'last_temperature_c', 'last_app_version_code']`

- [ ] **Step 4: Commit**

```bash
git add modules/production/models.py
git commit -m "feat(production): kolumny telemetrii na ProductionDevice"
```

---

## Task 3: Walidator payload heartbeat (pure function + test)

**Files:**
- Modify: `modules/production/services/mobile_api_service.py` (dopisać funkcję)
- Create: `tests/test_device_telemetry.py`

Ten task wyciąga walidację do osobnej pure funkcji, żeby dało się ją testować unit bez Flask context.

- [ ] **Step 1: Napisz failing test**

Utwórz `tests/test_device_telemetry.py`:

```python
"""Testy telemetrii urządzeń produkcyjnych."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services.mobile_api_service import validate_heartbeat_payload


def test_validate_heartbeat_ok():
    err = validate_heartbeat_payload({
        'battery_pct': 87,
        'battery_charging': True,
        'temperature_c': 32.5,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
        'ip_address': '192.168.33.7',
    })
    assert err is None


def test_validate_heartbeat_battery_out_of_range():
    err = validate_heartbeat_payload({
        'battery_pct': 150,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'battery_pct out of range'


def test_validate_heartbeat_battery_negative():
    err = validate_heartbeat_payload({
        'battery_pct': -1,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'battery_pct out of range'


def test_validate_heartbeat_battery_null_ok():
    err = validate_heartbeat_payload({
        'battery_pct': None,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err is None


def test_validate_heartbeat_temperature_out_of_range():
    err = validate_heartbeat_payload({
        'temperature_c': 999,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'temperature_c out of range'


def test_validate_heartbeat_temperature_negative_extreme():
    err = validate_heartbeat_payload({
        'temperature_c': -50,
        'app_version_code': 16,
        'app_version_name': '1.0.15',
    })
    assert err == 'temperature_c out of range'


def test_validate_heartbeat_missing_app_version_code():
    err = validate_heartbeat_payload({
        'app_version_name': '1.0.15',
    })
    assert err == 'app_version_code required'


def test_validate_heartbeat_missing_app_version_name():
    err = validate_heartbeat_payload({
        'app_version_code': 16,
    })
    assert err == 'app_version_name required'
```

- [ ] **Step 2: Uruchom test — ma fail z ImportError**

Run:
```bash
python3 -m pytest tests/test_device_telemetry.py -v
```

Expected: ImportError (`validate_heartbeat_payload` nie istnieje).

- [ ] **Step 3: Dopisz funkcję `validate_heartbeat_payload` w `mobile_api_service.py`**

Dodaj **przed** sekcją `# DEKORATOR` (czyli ~przed linią 218), w odrębnym bloku:

```python
# ============================================================================
# HEARTBEAT — walidacja payloadu
# ============================================================================

def validate_heartbeat_payload(payload):
    """
    Waliduje payload heartbeata urządzenia. Zwraca None gdy OK, lub
    krótki string z opisem błędu (do umieszczenia w response).

    Pure function — bez Flask context, bez DB. Testowalna unit.
    """
    battery_pct = payload.get('battery_pct')
    if battery_pct is not None:
        if not isinstance(battery_pct, int) or not (0 <= battery_pct <= 100):
            return 'battery_pct out of range'

    temp = payload.get('temperature_c')
    if temp is not None:
        if not isinstance(temp, (int, float)) or not (-20.0 <= temp <= 100.0):
            return 'temperature_c out of range'

    if 'app_version_code' not in payload or payload.get('app_version_code') is None:
        return 'app_version_code required'
    if not isinstance(payload['app_version_code'], int):
        return 'app_version_code required'

    name = payload.get('app_version_name')
    if not name or not isinstance(name, str):
        return 'app_version_name required'

    return None
```

- [ ] **Step 4: Uruchom test — ma pass**

Run:
```bash
python3 -m pytest tests/test_device_telemetry.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add modules/production/services/mobile_api_service.py tests/test_device_telemetry.py
git commit -m "feat(production): walidator payloadu heartbeat + testy"
```

---

## Task 4: Helper `get_devices_telemetry()` (pure-ish + test)

**Files:**
- Modify: `modules/production/services/mobile_api_service.py`
- Modify: `tests/test_device_telemetry.py`

Helper przyjmuje listę urządzeń jako argument (testowalność) plus thin wrapper który czyta z DB.

- [ ] **Step 1: Dopisz failing testy w `tests/test_device_telemetry.py`**

Na końcu pliku:

```python
from datetime import datetime, timedelta
from types import SimpleNamespace

from modules.production.services.mobile_api_service import build_devices_telemetry


def _make_device(station_code, **kw):
    """Lekki stub ProductionDevice — tylko atrybuty których używa helper."""
    defaults = dict(
        station_code=station_code,
        is_active=True,
        last_heartbeat_at=None,
        last_battery_pct=None,
        last_battery_charging=None,
        last_temperature_c=None,
        last_app_version_code=None,
        app_version=None,
        last_ip=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_telemetry_empty_fleet():
    """Brak urządzeń → wszystkie stanowiska Niedostępne."""
    result = build_devices_telemetry([], now=datetime(2026, 5, 21, 15, 0, 0))
    assert set(result.keys()) == {
        'cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging'
    }
    for code, status in result.items():
        assert status['active'] is False
        assert status['status_label'] == 'Niedostępne'
        assert status['last_heartbeat_at'] is None
        assert status['battery_pct'] is None
        assert status['apk_outdated'] is False


def test_telemetry_active_device():
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=2),
        last_battery_pct=87,
        last_battery_charging=True,
        last_temperature_c=32.5,
        last_app_version_code=16,
        app_version='1.0.15',
        last_ip='192.168.33.7',
    )]
    result = build_devices_telemetry(devices, now=now)
    cutting = result['cutting']
    assert cutting['active'] is True
    assert cutting['status_label'] == 'Aktywne'
    assert cutting['battery_pct'] == 87
    assert cutting['battery_charging'] is True
    assert cutting['temperature_c'] == 32.5
    assert cutting['app_version_name'] == '1.0.15'
    assert cutting['app_version_code'] == 16
    assert cutting['ip_address'] == '192.168.33.7'
    assert cutting['apk_outdated'] is False


def test_telemetry_stale_device_inactive():
    """Heartbeat >20 min temu → status Niedostępne."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=25),
        last_battery_pct=50,
        last_app_version_code=16,
        app_version='1.0.15',
    )]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['active'] is False
    assert result['cutting']['status_label'] == 'Niedostępne'


def test_telemetry_threshold_boundary_19m59s_active():
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=19, seconds=59),
        last_app_version_code=16,
        app_version='1.0.15',
    )]
    assert build_devices_telemetry(devices, now=now)['cutting']['active'] is True


def test_telemetry_threshold_boundary_20m_inactive():
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [_make_device(
        'cutting',
        last_heartbeat_at=now - timedelta(minutes=20),
        last_app_version_code=16,
        app_version='1.0.15',
    )]
    assert build_devices_telemetry(devices, now=now)['cutting']['active'] is False


def test_telemetry_apk_outdated():
    """Tablet z niższym version_code niż max w flocie = outdated."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=16, app_version='1.0.15'),
        _make_device('assembly',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=15, app_version='1.0.14'),
    ]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['apk_outdated'] is False
    assert result['assembly']['apk_outdated'] is True


def test_telemetry_multiple_devices_per_station_uses_freshest():
    """Gdy 2 tablety na stanowisku, używamy tego ze świeższym heartbeat."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=10),
            last_battery_pct=50,
            last_app_version_code=16, app_version='1.0.15'),
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_battery_pct=90,
            last_app_version_code=16, app_version='1.0.15'),
    ]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['battery_pct'] == 90


def test_telemetry_inactive_device_excluded_from_fleet_max():
    """is_active=False urządzenia nie liczą się do max APK floty."""
    now = datetime(2026, 5, 21, 15, 0, 0)
    devices = [
        _make_device('cutting',
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=16, app_version='1.0.15'),
        _make_device('assembly',
            is_active=False,
            last_heartbeat_at=now - timedelta(minutes=2),
            last_app_version_code=99, app_version='9.9.9'),
    ]
    result = build_devices_telemetry(devices, now=now)
    assert result['cutting']['apk_outdated'] is False
```

- [ ] **Step 2: Uruchom testy — fail (ImportError `build_devices_telemetry`)**

Run:
```bash
python3 -m pytest tests/test_device_telemetry.py -v
```

Expected: ImportError przy nowych testach, stare przechodzą.

- [ ] **Step 3: Dopisz `build_devices_telemetry` i `get_devices_telemetry` w `mobile_api_service.py`**

Dodaj **przed** `validate_heartbeat_payload` (czyli na początku sekcji HEARTBEAT):

```python
# ============================================================================
# HEARTBEAT — agregacja telemetrii dla dashboardu
# ============================================================================

HEARTBEAT_ACTIVE_THRESHOLD_MINUTES = 20

_STATION_CODES_WITH_TABLETS = (
    'cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging'
)


def build_devices_telemetry(devices, now=None):
    """
    Buduje słownik telemetrii per station_code z listy ProductionDevice.

    Pure function — testowalna z stubami (SimpleNamespace).
    `devices`: iterable obiektów z atrybutami modelu ProductionDevice.
    `now`: datetime do liczenia progu (testowalność); default = get_local_now().

    Reguły:
    - Tylko is_active=True urządzenia są brane pod uwagę (fleet max APK i mapping).
    - Gdy >1 urządzenie na station_code, bierzemy to z najświeższym last_heartbeat_at.
    - Próg `active`: heartbeat w ciągu ostatnich 20 min.
    - `apk_outdated`: tablet z last_app_version_code < max(last_app_version_code)
      ze wszystkich aktywnych urządzeń.
    """
    if now is None:
        now = get_local_now()

    active_devices = [d for d in devices if getattr(d, 'is_active', True)]

    fleet_max_apk = None
    for d in active_devices:
        v = getattr(d, 'last_app_version_code', None)
        if v is not None and (fleet_max_apk is None or v > fleet_max_apk):
            fleet_max_apk = v

    # Najświeższe urządzenie per station_code
    per_station = {}
    for d in active_devices:
        sc = getattr(d, 'station_code', None)
        if sc not in _STATION_CODES_WITH_TABLETS:
            continue
        current = per_station.get(sc)
        if current is None:
            per_station[sc] = d
            continue
        d_hb = getattr(d, 'last_heartbeat_at', None)
        c_hb = getattr(current, 'last_heartbeat_at', None)
        if d_hb and (c_hb is None or d_hb > c_hb):
            per_station[sc] = d

    threshold = timedelta(minutes=HEARTBEAT_ACTIVE_THRESHOLD_MINUTES)

    result = {}
    for code in _STATION_CODES_WITH_TABLETS:
        d = per_station.get(code)
        if d is None:
            result[code] = {
                'active': False,
                'status_label': 'Niedostępne',
                'last_heartbeat_at': None,
                'battery_pct': None,
                'battery_charging': None,
                'temperature_c': None,
                'app_version_name': None,
                'app_version_code': None,
                'ip_address': None,
                'apk_outdated': False,
            }
            continue

        last_hb = getattr(d, 'last_heartbeat_at', None)
        active = bool(last_hb and (now - last_hb) < threshold)
        apk_code = getattr(d, 'last_app_version_code', None)
        apk_outdated = bool(
            fleet_max_apk and apk_code and apk_code < fleet_max_apk
        )

        result[code] = {
            'active': active,
            'status_label': 'Aktywne' if active else 'Niedostępne',
            'last_heartbeat_at': last_hb.isoformat() if last_hb else None,
            'battery_pct': getattr(d, 'last_battery_pct', None),
            'battery_charging': getattr(d, 'last_battery_charging', None),
            'temperature_c': getattr(d, 'last_temperature_c', None),
            'app_version_name': getattr(d, 'app_version', None),
            'app_version_code': apk_code,
            'ip_address': getattr(d, 'last_ip', None),
            'apk_outdated': apk_outdated,
        }

    return result


def get_devices_telemetry():
    """
    Thin wrapper — pobiera urządzenia z DB i deleguje do build_devices_telemetry.
    Wywoływane z routerów dashboardu.
    """
    devices = ProductionDevice.query.all()
    return build_devices_telemetry(devices)
```

Upewnij się że na górze pliku jest import `from datetime import datetime, timedelta` (zazwyczaj jest — sprawdź i dodaj `timedelta` jeśli brakuje).

- [ ] **Step 4: Uruchom testy — wszystkie pass**

Run:
```bash
python3 -m pytest tests/test_device_telemetry.py -v
```

Expected: 16 passed (8 z walidatora + 8 z helpera).

- [ ] **Step 5: Commit**

```bash
git add modules/production/services/mobile_api_service.py tests/test_device_telemetry.py
git commit -m "feat(production): helper build_devices_telemetry z DB + testy"
```

---

## Task 5: Endpoint `POST /api/mobile/v1/devices/heartbeat`

**Files:**
- Modify: `modules/production/routers/mobile_api.py`

- [ ] **Step 1: Dodaj endpoint na końcu pliku**

W `modules/production/routers/mobile_api.py`, po ostatnim endpoincie:

```python
@mobile_api_bp.route('/devices/heartbeat', methods=['POST'])
@require_device_token
def device_heartbeat():
    """
    Tablet wysyła co 15 min telemetrię (bateria/temp/wersja APK/IP).
    Brak idempotency — każdy heartbeat nadpisuje pola na ProductionDevice.
    """
    from modules.production.services.mobile_api_service import (
        validate_heartbeat_payload,
    )

    payload = request.get_json(silent=True) or {}
    err = validate_heartbeat_payload(payload)
    if err:
        return jsonify({'error': 'validation', 'detail': err}), 422

    device = g.device
    device.last_heartbeat_at = get_local_now()
    device.last_battery_pct = payload.get('battery_pct')
    device.last_battery_charging = payload.get('battery_charging')
    device.last_temperature_c = payload.get('temperature_c')
    device.last_app_version_code = payload['app_version_code']
    device.app_version = payload['app_version_name']
    ip_addr = payload.get('ip_address')
    if ip_addr:
        device.last_ip = ip_addr

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API: heartbeat commit failed", extra={
            'device_id': device.device_id,
            'station_code': device.station_code,
            'error': str(e),
        })
        return jsonify({'error': 'internal'}), 500

    logger.info("Mobile API: heartbeat OK", extra={
        'event': 'device_heartbeat',
        'device_id': device.device_id,
        'station_code': device.station_code,
        'battery_pct': payload.get('battery_pct'),
        'battery_charging': payload.get('battery_charging'),
        'temperature_c': payload.get('temperature_c'),
        'app_version_code': payload['app_version_code'],
        'app_version_name': payload['app_version_name'],
    })

    return '', 204
```

Upewnij się że importy w pliku zawierają (dodaj jeśli brak):
- `from flask import request, jsonify, g`
- `from extensions import db`
- `from modules.production.services.mobile_api_service import require_device_token, get_local_now`
- `logger` (istnieje już w pliku — sprawdź).

Sprawdź na górze pliku jakie nazwy faktycznie są zaimportowane (`grep -n "^from\|^import" modules/production/routers/mobile_api.py | head -20`) i uzupełnij tylko brakujące.

- [ ] **Step 2: Smoke test — endpoint odpowiada 401 bez tokena**

Najpierw upewnij się że Flask app stoi (`run_local.bat` na Windows lub odpowiednik). Z osobnego terminala:

```bash
curl -i -X POST http://127.0.0.1:5000/api/mobile/v1/devices/heartbeat \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected: `HTTP/1.1 401` z `{"error":"missing_token"}` lub `{"error":"ip_not_allowed"}` (zależnie od konfigu whitelisty IP — oba są OK na tym etapie, znaczą że route działa).

- [ ] **Step 3: Smoke test — endpoint zapisuje payload (z prawdziwym JWT)**

Wygeneruj JWT testowego device i puść payload. Skrypt do uruchomienia z katalogu repo:

```bash
python3 <<'PY'
from app import create_app
from extensions import db
from modules.production.models import ProductionDevice
from modules.production.services.mobile_api_service import (
    register_device, generate_token,
)

app = create_app()
with app.app_context():
    info = register_device(
        device_id='HEARTBEAT-TEST-001',
        device_name='Smoke Test',
        station_code='cutting',
    )
    device = ProductionDevice.query.filter_by(device_id='HEARTBEAT-TEST-001').first()
    token = generate_token(device)
    print(token)
PY
```

Zapisz token w zmiennej środowiskowej i puść heartbeat (na lokalu IP whitelist musi pozwalać na 127.0.0.1 — sprawdź `config/core.json`):

```bash
TOKEN="<wklej token>"
curl -i -X POST http://127.0.0.1:5000/api/mobile/v1/devices/heartbeat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "battery_pct": 87,
    "battery_charging": true,
    "temperature_c": 32.5,
    "app_version_code": 16,
    "app_version_name": "1.0.15",
    "ip_address": "192.168.33.7"
  }'
```

Expected: `HTTP/1.1 204 No Content`, body puste.

- [ ] **Step 4: Smoke test — payload zapisany w DB**

```bash
python3 <<'PY'
from app import create_app
from modules.production.models import ProductionDevice
app = create_app()
with app.app_context():
    d = ProductionDevice.query.filter_by(device_id='HEARTBEAT-TEST-001').first()
    print('heartbeat_at:', d.last_heartbeat_at)
    print('battery:', d.last_battery_pct, 'charging:', d.last_battery_charging)
    print('temp:', d.last_temperature_c)
    print('apk code:', d.last_app_version_code, 'name:', d.app_version)
    print('ip:', d.last_ip)
PY
```

Expected: wszystkie pola wypełnione (battery=87, temp=32.5, apk=16, name='1.0.15', ip='192.168.33.7').

- [ ] **Step 5: Smoke test — walidacja 422**

```bash
curl -i -X POST http://127.0.0.1:5000/api/mobile/v1/devices/heartbeat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"battery_pct": 150, "app_version_code": 16, "app_version_name": "1.0.15"}'
```

Expected: `HTTP/1.1 422` z body `{"error":"validation","detail":"battery_pct out of range"}`.

- [ ] **Step 6: Commit**

```bash
git add modules/production/routers/mobile_api.py
git commit -m "feat(production): endpoint POST /devices/heartbeat"
```

---

## Task 6: Wycofanie `station_heartbeat.py` i podmiana 3 callerów

**Files:**
- Delete: `modules/production/services/station_heartbeat.py`
- Modify: `modules/production/routers/main_routers.py` (~linia 126)
- Modify: `modules/production/routers/api/dashboard_api.py` (~linie 843, 1060)
- Sprawdź: czy `record_heartbeat` jest gdzieś jeszcze wołane

- [ ] **Step 1: Znajdź wszystkie referencje do `station_heartbeat`**

```bash
grep -rn "station_heartbeat\|record_heartbeat\|get_all_statuses" modules/ tests/ 2>/dev/null
```

Spisz wszystkie pliki które trzeba ruszyć — poza znanymi z planu mogą być dodatkowe miejsca wywołujące `record_heartbeat` (np. w `require_device_token` lub innych routerach).

- [ ] **Step 2: Podmień import i wywołanie w `main_routers.py:126`**

Pokaż kontekst:
```bash
sed -n '120,135p' modules/production/routers/main_routers.py
```

Zamień:
- `from modules.production.services.station_heartbeat import get_all_statuses` (lub podobny import) → `from modules.production.services.mobile_api_service import get_devices_telemetry`
- `get_all_statuses()` w linii ~126 → `get_devices_telemetry()`

- [ ] **Step 3: To samo w `dashboard_api.py:843`**

```bash
sed -n '835,850p' modules/production/routers/api/dashboard_api.py
```

Zamień import i wywołanie analogicznie.

- [ ] **Step 4: To samo w `dashboard_api.py:1060`**

```bash
sed -n '1055,1070p' modules/production/routers/api/dashboard_api.py
```

Zamień import (jeśli osobny) i wywołanie.

- [ ] **Step 5: Usuń pozostałe wywołania `record_heartbeat`**

Z grepu w Step 1 — każde wywołanie `record_heartbeat(...)` poza testami trzeba usunąć (telemetrię teraz pisze sam endpoint heartbeat). Jeśli jest np. w `require_device_token` — usuń linię. Imports również.

- [ ] **Step 6: Usuń plik `station_heartbeat.py`**

```bash
git rm modules/production/services/station_heartbeat.py
```

- [ ] **Step 7: Verify — brak referencji**

```bash
grep -rn "station_heartbeat\|record_heartbeat\|get_all_statuses" modules/ 2>/dev/null
```

Expected: pusto (lub tylko `get_all_statuses` w niezwiązanych kontekstach — sprawdź).

- [ ] **Step 8: Smoke test — Flask startuje**

Uruchom Flask (`python3 -m flask run` lub `run_local.bat`). Otwórz `http://127.0.0.1:5000/production/dashboard` (po zalogowaniu).

Expected: strona ładuje się bez ImportError, badge "Aktywne/Niedostępne" pokazuje stan z DB (Niedostępne dla wszystkich stanowisk poza tym z Task 5 smoke testu — to cutting będzie Aktywne dopóki heartbeat <20 min).

- [ ] **Step 9: Commit**

```bash
git add -A modules/production/
git commit -m "refactor(production): wycofanie station_heartbeat in-memory na rzecz DB"
```

---

## Task 7: UI — ikony telemetrii przy badge stanowisk

**Files:**
- Modify: `modules/production/templates/components/dashboard-tab-content.html`
- Modify: `modules/production/static/css/production-panel.css`

- [ ] **Step 1: Przeczytaj kontekst HTML stanowiska**

```bash
sed -n '20,55p' modules/production/templates/components/dashboard-tab-content.html
```

Zobacz jak wygląda kafelka pierwszego stanowiska (`cutting`) — zwłaszcza `<span class="il-station-badge ...">`.

- [ ] **Step 2: Stwórz Jinja macro do telemetrii**

Na samej górze pliku `modules/production/templates/components/dashboard-tab-content.html` dodaj macro:

```jinja
{% macro station_telemetry(tablet) %}
  {%- set active = tablet.active|default(false) -%}
  {%- set bp = tablet.battery_pct -%}
  {%- set bcharge = tablet.battery_charging -%}
  {%- set temp = tablet.temperature_c -%}
  {%- set vname = tablet.app_version_name -%}
  {%- set outdated = tablet.apk_outdated|default(false) -%}
  {%- set ip = tablet.ip_address -%}
  {%- set hb = tablet.last_heartbeat_at -%}

  {%- if bp is none or bp >= 20 -%}{% set bclass = 'tel-ok' %}
  {%- elif bp >= 10 -%}{% set bclass = 'tel-warn' %}
  {%- else -%}{% set bclass = 'tel-crit' %}{%- endif -%}
  {%- if bp is none -%}{% set bclass = 'tel-none' %}{%- endif -%}

  {%- if temp is none -%}{% set tclass = 'tel-none' %}
  {%- elif temp < 40 -%}{% set tclass = 'tel-ok' %}
  {%- elif temp <= 50 -%}{% set tclass = 'tel-warn' %}
  {%- else -%}{% set tclass = 'tel-crit' %}{%- endif -%}

  {%- if not vname -%}{% set aclass = 'tel-none' %}
  {%- elif outdated -%}{% set aclass = 'tel-desync' %}
  {%- else -%}{% set aclass = 'tel-ok' %}{%- endif -%}

  <span class="il-station-telemetry{% if not active %} il-station-telemetry--stale{% endif %}"
        data-bs-toggle="tooltip"
        data-bs-html="true"
        title="Heartbeat: {{ hb or '—' }}<br>Bateria: {{ bp if bp is not none else '—' }}{% if bp is not none %}%{% endif %}{% if bcharge %} (ładuje się){% endif %}<br>Temperatura: {{ temp if temp is not none else '—' }}{% if temp is not none %}°C{% endif %}<br>APK: {{ vname or '—' }}{% if tablet.app_version_code %} (vc{{ tablet.app_version_code }}){% endif %}<br>IP: {{ ip or '—' }}">
    <span class="tel-icon tel-battery {{ bclass }}">
      <i class="fas fa-battery-half"></i>
      <span class="tel-value">{{ bp if (active and bp is not none) else '—' }}{% if active and bp is not none %}%{% endif %}</span>
      {% if active and bcharge %}<i class="fas fa-bolt tel-charge"></i>{% endif %}
    </span>
    <span class="tel-icon tel-temp {{ tclass }}">
      <i class="fas fa-thermometer-half"></i>
      <span class="tel-value">{{ temp if (active and temp is not none) else '—' }}{% if active and temp is not none %}°C{% endif %}</span>
    </span>
    <span class="tel-icon tel-apk {{ aclass }}">
      <i class="fas fa-mobile-alt"></i>
      <span class="tel-value">{{ vname if active else '—' }}</span>
      {% if active and outdated %}<span class="tel-badge-desync">DESYNC</span>{% endif %}
    </span>
  </span>
{% endmacro %}
```

- [ ] **Step 3: Wstaw macro przy każdym z 6 stanowisk**

W każdym z 6 bloków stanowisk (cutting, assembly, gluing, formatting, finishing, packaging) **bezpośrednio po** zamknięciu `</span>` od `il-station-badge`, wstaw:

```jinja
{{ station_telemetry(dashboard_stats.stations.<CODE>.tablet_status) }}
```

Gdzie `<CODE>` to odpowiednio `cutting`, `assembly`, `gluing`, `formatting`, `finishing`, `packaging`.

Lokalizacje linii (mogą się minimalnie przesunąć po dodaniu macro u góry):
- cutting: po linii ~33 (po `il-station-badge ... cutting-tablet-badge`)
- assembly: po linii ~70
- gluing: po linii ~107
- formatting: po linii ~144
- finishing: po linii ~181
- packaging: po linii ~237

**Pomiń logistykę** (linia ~216) — nie ma tabletu.

- [ ] **Step 4: Dodaj style do `production-panel.css`**

Na końcu pliku `modules/production/static/css/production-panel.css`:

```css
/* ============================================================
   STATION TELEMETRY — ikony przy badge stanowiska
   ============================================================ */
.il-station-telemetry {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-left: 8px;
    font-size: 0.85rem;
    cursor: help;
}

.il-station-telemetry--stale .tel-icon {
    opacity: 0.45;
}

.tel-icon {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.04);
}

.tel-icon .tel-value {
    font-variant-numeric: tabular-nums;
}

.tel-icon.tel-ok { color: #2ecc71; }
.tel-icon.tel-warn { color: #f39c12; }
.tel-icon.tel-crit { color: #e74c3c; }
.tel-icon.tel-none { color: #7f8c8d; }

.tel-icon.tel-desync { color: #e74c3c; }
.tel-icon .tel-charge { margin-left: 2px; color: #f1c40f; }

.tel-badge-desync {
    display: inline-block;
    margin-left: 4px;
    padding: 1px 5px;
    background: #e74c3c;
    color: #fff;
    border-radius: 3px;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.5px;
}
```

- [ ] **Step 5: Smoke test w przeglądarce**

Uruchom Flask. Otwórz `http://127.0.0.1:5000/production/dashboard`. Sprawdź:

1. Strona ładuje się bez błędu Jinja.
2. Przy `cutting` (z Task 5 smoke testu) widać zielone ikony: bateria 87% z ⚡, temp 32°C, v1.0.15.
3. Przy pozostałych stanowiskach widać `—` we wszystkich trzech polach (brak danych / niedostępne).
4. Hover na grupę ikon pokazuje tooltip z IP i heartbeat timestamp.

- [ ] **Step 6: Smoke test wariantów wizualnych (sztucznie nadpisz dane)**

```bash
python3 <<'PY'
from app import create_app
from extensions import db
from modules.production.models import ProductionDevice
app = create_app()
with app.app_context():
    d = ProductionDevice.query.filter_by(device_id='HEARTBEAT-TEST-001').first()
    d.last_battery_pct = 8
    d.last_temperature_c = 55.0
    d.last_app_version_code = 14  # niższy niż wkrótce ustawimy max
    db.session.commit()
    # Dodajmy drugie urządzenie z wyższym APK żeby triggerować DESYNC
    other = ProductionDevice.query.filter_by(device_id='HEARTBEAT-TEST-002').first()
    if not other:
        other = ProductionDevice(
            device_id='HEARTBEAT-TEST-002',
            device_name='Smoke 2',
            station_code='assembly',
            token_version=1,
            is_active=True,
        )
        db.session.add(other)
    from datetime import datetime
    other.last_heartbeat_at = datetime.now()
    other.last_app_version_code = 20
    other.app_version = '1.0.19'
    db.session.commit()
PY
```

Reload `/production/dashboard`. Sprawdź:
- `cutting`: bateria czerwona "8%", temp czerwona "55°C", APK "1.0.15" z czerwonym badge "DESYNC".
- `assembly`: zielona bateria/temp `—`, APK "1.0.19" zielony, bez DESYNC.

- [ ] **Step 7: Cleanup test devices**

```bash
python3 <<'PY'
from app import create_app
from extensions import db
from modules.production.models import ProductionDevice
app = create_app()
with app.app_context():
    for did in ('HEARTBEAT-TEST-001', 'HEARTBEAT-TEST-002'):
        d = ProductionDevice.query.filter_by(device_id=did).first()
        if d:
            db.session.delete(d)
    db.session.commit()
    print('Cleaned up')
PY
```

- [ ] **Step 8: Commit**

```bash
git add modules/production/templates/components/dashboard-tab-content.html modules/production/static/css/production-panel.css
git commit -m "feat(production): ikony telemetrii tabletów przy kafelkach stanowisk"
```

---

## Task 8: Finalna weryfikacja

- [ ] **Step 1: Pełny lokalny test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: wszystkie testy pass, nowych regresji brak.

- [ ] **Step 2: Grep finalny — brak martwych referencji**

```bash
grep -rn "station_heartbeat" modules/ tests/ 2>/dev/null
```

Expected: pusto.

- [ ] **Step 3: Sprawdź czy macro Jinja jest poprawne i nie ma 500 na żadnym widoku**

Reload kolejno:
- `/production/dashboard` (panel admina)
- każda zakładka która mogła używać `tablet_status`

Expected: brak 500, brak błędów w konsoli przeglądarki, brak błędów w `modules/logging/logs/`.

- [ ] **Step 4: Poinformuj usera o gotowości do deploy**

> Lokalnie wszystko działa. Przed `git push` na main, puść SQL z `docs/superpowers/specs/2026-05-21-device-heartbeat-telemetry.sql` na produkcyjnej bazie przez phpMyAdmin. Po deployu tablety w ciągu 15 min same zaczną sypać telemetrię (`HeartbeatWorker` już rusza w `crm_prod_app`).

---

## Self-Review Notes

- **Spec coverage**: ✓ migracja (T1), model (T2), walidator (T3), helper z DB (T4), endpoint (T5), wycofanie in-memory (T6), UI (T7), weryfikacja (T8).
- **Pliki**: każdy task ma exact paths.
- **TDD**: pure functions (walidator, helper) idą TDD; endpoint i UI smoke-test manualny (zgodnie ze stylem repo per `feedback_db_operations.md` + brak pytest-flask).
- **Commity**: 7 commitów = bite-sized (SQL, model, walidator, helper, endpoint, refactor, UI). Każdy testowalny i revertable.
- **Typy spójne**: `validate_heartbeat_payload`, `build_devices_telemetry`, `get_devices_telemetry` używane konsekwentnie. Klucze słownika telemetrii (`active`, `status_label`, `battery_pct`, …) zgadzają się między helperem (T4) a template (T7).
