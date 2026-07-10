# -*- coding: utf-8 -*-
# Telemetria leja sprzedazowego quote-bota: append-only log zdarzen (LS-08/TO-05/TO-06/TO-09).
# Nigdy nie rzuca — telemetria nie moze wywrocic tury bota.
import json
import time
from core.db import db
from core.log import log


def log_event(conv_id, event, meta=None):
    """Zapisuje jedno zdarzenie leja sprzedazowego: summary_sent/confirmed/priced/contact_given/
    contact_refused/quote_saved/shipping_quoted/handoff/turn_limit/failed. meta — dict serializowany
    do JSON (np. {'kwota':...}/{'powod':...}/{'nr':...})."""
    try:
        c = db()
        c.execute("INSERT INTO quote_events(conv_id, event, ts, meta) VALUES(?,?,?,?)",
                  (conv_id, event, time.time(), json.dumps(meta, ensure_ascii=False) if meta else None))
        c.commit(); c.close()
    except Exception as e:
        log("quote_events: log_event nieudany (conv %s, %s): %s" % (conv_id, event, repr(e)))
