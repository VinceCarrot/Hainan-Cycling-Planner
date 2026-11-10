"""Discovery, research and image pipelines wired as job handlers.

Every handler is idempotent: providers upsert through the Ingestor / ImageService, so
re-running a job never duplicates records (it only refreshes them).
"""
from __future__ import annotations

import logging
from typing import Any

from .discovery.commons import CommonsClient, fetch_image_candidates
from .discovery.nominatim import NominatimClient
from .discovery.osm import discover_osm_category, nearby_features, search_osm_by_name
from .discovery.wikidata import WikidataClient, binding_to_candidate, discover_wikidata
from .discovery.wikipedia import search_wikipedia_for_name, sweep_geosearch
from .geo import grid_points, haversine_km, in_bbox
from .http import HostCooldownError, ProviderDisabledError
from .normalize import contains_name, name_variants, normalize_name, similarity
from .regions import REGION_BY_KEY, region_from_text
from .services.common import dumps, loads, now_iso
from .services.context import AppContext
from .services.corridor import CorridorService
from .services.coverage import CoverageService
from .services.images import ImageCandidate, ImageService
from .services.ingest import Candidate, Ingestor, SourceSpec, upsert_source
from .services.jobs import JobRun, JobService
from .services.places import PlaceService
from .taxonomy import OSM_DISCOVERY_QUERIES, category_from_text

log = logging.getLogger(__name__)

NON_PHOTO_MARKERS = ("map", "地图", "flag", "logo", "locator", "diagram", "seal", "coat of arms", "emblem", "chart", "plan", "scheme", ".svg")


# ----------------------------------------------------------------------------- helpers
WIKIMEDIA_HOSTS = ("commons.wikimedia.org", "www.wikidata.org", "zh.wikipedia.org", "en.wikipedia.org")


def wait_for_wikimedia(run: JobRun) -> None:
    """If any Wikimedia API host is cooling down after 503/429, pause the job (cancellable) until it ends."""
    import time as _time

    while True:
        remaining = max(run.ctx.http.cooldown_remaining(h) for h in WIKIMEDIA_HOSTS)
        if remaining <= 0:
            return
        run.progress(stage=f"waiting for Wikimedia ({int(remaining)}s cooldown)")
        step = min(30.0, remaining)
        _time.sleep(step)
        run.check_cancelled()

def _ingest_many(ctx: AppContext, cands: list[Candidate], run: JobRun | None = None, label: str = "") -> dict[str, int]:
    ingestor = Ingestor(ctx)
    stats = {"created": 0, "updated": 0, "linked": 0, "merged": 0, "duplicate_relations": 0}
    for idx, cand in enumerate(cands):
        res = ingestor.ingest(cand)
        stats[res.action] = stats.get(res.action, 0) + 1
        if res.duplicate_relation_created:
            stats["duplicate_relations"] += 1
        if run and idx % 50 == 0:
            run.check_cancelled()
            run.progress(stage=f"ingest {label}", done=idx + 1, total=len(cands), **stats)
    return stats


def _place_names(place: dict[str, Any]) -> list[str]:
    return name_variants(place["canonical_name"], place.get("aliases") or [])


def score_image_for_place(place: dict[str, Any], img: ImageCandidate, *, linked: bool = False, from_category: bool = False) -> tuple[float, list[str]]:
    """Transparent image/place match score with reasons."""
    score = 0.0
    reasons: list[str] = []
    names = _place_names(place)
    title = img.title or ""
    desc = img.description or ""
    cats = " ".join(img.categories)
    if any(contains_name(title, n) for n in names if len(normalize_name(n)) >= 2):
        score += 3
        reasons.append("name_in_title")
    if any(contains_name(desc, n) for n in names if len(normalize_name(n)) >= 2):
        score += 2
        reasons.append("name_in_description")
    if any(contains_name(cats, n) for n in names if len(normalize_name(n)) >= 2):
        score += 2.5
        reasons.append("name_in_commons_category")
    if place.get("name_en") and (place["name_en"].lower() in title.lower() or place["name_en"].lower() in desc.lower() or place["name_en"].lower() in cats.lower()):
        if "name_in_title" not in reasons:
            score += 2.5
            reasons.append("english_name_match")
    if img.latitude is not None and place.get("latitude") is not None:
        d_km = haversine_km(place["latitude"], place["longitude"], img.latitude, img.longitude)
        if d_km <= 0.15:
            score += 3
            reasons.append("geotag_within_150m")
        elif d_km <= 0.4:
            score += 2
            reasons.append("geotag_within_400m")
        elif d_km <= 1.0:
            score += 1
            reasons.append("geotag_within_1km")
        elif d_km > 2.5:
            score -= 1
            reasons.append("geotag_far")
    if linked:
        score += 4
        reasons.append("linked_from_wikidata_or_wikipedia")
    if from_category:
        score += 3
        reasons.append("member_of_linked_commons_category")
    blob = (title + " " + desc).lower()
    if any(m in blob for m in NON_PHOTO_MARKERS) or (img.mime_type and img.mime_type == "image/svg+xml"):
        score -= 3
        reasons.append("looks_like_map_or_graphic")
    if img.width and img.width < 400:
        score -= 1
        reasons.append("low_resolution")
    county = place.get("county")
    if county and (county[:2] in title or county[:2] in desc or county[:2] in cats):
        score += 0.5
        reasons.append("county_mentioned")
    return round(score, 2), reasons


