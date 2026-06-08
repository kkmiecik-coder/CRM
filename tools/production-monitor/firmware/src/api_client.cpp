#include "api_client.h"
#include "json_parser.h"
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include "secrets.h"

namespace monitor {

void wifi_connect() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 60000UL) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[wifi] connected, ip=");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[wifi] connect FAILED, will retry from loop()");
  }
}

bool wifi_is_connected() { return WiFi.status() == WL_CONNECTED; }

bool fetch_monitor(MonitorPayload& out) {
  if (!wifi_is_connected()) {
    Serial.println("[api] wifi not connected, skipping fetch");
    return false;
  }

  std::unique_ptr<BearSSL::WiFiClientSecure> client(new BearSSL::WiFiClientSecure());
  client->setInsecure();  // TODO: ship CA fingerprint pinning before prod
  client->setBufferSizes(2048, 1024);

  HTTPClient http;
  String url = String("https://") + MONITOR_API_HOST + MONITOR_API_PATH;
  if (!http.begin(*client, url)) {
    Serial.println("[api] http.begin failed");
    return false;
  }
  http.addHeader("Authorization", String("Bearer ") + MONITOR_API_TOKEN);
  http.setTimeout(10000);

  int code = http.GET();
  if (code != 200) {
    Serial.printf("[api] GET returned %d\n", code);
    http.end();
    return false;
  }
  String body = http.getString();
  http.end();

  if (!parse_monitor_payload(body.c_str(), out)) {
    Serial.println("[api] parse FAILED");
    out.valid = false;
    return false;
  }

  out.last_fetch_ms = millis();
  Serial.printf("[api] fetch OK, %d bytes\n", body.length());
  return true;
}

}  // namespace monitor
