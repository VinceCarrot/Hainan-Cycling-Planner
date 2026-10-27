"""Wikidata discovery: all coordinate-bearing entities inside the Hainan bbox (SPARQL, paged).

Data is CC0. Policy (checked 2026-10-27): query.wikidata.org requires a descriptive
User-Agent and asks for modest, sequential queries; we page with LIMIT/OFFSET.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..http import ProviderDisabledError
from ..services.context import AppContext
from ..services.ingest import Candidate, SourceSpec
from ..taxonomy import category_from_text, category_from_wikidata_classes

log = logging.getLogger(__name__)

SPARQL_PAGE = """
SELECT ?item ?itemLabel ?itemDescription ?zhLabel ?enLabel ?lat ?lon
       (GROUP_CONCAT(DISTINCT ?classId; separator="|") AS ?classes)
       (GROUP_CONCAT(DISTINCT ?classLabel; separator="|") AS ?classLabels)
       (SAMPLE(?image) AS ?image) (SAMPLE(?commonsCat) AS ?commonsCat)
       (SAMPLE(?zhwiki) AS ?zhwiki) (SAMPLE(?enwiki) AS ?enwiki) (SAMPLE(?adminLabel) AS ?adminLabel)
       (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases)
WHERE {
  SERVICE wikibase:box {
    ?item wdt:P625 ?loc .
    bd:serviceParam wikibase:cornerWest "Point(%(west)s %(south)s)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerEast "Point(%(east)s %(north)s)"^^geo:wktLiteral .
  }
  BIND(geof:latitude(?loc) AS ?lat) BIND(geof:longitude(?loc) AS ?lon)
  OPTIONAL { ?item wdt:P31 ?class . BIND(STRAFTER(STR(?class), "entity/") AS ?classId)
             ?class rdfs:label ?classLabel FILTER(LANG(?classLabel) = "zh") }
  OPTIONAL { ?item wdt:P18 ?image }
  OPTIONAL { ?item wdt:P373 ?commonsCat }
  OPTIONAL { ?zhwiki schema:about ?item ; schema:isPartOf <https://zh.wikipedia.org/> }
  OPTIONAL { ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?item wdt:P131 ?admin . ?admin rdfs:label ?adminLabel FILTER(LANG(?adminLabel) = "zh") }
  OPTIONAL { ?item rdfs:label ?zhLabel FILTER(LANG(?zhLabel) = "zh") }
  OPTIONAL { ?item rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") }
  OPTIONAL { ?item skos:altLabel ?alias FILTER(LANG(?alias) IN ("zh", "zh-cn", "zh-hans", "en")) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "zh,zh-cn,zh-hans,en". }
}
GROUP BY ?item ?itemLabel ?itemDescription ?zhLabel ?enLabel ?lat ?lon
ORDER BY ?item
LIMIT %(limit)s OFFSET %(offset)s
"""

HUMAN_OR_EVENT_CLASSES = {"Q5", "Q1656682", "Q1190554", "Q13406463", "Q4830453", "Q43229", "Q783794", "Q891723", "Q7278", "Q11032", "Q484170"}
# classes we do not want as destinations (organisations, companies, schools, stations...)
SKIP_CLASSES = {"Q4830453", "Q783794", "Q3918", "Q9842", "Q159334", "Q55488", "Q928830", "Q1248784", "Q7075", "Q16917", "Q11707", "Q27686", "Q41253", "Q1187580", "Q1497375", "Q294414", "Q1248784"}
SKIP_LABEL_KEYWORDS = ("学校", "大学", "医院", "公司", "火车站", "高铁站", "地铁站", "车站", "机场", "收费站", "加油站", "派出所", "银行", "酒店", "小区", "政府", "法院", "监狱", "基地", "工厂", "电厂", "变电站", "开发区", "工业园", "街道", "社区", "办事处")


def _val(binding: dict[str, Any], key: str) -> str | None:
    v = binding.get(key)
    return v.get("value") if v else None


def binding_to_candidate(b: dict[str, Any]) -> Candidate | None:
    qid = _val(b, "item").rsplit("/", 1)[-1]
    zh = _val(b, "zhLabel")
    en = _val(b, "enLabel")
    label = zh or _val(b, "itemLabel") or en
    if not label or re.fullmatch(r"Q\d+", label):
        return None
    classes = [c for c in (_val(b, "classes") or "").split("|") if c]
    class_labels = [c for c in (_val(b, "classLabels") or "").split("|") if c]
    if any(c in HUMAN_OR_EVENT_CLASSES or c in SKIP_CLASSES for c in classes):
        return None
    if any(k in label for k in SKIP_LABEL_KEYWORDS):
        return None
    lat = _val(b, "lat")
    lon = _val(b, "lon")
    category = category_from_wikidata_classes(classes)
    if category == "unknown":
        category = category_from_text(" ".join(class_labels) + " " + label)
    description = _val(b, "itemDescription")
    image = _val(b, "image")
    commons_cat = _val(b, "commonsCat")
    zhwiki = _val(b, "zhwiki")
    enwiki = _val(b, "enwiki")
    aliases = [a for a in (_val(b, "aliases") or "").split("|") if a and a != label]
    if en and en != label:
        aliases.append(en)
    tags: dict[str, Any] = {"wikidata": qid, "wikidata_classes": classes[:6], "wikidata_class_labels": class_labels[:6]}
    if zhwiki:
        tags["has_wikipedia_zh"] = True
        tags["wikipedia_zh"] = zhwiki
    if enwiki:
        tags["has_wikipedia_en"] = True
        tags["wikipedia_en"] = enwiki
    url = f"https://www.wikidata.org/wiki/{qid}"
    image_hints: dict[str, Any] = {}
    if image:
        image_hints["commons_file"] = image.rsplit("/", 1)[-1]
    if commons_cat:
        image_hints["commons_category"] = commons_cat
    return Candidate(
        provider="wikidata",
        external_id=qid,
        external_url=url,
        name=label,
        name_en=en,
        aliases=aliases,
        latitude=float(lat) if lat else None,
        longitude=float(lon) if lon else None,
        coordinate_precision="approximate",
        category=category,
        subcategory=class_labels[0] if class_labels else None,
        tags=tags,
        description=description,
        description_language="zh" if description else None,
        discovery_reason="Wikidata_entity",
        sources=[
            SourceSpec(
                url=url,
                provider="wikidata",
                source_type="knowledge_base",
                title=f"Wikidata {qid}: {label}",
                publisher="Wikidata",
                access_status="fetched",
                terms_url="https://creativecommons.org/publicdomain/zero/1.0/",
                license_notes="Wikidata, CC0 1.0",
                excerpt=description,
                relationship_type="describes",
                confidence=0.8,
            )
        ],
        raw={k: _val(b, k) for k in b.keys()},
        wikidata_id=qid,
        region_hint=_val(b, "adminLabel"),
        image_hints=image_hints,
        confidence=0.75,
    )


class WikidataClient:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("wikidata")
        if not self.cfg.enabled:
            raise ProviderDisabledError("wikidata disabled")
        ctx.config.require_wikimedia_contact("wikidata")
        self.endpoint = self.cfg.endpoint or "https://query.wikidata.org/sparql"
        self.api = self.cfg.options.get("api_endpoint") or "https://www.wikidata.org/w/api.php"

    def sparql(self, query: str) -> list[dict[str, Any]]:
        resp = self.ctx.http.get(self.endpoint, params={"query": query, "format": "json"}, headers={"Accept": "application/sparql-results+json"},
                                 timeout=self.cfg.timeout_seconds, max_attempts=self.cfg.max_attempts)
        if resp.status_code >= 400:
            from ..http import HttpStatusError

            raise HttpStatusError(resp.status_code, self.endpoint, resp.text[:200])
        return resp.json()["results"]["bindings"]

    def iter_bbox(self, bbox: tuple[float, float, float, float] | None = None, page_size: int = 200, max_pages: int = 50):
        south, west, north, east = bbox or self.ctx.config.bbox
        offset = 0
        for _ in range(max_pages):
            query = SPARQL_PAGE % {"south": south, "west": west, "north": north, "east": east, "limit": page_size, "offset": offset}
            rows = self.sparql(query)
            if not rows:
                break
            yield offset, rows
            if len(rows) < page_size:
                break
            offset += page_size

    def search_entities(self, text: str, language: str = "zh", limit: int = 8) -> list[dict[str, Any]]:
        data = self.ctx.http.get_json(self.api, params={"action": "wbsearchentities", "search": text, "language": language, "uselang": language,
                                                        "type": "item", "limit": limit, "format": "json"}, timeout=self.cfg.timeout_seconds)
        return data.get("search", [])

    def entity_bindings(self, qids: list[str]) -> list[dict[str, Any]]:
        """Fetch the same projection as the bbox query for specific QIDs."""
        if not qids:
            return []
        values = " ".join(f"wd:{q}" for q in qids)
        query = SPARQL_PAGE.replace(
            "SERVICE wikibase:box {\n    ?item wdt:P625 ?loc .\n    bd:serviceParam wikibase:cornerWest \"Point(%(west)s %(south)s)\"^^geo:wktLiteral .\n    bd:serviceParam wikibase:cornerEast \"Point(%(east)s %(north)s)\"^^geo:wktLiteral .\n  }",
            f"VALUES ?item {{ {values} }} ?item wdt:P625 ?loc .",
        ) % {"limit": len(qids), "offset": 0}
        return self.sparql(query)


def discover_wikidata(ctx: AppContext, bbox: tuple[float, float, float, float] | None = None, on_page=None) -> list[Candidate]:
    client = WikidataClient(ctx)
    out: list[Candidate] = []
    for offset, rows in client.iter_bbox(bbox):
        for b in rows:
            cand = binding_to_candidate(b)
            if cand:
                out.append(cand)
        if on_page:
            on_page(offset, len(rows))
    return out
