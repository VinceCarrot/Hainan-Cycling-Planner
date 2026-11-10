"""Place queries, decisions (with undo), notes, verification, merge/unmerge."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..geo import haversine_km
from ..regions import REGION_BY_KEY, REGIONS
from ..taxonomy import CATEGORY_LABELS_ZH
from .common import dumps, loads, now_iso, place_code, row_to_dict, rows_to_dicts
from .context import AppContext

INTEREST_STATUSES = ("undecided", "want_to_visit", "maybe", "skip", "needs_research")
VERIFICATION_STATUSES = ("unverified", "partially_verified", "verified", "disputed")
SORT_OPTIONS = {
    "recent": "p.created_at DESC",
    "updated": "p.updated_at DESC",
    "novelty": "p.novelty_score DESC, p.discovery_score DESC",
    "score": "p.discovery_score DESC",
    "confidence": "p.confidence_score DESC",
    "route": "CASE WHEN p.route_distance_km IS NULL THEN 1 ELSE 0 END, p.route_distance_km ASC",
    "unreviewed": "CASE WHEN p.interest_status='undecided' THEN 0 ELSE 1 END, p.discovery_score DESC",
    "name": "p.canonical_name ASC",
    "region": "region_order ASC, p.discovery_score DESC",
    "images": "p.local_image_count DESC, p.image_count DESC, p.discovery_score DESC",
    # Route-book sorts: by day, then by detour (straight-line distance to that day's track) or by km along the day.
    "day_detour": "CASE WHEN p.route_day IS NULL THEN 1 ELSE 0 END, p.route_day ASC, p.route_distance_km ASC, p.discovery_score DESC",
    "day_km": "CASE WHEN p.route_day IS NULL THEN 1 ELSE 0 END, p.route_day ASC, p.route_day_km ASC, p.route_distance_km ASC",
}


class PlaceService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # ---------------------------------------------------------------- listing
    def list_places(
        self,
        *,
        q: str | None = None,
        region: str | None = None,
        category: str | None = None,
        interest: str | None = None,
        discovery_status: str | None = None,
        image_state: str | None = None,  # local | remote | none | any_image
        min_sources: int | None = None,
        min_confidence: float | None = None,
        max_route_km: float | None = None,
        day: int | None = None,
        coastal: bool | None = None,
        has_coords: bool | None = None,
        needs_geo: bool | None = None,
        duplicates_only: bool = False,
        undecided_only: bool = False,
        include_seeds: bool = False,
        sort: str = "region",
        limit: int = 60,
        offset: int = 0,
    ) -> dict[str, Any]:
        where = ["p.merged_into_place_id IS NULL"]
        params: list[Any] = []
        if not include_seeds and discovery_status is None:
            where.append("p.discovery_status != 'seed'")
        if discovery_status:
            where.append("p.discovery_status = ?")
            params.append(discovery_status)
        if q:
            where.append("(p.canonical_name LIKE ? OR p.aliases_json LIKE ? OR p.name_en LIKE ? OR p.description LIKE ?)")
            like = f"%{q}%"
            params += [like, like, like, like]
        if region:
            reg = REGION_BY_KEY.get(region)
            where.append("p.county = ?")
            params.append(reg.name if reg else region)
        if category:
            cats = [c for c in category.split(",") if c]
            where.append("p.category IN (%s)" % ",".join("?" for _ in cats))
            params += cats
        if interest:
            vals = [v for v in interest.split(",") if v]
            where.append("p.interest_status IN (%s)" % ",".join("?" for _ in vals))
            params += vals
        if undecided_only:
            where.append("p.interest_status = 'undecided'")
        if image_state == "local":
            where.append("p.local_image_count > 0")
        elif image_state == "remote":
            where.append("p.image_count > 0 AND p.local_image_count = 0")
        elif image_state == "none":
            where.append("p.image_count = 0")
        elif image_state == "any_image":
            where.append("p.image_count > 0")
        if min_sources:
            where.append("p.source_count >= ?")
            params.append(min_sources)
        if min_confidence is not None:
            where.append("p.confidence_score >= ?")
            params.append(min_confidence)
        if max_route_km is not None:
            where.append("p.route_distance_km IS NOT NULL AND p.route_distance_km <= ?")
            params.append(max_route_km)
        if day is not None:
            where.append("p.route_day = ?")
            params.append(day)
        if coastal is not None:
            where.append("p.is_coastal = ?")
            params.append(1 if coastal else 0)
        if has_coords is True:
            where.append("p.latitude IS NOT NULL")
        elif has_coords is False:
            where.append("p.latitude IS NULL")
        if needs_geo is True:
            where.append("p.needs_geographic_verification = 1")
        if duplicates_only:
            where.append(
                "EXISTS (SELECT 1 FROM place_relations r WHERE r.review_status='pending' AND (r.place_id_a=p.id OR r.place_id_b=p.id))"
            )
        order = SORT_OPTIONS.get(sort, SORT_OPTIONS["region"])
        region_case = " ".join(f"WHEN '{r.name}' THEN {r.route_order}" for r in REGIONS)
        sql = f"""
            SELECT p.*, (CASE p.county {region_case} ELSE 99 END) AS region_order,
                   (SELECT i.thumbnail_path FROM images i WHERE i.id = (
                       SELECT pi.image_id FROM place_images pi JOIN images i2 ON i2.id=pi.image_id
                        WHERE pi.place_id=p.id AND pi.association_status!='rejected'
                          AND (i2.thumbnail_path IS NOT NULL OR (i2.display_url IS NOT NULL AND i2.permission_status IN ('link_only','api_display_only','local_copy_allowed')))
                        ORDER BY pi.verified_by_user DESC, pi.match_score DESC, (i2.thumbnail_path IS NOT NULL) DESC LIMIT 1)) AS primary_thumbnail,
                   (SELECT i.display_url FROM images i WHERE i.id = (
                       SELECT pi.image_id FROM place_images pi JOIN images i2 ON i2.id=pi.image_id
                        WHERE pi.place_id=p.id AND pi.association_status!='rejected'
                          AND (i2.thumbnail_path IS NOT NULL OR (i2.display_url IS NOT NULL AND i2.permission_status IN ('link_only','api_display_only','local_copy_allowed')))
                        ORDER BY pi.verified_by_user DESC, pi.match_score DESC, (i2.thumbnail_path IS NOT NULL) DESC LIMIT 1)) AS primary_remote_url,
                   (SELECT MAX(pi.match_score) FROM place_images pi WHERE pi.place_id=p.id AND pi.association_status!='rejected') AS best_image_score,
                   (SELECT MAX(pi.verified_by_user) FROM place_images pi WHERE pi.place_id=p.id) AS any_image_verified,
                   (SELECT COUNT(*) FROM place_relations r WHERE r.review_status='pending' AND (r.place_id_a=p.id OR r.place_id_b=p.id)) AS pending_duplicates
            FROM places p
            WHERE {' AND '.join(where)}
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """
        conn = self.ctx.db.conn()
        rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM places p WHERE {' AND '.join(where)}", params).fetchone()[0]
        return {"total": total, "limit": limit, "offset": offset, "items": [self._card(r) for r in rows]}

    def _card(self, row: sqlite3.Row) -> dict[str, Any]:
        d = row_to_dict(row) or {}
        d["code"] = place_code(d["id"])
        d["aliases"] = loads(d.pop("aliases_json", "[]"), [])
        d["feature_tags"] = loads(d.pop("feature_tags_json", "{}"), {})
        d["category_label"] = CATEGORY_LABELS_ZH.get(d["category"], d["category"])
        d["image_state"] = (
            "local" if d.get("local_image_count") else ("remote" if d.get("image_count") else "none")
        )
        if d.get("primary_thumbnail"):
            d["thumbnail_url"] = f"/media/thumbnails/{d['primary_thumbnail']}"
        else:
            d["thumbnail_url"] = None
        # Representative image for the card: local thumbnail first, otherwise a small remote
        # Commons thumbnail (hotlinked; Wikimedia permits this for modest personal use).
        d["card_image_url"] = d["thumbnail_url"] or commons_thumb(d.get("primary_remote_url"), 480)
        d["image_badge"] = _image_badge(d)
        return d

    # ----------------------------------------------------------------- detail
    def get_place(self, place_id: int) -> dict[str, Any] | None:
        conn = self.ctx.db.conn()
        row = conn.execute(
            """SELECT p.*,
                      (SELECT MAX(pi.match_score) FROM place_images pi WHERE pi.place_id=p.id AND pi.association_status!='rejected') AS best_image_score,
                      (SELECT MAX(pi.verified_by_user) FROM place_images pi WHERE pi.place_id=p.id AND pi.association_status!='rejected') AS any_image_verified,
                      (SELECT COUNT(*) FROM place_relations r WHERE r.review_status='pending' AND (r.place_id_a=p.id OR r.place_id_b=p.id)) AS pending_duplicates
               FROM places p WHERE p.id=?""",
            (place_id,),
        ).fetchone()
        if not row:
            return None
        d = self._card(row)
        d["provider_ids"] = rows_to_dicts(
            conn.execute("SELECT provider, external_id, external_url, fetched_at FROM provider_ids WHERE place_id=? ORDER BY provider", (place_id,)).fetchall()
        )
        d["sources"] = rows_to_dicts(
            conn.execute(
                """SELECT s.*, ps.relationship_type, ps.evidence_excerpt, ps.confidence_score AS link_confidence
                   FROM place_sources ps JOIN sources s ON s.id=ps.source_id WHERE ps.place_id=?
                   ORDER BY ps.confidence_score DESC, s.retrieved_at""",
                (place_id,),
            ).fetchall()
        )
        d["images"] = [self._image_dict(r) for r in conn.execute(
            """SELECT i.*, pi.is_primary, pi.association_status, pi.match_score, pi.match_reasons_json, pi.verified_by_user, pi.notes AS association_notes
               FROM place_images pi JOIN images i ON i.id=pi.image_id WHERE pi.place_id=?
               ORDER BY pi.association_status='rejected', pi.verified_by_user DESC, pi.match_score DESC, (i.local_path IS NOT NULL) DESC""",
            (place_id,),
        ).fetchall()]
        d["reviews"] = rows_to_dicts(conn.execute("SELECT * FROM reviews WHERE place_id=? ORDER BY reviewed_at DESC LIMIT 50", (place_id,)).fetchall())
        d["relations"] = self.relations_for(place_id)
        d["nearby"] = self.nearby(place_id, radius_km=3.0, limit=12)
        d["merged_children"] = rows_to_dicts(conn.execute("SELECT id, canonical_name FROM places WHERE merged_into_place_id=?", (place_id,)).fetchall())
        corridor = conn.execute("SELECT is_estimated FROM route_corridors WHERE is_active=1 ORDER BY id DESC LIMIT 1").fetchone()
        d["facts"] = self._facts(d, corridor_is_estimated=bool(corridor["is_estimated"]) if corridor else True)
        return d

    @staticmethod
    def _image_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = row_to_dict(row) or {}
        d["match_reasons"] = loads(d.pop("match_reasons_json", "[]"), [])
        d["categories"] = loads(d.pop("categories_json", "[]"), [])
        d["local_url"] = f"/media/images/{d['local_path']}" if d.get("local_path") else None
        d["thumbnail_url"] = f"/media/thumbnails/{d['thumbnail_path']}" if d.get("thumbnail_path") else None
        return d

    @staticmethod
    def _facts(d: dict[str, Any], corridor_is_estimated: bool = True) -> dict[str, list[dict[str, Any]]]:
        """Separate sourced facts, derived estimates and unknowns for the detail panel."""
        sourced: list[dict[str, Any]] = []
        derived: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        if d.get("latitude") is not None:
            entry = {"label": "坐标", "value": f"{d['latitude']:.5f}, {d['longitude']:.5f}", "source": d.get("coordinate_source")}
            (sourced if d.get("coordinate_precision") == "exact" else derived).append(entry)
        else:
            unknown.append({"label": "坐标", "value": "未知（需地理核实）"})
        if d.get("county"):
            derived.append({"label": "所属市县", "value": d["county"], "note": "由坐标落入行政边界或名称推断"})
        else:
            unknown.append({"label": "所属市县", "value": "未知"})
        if d.get("route_day") is not None and d.get("route_distance_km") is not None:
            detour = d["route_distance_km"]
            derived.append({
                "label": "路书位置",
                "value": f"Day {d['route_day']} 第 {d['route_day_km']:.1f} km 附近，偏离路线约 {detour:.1f} km（往返约 {2 * detour:.1f} km）",
                "note": "按轨迹直线几何估算，不是路网骑行距离",
            })
        elif d.get("route_distance_km") is not None:
            label = "到路书路线的直线距离" if not corridor_is_estimated else "到粗略环岛走廊的直线距离"
            derived.append({"label": label, "value": f"约 {d['route_distance_km']:.1f} km", "note": "直线距离估算，不是骑行距离"})
        else:
            unknown.append({"label": "到环岛走廊距离", "value": "未计算"})
        unknown.append({"label": "是否开放/可进入", "value": "未知，需现场或资料核实"})
        if d.get("description"):
            sourced.append({"label": "描述", "value": d["description"], "source": d.get("description_language")})
        return {"sourced": sourced, "derived": derived, "unknown": unknown}

    def nearby(self, place_id: int, radius_km: float = 3.0, limit: int = 12) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        row = conn.execute("SELECT latitude, longitude FROM places WHERE id=?", (place_id,)).fetchone()
        if not row or row["latitude"] is None:
            return []
        lat, lon = row["latitude"], row["longitude"]
        dlat = radius_km / 111.0
        dlon = radius_km / 105.0
        rows = conn.execute(
            """SELECT id, canonical_name, category, county, latitude, longitude, discovery_status, interest_status, image_count
               FROM places WHERE merged_into_place_id IS NULL AND id!=? AND latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?""",
            (place_id, lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r) or {}
            d["distance_km"] = round(haversine_km(lat, lon, r["latitude"], r["longitude"]), 2)
            if d["distance_km"] <= radius_km:
                d["category_label"] = CATEGORY_LABELS_ZH.get(d["category"], d["category"])
                out.append(d)
        out.sort(key=lambda x: x["distance_km"])
        return out[:limit]

    def relations_for(self, place_id: int) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        rows = conn.execute(
            """SELECT r.*, pa.canonical_name AS name_a, pb.canonical_name AS name_b
               FROM place_relations r JOIN places pa ON pa.id=r.place_id_a JOIN places pb ON pb.id=r.place_id_b
               WHERE r.place_id_a=? OR r.place_id_b=? ORDER BY r.review_status='pending' DESC, r.confidence_score DESC""",
            (place_id, place_id),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r) or {}
            d["reasons"] = loads(d.pop("reasons_json", "[]"), [])
            out.append(d)
        return out

    # -------------------------------------------------------------- decisions
    def decide(self, place_id: int, decision: str, score: int | None = None, reason: str | None = None) -> dict[str, Any]:
        if decision not in INTEREST_STATUSES:
            raise ValueError(f"invalid decision: {decision}")
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT interest_status, interest_score FROM places WHERE id=?", (place_id,)).fetchone()
            if not row:
                raise KeyError(place_id)
            conn.execute(
                "INSERT INTO reviews (place_id, decision, previous_decision, score, reason) VALUES (?,?,?,?,?)",
                (place_id, decision, row["interest_status"], score, reason),
            )
            conn.execute(
                "UPDATE places SET interest_status=?, interest_score=COALESCE(?, interest_score), updated_at=? WHERE id=?",
                (decision, score, now_iso(), place_id),
            )
        return self.get_place(place_id) or {}

    def undo_last_decision(self, place_id: int | None = None) -> dict[str, Any] | None:
        with self.ctx.db.transaction() as conn:
            if place_id is None:
                row = conn.execute(
                    "SELECT * FROM reviews WHERE undone=0 AND decision IN (%s) ORDER BY id DESC LIMIT 1" % ",".join("?" for _ in INTEREST_STATUSES),
                    INTEREST_STATUSES,
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM reviews WHERE place_id=? AND undone=0 AND decision IN (%s) ORDER BY id DESC LIMIT 1" % ",".join("?" for _ in INTEREST_STATUSES),
                    (place_id, *INTEREST_STATUSES),
                ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE reviews SET undone=1 WHERE id=?", (row["id"],))
            conn.execute(
                "UPDATE places SET interest_status=?, updated_at=? WHERE id=?",
                (row["previous_decision"] or "undecided", now_iso(), row["place_id"]),
            )
            pid = row["place_id"]
        return self.get_place(pid)

    def update_notes(self, place_id: int, notes: str | None = None, verification_status: str | None = None,
                     canonical_name: str | None = None, category: str | None = None,
                     latitude: float | None = None, longitude: float | None = None) -> dict[str, Any]:
        if verification_status and verification_status not in VERIFICATION_STATUSES:
            raise ValueError("invalid verification status")
        with self.ctx.db.transaction() as conn:
            row = conn.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone()
            if not row:
                raise KeyError(place_id)
            updates: dict[str, Any] = {"updated_at": now_iso()}
            if notes is not None:
                updates["personal_notes"] = notes
            if verification_status:
                updates["verification_status"] = verification_status
                conn.execute("INSERT INTO reviews (place_id, decision, reason) VALUES (?, 'verify', ?)", (place_id, verification_status))
            if canonical_name and canonical_name != row["canonical_name"]:
                from ..normalize import normalize_name

                aliases = loads(row["aliases_json"], [])
                if row["canonical_name"] not in aliases:
                    aliases.append(row["canonical_name"])
                updates.update(canonical_name=canonical_name, normalized_name=normalize_name(canonical_name), aliases_json=dumps(aliases))
            if category:
                updates["category"] = category
            if latitude is not None and longitude is not None:
                updates.update(latitude=latitude, longitude=longitude, coordinate_source="user", coordinate_precision="exact", needs_geographic_verification=0)
                region, _ = self.ctx.regions.assign(latitude, longitude)
                if region:
                    updates.update(county=region.name, city=region.name)
                conn.execute("INSERT INTO reviews (place_id, decision, reason) VALUES (?, 'coordinates', ?)", (place_id, f"{row['latitude']},{row['longitude']} -> {latitude},{longitude}"))
            sets = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE places SET {sets} WHERE id=?", (*updates.values(), place_id))
        if latitude is not None and longitude is not None:
            self._position_on_route(place_id, latitude, longitude)
        return self.get_place(place_id) or {}

    def _position_on_route(self, place_id: int, latitude: float, longitude: float) -> None:
        """Manually pinned coordinates get the same route-book fields (day, km, detour) as discovered ones."""
        from .corridor import CorridorService
        from .routes import RouteService

        if RouteService(self.ctx).position_place(place_id) is None:
            d = CorridorService(self.ctx).distance_for(latitude, longitude)
            with self.ctx.db.transaction() as conn:
                conn.execute("UPDATE places SET route_distance_km=?, route_day=NULL, route_day_km=NULL WHERE id=?", (d, place_id))

    def bulk_decide(self, place_ids: list[int], decision: str) -> int:
        count = 0
        for pid in place_ids:
            try:
                self.decide(pid, decision)
                count += 1
            except KeyError:
                continue
        return count

    # ---------------------------------------------------------------- merging
    def merge(self, source_id: int, target_id: int, reason: str | None = None) -> dict[str, Any]:
        """Reversible merge: source is pointed at target; links are copied (not moved) and audited."""
        if source_id == target_id:
            raise ValueError("cannot merge a place into itself")
        with self.ctx.db.transaction() as conn:
            src = conn.execute("SELECT * FROM places WHERE id=?", (source_id,)).fetchone()
            tgt = conn.execute("SELECT * FROM places WHERE id=?", (target_id,)).fetchone()
            if not src or not tgt:
                raise KeyError("place not found")
            if src["merged_into_place_id"] is not None:
                raise ValueError("source already merged")
            audit = {
                "source_snapshot": row_to_dict(src),
                "provider_ids": rows_to_dicts(conn.execute("SELECT provider, external_id FROM provider_ids WHERE place_id=?", (source_id,)).fetchall()),
                "copied_sources": [r[0] for r in conn.execute("SELECT source_id FROM place_sources WHERE place_id=?", (source_id,)).fetchall()],
                "copied_images": [r[0] for r in conn.execute("SELECT image_id FROM place_images WHERE place_id=?", (source_id,)).fetchall()],
                "target_aliases_before": loads(tgt["aliases_json"], []),
                "merged_at": now_iso(),
            }
            aliases = loads(tgt["aliases_json"], [])
            for alias in [src["canonical_name"], *loads(src["aliases_json"], [])]:
                if alias and alias != tgt["canonical_name"] and alias not in aliases:
                    aliases.append(alias)
            updates = {"aliases_json": dumps(aliases), "updated_at": now_iso()}
            if tgt["latitude"] is None and src["latitude"] is not None:
                updates.update(latitude=src["latitude"], longitude=src["longitude"], coordinate_source=src["coordinate_source"],
                               coordinate_precision=src["coordinate_precision"], needs_geographic_verification=0)
            if not tgt["description"] and src["description"]:
                updates.update(description=src["description"], description_language=src["description_language"])
            sets = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE places SET {sets} WHERE id=?", (*updates.values(), target_id))
            conn.execute(
                "INSERT OR IGNORE INTO place_sources (place_id, source_id, relationship_type, evidence_excerpt, confidence_score) "
                "SELECT ?, source_id, relationship_type, evidence_excerpt, confidence_score FROM place_sources WHERE place_id=?",
                (target_id, source_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO place_images (place_id, image_id, is_primary, association_type, association_status, match_score, match_reasons_json, confidence_score, verified_by_user, notes) "
                "SELECT ?, image_id, 0, association_type, association_status, match_score, match_reasons_json, confidence_score, verified_by_user, notes FROM place_images WHERE place_id=?",
                (target_id, source_id),
            )
            conn.execute("UPDATE provider_ids SET place_id=? WHERE place_id=?", (target_id, source_id))
            conn.execute("UPDATE places SET merged_into_place_id=?, updated_at=? WHERE id=?", (target_id, now_iso(), source_id))
            conn.execute(
                """INSERT INTO place_relations (place_id_a, place_id_b, relation_type, confidence_score, reasons_json, review_status, audit_json)
                   VALUES (?,?,'duplicate_of',1.0,?, 'merged', ?)
                   ON CONFLICT(place_id_a, place_id_b, relation_type) DO UPDATE SET review_status='merged', audit_json=excluded.audit_json""",
                (source_id, target_id, dumps([reason or "user_merge"]), dumps(audit)),
            )
            conn.execute("INSERT INTO reviews (place_id, decision, reason) VALUES (?, 'merge', ?)", (target_id, f"merged {place_code(source_id)} into {place_code(target_id)}"))
            from .ingest import Ingestor

            Ingestor.refresh_counters(conn, target_id)
        return self.get_place(target_id) or {}

    def unmerge(self, source_id: int) -> dict[str, Any]:
        with self.ctx.db.transaction() as conn:
            rel = conn.execute(
                "SELECT * FROM place_relations WHERE place_id_a=? AND relation_type='duplicate_of' AND review_status='merged'", (source_id,)
            ).fetchone()
            if not rel:
                raise KeyError("no merge record")
            audit = loads(rel["audit_json"], {})
            target_id = rel["place_id_b"]
            for pid in audit.get("provider_ids", []):
                conn.execute("UPDATE provider_ids SET place_id=? WHERE provider=? AND external_id=?", (source_id, pid["provider"], pid["external_id"]))
            for sid in audit.get("copied_sources", []):
                conn.execute("DELETE FROM place_sources WHERE place_id=? AND source_id=? AND NOT EXISTS (SELECT 1 FROM place_sources WHERE place_id=? AND source_id=? AND created_at < ?)",
                             (target_id, sid, target_id, sid, audit.get("merged_at", "")))
            for iid in audit.get("copied_images", []):
                conn.execute("DELETE FROM place_images WHERE place_id=? AND image_id=? AND created_at >= ?", (target_id, iid, audit.get("merged_at", "")))
            conn.execute("UPDATE places SET aliases_json=?, updated_at=? WHERE id=?", (dumps(audit.get("target_aliases_before", [])), now_iso(), target_id))
            conn.execute("UPDATE places SET merged_into_place_id=NULL, updated_at=? WHERE id=?", (now_iso(), source_id))
            conn.execute("UPDATE place_relations SET review_status='undone' WHERE id=?", (rel["id"],))
            conn.execute("INSERT INTO reviews (place_id, decision, reason) VALUES (?, 'unmerge', ?)", (source_id, f"unmerged from {place_code(target_id)}"))
            from .ingest import Ingestor

            Ingestor.refresh_counters(conn, target_id)
            Ingestor.refresh_counters(conn, source_id)
        return self.get_place(source_id) or {}

    def set_relation_status(self, relation_id: int, status: str) -> dict[str, Any] | None:
        if status not in ("confirmed", "rejected", "pending"):
            raise ValueError("invalid status")
        with self.ctx.db.transaction() as conn:
            conn.execute("UPDATE place_relations SET review_status=? WHERE id=?", (status, relation_id))
            row = conn.execute("SELECT * FROM place_relations WHERE id=?", (relation_id,)).fetchone()
        return row_to_dict(row)

    # --------------------------------------------------------------- summary
    def summary(self) -> dict[str, Any]:
        conn = self.ctx.db.conn()
        base = "FROM places WHERE merged_into_place_id IS NULL AND discovery_status!='seed'"
        out: dict[str, Any] = {
            "total": conn.execute(f"SELECT COUNT(*) {base}").fetchone()[0],
            "seeds": conn.execute("SELECT COUNT(*) FROM places WHERE merged_into_place_id IS NULL AND discovery_status='seed'").fetchone()[0],
            "with_coords": conn.execute(f"SELECT COUNT(*) {base} AND latitude IS NOT NULL").fetchone()[0],
            "with_images": conn.execute(f"SELECT COUNT(*) {base} AND image_count>0").fetchone()[0],
            "with_local_images": conn.execute(f"SELECT COUNT(*) {base} AND local_image_count>0").fetchone()[0],
            "needs_geo": conn.execute(f"SELECT COUNT(*) {base} AND needs_geographic_verification=1").fetchone()[0],
            "pending_duplicates": conn.execute("SELECT COUNT(*) FROM place_relations WHERE review_status='pending'").fetchone()[0],
            "by_interest": {r[0]: r[1] for r in conn.execute(f"SELECT interest_status, COUNT(*) {base} GROUP BY interest_status")},
            "by_region": {r[0] or "未知": r[1] for r in conn.execute(f"SELECT county, COUNT(*) {base} GROUP BY county")},
            "by_category": {r[0]: r[1] for r in conn.execute(f"SELECT category, COUNT(*) {base} GROUP BY category ORDER BY 2 DESC")},
            "images_total": conn.execute("SELECT COUNT(*) FROM images").fetchone()[0],
            "images_local": conn.execute("SELECT COUNT(*) FROM images WHERE local_path IS NOT NULL").fetchone()[0],
        }
        return out


_COMMONS_THUMB_RE = re.compile(r"^(https://upload\.wikimedia\.org/wikipedia/commons/thumb/.+/)(\d+)px-([^/?]+)(\?.*)?$")


def commons_thumb(url: str | None, width: int) -> str | None:
    """Rewrite a Commons thumbnail URL to a smaller width (same file, server-side resize)."""
    if not url:
        return None
    match = _COMMONS_THUMB_RE.match(url)
    if not match:
        return url
    return f"{match.group(1)}{width}px-{match.group(3)}"


def _image_badge(d: dict[str, Any]) -> str:
    """Human-readable verification badge for the card."""
    if not d.get("image_count"):
        return "无图"
    if d.get("any_image_verified"):
        return "图片已人工核实"
    score = d.get("best_image_score") or 0
    if score >= 5:
        return "图片匹配较强（未核实）"
    if score >= 2.5:
        return "图片匹配一般（未核实）"
    return "图片匹配弱（未核实）"
