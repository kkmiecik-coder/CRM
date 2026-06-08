#include <Arduino.h>
#include <TFT_eSPI.h>
#include "data_model.h"
#include "api_client.h"
#include "ui/rotation.h"

TFT_eSPI tft = TFT_eSPI();
monitor::MonitorPayload payload{};

static unsigned long last_fetch_attempt = 0;
static unsigned long last_screen_switch = 0;
static uint8_t current_screen = 0;
const unsigned long FETCH_INTERVAL_MS = 60UL * 1000UL;

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n[monitor] boot");
  tft.init();
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("WiFi...", 20, 100);
  monitor::wifi_connect();
  tft.fillScreen(TFT_BLACK);
  tft.drawString("Pobieram...", 20, 100);
}

void loop() {
  unsigned long now = millis();

  if (last_fetch_attempt == 0 || now - last_fetch_attempt > FETCH_INTERVAL_MS) {
    last_fetch_attempt = now;
    monitor::fetch_monitor(payload);
  }

  if (now - last_screen_switch > monitor::ui::SCREEN_DWELL_MS) {
    last_screen_switch = now;
    if (payload.valid) {
      monitor::ui::render_current(tft, payload, current_screen);
      current_screen = (current_screen + 1) % monitor::ui::SCREEN_COUNT;
    } else {
      tft.fillScreen(TFT_BLACK);
      tft.setTextColor(TFT_RED, TFT_BLACK);
      tft.setTextSize(2);
      tft.drawString("Brak danych", 20, 140);
      tft.drawString("Ponawiam...", 20, 170);
    }
  }

  delay(100);
}
