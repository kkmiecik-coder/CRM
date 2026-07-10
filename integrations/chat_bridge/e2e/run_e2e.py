# -*- coding: utf-8 -*-
"""Runner E2E quote-bota: uruchamia katalog scenariuszy (scenarios.py) przez silnik (harness.py),
drukuje podsumowanie i zapisuje raport (JSON + Markdown).

Przyklady:
  python run_e2e.py --lista                      # sam wypisz scenariusze (nic nie wysyla)
  python run_e2e.py --bez-leadow                 # wszystko OPROCZ scenariuszy piszacych do CRM
  python run_e2e.py --only V01,V04,S02           # tylko wybrane
  python run_e2e.py --kat Wariantowa             # cala kategoria
  python run_e2e.py --md raport.md --out raport.json --sprzataj

Uwaga: scenariusze z 'tworzy_lead' DOPROWADZAJA do policzonej ceny i tym samym tworza REALNY
lead/wycene w CRM (chat-<conv_id>). Uzyj --bez-leadow, jesli nie chcesz zapisow w CRM.
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from scenarios import SCENARIUSZE, kategorie


def _filtruj(args):
    scs = list(SCENARIUSZE)
    if args.only:
        chce = {x.strip() for x in args.only.split(",") if x.strip()}
        scs = [s for s in scs if s["id"] in chce]
    if args.kat:
        katy = {k.strip().lower() for k in args.kat.split(",")}
        scs = [s for s in scs if s.get("kat", "").lower() in katy]
    if args.bez_leadow:
        scs = [s for s in scs if not s.get("tworzy_lead")]
    if args.limit:
        scs = scs[:args.limit]
    return scs


def _sprzataj(wyniki):
    """Rozwiazuje (resolved) rozmowy testowe, zeby nie zasmiecaly skrzynki. Best-effort."""
    for w in wyniki:
        cid = w.get("conv_id")
        if not cid:
            continue
        try:
            harness._api("POST", "/conversations/%s/toggle_status" % cid, json={"status": "resolved"})
        except Exception as e:
            print("[sprzatanie] conv %s nieudane: %r" % (cid, e))


def _md(wyniki, sciezka):
    linie = ["# Raport E2E quote-bota (Dębuś) — kandydat inbox 18", ""]
    z_werdyktu = {}
    for w in wyniki:
        z_werdyktu.setdefault(w["werdykt"], []).append(w)
    linie.append("**Data:** %s · **Scenariuszy:** %d" % (
        time.strftime("%Y-%m-%d %H:%M"), len(wyniki)))
    linie.append("")
    linie.append("| Werdykt | Liczba |")
    linie.append("|---|---|")
    for wd in ("PASS", "REVIEW", "FAIL"):
        linie.append("| %s | %d |" % (wd, len(z_werdyktu.get(wd, []))))
    linie.append("")
    leady = [w for w in wyniki if w.get("tworzy_lead")]
    if leady:
        linie.append("**Scenariusze piszace do CRM (lead chat-<conv_id>):** " +
                     ", ".join("%s→conv %s" % (w["id"], w["conv_id"]) for w in leady))
        linie.append("")
    for kat in kategorie():
        w_kat = [w for w in wyniki if w.get("kat") == kat]
        if not w_kat:
            continue
        linie.append("## %s" % kat)
        linie.append("")
        linie.append("| # | Tytuł | Werdykt | Uwagi |")
        linie.append("|---|---|---|---|")
        for w in w_kat:
            uw = "; ".join(w.get("powody") or []) or "—"
            uw = uw.replace("|", "\\|")
            linie.append("| %s | %s | %s | %s |" % (w["id"], w.get("tytul", ""), w["werdykt"], uw))
        linie.append("")
    with open(sciezka, "w", encoding="utf-8") as f:
        f.write("\n".join(linie))
    print("Raport MD: %s" % sciezka)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="lista id po przecinku")
    ap.add_argument("--kat", help="kategoria (lub kilka po przecinku)")
    ap.add_argument("--bez-leadow", action="store_true", dest="bez_leadow",
                    help="pomin scenariusze piszace do CRM")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--lista", action="store_true", help="tylko wypisz scenariusze")
    ap.add_argument("--out", help="plik JSON z pelnym transkryptem")
    ap.add_argument("--md", help="plik Markdown z raportem")
    ap.add_argument("--sprzataj", action="store_true", help="rozwiaz (resolved) rozmowy testowe po tescie")
    args = ap.parse_args()

    scs = _filtruj(args)

    if args.lista:
        for s in scs:
            lead = " [LEAD→CRM]" if s.get("tworzy_lead") else ""
            print("%-5s %-14s %s%s" % (s["id"], s.get("kat", ""), s.get("tytul", ""), lead))
        print("\nRazem: %d scenariuszy" % len(scs))
        return

    print("Uruchamiam %d scenariuszy (webhook=%s, timeout=%ss)\n" % (
        len(scs), harness.FIRE_WEBHOOK, harness.POLL_TIMEOUT))
    wyniki = []
    for i, sc in enumerate(scs, 1):
        try:
            wyniki.append(harness.uruchom_scenariusz(sc, i, len(scs)))
        except Exception as e:
            print("   [BLAD scenariusza %s]: %r\n" % (sc["id"], e))
            wyniki.append({"id": sc["id"], "kat": sc.get("kat"), "tytul": sc.get("tytul"),
                           "werdykt": "FAIL", "powody": ["wyjatek harnessu: %r" % e],
                           "tworzy_lead": bool(sc.get("tworzy_lead")), "conv_id": None,
                           "transkrypt": []})

    # podsumowanie
    z = {}
    for w in wyniki:
        z.setdefault(w["werdykt"], []).append(w["id"])
    print("=" * 60)
    for wd in ("PASS", "REVIEW", "FAIL"):
        ids = z.get(wd, [])
        print("%-7s %d  %s" % (wd, len(ids), " ".join(ids)))
    print("=" * 60)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(wyniki, f, ensure_ascii=False, indent=2)
        print("Transkrypt JSON: %s" % args.out)
    if args.md:
        _md(wyniki, args.md)
    if args.sprzataj:
        _sprzataj(wyniki)
        print("Rozmowy testowe rozwiazane (resolved).")


if __name__ == "__main__":
    main()
