"""Wikimedia Commons image discovery with per-file license/attribution metadata.

Policy (checked 2026-10-27): https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy —
descriptive User-Agent, reasonable rate; https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia —
each file has its own license; attribution and license link must be preserved. We never
assume a uniform license and only download files whose license passes the local policy.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any

from ..http import ProviderDisabledError
from ..services.context import AppContext
from ..services.images import ImageCandidate, normalize_license

log = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
TAG_RE = re.compile(r"<[^>]+>")
IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|tiff?)$", re.IGNORECASE)
VIEW_TYPE_KEYWORDS = [
    ("aerial", ("aerial", "drone", "航拍", "鸟瞰", "from above")),
    ("sunrise_sunset", ("sunset", "sunrise", "日落", "日出", "夕阳", "晚霞")),
    ("architecture", ("temple", "building", "church", "tower", "寺", "庙", "楼", "塔", "建筑", "祠")),
    ("trail", ("trail", "path", "boardwalk", "栈道", "步道", "小路")),
    ("roadside", ("road", "highway", "公路", "路边", "street", "街")),
    ("closeup", ("close-up", "closeup", "detail", "特写", "flower", "bird", "crab")),
    ("landscape", ("view", "panorama", "landscape", "beach", "bay", "coast", "全景", "风景", "海", "山")),
]


def strip_html(text: str | None) -> str | None:
    if not text:
        return None
    return html.unescape(TAG_RE.sub("", text)).strip() or None


def guess_view_type(*texts: str | None) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for view, keys in VIEW_TYPE_KEYWORDS:
        if any(k in blob for k in keys):
            return view
    return "unknown"


class CommonsClient:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("commons")
        if not self.cfg.enabled:
            raise ProviderDisabledError("commons disabled")
        ctx.config.require_wikimedia_contact("commons")
        self.api = self.cfg.endpoint or COMMONS_API
        self.width = ctx.config.license_policy.download_width

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "format": "json", "formatversion": 2}
        return self.ctx.http.get_json(self.api, params=params, timeout=self.cfg.timeout_seconds, max_attempts=self.cfg.max_attempts)

    def geosearch(self, lat: float, lon: float, radius_m: int = 1500, limit: int = 50) -> list[dict[str, Any]]:
        data = self._get({"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}", "gsradius": min(max(radius_m, 10), 10000),
                          "gsnamespace": 6, "gslimit": min(limit, 500), "gsprimary": "all"})
        return data.get("query", {}).get("geosearch", [])

    def search_files(self, text: str, limit: int = 30) -> list[dict[str, Any]]:
        data = self._get({"action": "query", "list": "search", "srsearch": text, "srnamespace": 6, "srlimit": min(limit, 50), "srinfo": "", "srprop": "snippet"})
        return data.get("query", {}).get("search", [])

    def category_members(self, category: str, limit: int = 50) -> list[dict[str, Any]]:
        title = category if category.lower().startswith("category:") else f"Category:{category}"
        data = self._get({"action": "query", "list": "categorymembers", "cmtitle": title, "cmnamespace": 6, "cmlimit": min(limit, 200), "cmtype": "file"})
        return data.get("query", {}).get("categorymembers", [])

    def imageinfo(self, titles: list[str] | None = None, pageids: list[int] | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "action": "query", "prop": "imageinfo|coordinates", "iiprop": "url|size|mime|extmetadata|sha1", "iiurlwidth": self.width,
            "iiextmetadatafilter": "LicenseShortName|License|LicenseUrl|Artist|Credit|ImageDescription|ObjectName|DateTimeOriginal|Categories|Restrictions|AttributionRequired|Attribution|Copyrighted|UsageTerms|GPSLatitude|GPSLongitude",
            "coprop": "type|name",
        }
        if titles:
            params["titles"] = "|".join(titles[:50])
        elif pageids:
            params["pageids"] = "|".join(str(p) for p in pageids[:50])
        else:
            return []
        data = self._get(params)
        return [p for p in data.get("query", {}).get("pages", []) if "missing" not in p]


def page_to_image_candidate(page: dict[str, Any]) -> ImageCandidate | None:
    title = page.get("title") or ""
    if not IMAGE_EXT_RE.search(title):
        return None
    infos = page.get("imageinfo") or []
    if not infos:
        return None
    info = infos[0]
    meta = info.get("extmetadata") or {}

    def m(key: str) -> str | None:
        v = meta.get(key)
        return v.get("value") if isinstance(v, dict) else None

    license_short = strip_html(m("LicenseShortName")) or strip_html(m("License"))
    license_url = m("LicenseUrl")
    license_id = normalize_license(license_short, license_url)
    copyrighted = (m("Copyrighted") or "").lower()
    if license_id is None and copyrighted == "false":
        license_id = "public domain"
        license_short = license_short or "Public domain"
    creator = strip_html(m("Artist"))
    credit = strip_html(m("Credit"))
    description = strip_html(m("ImageDescription"))
    object_name = strip_html(m("ObjectName"))
    categories = [c for c in (m("Categories") or "").split("|") if c]
    restrictions = m("Restrictions") or None
    attribution = strip_html(m("Attribution"))
    coords = (page.get("coordinates") or [{}])
    lat = lon = None
    for c in coords:
        if c.get("primary") is not False and c.get("lat") is not None:
            lat, lon = c.get("lat"), c.get("lon")
            break
    if lat is None and m("GPSLatitude") and m("GPSLongitude"):
        try:
            lat, lon = float(m("GPSLatitude")), float(m("GPSLongitude"))
        except ValueError:
            lat = lon = None
    page_url = info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}"
    display_url = info.get("thumburl") or info.get("url")
    attribution_text = attribution or f"{creator or credit or 'Unknown author'}, via Wikimedia Commons, {license_short or 'license unknown'}"
    date_taken = m("DateTimeOriginal")
    return ImageCandidate(
        provider="commons",
        external_id=title,
        title=title.removeprefix("File:"),
        source_page_url=page_url,
        original_url=info.get("url"),
        display_url=display_url,
        description=description or object_name,
        creator=creator or credit,
        attribution_text=attribution_text,
        attribution_url=page_url,
        license_id=license_id,
        license_short=license_short,
        license_url=license_url,
        width=info.get("width"),
        height=info.get("height"),
        mime_type=info.get("mime"),
        bytes=info.get("size"),
        latitude=lat,
        longitude=lon,
        categories=categories[:20],
        date_taken=strip_html(date_taken) if date_taken else None,
        restrictions=restrictions,
        view_type=guess_view_type(title, description, " ".join(categories)),
        raw={"pageid": page.get("pageid"), "sha1": info.get("sha1")},
    )


def fetch_image_candidates(client: CommonsClient, titles: list[str] | None = None, pageids: list[int] | None = None) -> list[ImageCandidate]:
    out = []
    for i in range(0, len(titles or pageids or []), 50):
        chunk_titles = titles[i:i + 50] if titles else None
        chunk_ids = pageids[i:i + 50] if pageids else None
        for page in client.imageinfo(titles=chunk_titles, pageids=chunk_ids):
            cand = page_to_image_candidate(page)
            if cand:
                out.append(cand)
    return out
