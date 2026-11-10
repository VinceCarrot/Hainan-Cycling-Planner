"""Route book: the user's own per-day GPX tracks.

Importing a directory of GPX files (one per day) stores each track as a `route_segments` row,
replaces the active corridor with the merged real route, and assigns every place with
coordinates to its nearest day: `route_day`, `route_day_km` (km from that day's start) and
`route_distance_km` (straight-line distance to the track). All of these are estimates derived
from straight-line geometry; they are never road-network distances and are labelled as such.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..crs import CRS_LABELS_ZH, WGS84, convert_coords, from_wgs84, validate_crs
from ..geo import (
    distance_to_bbox_km,
    nearest_on_polyline_km,
    polyline_bbox,
    polyline_cumulative_km,
    polyline_length_km,
    simplify_polyline,
)
from ..taxonomy import CATEGORY_LABELS_ZH
from .common import dumps, loads, now_iso, row_to_dict, rows_to_dicts
from .context import AppContext

log = logging.getLogger(__name__)

ACTIVE_ROUTE_KEY = "active_route_version"
ROUTE_CRS_KEY = "active_route_crs"  # coordinate system the imported GPX files were drawn in (wgs84 | gcj02 | bd09)
SIMPLIFY_TOLERANCE_KM = 0.025  # 25 m: keeps distance error far below the 0.1 km display precision
ELEVATION_HYSTERESIS_M = 5.0
_DAY_RE = re.compile(r"[Dd]ay\s*[_-]?\s*(\d+)")
INTEREST_LABELS = {"want_to_visit": "想去", "maybe": "也许", "skip": "跳过", "needs_research": "待研究", "undecided": "未决定"}
GPX_SYMBOLS = {"want_to_visit": "Flag, Green", "maybe": "Flag, Yellow", "needs_research": "Flag, Blue"}


def parse_gpx_track(path: Path) -> tuple[str | None, list[list[float]]]:
    """Return (name, [[lon, lat, ele?], ...]) from the track/route/waypoints of a GPX file."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    name: str | None = None
    coords: list[list[float]] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "name" and name is None and el.text and el.text.strip():
            name = el.text.strip()
        if tag in ("trkpt", "rtept"):
            try:
                point = [round(float(el.attrib["lon"]), 6), round(float(el.attrib["lat"]), 6)]
            except (KeyError, ValueError):
                continue
            ele = next((c.text for c in el if c.tag.split("}")[-1] == "ele"), None)
            if ele:
                try:
                    point.append(round(float(ele), 1))
                except ValueError:
                    pass
            coords.append(point)
    return name, coords


def elevation_gain_m(coords: list[list[float]], hysteresis: float = ELEVATION_HYSTERESIS_M) -> float | None:
    """Positive elevation gain with a small hysteresis to ignore GPS/DEM noise. None without elevation."""
    eles = [c[2] for c in coords if len(c) > 2]
    if len(eles) < 2:
        return None
    gain = 0.0
    anchor = eles[0]
    for e in eles[1:]:
        if e >= anchor + hysteresis:
            gain += e - anchor
            anchor = e
        elif e <= anchor - hysteresis:
            anchor = e
    return round(gain)


def day_number_from_name(text: str, fallback: int) -> int:
    m = _DAY_RE.search(text)
    return int(m.group(1)) if m else fallback


