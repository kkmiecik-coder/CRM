# Handoff: parsed_edges_groups (per-edge mixed obróbka)

**Data:** 2026-05-18
**Repo CRM, branch:** main (commit po wdrożeniu).
**Repo Android:** crm_prod_app.

## Co się zmieniło w CRM

Moduł produkcji w CRM (modele/API mobile) zyskał nowe pole `parsed_edges_groups` w produktach (`prod_products`):

```json
{
  "parsed_edges_groups": [
    {"type": "zaokrąglenie", "radius": 3, "angle": null, "letters": ["A", "B"]},
    {"type": "fazowanie",    "radius": 5, "angle": 45,   "letters": ["C", "D"]},
    {"type": "zaokrąglenie", "radius": 10, "angle": null, "letters": ["E"]}
  ]
}
```

Pole jest zwracane w endpointach `/api/mobile/orders/<id>` i listingach produktów (sprawdź `modules/production/routers/stations/interfaces.py`).

Stare pola pozostają i nadal działają:
- `parsed_edge_type` — `'zaokrąglenie' | 'fazowanie' | 'mixed' | null`. Wartość `'mixed'` oznacza że produkt ma per-edge config (wiele grup w `parsed_edges_groups`).
- `parsed_edge_radius` / `parsed_edge_angle` — `null` gdy `'mixed'`.
- `parsed_edge_letters` — union wszystkich liter ze wszystkich grup (lista płaska, jak dotychczas — funkcjonalność operacyjna "co obrabiać" działa bez zmian).

## Co zrobić w Android

1. **Modele danych** — dodaj pole `parsedEdgesGroups: List<EdgeGroup>?` do modelu produktu.
2. **Fallback** — jeśli `parsedEdgesGroups` jest puste/null, skonstruuj jedną grupę z legacy `parsedEdgeType/Radius/Angle/Letters`.
3. **UI stanowisk** — w widoku krawędzi pokaż listę grup zamiast pojedynczego zestawu. Każda grupa:
   - typ + R + (opcjonalnie kąt)
   - litery krawędzi do obróbki
   - sugerowany kolor lewego paska wg typu (zielony=zaokrąglenie, pomarańczowy=fazowanie)
4. **SVG** — jeśli Android wyświetla SVG kształtu, wystarczy pobranie z BE (już pokolorowany per typ). Bez zmian w renderze.

## Out of scope tej zmiany w CRM

Logika rejestracji wykonania (`/api/mobile/orders/<id>/complete` itp.) nie wymaga zmian — operuje na poziomie produktu, nie per-edge.

## Pytania → CRM session

Spec: `docs/superpowers/specs/2026-05-18-edges-advanced-per-edge-design.md`.
Plan: `docs/superpowers/plans/2026-05-18-edges-advanced-per-edge.md`.
