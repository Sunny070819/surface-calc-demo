from shapely.geometry import Polygon

import config
import qualification


def test_below_threshold_skips_nesting_entirely(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    tiny = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])  # area 25 < 300
    result = qualification.evaluate(tiny)
    assert result["passes_area_threshold"] is False
    assert result["qualifies"] is False
    assert result["reason"] == "area_below_threshold"
    assert result["nesting"] == {}


def test_area_ok_but_thin_sliver_fits_nothing(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    # a 1cm x 400cm sliver: area 400 > threshold, but too narrow for any A/B
    sliver = Polygon([(0, 0), (400, 0), (400, 1), (0, 1)])
    result = qualification.evaluate(sliver)
    assert result["passes_area_threshold"] is True
    assert result["qualifies"] is False
    assert result["reason"] == "no_standard_product_fits"


def test_qualifies_when_a_product_fits(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    square = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])
    result = qualification.evaluate(square)
    assert result["qualifies"] is True
    assert result["reason"] is None
    assert result["nesting"]["A"]["fits"] >= 1


def test_evaluate_design_packs_product_and_evaluates_leftover(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    # 30x30 product into a 100x100 sheet: 9 copies (3x3 grid) fit, leaving a
    # 1900cm2 leftover, comfortably above threshold.
    product = Polygon([(0, 0), (30, 0), (30, 30), (0, 30)])
    result = qualification.evaluate_design(product, sheet_length_cm=100, sheet_width_cm=100)
    assert result["product_area_cm2"] == 900.0
    assert result["sheet_area_cm2"] == 10000.0
    assert result["product_fit_count"] == 9
    assert result["area_cm2"] == 1900.0
    assert result["qualifies"] is True
    assert len(result["leftover_polygon_cm"]) >= 3


def test_evaluate_design_product_exceeds_sheet(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    product = Polygon([(0, 0), (20, 0), (20, 5), (0, 5)])
    result = qualification.evaluate_design(product, sheet_length_cm=10, sheet_width_cm=10)
    assert result["qualifies"] is False
    assert result["reason"] == "product_exceeds_sheet"
    assert result["product_fit_count"] == 0


def test_evaluate_design_leftover_below_threshold(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    # 19x19 product on a 20x20 sheet: leftover area 400-361=39 < 300.
    product = Polygon([(0, 0), (19, 0), (19, 19), (0, 19)])
    result = qualification.evaluate_design(product, sheet_length_cm=20, sheet_width_cm=20)
    assert result["passes_area_threshold"] is False
    assert result["reason"] == "area_below_threshold"
    assert result["qualifies"] is False


def test_evaluate_design_includes_mixed_nesting_entry(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 300.0)
    # 40x30 sheet, product is the sheet minus its top-right 29x20 corner ->
    # exactly 1 copy fits (bbox == sheet), leaving that 29x20 corner as
    # leftover. On a plain 29x20 rectangle the mixed shelf-packer fits both
    # products (fits_a=2, fits_b=4, benefit=80) -- see the equivalent direct
    # nesting.greedy_mixed_nesting test for the row-by-row derivation.
    product = Polygon([(0, 0), (40, 0), (40, 10), (11, 10), (11, 30), (0, 30)])
    result = qualification.evaluate_design(product, sheet_length_cm=40, sheet_width_cm=30)

    assert result["nesting"]["A+B"] == {
        "fits_a": 2,
        "fits_b": 4,
        "benefit": 80.0,
        "unit_price_a": 10.0,
        "unit_price_b": 15.0,
    }

    ranked_ids = [option["product_id"] for option in result["ranked_options"]]
    assert "A+B" in ranked_ids
    mixed_option = next(o for o in result["ranked_options"] if o["product_id"] == "A+B")
    assert mixed_option["benefit"] == 80.0
    # A alone (benefit 120) beats the mixed layout (80) beats B alone (60) --
    # confirms "A+B" is folded into the same benefit-ranked order, not just appended.
    assert ranked_ids == sorted(ranked_ids, key=lambda pid: -next(
        o["benefit"] for o in result["ranked_options"] if o["product_id"] == pid
    ))
    assert ranked_ids[0] == "A"

    # nesting dict key order should follow the same benefit ranking.
    assert list(result["nesting"].keys()) == ranked_ids


def test_evaluate_design_mixed_nesting_too_small_boundary(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 5.0)
    # L-shaped product (bbox 10x10, real area 75) packed onto a 10x10 sheet:
    # leftover is the product's own 25cm2 notch -- above the (lowered) area
    # threshold of 5, but below the smallest standard product's own area
    # (A is 45cm2), so nothing can possibly fit, mixed or otherwise.
    l_product = Polygon([(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)])
    result = qualification.evaluate_design(l_product, sheet_length_cm=10, sheet_width_cm=10)

    assert result["passes_area_threshold"] is True
    assert result["area_cm2"] == 25.0
    assert result["nesting"]["A+B"] == {
        "fits_a": 0,
        "fits_b": 0,
        "benefit": 0.0,
        "unit_price_a": 10.0,
        "unit_price_b": 15.0,
    }


def test_evaluate_design_leftover_reflects_product_notch(monkeypatch):
    monkeypatch.setattr(config, "AREA_DISCARD_THRESHOLD_CM2", 5.0)
    # L-shaped product (bbox 10x10, real area 75, missing its own top-right
    # 5x5 corner) packed onto a 10x10 sheet: exactly 1 copy fits. The leftover
    # must be the product's own notch (25cm2), not "sheet minus bbox" (0cm2) --
    # proves evaluate_design subtracts the real outline, not the bounding box.
    l_product = Polygon([(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)])
    result = qualification.evaluate_design(l_product, sheet_length_cm=10, sheet_width_cm=10)
    assert result["product_area_cm2"] == 75.0
    assert result["product_fit_count"] == 1
    assert result["area_cm2"] == 25.0
