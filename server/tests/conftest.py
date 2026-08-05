import io

import cv2
import ezdxf
import numpy as np
import pytest


@pytest.fixture
def tmp_excel_path(tmp_path):
    return str(tmp_path / "scrap_inventory.xlsx")


@pytest.fixture
def synthetic_rect_dxf_bytes():
    """A clean 20x10 (drawing units) rectangle, no arcs."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 5  # centimeter
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (20, 0), (20, 10), (0, 10)], close=True)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


@pytest.fixture
def synthetic_arc_dxf_bytes():
    """A rectangle with one rounded (bulge) corner, to prove arcs are flattened."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (20, 0), (20, 10, 0, 0, 1), (0, 10)], format="xyseb", close=True
    )
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


@pytest.fixture
def synthetic_empty_dxf_bytes():
    doc = ezdxf.new("R2010")
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


@pytest.fixture
def synthetic_scrap_photo_bytes():
    """A noisy gray 'production floor' background with a darker irregular blob,
    standing in for a real scrap photo (none are available in this repo)."""
    rng = np.random.default_rng(42)
    img = np.full((600, 800, 3), 150, dtype=np.uint8)
    noise = (rng.standard_normal((600, 800, 3)) * 10).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    pts = np.array(
        [[150, 150], [400, 120], [500, 200], [480, 350], [350, 420], [200, 380], [130, 280]],
        dtype=np.int32,
    )
    cv2.fillPoly(img, [pts], (40, 40, 40))
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def blank_photo_bytes():
    """A featureless black image -- should make auto-detection fail gracefully."""
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()
