"""OpenStreetMap discovery via the Overpass API (read-only; never the editing API).

Policy notes (checked 2026-10-27): overpass-api.de asks for a descriptive User-Agent,
one query at a time, and modest load. Data is ODbL — attribution is stored with every
candidate and shown in the UI.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from ..http import ProviderDisabledError
from ..services.context import AppContext
from ..services.ingest import Candidate, SourceSpec
from ..taxonomy import OSM_DISCOVERY_QUERIES, category_from_osm_tags

log = logging.getLogger(__name__)

OSM_ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0"
OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"


class OverpassClient:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("overpass")
        if not self.cfg.enabled:
            raise ProviderDisabledError("overpass disabled in config")
        self.endpoints = [self.cfg.endpoint or "https://overpass-api.de/api/interpreter"]
        self.endpoints += list(self.cfg.options.get("fallback_endpoints") or [])

    def query(self, overpass_ql: str, *, timeout: float | None = None, max_attempts: int | None = None) -> list[dict[str, Any]]:
        """Run a query, falling back through the configured mirrors. Small lookups pass short limits."""
        last_exc: Exception | None = None
        for endpoint in self.endpoints:
            try:
                resp = self.ctx.http.post(endpoint, data={"data": overpass_ql}, timeout=timeout or self.cfg.timeout_seconds,
                                          max_attempts=max_attempts or self.cfg.max_attempts)
                if resp.status_code >= 400:
                    raise RuntimeError(f"overpass {endpoint} -> HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                if "remark" in data and "error" in str(data["remark"]).lower():
                    raise RuntimeError(f"overpass remark: {data['remark'][:200]}")
                return data.get("elements", [])
            except Exception as exc:  # try next mirror
                last_exc = exc
                log.warning("Overpass endpoint %s failed: %s", endpoint, exc)
        raise RuntimeError(f"all Overpass endpoints failed: {last_exc}")


def build_category_query(filters: Iterable[str], bbox: tuple[float, float, float, float], timeout: int = 180) -> str:
    south, west, north, east = bbox
    parts = []
    for flt in filters:
        for kind in ("node", "way", "relation"):
            parts.append(f'{kind}{flt}({south},{west},{north},{east});')
    return f"[out:json][timeout:{timeout}];(" + "".join(parts) + ");out center tags;"


def element_to_candidate(el: dict[str, Any], category_group: str) -> Candidate | None:
    tags = el.get("tags") or {}
    name = tags.get("name:zh") or tags.get("name") or tags.get("name:en")
    if not name:
        # Unnamed features are retained only for a few high-value types (e.g. lighthouses, waterfalls).
        if tags.get("man_made") == "lighthouse" or tags.get("waterway") == "waterfall" or tags.get("natural") in ("waterfall", "cape", "arch"):
            label = {"lighthouse": "无名灯塔", "waterfall": "无名瀑布", "cape": "无名岬角", "arch": "无名海蚀拱"}
            key = tags.get("man_made") or tags.get("waterway") or tags.get("natural")
            name = f"{label.get(key, '无名地物')}（OSM {el['type']}/{el['id']}）"
        else:
            return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    category = category_from_osm_tags(tags)
    aliases = [v for k, v in tags.items() if k in ("name:en", "name:zh", "alt_name", "old_name", "official_name", "loc_name", "name:zh-Hans", "name:zh-Hant") and v and v != name]
    ext_id = f"{el['type']}/{el['id']}"
    url = f"https://www.openstreetmap.org/{ext_id}"
    keep_tags = {k: v for k, v in tags.items() if k in (
        "natural", "tourism", "historic", "heritage", "man_made", "leisure", "place", "amenity", "waterway", "boundary", "geological",
        "wikidata", "wikipedia", "website", "description", "ele", "protect_class", "religion", "denomination", "landuse", "water", "harbour",
        "addr:city", "addr:district", "addr:county", "is_in", "population", "surface", "access", "fee", "opening_hours",
    )}
    description = tags.get("description") or tags.get("description:zh")
    return Candidate(
        provider="osm",
        external_id=ext_id,
        external_url=url,
        name=name,
        name_en=tags.get("name:en"),
        aliases=aliases,
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
        coordinate_precision="exact" if el["type"] == "node" else "centroid",
        category=category,
        subcategory=category_group,
        tags=keep_tags,
        description=description,
        description_language="zh" if description else None,
        discovery_reason="OSM_feature",
        sources=[
            SourceSpec(
                url=url,
                provider="osm",
                source_type="map_feature",
                title=f"OSM {ext_id}: {name}",
                publisher="OpenStreetMap",
                access_status="fetched",
                terms_url=OSM_COPYRIGHT_URL,
                license_notes=OSM_ATTRIBUTION,
                relationship_type="locates",
                confidence=0.8,
            )
        ],
        raw={"tags": tags, "type": el["type"], "id": el["id"]},
        wikidata_id=tags.get("wikidata"),
        region_hint=" ".join(v for k, v in tags.items() if k.startswith("addr:") or k == "is_in"),
        confidence=0.7 if category not in ("unknown", "other") else 0.5,
    )


def discover_osm_category(ctx: AppContext, category_group: str, bbox: tuple[float, float, float, float] | None = None) -> list[Candidate]:
    filters = OSM_DISCOVERY_QUERIES[category_group]
    client = OverpassClient(ctx)
    query = build_category_query(filters, bbox or ctx.config.bbox)
    elements = client.query(query)
    out = []
    for el in elements:
        cand = element_to_candidate(el, category_group)
        if cand:
            out.append(cand)
    return out


def nearby_features(ctx: AppContext, lat: float, lon: float, radius_m: int = 1500) -> list[Candidate]:
    """Nearby named features around a seed (expansion step)."""
    client = OverpassClient(ctx)
    filters = [f for group in ("coast_features", "water_and_land", "tourism", "historic", "infrastructure", "protected_and_parks") for f in OSM_DISCOVERY_QUERIES[group]]
    parts = []
    for flt in filters:
        for kind in ("node", "way", "relation"):
            parts.append(f"{kind}{flt}(around:{radius_m},{lat},{lon});")
    query = "[out:json][timeout:90];(" + "".join(parts) + ");out center tags;"
    out = []
    for el in client.query(query, timeout=120, max_attempts=2):
        cand = element_to_candidate(el, "nearby_expansion")
        if cand:
            cand.discovery_reason = "nearby_expansion"
            out.append(cand)
    return out


def search_osm_by_name(ctx: AppContext, name: str, bbox: tuple[float, float, float, float] | None = None) -> list[Candidate]:
    """Exact/regex name search within Hainan (used when re-researching a legacy lead)."""
    south, west, north, east = bbox or ctx.config.bbox
    escaped = name.replace("\\", "\\\\").replace('"', '\\"').replace("(", "\\(").replace(")", "\\)").replace("·", ".")
    query = (
        f'[out:json][timeout:40];(node["name"~"{escaped}"]({south},{west},{north},{east});'
        f'way["name"~"{escaped}"]({south},{west},{north},{east});'
        f'relation["name"~"{escaped}"]({south},{west},{north},{east}););out center tags;'
    )
    out = []
    # A per-place lookup must not stall the whole research pass: short timeout, two attempts per mirror.
    for el in OverpassClient(ctx).query(query, timeout=50, max_attempts=2):
        cand = element_to_candidate(el, "name_search")
        if cand:
            out.append(cand)
    return out
