"""Local HTTP API (FastAPI). Binds to 127.0.0.1 by default; no secrets are ever returned."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from ..regions import REGIONS
from ..services.context import AppContext
from ..services.corridor import CorridorService
from ..services.coverage import CoverageService
from ..services.export import BackupService, ExportService
from ..services.images import ImageService
from ..services.importer import import_corridor, import_csv
from ..services.jobs import JobService
from ..services.places import INTEREST_STATUSES, PlaceService
from ..taxonomy import CATEGORIES, CATEGORY_LABELS_ZH
from . import schemas

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def ctx_dep(request: Request) -> AppContext:
    return request.app.state.ctx


def jobs_dep(request: Request) -> JobService:
    return request.app.state.jobs


# ------------------------------------------------------------------------ meta
@router.get("/meta")
def meta(ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    cfg = ctx.config
    providers = []
    for name in ("overpass", "wikidata", "wikipedia", "commons", "nominatim", "web_search", "web_pages"):
        p = cfg.provider(name)
        providers.append({
            "name": name, "enabled": p.enabled, "endpoint": p.endpoint, "min_interval_seconds": p.min_interval_seconds,
            "configured": (
                cfg.contact_configured if name in ("wikidata", "wikipedia", "commons")
                else not (name == "web_search" and (not p.options.get("api_key") or str(p.options.get("api_key")).startswith("${")))
            ),
            "note": (None if name not in ("wikidata", "wikipedia", "commons") or cfg.contact_configured else "需要在 .env 设置 HAINAN_EXPLORER_CONTACT"),
        })
    return {
        "version": __import__("hainan_explorer").__version__,
        "regions": [{"key": r.key, "name": r.name, "name_en": r.name_en, "coastal": r.coastal, "route_order": r.route_order, "lat": r.lat, "lon": r.lon} for r in REGIONS],
        "categories": [{"key": k, "label": v["zh"], "coastal": v["coastal"]} for k, v in CATEGORIES.items()],
        "interest_statuses": list(INTEREST_STATUSES),
        "map_tiles": cfg.map_tiles or {"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "attribution": "&copy; OpenStreetMap contributors", "max_zoom": 19},
        "bbox": list(cfg.bbox),
        "providers": providers,
        "license_policy": {"local_copy_allowed": cfg.license_policy.local_copy_allowed, "blocked_markers": cfg.license_policy.blocked_markers, "min_match_score": cfg.license_policy.min_match_score},
        "http_stats": ctx.http.stats,
    }


@router.get("/summary")
def summary(ctx: AppContext = Depends(ctx_dep), jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    data = PlaceService(ctx).summary()
    data["jobs"] = jobs.counts()
    corridor = CorridorService(ctx).active()
    data["corridor"] = {k: v for k, v in corridor.items() if k != "geometry"} if corridor else None
    return data


# ---------------------------------------------------------------------- places
@router.get("/places")
def list_places(
    ctx: AppContext = Depends(ctx_dep),
    q: str | None = None,
    region: str | None = None,
    category: str | None = None,
    interest: str | None = None,
    discovery_status: str | None = None,
    image_state: str | None = Query(default=None, pattern="^(local|remote|none|any_image)$"),
    min_sources: int | None = Query(default=None, ge=0),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_route_km: float | None = Query(default=None, ge=0),
    coastal: bool | None = None,
    has_coords: bool | None = None,
    needs_geo: bool | None = None,
    duplicates_only: bool = False,
    undecided_only: bool = False,
    include_seeds: bool = False,
    sort: str = "region",
    limit: int = Query(default=60, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return PlaceService(ctx).list_places(
        q=q, region=region, category=category, interest=interest, discovery_status=discovery_status, image_state=image_state,
        min_sources=min_sources, min_confidence=min_confidence, max_route_km=max_route_km, coastal=coastal, has_coords=has_coords,
        needs_geo=needs_geo, duplicates_only=duplicates_only, undecided_only=undecided_only, include_seeds=include_seeds,
        sort=sort, limit=limit, offset=offset,
    )


@router.get("/places/{place_id}")
def get_place(place_id: int, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    place = PlaceService(ctx).get_place(place_id)
    if not place:
        raise HTTPException(404, "place not found")
    return place


@router.post("/places/{place_id}/decision")
def decide(place_id: int, body: schemas.DecisionRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    try:
        return PlaceService(ctx).decide(place_id, body.decision, body.score, body.reason)
    except KeyError:
        raise HTTPException(404, "place not found")


@router.post("/places/bulk-decision")
def bulk_decide(body: schemas.BulkDecisionRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    return {"updated": PlaceService(ctx).bulk_decide(body.place_ids, body.decision)}


@router.post("/places/undo")
def undo(place_id: int | None = None, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    result = PlaceService(ctx).undo_last_decision(place_id)
    if not result:
        raise HTTPException(404, "nothing to undo")
    return result


@router.patch("/places/{place_id}")
def update_place(place_id: int, body: schemas.PlaceUpdateRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    try:
        return PlaceService(ctx).update_notes(place_id, notes=body.personal_notes, verification_status=body.verification_status,
                                              canonical_name=body.canonical_name, category=body.category, latitude=body.latitude, longitude=body.longitude)
    except KeyError:
        raise HTTPException(404, "place not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/places/merge")
def merge(body: schemas.MergeRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    try:
        return PlaceService(ctx).merge(body.source_id, body.target_id, body.reason)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/places/{place_id}/unmerge")
def unmerge(place_id: int, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    try:
        return PlaceService(ctx).unmerge(place_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/relations")
def relations(status: str = "pending", limit: int = Query(default=100, ge=1, le=500), ctx: AppContext = Depends(ctx_dep)) -> list[dict[str, Any]]:
    conn = ctx.db.conn()
    rows = conn.execute(
        """SELECT r.*, pa.canonical_name AS name_a, pa.county AS county_a, pa.latitude AS lat_a, pa.longitude AS lon_a, pa.category AS category_a, pa.image_count AS images_a,
                  pb.canonical_name AS name_b, pb.county AS county_b, pb.latitude AS lat_b, pb.longitude AS lon_b, pb.category AS category_b, pb.image_count AS images_b
           FROM place_relations r JOIN places pa ON pa.id=r.place_id_a JOIN places pb ON pb.id=r.place_id_b
           WHERE r.review_status=? ORDER BY r.confidence_score DESC, r.id DESC LIMIT ?""",
        (status, limit),
    ).fetchall()
    from ..services.common import loads

    out = []
    for r in rows:
        d = dict(r)
        d["reasons"] = loads(d.pop("reasons_json"), [])
        d.pop("audit_json", None)
        out.append(d)
    return out


@router.post("/relations/{relation_id}/status")
def relation_status(relation_id: int, body: schemas.RelationStatusRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    result = PlaceService(ctx).set_relation_status(relation_id, body.status)
    if not result:
        raise HTTPException(404, "relation not found")
    return result


# ---------------------------------------------------------------------- images
@router.get("/images/{image_id}")
def get_image(image_id: int, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    img = ImageService(ctx).get_image(image_id)
    if not img:
        raise HTTPException(404, "image not found")
    return img


@router.post("/places/{place_id}/images/{image_id}/association")
def set_association(place_id: int, image_id: int, body: schemas.ImageAssociationRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    ImageService(ctx).set_association(place_id, image_id, body.status, body.notes, body.make_primary)
    return PlaceService(ctx).get_place(place_id) or {}


@router.post("/images/{image_id}/report")
def report_image(image_id: int, body: schemas.ImageReportRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    ImageService(ctx).report_issue(image_id, body.issue)
    return {"ok": True}


@router.delete("/images/{image_id}/local")
def remove_local(image_id: int, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    ImageService(ctx).remove_local_copy(image_id)
    return {"ok": True}


@router.post("/images/{image_id}/download")
def download_image(image_id: int, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    from ..services.images import DownloadNotAllowed

    try:
        return ImageService(ctx).download(image_id)
    except DownloadNotAllowed as exc:
        raise HTTPException(403, str(exc))
    except KeyError:
        raise HTTPException(404, "image not found")
    except Exception as exc:
        raise HTTPException(502, f"download failed: {exc}")


@router.get("/images/leads/unassigned")
def unassigned_images(limit: int = Query(default=200, ge=1, le=1000), ctx: AppContext = Depends(ctx_dep)) -> list[dict[str, Any]]:
    return ImageService(ctx).unassigned_geotagged(limit)


@router.get("/images/duplicates")
def duplicate_images(ctx: AppContext = Depends(ctx_dep)) -> list[dict[str, Any]]:
    return ImageService(ctx).find_duplicates()


# ------------------------------------------------------------------------ jobs
@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = Query(default=100, ge=1, le=500), jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    return {"counts": jobs.counts(), "items": jobs.list_jobs(status, limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.post("/jobs")
def create_job(body: schemas.JobRequest, jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    key = f"{body.job_type}:{sorted(body.payload.items())}" if body.payload else body.job_type
    job_id = jobs.enqueue(body.job_type, body.payload, priority=body.priority, dedupe_key=key)
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    if not jobs.cancel(job_id):
        raise HTTPException(404, "job not found")
    return {"ok": True}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    if not jobs.retry(job_id):
        raise HTTPException(400, "job is not retryable")
    return {"ok": True}


@router.post("/jobs/retry-failed")
def retry_failed(jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    return {"requeued": jobs.retry_failed()}


@router.post("/leads/url")
def add_url(body: schemas.UrlRequest, jobs: JobService = Depends(jobs_dep)) -> dict[str, Any]:
    return {"job_id": jobs.enqueue("fetch_url", {"url": body.url}, priority=3, dedupe_key=f"fetch_url:{body.url}")}


# --------------------------------------------------------------------- coverage
@router.get("/coverage")
def coverage(ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    return CoverageService(ctx).matrix()


@router.get("/corridor")
def corridor(ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    return CorridorService(ctx).active() or {}


@router.get("/map/places")
def map_places(
    ctx: AppContext = Depends(ctx_dep),
    interest: str | None = None,
    category: str | None = None,
    region: str | None = None,
    include_seeds: bool = False,
    limit: int = Query(default=5000, ge=1, le=20000),
) -> dict[str, Any]:
    conn = ctx.db.conn()
    where = ["merged_into_place_id IS NULL", "latitude IS NOT NULL"]
    params: list[Any] = []
    if not include_seeds:
        where.append("discovery_status!='seed'")
    if interest:
        vals = interest.split(",")
        where.append("interest_status IN (%s)" % ",".join("?" for _ in vals))
        params += vals
    if category:
        vals = category.split(",")
        where.append("category IN (%s)" % ",".join("?" for _ in vals))
        params += vals
    if region:
        from ..regions import REGION_BY_KEY

        reg = REGION_BY_KEY.get(region)
        if reg:
            where.append("county=?")
            params.append(reg.name)
    rows = conn.execute(
        f"SELECT id, canonical_name, category, county, latitude, longitude, interest_status, image_count, local_image_count, coordinate_precision, discovery_score, route_distance_km FROM places WHERE {' AND '.join(where)} LIMIT ?",
        (*params, limit),
    ).fetchall()
    features = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
         "properties": {k: r[k] for k in r.keys() if k not in ("latitude", "longitude")} | {"category_label": CATEGORY_LABELS_ZH.get(r["category"], r["category"])}}
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------- export
@router.post("/export")
def export(body: schemas.ExportRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    path = ExportService(ctx).write_export(body.format, body.interest, body.include_seeds)
    return {"path": str(path), "name": path.name, "download_url": f"/api/export/files/{path.name}"}


@router.get("/export/files")
def export_files(ctx: AppContext = Depends(ctx_dep)) -> list[dict[str, Any]]:
    out = []
    for p in sorted(ctx.config.exports_dir.glob("places-*"), reverse=True):
        out.append({"name": p.name, "bytes": p.stat().st_size, "download_url": f"/api/export/files/{p.name}"})
    return out


@router.get("/export/files/{name}")
def export_file(name: str, ctx: AppContext = Depends(ctx_dep)):
    path = (ctx.config.exports_dir / Path(name).name).resolve()
    if not str(path).startswith(str(ctx.config.exports_dir.resolve())) or not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=path.name)


@router.post("/import/csv")
def import_csv_endpoint(name: str, dry_run: bool = True, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    path = (ctx.config.imports_dir / Path(name).name).resolve()
    if not str(path).startswith(str(ctx.config.imports_dir.resolve())) or not path.is_file():
        raise HTTPException(404, f"put the file in {ctx.config.imports_dir} first")
    return import_csv(ctx, path, dry_run=dry_run)


@router.post("/import/corridor")
def import_corridor_endpoint(name: str, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    path = (ctx.config.imports_dir / Path(name).name).resolve()
    if not str(path).startswith(str(ctx.config.imports_dir.resolve())) or not path.is_file():
        raise HTTPException(404, f"put the file in {ctx.config.imports_dir} first")
    try:
        return import_corridor(ctx, path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/import/files")
def import_files(ctx: AppContext = Depends(ctx_dep)) -> list[str]:
    return sorted(p.name for p in ctx.config.imports_dir.iterdir() if p.is_file())


# ---------------------------------------------------------------------- backup
@router.post("/backup")
def backup(ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    path = BackupService(ctx).backup()
    return {"path": str(path), "name": path.name}


@router.get("/backups")
def backups(ctx: AppContext = Depends(ctx_dep)) -> list[dict[str, Any]]:
    return BackupService(ctx).list_backups()


@router.post("/restore")
def restore(body: schemas.RestoreRequest, ctx: AppContext = Depends(ctx_dep)) -> dict[str, Any]:
    try:
        safety = BackupService(ctx).restore(body.backup_name)
    except FileNotFoundError:
        raise HTTPException(404, "backup not found")
    return {"restored": body.backup_name, "pre_restore_backup": safety.name}


@router.get("/policy", response_class=PlainTextResponse)
def policy(ctx: AppContext = Depends(ctx_dep)) -> str:
    from ..config import PROJECT_ROOT

    path = PROJECT_ROOT / "docs" / "LEGAL_AND_SOURCE_POLICY.md"
    return path.read_text(encoding="utf-8") if path.is_file() else "policy document missing"
