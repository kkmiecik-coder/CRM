# -*- coding: utf-8 -*-
# Rekonesans Chatwoota (read-only): wypisuje wersje, inboxy, etykiety,
# reguly automatyzacji i custom_filters. Sluzy do potwierdzenia ksztaltu API
# danej wersji ZANIM napiszemy cokolwiek zapisujacego. NIE zmienia stanu konta.
import os
import json
import sys
import requests


def cw_get(base, account_id, token, path):
    url = "%s/api/v1/accounts/%s%s" % (base, account_id, path)
    h = {"api_access_token": token, "Content-Type": "application/json"}
    return requests.get(url, headers=h, timeout=25)


def main():
    base = os.environ.get("CHATWOOT_BASE", "http://rails:3000")
    account_id = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ.get("CHATWOOT_API_TOKEN")
    if not token:
        print("BLAD: brak CHATWOOT_API_TOKEN w env")
        sys.exit(1)

    # /api/v1/accounts/{id} zwraca m.in. dane konta; brak 200 = zly token/uprawnienia
    for label, path in [
        ("ACCOUNT", ""),
        ("INBOXES", "/inboxes"),
        ("LABELS", "/labels"),
        ("AUTOMATION_RULES", "/automation_rules"),
        ("CUSTOM_FILTERS", "/custom_filters"),
    ]:
        r = cw_get(base, account_id, token, path)
        print("\n===== %s (HTTP %s) =====" % (label, r.status_code))
        try:
            print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:4000])
        except Exception:
            print(r.text[:1000])


if __name__ == "__main__":
    main()
