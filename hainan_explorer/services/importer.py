"""Imports: legacy data/attractions.json catalogue, CSV/JSON place lists, GPX/GeoJSON corridors."""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from ..normalize import strip_region_prefix
from ..regions import REGION_BY_NAME, region_from_text
from ..taxonomy import category_from_text
from .common import dumps, now_iso
from .context import AppContext
from .ingest import Candidate, Ingestor, SourceSpec

log = logging.getLogger(__name__)

LEGACY_PLATFORM_TYPES = {
    "OpenStreetMap": "map_feature",
    "Wikimedia Commons": "image_page",
    "马蜂窝": "travelogue",
    "携程旅行": "travelogue",
    "小红书": "travelogue",
    "哔哩哔哩": "travelogue",
    "今日头条": "travelogue",
    "搜狐": "web_page",
}


def _legacy_category(legacy_category: str | None, name: str) -> str:
    """The curated legacy category label is more reliable than keywords inside the name."""
    cat = category_from_text(legacy_category)
    if cat == "unknown":
        cat = category_from_text(name)
    return cat


def import_legacy_catalog(ctx: AppContext, path: Path) -> dict[str, Any]:
    """Import the old attractions.json. Names are kept as leads; every claim stays link-only evidence."""
    records = json.loads(path.read_text(encoding="utf-8"))
    ingestor = Ingestor(ctx)
    created = updated = 0
    for rec in records:
        name = rec["name"]
        region_name = rec.get("region")
        region = REGION_BY_NAME.get(region_name) or region_from_text(region_name)
        sources: list[SourceSpec] = []
        src_by_id = {s["id"]: s for s in rec.get("sources", [])}
        for s in rec.get("sources", []):
            platform = s.get("platform", "web")
            notes = s.get("notes")
            excerpt = None
            if rec.get("summary") and s["id"] in rec["summary"].get("source_ids", []):
                excerpt = rec["summary"]["text"]
            sources.append(
                SourceSpec(
                    url=s["url"],
                    provider="legacy_catalog",
                    source_type=LEGACY_PLATFORM_TYPES.get(platform, "web_page"),
                    title=s.get("title"),
                    publisher=platform,
                    author=s.get("author"),
                    published_at=s.get("published_at"),
                    access_status="link_only",
                    license_notes=notes,
                    excerpt=excerpt,
                    relationship_type="mentions" if s.get("kind") == "visitor_experience" else "locates",
                    confidence=0.5,
                )
            )
        lat, lon = rec.get("latitude"), rec.get("longitude")
        coord_src = rec.get("coordinate_source_id")
        coord_provider = "legacy_catalog"
        if coord_src and coord_src in src_by_id and "openstreetmap" in src_by_id[coord_src].get("url", ""):
            coord_provider = "osm_legacy"
        description = None
        if rec.get("summary"):
            description = rec["summary"]["text"]
        notes_lines = list(rec.get("research_notes", []))
        for claim in rec.get("highlights", []):
            notes_lines.append("亮点（来源待核实）：" + claim["text"])
        for claim in rec.get("drawbacks", []):
            notes_lines.append("注意（来源待核实）：" + claim["text"])
        cand = Candidate(
            provider="legacy_catalog",
            external_id=rec["id"],
            name=name,
            aliases=[strip_region_prefix(name)] if strip_region_prefix(name) != name else [],
            latitude=lat,
            longitude=lon,
            coordinate_precision="exact" if coord_provider == "osm_legacy" else "approximate",
            category=_legacy_category(rec.get("category"), name),
            subcategory=rec.get("category"),
            tags={"legacy_catalog": True, "legacy_category": rec.get("category"), "legacy_status": rec.get("status")},
            description=description,
            description_language="zh" if description else None,
            discovery_reason="user_import",
            sources=sources,
            raw={"legacy_record": rec},
            region_hint=region_name,
            needs_geographic_verification=lat is None,
            confidence=0.4,
        )
        result = ingestor.ingest(cand)
        if notes_lines:
            with ctx.db.transaction() as conn:
                conn.execute(
                    "UPDATE places SET personal_notes=COALESCE(personal_notes, ?), updated_at=? WHERE id=?",
                    ("\n".join(notes_lines), now_iso(), result.place_id),
                )
                if region and not conn.execute("SELECT county FROM places WHERE id=?", (result.place_id,)).fetchone()[0]:
                    conn.execute("UPDATE places SET county=?, city=? WHERE id=?", (region.name, region.name, result.place_id))
        if result.action == "created":
            created += 1
        else:
            updated += 1
    return {"records": len(records), "created": created, "updated_or_merged": updated}


