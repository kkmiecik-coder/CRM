# Device Heartbeat & Telemetry — Design

**Data:** 2026-05-21
**Moduł:** `production`
**Cel:** Tablety stanowiskowe (Android, `crm_prod_app`) wysyłają co 15 min telemetrię (bateria, temperatura, wersja APK, IP) do CRM. Brygadzista widzi te dane przy kafelkach stanowisk w dashboardzie produkcji, obok istniejącego badge "Aktywne / Niedostępne".

## Kontekst

Po stronie Androida gotowe: `HeartbeatWorker` (WorkManager, 15 min), `CrmApi.postDeviceHeartbeat()`, `DeviceHeartbeatDto`. Czeka tylko na endpoint backendowy.

Po stronie CRM istnieje już prymitywny `modules/production/services/station_heartbeat.py` — in-memory store z 60-sekundowym timeoutem, zasilany pośrednio z każdego mobile requestu. Jest używany w trzech miejscach do wyliczania `dashboard_stats.stations.{code}.tablet_status`:
- `modules/production/routers/main_routers.py:126`
- `modules/production/routers/api/dashboard_api.py:843`
- `modules/production/routers/api/dashboard_api.py:1060`

Decyzja: wycofujemy in-memory store. Jedno źródło prawdy = `prod_devices.last_heartbeat_at` w DB. Restart Flaska nie kasuje stanu.

## Backend

### Migracja `prod_devices`

User puszcza ręcznie przez phpMyAdmin **przed deployem kodu** (per `feedback_db_operations.md` — hosting blokuje information_schema, brak idempotent migracji).

Istniejące kolumny `last_ip` (45) i `app_version` (32) reusujemy do IP i `app_version_name` — nie tworzymy duplikatów. Dodajemy tylko nowe pola telemetrii:

```sql
ALTER TABLE prod_devices
  ADD COLUMN last_heartbeat_at DATETIME NULL,
  ADD COLUMN last_battery_pct SMALLINT NULL,
  ADD COLUMN last_battery_charging BOOLEAN NULL,
  ADD COLUMN last_temperature_c FLOAT NULL,
  ADD COLUMN last_app_version_code INT NULL,
  ADD INDEX idx_prod_devices_last_heartbeat (last_heartbeat_at);
```

### Model `ProductionDevice` (zmiany w `modules/production/models.py`)

Dodać kolumny (po istniejących `app_version`, `is_active`):
```python
last_heartbeat_at = Column(DateTime, nullable=True, index=True)
last_battery_pct = Column(SmallInteger, nullable=True)
last_battery_charging = Column(Boolean, nullable=True)
last_temperature_c = Column(Float, nullable=True)
last_app_version_code = Column(Integer, nullable=True)
```

`last_ip` i `app_version` reusujemy bez zmian.

### Endpoint `POST /api/mobile/v1/devices/heartbeat`

Plik: `modules/production/services/mobile_api_service.py`

```
POST /api/mobile/v1/devices/heartbeat
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "battery_pct": 87,
  "battery_charging": true,
  "temperature_c": 32.5,
  "app_version_code": 16,
  "app_version_name": "1.0.15",
  "ip_address": "192.168.33.7"
}
```

Logika:
1. Dekorator `@require_device_token` ustawia `g.device`.
2. Walidacja zakresów:
   - `battery_pct` (jeśli != null) ∈ [0, 100] — w przeciwnym razie 422 `{"error":"validation","detail":"battery_pct out of range"}`
   - `temperature_c` (jeśli != null) ∈ [-20.0, 100.0] — w przeciwnym razie 422
   - `app_version_code` i `app_version_name` — **wymagane**; brak → 422
3. Zapis pól na `g.device`:
   ```python
   device.last_heartbeat_at = get_local_now()
   device.last_battery_pct = battery_pct
   device.last_battery_charging = payload.get('battery_charging')
   device.last_temperature_c = temp
   device.last_app_version_code = payload['app_version_code']
   device.app_version = payload['app_version_name']  # reuse
   if payload.get('ip_address'):
       device.last_ip = payload['ip_address']  # reuse
   db.session.commit()
   ```
