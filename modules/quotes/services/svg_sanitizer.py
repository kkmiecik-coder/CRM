"""Sanityzator SVG dla publicznej strony wyceny.

Po co to jest
------------
Kolumny ``quote_items_details.shape_svg`` i ``quote_items_details.edges_svg`` sa
zapisywane do bazy verbatim (modules/calculator/services/quote_service.py), a
potem wstrzykiwane do DOM przez ``innerHTML`` na stronie ``/quotes/c/<token>``,
ktora nie wymaga logowania. SVG jest formatem aktywnym: dopuszcza ``<script>``,
atrybuty ``on*``, ``<foreignObject>`` z dowolnym HTML-em oraz ``javascript:`` w
``xlink:href``. Bez czyszczenia jest to stored XSS na kliencie.

Ten sam string idzie tez do WeasyPrint/cairosvg przy generowaniu PDF
(``modules/quotes/routers.py`` -> ``_svg_to_png_base64``, ``offer_pdf.html``
przez ``|safe``). Ta sciezka parsuje wynik XML-owo i potrafi pobrac ``http(s)``
z serwera, wiec wynik musi byc (a) poprawnym XML-em, bez duplikatow atrybutow,
(b) wolny od odwolan do zasobow zewnetrznych.

W repo nie ma DOMPurify ani bleach i celowo nie dokladamy zaleznosci — caly
sanityzator stoi na bibliotece standardowej (``xml.etree.ElementTree``).

Kontrakt
--------
    sanitize_svg(raw, id_prefix=None) -> str albo None

* ``None`` / pusty string / same biale znaki -> ``None``
* wejscie ktorego nie da sie bezpiecznie odtworzyc -> ``None``
  (lepiej brak podgladu niz dziura); funkcja NIGDY nie rzuca wyjatkiem
* wynik bez ANI JEDNEGO elementu rysujacego -> ``None`` (pusty ``<svg>`` jest
  wartoscia truthy i konsument wyrenderowalby pusta ramke)
* w przeciwnym razie: bezpieczny, dobrze uformowany string SVG
* ``id_prefix`` (opcjonalny) prefiksuje wszystkie ``id`` i wszystkie odwolania
  do nich (``url(#...)``, ``href="#..."``) — jeden dokument HTML sklada wiele
  produktow i bez tego ``id="edgesSvg"`` z pozycji 2 kolidowaloby z pozycja 1

Model bezpieczenstwa: whitelist (default deny). Wszystko, czego nie ma na
liscie dozwolonych elementow/atrybutow, wypada. Elementy jawnie niebezpieczne
(``script``, ``foreignObject``, ...) sa wycinane RAZEM z poddrzewem; elementy
nieznane, ale nieszkodliwe (np. ``<a>``, ``<switch>``) tracą tylko swoj tag —
tresc zostaje (tak samo zachowuje sie DOMPurify z ``KEEP_CONTENT``).
"""

import re
from html import escape
from xml.etree import ElementTree

__all__ = ['sanitize_svg']


# --- Przestrzenie nazw -------------------------------------------------------

SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'


# --- Limity (ochrona przed zadlawieniem sie na spreparowanym wejsciu) --------

# Powyzej tego rozmiaru nie probujemy nawet parsowac — realny SVG z kalkulatora
# ma kilkanascie-kilkadziesiat kB.
MAX_INPUT_LENGTH = 1_000_000
# Maksymalna glebokosc zagniezdzenia zachowanych elementow (chroni rekurencje
# serializatora przed wejsciem typu "<g>" x 100000). Przekroczenie = ODRZUCENIE
# calego dokumentu, nie ciche obciecie (patrz _DepthExceeded).
MAX_DEPTH = 60


class _DepthExceeded(Exception):
    """Wewnetrzny sygnal: dokument jest glebszy niz MAX_DEPTH."""


# --- Whitelisty --------------------------------------------------------------

# Nazwy elementow SVG sa case-sensitive (clipPath != clippath), wiec trzymamy
# kanoniczna pisownie i mapujemy na nia to, co przyszlo z wejscia.
ALLOWED_ELEMENTS = frozenset([
    'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
    'polygon', 'text', 'tspan', 'defs', 'clipPath', 'use', 'title', 'desc',
    'marker', 'pattern', 'mask', 'linearGradient', 'radialGradient', 'stop',
])
_ELEMENT_CANONICAL = dict((name.lower(), name) for name in ALLOWED_ELEMENTS)

