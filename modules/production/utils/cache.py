"""
HTTP cache helpers (Cache-Control + ETag) dla mobile API.

OkHttp Cache po stronie tabletu (NetworkModule.kt) sam wysyła `If-None-Match`
przy ponownym żądaniu i obsługuje 304 → zwraca cached body bez zmian
w warstwie Repository.

Strategia: weak ETag z `MAX(updated_at) + COUNT` po właściwym podzbiorze
pozycji. COUNT chroni przed kasowaniem (max sam by się nie zmienił).
Lekkie — jeden agregujący SELECT przed pełną serializacją; gdy ETag
pasuje, pomijamy ciężki SELECT + jsonify.
"""

from flask import Response, jsonify, request


def make_weak_etag(*parts) -> str:
    """
    Buduje weak ETag w formacie `W/"a:b:c"`. None → pusty segment.
    """
    body = ':'.join('' if p is None else str(p) for p in parts)
    return f'W/"{body}"'


def if_none_match(etag: str) -> bool:
    """
    True gdy klient przysłał ten sam ETag w `If-None-Match`. Porównanie
    string-equal — my zawsze wystawiamy ten sam format, OkHttp zwraca
    dokładnie to co dostał.
    """
    client = request.headers.get('If-None-Match')
    if not client:
        return False
    return client.strip() == etag


def _add_cache_headers(resp: Response, etag: str, max_age: int) -> Response:
    resp.headers['Cache-Control'] = f'private, max-age={max_age}'
    resp.headers['ETag'] = etag
    resp.headers['Vary'] = 'Authorization'
    return resp


def cached_json(payload, etag: str, max_age: int = 15) -> Response:
    """200 OK z payloadem + nagłówkami cache."""
    resp = jsonify(payload)
    return _add_cache_headers(resp, etag, max_age)


def not_modified(etag: str, max_age: int = 15) -> Response:
    """304 Not Modified bez body, z nagłówkami cache (RFC 7232 §4.1)."""
    resp = Response(status=304)
    return _add_cache_headers(resp, etag, max_age)