# ---------------------------------------------------------------------- discovery jobs
def job_build_regions(run: JobRun) -> dict[str, Any]:
    from .regions import fetch_region_boundaries

    count = fetch_region_boundaries(run.ctx)
    run.log(f"cached {count} county boundary polygons")
    return {"regions": count}


def job_discover_osm(run: JobRun) -> dict[str, Any]:
    ctx = run.ctx
    if not ctx.regions.has_polygons:
        from .regions import fetch_region_boundaries

        try:
            run.log(f"region polygons missing; fetched {fetch_region_boundaries(ctx)} from Overpass")
        except Exception as exc:
            run.log(f"could not fetch region polygons ({exc}); falling back to nearest centroid", level="warning")
    groups = run.payload.get("groups") or list(OSM_DISCOVERY_QUERIES.keys())
    region_key = run.payload.get("region")
    bbox = ctx.config.bbox
    if region_key and region_key in REGION_BY_KEY:
        r = REGION_BY_KEY[region_key]
        bbox = (r.lat - 0.45, r.lon - 0.45, r.lat + 0.45, r.lon + 0.45)
    coverage = CoverageService(ctx)
    totals: dict[str, int] = {}
    for gi, group in enumerate(groups):
        run.check_cancelled()
        run.progress(stage=f"overpass {group}", group_index=gi + 1, groups=len(groups))
        run_id = coverage.start_run("osm", f"overpass:{group}", region_key, group, run.job_id, {"bbox": bbox})
        try:
            cands = discover_osm_category(ctx, group, bbox)
            run.log(f"Overpass {group}: {len(cands)} named features")
            stats = _ingest_many(ctx, cands, run, group)
            coverage.finish_run(run_id, "succeeded", len(cands), stats.get("created", 0))
            for k, v in stats.items():
                totals[k] = totals.get(k, 0) + v
        except Exception as exc:
            coverage.finish_run(run_id, "failed", error=str(exc)[:500])
            run.log(f"Overpass {group} failed: {exc}", level="error")
    CorridorService(ctx).recompute_distances()
    return {"groups": groups, **totals}


def job_discover_wikidata(run: JobRun) -> dict[str, Any]:
    ctx = run.ctx
    coverage = CoverageService(ctx)
    run_id = coverage.start_run("wikidata", "sparql:bbox", None, "all", run.job_id)
    try:
        cands = discover_wikidata(ctx, on_page=lambda off, n: run.progress(stage="sparql", offset=off, page_rows=n))
        run.log(f"Wikidata: {len(cands)} entities with coordinates in bbox")
        stats = _ingest_many(ctx, cands, run, "wikidata")
        coverage.finish_run(run_id, "succeeded", len(cands), stats.get("created", 0))
    except Exception as exc:
        coverage.finish_run(run_id, "failed", error=str(exc)[:500])
        raise
    CorridorService(ctx).recompute_distances()
    return {"entities": len(cands), **stats}


def job_discover_wikipedia(run: JobRun) -> dict[str, Any]:
    ctx = run.ctx
    lang = run.payload.get("lang", "zh")
    coverage = CoverageService(ctx)
    run_id = coverage.start_run(f"wikipedia_{lang}", "geosearch:grid", None, "all", run.job_id)
    try:
        cands = sweep_geosearch(ctx, lang, on_cell=lambda i, n, found: run.progress(stage=f"geosearch {lang}", cell=i + 1, cells=n, pages=found))
        run.log(f"Wikipedia {lang}: {len(cands)} geotagged articles")
        stats = _ingest_many(ctx, cands, run, f"wikipedia_{lang}")
        coverage.finish_run(run_id, "succeeded", len(cands), stats.get("created", 0))
    except Exception as exc:
        coverage.finish_run(run_id, "failed", error=str(exc)[:500])
        raise
    CorridorService(ctx).recompute_distances()
    return {"articles": len(cands), **stats}


def job_build_corridor(run: JobRun) -> dict[str, Any]:
    result = CorridorService(run.ctx).build_default_from_osm()
    run.log(f"corridor built with {result['points']} points; missing stops: {result.get('missing_stops')}")
    return result