# Elementy, ktore faktycznie cos rysuja. Jesli po sanityzacji nie zostanie ANI
# JEDEN z nich, zwracamy None zamiast pustego <svg> (fail-closed).
DRAWING_ELEMENTS = frozenset([
    'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
    'text', 'use',
])

# Elementy wycinane razem z cala zawartoscia — ich tresc nigdy nie moze
# wyladowac w wyniku (np. tekst skryptu albo HTML w foreignObject).
DANGEROUS_ELEMENTS = frozenset([
    'script', 'foreignobject', 'iframe', 'embed', 'object', 'style',
    'animate', 'animatetransform', 'animatemotion', 'animatecolor',
    'set', 'handler', 'discard', 'audio', 'video', 'image', 'feimage',
    'link', 'meta', 'base', 'form', 'input', 'button', 'textarea', 'html',
    'body', 'head',
])

ALLOWED_ATTRIBUTES = frozenset([
    # geometria
    'd', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
    'points', 'width', 'height', 'transform', 'viewBox', 'preserveAspectRatio',
    # prezentacja
    'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
    'stroke-dasharray', 'stroke-dashoffset', 'stroke-miterlimit', 'opacity',
    'fill-opacity', 'stroke-opacity', 'font-family', 'font-size',
    'font-weight', 'font-style', 'text-anchor', 'text-decoration',
    'dominant-baseline', 'letter-spacing',
    # fill-rule/clip-rule WYCINAJA otwory z ksztaltu (edges.js emituje
    # fill-rule="evenodd" na sciezce gornej powierzchni) — bez nich produkt
    # z wycieciami pokazuje sie klientowi jako lita plyta
    'fill-rule', 'clip-rule',
    # paint-order canvas2svg stawia na kazdej sciezce (obrys pod wypelnieniem);
    # vector-effect jest NIEAKTYWNY (nie niesie URL-i ani kodu)
    'paint-order', 'vector-effect',
    # UWAGA: 'visibility' i 'display' celowo NIE sa dozwolone. Pod katem URL-i
    # i kodu sa nieaktywne, ale nie pod katem WIDOCZNOSCI: edges.js w
    # buildEdgesSvgForSave() ustawia svgClone.style.visibility = 'hidden' przed
    # pomiarem getBBox(), a sciezka catch (gdy getBBox rzuci) nie zdejmuje tej
    # wlasciwosci — wtedy do bazy leci edges_svg ze style="visibility: hidden".
    # Przepuszczenie tej pary (choćby przez konwersje style -> atrybut)
    # zamienia podglad klienta w PUSTY prostokat. Sanityzator ma prawo cos
    # usunac, nie ma prawa wygasic calego rysunku.
    # strukturalne / pomocnicze
    'class', 'id', 'clip-path', 'mask', 'offset',
    'stop-color', 'stop-opacity', 'gradientUnits', 'patternUnits',
    'markerWidth', 'markerHeight', 'refX', 'refY', 'orient',
    # dozwolone WARUNKOWO — tylko wartosc bedaca fragmentem ("#id"),
    # patrz _value_is_safe()
    'href', 'xlink:href',
])
_ATTR_CANONICAL = dict((name.lower(), name) for name in ALLOWED_ATTRIBUTES)

# UWAGA: "xmlns" i "xmlns:xlink" NIE moga byc na whitescie. Dla normalnego
# ruchu bylyby wpisami martwymi (prawdziwe deklaracje konsumuje expat), a
# jedyna droga do nich jest atak: przy prefiksie zwiazanym z SVG_NS zapis
# s:xmlns przychodzi jako {SVG_NS}xmlns, po odcieciu URI zostaje gole "xmlns"
# i przenosi poddrzewo poza przestrzen SVG (namespace confusion). Deklaracje
# na wyjsciu doklada _render_document.

# Atrybuty odwolujace sie do zasobu — dopuszczamy wylacznie fragment "#id".
URL_ATTRIBUTES = frozenset(['href', 'xlink:href'])

# Wlasciwosci, ktore wolno przeniesc z inline `style` na atrybuty prezentacyjne.
# Przeciecie z ALLOWED_ATTRIBUTES jest wymuszone KONSTRUKCYJNIE (nie asercja,
# bo assert znika przy python -O): ze style nie da sie wprowadzic niczego,
# czego nie wolnoby wpisac wprost w atrybucie.
_STYLE_PROPERTY_CANDIDATES = frozenset([
    'fill', 'fill-opacity', 'fill-rule', 'clip-rule',
    'stroke', 'stroke-width', 'stroke-opacity', 'stroke-linecap',
    'stroke-linejoin', 'stroke-dasharray', 'stroke-dashoffset',
    'stroke-miterlimit', 'opacity', 'paint-order', 'vector-effect',
    'font-family', 'font-size', 'font-weight', 'font-style',
    'text-anchor', 'text-decoration', 'dominant-baseline', 'letter-spacing',
    'stop-color', 'stop-opacity',
])
# Przeciecie jest tez SIATKA BEZPIECZENSTWA: gdyby ktos dopisal tu wlasciwosc
# nieobecna w ALLOWED_ATTRIBUTES (jak wczesniej visibility/display), i tak nie
# wjedzie ona na wyjscie przez konwersje style -> atrybut.
STYLE_PROPERTIES = _STYLE_PROPERTY_CANDIDATES & ALLOWED_ATTRIBUTES


