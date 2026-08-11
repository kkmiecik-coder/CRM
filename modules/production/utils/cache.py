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
    True gdy klient przysłał ten sam ETag w `If-None-Match`.

    RFC 7232 §3.2 dopuszcza listę po przecinku oraz `*`, a apka nie zawsze
    odsyła surowo to, co dostała: `/workers` echuje POLE `catalog_version`
    z ciała, więc wystawiamy tam tę samą wartość co w nagłówku. Rozbicie
    listy i porównanie każdego elementu kosztuje jeden split, a chroni przed
    proxy, które doklei drugi ETag.

    Porównanie jest string-equal na całej wartości (razem z `W/` i cudzysłowami)
    — my zawsze wystawiamy jeden format, więc słabe porównanie z RFC nie ma
    tu czego zrównać poza tym, co i tak jest identyczne.
    """
    client = request.headers.get('If-None-Match')
    if not client:
        return False

    kandydaci = [c.strip() for c in client.split(',')]
    return '*' in kandydaci or etag in kandydaci


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


def no_store_json(payload) -> Response:
    """
    200 OK z payloadem, którego NIE WOLNO cache'ować ani chwili.

    Dla endpointów stanu bieżącego (np. /sessions/active). Tablet ma na sobie
    OkHttp Cache (NetworkModule.kt) i sam wysyła `Cache-Control: no-store`
    w żądaniu, ale to tylko połowa kontraktu: bez nagłówka po naszej stronie
    wystarczy jeden proxy albo zmiana konfiguracji klienta, żeby odpowiedź
    „sesja nadal Twoja" wisiała w cache przez max-age. Skutkiem jest tablet,
    który po przejęciu profilu (`replaced`) NIE wraca na bramkę wyboru
    i podpisuje pracę cudzym nazwiskiem — dokładnie to, czemu ma zapobiegać
    polling co 60 s. `Vary: Authorization`, bo odpowiedź jest per urządzenie
    (device_id z JWT).
    """
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Vary'] = 'Authorization'
    return resp
