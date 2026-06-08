#pragma once
#include <TFT_eSPI.h>
#include "../data_model.h"

namespace monitor::ui {

void render_stations(TFT_eSPI& tft, const MonitorPayload& p);

}  // namespace monitor::ui
