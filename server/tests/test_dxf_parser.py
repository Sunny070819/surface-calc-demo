import dxf_parser


def test_rectangle_dxf_area_and_bbox(synthetic_rect_dxf_bytes):
    result = dxf_parser.parse_dxf(synthetic_rect_dxf_bytes, scale_cm_per_unit=2.0)
    assert result["ok"]
    # 20x10 drawing units * (scale 2.0)^2 = 800 cm^2
    assert abs(result["area_cm2"] - 800.0) < 0.01
    assert abs(result["length_cm"] - 40.0) < 0.01
    assert abs(result["width_cm"] - 20.0) < 0.01
    assert result["units_detected"] == "centimeter"


def test_arc_bulge_is_flattened_into_extra_points(synthetic_arc_dxf_bytes):
    result = dxf_parser.parse_dxf(synthetic_arc_dxf_bytes, scale_cm_per_unit=1.0)
    assert result["ok"]
    # A straight 4-vertex rectangle would produce 5 points (closed loop); the
    # rounded corner must flatten into noticeably more, proving arcs are handled
    # (unlike the old JS regex parser, which only understood straight vertices).
    assert len(result["polygon_cm"]) > 6
    assert result["area_cm2"] > 0


def test_empty_dxf_returns_not_ok(synthetic_empty_dxf_bytes):
    result = dxf_parser.parse_dxf(synthetic_empty_dxf_bytes, scale_cm_per_unit=1.0)
    assert not result["ok"]
    assert result["warning"]


def test_garbage_bytes_do_not_crash():
    result = dxf_parser.parse_dxf(b"this is not a dxf file at all", scale_cm_per_unit=1.0)
    assert not result["ok"]
    assert result["warning"]
