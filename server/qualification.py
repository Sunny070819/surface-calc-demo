"""Combines the area pre-filter with the nesting computation into one qualification
verdict, matching the spec's flow:

1. Area below threshold -> discard immediately, skip nesting entirely.
2. Area OK but no configured standard product fits even once -> still discard
   (a large, thin sliver can pass the area check yet be useless).
3. Otherwise -> qualifies; the per-product fit counts are used for the Excel row.
"""

import shapely

import config
import geometry_utils
import nesting
import standard_products


def _enrich_nesting_result(fits_by_product, products):
    product_lookup = {p["id"]: p for p in products}
    enriched_entries = {}
    ranked_options = []

    for product_id, fit_data in fits_by_product.items():
        product_info = product_lookup.get(product_id) or {}
        entry = dict(fit_data)
        unit_price = product_info.get("unit_price")
        benefit = None
        if unit_price is not None:
            try:
                benefit = round(float(entry.get("fits", 0)) * float(unit_price), 2)
            except (TypeError, ValueError):
                benefit = None
        if unit_price is not None:
            entry["unit_price"] = unit_price
        if benefit is not None:
            entry["benefit"] = benefit

        enriched_entries[product_id] = entry
        ranked_options.append({
            "product_id": product_id,
            "fits": entry.get("fits", 0),
            "unit_price": entry.get("unit_price"),
            "benefit": entry.get("benefit"),
        })

    ranked_options = sorted(
        ranked_options,
        key=lambda item: (item.get("benefit") is None, -(item.get("benefit") or 0), item["product_id"]),
    )

    ordered_nesting = {}
    for option in ranked_options:
        ordered_nesting[option["product_id"]] = enriched_entries[option["product_id"]]

    return ordered_nesting, ranked_options


def _add_mixed_nesting(result, leftover_polygon, product_ids):
    """Adds an "A+B" entry to an already-computed evaluate() result: a single
    shared layout mixing both products (see nesting.greedy_mixed_nesting),
    as opposed to the "A" and "B" entries which each hypothesize the whole
    polygon filled with just that one product. Folded into evaluate_design()
    rather than evaluate() itself because it only makes sense once the polygon
    has already passed the area threshold and produced real A/B entries --
    mirrors nesting["A"]/["B"] being skipped for the same reason."""
    if not result.get("passes_area_threshold"):
        return

    products = standard_products.load_products()
    if product_ids:
        products = [p for p in products if p["id"] in product_ids]
    product_lookup = {p["id"]: p for p in products}
    product_a = product_lookup.get("A")
    product_b = product_lookup.get("B")
    if product_a is None or product_b is None:
        return

    mixed = nesting.greedy_mixed_nesting(leftover_polygon, product_a, product_b)
    mixed_entry = {
        "fits_a": mixed["fits_a"],
        "fits_b": mixed["fits_b"],
        "benefit": mixed["benefit"],
        "unit_price_a": product_a.get("unit_price"),
        "unit_price_b": product_b.get("unit_price"),
    }

    ranked_options = result.get("ranked_options") or []
    ranked_options.append({
        "product_id": "A+B",
        "fits_a": mixed["fits_a"],
        "fits_b": mixed["fits_b"],
        "unit_price_a": product_a.get("unit_price"),
        "unit_price_b": product_b.get("unit_price"),
        "benefit": mixed["benefit"],
    })
    ranked_options.sort(
        key=lambda item: (item.get("benefit") is None, -(item.get("benefit") or 0), item["product_id"]),
    )
    result["ranked_options"] = ranked_options

    nesting_dict = result.get("nesting") or {}
    nesting_dict["A+B"] = mixed_entry
    ordered_nesting = {}
    for option in ranked_options:
        ordered_nesting[option["product_id"]] = nesting_dict[option["product_id"]]
    result["nesting"] = ordered_nesting


def evaluate(polygon, product_ids=None):
    area = polygon.area
    threshold = config.AREA_DISCARD_THRESHOLD_CM2
    passes_area_threshold = area >= threshold

    result = {
        "ok": True,
        "area_cm2": round(area, 2),
        "area_threshold_cm2": threshold,
        "passes_area_threshold": passes_area_threshold,
        "nesting": {},
        "qualifies": False,
        "reason": None,
        "grid_cell_size_cm": None,
    }

    if not passes_area_threshold:
        result["reason"] = "area_below_threshold"
        return result

    products = standard_products.load_products()
    if product_ids:
        products = [p for p in products if p["id"] in product_ids]

    fits_by_product, grid_cell_size_cm = nesting.compute_fits_all(polygon, products)
    ordered_nesting, ranked_options = _enrich_nesting_result(fits_by_product, products)
    result["nesting"] = ordered_nesting
    result["ranked_options"] = ranked_options
    result["grid_cell_size_cm"] = grid_cell_size_cm

    qualifies = any(r.get("fits", 0) >= 1 for r in fits_by_product.values())
    result["qualifies"] = qualifies
    if not qualifies:
        result["reason"] = "no_standard_product_fits"

    return result


def evaluate_design(product_polygon, sheet_length_cm, sheet_width_cm, product_ids=None):
    """Entry point for the design-to-leftover flow: figures out how many copies
    of `product_polygon` fit into a sheet_length_cm x sheet_width_cm standard
    sheet (placement decisions use the product's bounding box, same
    undercount-not-overcount approximation as A/B elsewhere), then subtracts
    the product's *actual* outline -- not just its bounding box -- at each
    placement, so notches/curves in the real design show up in the leftover
    shape (see nesting.pack_rect_into_polygon's item_polygon parameter).
    Finally runs the existing area-threshold + A/B nesting evaluation
    (`evaluate`, unchanged) against whatever is left over. This replaces
    feeding `evaluate` a directly-measured scrap polygon -- the leftover is
    now computed, not photographed, but everything downstream of "here is the
    scrap polygon" is identical to before.
    """
    sheet_polygon = shapely.box(0, 0, sheet_length_cm, sheet_width_cm)
    minx, miny, maxx, maxy = product_polygon.bounds
    product_length_cm = maxx - minx
    product_width_cm = maxy - miny

    pack = nesting.pack_rect_into_polygon(
        sheet_polygon, product_length_cm, product_width_cm, item_polygon=product_polygon
    )

    result = {
        "ok": True,
        "sheet_area_cm2": round(sheet_polygon.area, 2),
        "product_area_cm2": round(product_polygon.area, 2),
        "product_fit_count": pack["fits"],
        "product_orientation_used_deg": pack["orientation_used_deg"],
    }

    if pack["fits"] < 1:
        result.update({
            "qualifies": False,
            "reason": "product_exceeds_sheet",
            "area_cm2": 0.0,
            "area_threshold_cm2": config.AREA_DISCARD_THRESHOLD_CM2,
            "passes_area_threshold": False,
            "nesting": {},
            "grid_cell_size_cm": None,
        })
        return result

    result.update(evaluate(pack["leftover_polygon"], product_ids))
    result["leftover_polygon_cm"] = geometry_utils.polygon_to_points(pack["leftover_polygon"])
    _add_mixed_nesting(result, pack["leftover_polygon"], product_ids)
    return result
