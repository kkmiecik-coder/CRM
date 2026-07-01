# -*- coding: utf-8 -*-
# Provisioning Chatwoota: idempotentnie tworzy etykiety/foldery/reguly.
# Domyslnie dry-run; zapisy tylko z --apply. Auto-respondery tworzone nieaktywne.
import os
import sys
import argparse

from setup import desired_state as ds
from setup.cw_admin import CwAdmin, to_create


def _names(resp, key):
    # Niektore endpointy zwracaja {"payload": [...]}, a custom_filters - gola liste.
    try:
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("payload", [])
        return {x.get(key) for x in data}
    except Exception:
        return set()


def build_plan(client):
    have_labels = _names(client.get("/labels"), "title")
    have_folders = _names(client.get("/custom_filters"), "name")
    have_rules = _names(client.get("/automation_rules"), "name")

    labels = to_create(have_labels, ds.LABELS, "title")
    folders = to_create(have_folders, ds.FOLDERS, "name")

    # Reguly: tematyczne + nowy-kontakt + powitanie (nieaktywne).
    # Zrodlowe (OLX/Allegro) dokladamy w Task 5 po potwierdzeniu inbox IDs.
    desired_rules = []
    for label, kws in ds.KEYWORDS.items():
        if label == "pilne":
            desired_rules.append(ds.topic_rule_payload("pilne", kws))
        else:
            desired_rules.append(ds.topic_rule_payload(label, kws))
    for label, inbox_id in ds.SOURCE_INBOXES.items():
        desired_rules.append(ds.source_rule_payload(label, inbox_id))
    desired_rules.append(ds.new_contact_rule_payload())
    desired_rules.append(ds.b2c_default_rule_payload())
    desired_rules.append(ds.b2b_detect_rule_payload(ds.B2B_KEYWORDS))
    desired_rules.append(ds.internal_rule_payload(ds.INTERNAL_DOMAINS))
    desired_rules.append(ds.assign_on_reply_rule_payload(ds.PERSONAL_INBOXES))
    desired_rules.append(ds.greeting_rule_payload(ds.GREETING_TEXT))
    rules = to_create(have_rules, desired_rules, "name")

    return {"labels": labels, "folders": folders, "rules": rules}


def apply_plan(client, plan):
    log = []
    for l in plan["labels"]:
        r = client.post("/labels", ds.label_payload(l))
        log.append("etykieta %s -> HTTP %s" % (l["title"], r.status_code))
    for f in plan["folders"]:
        r = client.post("/custom_filters", ds.folder_payload(f["name"], f["query"]))
        log.append("folder %s -> HTTP %s" % (f["name"], r.status_code))
    for rule in plan["rules"]:
        r = client.post("/automation_rules", rule)
        log.append("regula %s -> HTTP %s" % (rule["name"], r.status_code))
    return log


def _print_plan(plan):
    print("PLAN (do utworzenia):")
    print("  etykiety:", [l["title"] for l in plan["labels"]] or "brak")
    print("  foldery :", [f["name"] for f in plan["folders"]] or "brak")
    print("  reguly  :", [r["name"] for r in plan["rules"]] or "brak")


def _make_client():
    base = os.environ.get("CHATWOOT_BASE", "http://rails:3000")
    account_id = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ.get("CHATWOOT_API_TOKEN")
    if not token:
        print("BLAD: brak CHATWOOT_API_TOKEN")
        sys.exit(1)
    return CwAdmin(base, account_id, token)


def run(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="wykonaj zmiany (domyslnie dry-run)")
    # --dry-run jest domyslnym trybem; flaga przyjmowana jawnie dla czytelnosci.
    ap.add_argument("--dry-run", action="store_true", help="tylko wypis planu (domyslne)")
    args = ap.parse_args(argv)

    client = _make_client()
    client.verify_admin()
    plan = build_plan(client)
    _print_plan(plan)

    if not args.apply:
        print("\n(dry-run) Nic nie zapisano. Uruchom z --apply aby wykonac.")
        return 0

    print("\n--apply: wykonuje...")
    for line in apply_plan(client, plan):
        print(" ", line)
    print("Gotowe. Auto-respondery utworzone jako NIEAKTYWNE.")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
