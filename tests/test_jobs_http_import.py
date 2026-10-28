import json
import threading

import httpx
import pytest

from hainan_explorer.http import HostCooldownError, HttpClient, RateLimitedError
from hainan_explorer.services.importer import import_corridor, import_csv, import_legacy_catalog
from hainan_explorer.services.jobs import JobCancelled, JobService
from hainan_explorer.services.places import PlaceService


def _client_with_transport(handler, user_agent="HainanExplorerTests/0 (tests)"):
    client = HttpClient(user_agent)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": user_agent})
    return client


def test_http_backoff_on_429_then_success(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    sleeps = []
    monkeypatch.setattr("hainan_explorer.http.time.sleep", lambda s: sleeps.append(s))
    client = _client_with_transport(handler)
    client.set_rate("api.test", 0)
    assert client.get_json("https://api.test/x") == {"ok": True}
    assert calls["n"] == 3 and len(sleeps) >= 2
    assert client.stats["api.test"]["rate_limited"] == 2


def test_http_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("hainan_explorer.http.time.sleep", lambda s: None)
    client = _client_with_transport(lambda req: httpx.Response(429))
    client.set_rate("api.test", 0)
    client.cooldown_after_failures = 10  # keep the circuit breaker out of this test
    with pytest.raises(RateLimitedError):
        client.get("https://api.test/x", max_attempts=3)


def test_http_cooldown_after_repeated_503(monkeypatch):
    monkeypatch.setattr("hainan_explorer.http.time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, headers={"Retry-After": "40"})

    client = _client_with_transport(handler)
    client.set_rate("api.test", 0)
    with pytest.raises(HostCooldownError):
        client.get("https://api.test/x", max_attempts=4)
    assert calls["n"] == 3  # the third consecutive 503 opens the breaker
    assert client.cooldown_remaining("api.test") >= 100  # max(cooldown_seconds, Retry-After)
    with pytest.raises(HostCooldownError):
        client.get("https://api.test/y")
    assert calls["n"] == 3  # refused without a request while cooling down


def test_http_sends_identifying_user_agent_and_redacts_query(monkeypatch):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, json={})

    client = _client_with_transport(handler, "HainanExplorer/0.2 (test@example.org)")
    client.set_rate("api.test", 0)
    client.get_json("https://api.test/x", params={"api_key": "SECRET"})
    assert seen["ua"].startswith("HainanExplorer/0.2")
    from hainan_explorer.http import _redact

    assert "SECRET" not in _redact("https://api.test/x?api_key=SECRET")


def test_job_queue_lifecycle_retry_and_cancel(ctx):
    jobs = JobService(ctx)
    attempts = {"n": 0}

    def flaky(run):
        attempts["n"] += 1
        run.progress(stage="work", done=attempts["n"], total=2)
        if attempts["n"] == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    jobs.register("flaky", flaky)
    job_id = jobs.enqueue("flaky", {"x": 1}, max_attempts=3, dedupe_key="flaky:1")
    assert jobs.enqueue("flaky", {"x": 1}, dedupe_key="flaky:1") == job_id
    jobs.run_pending()
    job = jobs.get_job(job_id)
    assert job["status"] == "retry_wait" and "boom" in job["last_error"]
    with ctx.db.transaction() as conn:
        conn.execute("UPDATE jobs SET next_run_at='2000-01-01T00:00:00.000Z' WHERE id=?", (job_id,))
    jobs.run_pending()
    job = jobs.get_job(job_id)
    assert job["status"] == "succeeded" and job["progress"]["result"] == {"ok": True} and job["attempt_count"] == 2
    assert any("boom" in l["message"] for l in job["logs"])

    def cancellable(run):
        run.check_cancelled()
        return {}

    jobs.register("cancellable", cancellable)
    jid = jobs.enqueue("cancellable")
    jobs.cancel(jid)
    jobs.run_pending()
    assert jobs.get_job(jid)["status"] == "cancelled"
    assert jobs.retry(jid) and jobs.get_job(jid)["status"] == "queued"
    jobs.run_pending()
    assert jobs.get_job(jid)["status"] == "succeeded"


def test_recover_only_stale_running_jobs(ctx):
    jobs = JobService(ctx)
    fresh = jobs.enqueue("x", {"a": 1})
    stale = jobs.enqueue("x", {"a": 2})
    with ctx.db.transaction() as conn:
        conn.execute("UPDATE jobs SET status='running', started_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (fresh,))
        conn.execute("UPDATE jobs SET status='running', started_at='2000-01-01T00:00:00.000Z' WHERE id=?", (stale,))
    assert jobs.recover_interrupted() == 1
    assert jobs.get_job(stale)["status"] == "queued" and jobs.get_job(fresh)["status"] == "running"


def test_legacy_import_keeps_names_as_leads(ctx, tmp_path):
    records = [{
        "id": "danzhou-eman-coast-viewpoint", "name": "峨蔓火山海岸观景台", "region": "儋州市", "category": "海岸观景点",
        "summary": {"text": "作者在观景台停留拍照。", "source_ids": ["xhs-1"]},
        "sources": [{"id": "xhs-1", "platform": "小红书", "kind": "visitor_experience", "title": "儋州一日", "url": "https://www.xiaohongshu.com/explore/abc", "accessed_at": "2026-10-22"}],
        "images": [], "status": "candidate", "research_notes": ["只有一篇来源"],
    }, {
        "id": "haikou-clock-tower", "name": "海口钟楼", "region": "海口市", "category": "历史街区与地标", "latitude": 20.0466062, "longitude": 110.3372243,
        "coordinate_source_id": "osm-1", "sources": [{"id": "osm-1", "platform": "OpenStreetMap", "kind": "objective_reference", "title": "x", "url": "https://www.openstreetmap.org/way/1171637360", "accessed_at": "2026-10-22"}],
        "images": [], "status": "candidate",
    }]
    path = tmp_path / "attractions.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    result = import_legacy_catalog(ctx, path)
    assert result["created"] == 2
    svc = PlaceService(ctx)
    lead = svc.list_places(q="峨蔓")["items"][0]
    detail = svc.get_place(lead["id"])
    assert detail["needs_geographic_verification"] == 1 and detail["county"] == "儋州市"
    assert detail["sources"][0]["access_status"] == "link_only"
    assert detail["category"] == "viewpoint" and detail["discovery_reason"] == "user_import"
    tower = svc.get_place(svc.list_places(q="钟楼")["items"][0]["id"])
    assert tower["latitude"] == pytest.approx(20.0466062) and tower["coordinate_precision"] == "exact"
    # idempotent
    assert import_legacy_catalog(ctx, path)["created"] == 0


def test_csv_import_preview_and_apply(ctx, tmp_path):
    path = tmp_path / "places.csv"
    path.write_text("name,latitude,longitude,category,county,url\n莺歌嘴,18.5122,108.6901,cape,乐东,https://example.com/a\n坏行,abc,1,,,\n", encoding="utf-8")
    preview = import_csv(ctx, path, dry_run=True)
    assert preview["dry_run"] and len(preview["preview"]) == 1 and preview["errors"]
    assert PlaceService(ctx).list_places()["total"] == 0
    applied = import_csv(ctx, path, dry_run=False)
    assert applied["created"] == 1 and PlaceService(ctx).list_places()["total"] == 1


def test_corridor_import_sets_straight_line_distance(ctx, tmp_path):
    from hainan_explorer.services.ingest import Candidate, Ingestor

    pid = Ingestor(ctx).ingest(Candidate(provider="osm", external_id="node/1", name="测试点", latitude=19.0, longitude=110.1, category="beach")).place_id
    gpx = tmp_path / "route.gpx"
    gpx.write_text('<?xml version="1.0"?><gpx><trk><trkseg><trkpt lat="18.9" lon="110.0"/><trkpt lat="19.1" lon="110.0"/></trkseg></trk></gpx>', encoding="utf-8")
    result = import_corridor(ctx, gpx)
    assert result["points"] == 2 and result["places_updated"] == 1
    place = PlaceService(ctx).get_place(pid)
    assert 10 < place["route_distance_km"] < 11
    assert any("不是骑行距离" in f["note"] for f in place["facts"]["derived"] if f.get("note"))