def job_nearby_expansion(run: JobRun) -> dict[str, Any]:
    ctx = run.ctx
    place = PlaceService(ctx).get_place(int(run.payload["place_id"]))
    if not place or place["latitude"] is None:
        return {"skipped": "no coordinates"}
    radius = int(run.payload.get("radius_m", 1500))
    cands = nearby_features(ctx, place["latitude"], place["longitude"], radius)
    stats = _ingest_many(ctx, cands, run, "nearby")
    with ctx.db.transaction() as conn:
        for cand in cands:
            row = conn.execute("SELECT place_id FROM provider_ids WHERE provider='osm' AND external_id=?", (cand.external_id,)).fetchone()
            if row and row["place_id"] != place["id"]:
                conn.execute(
                    "INSERT OR IGNORE INTO place_relations (place_id_a, place_id_b, relation_type, confidence_score, reasons_json, review_status) VALUES (?,?,'nearby_to',0.9,?,'confirmed')",
                    (row["place_id"], place["id"], dumps([f"within_{radius}m"])),
                )
    CorridorService(ctx).recompute_distances()
    return {"features": len(cands), **stats}


# ------------------------------------------------------------------------ image jobs
class ImagePipeline:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.images = ImageService(ctx)
        self.policy = ctx.config.license_policy
        try:
            self.commons: CommonsClient | None = CommonsClient(ctx)
        except ProviderDisabledError:
            self.commons = None

    def collect_for_place(self, place: dict[str, Any]) -> list[tuple[ImageCandidate, bool, bool]]:
        """Return [(candidate, linked, from_category)] from name search, linked files, category and geosearch."""
        if not self.commons:
            return []
        found: dict[str, tuple[ImageCandidate, bool, bool]] = {}
        tags = place.get("feature_tags") or {}
        linked_titles: list[str] = []
        hints = place.get("image_hints") or {}
        for key in ("commons_file",):
            if hints.get(key):
                linked_titles.append("File:" + str(hints[key]).replace("_", " ").removeprefix("File:"))
        if tags.get("commons_file"):
            linked_titles.append("File:" + str(tags["commons_file"]).replace("_", " ").removeprefix("File:"))
        if linked_titles:
            for cand in fetch_image_candidates(self.commons, titles=linked_titles):
                found[cand.external_id] = (cand, True, False)
        category = hints.get("commons_category") or tags.get("commons_category")
        if category:
            try:
                members = self.commons.category_members(category, limit=40)
                ids = [m["pageid"] for m in members]
                for cand in fetch_image_candidates(self.commons, pageids=ids):
                    if cand.external_id not in found:
                        found[cand.external_id] = (cand, False, True)
            except Exception as exc:
                log.warning("commons category %s failed: %s", category, exc)
        # name search (zh + en)
        queries: list[str] = []
        for n in _place_names(place)[:4]:
            if len(normalize_name(n)) >= 2:
                queries.append(n)
        if place.get("name_en"):
            queries.append(place["name_en"])
        seen_q = set()
        for q in queries[:5]:
            if q in seen_q:
                continue
            seen_q.add(q)
            try:
                hits = self.commons.search_files(f'"{q}" Hainan' if q.isascii() else q, limit=25)
                ids = [h["pageid"] for h in hits]
                for cand in fetch_image_candidates(self.commons, pageids=ids):
                    if cand.external_id not in found:
                        found[cand.external_id] = (cand, False, False)
            except Exception as exc:
                log.warning("commons search %s failed: %s", q, exc)
        if place.get("latitude") is not None:
            radius = int(self.ctx.config.provider("commons").options.get("geosearch_radius_m", 1500))
            try:
                hits = self.commons.geosearch(place["latitude"], place["longitude"], radius_m=radius, limit=60)
                ids = [h["pageid"] for h in hits]
                for cand in fetch_image_candidates(self.commons, pageids=ids):
                    if cand.external_id not in found:
                        found[cand.external_id] = (cand, False, False)
            except Exception as exc:
                log.warning("commons geosearch failed: %s", exc)
        return list(found.values())

    def process_place(self, place_id: int, download: bool = True) -> dict[str, Any]:
        place = PlaceService(self.ctx).get_place(place_id)
        if not place:
            return {"error": "place not found"}
        hints = {}
        pid_rows = self.ctx.db.conn().execute("SELECT raw_json FROM provider_ids WHERE place_id=? AND provider='wikidata'", (place_id,)).fetchall()
        for r in pid_rows:
            raw = loads(r["raw_json"], {})
            if raw.get("image"):
                hints["commons_file"] = raw["image"].rsplit("/", 1)[-1]
            if raw.get("commonsCat"):
                hints["commons_category"] = raw["commonsCat"]
        place["image_hints"] = hints
        collected = self.collect_for_place(place)
        kept = 0
        for cand, linked, from_cat in collected:
            score, reasons = score_image_for_place(place, cand, linked=linked, from_category=from_cat)
            if score < self.policy.min_match_score and not linked:
                continue
            image_id = self.images.upsert_image(cand)
            self.images.associate(place_id, image_id, score, reasons)
            kept += 1
        dl = self.images.download_for_place(place_id) if download and kept else {"downloaded": 0}
        return {"place_id": place_id, "candidates": len(collected), "associated": kept, **{k: v for k, v in dl.items() if k != "place_id"}}


