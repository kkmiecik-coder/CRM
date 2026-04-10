-- Przebudowa systemu wykończenia: 4 nowe kolumny strukturalne
ALTER TABLE prod_items ADD COLUMN parsed_finish_type VARCHAR(20) DEFAULT 'surowe' NOT NULL;
ALTER TABLE prod_items ADD COLUMN parsed_finish_color_type VARCHAR(20) DEFAULT NULL;
ALTER TABLE prod_items ADD COLUMN parsed_finish_gloss VARCHAR(20) DEFAULT NULL;
ALTER TABLE prod_items ADD COLUMN parsed_finish_color VARCHAR(50) DEFAULT NULL;
