"""Hainan county-level regions: seeds for discovery and point-to-region assignment.

Region centroids and OSM relation IDs were retrieved from OpenStreetMap (Overpass,
2026-10-27; ODbL, © OpenStreetMap contributors). Boundary polygons are fetched on
demand and cached locally as GeoJSON; assignment falls back to the nearest centroid
when no polygon is available.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .geo import haversine_km, point_in_geometry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    name_en: str
    osm_relation_id: int
    admin_level: int
    lat: float
    lon: float
    coastal: bool
    route_order: int  # counter-clockwise from Haikou; inland counties are detours


# Counter-clockwise order starting in Haikou (west coast first), inland detours interleaved.
REGIONS: tuple[Region, ...] = (
    Region("haikou", "海口市", "Haikou", 2784613, 5, 19.8290566, 110.4055757, True, 0),
    Region("chengmai", "澄迈县", "Chengmai", 2784609, 6, 19.7011233, 109.9896717, True, 1),
    Region("lingao", "临高县", "Lingao", 2784615, 6, 19.7973882, 109.6938518, True, 2),
    Region("danzhou", "儋州市", "Danzhou", 2784610, 5, 19.551314, 109.3448865, True, 3),
    Region("baisha", "白沙黎族自治县", "Baisha", 2784606, 6, 19.2140428, 109.3650475, False, 4),
    Region("qiongzhong", "琼中黎族苗族自治县", "Qiongzhong", 2784618, 6, 19.0721461, 109.8369532, False, 5),
    Region("changjiang", "昌江黎族自治县", "Changjiang", 2784608, 6, 19.202481, 108.9652676, True, 6),
    Region("dongfang", "东方市", "Dongfang", 2784612, 6, 19.0341941, 108.8524886, True, 7),
    Region("ledong", "乐东黎族自治县", "Ledong", 2784614, 6, 18.6468786, 109.0247677, True, 8),
    Region("wuzhishan", "五指山市", "Wuzhishan", 2784622, 6, 18.8314774, 109.5236531, False, 9),
    Region("baoting", "保亭黎族苗族自治县", "Baoting", 2784607, 6, 18.6118865, 109.6236937, False, 10),
    Region("sanya", "三亚市", "Sanya", 2128284, 5, 18.3844686, 109.3675616, True, 11),
    Region("lingshui", "陵水黎族自治县", "Lingshui", 2784616, 6, 18.5770054, 109.9794866, True, 12),
    Region("wanning", "万宁市", "Wanning", 2784620, 6, 18.8427941, 110.303692, True, 13),
    Region("qionghai", "琼海市", "Qionghai", 2784617, 6, 19.224333, 110.4184192, True, 14),
    Region("tunchang", "屯昌县", "Tunchang", 2784619, 6, 19.3637568, 110.0331967, False, 15),
    Region("dingan", "定安县", "Ding'an", 2784611, 6, 19.4728655, 110.3332569, False, 16),
    Region("wenchang", "文昌市", "Wenchang", 2784621, 6, 19.7589303, 110.874227, True, 17),
)

REGION_BY_KEY = {r.key: r for r in REGIONS}
REGION_BY_NAME = {r.name: r for r in REGIONS}
# Short names used in travelogues and OSM addr tags
SHORT_NAMES = {
    "海口": "haikou", "澄迈": "chengmai", "临高": "lingao", "儋州": "danzhou", "白沙": "baisha",
    "琼中": "qiongzhong", "昌江": "changjiang", "东方": "dongfang", "乐东": "ledong", "五指山": "wuzhishan",
    "保亭": "baoting", "三亚": "sanya", "陵水": "lingshui", "万宁": "wanning", "琼海": "qionghai",
    "屯昌": "tunchang", "定安": "dingan", "文昌": "wenchang", "洋浦": "danzhou",
}


def region_from_text(text: str | None) -> Region | None:
    if not text:
        return None
    for name, region in REGION_BY_NAME.items():
        if name in text:
            return region
    for short, key in SHORT_NAMES.items():
        if short in text:
            return REGION_BY_KEY[key]
    return None


class RegionIndex:
    """Assigns coordinates to a region using cached OSM boundary polygons (fallback: nearest centroid)."""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._geometries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            for feature in data.get("features", []):
                key = feature.get("properties", {}).get("key")
                if key and feature.get("geometry"):
                    self._geometries[key] = feature["geometry"]
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not load region boundaries: %s", exc)

    @property
    def has_polygons(self) -> bool:
        return bool(self._geometries)

    def assign(self, lat: float | None, lon: float | None) -> tuple[Region | None, str]:
        """Return (region, method) where method is 'polygon' | 'nearest_centroid' | 'none'."""
        if lat is None or lon is None:
            return None, "none"
        for key, geometry in self._geometries.items():
            if point_in_geometry(lat, lon, geometry):
                return REGION_BY_KEY[key], "polygon"
        nearest = min(REGIONS, key=lambda r: haversine_km(lat, lon, r.lat, r.lon))
        if haversine_km(lat, lon, nearest.lat, nearest.lon) > 80:
            return None, "none"
        return nearest, "nearest_centroid"

    def save(self, features: list[dict]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "type": "FeatureCollection",
            "attribution": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
            "features": features,
        }
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_path)
        self._geometries = {}
        self._load()


def fetch_region_boundaries(ctx) -> int:
    """Fetch the 18 county polygons from Overpass (`out geom`) and cache them as GeoJSON. Returns count."""
    from .discovery.osm import OverpassClient

    ids = ",".join(str(r.osm_relation_id) for r in REGIONS)
    elements = OverpassClient(ctx).query(f"[out:json][timeout:240];relation(id:{ids});out geom;")
    by_id = {e["id"]: e for e in elements}
    features = []
    for region in REGIONS:
        element = by_id.get(region.osm_relation_id)
        geometry = overpass_relation_to_geometry(element) if element else None
        if geometry:
            features.append({"type": "Feature", "properties": {"key": region.key, "name": region.name, "osm_relation_id": region.osm_relation_id}, "geometry": geometry})
    if features:
        ctx.regions.save(features)
    return len(features)


def assemble_rings(ways: list[list[list[float]]]) -> list[list[list[float]]]:
    """Join way geometries ([lon, lat] lists) end-to-end into closed rings."""
    remaining = [list(w) for w in ways if len(w) >= 2]
    rings: list[list[list[float]]] = []
    while remaining:
        ring = remaining.pop(0)
        progress = True
        while progress and ring[0] != ring[-1]:
            progress = False
            for idx, way in enumerate(remaining):
                if way[0] == ring[-1]:
                    ring.extend(way[1:])
                elif way[-1] == ring[-1]:
                    ring.extend(list(reversed(way))[1:])
                elif way[-1] == ring[0]:
                    ring = way[:-1] + ring
                elif way[0] == ring[0]:
                    ring = list(reversed(way))[:-1] + ring
                else:
                    continue
                remaining.pop(idx)
                progress = True
                break
        if ring[0] != ring[-1]:
            ring.append(ring[0])  # force closure of slightly broken rings
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def overpass_relation_to_geometry(element: dict) -> dict | None:
    """Convert an Overpass relation (with `out geom`) into a GeoJSON MultiPolygon of outer rings."""
    outers: list[list[list[float]]] = []
    for member in element.get("members", []):
        if member.get("type") != "way" or member.get("role") not in ("outer", ""):
            continue
        geom = member.get("geometry") or []
        outers.append([[pt["lon"], pt["lat"]] for pt in geom])
    rings = assemble_rings(outers)
    if not rings:
        return None
    return {"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]}