def job_images_for_place(run: JobRun) -> dict[str, Any]:
    return ImagePipeline(run.ctx).process_place(int(run.payload["place_id"]), download=run.payload.get("download", True))


def job_images_batch(run: JobRun) -> dict[str, Any]:
    ctx = run.ctx
    pipeline = ImagePipeline(ctx)
    conn = ctx.db.conn()
    where = ["merged_into_place_id IS NULL", "discovery_status!='seed'"]
    params: list[Any] = []
    if run.payload.get("only_without_images", True):
        where.append("image_count=0")
    if run.payload.get("region"):
        reg = REGION_BY_KEY.get(run.payload["region"])
        if reg:
            where.append("county=?")
            params.append(reg.name)
    if run.payload.get("with_coords_only"):
        where.append("latitude IS NOT NULL")
    limit = int(run.payload.get("limit", 500))
    ids = [r[0] for r in conn.execute(f"SELECT id FROM places WHERE {' AND '.join(where)} ORDER BY discovery_score DESC LIMIT ?", (*params, limit)).fetchall()]
    totals = {"places": len(ids), "associated": 0, "downloaded": 0, "failed_places": 0}
    for i, pid in enumerate(ids):
        run.check_cancelled()
        wait_for_wikimedia(run)
        try:
            res = pipeline.process_place(pid, download=run.payload.get("download", True))
            totals["associated"] += res.get("associated", 0)
            totals["downloaded"] += res.get("downloaded", 0)
        except Exception as exc:
            totals["failed_places"] += 1
            run.log(f"images for place {pid} failed: {exc}", level="warning")
        run.progress(stage="images", done=i + 1, total=len(ids), **{k: v for k, v in totals.items() if k != "places"})
    return totals


def job_download_pending(run: JobRun) -> dict[str, Any]:
    """Download permitted images that are still pending or failed earlier (e.g. after a network outage)."""
    ctx = run.ctx
    images = ImageService(ctx)
    rows = ctx.db.conn().execute(
        """SELECT DISTINCT pi.place_id FROM place_images pi JOIN images i ON i.id=pi.image_id
           WHERE pi.association_status!='rejected' AND i.permission_status='local_copy_allowed' AND i.local_path IS NULL
             AND i.download_status IN ('not_downloaded','failed') AND pi.match_score >= ?""",
        (ctx.config.license_policy.min_match_score,),
    ).fetchall()
    totals = {"places": len(rows), "downloaded": 0, "failed": 0}
    for i, r in enumerate(rows):
        run.check_cancelled()
        res = images.download_for_place(r["place_id"])
        totals["downloaded"] += res["downloaded"]
        totals["failed"] += res["failed"]
        if i % 10 == 0:
            run.progress(stage="download pending", done=i + 1, total=len(rows), **{k: v for k, v in totals.items() if k != "places"})
    return totals


def job_commons_sweep(run: JobRun) -> dict[str, Any]:
    """Grid sweep of geotagged Commons files over the island; attach to nearby places or keep as image leads."""
    ctx = run.ctx
    pipeline = ImagePipeline(ctx)
    if not pipeline.commons:
        raise ProviderDisabledError("commons disabled")
    step_km = float(run.payload.get("step_km", 8.0))
    radius = int(run.payload.get("radius_m", 6000))
    cells = grid_points(ctx.config.bbox, step_km)
    coverage = CoverageService(ctx)
    run_id = coverage.start_run("commons", "geosearch:grid", None, "images", run.job_id, {"step_km": step_km, "radius_m": radius})
    seen: set[int] = set()
    attached = unassigned = 0
    conn = ctx.db.conn()
    places = [dict(r) for r in conn.execute("SELECT id, canonical_name, name_en, aliases_json, latitude, longitude, county, feature_tags_json FROM places WHERE latitude IS NOT NULL AND merged_into_place_id IS NULL").fetchall()]
    for p in places:
        p["aliases"] = loads(p.pop("aliases_json"), [])
        p["feature_tags"] = loads(p.pop("feature_tags_json"), {})
    try:
        for ci, (lat, lon) in enumerate(cells):
            run.check_cancelled()
            try:
                hits = pipeline.commons.geosearch(lat, lon, radius_m=radius, limit=500)
            except Exception as exc:
                run.log(f"commons geosearch cell {ci} failed: {exc}", level="warning")
                continue
            new_ids = [h["pageid"] for h in hits if h["pageid"] not in seen]
            seen.update(new_ids)
            for cand in fetch_image_candidates(pipeline.commons, pageids=new_ids):
                if cand.latitude is None:
                    continue
                best: tuple[float, dict[str, Any], list[str]] | None = None
                for p in places:
                    if abs(p["latitude"] - cand.latitude) > 0.01 or abs(p["longitude"] - cand.longitude) > 0.01:
                        continue
                    score, reasons = score_image_for_place(p, cand)
                    if score >= pipeline.policy.min_match_score and (best is None or score > best[0]):
                        best = (score, p, reasons)
                image_id = pipeline.images.upsert_image(cand)
                if best:
                    pipeline.images.associate(best[1]["id"], image_id, best[0], best[2])
                    attached += 1
                else:
                    unassigned += 1
            run.progress(stage="commons sweep", cell=ci + 1, cells=len(cells), files=len(seen), attached=attached, unassigned=unassigned)
        coverage.finish_run(run_id, "succeeded", len(seen), attached)
    except Exception as exc:
        coverage.finish_run(run_id, "failed", len(seen), attached, error=str(exc)[:500])
        raise
    if run.payload.get("download", True):
        for p in places:
            try:
                pipeline.images.download_for_place(p["id"])
            except Exception as exc:
                run.log(f"download for {p['id']} failed: {exc}", level="warning")
    return {"files": len(seen), "attached": attached, "unassigned": unassigned}


