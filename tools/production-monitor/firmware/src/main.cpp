#include <Arduino.h>
#include <TFT_eSPI.h>

TFT_eSPI tft = TFT_eSPI();

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n[monitor] boot");

  tft.init();
  tft.setRotation(0);  // portrait, USB-port facing down — adjust later
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("Hello", 20, 100);
  tft.drawString("Production", 20, 130);
  tft.drawString("Monitor", 20, 160);
  Serial.println("[monitor] display ready");
}

void loop() {
  delay(1000);
}