# --- Wyrazenia pomocnicze ----------------------------------------------------

# Biale znaki i znaki kontrolne usuwane PRZED sprawdzeniem wartosci — inaczej
# "java\tscript:" albo " JAVASCRIPT:" przechodzi bokiem.
_JUNK_CLASS = u'[\\s\\x00-\\x20\\x7f-\\xa0\\u200b-\\u200f\\u2028\\u2029\\ufeff]'
_JUNK_RE = re.compile(_JUNK_CLASS)
_LEADING_JUNK_RE = re.compile(u'^' + _JUNK_CLASS + u'+')
# Schematy wykonujace kod lub pozwalajace osadzic wlasny dokument.
_DANGEROUS_SCHEME_RE = re.compile(
    r'(?:javascript|vbscript|livescript|mocha|data|blob|filesystem):'
)
# Kazde wystapienie "url(" musi byc PELNYM url(#fragment) — patrz _value_is_safe.
_URL_OPEN_RE = re.compile(r'url\(')
_URL_FRAGMENT_RE = re.compile(r'url\((?:"#[^"()]*"|\'#[^\'()]*\'|#[^()"\']*)\)')
# Podmiana referencji przy id_prefix — dziala na wartosci SUROWEJ (nie
# znormalizowanej), zeby nie zgubic wielkosci liter w identyfikatorze.
# IGNORECASE jest OBOWIAZKOWE: _value_is_safe waliduje na wartosci
# zlowercasowanej, wiec fill="URL(#grad)" przechodzi jako referencja
# fragmentowa. Bez IGNORECASE id dostawalo prefiks, a odwolanie NIE — a funkcja
# CSS url() jest w przegladarce ASCII case-insensitive, wiec taka referencja
# albo wisi, albo trafia w cudzy element o tym samym id (dokladnie kolizja,
# przed ktora id_prefix ma bronic).
_URL_REF_RE = re.compile(r'(url\(\s*["\']?\s*)#', re.IGNORECASE)
# Escape CSS: "\HH..." (1-6 cyfr hex + opcjonalny JEDEN bialy znak) albo
# "\znak". Tokenizer CSS rozwija je PRZED rozpoznaniem funkcji i schematu,
# wiec bez rozwiniecia "\75 rl(" i "j\61 vascript:" to dla nas zwykly tekst,
# a dla przegladarki poprawny url-token / schemat.
_CSS_ESCAPE_RE = re.compile(r'\\(?:([0-9A-Fa-f]{1,6})[ \t\r\n\f]?|(.))', re.DOTALL)
_SVG_OPEN_RE = re.compile(r'<svg[\s/>]', re.IGNORECASE)
_SVG_CLOSE_RE = re.compile(r'</\s*svg\s*>', re.IGNORECASE)
# Prefiks id musi sam byc bezpiecznym poczatkiem nazwy XML.
_ID_PREFIX_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.\-]*$')
# "!important" w atrybucie prezentacyjnym jest nielegalny — obcinamy go,
# zeby nie unieważnił przeniesionej wartosci.
_STYLE_IMPORTANT_RE = re.compile(r'!\s*important\s*$', re.IGNORECASE)


# --- API ---------------------------------------------------------------------

