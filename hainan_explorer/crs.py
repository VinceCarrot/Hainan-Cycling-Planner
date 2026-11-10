"""Coordinate reference systems used by Chinese map providers.

GPS devices, OpenStreetMap and this database use WGS-84. Map products published in mainland China
are offset by the GCJ-02 ("Mars") transformation; Baidu adds a second transformation (BD-09) on top.
A route drawn on a Chinese web map (Garmin Connect China, Amap, Baidu) is therefore stored in GCJ-02
or BD-09 and appears shifted by a few hundred metres when drawn on an OSM basemap.

These functions only convert for *display and distance calculations*. The user's GPX files are never
rewritten. Forward transforms (WGS-84 → GCJ-02 → BD-09) are the public approximations; the inverse of
GCJ-02 is solved iteratively and is accurate to well under one metre.

All functions take and return (lon, lat) to match GeoJSON coordinate order.
"""
from __future__ import annotations

import math

WGS84 = "wgs84"
GCJ02 = "gcj02"
BD09 = "bd09"
CRS_CHOICES = (WGS84, GCJ02, BD09)
CRS_LABELS_ZH = {
    WGS84: "WGS-84（GPS / OpenStreetMap，不转换）",
    GCJ02: "GCJ-02（火星坐标：高德、腾讯、佳明中国）",
    BD09: "BD-09（百度坐标）",
}

_A = 6378245.0
_EE = 0.00669342162296594323
_X_PI = math.pi * 3000.0 / 180.0


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _gcj_delta(lon: float, lat: float) -> tuple[float, float]:
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return dlon, dlat


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    dlon, dlat = _gcj_delta(lon, lat)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float, iterations: int = 4) -> tuple[float, float]:
    """Iterative inverse: converges to < 0.01 m in a handful of steps."""
    wlon, wlat = lon, lat
    for _ in range(iterations):
        glon, glat = wgs84_to_gcj02(wlon, wlat)
        wlon += lon - glon
        wlat += lat - glat
    return wlon, wlat


def gcj02_to_bd09(lon: float, lat: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * _X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    x = lon - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def to_wgs84(lon: float, lat: float, crs: str) -> tuple[float, float]:
    if crs == WGS84:
        return lon, lat
    if crs == GCJ02:
        return gcj02_to_wgs84(lon, lat)
    if crs == BD09:
        return gcj02_to_wgs84(*bd09_to_gcj02(lon, lat))
    raise ValueError(f"unknown coordinate system: {crs}")


def from_wgs84(lon: float, lat: float, crs: str) -> tuple[float, float]:
    if crs == WGS84:
        return lon, lat
    if crs == GCJ02:
        return wgs84_to_gcj02(lon, lat)
    if crs == BD09:
        return gcj02_to_bd09(*wgs84_to_gcj02(lon, lat))
    raise ValueError(f"unknown coordinate system: {crs}")


def convert_coords(coords: list[list[float]], crs_from: str, crs_to: str = WGS84, precision: int = 7) -> list[list[float]]:
    """Convert a GeoJSON coordinate list ([lon, lat, ele?]) between systems, keeping extra members."""
    if crs_from == crs_to:
        return [list(c) for c in coords]
    out = []
    for c in coords:
        lon, lat = to_wgs84(c[0], c[1], crs_from)
        if crs_to != WGS84:
            lon, lat = from_wgs84(lon, lat, crs_to)
        out.append([round(lon, precision), round(lat, precision), *c[2:]])
    return out


def validate_crs(crs: str | None) -> str:
    crs = (crs or WGS84).lower().replace("-", "")
    if crs not in CRS_CHOICES:
        raise ValueError(f"coordinate system must be one of {', '.join(CRS_CHOICES)}")
    return crs
