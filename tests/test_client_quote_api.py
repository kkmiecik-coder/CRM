# -*- coding: utf-8 -*-
"""
Testy serializacji danych dla PUBLICZNEJ strony wyceny /quotes/c/<token>.

Sprawdzamy czystą logikę z modules/quotes/routers.py:
- build_client_finishing_entry — biała lista pól (bez danych wewnętrznych),
  podgląd kształtu (shape/shape_svg) i SVG przepuszczone przez sanitizer,
- build_edges_config_with_labels — serwerowe etykiety krawędzi (też dla
  kształtów nieregularnych i krawędzi wycięć),
- flatten_costs_for_template — kwoty dla modala akceptacji.

Testujemy funkcje bezpośrednio na obiektach SimpleNamespace (jak
tests/test_edge_name_generator.py), bez podnoszenia Flaska ani bazy.
"""
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SANITIZER_PATH = os.path.join(_ROOT, "modules", "quotes", "services", "svg_sanitizer.py")

if not os.path.exists(_SANITIZER_PATH):
    # Sanitizer powstaje w równoległym zadaniu. Dopóki go nie ma, podstawiamy
    # minimalną atrapę zgodną z kontraktem (sanitize_svg(raw) -> str | None),
    # żeby testy weryfikowały PODPIĘCIE sanitizera w serializerze.
    # Gdy prawdziwy moduł trafi do repo, atrapa nie zostanie użyta.
    _stub = types.ModuleType("modules.quotes.services.svg_sanitizer")

    def _sanitize_svg(raw):
        if raw is None or not str(raw).strip():
            return None
        return re.sub(r"(?is)<script.*?</script>", "", str(raw))

    _stub.sanitize_svg = _sanitize_svg
    sys.modules["modules.quotes.services.svg_sanitizer"] = _stub

from types import SimpleNamespace  # noqa: E402

from modules.quotes import routers  # noqa: E402

build_client_finishing_entry = routers.build_client_finishing_entry
build_edges_config_with_labels = routers.build_edges_config_with_labels
flatten_costs_for_template = routers.flatten_costs_for_template
calculate_costs_with_vat = routers.calculate_costs_with_vat


CLEAN_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
DIRTY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<script>alert("xss")</script><rect width="10" height="10"/></svg>'
)

# Pola wewnętrzne, które NIE mogą wyjść na publiczną stronę klienta
INTERNAL_FIELDS = (
    "id",
    "quote_id",
    "product_type",
    "baselinker_order_product_id",
    "round_surcharge_netto",
    "round_surcharge_brutto",
)


