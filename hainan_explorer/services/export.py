"""Exports (CSV / JSON / GeoJSON) with provenance and image rights metadata, plus backup/restore."""
from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ..taxonomy import CATEGORY_LABELS_ZH
from .common import loads, now_iso, place_code
from .context import AppContext

ATTRIBUTION_NOTES = {
    "osm": "© OpenStreetMap contributors, ODbL 1.0 — https://www.openstreetmap.org/copyright",
    "wikidata": "Wikidata, CC0 1.0 — https://www.wikidata.org",
    "wikipedia_zh": "Wikipedia text excerpts, CC BY-SA 4.0 — attribution to the article URL required",
    "wikipedia_en": "Wikipedia text excerpts, CC BY-SA 4.0 — attribution to the article URL required",
    "commons": "Images from Wikimedia Commons; each image carries its own license and attribution",
}


class ExportService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def _places(self, *, interest: list[str] | None, include_seeds: bool = False) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        where = ["p.merged_into_place_id IS NULL"]
        params: list[Any] = []
        if not include_seeds:
            where.append("p.discovery_status != 'seed'")
        if interest:
            where.append("p.interest_status IN (%s)" % ",".join("?" for _ in interest))
            params += interest
        rows = conn.execute(f"SELECT * FROM places p WHERE {' AND '.join(where)} ORDER BY p.county, p.discovery_score DESC", params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["code"] = place_code(d["id"])
            d["aliases"] = loads(d.pop("aliases_json"), [])
            d["feature_tags"] = loads(d.pop("feature_tags_json"), {})
            d["category_label"] = CATEGORY_LABELS_ZH.get(d["category"], d["category"])
            d["sources"] = [dict(s) for s in conn.execute(
                "SELECT s.provider, s.source_type, s.url, s.title, s.publisher, s.author, s.published_at, s.retrieved_at, s.access_status, s.license_notes, ps.relationship_type, ps.evidence_excerpt "
                "FROM place_sources ps JOIN sources s ON s.id=ps.source_id WHERE ps.place_id=?", (d["id"],)).fetchall()]
            d["provider_ids"] = [dict(s) for s in conn.execute("SELECT provider, external_id, external_url FROM provider_ids WHERE place_id=?", (d["id"],)).fetchall()]
            d["images"] = [dict(s) for s in conn.execute(
                "SELECT i.id AS image_id, i.provider, i.title, i.source_page_url, i.original_url, i.local_path, i.creator, i.attribution_text, i.license_short, i.license_id, i.license_url, "
                "i.permission_status, i.sha256, pi.is_primary, pi.association_status, pi.match_score, pi.verified_by_user "
                "FROM place_images pi JOIN images i ON i.id=pi.image_id WHERE pi.place_id=? AND pi.association_status!='rejected' ORDER BY pi.is_primary DESC, pi.match_score DESC", (d["id"],)).fetchall()]
            d["route_distance_note"] = "straight-line estimate to rough corridor, not cycling distance" if d.get("route_distance_km") is not None else None
            out.append(d)
        return out

    def export_json(self, interest: list[str] | None = None, include_seeds: bool = False) -> str:
        payload = {
            "exported_at": now_iso(),
            "generator": "HainanExplorer",
            "attribution": ATTRIBUTION_NOTES,
            "places": self._places(interest=interest, include_seeds=include_seeds),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def export_geojson(self, interest: list[str] | None = None, include_seeds: bool = False) -> str:
        features = []
        for p in self._places(interest=interest, include_seeds=include_seeds):
            if p["latitude"] is None:
                continue
            props = {k: v for k, v in p.items() if k not in ("latitude", "longitude", "geometry_json", "sources", "images", "provider_ids")}
            props["source_urls"] = [s["url"] for s in p["sources"]]
            props["primary_image"] = next((i for i in p["images"] if i["is_primary"]), None)
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["longitude"], p["latitude"]]}, "properties": props})
        return json.dumps({"type": "FeatureCollection", "attribution": ATTRIBUTION_NOTES, "features": features}, ensure_ascii=False)

    def export_csv(self, interest: list[str] | None = None, include_seeds: bool = False) -> str:
        buf = io.StringIO()
        fields = [
            "code", "id", "canonical_name", "name_en", "aliases", "county", "category", "category_label", "latitude", "longitude",
            "coordinate_source", "coordinate_precision", "needs_geographic_verification", "interest_status", "interest_score", "personal_notes",
            "verification_status", "confidence_score", "discovery_score", "novelty_score", "route_distance_km", "route_distance_note",
            "discovery_reason", "description", "source_count", "image_count", "local_image_count", "source_urls", "primary_image_local_path",
            "primary_image_attribution", "primary_image_license", "primary_image_source_page",
        ]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in self._places(interest=interest, include_seeds=include_seeds):
            primary = next((i for i in p["images"] if i["is_primary"]), None)
            row = dict(p)
            row["aliases"] = "|".join(p["aliases"])
            row["source_urls"] = "|".join(s["url"] for s in p["sources"])
            row["primary_image_local_path"] = primary["local_path"] if primary else ""
            row["primary_image_attribution"] = primary["attribution_text"] if primary else ""
            row["primary_image_license"] = (primary["license_short"] or primary["license_id"]) if primary else ""
            row["primary_image_source_page"] = primary["source_page_url"] if primary else ""
            writer.writerow(row)
        return buf.getvalue()

    def write_export(self, fmt: str, interest: list[str] | None = None, include_seeds: bool = False) -> Path:
        fmt = fmt.lower()
        if fmt == "json":
            text, ext = self.export_json(interest, include_seeds), "json"
        elif fmt == "geojson":
            text, ext = self.export_geojson(interest, include_seeds), "geojson"
        elif fmt == "csv":
            text, ext = self.export_csv(interest, include_seeds), "csv"
        else:
            raise ValueError("format must be json, geojson or csv")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = "-" + "_".join(interest) if interest else ""
        path = self.ctx.config.exports_dir / f"places-{stamp}{suffix}.{ext}"
        path.write_text(text, encoding="utf-8-sig" if ext == "csv" else "utf-8")
        return path


class BackupService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def backup(self, label: str | None = None) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"explorer-{stamp}" + (f"-{label}" if label else "") + ".db"
        dest = self.ctx.config.backups_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = self.ctx.db.conn()
        tmp = dest.with_suffix(".db.part")
        target = sqlite3.connect(str(tmp))
        try:
            src.backup(target)
        finally:
            target.close()
        tmp.replace(dest)
        return dest

    def list_backups(self) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self.ctx.config.backups_dir.glob("*.db"), reverse=True):
            st = path.stat()
            out.append({"name": path.name, "bytes": st.st_size, "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
        return out

    def restore(self, backup_name: str) -> Path:
        """Restore a backup over the live DB; the current DB is saved first (never silently overwritten)."""
        source = self.ctx.config.backups_dir / Path(backup_name).name
        if not source.is_file():
            raise FileNotFoundError(backup_name)
        safety = self.backup(label="pre-restore")
        self.ctx.db.close()
        live = self.ctx.config.db_path
        for suffix in ("-wal", "-shm"):
            side = live.with_name(live.name + suffix)
            if side.exists():
                side.unlink()
        shutil.copy2(source, live)
        self.ctx.db.migrate()
        return safety
