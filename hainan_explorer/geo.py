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


# ----------------------------------------------------------------------------- route books
# Helpers for per-day route tracks: simplification, cumulative distance and the position of a
# point along a track. All polylines are GeoJSON-style [lon, lat(, ele)] sequences.


def polyline_bbox(line: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """(south, west, north, east) of a [lon, lat] polyline."""
    lats = [p[1] for p in line]
    lons = [p[0] for p in line]
    return (min(lats), min(lons), max(lats), max(lons))


def distance_to_bbox_km(lat: float, lon: float, bbox: Sequence[float]) -> float:
    """Lower bound of the distance from a point to anything inside the bbox (0 when inside)."""
    south, west, north, east = bbox
    clat = min(max(lat, south), north)
    clon = min(max(lon, west), east)
    if clat == lat and clon == lon:
        return 0.0
    return haversine_km(lat, lon, clat, clon)


def polyline_length_km(line: Sequence[Sequence[float]]) -> float:
    return sum(haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(line[:-1], line[1:]))


def polyline_cumulative_km(line: Sequence[Sequence[float]]) -> list[float]:
    """Cumulative distance from the start at every vertex (same length as the line)."""
    cum = [0.0]
    for a, b in zip(line[:-1], line[1:]):
        cum.append(cum[-1] + haversine_km(a[1], a[0], b[1], b[0]))
    return cum


def simplify_polyline(line: Sequence[Sequence[float]], tolerance_km: float) -> list[list[float]]:
    """Douglas-Peucker simplification (iterative). Keeps the first and last vertex."""
    n = len(line)
    if n < 3:
        return [list(p) for p in line]
    lat0 = sum(p[1] for p in line) / n
    pts = [_project(p[1], p[0], lat0) for p in line]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        x1, y1 = pts[start]
        x2, y2 = pts[end]
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        worst, worst_i = -1.0, -1
        for i in range(start + 1, end):
            px, py = pts[i]
            if seg_len2 == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
                d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance_km and worst_i > 0:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))
    return [list(p) for p, k in zip(line, keep) if k]


def nearest_on_polyline_km(
    lat: float, lon: float, line: Sequence[Sequence[float]], cumulative: Sequence[float] | None = None
) -> tuple[float, float]:
    """(straight-line distance km, distance along the line km) for the closest point on the line."""
    if len(line) == 0:
        return float("inf"), 0.0
    if len(line) == 1:
        return haversine_km(lat, lon, line[0][1], line[0][0]), 0.0
    cum = cumulative or polyline_cumulative_km(line)
    lat0 = lat
    px, py = _project(lat, lon, lat0)
    best, best_along = float("inf"), 0.0
    for i in range(len(line) - 1):
        lon1, lat1 = line[i][0], line[i][1]
        lon2, lat2 = line[i + 1][0], line[i + 1][1]
        x1, y1 = _project(lat1, lon1, lat0)
        x2, y2 = _project(lat2, lon2, lat0)
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        t = 0.0 if seg_len2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
        d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
        if d < best:
            best = d
            best_along = cum[i] + t * (cum[i + 1] - cum[i])
    return best, best_along
