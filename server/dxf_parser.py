"""Server-side DXF parsing using ezdxf, replacing the frontend's hand-rolled
regex parser (which only understood straight-line LWPOLYLINE/POLYLINE vertices).
ezdxf understands the full DXF entity model, including arc segments (bulges)
within a polyline via `flattening()`, which approximates them as short line
segments -- so curved scrap outlines are now handled, not just straight polygons.
"""

import io

import ezdxf
from ezdxf import path as ezdxf_path

_UNIT_MAP = {
    0: "unknown", 1: "inch", 2: "foot", 3: "mile", 4: "millimeter",
    5: "centimeter", 6: "meter", 7: "kilometer", 8: "microinch", 9: "mil",
    10: "yard", 11: "angstrom",
}


def _shoelace_area(points):
    n = len(points)
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _is_closed(entity):
    closed = getattr(entity, "closed", None)
    if closed is not None:
        return bool(closed)
    return bool(getattr(entity, "is_closed", False))


def parse_dxf(file_bytes, scale_cm_per_unit):
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="ignore")

    try:
        doc = ezdxf.read(io.StringIO(text))
    except ezdxf.DXFStructureError as e:
        return {"ok": False, "warning": f"DXF 檔案結構錯誤：{e}"}
    except Exception as e:
        return {"ok": False, "warning": f"DXF 解析失敗：{e}"}

    units_code = doc.header.get("$INSUNITS", 0)
    units_label = _UNIT_MAP.get(units_code, "unknown")

    shapes = []
    try:
        msp = doc.modelspace()
        for entity in msp:
            if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            if not _is_closed(entity):
                continue
            flat_path = ezdxf_path.make_path(entity)
            pts = [(p.x, p.y) for p in flat_path.flattening(0.1)]
            if len(pts) >= 3:
                shapes.append(pts)
    except Exception as e:
        return {"ok": False, "warning": f"讀取 DXF 圖元時發生錯誤：{e}"}

    if not shapes:
        return {"ok": False, "warning": "DXF 內沒有可計算的封閉多邊形（LWPOLYLINE/POLYLINE）。"}

    best = max(shapes, key=_shoelace_area)
    area_units = _shoelace_area(best)
    area_cm2 = area_units * (scale_cm_per_unit ** 2)

    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    minx, miny = min(xs), min(ys)
    length_cm = (max(xs) - minx) * scale_cm_per_unit
    width_cm = (max(ys) - miny) * scale_cm_per_unit

    # Shift origin to (0,0) so downstream nesting/bbox math doesn't care about the
    # DXF file's absolute drawing coordinates.
    polygon_cm = [
        {"x": (x - minx) * scale_cm_per_unit, "y": (y - miny) * scale_cm_per_unit}
        for x, y in best
    ]

    warning = None
    if len(shapes) > 1:
        warning = f"DXF 內含 {len(shapes)} 個封閉圖形，已取面積最大者作為餘料輪廓。"

    return {
        "ok": True,
        "polygon_cm": polygon_cm,
        "area_cm2": round(area_cm2, 2),
        "length_cm": round(length_cm, 2),
        "width_cm": round(width_cm, 2),
        "units_detected": units_label,
        "warning": warning,
    }
