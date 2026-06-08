#include "screen_overall.h"

namespace monitor::ui {

void render_overall(TFT_eSPI& tft, const MonitorPayload& p) {
  tft.fillScreen(TFT_BLACK);

  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("PRODUKCJA DZIS", 10, 6);

  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(4);

  // In production now (big number, top half)
  tft.drawString(String(p.overall.in_progress), 20, 40);
  tft.setTextSize(2);
  tft.drawString("w produkcji", 20, 90);

  tft.setTextSize(4);
  tft.drawString(String(p.overall.done_today), 20, 120);
  tft.setTextSize(2);
  tft.drawString("gotowe", 20, 170);

  tft.drawString("kolejka:  " + String(p.overall.queued), 10, 210);
  tft.drawString("wartosc:  " + String(p.overall.value_done_today_pln) + " zl", 10, 235);

  if (p.overall.overdue > 0) {
    tft.fillRect(0, 285, 240, 35, TFT_RED);
    tft.setTextColor(TFT_WHITE, TFT_RED);
    tft.setTextSize(2);
    tft.drawString("ZALEGLE: " + String(p.overall.overdue), 10, 293);
  }
}

}  // namespace monitor::ui