4. Response: `204 No Content` (puste body).
5. Logowanie przez `StructuredLogger` jak inne mobile endpointy (`event='device_heartbeat'`, `device_id`, `station_code`, `battery_pct`, `temperature_c`).

**Response codes:**
- 204 — sukces
- 401 — JWT nieważny (już obsługiwane przez `@require_device_token`)
- 422 — walidacja
- 500 — awaria (tablet zrobi retry przez WorkManager)

### Helper `get_devices_telemetry()` (w `mobile_api_service.py`)

Zastępuje `station_heartbeat.get_all_statuses()`. Zwraca słownik per `station_code`:

```python
{
  'cutting': {
    'active': bool,                  # last_heartbeat_at w ostatnich 20 min
    'status_label': 'Aktywne' | 'Niedostępne',
    'last_heartbeat_at': iso str | None,
    'battery_pct': int | None,
    'battery_charging': bool | None,
    'temperature_c': float | None,
    'app_version_name': str | None,
    'app_version_code': int | None,
    'ip_address': str | None,
    'apk_outdated': bool,            # last_app_version_code < max ze wszystkich tabletów
  },
  ...
}
```

Implementacja:
- Pobiera wszystkie `ProductionDevice` gdzie `is_active=True`.
- Liczy `fleet_max_apk = max(d.last_app_version_code for d in devices if d.last_app_version_code)` (None gdy brak danych).
- Per stanowisko z `ProductionDevice.VALID_STATION_CODES`: znajdź urządzenie (jeśli >1 na stanowisko — bierzemy z najświeższym `last_heartbeat_at`), wylicz pola.
- Próg: `active = last_heartbeat_at and (now - last_heartbeat_at) < 20 min`.
- `apk_outdated = bool(fleet_max_apk and device.last_app_version_code and device.last_app_version_code < fleet_max_apk)`.
- Stanowiska bez urządzenia → wszystkie pola None, `active=False, status_label='Niedostępne', apk_outdated=False`.

### Wycofanie `station_heartbeat.py`

- Usuwam plik `modules/production/services/station_heartbeat.py`.
- W trzech miejscach (`main_routers.py:126`, `dashboard_api.py:843`, `dashboard_api.py:1060`) podmieniam wywołanie na `get_devices_telemetry()`.
- Sprawdzam czy `record_heartbeat` jest jeszcze gdzieś wywoływane (najpewniej z dekoratora autoryzacji); usuwam wywołania.
- Usuwam `from . import station_heartbeat` i podobne importy.

## Frontend (kafelka stanowiska)

Plik: `modules/production/templates/components/dashboard-tab-content.html`

Dla każdego z 6 stanowisk z tabletem (`cutting`, `assembly`, `gluing`, `formatting`, `finishing`, `packaging`; logistyka pominięta — hardcoded "Aktywne", bez tabletu) dodaję obok `il-station-badge` rząd 3 ikon FontAwesome:

```html
<span class="il-station-telemetry"
      data-bs-toggle="tooltip"
      data-bs-html="true"
      title="<pełen tooltip>">
  <span class="tel-battery tel-{ok|warn|crit|none}">
    <i class="fas fa-battery-{full|three-quarters|half|quarter|empty}"></i>
    {{ pct }}%
    {% if charging %}<i class="fas fa-bolt"></i>{% endif %}
  </span>
  <span class="tel-temp tel-{ok|warn|crit|none}">
    <i class="fas fa-thermometer-half"></i> {{ temp }}°C
  </span>
  <span class="tel-apk tel-{ok|desync|none}">
    <i class="fas fa-mobile-alt"></i> {{ version_name }}
    {% if apk_outdated %}<span class="tel-badge-desync">DESYNC</span>{% endif %}
  </span>
</span>
```

