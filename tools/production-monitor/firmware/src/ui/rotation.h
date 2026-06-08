#pragma once
#include <TFT_eSPI.h>
#include "../data_model.h"

namespace monitor::ui {

// Total screens: overall + all-stations + per-station-species × STATION_COUNT
constexpr uint8_t SCREEN_COUNT = 2 + STATION_COUNT;  // 9
constexpr unsigned long SCREEN_DWELL_MS = 5000;      // 5 s per screen

void render_current(TFT_eSPI& tft, const MonitorPayload& p, uint8_t screen_idx);

}  // namespace monitor::ui