def sanitize_svg(raw, id_prefix=None):
    """Zwraca bezpieczny markup SVG albo ``None``, jesli nie da sie oczyscic.

    Funkcja jest calkowicie defensywna: dowolne wejscie (None, liczba, bajty,
    smieci, 10 MB tekstu, obiekt rzucajacy z ``__len__``) konczy sie wynikiem
    ``str`` albo ``None``, nigdy wyjatkiem.

    ``id_prefix`` — gdy podany, kazdy ``id`` i kazde odwolanie do niego
    (``url(#...)``, ``href="#..."``) dostaje ten prefiks. Sluzy izolacji wielu
    SVG sklejonych w jeden dokument HTML. Musi pasowac do ``_ID_PREFIX_RE``,
    w przeciwnym razie zwracamy ``None`` (fail-closed: cicha rezygnacja z
    prefiksowania przywrocilaby kolizje, przed ktora wolajacy sie broni).
    """
    try:
        if id_prefix is not None:
            if not isinstance(id_prefix, str) or not _ID_PREFIX_RE.match(id_prefix):
                return None

        # Normalizacja wejscia MUSI byc w try — inaczej wyjatek z len()/replace()
        # /decode() na spreparowanym obiekcie wychodzi na zewnatrz mimo
        # kontraktu "nigdy nie rzuca".
        text = _coerce_to_text(raw)
        if text is None:
            return None

        root = _parse_root(text)
        if root is None:
            return None
        return _render_document(root, id_prefix)
    except Exception:
        # Sanityzator nie ma prawa wywrocic zapisu wyceny ani renderu strony.
        return None


# --- Wejscie -----------------------------------------------------------------

def _coerce_to_text(raw):
    """Sprowadza wejscie do stringa nadajacego sie do parsowania albo None."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except (UnicodeDecodeError, AttributeError):
            return None
    if not isinstance(raw, str):
        return None
    if len(raw) > MAX_INPUT_LENGTH:
        # Twardy limit — nie zadlawiamy sie na spreparowanym wejsciu.
        return None
    # NUL potrafi rozjechac parsery i bywa ignorowany przez przegladarki.
    text = raw.replace('\x00', '')
    if not text.strip():
        return None
    return text


def _parse_root(text):
    """Parsuje wejscie i zwraca element <svg> albo None.

    Najpierw proba na calosci. Jesli sie nie uda (albo korzeniem nie jest svg),
    probujemy jeszcze raz na wycinku od pierwszego "<svg" do ostatniego
    "</svg>" — to odcina deklaracje XML, DOCTYPE i smieci dookola.
    """
    lowered = text.lower()
    has_dtd = '<!doctype' in lowered or '<!entity' in lowered

    if not has_dtd:
        root = _try_parse(text)
        if root is not None and _local_name(root.tag) == 'svg':
            return root

    trimmed = _trim_to_svg(text)
    if trimmed is None:
        return None
    root = _try_parse(trimmed)
    if root is not None and _local_name(root.tag) == 'svg':
        return root
    return None


def _try_parse(text):
    try:
        return ElementTree.fromstring(text)
    except Exception:
        # ParseError, przekroczony limit rekurencji, nieznana encja — wszystko
        # traktujemy tak samo: nie udalo sie.
        return None


def _trim_to_svg(text):
    """Wycinek od pierwszego <svg do ostatniego </svg> albo None."""
    start_match = _SVG_OPEN_RE.search(text)
    if start_match is None:
        return None
    end_match = None
    for end_match in _SVG_CLOSE_RE.finditer(text):
        pass
    if end_match is None:
        return None
    start = start_match.start()
    end = end_match.end()
    if start >= end:
        return None
    return text[start:end]


# --- Nazwy -------------------------------------------------------------------

def _local_name(tag):
    """Nazwa lokalna, malymi literami: '{ns}Script' / 'svg:Script' -> 'script'."""
    if not isinstance(tag, str):
        return ''
    if tag.startswith('{'):
        tag = tag.partition('}')[2]
    return tag.rsplit(':', 1)[-1].lower()


def _split_attribute_name(raw_name):
    """Sprowadza nazwe atrybutu do postaci 'prefiks:lokalna' albo None.

    Zwraca krotke ``(lowered, prefix, local)``; ``None`` gdy nazwa pochodzi
    z obcej przestrzeni nazw (xml:*, xhtml:*, ...) i nie mamy jej przepuszczac.
    """
    if not isinstance(raw_name, str) or not raw_name:
        return None

    name = raw_name
    if name.startswith('{'):
        uri, _, local = name[1:].partition('}')
        if uri == XLINK_NS:
            name = 'xlink:' + local
        elif uri == SVG_NS:
            name = local
        else:
            # xml:*, xhtml:*, dowolna obca przestrzen nazw — nie przepuszczamy
            return None

    lowered = name.lower()
    if ':' in lowered:
        prefix, _, local_part = lowered.rpartition(':')
    else:
        prefix, local_part = '', lowered
    return (lowered, prefix, local_part)


def _attribute_name(raw_name):
    """Kanoniczna nazwa dozwolonego atrybutu albo None (odrzucamy)."""
    parts = _split_attribute_name(raw_name)
    if parts is None:
        return None
    lowered, prefix, local_part = parts

    # Handlery zdarzen — bezwzglednie, niezaleznie od wielkosci liter
    # i ewentualnego prefiksu (onload, ONLOAD, svg:onclick, ...).
    if lowered.startswith('on') or local_part.startswith('on'):
        return None
    # style nie idzie do wyniku jako atrybut — jest KONWERTOWANY na atrybuty
    # prezentacyjne w _render_attributes (patrz _is_style_attribute).
    if local_part == 'style':
        return None
    # Deklaracje przestrzeni nazw odtwarza wylacznie _render_document.
    if local_part == 'xmlns' or prefix == 'xmlns':
        return None

    return _ATTR_CANONICAL.get(lowered)


def _is_style_attribute(raw_name):
    """True dla inline `style` (bez prefiksu albo w przestrzeni SVG)."""
    parts = _split_attribute_name(raw_name)
    if parts is None:
        return False
    lowered, prefix, local_part = parts
    if lowered.startswith('on') or local_part.startswith('on'):
        return False
    return local_part == 'style'


# --- Wartosci ----------------------------------------------------------------

def _expand_css_escapes(value):
    """Rozwija escape'y CSS: "\\75 rl(" -> "url(", "j\\61 vascript:" -> "javascript:".

    Wybor rozwiazania (F4): rozwijamy escape'y, a NIE odrzucamy hurtem kazdej
    wartosci z backslashem. Powod: backslash jest legalny w wartosciach, ktore
    realnie wystepuja (np. font-family z nazwa zawierajaca escapowana spacje),
    a odrzucenie wartosci to u nas utrata atrybutu — przy `d` albo `fill`
    oznacza to widoczny defekt podgladu. Rozwiniecie daje ten sam efekt
    bezpieczenstwa (kontrole widza to, co zobaczy tokenizer CSS) bez
    kasowania poprawnych wartosci. Wyjatek stanowia href/xlink:href — tam
    escape'ow NIKT nie rozwija (to URI, nie CSS), wiec ich obsluga jest osobna,
    patrz _value_is_safe.
    """
    if '\\' not in value:
        return value

    def _replace(match):
        hex_digits = match.group(1)
        if hex_digits is None:
            return match.group(2)
        code = int(hex_digits, 16)
        # Zakresy, ktorych chr() nie uniesie albo ktore CSS zamienia na U+FFFD.
        if code == 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            return u'�'
        return chr(code)

    # Jeden przebieg — dokladnie tak, jak robi to tokenizer CSS (rozwiniety
    # backslash nie jest ponownie interpretowany jako poczatek escape'u).
    return _CSS_ESCAPE_RE.sub(_replace, value)


def _normalize_value(value):
    """Wartosc po rozwinieciu escape'ow CSS, bez bialych znakow, malymi literami."""
    return _JUNK_RE.sub('', _expand_css_escapes(value)).lower()