### Reguły kolorów (dark theme, zgodnie z `feedback_station_design.md` — w panelu admina, nie tablecie)

- **Bateria**:
  - `ok` (zielony): `pct ≥ 20`
  - `warn` (żółty): `pct ∈ [10, 19]`
  - `crit` (czerwony): `pct < 10`
  - `none` (szary): `pct is None`
- **Temperatura**:
  - `ok`: `temp < 40`
  - `warn`: `temp ∈ [40, 50]`
  - `crit`: `temp > 50`
  - `none`: `temp is None`
- **APK**:
  - `ok` (szary): `apk_outdated=False`
  - `desync` (czerwony + badge "DESYNC"): `apk_outdated=True`
  - `none`: brak `app_version_name`
- Cała grupa ikon wyświetla `—` gdy `active=False` (tablet nie biał >20 min) — dane są stare, nie wprowadzamy w błąd.

### Tooltip (Bootstrap, JS już zainicjowany w panelu)

```
Heartbeat: 2 min temu (15:42:31)
Bateria: 87% (ładuje się)
Temperatura: 32.5°C
APK: 1.0.15 (vc16)
IP: 192.168.33.7
```

### CSS

Dodać do istniejącego stylesheet panelu (`modules/production/static/css/...` — sprawdzić w trakcie implementacji). Klasy: `il-station-telemetry`, `tel-battery`, `tel-temp`, `tel-apk`, `tel-{ok|warn|crit|desync|none}`, `tel-badge-desync`.

### Backend → template

W trzech routerach (gdzie dziś jest `get_all_statuses()`) wstrzykujemy nową strukturę pod `dashboard_stats.stations.{code}.tablet_status` — template czyta nowe pola. Pola które już są (`active`, `status_label`) zostają wstecz-kompatybilne.

## Bez zmian

- **Auto-refresh dashboardu**: świadomie brak (per `a6e98b5` — user wycofał auto-odświeżanie z panelu). Telemetria refreshuje się przy przeładowaniu strony.
- **Logistyka**: badge hardcoded "Aktywne" (logistyka nie ma tabletu).
- **Android**: nic, kod gotowy po stronie `crm_prod_app`.

## Testy manualne (pre-deploy)

1. **Migracja SQL** puszczona w phpMyAdmin (lokalny + prod).
2. **Endpoint smoke test** (`python3` per `feedback_python_command.md`):
   - POST z prawidłowym JWT i payloadem → 204, w DB zapisane pola.
   - POST z `battery_pct=150` → 422.
   - POST z `temperature_c=999` → 422.
   - POST bez `app_version_code` → 422.
   - POST z nieważnym JWT → 401.
3. **Helper `get_devices_telemetry`** — zwraca poprawne dane dla wszystkich 6 stanowisk, w tym dla stanowisk bez urządzenia (None values, `Niedostępne`).
4. **UI dashboard**:
   - Tablet po heartbeat → zielone ikony + dane.
   - Tablet nie bije >20 min → `Niedostępne`, ikony `—`.
   - Sztucznie ustawić w DB `last_battery_pct=8` → czerwona bateria.
   - Sztucznie ustawić `last_temperature_c=55` → czerwona temperatura.
   - Sztucznie obniżyć `last_app_version_code` jednego tabletu → "DESYNC".
5. **Brak referencji** do usuniętego `station_heartbeat`: `grep -rn "station_heartbeat\|record_heartbeat" modules/` → pusto.

## Plan deploya

1. User puszcza migrację SQL w phpMyAdmin (lokal + prod).
2. Merge do `main` → GitHub Actions deploy → Passenger restart.
3. Tablety w ciągu kolejnych 15 min zaczną sypać telemetrię (`HeartbeatWorker` już działa).
4. Brygadzista przeładowuje dashboard — widzi nowe dane.
