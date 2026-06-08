#include <unity.h>
#include <string.h>
#include "json_parser.h"
#include "data_model.h"

using namespace monitor;

const char* SAMPLE_PAYLOAD = R"JSON({
  "t": 1733601234,
  "o": [47, 23, 18, 89200, 18450, 3],
  "sp": ["dąb", "jesion", "buk"],
  "st": [
    {"c":"cut","ip":12,"d":8,"q":15,"bs":[[7,4,10],[3,2,3],[2,2,2]]},
    {"c":"asm","ip":3, "d":2,"q":5, "bs":[[2,1,3],[1,1,2],[0,0,0]]},
    {"c":"glu","ip":8, "d":5,"q":11,"bs":[[5,3,7],[2,1,2],[1,1,2]]},
    {"c":"fmt","ip":5, "d":7,"q":9, "bs":[[3,4,5],[1,2,2],[1,1,2]]},
    {"c":"fin","ip":4, "d":3,"q":6, "bs":[[2,2,3],[1,1,2],[1,0,1]]},
    {"c":"pnt","ip":2, "d":1,"q":4, "bs":[[1,1,2],[1,0,1],[0,0,1]]},
    {"c":"pkg","ip":3, "d":5,"q":2, "bs":[[2,3,1],[1,1,1],[0,1,0]]}
  ]
})JSON";

void test_parses_timestamp_and_overall() {
  MonitorPayload p{};
  TEST_ASSERT_TRUE(parse_monitor_payload(SAMPLE_PAYLOAD, p));
  TEST_ASSERT_EQUAL_UINT32(1733601234, p.timestamp);
  TEST_ASSERT_EQUAL_UINT16(47, p.overall.in_progress);
  TEST_ASSERT_EQUAL_UINT16(23, p.overall.queued);
  TEST_ASSERT_EQUAL_UINT16(18, p.overall.done_today);
  TEST_ASSERT_EQUAL_UINT32(89200, p.overall.value_ip_pln);
  TEST_ASSERT_EQUAL_UINT32(18450, p.overall.value_done_today_pln);
  TEST_ASSERT_EQUAL_UINT16(3, p.overall.overdue);
}

void test_parses_species() {
  MonitorPayload p{};
  TEST_ASSERT_TRUE(parse_monitor_payload(SAMPLE_PAYLOAD, p));
  TEST_ASSERT_EQUAL_UINT8(3, p.species_count);
  TEST_ASSERT_EQUAL_STRING("dąb", p.species_labels[0]);
  TEST_ASSERT_EQUAL_STRING("jesion", p.species_labels[1]);
  TEST_ASSERT_EQUAL_STRING("buk", p.species_labels[2]);
}

void test_parses_station_in_canonical_order() {
  MonitorPayload p{};
  TEST_ASSERT_TRUE(parse_monitor_payload(SAMPLE_PAYLOAD, p));
  TEST_ASSERT_EQUAL_UINT16(12, p.stations[ST_CUT].ip);
  TEST_ASSERT_EQUAL_UINT16(8,  p.stations[ST_CUT].d);
  TEST_ASSERT_EQUAL_UINT16(15, p.stations[ST_CUT].q);
  TEST_ASSERT_EQUAL_UINT16(3,  p.stations[ST_PKG].ip);
  TEST_ASSERT_EQUAL_UINT16(5,  p.stations[ST_PKG].d);
  TEST_ASSERT_EQUAL_UINT16(2,  p.stations[ST_PKG].q);
}

void test_parses_per_species_cells() {
  MonitorPayload p{};
  TEST_ASSERT_TRUE(parse_monitor_payload(SAMPLE_PAYLOAD, p));
  TEST_ASSERT_EQUAL_UINT16(7,  p.stations[ST_CUT].bs[0].ip);
  TEST_ASSERT_EQUAL_UINT16(4,  p.stations[ST_CUT].bs[0].d);
  TEST_ASSERT_EQUAL_UINT16(10, p.stations[ST_CUT].bs[0].q);
  TEST_ASSERT_EQUAL_UINT16(2,  p.stations[ST_CUT].bs[2].ip);
  TEST_ASSERT_EQUAL_UINT16(2,  p.stations[ST_CUT].bs[2].d);
  TEST_ASSERT_EQUAL_UINT16(2,  p.stations[ST_CUT].bs[2].q);
}

void test_rejects_malformed_json() {
  MonitorPayload p{};
  TEST_ASSERT_FALSE(parse_monitor_payload("not json", p));
}

void test_rejects_missing_overall_array() {
  const char* bad = R"JSON({"t":1,"sp":["x"],"st":[]})JSON";
  MonitorPayload p{};
  TEST_ASSERT_FALSE(parse_monitor_payload(bad, p));
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_parses_timestamp_and_overall);
  RUN_TEST(test_parses_species);
  RUN_TEST(test_parses_station_in_canonical_order);
  RUN_TEST(test_parses_per_species_cells);
  RUN_TEST(test_rejects_malformed_json);
  RUN_TEST(test_rejects_missing_overall_array);
  return UNITY_END();
}
