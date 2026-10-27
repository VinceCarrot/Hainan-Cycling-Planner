import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from hainan_explorer.main import create_app
from hainan_explorer.services.export import BackupService, ExportService
from hainan_explorer.services.images import ImageCandidate, ImageService
from hainan_explorer.services.ingest import Candidate, Ingestor, SourceSpec


@pytest.fixture
def seeded(ctx):
    ing = Ingestor(ctx)
    a = ing.ingest(Candidate(provider="osm", external_id="node/1", name="峻壁角灯塔", latitude=19.17, longitude=108.62, category="lighthouse",
                             sources=[SourceSpec(url="https://www.openstreetmap.org/node/1", provider="osm", source_type="map_feature", license_notes="© OpenStreetMap contributors, ODbL 1.0")]))
    b = ing.ingest(Candidate(provider="legacy_catalog", external_id="l1", name="临高古银瀑布", region_hint="临高县", category="waterfall"))
    svc = ImageService(ctx)
    img = svc.upsert_image(ImageCandidate(provider="commons", external_id="File:Junbijiao.jpg", title="Junbijiao.jpg", source_page_url="https://commons.wikimedia.org/wiki/File:Junbijiao.jpg",
                                          original_url="https://upload.wikimedia.org/x.jpg", display_url="https://upload.wikimedia.org/thumb/x.jpg", creator="Alice", license_short="CC BY-SA 4.0",
                                          license_url="https://creativecommons.org/licenses/by-sa/4.0"))
    svc.associate(a.place_id, img, 5.5, ["name_in_title", "geotag_within_150m"])
    return {"a": a.place_id, "b": b.place_id, "img": img}


@pytest.fixture
def client(ctx):
    app = create_app(ctx, start_worker=False)
    with TestClient(app) as c:
        yield c


def test_api_list_detail_decision_undo(client, seeded):
    r = client.get("/api/places?sort=name")
    assert r.status_code == 200 and r.json()["total"] == 2
    card = next(i for i in r.json()["items"] if i["id"] == seeded["a"])
    assert card["image_state"] == "remote" and "未核实" in card["image_badge"]
    detail = client.get(f"/api/places/{seeded['a']}").json()
    assert detail["images"][0]["attribution_text"].startswith("Alice")
    assert detail["facts"]["unknown"]
    assert client.post(f"/api/places/{seeded['a']}/decision", json={"decision": "want_to_visit"}).json()["interest_status"] == "want_to_visit"
    assert client.post("/api/places/undo").json()["interest_status"] == "undecided"
    assert client.post(f"/api/places/{seeded['a']}/decision", json={"decision": "nope"}).status_code == 422
    assert client.get("/api/places/999999").status_code == 404


def test_api_validation_and_safe_paths(client, ctx):
    assert client.post("/api/leads/url", json={"url": "javascript:alert(1)"}).status_code == 422
    assert client.get("/api/export/files/..%5c..%5cexplorer.db").status_code == 404
    assert client.post("/api/import/csv?name=../../etc/passwd").status_code == 404
    assert client.patch("/api/places/1", json={"latitude": 19.0}).status_code == 422
    meta = client.get("/api/meta").json()
    assert "api_key" not in json.dumps(meta)
    assert len(meta["regions"]) == 18


def test_api_image_association_and_report(client, seeded):
    pid, img = seeded["a"], seeded["img"]
    r = client.post(f"/api/places/{pid}/images/{img}/association", json={"status": "user_verified", "make_primary": True})
    assert r.json()["images"][0]["verified_by_user"] == 1 and r.json()["image_badge"] == "图片已人工核实"
    assert client.post(f"/api/images/{img}/report", json={"issue": "wrong place"}).json()["ok"]
    r = client.post(f"/api/places/{pid}/images/{img}/association", json={"status": "rejected"})
    assert r.json()["image_count"] == 0
    assert client.post(f"/api/images/{img}/download").status_code in (403, 502)  # local_copy_allowed but no network in tests -> 502; policy ok


def test_api_merge_relations_and_jobs(client, seeded):
    r = client.post("/api/places/merge", json={"source_id": seeded["b"], "target_id": seeded["a"]})
    assert r.status_code == 200 and "临高古银瀑布" in r.json()["aliases"]
    assert client.post(f"/api/places/{seeded['b']}/unmerge").status_code == 200
    assert client.post("/api/places/merge", json={"source_id": seeded["a"], "target_id": seeded["a"]}).status_code == 400
    job = client.post("/api/jobs", json={"job_type": "research_place", "payload": {"place_id": seeded["a"]}}).json()
    again = client.post("/api/jobs", json={"job_type": "research_place", "payload": {"place_id": seeded["a"]}}).json()
    assert job["job_id"] == again["job_id"]  # dedupe while queued
    assert client.post(f"/api/jobs/{job['job_id']}/cancel").json()["ok"]
    assert client.get(f"/api/jobs/{job['job_id']}").json()["status"] == "cancelled"
    assert client.post("/api/jobs", json={"job_type": "rm_rf", "payload": {}}).status_code == 422


def test_exports_include_ids_aliases_sources_and_image_rights(ctx, seeded):
    svc = ExportService(ctx)
    data = json.loads(svc.export_json())
    assert data["attribution"]["osm"].startswith("© OpenStreetMap")
    place = next(p for p in data["places"] if p["id"] == seeded["a"])
    assert place["code"] == f"HN{seeded['a']:06d}"
    assert place["sources"][0]["url"].startswith("https://www.openstreetmap.org")
    assert place["images"][0]["license_short"] == "CC BY-SA 4.0" and place["images"][0]["attribution_text"]
    assert place["images"][0]["permission_status"] == "local_copy_allowed"
    geo = json.loads(svc.export_geojson())
    assert len(geo["features"]) == 1 and geo["features"][0]["geometry"]["coordinates"] == [108.62, 19.17]
    rows = list(csv.DictReader(io.StringIO(svc.export_csv())))
    assert len(rows) == 2
    row = next(r for r in rows if r["id"] == str(seeded["a"]))
    assert row["primary_image_license"] == "CC BY-SA 4.0" and row["primary_image_source_page"].startswith("https://commons")
    assert row["route_distance_note"] == "" or "not cycling distance" in row["route_distance_note"]
    path = svc.write_export("csv", interest=["undecided"])
    assert path.exists() and path.suffix == ".csv"


def test_backup_and_restore_round_trip(ctx, seeded):
    from hainan_explorer.services.places import PlaceService

    svc = BackupService(ctx)
    backup = svc.backup("t")
    assert backup.exists() and svc.list_backups()[0]["name"] == backup.name
    PlaceService(ctx).decide(seeded["a"], "skip")
    assert PlaceService(ctx).get_place(seeded["a"])["interest_status"] == "skip"
    safety = svc.restore(backup.name)
    assert safety.exists()
    assert PlaceService(ctx).get_place(seeded["a"])["interest_status"] == "undecided"
    with pytest.raises(FileNotFoundError):
        svc.restore("missing.db")


def test_migrations_are_idempotent(ctx):
    assert ctx.db.migrate() == []
    tables = {r[0] for r in ctx.db.conn().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"places", "sources", "place_sources", "images", "place_images", "discovery_runs", "jobs", "reviews", "place_relations", "route_segments", "provider_ids"} <= tables
