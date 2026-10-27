import pytest

from hainan_explorer.services.ingest import Candidate, Ingestor, SourceSpec
from hainan_explorer.services.places import PlaceService


def _two_places(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(Candidate(provider="osm", external_id="node/1", name="光村银滩", latitude=19.84, longitude=109.25, category="beach",
                             sources=[SourceSpec(url="https://osm.org/1", provider="osm", source_type="map_feature")]))
    b = ing.ingest(Candidate(provider="legacy_catalog", external_id="legacy-1", name="儋州光村银滩沙滩", region_hint="儋州市", category="beach",
                             sources=[SourceSpec(url="https://example.com/trip", provider="legacy_catalog", source_type="travelogue", access_status="link_only")]))
    assert a.place_id != b.place_id
    return a.place_id, b.place_id


def test_decision_undo_and_history(ctx):
    pid, _ = _two_places(ctx)
    svc = PlaceService(ctx)
    svc.decide(pid, "want_to_visit", score=8)
    assert svc.get_place(pid)["interest_status"] == "want_to_visit"
    svc.decide(pid, "skip")
    assert svc.undo_last_decision()["interest_status"] == "want_to_visit"
    assert svc.undo_last_decision(pid)["interest_status"] == "undecided"
    assert svc.undo_last_decision(pid) is None
    with pytest.raises(ValueError):
        svc.decide(pid, "love_it")


def test_decisions_persist_across_context_restart(tmp_path, monkeypatch):
    from tests.conftest import make_config
    from hainan_explorer.services.context import AppContext

    monkeypatch.setenv("HAINAN_EXPLORER_CONTACT", "t@example.org")
    cfg = make_config(tmp_path)
    ctx1 = AppContext(cfg)
    pid, _ = _two_places(ctx1)
    PlaceService(ctx1).decide(pid, "maybe")
    ctx1.close()
    ctx2 = AppContext(cfg)
    assert PlaceService(ctx2).get_place(pid)["interest_status"] == "maybe"
    ctx2.close()


def test_merge_is_reversible_and_preserves_everything(ctx):
    target, source = _two_places(ctx)
    svc = PlaceService(ctx)
    before = svc.get_place(target)
    merged = svc.merge(source, target, reason="test")
    assert "儋州光村银滩沙滩" in merged["aliases"]
    assert merged["source_count"] == 2
    assert svc.get_place(source)["merged_into_place_id"] == target
    assert svc.list_places()["total"] == 1
    assert any(p["provider"] == "legacy_catalog" for p in merged["provider_ids"])
    restored = svc.unmerge(source)
    assert restored["merged_into_place_id"] is None
    after = svc.get_place(target)
    assert after["aliases"] == before["aliases"]
    assert after["source_count"] == before["source_count"]
    assert any(p["provider"] == "legacy_catalog" for p in restored["provider_ids"])
    assert svc.list_places()["total"] == 2


def test_merge_rejects_self_and_double_merge(ctx):
    target, source = _two_places(ctx)
    svc = PlaceService(ctx)
    with pytest.raises(ValueError):
        svc.merge(target, target)
    svc.merge(source, target)
    with pytest.raises(ValueError):
        svc.merge(source, target)


def test_filters_and_sorting(ctx):
    target, source = _two_places(ctx)
    svc = PlaceService(ctx)
    assert svc.list_places(region="danzhou")["total"] == 2
    assert svc.list_places(has_coords=True)["total"] == 1
    assert svc.list_places(needs_geo=True)["total"] == 1
    assert svc.list_places(q="银滩")["total"] == 2
    svc.decide(target, "want_to_visit")
    assert svc.list_places(undecided_only=True)["total"] == 1
    assert svc.list_places(interest="want_to_visit")["items"][0]["id"] == target
    names = [i["canonical_name"] for i in svc.list_places(sort="name")["items"]]
    assert names == sorted(names)


def test_update_notes_coordinates_and_name(ctx):
    _, source = _two_places(ctx)
    svc = PlaceService(ctx)
    p = svc.update_notes(source, notes="骑行可达？待核实", latitude=19.841, longitude=109.251, canonical_name="光村银滩（旧录）")
    assert p["personal_notes"].startswith("骑行")
    assert p["coordinate_source"] == "user" and p["needs_geographic_verification"] == 0
    assert "儋州光村银滩沙滩" in p["aliases"]
    with pytest.raises(ValueError):
        svc.update_notes(source, verification_status="sure")
