"""Route corridor: a rough polyline used only to triage places by straight-line distance.

The default corridor is built from OSM town/village nodes along the coastal ring,
retrieved live from Overpass (so nothing is invented). It is explicitly an estimate:
the user can replace it with their own GPX/GeoJSON at any time.
"""
from __future__ import annotations

import logging
from typing import Any

from ..geo import distance_to_geometry_km
from .common import dumps, loads, now_iso, row_to_dict
from .context import AppContext

log = logging.getLogger(__name__)

# Counter-clockwise ring of named settlements (Haikou -> west coast -> south -> east -> Haikou).
# Each entry: (display name, OSM name to match, county name used to disambiguate same-named places)
DEFAULT_CORRIDOR_STOPS: list[tuple[str, str, str]] = [
    ("海口", "海口市", "海口市"),
    ("老城镇", "老城镇", "澄迈县"),
    ("马村", "马村", "澄迈县"),
    ("临高县城", "临城镇", "临高县"),
    ("调楼镇", "调楼镇", "临高县"),
    ("新盈镇", "新盈镇", "临高县"),
    ("洋浦", "洋浦", "儋州市"),
    ("白马井镇", "白马井镇", "儋州市"),
    ("排浦镇", "排浦镇", "儋州市"),
    ("海头镇", "海头镇", "儋州市"),
    ("昌化镇", "昌化镇", "昌江黎族自治县"),
    ("海尾镇", "海尾镇", "昌江黎族自治县"),
    ("八所镇", "八所镇", "东方市"),
    ("板桥镇", "板桥镇", "东方市"),
    ("莺歌海镇", "莺歌海镇", "乐东黎族自治县"),
    ("黄流镇", "黄流镇", "乐东黎族自治县"),
    ("崖城", "崖城", "三亚市"),
    ("三亚", "三亚市", "三亚市"),
    ("海棠湾", "海棠湾", "三亚市"),
    ("英州镇", "英州镇", "陵水黎族自治县"),
    ("陵水县城", "椰林镇", "陵水黎族自治县"),
    ("新村镇", "新村镇", "陵水黎族自治县"),
    ("兴隆", "兴隆", "万宁市"),
    ("万宁", "万城镇", "万宁市"),
    ("和乐镇", "和乐镇", "万宁市"),
    ("博鳌镇", "博鳌镇", "琼海市"),
    ("潭门镇", "潭门镇", "琼海市"),
    ("会文镇", "会文镇", "文昌市"),
    ("清澜", "清澜", "文昌市"),
    ("龙楼镇", "龙楼镇", "文昌市"),
    ("翁田镇", "翁田镇", "文昌市"),
    ("铺前镇", "铺前镇", "文昌市"),
    ("演丰镇", "演丰镇", "海口市"),
    ("海口", "海口市", "海口市"),
]


class CorridorService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def active(self) -> dict[str, Any] | None:
        row = self.ctx.db.conn().execute("SELECT * FROM route_corridors WHERE is_active=1 ORDER BY id DESC LIMIT 1").fetchone()
        d = row_to_dict(row)
        if d:
            d["geometry"] = loads(d.pop("geometry_json"), None)
        return d

    def set_corridor(self, name: str, version: str, geometry: dict, *, source_note: str, is_estimated: bool = True) -> dict[str, Any]:
        with self.ctx.db.transaction() as conn:
            conn.execute("UPDATE route_corridors SET is_active=0")
            conn.execute(
                "INSERT INTO route_corridors (name, version, geometry_json, source_note, is_estimated, is_active) VALUES (?,?,?,?,?,1)",
                (name, version, dumps(geometry), source_note, 1 if is_estimated else 0),
            )
        updated = self.recompute_distances()
        return {"name": name, "version": version, "points": len(geometry.get("coordinates", [])), "places_updated": updated}

    def recompute_distances(self) -> int:
        corridor = self.active()
        if not corridor or not corridor.get("geometry"):
            return 0
        geometry = corridor["geometry"]
        conn = self.ctx.db.conn()
        rows = conn.execute("SELECT id, latitude, longitude FROM places WHERE latitude IS NOT NULL").fetchall()
        updates = [(round(distance_to_geometry_km(r["latitude"], r["longitude"], geometry), 2), r["id"]) for r in rows]
        with self.ctx.db.transaction() as wconn:
            wconn.executemany("UPDATE places SET route_distance_km=? WHERE id=?", updates)
            # refresh discovery scores
            from .ingest import compute_scores

            for r in wconn.execute("SELECT * FROM places WHERE latitude IS NOT NULL").fetchall():
                novelty, score = compute_scores(r)
                wconn.execute("UPDATE places SET novelty_score=?, discovery_score=? WHERE id=?", (novelty, score, r["id"]))
        return len(updates)

    def distance_for(self, lat: float, lon: float) -> float | None:
        corridor = self.active()
        if not corridor or not corridor.get("geometry"):
            return None
        return round(distance_to_geometry_km(lat, lon, corridor["geometry"]), 2)

    def build_default_from_osm(self) -> dict[str, Any]:
        """Look up the corridor stops in OSM via Overpass and store the polyline (estimate)."""
        from ..discovery.osm import OverpassClient

        client = OverpassClient(self.ctx)
        names = sorted({osm_name for _, osm_name, _ in DEFAULT_CORRIDOR_STOPS})
        regex = "^(" + "|".join(names) + ")$"
        south, west, north, east = self.ctx.config.bbox
        query = (
            f'[out:json][timeout:120];(node["place"]["name"~"{regex}"]({south},{west},{north},{east});'
            f'way["place"]["name"~"{regex}"]({south},{west},{north},{east});'
            f'relation["place"~"^(city|town)$"]["name"~"{regex}"]({south},{west},{north},{east}););out center tags;'
        )
        elements = client.query(query)
        found: dict[str, list[tuple[float, float, str]]] = {}
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name")
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            if name and lat and lon:
                found.setdefault(name, []).append((lat, lon, tags.get("place", "")))
        coords: list[list[float]] = []
        missing: list[str] = []
        for display, osm_name, county in DEFAULT_CORRIDOR_STOPS:
            options = found.get(osm_name) or []
            if not options:
                missing.append(display)
                continue
            # Disambiguate by region polygon when several same-named places exist.
            chosen = None
            for lat, lon, _ in options:
                region, _m = self.ctx.regions.assign(lat, lon)
                if region and region.name == county:
                    chosen = (lat, lon)
                    break
            if chosen is None:
                # prefer the largest place type
                rank = {"city": 0, "town": 1, "village": 2, "suburb": 3, "hamlet": 4}
                options.sort(key=lambda o: rank.get(o[2], 9))
                chosen = (options[0][0], options[0][1])
            coords.append([round(chosen[1], 6), round(chosen[0], 6)])
        if len(coords) < 4:
            raise RuntimeError(f"too few corridor stops resolved ({len(coords)}); missing: {missing}")
        geometry = {"type": "LineString", "coordinates": coords}
        result = self.set_corridor(
            "粗略环岛走廊（OSM 城镇连线估算）",
            now_iso()[:10],
            geometry,
            source_note="Polyline through OSM town/village nodes along the coastal ring; © OpenStreetMap contributors (ODbL). "
            "Straight-line triage only, not a cycling route.",
            is_estimated=True,
        )
        result["missing_stops"] = missing
        return result