def _detail(**overrides):
    """Atrapa QuoteItemDetails — komplet pól, które czyta serializer."""
    data = dict(
        id=123,
        quote_id=456,
        product_index=0,
        finishing_type="Lakierowanie",
        finishing_variant="Bezbarwne",
        finishing_color="Brak",
        finishing_gloss_level="Matowy",
        finishing_price_netto=100,
        finishing_price_brutto=123,
        quantity=2,
        edges_config=[{"letter": "A", "type": "round", "r_value": 5}],
        edges_type="round",
        edges_mode="basic",
        edges_r_value=5,
        edges_angle_value=45,
        edges_price_netto=10,
        edges_price_brutto=12.3,
        edges_svg=CLEAN_SVG,
        shape="irregular",
        shape_svg=CLEAN_SVG,
        lamella_direction=45,
        cut_to_size=True,
        # Pola wewnętrzne — muszą zostać w bazie, nie w odpowiedzi publicznej
        baselinker_order_product_id=987,
        round_surcharge_netto=50,
        round_surcharge_brutto=61.5,
        product_type="blaty",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


class TestSerializerPolPublicznych:
    def test_zwraca_nowe_klucze_ksztaltu(self):
        entry = build_client_finishing_entry(_detail())

        assert entry["shape"] == "irregular"
        assert entry["shape_svg"] is not None
        assert entry["lamella_direction"] == 45
        assert entry["edges_angle_value"] == 45

    def test_zachowuje_dotychczasowe_pola(self):
        entry = build_client_finishing_entry(_detail())

        assert entry["product_index"] == 0
        assert entry["finishing_type"] == "Lakierowanie"
        assert entry["finishing_price_netto"] == 100.0
        assert entry["edges_price_brutto"] == 12.3
        assert entry["quantity"] == 2
        assert entry["edges_mode"] == "basic"
        assert entry["cut_to_size"] is True

    def test_nie_wystawia_pol_wewnetrznych(self):
        entry = build_client_finishing_entry(_detail())

        for field in INTERNAL_FIELDS:
            assert field not in entry, f"pole wewnętrzne {field} wyciekło na stronę klienta"

    def test_brak_ksztaltu_nie_wywala(self):
        entry = build_client_finishing_entry(
            _detail(shape=None, shape_svg=None, edges_svg=None, lamella_direction=None)
        )

        assert entry["shape"] is None
        assert entry["shape_svg"] is None
        assert entry["edges_svg"] is None
        assert entry["lamella_direction"] is None

    def test_cut_to_size_null_domyslnie_true(self):
        entry = build_client_finishing_entry(_detail(cut_to_size=None))
        assert entry["cut_to_size"] is True


class TestSanitizerSvg:
    def test_oba_svg_ida_przez_sanitizer(self, monkeypatch):
        # Podmieniamy sanitizer na znacznik — dowód, że serializer NIE oddaje surowego SVG
        monkeypatch.setattr(routers, "sanitize_svg", lambda raw: "OCZYSZCZONE::{}".format(raw))

        entry = build_client_finishing_entry(_detail(shape_svg="<svg/>", edges_svg="<svg id='e'/>"))

        assert entry["shape_svg"] == "OCZYSZCZONE::<svg/>"
        assert entry["edges_svg"] == "OCZYSZCZONE::<svg id='e'/>"

    def test_script_nie_przechodzi_do_klienta(self):
        entry = build_client_finishing_entry(_detail(shape_svg=DIRTY_SVG, edges_svg=DIRTY_SVG))

        assert "script" not in (entry["shape_svg"] or "").lower()
        assert "script" not in (entry["edges_svg"] or "").lower()
        assert "alert" not in (entry["shape_svg"] or "").lower()

    def test_pusty_svg_daje_none(self):
        entry = build_client_finishing_entry(_detail(shape_svg="   ", edges_svg=""))

        assert entry["shape_svg"] is None
        assert entry["edges_svg"] is None

    def test_blad_sanitizera_nie_wywala_serializacji(self, monkeypatch):
        def _boom(raw):
            raise ValueError("uszkodzony SVG")

        monkeypatch.setattr(routers, "sanitize_svg", _boom)

        entry = build_client_finishing_entry(_detail())

        assert entry["shape_svg"] is None
        assert entry["edges_svg"] is None
        # reszta danych nadal się serializuje
        assert entry["finishing_type"] == "Lakierowanie"


class TestEtykietyKrawedzi:
    def test_krawedz_ksztaltu_nieregularnego(self):
        out = build_edges_config_with_labels([{"letter": "G1", "type": "round", "r_value": 5}])

        assert out[0]["label"] == "Krawędź 1"
        # oryginalne pola zostają nietknięte
        assert out[0]["letter"] == "G1"
        assert out[0]["r_value"] == 5

    def test_krawedz_wyciecia(self):
        out = build_edges_config_with_labels([{"letter": "H1.G2", "type": "chamfer"}])

        assert out[0]["label"] == "Wycięcie 1, góra 2"

    def test_prostokat_dostaje_czytelna_nazwe(self):
        out = build_edges_config_with_labels([
            {"letter": "A"},
            {"letter": "N4"},
        ])

        # 'A' nie jest znane translatorowi ID krawędzi — bierzemy nazwę z definicji
        assert out[0]["label"] == "Góra przednia (długość)"
        assert out[1]["label"] == "Narożnik 4"

    def test_wszystkie_wpisy_dostaja_label(self):
        out = build_edges_config_with_labels([
            {"letter": "G1"},
            {"letter": "D2"},
            {"letter": "H2.P3"},
        ])

        assert len(out) == 3
        assert all("label" in e for e in out)

    def test_brak_letter_nie_wywala(self):
        out = build_edges_config_with_labels([
            {"type": "round", "r_value": 3},
            {"letter": "G1"},
        ])

        assert len(out) == 2
        assert "label" not in out[0]
        assert out[0]["type"] == "round"
        assert out[1]["label"] == "Krawędź 1"

    def test_blad_translatora_nie_wywala(self, monkeypatch):
        def _boom(letter):
            raise RuntimeError("translator padł")

        monkeypatch.setattr(routers, "human_edge_label", _boom)

        out = build_edges_config_with_labels([{"letter": "G1", "type": "round"}])

        assert len(out) == 1
        assert "label" not in out[0]
        assert out[0]["letter"] == "G1"

    def test_nietypowe_wejscie_przechodzi_bez_zmian(self):
        assert build_edges_config_with_labels(None) is None
        assert build_edges_config_with_labels("KG") == "KG"
        assert build_edges_config_with_labels([]) == []
        assert build_edges_config_with_labels(["G1"]) == ["G1"]

    def test_nie_mutuje_wejscia(self):
        source = [{"letter": "G1"}]
        build_edges_config_with_labels(source)

        assert "label" not in source[0]

    def test_serializer_dopisuje_etykiety(self):
        entry = build_client_finishing_entry(
            _detail(edges_config=[{"letter": "H1.G2"}, {"letter": "G1"}])
        )

        assert [e["label"] for e in entry["edges_config"]] == ["Wycięcie 1, góra 2", "Krawędź 1"]


class TestKosztyDlaSzablonu:
    def test_plaskie_totale_dla_modala(self):
        costs = calculate_costs_with_vat(1000.0, 100.0, 123.0)
        flat = flatten_costs_for_template(costs)

        assert flat["total_netto"] == "1200.00"
        assert flat["total_vat"] == "276.00"
        assert flat["total_brutto"] == "1476.00"

    def test_zachowuje_strukture_zagniezdzona(self):
        costs = calculate_costs_with_vat(1000.0, 0.0, 0.0)
        flat = flatten_costs_for_template(costs)

        assert flat["total"]["netto"] == 1000.0
        assert flat["products"]["brutto"] == 1230.0

    def test_brak_kosztow_daje_zera(self):
        flat = flatten_costs_for_template(None)

        assert flat["total_netto"] == "0.00"
        assert flat["total_vat"] == "0.00"
        assert flat["total_brutto"] == "0.00"
