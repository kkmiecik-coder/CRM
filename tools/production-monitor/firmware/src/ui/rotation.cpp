#include <Arduino.h>
#include "rotation.h"
#include "screen_overall.h"
#include "screen_stations.h"
#include "screen_station_species.h"

namespace monitor::ui {

void render_current(TFT_eSPI& tft, const MonitorPayload& p, uint8_t screen_idx) {
  uint8_t idx = screen_idx % SCREEN_COUNT;
  if (idx == 0) {
    render_overall(tft, p);
  } else if (idx == 1) {
    render_stations(tft, p);
  } else {
    render_station_species(tft, p, idx - 2);
  }

  unsigned long age_ms = millis() - p.last_fetch_ms;
  if (age_ms > 5UL * 60UL * 1000UL) {
    tft.setTextColor(TFT_ORANGE, TFT_BLACK);
    tft.setTextSize(1);
    tft.drawString("STALE", 200, 6);
  }
}

}  // namespace monitor::ui
