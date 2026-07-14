# -*- coding: utf-8 -*-
# Google Search Console — Search Analytics API. Glowne zrodlo realnego popytu: zapytania, na ktore
# woodpower.pl juz sie wyswietla. Filtr striking distance (pozycja 6-20) + prog wyswietlen — tam jeden
# dobry artykul wskakuje na 1. strone. Auth: konto uslugowe (google-auth) -> Bearer token -> requests.
# Never-raises: dowolny blad (auth/HTTP/parsowanie) zwraca [].
import datetime
from urllib.parse import quote
import requests
from config import (GSC_ENABLED, GSC_SITE_URL, GSC_CREDENTIALS_JSON, GSC_DAYS,
                    GSC_MIN_IMPRESSIONS, GSC_POS_MIN, GSC_POS_MAX)
from core.log import log

_SCOPE = ["https://www.googleapis.com/auth/webmasters.readonly"]
_ENDPOINT = "https://searchconsole.googleapis.com/webmasters/v3/sites/%s/searchAnalytics/query"


def _access_token():
    # Token dostepu z konta uslugowego (import lokalny — google-auth potrzebny tylko tu).
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_file(GSC_CREDENTIALS_JSON, scopes=_SCOPE)
    creds.refresh(Request())
    return creds.token


def _score(impressions, position):
    # Wyzej: wiecej wyswietlen ORAZ blizej 1. strony (nizsza pozycja). Waga liniowa w oknie striking distance.
    return float(impressions) * max(1.0, (GSC_POS_MAX + 1 - float(position)))


def fetch_gsc_candidates():
    if not GSC_ENABLED or not GSC_CREDENTIALS_JSON:
        return []
    try:
        token = _access_token()
        today = datetime.date.today()
        body = {
            "startDate": (today - datetime.timedelta(days=GSC_DAYS)).isoformat(),
            "endDate": today.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 200,
        }
        url = _ENDPOINT % quote(GSC_SITE_URL, safe="")
        r = requests.post(url, json=body, headers={"Authorization": "Bearer " + token}, timeout=30)
        rows = (r.json() or {}).get("rows") or []
    except Exception as e:
        log("gsc: blad pobierania:", e)
        return []
    out = []
    for row in rows:
        try:
            query = (row.get("keys") or [""])[0]
            impr = row.get("impressions") or 0
            pos = row.get("position") or 0
            if not query or impr < GSC_MIN_IMPRESSIONS:
                continue
            if pos < GSC_POS_MIN or pos > GSC_POS_MAX:
                continue
            out.append({"query": query.strip(), "score": _score(impr, pos),
                        "source": "gsc", "impressions": impr, "position": pos})
        except Exception:
            continue
    return out
