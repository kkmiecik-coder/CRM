-- Migracja: Dodanie kolumn width_min/width_max do tabeli prices
-- Szerokość wpływa na cenę - wąskie produkty (<10cm) mogą mieć inną cenę niż szerokie

ALTER TABLE prices
  ADD COLUMN width_min DECIMAL(10,2) NOT NULL DEFAULT 0.00 AFTER length_max,
  ADD COLUMN width_max DECIMAL(10,2) NOT NULL DEFAULT 999.99 AFTER width_min;

-- Istniejące rekordy dotyczą produktów o szerokości 10-120 cm
UPDATE prices SET width_min = 10.00, width_max = 120.00;
