-- Migracja: Strukturalna obróbka krawędzi
-- Data: 2026-04-10

-- Nowe pola w prod_items (ProductionItem)
ALTER TABLE prod_items ADD COLUMN parsed_edge_type VARCHAR(20) DEFAULT NULL COMMENT 'Typ obróbki: zaokrąglenie / fazowanie';
ALTER TABLE prod_items ADD COLUMN parsed_edge_radius INT DEFAULT NULL COMMENT 'Wartość promienia R (np. 3, 6, 30)';
ALTER TABLE prod_items ADD COLUMN parsed_edge_angle INT DEFAULT NULL COMMENT 'Kąt fazowania w stopniach (30, 45, 60)';
ALTER TABLE prod_items ADD COLUMN parsed_edge_letters JSON DEFAULT NULL COMMENT 'Lista krawędzi JSON: ["A","B","N1"]';
ALTER TABLE prod_items ADD COLUMN edge_svg TEXT DEFAULT NULL COMMENT 'SVG izometryczny 3D z zaznaczonymi krawędziami';
ALTER TABLE prod_items ADD COLUMN shape_svg TEXT DEFAULT NULL COMMENT 'SVG kształtu 2D';
ALTER TABLE prod_items ADD COLUMN quote_item_detail_id INT DEFAULT NULL COMMENT 'ID powiązanego QuoteItemDetails';

-- Nowe pole w quote_items_details (QuoteItemDetails)
ALTER TABLE quote_items_details ADD COLUMN baselinker_order_product_id INT DEFAULT NULL COMMENT 'ID produktu z BaseLinker getOrders';
