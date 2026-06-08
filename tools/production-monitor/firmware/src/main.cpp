#include <Arduino.h>
#include <TFT_eSPI.h>
#include "data_model.h"
#include "api_client.h"

TFT_eSPI tft = TFT_eSPI();
monitor::MonitorPayload payload{};

static unsigned long last_fetch_attempt = 0;
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
  tft.drawString(monitor::wifi_is_connected() ? "WiFi OK" : "WiFi FAIL", 20, 100);
  delay(500);
}

void loop() {
  if (millis() - last_fetch_attempt > FETCH_INTERVAL_MS || last_fetch_attempt == 0) {
    last_fetch_attempt = millis();
    bool ok = monitor::fetch_monitor(payload);
    tft.fillScreen(TFT_BLACK);
    tft.setTextSize(2);
    if (ok) {
      tft.drawString("IP=" + String(payload.overall.in_progress), 20, 80);
      tft.drawString("Q=" + String(payload.overall.queued), 20, 110);
      tft.drawString("D=" + String(payload.overall.done_today), 20, 140);
    } else {
      tft.drawString("FETCH FAIL", 20, 100);
    }
  }
  delay(500);
}
