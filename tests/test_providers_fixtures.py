"""Provider response parsing against saved fixtures; no live network."""
import json

import pytest

from hainan_explorer.config import LicensePolicy
from hainan_explorer.discovery.commons import guess_view_type, page_to_image_candidate
from hainan_explorer.discovery.osm import build_category_query, element_to_candidate
from hainan_explorer.discovery.web_search import PageFetcher, extract_mentions, html_to_text
from hainan_explorer.discovery.wikidata import binding_to_candidate
from hainan_explorer.discovery.wikipedia import page_to_candidate
from hainan_explorer.http import ProviderDisabledError
from hainan_explorer.services.images import evaluate_permission
from tests.conftest import load_fixture


def test_overpass_elements_to_candidates():
    data = json.loads(load_fixture("overpass_sample.json"))
    cands = [c for c in (element_to_candidate(e, "coast_features") for e in data["elements"]) if c]
    names = {c.name for c in cands}
    assert "莺歌嘴" in names and "鱼鳞洲" in names
    lighthouse = next(c for c in cands if c.category == "lighthouse")
    assert lighthouse.external_id.startswith("node/")
    assert lighthouse.sources[0].license_notes.startswith("© OpenStreetMap")
    way = next(c for c in cands if c.external_id.startswith("way/"))
    assert way.coordinate_precision == "centroid" and way.latitude is not None
    unnamed_shop = [e for e in data["elements"] if not e.get("tags", {}).get("name") and e["tags"].get("shop")]
    assert unnamed_shop and all(element_to_candidate(e, "x") is None for e in unnamed_shop)
    wd = next(c for c in cands if c.wikidata_id)
    assert wd.wikidata_id == "Q11138700"


def test_overpass_query_builder_uses_bbox():
    q = build_category_query(['["natural"="beach"]'], (18.1, 108.5, 20.2, 111.1))
    assert "(18.1,108.5,20.2,111.1)" in q and "out center tags" in q and q.count('["natural"="beach"]') == 3


def test_wikidata_bindings_to_candidates():
    data = json.loads(load_fixture("wikidata_sample.json"))
    cands = [binding_to_candidate(b) for b in data["results"]["bindings"]]
    kept = [c for c in cands if c]
    assert len(kept) == 2  # the human (Q5) and the school are dropped
    cape = next(c for c in kept if c.external_id == "Q10942215")
    assert cape.category == "cape" and cape.tags["has_wikipedia_zh"] and cape.image_hints["commons_file"] == "Yulin_Zhou.jpg"
    assert cape.region_hint == "东方市"


def test_wikipedia_page_to_candidate_keeps_short_extract_and_attribution():
    data = json.loads(load_fixture("wikipedia_pages_sample.json"))
    pages = list(data["query"]["pages"].values())
    cands = [page_to_candidate("zh", p) for p in pages]
    kept = [c for c in cands if c]
    assert len(kept) == 1  # disambiguation page and school dropped
    c = kept[0]
    assert c.name == "铜鼓岭" and c.latitude == pytest.approx(19.6666) and c.wikidata_id == "Q11138700"
    assert c.sources[0].license_notes.startswith("Wikipedia text, CC BY-SA 4.0")
    assert len(c.description) <= 600


def test_commons_imageinfo_parsing_and_policy():
    data = json.loads(load_fixture("commons_imageinfo_sample.json"))
    pages = data["query"]["pages"]
    cands = {p["title"]: page_to_image_candidate(p) for p in pages}
    free = cands["File:Tonggu Ridge view (122209187).jpg"]
    assert free.license_id == "cc-by-sa-4.0" and free.creator == "肥川" and free.latitude == pytest.approx(19.663927)
    assert free.display_url.startswith("https://upload.wikimedia.org/") and "1600px" in free.display_url
    assert evaluate_permission(free.license_id, LicensePolicy())[0] == "local_copy_allowed"
    nc = cands["File:Haikou sunset NC.jpg"]
    assert nc.license_id == "cc-by-nc-2.0"
    assert evaluate_permission(nc.license_id, LicensePolicy())[0] == "link_only"
    nolic = cands["File:Mystery.jpg"]
    assert nolic.license_id is None
    assert cands["File:Not an image.pdf"] is None
    assert guess_view_type("Sunset over Haikou bay") == "sunrise_sunset"


def test_html_to_text_and_mention_extraction():
    html = load_fixture("travelogue_sample.html")
    text = html_to_text(html)
    assert "<script" not in text and "alert" not in text
    known = {"铜鼓岭": 1, "石头公园": 2}
    matched, new_phrases = extract_mentions(text, known)
    assert set(matched) == {1, 2}
    phrases = [p for p, _ in new_phrases]
    assert "月亮湾" in phrases and "宝陵港" in phrases
    assert all(p not in ("海南岛", "文昌市") for p in phrases)
    assert all(evidence for _, evidence in new_phrases)


def test_page_fetcher_blocks_disabled_domains_and_private_hosts(ctx):
    fetcher = PageFetcher(ctx)
    ok, reason = fetcher.is_allowed("https://www.xiaohongshu.com/explore/abc")
    assert not ok and "disabled" in reason
    ok, reason = fetcher.is_allowed("http://127.0.0.1:8765/api/summary")
    assert not ok and "SSRF" in reason
    ok, reason = fetcher.is_allowed("ftp://example.com/x")
    assert not ok


def test_wikimedia_clients_refuse_without_contact(ctx_no_contact):
    from hainan_explorer.discovery.commons import CommonsClient
    from hainan_explorer.discovery.wikidata import WikidataClient
    from hainan_explorer.discovery.wikipedia import WikipediaClient

    for cls in (CommonsClient, WikidataClient, WikipediaClient):
        with pytest.raises(ProviderDisabledError, match="HAINAN_EXPLORER_CONTACT"):
            cls(ctx_no_contact)


def test_web_search_disabled_without_key(ctx):
    from hainan_explorer.discovery.web_search import WebSearchAdapter

    with pytest.raises(ProviderDisabledError):
        WebSearchAdapter(ctx)
