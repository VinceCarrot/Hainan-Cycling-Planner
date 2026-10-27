"""Candidate ingestion: provider results -> deduplicated place records with provenance.

Dedup is conservative: provider IDs are strong evidence; name + proximity merges only
within 100 m (or same county when coordinates are missing on one side and names are
identical); 100-500 m with category agreement creates a *pending* duplicate relation
instead of merging. Nothing is hard-deleted.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ..geo import haversine_km, in_bbox
from ..normalize import core_name, normalize_name, similarity
from ..regions import Region, region_from_text
from ..taxonomy import category_is_coastal, category_weight
from .common import dumps, loads, now_iso
from .context import AppContext

log = logging.getLogger(__name__)

COASTAL_NAME_HINTS = ("海", "湾", "滩", "港", "岛", "角", "礁", "洲", "灯塔", "渔", "盐")


@dataclass
class SourceSpec:
    url: str
    provider: str
    source_type: str  # map_feature | knowledge_base | encyclopedia | web_page | travelogue | image_page | user_note
    title: str | None = None
    publisher: str | None = None
    author: str | None = None
    published_at: str | None = None
    access_status: str = "fetched"
    terms_url: str | None = None
    license_notes: str | None = None
    excerpt: str | None = None
    relationship_type: str = "describes"
    confidence: float = 0.8


@dataclass
class Candidate:
    provider: str
    external_id: str
    name: str
    external_url: str | None = None
    name_en: str | None = None
    aliases: list[str] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    coordinate_precision: str = "exact"
    category: str = "unknown"
    subcategory: str | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    description_language: str | None = None
    discovery_reason: str = "OSM_feature"
    sources: list[SourceSpec] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    wikidata_id: str | None = None
    region_hint: str | None = None  # text that may contain a county name
    image_hints: dict[str, Any] = field(default_factory=dict)  # e.g. {"commons_file": ..., "commons_category": ...}
    needs_geographic_verification: bool = False
    confidence: float = 0.6


@dataclass
class IngestResult:
    place_id: int
    action: str  # created | updated | linked | merged
    duplicate_relation_created: bool = False


class Ingestor:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.bbox = ctx.config.bbox

    # ------------------------------------------------------------------ public
    def ingest(self, cand: Candidate) -> IngestResult:
        if cand.latitude is not None and not in_bbox(cand.latitude, cand.longitude, self.bbox):
            # Outside Hainan: keep coordinates out but still allow a lead without coordinates
            cand.latitude = None
            cand.longitude = None
            cand.needs_geographic_verification = True
        with self.ctx.db.transaction() as conn:
            result = self._ingest(conn, cand)
            self.refresh_counters(conn, result.place_id)
            return result

    # ----------------------------------------------------------------- private
    def _ingest(self, conn: sqlite3.Connection, cand: Candidate) -> IngestResult:
        existing = conn.execute(
            "SELECT place_id FROM provider_ids WHERE provider=? AND external_id=?",
            (cand.provider, cand.external_id),
        ).fetchone()
        if existing:
            place_id = self._resolve_merged(conn, existing["place_id"])
            self._update_place(conn, place_id, cand)
            self._touch_provider_id(conn, place_id, cand)
            self._attach_sources(conn, place_id, cand)
            return IngestResult(place_id, "updated")

        linked = self._find_cross_provider_link(conn, cand)
        if linked is not None:
            self._update_place(conn, linked, cand)
            self._touch_provider_id(conn, linked, cand)
            self._attach_sources(conn, linked, cand)
            return IngestResult(linked, "linked")

        match, relation_only = self._find_duplicate(conn, cand)
        if match is not None and not relation_only:
            self._update_place(conn, match, cand)
            self._touch_provider_id(conn, match, cand)
            self._attach_sources(conn, match, cand)
            return IngestResult(match, "merged")

        place_id = self._insert_place(conn, cand)
        self._touch_provider_id(conn, place_id, cand)
        self._attach_sources(conn, place_id, cand)
        dup = False
        if match is not None and relation_only:
            self._create_relation(conn, place_id, match, "duplicate_of", 0.6, ["name_similar", "within_500m", "category_agrees"])
            dup = True
        return IngestResult(place_id, "created", dup)

    @staticmethod
    def _resolve_merged(conn: sqlite3.Connection, place_id: int) -> int:
        seen = set()
        while True:
            row = conn.execute("SELECT merged_into_place_id FROM places WHERE id=?", (place_id,)).fetchone()
            if not row or row["merged_into_place_id"] is None or place_id in seen:
                return place_id
            seen.add(place_id)
            place_id = row["merged_into_place_id"]

    def _find_cross_provider_link(self, conn: sqlite3.Connection, cand: Candidate) -> int | None:
        if cand.wikidata_id:
            row = conn.execute(
                "SELECT place_id FROM provider_ids WHERE provider='wikidata' AND external_id=?", (cand.wikidata_id,)
            ).fetchone()
            if row:
                return self._resolve_merged(conn, row["place_id"])
        if cand.provider == "wikidata":
            row = conn.execute(
                "SELECT p.place_id FROM provider_ids p JOIN places pl ON pl.id=p.place_id "
                "WHERE p.provider='osm' AND json_extract(pl.feature_tags_json, '$.wikidata')=?",
                (cand.external_id,),
            ).fetchone()
            if row:
                return self._resolve_merged(conn, row["place_id"])
        return None

    def _find_duplicate(self, conn: sqlite3.Connection, cand: Candidate) -> tuple[int | None, bool]:
        """Return (place_id, relation_only). relation_only=True means 'create pending duplicate relation'."""
        names = {normalize_name(cand.name)} | {normalize_name(a) for a in cand.aliases}
        names.discard("")
        if not names:
            return None, False
        cores = {core_name(n) for n in names if len(core_name(n)) >= 2}
        placeholders = ",".join("?" for _ in names)
        rows = conn.execute(
            f"SELECT id, canonical_name, normalized_name, aliases_json, latitude, longitude, category, county "
            f"FROM places WHERE merged_into_place_id IS NULL AND normalized_name IN ({placeholders})",
            tuple(names),
        ).fetchall()
        if cores:
            # core-name matches (e.g. 东坡书院 vs 儋州东坡书院景区) found by LIKE on a bounded set
            for core in cores:
                rows += conn.execute(
                    "SELECT id, canonical_name, normalized_name, aliases_json, latitude, longitude, category, county "
                    "FROM places WHERE merged_into_place_id IS NULL AND normalized_name LIKE ? LIMIT 50",
                    (f"%{core}%",),
                ).fetchall()
        best: tuple[int | None, bool, float] = (None, False, 0.0)
        seen: set[int] = set()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            row_names = {row["normalized_name"]} | {normalize_name(a) for a in loads(row["aliases_json"], [])}
            name_score = max((similarity(a, b) for a in names for b in row_names), default=0.0)
            exact = bool(names & row_names)
            core_match = bool(cores & {core_name(n) for n in row_names})
            if not exact and not core_match and name_score < 92:
                continue
            if cand.latitude is not None and row["latitude"] is not None:
                dist_km = haversine_km(cand.latitude, cand.longitude, row["latitude"], row["longitude"])
                if dist_km <= 0.1 and (exact or name_score >= 92 or core_match):
                    return row["id"], False
                if dist_km <= 0.5 and (exact or core_match) and _category_compatible(cand.category, row["category"]):
                    if best[0] is None:
                        best = (row["id"], True, name_score)
                continue
            # one side has no coordinates: merge only on exact name and same county (or unknown county)
            cand_region = region_from_text(cand.region_hint or "")
            same_county = cand_region is None or row["county"] is None or row["county"] == cand_region.name
            if exact and same_county and _is_settlement_free(cand.category, row["category"]):
                return row["id"], False
            if (exact or core_match) and same_county and best[0] is None:
                best = (row["id"], True, name_score)
        return best[0], best[1]

    def _insert_place(self, conn: sqlite3.Connection, cand: Candidate) -> int:
        region, method = self._region_for(cand)
        is_coastal = category_is_coastal(cand.category) or any(h in cand.name for h in COASTAL_NAME_HINTS)
        discovery_status = "seed" if cand.category in ("settlement", "village", "other", "unknown") and not cand.description else "candidate"
        aliases = [a for a in dict.fromkeys(cand.aliases) if a and a != cand.name]
        tags = dict(cand.tags)
        if cand.wikidata_id:
            tags.setdefault("wikidata", cand.wikidata_id)
        cur = conn.execute(
            """INSERT INTO places (canonical_name, normalized_name, name_en, aliases_json, city, county, latitude, longitude,
                   coordinate_source, coordinate_precision, category, subcategory, feature_tags_json, description,
                   description_language, discovery_status, needs_geographic_verification, confidence_score, discovery_reason,
                   is_coastal, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cand.name,
                normalize_name(cand.name),
                cand.name_en,
                dumps(aliases),
                region.name if region else None,
                region.name if region else None,
                cand.latitude,
                cand.longitude,
                cand.provider if cand.latitude is not None else None,
                (cand.coordinate_precision if cand.latitude is not None else None),
                cand.category,
                cand.subcategory,
                dumps(tags),
                cand.description,
                cand.description_language,
                discovery_status,
                1 if (cand.needs_geographic_verification or cand.latitude is None) else 0,
                cand.confidence,
                cand.discovery_reason,
                1 if is_coastal else 0,
                now_iso(),
                now_iso(),
            ),
        )
        place_id = int(cur.lastrowid)
        if method == "nearest_centroid":
            conn.execute("UPDATE places SET town=COALESCE(town, '') WHERE id=?", (place_id,))
        return place_id

    def _update_place(self, conn: sqlite3.Connection, place_id: int, cand: Candidate) -> None:
        row = conn.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone()
        if not row:
            return
        updates: dict[str, Any] = {}
        aliases = loads(row["aliases_json"], [])
        for alias in [cand.name, cand.name_en, *cand.aliases]:
            if alias and alias != row["canonical_name"] and alias not in aliases:
                aliases.append(alias)
        if aliases != loads(row["aliases_json"], []):
            updates["aliases_json"] = dumps(aliases)
        if not row["name_en"] and cand.name_en:
            updates["name_en"] = cand.name_en
        if row["latitude"] is None and cand.latitude is not None:
            updates.update(latitude=cand.latitude, longitude=cand.longitude, coordinate_source=cand.provider,
                           coordinate_precision=cand.coordinate_precision, needs_geographic_verification=0)
            region, _ = self._region_for(cand)
            if region and not row["county"]:
                updates.update(county=region.name, city=region.name)
        elif cand.latitude is not None and row["coordinate_precision"] in ("approximate", "centroid", None) and cand.coordinate_precision == "exact":
            updates.update(latitude=cand.latitude, longitude=cand.longitude, coordinate_source=cand.provider, coordinate_precision="exact")
        if (row["category"] in ("unknown", "other", "attraction", "settlement", "village")) and cand.category not in ("unknown", "other"):
            if not (row["category"] == "village" and cand.category == "settlement"):
                updates["category"] = cand.category
        if not row["description"] and cand.description:
            updates.update(description=cand.description, description_language=cand.description_language)
        tags = loads(row["feature_tags_json"], {})
        merged_tags = {**cand.tags, **tags}  # existing tags win
        if cand.wikidata_id:
            merged_tags.setdefault("wikidata", cand.wikidata_id)
        if merged_tags != tags:
            updates["feature_tags_json"] = dumps(merged_tags)
        if row["discovery_status"] == "seed" and (cand.description or cand.category not in ("settlement", "village", "other", "unknown")):
            updates["discovery_status"] = "candidate"
        if cand.confidence > (row["confidence_score"] or 0):
            updates["confidence_score"] = cand.confidence
        if not row["county"] and cand.region_hint:
            region = region_from_text(cand.region_hint)
            if region:
                updates.update(county=region.name, city=region.name)
        if updates:
            updates["updated_at"] = now_iso()
            sets = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE places SET {sets} WHERE id=?", (*updates.values(), place_id))

    def _touch_provider_id(self, conn: sqlite3.Connection, place_id: int, cand: Candidate) -> None:
        conn.execute(
            """INSERT INTO provider_ids (place_id, provider, external_id, external_url, raw_json, fetched_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(provider, external_id) DO UPDATE SET external_url=excluded.external_url,
                   raw_json=excluded.raw_json, fetched_at=excluded.fetched_at""",
            (place_id, cand.provider, cand.external_id, cand.external_url, dumps(cand.raw) if cand.raw else None, now_iso()),
        )

    def _attach_sources(self, conn: sqlite3.Connection, place_id: int, cand: Candidate) -> None:
        for spec in cand.sources:
            source_id = upsert_source(conn, spec)
            conn.execute(
                """INSERT INTO place_sources (place_id, source_id, relationship_type, evidence_excerpt, confidence_score)
                   VALUES (?,?,?,?,?) ON CONFLICT(place_id, source_id) DO UPDATE SET
                   evidence_excerpt=COALESCE(excluded.evidence_excerpt, place_sources.evidence_excerpt),
                   confidence_score=MAX(place_sources.confidence_score, excluded.confidence_score)""",
                (place_id, source_id, spec.relationship_type, spec.excerpt, spec.confidence),
            )

    @staticmethod
    def _create_relation(conn: sqlite3.Connection, a: int, b: int, relation_type: str, confidence: float, reasons: list[str]) -> None:
        conn.execute(
            """INSERT INTO place_relations (place_id_a, place_id_b, relation_type, confidence_score, reasons_json)
               VALUES (?,?,?,?,?) ON CONFLICT(place_id_a, place_id_b, relation_type) DO NOTHING""",
            (a, b, relation_type, confidence, dumps(reasons)),
        )

    def _region_for(self, cand: Candidate) -> tuple[Region | None, str]:
        region, method = self.ctx.regions.assign(cand.latitude, cand.longitude)
        if region is None:
            hinted = region_from_text(cand.region_hint or "") or region_from_text(cand.name)
            if hinted:
                return hinted, "hint"
        return region, method

    # ------------------------------------------------------------- maintenance
    @staticmethod
    def refresh_counters(conn: sqlite3.Connection, place_id: int) -> None:
        conn.execute(
            """UPDATE places SET
                 source_count=(SELECT COUNT(*) FROM place_sources WHERE place_id=?),
                 image_count=(SELECT COUNT(*) FROM place_images pi WHERE pi.place_id=? AND pi.association_status!='rejected'),
                 local_image_count=(SELECT COUNT(*) FROM place_images pi JOIN images i ON i.id=pi.image_id
                                    WHERE pi.place_id=? AND pi.association_status!='rejected' AND i.local_path IS NOT NULL)
               WHERE id=?""",
            (place_id, place_id, place_id, place_id),
        )
        row = conn.execute("SELECT * FROM places WHERE id=?", (place_id,)).fetchone()
        if row:
            novelty, score = compute_scores(row)
            conn.execute("UPDATE places SET novelty_score=?, discovery_score=? WHERE id=?", (novelty, score, place_id))


