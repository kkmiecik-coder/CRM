-- Migracja: backfill koloru BEZ BN-125/09 w pozycjach produkcyjnych
-- Data: 2026-09-17
--
-- Tabela: prod_products (parsed_finish_color, parsed_finish_color_type).
--
-- DLACZEGO. Regex wyciagajacy kod koloru z nazwy pozycji wymagal, zeby kod
-- zaczynal sie od dwoch cyfr (parser_service.py, _parse_lacquer_finish_structured).
-- Osiem kolorow palety ma format "22-05" i przechodzilo; dziewiaty ma
-- "BN-125/09" i nie przechodzil NIGDY — dopasowanie musialoby trafic w "25/09",
-- a tam zamiast spacji stoi "1" z "BN-125". Regex poprawiony w tym samym
-- commicie, ale to dotyczy wylacznie nowych zamowien; rekordy juz w bazie
-- maja NULL i sam kod ich nie ruszy.
--
-- Nie kosmetyka: parsed_finish_color trafia na DRUKOWANA ETYKIETE naklejana
-- na sztuke (label_print_service.py) oraz do pola finish.color w API mobilnym
-- (mobile_api_service.py), czyli na tablet lakierni. W chwili pisania cztery
-- z dziewieciu sztuk stoja w statusie czeka_na_lakiernie bez koloru — lakiernik
-- nie ma z czego odczytac, czym malowac.
--
-- SEKCJA 2 TO OSOBNY DEFEKT, cieższy. Dwie z tych dziewieciu pozycji parser
-- sklasyfikowal jako lakier BEZBARWNY, mimo ze nazwa mowi wprost o kolorze:
--   id 2150 (738_1)  — nazwa zawiera wczesniej "lakierowany bezbarwny",
--                      parser lapie to zamiast pozniejszego "barwnie"
--   id 3202 (1286_1) — nazwa nie zawiera slowa "barwnie" w ogole
--                      ("lakierowana Beż BN-125/09 matowy")
-- Poprawka regexa ich NIE naprawia, bo nie docieraja do galezi koloru.
-- 1286_1 stoi w kolejce lakierni jako bezbarwny — czyli rekord mowi "lakier
-- bezbarwny" o sztuce, ktora ma byc bezowa. Przyczyne w parserze zostawiamy
-- do osobnego zadania (dotyka klasyfikacji 3600 pozycji); tutaj prostujemy
-- wylacznie te dwa rekordy, bo ich nazwy nie pozostawiaja watpliwosci.
--
-- ZASIEG. Sprawdzone na produkcji: 9 pozycji zawiera "BN-125", wszystkie
-- dziewiec to ten sam kolor, zaden inny wariant "BN-" nie wystepuje.
--
-- IDEMPOTENTNOSC. Kazdy UPDATE ma warunek na STARA wartosc (NULL / bezbarwnie),
-- wiec drugi przebieg obejmuje zero wierszy.

-- 1. Kolor — wszystkie dziewiec pozycji.
UPDATE prod_products
   SET parsed_finish_color = 'BEŻ BN-125/09'
 WHERE original_product_name LIKE '%BN-125/09%'
   AND parsed_finish_color IS NULL;

-- 2. Typ koloru — dwie pozycje blednie oznaczone jako lakier bezbarwny.
UPDATE prod_products
   SET parsed_finish_color_type = 'barwnie'
 WHERE original_product_name LIKE '%BN-125/09%'
   AND parsed_finish_color_type = 'bezbarwnie';
