# -*- coding: utf-8 -*-
# Cienki klient Application API Chatwoota dla provisioningu + idempotentny diff.
import requests


class CwAdmin:
    def __init__(self, base, account_id, token):
        self.base = base.rstrip("/")
        self.account_id = str(account_id)
        self.token = token

    def _url(self, path):
        return "%s/api/v1/accounts/%s%s" % (self.base, self.account_id, path)

    def _req(self, method, path, payload=None):
        h = {"api_access_token": self.token, "Content-Type": "application/json"}
        return requests.request(method, self._url(path), headers=h, json=payload, timeout=25)

    def get(self, path):
        return self._req("GET", path)

    def post(self, path, payload):
        return self._req("POST", path, payload)

    def patch(self, path, payload):
        return self._req("PATCH", path, payload)

    def verify_admin(self):
        # Token musi miec uprawnienia admina; /labels jest chronione.
        r = self.get("/labels")
        if r.status_code != 200:
            raise PermissionError(
                "Token nie ma uprawnien admina lub endpoint niedostepny (HTTP %s): %s"
                % (r.status_code, r.text[:200])
            )


def to_create(existing_names, desired, name_key):
    # Zwraca tylko te elementy desired, ktorych nazwa nie wystepuje juz na koncie.
    return [d for d in desired if d[name_key] not in existing_names]
