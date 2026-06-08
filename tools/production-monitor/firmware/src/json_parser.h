#pragma once
#include "data_model.h"

namespace monitor {

/// Parse the compact display monitor payload into `out`.
/// Returns true on success; false on malformed JSON or missing required fields.
/// Safe to call with any null-terminated input.
bool parse_monitor_payload(const char* json, MonitorPayload& out);

}  // namespace monitor
