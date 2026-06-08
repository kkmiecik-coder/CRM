#pragma once
#include "data_model.h"

namespace monitor {

void wifi_connect();   // blocks until connected, with 60 s timeout
bool wifi_is_connected();

/// Fetches and parses /production/api/display/monitor.
/// On success, fills `out` and returns true. On failure returns false and
/// leaves `out.valid = false`.
bool fetch_monitor(MonitorPayload& out);

}  // namespace monitor