class RouteService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # ------------------------------------------------------------------ state
    def active_version(self) -> str | None:
        row = self.ctx.db.conn().execute("SELECT value_json FROM settings WHERE key=?", (ACTIVE_ROUTE_KEY,)).fetchone()
        return loads(row["value_json"], None) if row else None

    def crs(self) -> str:
        """Coordinate system of the active route book's source files; WGS-84 unless the user said otherwise."""
        row = self.ctx.db.conn().execute("SELECT value_json FROM settings WHERE key=?", (ROUTE_CRS_KEY,)).fetchone()
        return validate_crs(loads(row["value_json"], None) if row else None)

    def segments(self, version: str | None = None, *, include_geometry: bool = False) -> list[dict[str, Any]]:
        """Segments of a route book. `geometry` is WGS-84 (display/distances); `source_geometry` is the GPX as parsed."""
        version = version or self.active_version()
        if not version:
            return []
        rows = self.ctx.db.conn().execute(
            "SELECT * FROM route_segments WHERE route_version=? ORDER BY sequence_no", (version,)
        ).fetchall()
        out = []
        for d in rows_to_dicts(rows):
            geometry = loads(d.pop("geometry_json"), None)
            source = loads(d.pop("source_geometry_json"), None)
            d["source_crs"] = validate_crs(d.get("source_crs"))
            if include_geometry:
                d["geometry"] = geometry
                d["source_geometry"] = source or geometry
            out.append(d)
        return out

    def summary(self) -> dict[str, Any] | None:
        version = self.active_version()
        if not version:
            return None
        segs = self.segments(version)
        if not segs:
            return None
        conn = self.ctx.db.conn()
        counts = {
            r["route_day"]: dict(r)
            for r in conn.execute(
                """SELECT route_day,
                          COUNT(*) AS places,
                          SUM(route_distance_km <= 1) AS within_1km,
                          SUM(route_distance_km <= 3) AS within_3km,
                          SUM(route_distance_km <= 5) AS within_5km,
                          SUM(interest_status='want_to_visit') AS want,
                          SUM(interest_status='maybe') AS maybe,
                          SUM(interest_status='undecided') AS undecided
                     FROM places
                    WHERE merged_into_place_id IS NULL AND discovery_status!='seed' AND route_day IS NOT NULL
                    GROUP BY route_day"""
            ).fetchall()
        }
        days = []
        for s in segs:
            c = counts.get(s["day_number"], {})
            days.append({
                "day": s["day_number"], "name": s["name"], "distance_km": s["distance_km"], "elevation_gain_m": s["elevation_gain_m"],
                "start": [s["start_lat"], s["start_lon"]], "end": [s["end_lat"], s["end_lon"]], "point_count": s["point_count"],
                "places": c.get("places", 0) or 0, "within_1km": c.get("within_1km", 0) or 0, "within_3km": c.get("within_3km", 0) or 0,
                "within_5km": c.get("within_5km", 0) or 0, "want": c.get("want", 0) or 0, "maybe": c.get("maybe", 0) or 0, "undecided": c.get("undecided", 0) or 0,
            })
        name_row = conn.execute("SELECT name, source_note, created_at FROM route_corridors WHERE version=? ORDER BY id DESC LIMIT 1", (version,)).fetchone()
        crs = self.crs()
        return {
            "version": version,
            "name": name_row["name"] if name_row else version,
            "imported_at": name_row["created_at"] if name_row else None,
            "crs": crs,
            "crs_label": CRS_LABELS_ZH[crs],
            "crs_note": None if crs == WGS84 else "GPX 原始坐标未改动；显示、偏离距离和排序使用转换后的 WGS-84 几何。导出 GPX 时轨迹保持原坐标系，航点也转换到同一坐标系。",
            "days": days,
            "total_km": round(sum(d["distance_km"] or 0 for d in days), 1),
            "distance_note": "沿途公里数与偏离距离均按轨迹直线几何估算，不是路网骑行距离；往返绕行按偏离距离的 2 倍粗估。",
        }

    def geojson(self) -> dict[str, Any]:
        features = []
        for s in self.segments(include_geometry=True):
            if not s.get("geometry"):
                continue
            features.append({
                "type": "Feature",
                "geometry": s["geometry"],
                "properties": {"day": s["day_number"], "name": s["name"], "distance_km": s["distance_km"], "elevation_gain_m": s["elevation_gain_m"]},
            })
        return {"type": "FeatureCollection", "features": features}

    # ----------------------------------------------------------------- import
    def import_directory(self, directory: Path, *, name: str | None = None, version: str | None = None, crs: str | None = None) -> dict[str, Any]:
        """Import `directory/*.gpx` as the route book. `crs` is the system the files were drawn in (default: the current setting)."""
        crs = validate_crs(crs or self.crs())
        directory = Path(directory)
        files = sorted(directory.glob("*.gpx"))
        if not files:
            raise ValueError(f"no .gpx files in {directory}")
        parsed: list[tuple[int, str, Path, list[list[float]]]] = []
        for index, path in enumerate(files, start=1):
            track_name, coords = parse_gpx_track(path)
            if len(coords) < 2:
                log.warning("skipping %s: no track geometry", path.name)
                continue
            day = day_number_from_name(path.stem, day_number_from_name(track_name or "", index))
            parsed.append((day, (track_name or path.stem).strip(), path, coords))
        if not parsed:
            raise ValueError("no usable tracks found")
        parsed.sort(key=lambda item: item[0])
        days = [p[0] for p in parsed]
        if len(set(days)) != len(days):
            raise ValueError(f"duplicate day numbers in file names: {days}")

        version = version or f"route-{now_iso()[:10]}"
        name = name or f"路书 {version}"
        merged: list[list[float]] = []
        stored = []
        for sequence, (day, track_name, path, coords) in enumerate(parsed, start=1):
            wgs = convert_coords(coords, crs)
            merged.extend(simplify_polyline([c[:2] for c in wgs], SIMPLIFY_TOLERANCE_KM))
            stored.append({
                "route_version": version, "sequence_no": sequence, "day_number": day, "name": track_name, "source_file": path.name,
                **self._geometry_fields(coords, wgs, crs),
                "is_estimated": 0, "notes": "user GPX track; distances along the track are geometric estimates",
            })
        with self.ctx.db.transaction() as conn:
            conn.execute("DELETE FROM route_segments WHERE route_version=?", (version,))
            for s in stored:
                conn.execute(
                    """INSERT INTO route_segments (route_version, sequence_no, day_number, name, source_file, distance_km, elevation_gain_m,
                                                   point_count, start_lat, start_lon, end_lat, end_lon, geometry_json, source_crs, source_geometry_json,
                                                   is_estimated, notes, created_at)
                       VALUES (:route_version, :sequence_no, :day_number, :name, :source_file, :distance_km, :elevation_gain_m,
                               :point_count, :start_lat, :start_lon, :end_lat, :end_lon, :geometry_json, :source_crs, :source_geometry_json,
                               :is_estimated, :notes, :created_at)""",
                    {**s, "created_at": now_iso()},
                )
            self._set_setting(conn, ACTIVE_ROUTE_KEY, version)
            self._set_setting(conn, ROUTE_CRS_KEY, crs)
            conn.execute("UPDATE route_corridors SET is_active=0")
            conn.execute(
                "INSERT INTO route_corridors (name, version, geometry_json, source_note, is_estimated, is_active) VALUES (?,?,?,?,0,1)",
                (f"{name}（{len(stored)} 天）", version, dumps({"type": "LineString", "coordinates": merged}),
                 "User route book imported from " + ", ".join(s["source_file"] for s in stored) + f"; source CRS {crs}, stored as WGS-84; straight-line distances only."),
            )
        updated = self.recompute_positions()
        return {
            "version": version, "name": name, "crs": crs,
            "days": [{"day": s["day_number"], "name": s["name"], "file": s["source_file"], "distance_km": s["distance_km"], "points": s["point_count"]} for s in stored],
            "total_km": round(sum(s["distance_km"] for s in stored), 1), "places_updated": updated,
        }

    @staticmethod
    def _geometry_fields(source: list[list[float]], wgs: list[list[float]], crs: str) -> dict[str, Any]:
        return {
            "distance_km": round(polyline_length_km(wgs), 1), "elevation_gain_m": elevation_gain_m(wgs), "point_count": len(wgs),
            "start_lat": wgs[0][1], "start_lon": wgs[0][0], "end_lat": wgs[-1][1], "end_lon": wgs[-1][0],
            "geometry_json": dumps({"type": "LineString", "coordinates": wgs}),
            "source_crs": crs, "source_geometry_json": dumps({"type": "LineString", "coordinates": source}),
        }

    @staticmethod
    def _set_setting(conn, key: str, value: Any) -> None:
        conn.execute(
            "INSERT INTO settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, dumps(value), now_iso()),
        )

    def set_crs(self, crs: str) -> dict[str, Any]:
        """Re-interpret the active route book's source coordinates as `crs` and rebuild the WGS-84 display
        geometry, the merged corridor and every place's day/detour fields. The GPX files are untouched."""
        crs = validate_crs(crs)
        version = self.active_version()
        if not version:
            raise ValueError("no route imported")
        segs = self.segments(version, include_geometry=True)
        merged: list[list[float]] = []
        with self.ctx.db.transaction() as conn:
            for s in segs:
                source = s["source_geometry"]["coordinates"]
                wgs = convert_coords(source, crs)
                merged.extend(simplify_polyline([c[:2] for c in wgs], SIMPLIFY_TOLERANCE_KM))
                fields = self._geometry_fields(source, wgs, crs)
                conn.execute(
                    """UPDATE route_segments SET distance_km=:distance_km, elevation_gain_m=:elevation_gain_m, point_count=:point_count,
                              start_lat=:start_lat, start_lon=:start_lon, end_lat=:end_lat, end_lon=:end_lon,
                              geometry_json=:geometry_json, source_crs=:source_crs, source_geometry_json=:source_geometry_json
                        WHERE id=:id""",
                    {**fields, "id": s["id"]},
                )
            conn.execute("UPDATE route_corridors SET geometry_json=? WHERE version=?", (dumps({"type": "LineString", "coordinates": merged}), version))
            self._set_setting(conn, ROUTE_CRS_KEY, crs)
        updated = self.recompute_positions()
        return {"version": version, "crs": crs, "crs_label": CRS_LABELS_ZH[crs], "segments": len(segs), "places_updated": updated}

    # -------------------------------------------------------------- positions
    def _prepared_tracks(self) -> list[tuple[int, list[list[float]], list[float], tuple[float, float, float, float]]]:
        prepared = []
        for s in self.segments(include_geometry=True):
            line = simplify_polyline([c[:2] for c in s["geometry"]["coordinates"]], SIMPLIFY_TOLERANCE_KM)
            prepared.append((s["day_number"], line, polyline_cumulative_km(line), polyline_bbox(line)))
        return prepared

    @staticmethod
    def _position(lat: float, lon: float, prepared) -> tuple[float, int | None, float]:
        """(straight-line detour km, nearest day, km along that day) for one point."""
        best = (float("inf"), None, 0.0)
        for day, line, cum, bbox in prepared:
            if distance_to_bbox_km(lat, lon, bbox) >= best[0]:
                continue
            dist, along = nearest_on_polyline_km(lat, lon, line, cum)
            if dist < best[0]:
                best = (dist, day, along)
        return round(best[0], 2), best[1], round(best[2], 1)

    def position_place(self, place_id: int) -> dict[str, Any] | None:
        """Assign one place to the route book (after a research/import step located it). None when there is
        no route book or the place has no coordinates; the caller may fall back to the plain corridor."""
        prepared = self._prepared_tracks()
        if not prepared:
            return None
        row = self.ctx.db.conn().execute("SELECT latitude, longitude FROM places WHERE id=?", (place_id,)).fetchone()
        if not row or row["latitude"] is None:
            return None
        dist, day, along = self._position(row["latitude"], row["longitude"], prepared)
        with self.ctx.db.transaction() as conn:
            conn.execute("UPDATE places SET route_distance_km=?, route_day=?, route_day_km=? WHERE id=?", (dist, day, along, place_id))
        return {"route_distance_km": dist, "route_day": day, "route_day_km": along}

    def recompute_positions(self) -> int:
        """Assign every place with coordinates to its nearest day. Returns the number of places updated."""
        prepared = self._prepared_tracks()
        if not prepared:
            return 0
        conn = self.ctx.db.conn()
        rows = conn.execute("SELECT id, latitude, longitude FROM places WHERE latitude IS NOT NULL").fetchall()
        updates = [(*self._position(r["latitude"], r["longitude"], prepared), r["id"]) for r in rows]
        with self.ctx.db.transaction() as wconn:
            wconn.executemany("UPDATE places SET route_distance_km=?, route_day=?, route_day_km=? WHERE id=?", updates)
            wconn.execute("UPDATE places SET route_day=NULL, route_day_km=NULL, route_distance_km=NULL WHERE latitude IS NULL")
            from .ingest import compute_scores

            for r in wconn.execute("SELECT * FROM places WHERE latitude IS NOT NULL").fetchall():
                novelty, score = compute_scores(r)
                wconn.execute("UPDATE places SET novelty_score=?, discovery_score=? WHERE id=?", (novelty, score, r["id"]))
        return len(updates)

    # ----------------------------------------------------------------- export
    def export_gpx(self, *, day: int | None = None, interests: list[str] | None = None, max_detour_km: float | None = None) -> list[Path]:
        """Write one GPX per day: the day's track plus the selected places as waypoints. Returns the files written."""
        interests = interests or ["want_to_visit"]
        segs = [s for s in self.segments(include_geometry=True) if day is None or s["day_number"] == day]
        if not segs:
            raise ValueError("no route imported" if day is None else f"no route day {day}")
        conn = self.ctx.db.conn()
        written = []
        for s in segs:
            where = ["merged_into_place_id IS NULL", "latitude IS NOT NULL", "route_day=?", "interest_status IN (%s)" % ",".join("?" for _ in interests)]
            params: list[Any] = [s["day_number"], *interests]
            if max_detour_km is not None:
                where.append("route_distance_km <= ?")
                params.append(max_detour_km)
            places = conn.execute(f"SELECT * FROM places WHERE {' AND '.join(where)} ORDER BY route_day_km", params).fetchall()
            path = self.ctx.config.exports_dir / f"route-{_slug(s['route_version'])}-day{s['day_number']:02d}-{'_'.join(interests)}.gpx"
            path.write_text(self._gpx_document(s, places, s["source_crs"]), encoding="utf-8")
            written.append(path)
        return written

    def _gpx_document(self, segment: dict[str, Any], places: list, crs: str = WGS84) -> str:
        """The track is written exactly as imported (its original coordinate system); place waypoints, which the
        database holds in WGS-84, are converted into that same system so the file is internally consistent."""
        gpx = ET.Element("gpx", {
            "version": "1.1", "creator": "HainanExplorer", "xmlns": "http://www.topografix.com/GPX/1/1",
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd",
        })
        meta = ET.SubElement(gpx, "metadata")
        ET.SubElement(meta, "name").text = segment["name"]
        ET.SubElement(meta, "desc").text = (
            f"Day {segment['day_number']} · {segment['distance_km']} km · {len(places)} 个地点航点。"
            "航点的沿途公里数与偏离距离为直线估算，不是路网距离。"
            + ("" if crs == WGS84 else f" 坐标系：{CRS_LABELS_ZH[crs]}，与原始路书一致；航点已从 WGS-84 转换。")
        )
        ET.SubElement(meta, "time").text = now_iso()
        for p in places:
            lon, lat = from_wgs84(p["longitude"], p["latitude"], crs)
            wpt = ET.SubElement(gpx, "wpt", {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}"})
            ET.SubElement(wpt, "name").text = p["canonical_name"]
            detour = p["route_distance_km"]
            ET.SubElement(wpt, "desc").text = (
                f"{CATEGORY_LABELS_ZH.get(p['category'], p['category'])} · {INTEREST_LABELS.get(p['interest_status'], p['interest_status'])}"
                + (f" · 第 {p['route_day_km']:.1f} km 附近 · 偏离约 {detour:.1f} km（往返约 {2 * detour:.1f} km，直线估算）" if detour is not None else "")
                + (f" · {p['personal_notes']}" if p["personal_notes"] else "")
            )
            ET.SubElement(wpt, "sym").text = GPX_SYMBOLS.get(p["interest_status"], "Flag, Blue")
            ET.SubElement(wpt, "type").text = p["category"]
        trk = ET.SubElement(gpx, "trk")
        ET.SubElement(trk, "name").text = segment["name"]
        seg = ET.SubElement(trk, "trkseg")
        for c in segment.get("source_geometry", segment["geometry"])["coordinates"]:
            pt = ET.SubElement(seg, "trkpt", {"lat": f"{c[1]:.6f}", "lon": f"{c[0]:.6f}"})
            if len(c) > 2:
                ET.SubElement(pt, "ele").text = f"{c[2]:.1f}"
        ET.indent(gpx, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="unicode")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-") or "route"
