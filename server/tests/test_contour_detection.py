import contour_detection


def test_detects_blob_on_noisy_background(synthetic_scrap_photo_bytes):
    result = contour_detection.detect_contour(
        synthetic_scrap_photo_bytes, display_width=560, display_height=420
    )
    assert result["ok"] is True
    assert len(result["contour_px"]) >= 3
    assert 0.0 <= result["confidence"] <= 1.0
    # points must be scaled into the requested display canvas size, not raw pixels
    for p in result["contour_px"]:
        assert 0 <= p["x"] <= 560 + 1
        assert 0 <= p["y"] <= 420 + 1


def test_blank_image_fails_gracefully_not_crash(blank_photo_bytes):
    result = contour_detection.detect_contour(blank_photo_bytes, display_width=400, display_height=400)
    assert result["ok"] is False
    assert result["warning"]


def test_garbage_bytes_do_not_crash():
    result = contour_detection.detect_contour(b"not an image", display_width=100, display_height=100)
    assert result["ok"] is False
    assert result["warning"]
