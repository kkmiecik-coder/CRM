# Production Monitor Firmware

ESP8266 firmware for the GeekMagic SmallTV-Ultra display showing live WoodPower
production stats from the CRM.

## Hardware

- **Module:** ESP-12F (ESP8266EX, 4 MB flash, 80 KB RAM)
- **Display:** ST7789 240×320 IPS (assumed — verify on first flash)
- **WiFi:** 2.4 GHz only (single-band radio)

## Layout

- `src/` — Arduino sources
  - `main.cpp` — boot, WiFi, fetch loop, rotation
  - `data_model.h` — `MonitorPayload` and friends
  - `json_parser.{h,cpp}` — payload deserialisation
  - `api_client.{h,cpp}` — WiFi + HTTPS fetch
  - `ui/` — per-screen rendering and rotation
- `test/test_json_parser/` — Unity native unit tests (run with `pio test -e native`)
- `include/secrets.h.example` — copy to `include/secrets.h`, fill credentials (gitignored)
- `scripts/release.bat` — build + gzip + copy to `release/`
- `release/` — output `.bin` / `.bin.gz` artifacts (gitignored)
- `platformio.ini` — PlatformIO config (esp12e + native test envs)

## Prerequisites

Install PlatformIO Core:
```
pip install platformio
```
(or use the VS Code "PlatformIO IDE" extension).

`gzip` must be on PATH for the release script (Git for Windows ships it).

## Configuration on the CRM side

On the server running the CRM:
```
flask init-display-monitor
```
This prints the display token once. Paste it into `include/secrets.h` as `MONITOR_API_TOKEN`.

## Build + flash

1. Copy `include/secrets.h.example` to `include/secrets.h`; fill WiFi credentials, API host (default `crm.woodpower.pl`), and the token from above.
2. Build and package:
   ```
   scripts\release.bat
   ```
3. Open `http://<device-ip>/update` in a browser.
4. Upload `release\production-monitor-YYYYMMDD.bin.gz`. Device reboots automatically when done.

## Native unit tests

```
pio test -e native
```
Tests the JSON parser without any hardware. Should report all green.

## On-device sanity check

After flashing, the screen should cycle through 9 screens (~5 s each):
1. PRODUKCJA DZIS — overall today
2. STANOWISKA — all 7 stations
3-9. One per station with per-species breakdown (dąb / jesion / buk)

Total cycle: ~45 s. Fetch happens every 60 s in the background.

## Troubleshooting

- **Black screen after upload:** display driver mismatch. Open the device, photograph the PCB ribbon side, and update the `TFT_*` defines in `platformio.ini`. Most common alternative is GC9A01 (round) — swap `ST7789_DRIVER=1` for `GC9A01_DRIVER=1`.
- **Garbled colors:** driver is partly wrong (likely ST7735 instead of ST7789). Try `ST7735_DRIVER=1` and `ST7735_GREENTAB`/`ST7735_REDTAB` variants.
- **"FETCH FAIL" stays on screen:** check serial monitor (`pio device monitor`) for HTTP error code. 401 = token mismatch. 5xx = CRM problem. Anything else = WiFi or TLS.
- **"Brak danych / Ponawiam":** first fetch hasn't succeeded yet; should clear within 60 s. If it persists, see "FETCH FAIL" above.
- **STALE overlay (top-right corner):** last successful fetch was >5 min ago. Either the CRM is down or the device's WiFi has been flapping.

## Reverting to factory firmware

The factory image was saved in `tools/production-monitor/backups/factory-Ultra-V9.0.50.zip`
(gitignored). Extract the `.bin`, then upload it via `http://<device-ip>/update`.
