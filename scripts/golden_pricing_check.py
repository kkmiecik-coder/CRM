# -*- coding: utf-8 -*-
"""
Złote przypadki: bierze N ostatnich wycen z DB, odtwarza parametry produktów,
liczy pricing_service i porównuje ze wartościami zapisanymi przez frontendowy JS.
Tolerancja 1 grosz. Rozjazd price_per_m3 (zapisany vs aktualny cennik) oznacza
zmianę cennika w międzyczasie — raportowany osobno, nie jako bug logiki.

Uruchomienie (lokalna kopia DB!): python3 scripts/golden_pricing_check.py --limit 200
Selftest (bez DB, obiekty in-memory): python3 scripts/golden_pricing_check.py --selftest
"""
import argparse
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOL = 0.011  # 1 grosz + luz floatowy


def _rebuild_finishing_full_path(det):
    """
    Odtwarza pełną ścieżkę wykończenia (np. "Lakierowane > Barwne > BRUNAT 22-23")
    z pól faktycznie zapisanych w quote_items_details.

    UWAGA: finishing_option_id/finishing_full_path NIE są zapisywane w DB —
    JS liczył cenę po window.finishingPrices[fullPath] (calculator-ui.js:601-603),
    a ta ścieżka opierała się na nazwie opcji z drzewka FinishingOption (dziś:
    "Lakierowane", NIE "Lakierowanie" — legacy fallback w JS/pricing_service
    porównuje z hardcodowanym stringiem "Lakierowanie", który dla współczesnego
    drzewka nigdy nie trafia; prawdziwe źródło ceny to właśnie fullPath).
    Bez tej rekonstrukcji każde wykończenie barwne/bezbarwne/olejowane wypadnie
    jako "obliczono 0.0" (brak trafienia w żaden fallback pricing_service).
    """
    if not det or not det.finishing_type or det.finishing_type == 'Surowe':
        return None
    parts = [det.finishing_type]
    if det.finishing_variant:
        parts.append(det.finishing_variant)
    if det.finishing_color:
        parts.append(det.finishing_color)
    return ' > '.join(parts)


def _rebuild_payload(quote, items, details_by_index):
    """Odtwarza payload calculate_quote z zapisanej wyceny."""
    import json
    products = []
    by_index = {}
    for it in items:
        by_index.setdefault(it.product_index, []).append(it)

    for idx in sorted(by_index):
        det = details_by_index.get(idx)
        first = by_index[idx][0]
        holes = 0
        shape_data = det.shape_data if det else None
        if shape_data:
            try:
                sd = json.loads(shape_data) if isinstance(shape_data, str) else shape_data
                holes = len(sd.get('holes') or [])
            except Exception:
                pass
        selected = next((i.variant_code for i in by_index[idx] if i.is_selected), None)
        products.append({
            'index': idx,
            'length': float(first.length_cm or 0),
            'width': float(first.width_cm or 0),
            'thickness': float(first.thickness_cm or 0),
            'quantity': det.quantity if det else 1,
            'shape': (det.shape if det else None) or 'rectangular',
            'shape_data': shape_data,
            'holes_count': holes,
            'selected_variant': selected,
            'finishing_type': det.finishing_type if det else 'Surowe',
            'finishing_variant': det.finishing_variant if det else None,
            'finishing_gloss_level': det.finishing_gloss_level if det else None,
            'finishing_option_id': None,  # niezapisywane w DB — cena pójdzie fallbackiem po ścieżce
            'finishing_full_path': _rebuild_finishing_full_path(det),
            'edges': det.edges_config if det else None,
            'edges_mode': det.edges_mode if det else None,
        })
    return {
        'client_type': quote.quote_client_type,
        'multiplier': float(quote.quote_multiplier) if quote.quote_multiplier else None,
        'products': products,
    }


def _is_legacy_edges(det):
    """Produkt z wyceny sprzed edges_mode: pole NULL, ale ma zapisaną konfigurację krawędzi."""
    return det is not None and det.edges_mode is None and bool(det.edges_config)


