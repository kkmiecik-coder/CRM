#include "screen_stations.h"

namespace monitor::ui {

void render_stations(TFT_eSPI& tft, const MonitorPayload& p) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("STANOWISKA", 10, 6);

  // Header row
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString("Stacja",   10,  40);
  tft.drawString("Kolejka", 110,  40);
  tft.drawString("W trakc.", 160, 40);
  tft.drawString("Gotowe",  210,  40);

  tft.setTextSize(2);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);

  int y = 55;
  for (uint8_t i = 0; i < STATION_COUNT; ++i) {
    tft.drawString(STATION_LABELS_PL[i], 10, y);
    tft.drawString(String(p.stations[i].q),  120, y);
    tft.drawString(String(p.stations[i].ip), 170, y);
    tft.drawString(String(p.stations[i].d),  215, y);
    y += 30;
  }
}

}  // namespace monitor::ui
