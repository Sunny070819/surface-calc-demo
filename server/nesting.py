"""Simple grid-approximation nesting: for an irregular scrap polygon, estimate how
many copies of a standard rectangular product fit inside it.

Method (as agreed for this POC -- not a precise no-fit-polygon algorithm):
1. Rasterize the polygon's bounding box into a grid of `cell_size_cm` cells; a cell
   is "inside" if its center point is inside the polygon (shapely.vectorized.contains,
   vectorized over the whole grid at once).
2. For each standard product, try both 0 degrees and 90 degrees rotation. For each
   orientation, greedily scan grid positions top-left to bottom-right; place a copy
   wherever its footprint of cells is fully inside the polygon and does not overlap
   an already-placed copy of the SAME product. Keep whichever orientation places more.
3. Each product is evaluated independently on its own placement mask (but sharing the
   same underlying occupancy grid), because the Excel record needs "how many A" and
   "how many B" as two independent hypothetical answers. A single mixed A+B layout is
   handled separately by greedy_mixed_nesting() (shelf packing, see its docstring).

Rectangle dimensions are rounded UP to whole cells, which is a conservative bias: the
algorithm will never claim a fit that doesn't actually exist, but may undercount by a
sliver near the polygon boundary. That is the safe direction for a "is this scrap
usable" judgment.
"""

import logging
import math
import time

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon

import config

logger = logging.getLogger(__name__)

MIXED_NESTING_SLOW_THRESHOLD_SECONDS = 1.0


def _choose_cell_size(bbox_w, bbox_h, base_cell_size, max_cells):
    if bbox_w <= 0 or bbox_h <= 0:
        return base_cell_size
    rows = math.ceil(bbox_h / base_cell_size)
    cols = math.ceil(bbox_w / base_cell_size)
    if rows * cols <= max_cells:
        return base_cell_size
    scale = math.sqrt((rows * cols) / max_cells)
    return base_cell_size * scale


def build_grid(polygon, cell_size_cm=None):
    """Rasterizes `polygon` once; the resulting grid is reused across every
    standard product so we don't recompute point-in-polygon tests per product."""
    base_cell_size = cell_size_cm or config.GRID_CELL_SIZE_CM
    minx, miny, maxx, maxy = polygon.bounds
    bbox_w, bbox_h = maxx - minx, maxy - miny
    g = _choose_cell_size(bbox_w, bbox_h, base_cell_size, config.MAX_GRID_CELLS)

    cols = max(1, math.ceil(bbox_w / g))
    rows = max(1, math.ceil(bbox_h / g))

    xs = minx + (np.arange(cols) + 0.5) * g
    ys = miny + (np.arange(rows) + 0.5) * g
    xx, yy = np.meshgrid(xs, ys)  # shape (rows, cols)
    occ = shapely.contains_xy(polygon, xx.ravel(), yy.ravel()).reshape(rows, cols)

    # 2D prefix sum ("integral image"), padded so rect_sum() needs no bounds checks.
    integral = np.zeros((rows + 1, cols + 1), dtype=np.int64)
    integral[1:, 1:] = occ.cumsum(axis=0).cumsum(axis=1)

    return {
        "occ": occ, "integral": integral, "rows": rows, "cols": cols,
        "cell_size_cm": g, "minx": minx, "miny": miny,
    }


def _rect_fully_inside(integral, r0, c0, r1, c1):
    total = integral[r1, c1] - integral[r0, c1] - integral[r1, c0] + integral[r0, c0]
    return total == (r1 - r0) * (c1 - c0)


def _greedy_place(grid, rect_rows, rect_cols):
    """Greedily scans grid positions top-left to bottom-right, placing a copy
    wherever it fits without overlapping an earlier placement. Returns
    (fits, positions); positions is the list of (r0, c0, r1, c1) grid-cell
    bounds actually used -- callers that only need the count can ignore it."""
    rows, cols = grid["rows"], grid["cols"]
    if rect_rows > rows or rect_cols > cols or rect_rows <= 0 or rect_cols <= 0:
        return 0, []
    integral = grid["integral"]
    placed = np.zeros((rows, cols), dtype=bool)
    positions = []
    for r in range(0, rows - rect_rows + 1):
        for c in range(0, cols - rect_cols + 1):
            if placed[r:r + rect_rows, c:c + rect_cols].any():
                continue
            if _rect_fully_inside(integral, r, c, r + rect_rows, c + rect_cols):
                placed[r:r + rect_rows, c:c + rect_cols] = True
                positions.append((r, c, r + rect_rows, c + rect_cols))
    return len(positions), positions