def _compare_product(p_out, p_in, det, saved_items, quantity, stats):
    """
    Porównuje jeden produkt (obliczone przez pricing_service vs zapisane w DB).

    `p_out` — wynik calculate_quote dla tego produktu (klucze: variants/finishing/edges).
    `p_in` — wejściowy payload produktu (index, quantity, ...).
    `det` — QuoteItemDetails (albo None/SimpleNamespace w selftest) albo None gdy brak.
    `saved_items` — dict {variant_code: QuoteItem-like} dla tego produktu.
    `quantity` — ilość sztuk (do liczenia unit price z total).
    `stats` — słownik liczników, mutowany in-place.

    Zwraca True jeśli produkt bez rozjazdów (MATERIAŁ/WYKOŃCZENIE zawsze liczone
    do wyniku; KRAWĘDZIE na produkcie z legacy edges_mode liczone osobno do
    `legacy_edges`, bez wpływu na ogólny wynik/exit code).
    """
    idx = p_in['index']
    ok = True

    # 1) Materiał: porównaj unit_price_netto/brutto per wariant (zawsze mismatch, nie legacy)
    for v in p_out['variants']:
        saved = saved_items.get(v['variant_code'])
        if not saved or not v.get('available'):
            stats['skipped_unmatched_variant'] += 1
            continue
        stats['compared_material'] += 1
        # zmiana cennika? zapisany price_per_m3 != aktualny
        if abs(float(saved.price_per_m3 or 0) - v['price_per_m3']) > 0.01:
            stats['pricelist_changed'] += 1
            continue
        calc_unit_n = round(v['total_netto'] / quantity, 2)
        # Rabaty: jeśli sztuka ma discount_percentage != 0, zapisany
        # price_netto jest PO rabacie — porównuj z original_price_netto
        # (cena przed rabatem), bo pricing_service nie liczy rabatów.
        has_discount = float(saved.discount_percentage or 0) != 0
        reference = (float(saved.original_price_netto)
                     if has_discount and saved.original_price_netto is not None
                     else float(saved.price_netto or 0))
        if abs(calc_unit_n - reference) > TOL:
            print(f"[MATERIAŁ] p{idx} {v['variant_code']}: "
                  f"obliczono unit {calc_unit_n}, zapisano "
                  f"{'original ' if has_discount else ''}{reference}")
            ok = False

    # 2) Wykończenie — ZAWSZE mismatch, niezależnie od edges_mode/legacy
    if det is None:
        stats['skipped_no_details'] += 1
    else:
        stats['compared_finishing'] += 1
        if abs(p_out['finishing']['netto'] - float(det.finishing_price_netto or 0)) > TOL:
            print(f"[WYKOŃCZENIE] p{idx}: "
                  f"obliczono {p_out['finishing']['netto']}, zapisano {det.finishing_price_netto}")
            ok = False

    # 3) Krawędzie — rozjazd na produkcie z legacy edges_mode idzie do osobnej
    # kategorii `legacy_edges` (nie wpływa na exit code); inne rozjazdy = mismatch.
    if det is None:
        # skipped_no_details już zliczony wyżej
        pass
    else:
        stats['compared_edges'] += 1
        edges_mismatch = abs(p_out['edges']['netto'] - float(det.edges_price_netto or 0)) > TOL
        if edges_mismatch:
            if _is_legacy_edges(det):
                stats['legacy_edges'] += 1
                print(f"[LEGACY-KRAWĘDZIE] p{idx}: rozjazd na starej wycenie sprzed "
                      f"edges_mode — obliczono {p_out['edges']['netto']}, "
                      f"zapisano {det.edges_price_netto} (raportowane, nie naprawiane na siłę)")
                # legacy krawędzie NIE zrzucają quote_ok / mismatch
            else:
                print(f"[KRAWĘDZIE] p{idx}: "
                      f"obliczono {p_out['edges']['netto']}, zapisano {det.edges_price_netto}")
                ok = False

    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--quote', type=str, default=None, help='konkretny numer wyceny')
    parser.add_argument('--selftest', action='store_true',
                         help='testy syntetyczne na obiektach in-memory, bez DB')
    args = parser.parse_args()

    if args.selftest:
        sys.exit(_run_selftest())

    from app import create_app
    app = create_app()
    with app.app_context():
        from modules.calculator.models import Quote, QuoteItem, QuoteItemDetails
        from modules.calculator.services.pricing_service import (
            load_pricing_data, calculate_quote, find_price_entry, VARIANT_MAPPING,
        )

        data = load_pricing_data()
        q = Quote.query.order_by(Quote.id.desc())
        if args.quote:
            q = Quote.query.filter_by(quote_number=args.quote)
        quotes = q.limit(args.limit).all()

        stats = {
            'ok': 0, 'mismatch': 0, 'pricelist_changed': 0, 'skipped': 0,
            'legacy_edges': 0,
            'skipped_no_details': 0, 'skipped_unmatched_variant': 0,
            'compared_material': 0, 'compared_finishing': 0, 'compared_edges': 0,
        }
        for quote in quotes:
            items = QuoteItem.query.filter_by(quote_id=quote.id).all()
            details = QuoteItemDetails.query.filter_by(quote_id=quote.id).all()
            details_by_index = {d.product_index: d for d in details}
            if not items:
                stats['skipped'] += 1
                continue

            payload = _rebuild_payload(quote, items, details_by_index)
            result = calculate_quote(payload, data)
            if not result['ok']:
                print(f"[BŁĄD WALIDACJI] {quote.quote_number}: {result['errors'][:2]}")
                stats['mismatch'] += 1
                continue

            quote_ok = True
            quote_pricelist_changed = False

            for p_out, p_in in zip(result['products'], payload['products']):
                idx = p_in['index']
                det = details_by_index.get(idx)
                saved_items = {i.variant_code: i for i in items if i.product_index == idx}

                before_pricelist = stats['pricelist_changed']
                product_ok = _compare_product(
                    p_out, p_in, det, saved_items, p_in['quantity'], stats)
                if stats['pricelist_changed'] > before_pricelist:
                    quote_pricelist_changed = True
                if not product_ok:
                    quote_ok = False

            if quote_pricelist_changed and quote_ok:
                # cały rozjazd dla tej wyceny wyjaśniony zmianą cennika — nie licz jako mismatch
                continue

            stats['ok' if quote_ok else 'mismatch'] += 1

        print(f"\n=== WYNIK: {stats['ok']} OK, {stats['mismatch']} rozjazdów, "
              f"{stats['pricelist_changed']} zmian cennika, "
              f"{stats['legacy_edges']} legacy-krawędzie, "
              f"{stats['skipped']} pominiętych wycen ===")
        print(f"=== POMINIĘTE PRZY PORÓWNANIU: {stats['skipped_no_details']} bez QuoteItemDetails, "
              f"{stats['skipped_unmatched_variant']} niesparowanych/niedostępnych wariantów ===")
        print(f"=== WYKONANE PORÓWNANIA: {stats['compared_material']} materiał, "
              f"{stats['compared_finishing']} wykończenie, {stats['compared_edges']} krawędzie ===")
        sys.exit(0 if stats['mismatch'] == 0 else 1)


