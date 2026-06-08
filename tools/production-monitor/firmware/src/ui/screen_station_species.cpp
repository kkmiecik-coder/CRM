#include "screen_station_species.h"

namespace monitor::ui {

void render_station_species(TFT_eSPI& tft, const MonitorPayload& p, uint8_t idx) {
  if (idx >= STATION_COUNT) return;
  tft.fillScreen(TFT_BLACK);

  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString(STATION_LABELS_PL[idx], 10, 6);

  // Column headers
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString("Gatunek",   10, 40);
  tft.drawString("Kolejka",  100, 40);
  tft.drawString("W trakc.", 155, 40);
  tft.drawString("Gotowe",   210, 40);

  tft.setTextSize(2);

  int y = 60;
  for (uint8_t i = 0; i < p.species_count && i < MAX_SPECIES; ++i) {
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
    tft.drawString(p.species_labels[i], 10, y);

    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.drawString(String(p.stations[idx].bs[i].q),  110, y);
    tft.drawString(String(p.stations[idx].bs[i].ip), 160, y);
    tft.drawString(String(p.stations[idx].bs[i].d),  215, y);
    y += 35;
  }

  // Footer with station totals as sanity check
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.setTextSize(1);
  String footer = "SUMA: K=" + String(p.stations[idx].q)
                + "  T=" + String(p.stations[idx].ip)
                + "  G=" + String(p.stations[idx].d);
  tft.drawString(footer, 10, 300);
}

}  // namespace monitor::ui