def compute_fits_for_product(grid, product):
    """Returns {"fits": int, "orientation_used_deg": int} for one standard product
    against an already-built grid (see build_grid)."""
    g = grid["cell_size_cm"]
    best = {"fits": 0, "orientation_used_deg": config.TRY_ROTATIONS_DEG[0]}
    for deg in config.TRY_ROTATIONS_DEG:
        if deg % 180 == 0:
            prod_len, prod_wid = product["length_cm"], product["width_cm"]
        else:
            prod_len, prod_wid = product["width_cm"], product["length_cm"]
        rect_cols = math.ceil(prod_len / g)
        rect_rows = math.ceil(prod_wid / g)
        fits, _positions = _greedy_place(grid, rect_rows, rect_cols)
        if fits > best["fits"]:
            best = {"fits": fits, "orientation_used_deg": deg}
    return best


def compute_fits_all(polygon, products, cell_size_cm=None):
    """Runs the nesting computation for every product in `products` against the
    same polygon. Returns (results, cell_size_cm_used) where results is a dict
    keyed by product id."""
    grid = build_grid(polygon, cell_size_cm)
    results = {}
    for product in products:
        results[product["id"]] = compute_fits_for_product(grid, product)
    return results, grid["cell_size_cm"]


def _normalize_to_origin(poly):
    minx, miny, _, _ = poly.bounds
    return affinity.translate(poly, xoff=-minx, yoff=-miny)


def _place_normalized_item(item_normalized, deg, target_minx, target_miny):
    """`item_normalized` already has its bounding-box min corner at (0, 0).
    Rotates it (if deg calls for 90) back onto a (0, 0)-anchored bbox, then
    translates it so that bbox's min corner lands exactly on the grid cell
    corner a bounding-box placement would have used."""
    if deg % 180 != 0:
        rotated = affinity.rotate(item_normalized, 90, origin=(0, 0))
        rotated = _normalize_to_origin(rotated)
    else:
        rotated = item_normalized
    return affinity.translate(rotated, xoff=target_minx, yoff=target_miny)


def pack_rect_into_polygon(polygon, item_length_cm, item_width_cm, cell_size_cm=None, item_polygon=None):
    """Reverse of compute_fits_for_product: greedily packs copies of a single
    item (trying both configured rotations, keeping whichever orientation
    places more) into `polygon`, using the same grid+greedy approximation as
    the rest of this module. Used to pack a product into a standard sheet.

    Placement decisions (where copies go, how many fit) are always based on
    the item's bounding box (item_length_cm x item_width_cm), same as standard
    A/B products elsewhere in this module -- so an irregular item's fit count
    can be undercounted but never overcounted, same safe direction as the rest
    of this module. This is unaffected by item_polygon.

    item_polygon controls what gets SUBTRACTED once placements are chosen:
    if given, each placement subtracts the item's actual outline (rotated/
    translated onto that placement's grid cell), so notches or curves in the
    item's real shape show up in the leftover region instead of being
    flattened into a plain rectangular bite. If omitted, falls back to
    subtracting the plain bounding-box rectangle at each placement (coarser,
    but cheaper and matches every other simplification in this module).

    Returns fits, orientation_used_deg, cell_size_cm, and leftover_polygon --
    `polygon` with the union of all placed item footprints subtracted out. If
    the leftover splits into several disconnected pieces, only the largest is
    kept: downstream nesting only operates on a single connected region, and
    smaller disconnected offcut slivers from the same sheet are ignored
    (consistent with this module's undercount-not-overcount bias).
    """
    grid = build_grid(polygon, cell_size_cm)
    g = grid["cell_size_cm"]
    best = None
    for deg in config.TRY_ROTATIONS_DEG:
        if deg % 180 == 0:
            length, width = item_length_cm, item_width_cm
        else:
            length, width = item_width_cm, item_length_cm
        rect_cols = math.ceil(length / g)
        rect_rows = math.ceil(width / g)
        fits, positions = _greedy_place(grid, rect_rows, rect_cols)
        if best is None or fits > best["fits"]:
            best = {"fits": fits, "orientation_used_deg": deg, "positions": positions}

    if best["fits"] < 1:
        return {
            "fits": 0,
            "orientation_used_deg": best["orientation_used_deg"],
            "cell_size_cm": g,
            "leftover_polygon": polygon,
        }

    minx, miny = grid["minx"], grid["miny"]
    if item_polygon is not None:
        item_normalized = _normalize_to_origin(item_polygon)
        placed_shapes = [
            _place_normalized_item(item_normalized, best["orientation_used_deg"], minx + c0 * g, miny + r0 * g)
            for (r0, c0, r1, c1) in best["positions"]
        ]
    else:
        placed_shapes = [
            shapely.box(minx + c0 * g, miny + r0 * g, minx + c1 * g, miny + r1 * g)
            for (r0, c0, r1, c1) in best["positions"]
        ]

    leftover = polygon.difference(shapely.union_all(placed_shapes))
    if leftover.geom_type != "Polygon":
        candidates = [geom for geom in getattr(leftover, "geoms", []) if geom.geom_type == "Polygon"]
        leftover = max(candidates, key=lambda geom: geom.area) if candidates else Polygon()

    return {
        "fits": best["fits"],
        "orientation_used_deg": best["orientation_used_deg"],
        "cell_size_cm": g,
        "leftover_polygon": leftover,
    }


