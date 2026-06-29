# -*- coding: utf-8 -*-
# Wspolny klient GET z ograniczonym retry+backoffem na przejsciowe bledy (400/401/429/5xx).
# API OLX i Allegro potrafia zwrocic przejsciowy blad na poprawne zadanie — to samo zadanie
# po chwili dziala. Zamiast wywalac caly cykl pollera, ponawiamy z backoffem.
import time
import requests
from core.log import log

def get_with_retry(url, headers_fn, tries=3, timeout=25, label=None):
    """headers_fn(force_refresh: bool) -> dict naglowkow. force_refresh=True po 401 (odswiez token)."""
    last = None
    r = None
    for i in range(tries):
        r = requests.get(url, headers=headers_fn(force_refresh=(last == 401)), timeout=timeout)
        if r.status_code == 200:
            return r
        last = r.status_code
        if i < tries - 1 and (r.status_code in (400, 401, 429) or r.status_code >= 500):
            time.sleep(1.0 * (i + 1))
            continue
        break
    log("HTTP_GET blad", last, label or url, "BODY:", (r.text[:300] if r is not None else "-"))
    r.raise_for_status()
    return r
