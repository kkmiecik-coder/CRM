#pragma once
#include <stdint.h>

namespace monitor {

constexpr size_t STATION_COUNT = 7;
constexpr size_t MAX_SPECIES   = 4;   // configurable on CRM, but firmware caps at 4

// Order MUST match STATION_CODES in display_monitor_service.py
enum StationIdx : uint8_t {
  ST_CUT = 0, ST_ASM = 1, ST_GLU = 2, ST_FMT = 3,
  ST_FIN = 4, ST_PNT = 5, ST_PKG = 6,
};

constexpr const char* STATION_LABELS_PL[STATION_COUNT] = {
  "Ciecie", "Skladanie", "Sklejanie", "Formatka",
  "Wykonczenie", "Lakiernia", "Pakowanie",
};

// 3 ints per station × species cell: in_progress, done_today, queue
struct SpeciesCell {
  uint16_t ip;
  uint16_t d;
  uint16_t q;
};

struct StationData {
  uint16_t ip;
  uint16_t d;
  uint16_t q;
  SpeciesCell bs[MAX_SPECIES];
};

struct OverallData {
  uint16_t in_progress;
  uint16_t queued;
  uint16_t done_today;
  uint32_t value_ip_pln;
  uint32_t value_done_today_pln;
  uint16_t overdue;
};

struct MonitorPayload {
  uint32_t timestamp;
  OverallData overall;
  uint8_t species_count;
  char species_labels[MAX_SPECIES][24];  // UTF-8, null-terminated
  StationData stations[STATION_COUNT];
  bool valid;       // false if last fetch failed
  uint32_t last_fetch_ms;  // millis() of last successful fetch
};

}  // namespace monitor
