"""Shared shapely helpers for turning raw point lists into well-formed polygons."""

from shapely.geometry import Polygon
from shapely.validation import make_valid


def points_to_polygon(points_cm):
    """points_cm: list of (x, y) or {"x":..,"y":..} in cm. Returns a valid shapely Polygon.

    Auto-detected or manually traced outlines can self-intersect (e.g. a wobbly
    click sequence), which silently breaks area/contains results if not repaired.
    """
    coords = [(p["x"], p["y"]) if isinstance(p, dict) else (p[0], p[1]) for p in points_cm]
    if len(coords) < 3:
        raise ValueError("A polygon needs at least 3 points")
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = make_valid(poly)
    # make_valid can return a GeometryCollection/MultiPolygon for badly self-intersecting
    # input; keep the largest polygonal piece since that is the scrap shape we care about.
    if poly.geom_type != "Polygon":
        candidates = [g for g in getattr(poly, "geoms", []) if g.geom_type == "Polygon"]
        if not candidates:
            raise ValueError("Traced points do not form a usable polygon")
        poly = max(candidates, key=lambda g: g.area)
    return poly


def polygon_to_points(polygon):
    """Inverse of points_to_polygon: exterior ring coordinates as a list of
    {"x":.., "y":..} dicts, for sending a computed polygon (e.g. a leftover
    region) back to the frontend or round-tripping it through /api/stock-in."""
    if polygon.is_empty:
        return []
    return [{"x": x, "y": y} for x, y in polygon.exterior.coords]


def area_cm2(polygon):
    return polygon.area


def bbox(polygon):
    minx, miny, maxx, maxy = polygon.bounds
    return {
        "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy,
        "length": maxx - minx, "width": maxy - miny,
    }
