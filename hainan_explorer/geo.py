"""Geographic helpers: distances, bbox checks, point-in-polygon, corridor distance."""
from __future__ import annotations

import json
import math
from typing import Iterable, Sequence

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def in_bbox(lat: float | None, lon: float | None, bbox: Sequence[float]) -> bool:
    if lat is None or lon is None:
        return False
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east


def point_in_ring(lat: float, lon: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray casting; ring is a list of [lon, lat] pairs (GeoJSON order)."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_geometry(lat: float, lon: float, geometry: dict) -> bool:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        return _point_in_polygon(lat, lon, coords)
    if gtype == "MultiPolygon":
        return any(_point_in_polygon(lat, lon, poly) for poly in coords)
    return False


def _point_in_polygon(lat: float, lon: float, polygon: Sequence[Sequence[Sequence[float]]]) -> bool:
    if not polygon:
        return False
    if not point_in_ring(lat, lon, polygon[0]):
        return False
    return not any(point_in_ring(lat, lon, hole) for hole in polygon[1:])


def _project(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    """Equirectangular projection to km around latitude lat0 (fine for an island)."""
    x = math.radians(lon) * EARTH_RADIUS_KM * math.cos(math.radians(lat0))
    y = math.radians(lat) * EARTH_RADIUS_KM
    return x, y


def distance_to_polyline_km(lat: float, lon: float, line: Sequence[Sequence[float]]) -> float:
    """Shortest straight-line distance from a point to a GeoJSON LineString ([lon, lat] pairs)."""
    if len(line) == 0:
        return float("inf")
    if len(line) == 1:
        return haversine_km(lat, lon, line[0][1], line[0][0])
    lat0 = lat
    px, py = _project(lat, lon, lat0)
    best = float("inf")
    for (lon1, lat1), (lon2, lat2) in zip(line[:-1], line[1:]):
        x1, y1 = _project(lat1, lon1, lat0)
        x2, y2 = _project(lat2, lon2, lat0)
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        if seg_len2 == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
        cx, cy = x1 + t * dx, y1 + t * dy
        d = math.hypot(px - cx, py - cy)
        if d < best:
            best = d
    return best


def distance_to_geometry_km(lat: float, lon: float, geometry: dict) -> float:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "LineString":
        return distance_to_polyline_km(lat, lon, coords)
    if gtype == "MultiLineString":
        return min((distance_to_polyline_km(lat, lon, part) for part in coords), default=float("inf"))
    if gtype == "Point":
        return haversine_km(lat, lon, coords[1], coords[0])
    return float("inf")


def grid_points(bbox: Sequence[float], step_km: float) -> list[tuple[float, float]]:
    """Regular grid of (lat, lon) centres covering the bbox, for radius sweeps."""
    south, west, north, east = bbox
    dlat = step_km / 111.0
    points: list[tuple[float, float]] = []
    lat = south + dlat / 2
    while lat < north:
        dlon = step_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
        lon = west + dlon / 2
        while lon < east:
            points.append((round(lat, 5), round(lon, 5)))
            lon += dlon
        lat += dlat
    return points


def centroid(points: Iterable[tuple[float, float]]) -> tuple[float, float] | None:
    pts = list(points)
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def geometry_from_json(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