# ---------------------------------------------------------------------- research jobs
class ResearchPipeline:
    """Re-research one place: locate it (Wikidata / Nominatim / OSM), describe it (Wikipedia), picture it (Commons)."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.places = PlaceService(ctx)
        self.ingestor = Ingestor(ctx)
        self.images = ImagePipeline(ctx)
        self.corridor = CorridorService(ctx)
        self._wikidata = self._try(lambda: WikidataClient(ctx))
        self._nominatim = self._try(lambda: NominatimClient(ctx))

    @staticmethod
    def _try(factory):
        try:
            return factory()
        except ProviderDisabledError:
            return None

    def research(self, place_id: int, *, with_images: bool = True, log=None) -> dict[str, Any]:
        place = self.places.get_place(place_id)
        if not place:
            return {"error": "not found"}
        if place.get("merged_into_place_id"):
            return {"skipped": "merged"}
        report: dict[str, Any] = {"place_id": place_id, "name": place["canonical_name"], "steps": []}
        names = _place_names(place)
        county = place.get("county")
        region = region_from_text(county) if county else None

        # 1. Wikidata entity search (for places not yet linked to Wikidata)
        if self._wikidata and not any(p["provider"] == "wikidata" for p in place["provider_ids"]):
            try:
                qids: list[str] = []
                for q in names[:3]:
                    for hit in self._wikidata.search_entities(q, "zh", limit=6):
                        label = hit.get("label") or ""
                        if similarity(normalize_name(label), normalize_name(q)) >= 80 or any(similarity(normalize_name(a), normalize_name(q)) >= 90 for a in hit.get("aliases", [])):
                            qids.append(hit["id"])
                qids = list(dict.fromkeys(qids))[:8]
                linked_any = False
                if qids:
                    for b in self._wikidata.entity_bindings(qids):
                        cand = binding_to_candidate(b)
                        if not cand or cand.latitude is None or not in_bbox(cand.latitude, cand.longitude, self.ctx.config.bbox):
                            continue
                        cand.discovery_reason = "research_relink"
                        linked_any = self._attach_or_relate(place, cand, min_similarity=85) or linked_any
                report["steps"].append({"wikidata": {"queried": names[:3], "qids": qids, "linked": linked_any}})
            except Exception as exc:
                report["steps"].append({"wikidata_error": str(exc)[:200]})

        place = self.places.get_place(place_id) or place
        # 2. Geocode when coordinates are missing (Nominatim, 1 req/s), then Overpass name search as fallback
        if place.get("latitude") is None:
            located = False
            if self._nominatim:
                for q in names[:3]:
                    try:
                        hits = self._nominatim.search(q if region is None else f"{q} {region.name}", limit=5)
                    except Exception as exc:
                        report["steps"].append({"nominatim_error": str(exc)[:200]})
                        break
                    for h in hits:
                        hit_name = (h.get("namedetails") or {}).get("name") or h.get("name") or h.get("display_name", "").split(",")[0]
                        sim = max(similarity(normalize_name(hit_name), normalize_name(n)) for n in names)
                        if sim < 80 or h.get("osm_type") not in ("node", "way", "relation"):
                            continue
                        if not nominatim_hit_compatible(place.get("category"), h):
                            report["steps"].append({"geocode_skipped": f"{h.get('osm_type')}/{h.get('osm_id')} is {h.get('category') or h.get('class')}={h.get('type')}, not a {place.get('category')}"})
                            continue
                        cand = _nominatim_to_candidate(h, hit_name)
                        if cand:
                            located = self._attach_or_relate(place, cand, min_similarity=80) or located
                    if located:
                        break
            if not located:
                for q in names[:2]:
                    if len(q) < 3:
                        continue
                    try:
                        cands = search_osm_by_name(self.ctx, q)
                    except Exception as exc:
                        report["steps"].append({"overpass_error": str(exc)[:200]})
                        break
                    for cand in cands[:10]:
                        if max(similarity(normalize_name(cand.name), normalize_name(n)) for n in names) >= 85:
                            cand.discovery_reason = "research_relink"
                            located = self._attach_or_relate(place, cand, min_similarity=85) or located
                    if located:
                        break
            report["steps"].append({"geocode": {"located": located}})

        place = self.places.get_place(place_id) or place
        # 3. Wikipedia description
        if not place.get("description") or place.get("description_language") not in ("zh", "en"):
            try:
                for q in names[:2]:
                    cands = search_wikipedia_for_name(self.ctx, q, "zh")
                    hit = False
                    for cand in cands:
                        sim = max(similarity(normalize_name(cand.name), normalize_name(n)) for n in names)
                        hainan_ok = (cand.latitude is not None and in_bbox(cand.latitude, cand.longitude, self.ctx.config.bbox)) or ("海南" in (cand.description or "")) or (county and county[:2] in (cand.description or ""))
                        if sim >= 85 and hainan_ok:
                            cand.discovery_reason = "research_relink"
                            if self._attach_or_relate(place, cand, min_similarity=85):
                                hit = True
                                break
                    if hit:
                        break
                report["steps"].append({"wikipedia": "searched"})
            except Exception as exc:
                report["steps"].append({"wikipedia_error": str(exc)[:200]})

        place = self.places.get_place(place_id) or place
        # 4. Images
        if with_images:
            try:
                img = self.images.process_place(place_id)
                report["steps"].append({"images": img})
            except Exception as exc:
                report["steps"].append({"images_error": str(exc)[:200]})

        place = self.places.get_place(place_id) or place
        errors = [s for s in report["steps"] if any(k.endswith("_error") for k in s)]
        successes = [s for s in report["steps"] if not any(k.endswith("_error") for k in s)]
        status = "failed" if errors and not successes else "done"
        if any("cooling down" in str(v) for s in errors for v in s.values()):
            status = "pending"  # interrupted by a Wikimedia cooldown: redo this place later
        report["research_status"] = status
        with self.ctx.db.transaction() as conn:
            confidence = min(1.0, 0.3 + 0.15 * min(4, place.get("source_count", 0)) + (0.2 if place.get("latitude") is not None else 0))
            conn.execute(
                "UPDATE places SET research_status=?, researched_at=?, confidence_score=MAX(confidence_score, ?), updated_at=? WHERE id=?",
                (status, now_iso(), confidence, now_iso(), place_id),
            )
            Ingestor.refresh_counters(conn, place_id)
        if place.get("latitude") is not None:
            from .services.routes import RouteService

            if RouteService(self.ctx).position_place(place_id) is None:
                d = self.corridor.distance_for(place["latitude"], place["longitude"])
                if d is not None:
                    with self.ctx.db.transaction() as conn:
                        conn.execute("UPDATE places SET route_distance_km=? WHERE id=?", (d, place_id))
        report["final"] = {"latitude": place.get("latitude"), "longitude": place.get("longitude"), "sources": place.get("source_count"), "images": place.get("image_count")}
        return report

    def _attach_or_relate(self, place: dict[str, Any], cand: Candidate, *, min_similarity: float) -> bool:
        """Ingest a research hit. If it resolves to another place, merge (strong) or relate (weak)."""
        res = self.ingestor.ingest(cand)
        if res.place_id == place["id"]:
            return True
        names = _place_names(place)
        sim = max(similarity(normalize_name(cand.name), normalize_name(n)) for n in names)
        other = self.places.get_place(res.place_id)
        if not other:
            return False
        if sim >= 92 and other.get("latitude") is not None:
            # Strong match: the legacy lead and the harvested entity are the same place -> reversible merge
            try:
                self.places.merge(place["id"], res.place_id, reason=f"research match ({sim:.0f}%) via {cand.provider}")
                return True
            except (ValueError, KeyError) as exc:
                log.warning("merge failed: %s", exc)
                return False
        with self.ctx.db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO place_relations (place_id_a, place_id_b, relation_type, confidence_score, reasons_json) VALUES (?,?,'duplicate_of',?,?)",
                (place["id"], res.place_id, round(sim / 100, 2), dumps([f"research_hit_via_{cand.provider}", f"name_similarity_{sim:.0f}"])),
            )
        return False


# Nominatim classes that describe infrastructure, not a destination. A hit of one of these classes may
# only locate a place whose own category is infrastructure-like; "棋子湾" the bay must not be pinned to
# "棋子湾" the railway station just because the names match.
_INFRASTRUCTURE_CLASSES = {"railway", "highway", "building", "aeroway", "public_transport", "office", "shop"}
_INFRASTRUCTURE_OK_CATEGORIES = {"transport", "bridge", "architecture", "attraction", "other", "unknown"}


def nominatim_hit_compatible(place_category: str | None, hit: dict[str, Any]) -> bool:
    """False when a Nominatim hit is infrastructure (station, road, building) and the place is not."""
    cls = (hit.get("category") or hit.get("class") or "").lower()
    if cls not in _INFRASTRUCTURE_CLASSES:
        return True
    return (place_category or "unknown") in _INFRASTRUCTURE_OK_CATEGORIES


def _nominatim_to_candidate(h: dict[str, Any], name: str) -> Candidate | None:
    osm_type, osm_id = h.get("osm_type"), h.get("osm_id")
    if not osm_type or not osm_id:
        return None
    ext_id = f"{osm_type}/{osm_id}"
    url = f"https://www.openstreetmap.org/{ext_id}"
    extratags = h.get("extratags") or {}
    tags = {k: v for k, v in extratags.items() if k in ("wikidata", "wikipedia", "website", "description")}
    tags[h.get("category", "class")] = h.get("type")
    addr = h.get("address") or {}
    region_hint = " ".join(str(v) for k, v in addr.items() if k in ("county", "city", "state_district", "town", "district"))
    return Candidate(
        provider="osm",
        external_id=ext_id,
        external_url=url,
        name=name,
        latitude=float(h["lat"]),
        longitude=float(h["lon"]),
        coordinate_precision="exact" if osm_type == "node" else "centroid",
        category=category_from_text(name + " " + str(h.get("type", ""))),
        tags=tags,
        discovery_reason="research_relink",
        sources=[SourceSpec(url=url, provider="osm", source_type="map_feature", title=f"OSM {ext_id}: {name}", publisher="OpenStreetMap",
                            terms_url="https://www.openstreetmap.org/copyright", license_notes="© OpenStreetMap contributors, ODbL 1.0 (via Nominatim)",
                            relationship_type="locates", confidence=0.7)],
        raw={"nominatim": {k: h.get(k) for k in ("display_name", "category", "type", "importance")}},
        wikidata_id=extratags.get("wikidata"),
        region_hint=region_hint,
        confidence=0.65,
    )


def job_research_place(run: JobRun) -> dict[str, Any]:
    return ResearchPipeline(run.ctx).research(int(run.payload["place_id"]), with_images=run.payload.get("with_images", True))


def job_research_batch(run: JobRun) -> dict[str, Any]:
    ctx = run.ctx
    conn = ctx.db.conn()
    where = ["merged_into_place_id IS NULL"]
    params: list[Any] = []
    if run.payload.get("provider"):
        where.append("EXISTS (SELECT 1 FROM provider_ids pi WHERE pi.place_id=places.id AND pi.provider=?)")
        params.append(run.payload["provider"])
    if run.payload.get("pending_only", True):
        where.append("research_status IN ('pending','failed')")
    if run.payload.get("region"):
        reg = REGION_BY_KEY.get(run.payload["region"])
        if reg:
            where.append("county=?")
            params.append(reg.name)
    if run.payload.get("place_ids"):
        ids = [int(x) for x in run.payload["place_ids"]]
        where.append("id IN (%s)" % ",".join("?" for _ in ids))
        params += ids
    limit = int(run.payload.get("limit", 1000))
    ids = [r[0] for r in conn.execute(f"SELECT id FROM places WHERE {' AND '.join(where)} ORDER BY id LIMIT ?", (*params, limit)).fetchall()]
    pipeline = ResearchPipeline(ctx)
    totals = {"places": len(ids), "located": 0, "images": 0, "failed": 0, "merged": 0}
    for i, pid in enumerate(ids):
        run.check_cancelled()
        wait_for_wikimedia(run)
        try:
            rep = pipeline.research(pid, with_images=run.payload.get("with_images", True))
            final = rep.get("final") or {}
            if final.get("latitude") is not None:
                totals["located"] += 1
            totals["images"] += final.get("images") or 0
            if rep.get("skipped") == "merged":
                totals["merged"] += 1
            run.log(f"researched {pid} {rep.get('name')}: coords={'yes' if final.get('latitude') is not None else 'no'} sources={final.get('sources')} images={final.get('images')}")
        except Exception as exc:
            totals["failed"] += 1
            run.log(f"research {pid} failed: {exc}", level="warning")
            with ctx.db.transaction() as wconn:
                wconn.execute("UPDATE places SET research_status='failed' WHERE id=?", (pid,))
        run.progress(stage="research", done=i + 1, total=len(ids), **{k: v for k, v in totals.items() if k != "places"})
    return totals


def job_fetch_url(run: JobRun) -> dict[str, Any]:
    """User-pasted URL -> permitted fetch -> mention extraction -> leads."""
    from .discovery.web_search import PageFetcher, extract_mentions, mention_candidate

    ctx = run.ctx
    url = run.payload["url"]
    fetcher = PageFetcher(ctx)
    text, status, info = fetcher.fetch_text(url)
    title = info if status == "fetched" else None
    with ctx.db.transaction() as conn:
        source_id = upsert_source(conn, SourceSpec(url=url, provider="user_url", source_type="web_page", title=title, access_status=status,
                                                   license_notes=None if status == "fetched" else info, excerpt=(text or "")[:300] or None, relationship_type="mentions"))
    if not text:
        run.log(f"page kept link-only: {info}")
        return {"url": url, "access_status": status, "reason": info, "source_id": source_id}
    conn = ctx.db.conn()
    known = {r["canonical_name"]: r["id"] for r in conn.execute("SELECT id, canonical_name FROM places WHERE merged_into_place_id IS NULL").fetchall()}
    matched, new_phrases = extract_mentions(text, known)
    with ctx.db.transaction() as wconn:
        for pid, evidence in matched.items():
            wconn.execute(
                "INSERT INTO place_sources (place_id, source_id, relationship_type, evidence_excerpt, confidence_score) VALUES (?,?,?,?,?) "
                "ON CONFLICT(place_id, source_id) DO UPDATE SET evidence_excerpt=excluded.evidence_excerpt",
                (pid, source_id, "mentions", evidence, 0.6),
            )
            Ingestor.refresh_counters(wconn, pid)
    created = 0
    ingestor = Ingestor(ctx)
    for phrase, evidence in new_phrases[: int(run.payload.get("max_new", 40))]:
        res = ingestor.ingest(mention_candidate(phrase, evidence, url, title))
        if res.action == "created":
            created += 1
    return {"url": url, "access_status": status, "matched_places": len(matched), "new_leads": created, "phrases": len(new_phrases)}


def job_web_search(run: JobRun) -> dict[str, Any]:
    """Regional query batch through the configured search API (disabled without a key)."""
    from .discovery.web_search import QUERY_TEMPLATES, PageFetcher, WebSearchAdapter, extract_mentions, mention_candidate

    ctx = run.ctx
    adapter = WebSearchAdapter(ctx)  # raises ProviderDisabledError when not configured
    fetcher = PageFetcher(ctx)
    region_key = run.payload.get("region")
    regions = [REGION_BY_KEY[region_key]] if region_key in REGION_BY_KEY else list(REGION_BY_KEY.values())
    coverage = CoverageService(ctx)
    totals = {"queries": 0, "results": 0, "fetched": 0, "link_only": 0, "new_leads": 0}
    conn = ctx.db.conn()
    known = {r["canonical_name"]: r["id"] for r in conn.execute("SELECT id, canonical_name FROM places WHERE merged_into_place_id IS NULL").fetchall()}
    ingestor = Ingestor(ctx)
    for region in regions:
        for template in QUERY_TEMPLATES:
            if "{place}" in template:
                continue
            query = template.format(region=region.name.replace("黎族自治县", "").replace("黎族苗族自治县", "").replace("市", "").replace("县", ""))
            run.check_cancelled()
            run_id = coverage.start_run(adapter.kind, query, region.key, "web", run.job_id)
            try:
                results = adapter.search(query)
                totals["queries"] += 1
                totals["results"] += len(results)
                for res in results:
                    with ctx.db.transaction() as wconn:
                        source_id = upsert_source(wconn, SourceSpec(url=res.url, provider=adapter.kind, source_type="web_page", title=res.title,
                                                                    access_status="link_only", excerpt=res.snippet, relationship_type="mentions", confidence=0.3))
                    text, status, info = fetcher.fetch_text(res.url)
                    with ctx.db.transaction() as wconn:
                        wconn.execute("UPDATE sources SET access_status=?, license_notes=COALESCE(?, license_notes) WHERE id=?", (status, None if status == "fetched" else info, source_id))
                    if not text:
                        totals["link_only"] += 1
                        continue
                    totals["fetched"] += 1
                    matched, new_phrases = extract_mentions(text, known)
                    with ctx.db.transaction() as wconn:
                        for pid, evidence in matched.items():
                            wconn.execute(
                                "INSERT INTO place_sources (place_id, source_id, relationship_type, evidence_excerpt, confidence_score) VALUES (?,?,?,?,?) "
                                "ON CONFLICT(place_id, source_id) DO NOTHING", (pid, source_id, "mentions", evidence, 0.5))
                    for phrase, evidence in new_phrases[:20]:
                        r = ingestor.ingest(mention_candidate(phrase, evidence, res.url, res.title, provider=adapter.kind))
                        if r.action == "created":
                            totals["new_leads"] += 1
                            known[phrase] = r.place_id
                coverage.finish_run(run_id, "succeeded", len(results))
            except Exception as exc:
                coverage.finish_run(run_id, "failed", error=str(exc)[:300])
                run.log(f"search '{query}' failed: {exc}", level="warning")
            run.progress(stage="web search", **totals)
    return totals


def register_handlers(jobs: JobService) -> None:
    jobs.register("discover_osm", job_discover_osm)
    jobs.register("build_regions", job_build_regions)
    jobs.register("discover_wikidata", job_discover_wikidata)
    jobs.register("discover_wikipedia", job_discover_wikipedia)
    jobs.register("build_corridor", job_build_corridor)
    jobs.register("nearby_expansion", job_nearby_expansion)
    jobs.register("images_for_place", job_images_for_place)
    jobs.register("images_batch", job_images_batch)
    jobs.register("commons_sweep", job_commons_sweep)
    jobs.register("download_pending", job_download_pending)
    jobs.register("research_place", job_research_place)
    jobs.register("research_batch", job_research_batch)
    jobs.register("fetch_url", job_fetch_url)
    jobs.register("web_search", job_web_search)