def _run_selftest():
    """
    Weryfikacja syntetyczna `_compare_product` na obiektach in-memory
    (types.SimpleNamespace) — zero zapisu/odczytu z DB.

    (a) produkt z rabatem: discount_percentage=10, original_price_netto=100,
        price_netto=90 — porównanie musi iść z original (100), nie z 90.
    (b) brak QuoteItemDetails (det=None) — ma inkrementować skipped_no_details
        i NIE liczyć porównania finishing/edges jako wykonanego (OK).
    (c) rozjazd wykończenia na produkcie z legacy edges_mode — musi wpaść do
        mismatch (kategoria WYKOŃCZENIE), a NIE do legacy_edges (ta kategoria
        jest wyłącznie dla rozjazdów KRAWĘDZI).
    """
    failures = []

    def new_stats():
        return {
            'ok': 0, 'mismatch': 0, 'pricelist_changed': 0, 'skipped': 0,
            'legacy_edges': 0,
            'skipped_no_details': 0, 'skipped_unmatched_variant': 0,
            'compared_material': 0, 'compared_finishing': 0, 'compared_edges': 0,
        }

    # --- (a) rabat: porównanie musi iść z original_price_netto ---
    stats = new_stats()
    p_in = {'index': 1, 'quantity': 1}
    p_out = {
        'variants': [{
            'variant_code': 'A_S', 'available': True,
            'price_per_m3': 1000.0, 'total_netto': 100.0,
        }],
        'finishing': {'netto': 0.0, 'brutto': 0.0},
        'edges': {'netto': 0.0, 'brutto': 0.0},
    }
    saved = types.SimpleNamespace(
        variant_code='A_S', price_per_m3=1000.0,
        price_netto=90.0, original_price_netto=100.0, discount_percentage=10,
    )
    det = types.SimpleNamespace(
        finishing_price_netto=0.0, edges_price_netto=0.0,
        edges_mode='basic', edges_config=None,
    )
    ok = _compare_product(p_out, p_in, det, {'A_S': saved}, 1, stats)
    if not ok:
        failures.append("(a) rabat: oczekiwano OK (porównanie z original=100), dostano mismatch")
    if stats['compared_material'] != 1:
        failures.append(f"(a) rabat: compared_material powinno być 1, jest {stats['compared_material']}")

    # --- (b) brak det: skipped_no_details, brak liczenia OK dla finishing/edges ---
    stats = new_stats()
    p_in = {'index': 2, 'quantity': 1}
    p_out = {
        'variants': [],
        'finishing': {'netto': 50.0, 'brutto': 61.5},
        'edges': {'netto': 10.0, 'brutto': 12.3},
    }
    ok = _compare_product(p_out, p_in, None, {}, 1, stats)
    if stats['skipped_no_details'] != 1:
        failures.append(f"(b) brak det: skipped_no_details powinno być 1, jest {stats['skipped_no_details']}")
    if stats['compared_finishing'] != 0 or stats['compared_edges'] != 0:
        failures.append(
            "(b) brak det: compared_finishing/compared_edges powinny zostać 0, "
            f"są {stats['compared_finishing']}/{stats['compared_edges']}"
        )
    if not ok:
        failures.append("(b) brak det: brak det sam w sobie nie powinien dawać mismatch")

    # --- (c) rozjazd wykończenia na produkcie legacy-edges -> mismatch, nie legacy ---
    stats = new_stats()
    p_in = {'index': 3, 'quantity': 1}
    p_out = {
        'variants': [],
        'finishing': {'netto': 150.0, 'brutto': 184.5},
        'edges': {'netto': 10.0, 'brutto': 12.3},
    }
    det = types.SimpleNamespace(
        finishing_price_netto=0.0,   # rozjazd: obliczono 150 vs zapisano 0
        edges_price_netto=10.0,      # krawędzie zgodne
        edges_mode=None, edges_config='{"N1": "..."}',  # legacy edges
    )
    ok = _compare_product(p_out, p_in, det, {}, 1, stats)
    if ok:
        failures.append("(c) rozjazd wykończenia na legacy-edges: oczekiwano mismatch (ok=False)")
    if stats['legacy_edges'] != 0:
        failures.append(
            f"(c) rozjazd wykończenia na legacy-edges: legacy_edges powinno zostać 0, "
            f"jest {stats['legacy_edges']}"
        )

    if failures:
        print("SELFTEST: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("SELFTEST: PASS (a) rabat->original, (b) brak det->skipped_no_details, "
          "(c) wykończenie legacy-edges->mismatch")
    return 0


if __name__ == '__main__':
    main()