def _value_is_safe(name, value):
    normalized = _normalize_value(value)

    # Encje liczbowe sa juz rozwiniete przez parser XML (&#106;avascript: ->
    # javascript:), wiec porownanie tekstowe wystarcza.
    if _DANGEROUS_SCHEME_RE.search(normalized):
        return False
    # Legacy IE, ale nic nas nie kosztuje.
    if 'expression(' in normalized:
        return False

    if name in URL_ATTRIBUTES:
        # href/xlink:href konsumuje parser URI, ktory NIE rozwija escape'ow CSS
        # — "\23 a" to dla niego adres wzgledny, a nie fragment "#a". Gdybysmy
        # ocenili wartosc po rozwinieciu, przepuscilibysmy cos innego, niz
        # potem pobierze przegladarka. Tu wiec: zero backslashy, a decyzja na
        # wartosci nierozwinietej.
        if '\\' in value:
            return False
        # Tylko odwolanie wewnatrz tego samego dokumentu.
        return _JUNK_RE.sub('', value).lower().startswith('#')

    if 'url(' in normalized:
        # Walidacja POZYTYWNA: KAZDE "url(" musi byc pelnym url(#fragment).
        # Szukanie wzorca url\(([^)]*)\) bylo przepustka — przy
        # fill="url(https://evil/x" (bez domykajacego nawiasu, dla przegladarki
        # wciaz poprawny <url-token>, a dla WeasyPrint pobranie z sieci)
        # findall nie zwracal nic i funkcja spadala do return True.
        if len(_URL_OPEN_RE.findall(normalized)) != len(_URL_FRAGMENT_RE.findall(normalized)):
            return False

    return True