def upsert_source(conn: sqlite3.Connection, spec: SourceSpec) -> int:
    row = conn.execute("SELECT id FROM sources WHERE url=?", (spec.url,)).fetchone()
    if row:
        conn.execute(
            """UPDATE sources SET title=COALESCE(?, title), publisher=COALESCE(?, publisher), author=COALESCE(?, author),
               published_at=COALESCE(?, published_at), access_status=?, terms_url=COALESCE(?, terms_url),
               license_notes=COALESCE(?, license_notes), excerpt=COALESCE(?, excerpt), last_checked_at=? WHERE id=?""",
            (spec.title, spec.publisher, spec.author, spec.published_at, spec.access_status, spec.terms_url,
             spec.license_notes, spec.excerpt, now_iso(), row["id"]),
        )
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO sources (provider, source_type, url, canonical_url, title, publisher, author, published_at,
               retrieved_at, access_status, terms_url, license_notes, excerpt, last_checked_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (spec.provider, spec.source_type, spec.url, spec.url, spec.title, spec.publisher, spec.author, spec.published_at,
         now_iso(), spec.access_status, spec.terms_url, spec.license_notes, spec.excerpt, now_iso()),
    )
    return int(cur.lastrowid)


def _category_compatible(a: str, b: str) -> bool:
    if a == b or "unknown" in (a, b) or "attraction" in (a, b):
        return True
    groups = [
        {"beach", "bay", "coast", "cape", "reef", "cliff"},
        {"village", "fishing_village", "historic_village", "settlement"},
        {"historic", "temple", "fort", "archaeological", "memorial", "architecture", "old_town"},
        {"peak", "mountain", "viewpoint", "forest", "nature_reserve"},
        {"lake", "reservoir", "river", "waterfall"},
        {"park", "garden", "theme_park"},
    ]
    return any(a in g and b in g for g in groups)


