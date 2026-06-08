#pragma once
#include <TFT_eSPI.h>
#include "../data_model.h"

namespace monitor::ui {

void render_station_species(TFT_eSPI& tft, const MonitorPayload& p, uint8_t station_idx);

}  // namespace monitor::ui