def _parse_style(raw_style):
    """Rozklada inline `style` na liste par (atrybut, wartosc) do emisji.

    Caly wyglad edges_svg siedzi WYLACZNIE w inline style (edges.js ustawia
    fill/stroke/stroke-width przez el.style.setProperty), a publiczna strona
    nie ma regul .edges-face/.edges-line — sa tylko w wewnetrznym quotes.css.
    Wyciecie style zostawialo path bez fill (renderowany na czarno) i line bez
    stroke (niewidoczna), a w trybie advanced kolor jest JEDYNYM nosnikiem
    informacji, ktora krawedz jest zaokraglona, a ktora fazowana.

    Dlatego atrybutu style nie przepuszczamy, tylko go konwertujemy: emitujemy
    wylacznie wlasciwosci z STYLE_PROPERTIES (czyli i tak obecne na
    ALLOWED_ATTRIBUTES), kazda po tym samym _value_is_safe. Reszta (behavior,
    -moz-binding, content, width: expression(...)) wypada.
    """
    result = []
    seen = {}
    for declaration in raw_style.split(';'):
        prop, separator, value = declaration.partition(':')
        if not separator:
            continue
        prop = prop.strip().lower()
        if prop not in STYLE_PROPERTIES:
            continue
        value = _STYLE_IMPORTANT_RE.sub('', value).strip()
        if not value:
            continue
        if not _value_is_safe(prop, value):
            continue
        canonical = _ATTR_CANONICAL.get(prop)
        if canonical is None:
            continue
        if canonical in seen:
            # W CSS ostatnia deklaracja wygrywa (pozycje zostawiamy pierwsza,
            # zeby wynik byl deterministyczny i idempotentny).
            result[seen[canonical]] = (canonical, value)
        else:
            seen[canonical] = len(result)
            result.append((canonical, value))
    return result


def _apply_id_prefix(name, value, prefix):
    """Prefiksuje identyfikator albo odwolanie do niego; None = wyrzuc atrybut.

    Publiczna strona sklada WIELE produktow w jeden dokument HTML, a edges_svg
    kazdego z nich ma id="edgesSvg" i clipPath-y o tych samych id. clip-path
    ="url(#id)" rozwiazuje sie w HTML DOKUMENTOWO, do pierwszego takiego id —
    bez prefiksowania jeden ksztalt zostaje przyciety maska drugiego.
    """
    if name == 'id':
        return prefix + value.strip()

    if name in URL_ATTRIBUTES:
        stripped = _LEADING_JUNK_RE.sub('', value).strip()
        if not stripped.startswith('#'):
            # _value_is_safe juz to przepuscil (po normalizacji), ale skoro nie
            # umiemy bezpiecznie przepisac — nie przepuszczamy wcale.
            return None
        return '#' + prefix + stripped[1:]

    if 'url(' in value.lower():
        return _URL_REF_RE.sub(lambda match: match.group(1) + '#' + prefix, value)

    return value


# --- Serializacja ------------------------------------------------------------

def _escape_text(text):
    # W TRESCI parser XML normalizuje znaki konca linii (CR i CRLF -> LF), wiec
    # doslowny CR nie przezylby ponownego parsowania. LF i TAB w tresci sa
    # zachowywane doslownie, tych nie ruszamy.
    return escape(text, quote=False).replace('\r', '&#13;')


# W WARTOSCI ATRYBUTU parser XML zamienia kazdy bialy znak na spacje
# (normalizacja atrybutu), a &#10; & spolka rozwija do prawdziwego znaku.
# Serializator kodujacy tylko & < > " lamal wiec dwie rzeczy naraz:
# (a) sanitize(sanitize(x)) != sanitize(x) — drugi przebieg widzial juz spacje,
# (b) sciezka HTML (innerHTML, bez normalizacji) i sciezka XML (WeasyPrint,
#     z normalizacja) czytaly INNE wartosci d/transform/id z tego samego stringa.
_ATTRIBUTE_WHITESPACE = (('\r', '&#13;'), ('\n', '&#10;'), ('\t', '&#9;'))


def _escape_attribute(value):
    # Kolejnosc jest istotna: najpierw escape() (zamienia & na &amp;), dopiero
    # potem wstawiamy encje — inaczej ich "&" zostaloby podwojnie zakodowane.
    escaped = escape(value, quote=True)
    for char, entity in _ATTRIBUTE_WHITESPACE:
        escaped = escaped.replace(char, entity)
    return escaped


# --- Cykle <use> -------------------------------------------------------------