def _is_settlement_free(a: str, b: str) -> bool:
    """Villages share names across Hainan; never merge two bare settlements on name alone."""
    settlements = {"village", "settlement"}
    return not (a in settlements and b in settlements)


def compute_scores(row: sqlite3.Row | dict[str, Any]) -> tuple[float, float]:
    """Return (novelty_score 0..1, discovery_score). Transparent, not popularity-driven."""
    tags = loads(row["feature_tags_json"], {})
    novelty = 1.0
    if tags.get("has_wikipedia_zh"):
        novelty -= 0.35
    if tags.get("has_wikipedia_en"):
        novelty -= 0.15
    if tags.get("tourism") == "attraction" or tags.get("legacy_catalog"):
        novelty -= 0.1
    if (row["source_count"] or 0) >= 6:
        novelty -= 0.1
    novelty = max(0.1, round(novelty, 3))

    weight = category_weight(row["category"])
    evidence = min(1.0, 0.25 * (row["source_count"] or 0))
    coords = 0.3 if row["latitude"] is not None else 0.0
    imagery = 0.2 if (row["image_count"] or 0) > 0 else 0.0
    route = 0.0
    dist = row["route_distance_km"]
    if dist is not None:
        if dist <= 3:
            route = 0.6
        elif dist <= 10:
            route = 0.4
        elif dist <= 25:
            route = 0.2
    coastal = 0.2 if row["is_coastal"] else 0.0
    score = weight * (0.6 + 0.6 * novelty) + evidence + coords + imagery + route + coastal
    return novelty, round(score, 3)
