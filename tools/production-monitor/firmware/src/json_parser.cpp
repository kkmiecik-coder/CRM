#include "json_parser.h"
#include <ArduinoJson.h>
#include <string.h>

namespace monitor {

// Station code -> canonical index. Returns -1 if unknown.
static int station_index(const char* code) {
  if (!code) return -1;
  if (strcmp(code, "cut") == 0) return ST_CUT;
  if (strcmp(code, "asm") == 0) return ST_ASM;
  if (strcmp(code, "glu") == 0) return ST_GLU;
  if (strcmp(code, "fmt") == 0) return ST_FMT;
  if (strcmp(code, "fin") == 0) return ST_FIN;
  if (strcmp(code, "pnt") == 0) return ST_PNT;
  if (strcmp(code, "pkg") == 0) return ST_PKG;
  return -1;
}

bool parse_monitor_payload(const char* json, MonitorPayload& out) {
  if (!json) return false;

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, json);
  if (err) return false;

  JsonArrayConst o = doc["o"].as<JsonArrayConst>();
  if (o.isNull() || o.size() < 6) return false;

  out = MonitorPayload{};  // zero-init

  out.timestamp = doc["t"].as<uint32_t>();
  out.overall.in_progress          = o[0].as<uint16_t>();
  out.overall.queued               = o[1].as<uint16_t>();
  out.overall.done_today           = o[2].as<uint16_t>();
  out.overall.value_ip_pln         = o[3].as<uint32_t>();
  out.overall.value_done_today_pln = o[4].as<uint32_t>();
  out.overall.overdue              = o[5].as<uint16_t>();

  JsonArrayConst sp = doc["sp"].as<JsonArrayConst>();
  out.species_count = 0;
  if (!sp.isNull()) {
    for (JsonVariantConst v : sp) {
      if (out.species_count >= MAX_SPECIES) break;
      const char* label = v.as<const char*>();
      if (!label) continue;
      strncpy(out.species_labels[out.species_count], label,
              sizeof(out.species_labels[0]) - 1);
      out.species_count++;
    }
  }

  JsonArrayConst st = doc["st"].as<JsonArrayConst>();
  if (!st.isNull()) {
    for (JsonObjectConst s : st) {
      int idx = station_index(s["c"].as<const char*>());
      if (idx < 0) continue;
      StationData& sd = out.stations[idx];
      sd.ip = s["ip"].as<uint16_t>();
      sd.d  = s["d"].as<uint16_t>();
      sd.q  = s["q"].as<uint16_t>();
      JsonArrayConst bs = s["bs"].as<JsonArrayConst>();
      if (bs.isNull()) continue;
      uint8_t i = 0;
      for (JsonArrayConst row : bs) {
        if (i >= MAX_SPECIES) break;
        if (row.size() < 3) { i++; continue; }
        sd.bs[i].ip = row[0].as<uint16_t>();
        sd.bs[i].d  = row[1].as<uint16_t>();
        sd.bs[i].q  = row[2].as<uint16_t>();
        i++;
      }
    }
  }

  out.valid = true;
  return true;
}

}  // namespace monitor