def _element_id(node):
    """Wartosc atrybutu ``id`` elementu (po kanonizacji nazwy) albo None."""
    for raw_name, raw_value in node.attrib.items():
        if _attribute_name(raw_name) == 'id':
            return ('' if raw_value is None else str(raw_value)).strip()
    return None


def _fragment_target(value):
    """Identyfikator z odwolania "#id" albo None, gdy to nie jest fragment."""
    stripped = _LEADING_JUNK_RE.sub('', value).strip()
    if not stripped.startswith('#'):
        return None
    return stripped[1:].strip()


def _use_target(node):
    """Cel ``<use href="#id">`` albo None."""
    for raw_name, raw_value in node.attrib.items():
        name = _attribute_name(raw_name)
        if name in URL_ATTRIBUTES:
            target = _fragment_target('' if raw_value is None else str(raw_value))
            if target:
                return target
    return None


def _collect_use_edges(node, ancestors, edges, depth):
    """Buduje graf ``id przodka -> id celu <use>`` z poddrzewa.

    Rozwiniecie ``<use href="#X">`` wstawia w to miejsce KLON calego poddrzewa
    X, wiec kazdy przodek z ``id`` "zawiera" to odwolanie: stad krawedz od
    kazdego przodka, nie tylko od najblizszego.
    """
    if depth > MAX_DEPTH:
        return
    local = _local_name(node.tag)
    if not local or local in DANGEROUS_ELEMENTS:
        # Poddrzewo i tak nie trafi na wyjscie.
        return

    canonical = _ELEMENT_CANONICAL.get(local)
    own_id = None
    if canonical is not None:
        # Element spoza whitelisty traci tag RAZEM z atrybutami, wiec jego id
        # nie istnieje na wyjsciu i nie moze byc celem <use>.
        own_id = _element_id(node)
        if canonical == 'use':
            target = _use_target(node)
            if target:
                # Zrodlem krawedzi jest tez WLASNE id elementu <use> —
                # <use id="u" href="#u"/> rozwija sam siebie.
                sources = ancestors + [own_id] if own_id else ancestors
                for source in sources:
                    edges.setdefault(source, set()).add(target)

    child_ancestors = ancestors + [own_id] if own_id else ancestors
    for child in list(node):
        _collect_use_edges(child, child_ancestors, edges, depth + 1)


def _divergent_use_targets(edges):
    """Zbior id, ktorych rozwiniecie przez <use> nigdy sie nie konczy.

    Sam MAX_DEPTH tego nie lapie — chroni przed statycznym zagniezdzeniem, a
    cykl <use> jest PLASKI w zrodle i rozwija sie dopiero w rendererze.
    ``<g id="a"><use href="#a"/></g>`` to 170 bajtow, ktore wyczerpuja stos
    cairosvg/WeasyPrint przy generowaniu PDF.

    DFS jest iteracyjny (nie rekurencyjny), bo lancuch a1->a2->...->aN buduje
    sie w zrodle plasko i moze miec tysiace ogniw.
    """
    white, gray, black = 0, 1, 2
    color = {}
    divergent = set()

    for start in list(edges.keys()):
        if color.get(start, white) != white:
            continue
        color[start] = gray
        stack = [[start, list(edges.get(start, ())), 0]]
        while stack:
            frame = stack[-1]
            node_id, successors, index = frame
            if index >= len(successors):
                stack.pop()
                color[node_id] = black
                continue
            frame[2] = index + 1
            nxt = successors[index]
            nxt_color = color.get(nxt, white)
            if nxt_color == gray or nxt in divergent:
                # Krawedz wsteczna (cykl) albo dojscie do wezla juz rozbieznego
                # — cala biezaca sciezka DFS rozwija sie w nieskonczonosc.
                divergent.add(nxt)
                for pending in stack:
                    divergent.add(pending[0])
            elif nxt_color == white:
                color[nxt] = gray
                stack.append([nxt, list(edges.get(nxt, ())), 0])

    return divergent


