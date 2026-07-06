# -*- coding: utf-8 -*-
"""
Złote przypadki: bierze N ostatnich wycen z DB, odtwarza parametry produktów,
liczy pricing_service i porównuje ze wartościami zapisanymi przez frontendowy JS.
Tolerancja 1 grosz. Rozjazd price_per_m3 (zapisany vs aktualny cennik) oznacza
zmianę cennika w międzyczasie — raportowany osobno, nie jako bug logiki.

Uruchomienie (lokalna kopia DB!): python3 scripts/golden_pricing_check.py --limit 200
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=200)
    parser.add_argument('--quote', type=str, default=None, help='konkretny numer wyceny')
    args = parser.parse_args()

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

        stats = {'ok': 0, 'mismatch': 0, 'pricelist_changed': 0, 'skipped': 0, 'legacy': 0}
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
            # Wycena sprzed wdrożenia edges_mode/kształtów — traktuj wyrozumiale,
            # zaraportuj osobno zamiast liczyć jako bug logiki.
            is_legacy = any(
                (details_by_index.get(p['index']) is None) or
                (details_by_index.get(p['index']).edges_mode is None and
                 details_by_index.get(p['index']).edges_config)
                for p in payload['products']
            )

            for p_out, p_in in zip(result['products'], payload['products']):
                idx = p_in['index']
                det = details_by_index.get(idx)
                saved_items = {i.variant_code: i for i in items if i.product_index == idx}

                # 1) Materiał: porównaj unit_price_netto/brutto per wariant
                for v in p_out['variants']:
                    saved = saved_items.get(v['variant_code'])
                    if not saved or not v.get('available'):
                        continue
                    # zmiana cennika? zapisany price_per_m3 != aktualny
                    if abs(float(saved.price_per_m3 or 0) - v['price_per_m3']) > 0.01:
                        stats['pricelist_changed'] += 1
                        quote_pricelist_changed = True
                        continue
                    calc_unit_n = round(v['total_netto'] / p_in['quantity'], 2)
                    # Rabaty: jeśli sztuka ma discount_percentage != 0, zapisany
                    # price_netto jest PO rabacie — porównuj z original_price_netto
                    # (cena przed rabatem), bo pricing_service nie liczy rabatów.
                    has_discount = float(saved.discount_percentage or 0) != 0
                    reference = (float(saved.original_price_netto)
                                 if has_discount and saved.original_price_netto is not None
                                 else float(saved.price_netto or 0))
                    if abs(calc_unit_n - reference) > TOL:
                        print(f"[MATERIAŁ] {quote.quote_number} p{idx} {v['variant_code']}: "
                              f"obliczono unit {calc_unit_n}, zapisano "
                              f"{'original ' if has_discount else ''}{reference}")
                        quote_ok = False
                # 2) Wykończenie
                if det and abs(p_out['finishing']['netto'] - float(det.finishing_price_netto or 0)) > TOL:
                    print(f"[WYKOŃCZENIE] {quote.quote_number} p{idx}: "
                          f"obliczono {p_out['finishing']['netto']}, zapisano {det.finishing_price_netto}")
                    quote_ok = False
                # 3) Krawędzie
                if det and abs(p_out['edges']['netto'] - float(det.edges_price_netto or 0)) > TOL:
                    print(f"[KRAWĘDZIE] {quote.quote_number} p{idx}: "
                          f"obliczono {p_out['edges']['netto']}, zapisano {det.edges_price_netto}")
                    quote_ok = False

            if quote_pricelist_changed and quote_ok:
                # cały rozjazd dla tej wyceny wyjaśniony zmianą cennika — nie licz jako mismatch
                continue
            if not quote_ok and is_legacy:
                stats['legacy'] += 1
                print(f"[LEGACY] {quote.quote_number}: rozjazd na starej wycenie sprzed edges_mode — "
                      f"raportowane, nie naprawiane na siłę")
                continue

            stats['ok' if quote_ok else 'mismatch'] += 1

        print(f"\n=== WYNIK: {stats['ok']} OK, {stats['mismatch']} rozjazdów, "
              f"{stats['pricelist_changed']} zmian cennika, {stats['legacy']} legacy, "
              f"{stats['skipped']} pominiętych ===")
        sys.exit(0 if stats['mismatch'] == 0 else 1)


if __name__ == '__main__':
    main()
