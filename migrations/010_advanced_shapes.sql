ALTER TABLE quote_items_details MODIFY COLUMN shape VARCHAR(50) DEFAULT 'rectangular';
ALTER TABLE quote_items_details ADD COLUMN shape_data TEXT NULL AFTER round_surcharge_brutto;
ALTER TABLE quote_items_details ADD COLUMN shape_svg TEXT NULL AFTER shape_data;
