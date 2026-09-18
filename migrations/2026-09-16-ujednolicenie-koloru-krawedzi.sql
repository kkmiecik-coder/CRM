-- Migracja: ujednolicenie koloru aktywnych krawedzi w zapisanych edge_svg
-- Data: 2026-09-16
--
-- Tabela: prod_products (kolumna edge_svg).
--
-- DLACZEGO. edge_svg powstaje dwiema sciezkami (sync_service.py):
--   :3112 — detail.edges_svg z wyceny, serializowany z DOM kalkulatora,
--           aktywne krawedzie #ED6B24 (edges.css:161);
--   :3038 — fallback EdgeSvgGenerator dla zamowien sklepowych bez wyceny,
--           ktory az do dzis malowal aktywne krawedzie #f59e0b.
-- Port w Pythonie wzial inny pomarancz niz CSS, ktory portowal. Kod poprawiony
-- razem z ta migracja (edge_svg_generator.py: ACTIVE_STROKE, LABEL_BG_ACTIVE),
-- ale historyczne SVG maja kolor zapieczony w tresci — sam kod ich nie ruszy.
--
-- Nie kosmetyka: tablet stanowiska renderuje edge_svg przyslane z serwera,
-- wiec bez backfillu operator zobaczylby na jednym ekranie pozycje w dwoch
-- roznych pomaranczach, zaleznie od tego, czy zamowienie przyszlo z wyceny
-- czy ze sklepu.
--
-- ZASIEG. Tylko prod_products.edge_svg. Sprawdzone na kopii produkcji:
-- prod_products.shape_svg, quote_items_details.edges_svg i .shape_svg nie
-- zawieraja #f59e0b — tamte generuje front, ktory mial poprawny kolor od zawsze.
--
-- IDEMPOTENTNOSC. WHERE trafia w STARA wartosc, wiec drugi przebieg obejmuje
-- zero wierszy. REPLACE podmienia wszystkie wystapienia w rekordzie: stroke
-- linii i tlo labelki, po 1 na kazda aktywna krawedz.
--
-- Grubosc kreski (Python 2.5 vs front 3) zostaje rozna — swiadomie poza
-- zakresem, ujednolicamy wylacznie kolor.

UPDATE prod_products
   SET edge_svg = REPLACE(edge_svg, '#f59e0b', '#ED6B24')
 WHERE edge_svg LIKE '%#f59e0b%';
