from shapely.geometry import Polygon

import nesting


def test_square_exact_fit():
    square = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])
    grid = nesting.build_grid(square, cell_size_cm=1.0)
    result = nesting.compute_fits_for_product(grid, {"length_cm": 10.0, "width_cm": 10.0})
    assert result["fits"] == 25


def test_polygon_smaller_than_product_yields_zero():
    small = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    grid = nesting.build_grid(small, cell_size_cm=1.0)
    result = nesting.compute_fits_for_product(grid, {"length_cm": 10.0, "width_cm": 10.0})
    assert result["fits"] == 0


def test_orientation_selection_picks_the_fitting_rotation():
    # 12 wide x 40 tall rectangle; a 12x8 product only fits if oriented 8-wide/12-tall
    # is rejected (12 > 12 width is ok either way here) -- use a tighter case instead:
    # 8 wide x 40 tall strip; product 12x8 only fits rotated (8 wide x 12 tall).
    strip = Polygon([(0, 0), (8, 0), (8, 40), (0, 40)])
    grid = nesting.build_grid(strip, cell_size_cm=1.0)
    result = nesting.compute_fits_for_product(grid, {"length_cm": 12.0, "width_cm": 8.0})
    assert result["fits"] == 3  # floor(40/12) with the product rotated to 8x12
    assert result["orientation_used_deg"] == 90


def test_concave_l_shape_does_not_cross_the_notch():
    # 20x20 square missing its top-right 10x10 corner -> an L shape, area = 300
    l_shape = Polygon([(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)])
    grid = nesting.build_grid(l_shape, cell_size_cm=1.0)

    too_big = nesting.compute_fits_for_product(grid, {"length_cm": 15.0, "width_cm": 15.0})
    assert too_big["fits"] == 0  # no 15x15 square fits without crossing the notch

    fits_10 = nesting.compute_fits_for_product(grid, {"length_cm": 10.0, "width_cm": 10.0})
    assert fits_10["fits"] == 3  # the L is exactly three 10x10 blocks


def test_compute_fits_all_runs_independently_per_product():
    square = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])
    products = [
        {"id": "A", "length_cm": 10.0, "width_cm": 10.0, "area_cm2": 100.0},
        {"id": "B", "length_cm": 12.0, "width_cm": 8.0, "area_cm2": 96.0},
    ]
    results, cell_size = nesting.compute_fits_all(square, products)
    assert results["A"]["fits"] == 25
    # B independently gets its own fresh grid, not reduced by A's placements
    assert results["B"]["fits"] > 0
    assert cell_size == 1.0


def test_grid_auto_coarsens_for_huge_polygons():
    huge = Polygon([(0, 0), (10000, 0), (10000, 10000), (0, 10000)])
    grid = nesting.build_grid(huge, cell_size_cm=1.0)
    assert grid["rows"] * grid["cols"] <= 200 * 200
    assert grid["cell_size_cm"] > 1.0


def test_pack_rect_into_polygon_leaves_correct_leftover_area():
    # 23x10 sheet, 10x10 items: 2 fit side by side (a 3rd would need x in
    # [20,30), which exceeds the 23-wide sheet), leaving a 3x10 strip.
    sheet = Polygon([(0, 0), (23, 0), (23, 10), (0, 10)])
    result = nesting.pack_rect_into_polygon(sheet, 10.0, 10.0, cell_size_cm=1.0)
    assert result["fits"] == 2
    assert result["leftover_polygon"].geom_type == "Polygon"
    assert result["leftover_polygon"].area == 30.0


def test_pack_rect_into_polygon_item_bigger_than_container_in_both_rotations():
    sheet = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    result = nesting.pack_rect_into_polygon(sheet, 20.0, 15.0, cell_size_cm=1.0)
    assert result["fits"] == 0
    assert result["leftover_polygon"].equals(sheet)


def test_pack_rect_into_polygon_tries_both_rotations():
    # 8 wide x 40 tall strip, 12x8 item only fits rotated (8 wide x 12 tall) --
    # same fixture/expectation as the forward-direction orientation test above.
    strip = Polygon([(0, 0), (8, 0), (8, 40), (0, 40)])
    result = nesting.pack_rect_into_polygon(strip, 12.0, 8.0, cell_size_cm=1.0)
    assert result["fits"] == 3
    assert result["orientation_used_deg"] == 90


def test_pack_rect_into_polygon_with_item_polygon_preserves_notch():
    # 10x10 sheet; item is an L-shape whose bounding box is also 10x10 but
    # whose real area is 75 (missing its own top-right 5x5 corner). Exactly
    # one copy fits either way -- item_polygon only changes what gets
    # subtracted, not the placement decision.
    sheet = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    l_item = Polygon([(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)])

    bbox_result = nesting.pack_rect_into_polygon(sheet, 10.0, 10.0, cell_size_cm=1.0)
    assert bbox_result["fits"] == 1
    assert bbox_result["leftover_polygon"].area == 0.0  # bbox exactly covers the sheet

    real_result = nesting.pack_rect_into_polygon(sheet, 10.0, 10.0, cell_size_cm=1.0, item_polygon=l_item)
    assert real_result["fits"] == 1  # same placement decision as the bbox path
    assert real_result["leftover_polygon"].area == 25.0
    # leftover should be exactly the item's own notch: the top-right 5x5 corner
    expected_notch = Polygon([(5, 5), (10, 5), (10, 10), (5, 10)])
    assert real_result["leftover_polygon"].equals(expected_notch)