def import_csv(ctx: AppContext, path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """CSV columns: name, [latitude], [longitude], [category], [county], [description], [url], [aliases]."""
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
    errors: list[str] = []
    preview: list[dict[str, Any]] = []
    ingestor = Ingestor(ctx)
    created = merged = 0
    for idx, row in enumerate(rows, start=2):
        name = row.get("name") or row.get("名称")
        if not name:
            errors.append(f"line {idx}: missing name")
            continue
        lat = lon = None
        try:
            if row.get("latitude") and row.get("longitude"):
                lat, lon = float(row["latitude"]), float(row["longitude"])
        except ValueError:
            errors.append(f"line {idx}: invalid coordinates")
            continue
        aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
        sources = []
        if row.get("url"):
            sources.append(SourceSpec(url=row["url"], provider="user_import", source_type="user_note", access_status="link_only", relationship_type="user_note", confidence=0.5))
        cand = Candidate(
            provider="user_import",
            external_id=f"{path.name}:{idx}:{name}",
            name=name,
            aliases=aliases,
            latitude=lat,
            longitude=lon,
            coordinate_precision="approximate",
            category=row.get("category") or category_from_text(name),
            description=row.get("description") or None,
            description_language="zh" if row.get("description") else None,
            discovery_reason="user_import",
            sources=sources,
            region_hint=row.get("county"),
            confidence=0.5,
        )
        preview.append({"line": idx, "name": name, "latitude": lat, "longitude": lon, "category": cand.category})
        if not dry_run:
            res = ingestor.ingest(cand)
            if res.action == "created":
                created += 1
            else:
                merged += 1
    return {"rows": len(rows), "errors": errors, "preview": preview[:50], "created": created, "merged": merged, "dry_run": dry_run}


def import_corridor(ctx: AppContext, path: Path, name: str = "用户导入路线", version: str | None = None) -> dict[str, Any]:
    """Import a GPX or GeoJSON line as the active route corridor and recompute distances."""
    text = path.read_text(encoding="utf-8")
    coords: list[list[float]] = []
    if path.suffix.lower() == ".gpx":
        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag in ("trkpt", "rtept", "wpt"):
                try:
                    coords.append([float(el.attrib["lon"]), float(el.attrib["lat"])])
                except (KeyError, ValueError):
                    continue
    else:
        data = json.loads(text)
        geoms = []
        if data.get("type") == "FeatureCollection":
            geoms = [f.get("geometry") for f in data.get("features", []) if f.get("geometry")]
        elif data.get("type") == "Feature":
            geoms = [data.get("geometry")]
        else:
            geoms = [data]
        for g in geoms:
            if g.get("type") == "LineString":
                coords.extend(g["coordinates"])
            elif g.get("type") == "MultiLineString":
                for part in g["coordinates"]:
                    coords.extend(part)
    if len(coords) < 2:
        raise ValueError("no line geometry found")
    geometry = {"type": "LineString", "coordinates": [[round(c[0], 6), round(c[1], 6)] for c in coords]}
    from .corridor import CorridorService
    from .routes import ACTIVE_ROUTE_KEY

    # A single-line corridor replaces the per-day route book as the distance reference.
    with ctx.db.transaction() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (ACTIVE_ROUTE_KEY,))
    return CorridorService(ctx).set_corridor(name, version or now_iso()[:10], geometry, source_note=f"imported from {path.name}", is_estimated=True)