def _shelf_pack_pass(polygon, minx, miny, maxx, maxy, row_height, primary, secondary):
    """One greedy shelf-packing pass over `polygon`'s bounding box: fills each
    row with `primary` left-to-right, then whatever `secondary` copies still
    fit in that same row's leftover width. `row_height` is shared by both
    products (the larger of both products' larger sides) so that neither one
    can overflow into the row below regardless of which one occupies a given
    row. Every candidate rectangle is checked against the real (possibly
    notched/concave) polygon via covers() and dropped if it pokes outside --
    only the bounding box is guaranteed rectangular, not the polygon itself.
    Returns (count_primary, count_secondary)."""
    if row_height <= 0:
        return 0, 0
    num_rows = int((maxy - miny) // row_height)
    count_primary = 0
    count_secondary = 0
    for row_idx in range(num_rows):
        row_y0 = miny + row_idx * row_height
        cursor_x = minx
        while cursor_x + primary["length_cm"] <= maxx + 1e-9:
            rect = shapely.box(cursor_x, row_y0, cursor_x + primary["length_cm"], row_y0 + primary["width_cm"])
            if polygon.covers(rect):
                count_primary += 1
            cursor_x += primary["length_cm"]
        while cursor_x + secondary["length_cm"] <= maxx + 1e-9:
            rect = shapely.box(cursor_x, row_y0, cursor_x + secondary["length_cm"], row_y0 + secondary["width_cm"])
            if polygon.covers(rect):
                count_secondary += 1
            cursor_x += secondary["length_cm"]
    return count_primary, count_secondary


def greedy_mixed_nesting(polygon, product_a, product_b):
    """Shelf-based greedy approximation for packing a MIX of product_a and
    product_b into the same scrap polygon -- unlike compute_fits_all, which
    scores each product independently on its own hypothetical full placement,
    this tries to actually combine both into one shared layout. Not an
    optimal solver: it only tries two simple row orderings (B-then-A and
    A-then-B, "shelf packing") and keeps whichever yields the higher benefit.

    Returns {"fits_a": int, "fits_b": int, "benefit": float, "strategy": str}.
    """
    min_product_area = min(
        product_a["length_cm"] * product_a["width_cm"],
        product_b["length_cm"] * product_b["width_cm"],
    )
    if polygon.area < min_product_area:
        return {"fits_a": 0, "fits_b": 0, "benefit": 0.0, "strategy": "too_small"}

    unit_price_a = product_a.get("unit_price")
    if unit_price_a is None:
        logger.warning("greedy_mixed_nesting: product_a is missing unit_price, defaulting to 0")
        unit_price_a = 0.0
    unit_price_b = product_b.get("unit_price")
    if unit_price_b is None:
        logger.warning("greedy_mixed_nesting: product_b is missing unit_price, defaulting to 0")
        unit_price_b = 0.0

    minx, miny, maxx, maxy = polygon.bounds
    # Shared by both passes so a row can safely hold either product (or both)
    # without one of them overflowing into the row below.
    row_height = max(product_a["length_cm"], product_a["width_cm"], product_b["length_cm"], product_b["width_cm"])

    start = time.monotonic()
    b_first_b, b_first_a = _shelf_pack_pass(polygon, minx, miny, maxx, maxy, row_height, product_b, product_a)
    a_first_a, a_first_b = _shelf_pack_pass(polygon, minx, miny, maxx, maxy, row_height, product_a, product_b)
    elapsed = time.monotonic() - start
    if elapsed > MIXED_NESTING_SLOW_THRESHOLD_SECONDS:
        logger.warning("greedy_mixed_nesting: took %.2fs for polygon bounds=%s", elapsed, polygon.bounds)

    benefit_b_then_a = round(b_first_a * unit_price_a + b_first_b * unit_price_b, 2)
    benefit_a_then_b = round(a_first_a * unit_price_a + a_first_b * unit_price_b, 2)

    if benefit_b_then_a >= benefit_a_then_b:
        return {"fits_a": b_first_a, "fits_b": b_first_b, "benefit": benefit_b_then_a, "strategy": "B_then_A"}
    return {"fits_a": a_first_a, "fits_b": a_first_b, "benefit": benefit_a_then_b, "strategy": "A_then_B"}
