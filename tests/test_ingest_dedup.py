from hainan_explorer.services.ingest import Candidate, Ingestor, SourceSpec
from hainan_explorer.services.places import PlaceService


def osm(name, lat, lon, ext="node/1", category="peak", **kw):
    return Candidate(provider="osm", external_id=ext, name=name, latitude=lat, longitude=lon, category=category,
                     sources=[SourceSpec(url=f"https://www.openstreetmap.org/{ext}", provider="osm", source_type="map_feature")], **kw)


def test_same_provider_id_updates_not_duplicates(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(osm("铜鼓岭", 19.67, 111.03))
    b = ing.ingest(osm("铜鼓岭", 19.67, 111.03))
    assert a.action == "created" and b.action == "updated" and a.place_id == b.place_id
    assert PlaceService(ctx).list_places()["total"] == 1


def test_similar_name_within_100m_merges_and_keeps_alias(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(osm("铜鼓岭", 19.67, 111.03))
    b = ing.ingest(Candidate(provider="wikidata", external_id="Q1", name="铜鼓岭景区", latitude=19.6703, longitude=111.0302, category="mountain"))
    assert b.action == "merged" and b.place_id == a.place_id
    place = PlaceService(ctx).get_place(a.place_id)
    assert "铜鼓岭景区" in place["aliases"]
    assert {p["provider"] for p in place["provider_ids"]} == {"osm", "wikidata"}


def test_same_name_300m_apart_creates_pending_relation_not_merge(ctx):
    ing = Ingestor(ctx)
    ing.ingest(osm("观海台", 20.0314, 110.30, category="viewpoint"))
    b = ing.ingest(osm("观海台", 20.0340, 110.30, ext="node/2", category="viewpoint"))
    assert b.action == "created" and b.duplicate_relation_created
    assert PlaceService(ctx).summary()["pending_duplicates"] == 1


def test_same_village_name_far_apart_stays_separate(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(osm("新村", 18.40, 109.98, category="village"))
    b = ing.ingest(osm("新村", 19.90, 110.40, ext="node/2", category="village"))
    assert a.place_id != b.place_id and not b.duplicate_relation_created


def test_wikidata_tag_links_osm_and_wikidata_records(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(Candidate(provider="wikidata", external_id="Q77", name="五公祠", latitude=20.0097, longitude=110.35, category="temple"))
    b = ing.ingest(osm("Wugong Temple", 20.0099, 110.3502, category="temple", wikidata_id="Q77"))
    assert b.action == "linked" and b.place_id == a.place_id


def test_out_of_bbox_coordinates_are_dropped_and_flagged(ctx):
    ing = Ingestor(ctx)
    r = ing.ingest(osm("某地", 39.9, 116.4))
    place = PlaceService(ctx).get_place(r.place_id)
    assert place["latitude"] is None and place["needs_geographic_verification"] == 1


def test_legacy_lead_without_coords_merges_on_exact_name_same_county(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(osm("东坡书院", 19.55, 109.35, category="historic"))
    b = ing.ingest(Candidate(provider="legacy_catalog", external_id="x", name="东坡书院", region_hint="儋州市", category="historic"))
    assert b.action == "merged" and b.place_id == a.place_id


def test_scores_do_not_reward_popularity(ctx):
    ing = Ingestor(ctx)
    obscure = ing.ingest(osm("无名礁", 19.0, 110.5, category="reef"))
    famous = ing.ingest(osm("天涯海角", 18.29, 109.35, ext="node/9", category="attraction", tags={"tourism": "attraction", "has_wikipedia_zh": True}))
    po = PlaceService(ctx).get_place(obscure.place_id)
    pf = PlaceService(ctx).get_place(famous.place_id)
    assert po["novelty_score"] > pf["novelty_score"]


def test_seed_settlements_hidden_by_default(ctx):
    ing = Ingestor(ctx)
    ing.ingest(osm("某村", 19.0, 110.0, category="village"))
    svc = PlaceService(ctx)
    assert svc.list_places()["total"] == 0
    assert svc.list_places(include_seeds=True)["total"] == 1