def _render_attributes(attrib, state, local=None):
    ordered = []
    values = {}
    style_value = None

    for raw_name, raw_value in attrib.items():
        value = '' if raw_value is None else str(raw_value)

        if _is_style_attribute(raw_name):
            if style_value is None:
                style_value = value
            continue

        name = _attribute_name(raw_name)
        if name is None:
            continue
        if not _value_is_safe(name, value):
            continue
        if name in values:
            # W XML nazwy sa case-sensitive, wiec <rect x="1" X="2"/> to dwa
            # legalne atrybuty; ta sama nazwa kanoniczna przychodzi tez przez
            # drugi prefiks zwiazany z SVG_NS (s:fill). Emisja obu daje
            # duplikat atrybutu = fatal error XML: WeasyPrint/cairosvg w
            # sciezce PDF sie wywala, a sanitize_svg(sanitize_svg(x)) -> None.
            # Pierwszy (z przechodzacych) wygrywa.
            continue
        values[name] = value
        ordered.append(name)

    if style_value:
        for prop, value in _parse_style(style_value):
            if prop not in values:
                ordered.append(prop)
            # CSS-owo inline style wygrywa nad atrybutem prezentacyjnym,
            # wiec nadpisujemy wartosc, zachowujac pozycje atrybutu.
            values[prop] = value

    id_prefix = state.get('id_prefix')
    blocked = state.get('blocked_use_targets')
    parts = []
    for name in ordered:
        value = values[name]
        if blocked and local == 'use' and name in URL_ATTRIBUTES:
            # Odwolanie zamykajace cykl rozwijania <use>. Usuwamy SAM ATRYBUT,
            # element zostaje — nie mamy powodu kasowac geometrii, a bez href
            # <use> jest po prostu pusty.
            target = _fragment_target(value)
            if target is not None and target in blocked:
                continue
        if id_prefix:
            value = _apply_id_prefix(name, value, id_prefix)
            if value is None:
                continue
        if name.startswith('xlink:'):
            state['uses_xlink'] = True
        parts.append(' %s="%s"' % (name, _escape_attribute(value)))
    return ''.join(parts)


def _render_children(node, depth, state):
    parts = []
    if node.text:
        parts.append(_escape_text(node.text))
    for child in list(node):
        parts.append(_render_element(child, depth + 1, state))
        if child.tail:
            parts.append(_escape_text(child.tail))
    return ''.join(parts)


def _render_element(node, depth, state):
    if depth >= MAX_DEPTH:
        # Ciche obciecie (inner = "" powyzej limitu) zwracalo kadlubek udajacy
        # poprawny podglad. Przekroczenie limitu = odrzucenie dokumentu.
        raise _DepthExceeded()

    local = _local_name(node.tag)

    # Komentarze i instrukcje przetwarzania maja tag bedacy funkcja — pomijamy.
    if not local:
        return ''

    if local in DANGEROUS_ELEMENTS:
        # Element + cale poddrzewo (tresc skryptu, HTML w foreignObject, ...).
        return ''

    inner = _render_children(node, depth, state)

    canonical = _ELEMENT_CANONICAL.get(local)
    if canonical is None:
        # Element nieznany, ale nieszkodliwy (np. <a>, <switch>): zdejmujemy
        # tag razem z jego atrybutami, tresc zostaje.
        return inner

    # has_drawing liczymy WYLACZNIE po DRAWING_ELEMENTS. Wczesniejszy warunek
    # "albo <g> z niepusta trescia" byl obejsciem calego fail-closed: `inner` to
    # dowolny niepusty string, wiec zaliczala sie spacja, luzny tekst, <title>,
    # <desc> czy <defs> z gradientem — a wtedy konsument dostawal truthy SVG
    # bez ani jednego elementu rysujacego, czyli pusta ramke. Klauzula byla przy
    # tym zbedna: dzieci rysujace ustawiaja te flage same.
    if canonical in DRAWING_ELEMENTS:
        state['has_drawing'] = True

    attributes = _render_attributes(node.attrib, state, canonical)
    if inner:
        return '<%s%s>%s</%s>' % (canonical, attributes, inner, canonical)
    return '<%s%s/>' % (canonical, attributes)


def _render_document(root, id_prefix=None):
    edges = {}
    _collect_use_edges(root, [], edges, 0)

    state = {
        'uses_xlink': False,
        'has_drawing': False,
        'id_prefix': id_prefix,
        'blocked_use_targets': _divergent_use_targets(edges),
    }
    attributes = _render_attributes(root.attrib, state, 'svg')
    inner = _render_children(root, 1, state)

    if not state['has_drawing']:
        # Pusty "<svg ...></svg>" jest wartoscia truthy — konsument uznalby, ze
        # podglad istnieje, i wyrenderowal pusta ramke. Lepiej brak podgladu.
        return None

    # Deklaracje xmlns sa konsumowane przez parser, wiec odtwarzamy je sami
    # (i tylko my — z whitelisty atrybutow xmlns jest wykluczony).
    namespaces = ' xmlns="%s"' % SVG_NS
    if state['uses_xlink']:
        namespaces += ' xmlns:xlink="%s"' % XLINK_NS

    return '<svg%s%s>%s</svg>' % (namespaces, attributes, inner)
