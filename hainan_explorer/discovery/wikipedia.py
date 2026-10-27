"""Wikipedia (zh/en) discovery: geosearch grid sweep + title search with extracts.

Text excerpts are CC BY-SA 4.0; we store short extracts with the article URL as the
attribution target. Policy (checked 2026-10-27): descriptive User-Agent, modest rate.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..geo import grid_points
from ..http import ProviderDisabledError
from ..services.context import AppContext
from ..services.ingest import Candidate, SourceSpec
from ..taxonomy import category_from_text

log = logging.getLogger(__name__)

SKIP_TITLE_KEYWORDS = ("学校", "大学", "中学", "小学", "医院", "公司", "火车站", "高铁站", "车站", "机场", "收费站", "派出所", "银行", "酒店", "政府",
                       "法院", "监狱", "电厂", "变电站", "开发区", "工业园", "街道", "社区", "办事处", "有限公司", "集团", "航空")
EXTRACT_MAX = 600


def _api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


class WikipediaClient:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("wikipedia")
        if not self.cfg.enabled:
            raise ProviderDisabledError("wikipedia disabled")
        ctx.config.require_wikimedia_contact("wikipedia")
        self.languages: list[str] = list(self.cfg.options.get("languages") or ["zh", "en"])

    def geosearch(self, lang: str, lat: float, lon: float, radius_m: int = 10000, limit: int = 500) -> list[dict[str, Any]]:
        data = self.ctx.http.get_json(_api(lang), params={"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": min(radius_m, 10000),
                                                           "gslimit": min(limit, 500), "format": "json"}, timeout=self.cfg.timeout_seconds)
        return data.get("query", {}).get("geosearch", [])

    def search(self, lang: str, text: str, limit: int = 5) -> list[dict[str, Any]]:
        data = self.ctx.http.get_json(_api(lang), params={"action": "query", "list": "search", "srsearch": text, "srlimit": limit, "format": "json"},
                                      timeout=self.cfg.timeout_seconds)
        return data.get("query", {}).get("search", [])

    def pages(self, lang: str, pageids: list[int] | None = None, titles: list[str] | None = None) -> list[dict[str, Any]]:
        """Extracts + coordinates + page image + Wikidata id for up to 20 pages."""
        params: dict[str, Any] = {
            "action": "query", "prop": "extracts|coordinates|pageprops|pageimages|info", "exintro": 1, "explaintext": 1, "exlimit": 20,
            "coprop": "type|name", "ppprop": "wikibase_item|disambiguation", "piprop": "original|name", "inprop": "url",
            "redirects": 1, "format": "json",
        }
        if pageids:
            params["pageids"] = "|".join(str(p) for p in pageids[:20])
        elif titles:
            params["titles"] = "|".join(titles[:20])
        else:
            return []
        if lang == "zh":
            params["variant"] = "zh-cn"
        data = self.ctx.http.get_json(_api(lang), params=params, timeout=self.cfg.timeout_seconds)
        pages = data.get("query", {}).get("pages", {})
        return [p for p in pages.values() if "missing" not in p]


def page_to_candidate(lang: str, page: dict[str, Any], reason: str = "Wikipedia_geosearch") -> Candidate | None:
    title = page.get("title") or ""
    if not title or any(k in title for k in SKIP_TITLE_KEYWORDS):
        return None
    props = page.get("pageprops") or {}
    if "disambiguation" in props:
        return None
    extract = (page.get("extract") or "").strip()
    extract = re.sub(r"\s+", " ", extract)[:EXTRACT_MAX]
    coords = (page.get("coordinates") or [{}])[0]
    lat, lon = coords.get("lat"), coords.get("lon")
    qid = props.get("wikibase_item")
    url = page.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
    category = category_from_text(title + " " + extract[:120])
    tags: dict[str, Any] = {f"has_wikipedia_{lang}": True, f"wikipedia_{lang}": url}
    if qid:
        tags["wikidata"] = qid
    image_hints = {}
    original = page.get("original") or {}
    if original.get("source") and "upload.wikimedia.org" in original["source"]:
        image_hints["wikipedia_page_image"] = original["source"]
        if page.get("pageimage"):
            image_hints["commons_file"] = page["pageimage"]
    return Candidate(
        provider=f"wikipedia_{lang}",
        external_id=str(page.get("pageid")),
        external_url=url,
        name=title,
        name_en=title if lang == "en" else None,
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
        coordinate_precision="approximate",
        category=category,
        tags=tags,
        description=extract or None,
        description_language=lang if extract else None,
        discovery_reason=reason,
        sources=[
            SourceSpec(
                url=url,
                provider=f"wikipedia_{lang}",
                source_type="encyclopedia",
                title=title,
                publisher=f"{lang}.wikipedia.org",
                access_status="fetched",
                terms_url="https://creativecommons.org/licenses/by-sa/4.0/",
                license_notes="Wikipedia text, CC BY-SA 4.0 — attribution: article URL",
                excerpt=extract[:300] or None,
                relationship_type="describes",
                confidence=0.85,
            )
        ],
        raw={"pageid": page.get("pageid"), "lang": lang},
        wikidata_id=qid,
        image_hints=image_hints,
        confidence=0.75,
    )


def sweep_geosearch(ctx: AppContext, lang: str, step_km: float = 14.0, radius_m: int = 10000, on_cell=None) -> list[Candidate]:
    """Grid-sweep the island with 10 km geosearch circles and fetch extracts for every page found."""
    client = WikipediaClient(ctx)
    seen: dict[int, dict[str, Any]] = {}
    cells = grid_points(ctx.config.bbox, step_km)
    for idx, (lat, lon) in enumerate(cells):
        try:
            hits = client.geosearch(lang, lat, lon, radius_m=radius_m)
        except Exception as exc:
            log.warning("geosearch %s cell %d failed: %s", lang, idx, exc)
            hits = []
        for h in hits:
            seen.setdefault(h["pageid"], h)
        if on_cell:
            on_cell(idx, len(cells), len(seen))
    out: list[Candidate] = []
    ids = list(seen.keys())
    for i in range(0, len(ids), 20):
        for page in client.pages(lang, pageids=ids[i:i + 20]):
            cand = page_to_candidate(lang, page)
            if cand:
                out.append(cand)
    return out


def search_wikipedia_for_name(ctx: AppContext, name: str, lang: str = "zh") -> list[Candidate]:
    client = WikipediaClient(ctx)
    hits = client.search(lang, name, limit=5)
    if not hits:
        return []
    out = []
    for page in client.pages(lang, pageids=[h["pageid"] for h in hits]):
        cand = page_to_candidate(lang, page, reason="Wikipedia_search")
        if cand:
            out.append(cand)
    return out
