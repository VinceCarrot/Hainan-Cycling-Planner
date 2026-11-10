"""Route book: per-day GPX import, place positioning, API filters/sorts and GPX export."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from hainan_explorer.geo import nearest_on_polyline_km, polyline_length_km, simplify_polyline
from hainan_explorer.main import create_app
from hainan_explorer.services.corridor import CorridorService
from hainan_explorer.services.importer import import_corridor
from hainan_explorer.services.ingest import Candidate, Ingestor
from hainan_explorer.services.places import PlaceService
from hainan_explorer.services.routes import RouteService, day_number_from_name, elevation_gain_m


def _gpx(name: str, points: list[tuple[float, float, float | None]]) -> str:
    body = "".join(
        f'<trkpt lat="{lat}" lon="{lon}">' + (f"<ele>{ele}</ele>" if ele is not None else "") + "</trkpt>" for lat, lon, ele in points
    )
    return f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>{name}</name></metadata><trk><name>{name}</name><trkseg>{body}</trkseg></trk></gpx>'


@pytest.fixture
def routes_dir(tmp_path):
    d = tmp_path / "data" / "routes"
    d.mkdir(parents=True)
    # Day 1 runs north along lon 110.0 from lat 19.0 to 19.2 (~22 km); Day 2 continues east along lat 19.2.
    (d / "环岛_Day1.gpx").write_text(_gpx("环岛 Day1", [(19.0, 110.0, 10), (19.1, 110.0, 30), (19.2, 110.0, 12)]), encoding="utf-8")
    (d / "环岛_Day2.gpx").write_text(_gpx("环岛 Day2", [(19.2, 110.0, None), (19.2, 110.2, None), (19.2, 110.4, None)]), encoding="utf-8")
    return d


@pytest.fixture
def places(ctx):
    ing = Ingestor(ctx)
    near_day1 = ing.ingest(Candidate(provider="osm", external_id="node/1", name="一日路边海滩", latitude=19.1, longitude=110.01, category="beach")).place_id
    near_day2 = ing.ingest(Candidate(provider="osm", external_id="node/2", name="二日灯塔", latitude=19.23, longitude=110.3, category="lighthouse")).place_id
    far = ing.ingest(Candidate(provider="osm", external_id="node/3", name="远处瀑布", latitude=18.6, longitude=109.5, category="waterfall")).place_id
    no_coords = ing.ingest(Candidate(provider="legacy_catalog", external_id="l1", name="无坐标", region_hint="临高县", category="village")).place_id
    return {"d1": near_day1, "d2": near_day2, "far": far, "none": no_coords}


@pytest.fixture
def client(ctx):
    with TestClient(create_app(ctx, start_worker=False)) as c:
        yield c


def test_geo_helpers_simplify_and_position():
    line = [[110.0, 19.0], [110.0, 19.05], [110.0001, 19.1], [110.0, 19.2]]
    simplified = simplify_polyline(line, 0.05)
    assert simplified[0] == line[0] and simplified[-1] == line[-1] and len(simplified) == 2
    dist, along = nearest_on_polyline_km(19.1, 110.01, line)
    assert 1.0 < dist < 1.1
    assert 11.0 < along < 11.2
    assert 22.1 < polyline_length_km(line) < 22.3
    assert day_number_from_name("海南环岛2026_Day7", 1) == 7
    assert day_number_from_name("ride.gpx", 3) == 3
    assert elevation_gain_m([[0, 0, 10.0], [0, 0, 12.0], [0, 0, 30.0], [0, 0, 5.0], [0, 0, 11.0]]) == 26
    assert elevation_gain_m([[0, 0], [0, 0]]) is None


def test_import_routes_assigns_days_and_replaces_corridor(ctx, routes_dir, places):
    result = RouteService(ctx).import_directory(routes_dir, name="测试路书")
    assert [d["day"] for d in result["days"]] == [1, 2]
    assert result["places_updated"] == 3
    svc = PlaceService(ctx)
    d1 = svc.get_place(places["d1"])
    assert d1["route_day"] == 1 and 11.0 < d1["route_day_km"] < 11.2 and 1.0 < d1["route_distance_km"] < 1.1
    assert any(f["label"] == "路书位置" and "Day 1" in f["value"] and "往返约" in f["value"] for f in d1["facts"]["derived"])
    d2 = svc.get_place(places["d2"])
    assert d2["route_day"] == 2 and 31 < d2["route_day_km"] < 33 and 3.2 < d2["route_distance_km"] < 3.4
    far = svc.get_place(places["far"])
    assert far["route_day"] == 1 and far["route_distance_km"] > 50
    assert svc.get_place(places["none"])["route_day"] is None

    corridor = CorridorService(ctx).active()
    assert corridor["version"] == result["version"] and corridor["is_estimated"] == 0 and "2 天" in corridor["name"]

    summary = RouteService(ctx).summary()
    assert summary["total_km"] == pytest.approx(result["total_km"], abs=0.1)
    assert summary["days"][0]["within_3km"] == 1 and summary["days"][1]["within_5km"] == 1
    assert summary["days"][0]["elevation_gain_m"] == 20 and summary["days"][1]["elevation_gain_m"] is None

    # Re-import is idempotent: same version replaces segments instead of duplicating them.
    again = RouteService(ctx).import_directory(routes_dir, name="测试路书", version=result["version"])
    assert len(RouteService(ctx).segments(again["version"])) == 2


def test_corridor_recompute_keeps_day_assignments_and_single_file_import_clears_them(ctx, routes_dir, places, tmp_path):
    RouteService(ctx).import_directory(routes_dir)
    assert CorridorService(ctx).recompute_distances() == 3
    assert PlaceService(ctx).get_place(places["d2"])["route_day"] == 2

    single = tmp_path / "single.gpx"
    single.write_text(_gpx("single", [(18.9, 110.0, None), (19.1, 110.0, None)]), encoding="utf-8")
    import_corridor(ctx, single)
    assert RouteService(ctx).active_version() is None
    assert PlaceService(ctx).get_place(places["d2"])["route_day"] is None
    assert PlaceService(ctx).get_place(places["d2"])["route_distance_km"] is not None


def test_api_day_filter_sorts_map_and_gpx_export(client, ctx, routes_dir, places):
    r = client.post("/api/import/routes?subdir=routes&name=测试路书")
    assert r.status_code == 200 and r.json()["places_updated"] == 3
    assert client.post("/api/import/routes?subdir=../outside").status_code == 404

    summary = client.get("/api/routes").json()
    assert [d["day"] for d in summary["days"]] == [1, 2] and "直线" in summary["distance_note"]
    geo = client.get("/api/routes/geojson").json()
    assert len(geo["features"]) == 2 and geo["features"][0]["properties"]["day"] == 1

    day1 = client.get("/api/places?day=1&sort=day_detour").json()
    assert [i["id"] for i in day1["items"]] == [places["d1"], places["far"]]
    day2 = client.get("/api/places?day=2&sort=day_km").json()
    assert [i["id"] for i in day2["items"]] == [places["d2"]]
    all_sorted = client.get("/api/places?sort=day_km&include_seeds=true&limit=100").json()["items"]
    days = [i["route_day"] for i in all_sorted]
    assert days == sorted(days, key=lambda v: (v is None, v or 0)) and None in days
    assert client.get("/api/map/places?day=2").json()["features"][0]["properties"]["route_day_km"] > 30

    client.post(f"/api/places/{places['d1']}/decision", json={"decision": "want_to_visit"})
    client.post(f"/api/places/{places['far']}/decision", json={"decision": "want_to_visit"})
    client.post(f"/api/places/{places['d2']}/decision", json={"decision": "maybe"})

    r = client.post("/api/export/gpx", json={"interest": ["want_to_visit", "maybe"], "max_detour_km": 5})
    assert r.status_code == 200
    files = r.json()["files"]
    assert len(files) == 2 and all(f["name"].startswith("route-") for f in files)
    text = client.get(files[0]["download_url"]).text
    root = ET.fromstring(text)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    wpts = root.findall("g:wpt", ns)
    assert [w.find("g:name", ns).text for w in wpts] == ["一日路边海滩"]  # the far waterfall exceeds max_detour_km
    assert "往返约" in wpts[0].find("g:desc", ns).text and wpts[0].find("g:sym", ns).text == "Flag, Green"
    assert len(root.findall("g:trk/g:trkseg/g:trkpt", ns)) == 3
    assert root.find("g:trk/g:trkseg/g:trkpt/g:ele", ns) is not None
    day2_text = client.get(files[1]["download_url"]).text
    assert "二日灯塔" in day2_text and "Flag, Yellow" in day2_text

    listed = client.get("/api/export/files").json()
    assert any(f["name"].endswith(".gpx") for f in listed)
    assert client.post("/api/export/gpx", json={"day": 9}).status_code == 400


# ---------------------------------------------------------------- coordinate systems
def test_crs_transforms_round_trip_and_offset_in_hainan():
    from hainan_explorer.crs import BD09, GCJ02, WGS84, convert_coords, from_wgs84, to_wgs84, validate_crs
    from hainan_explorer.geo import haversine_km

    lon, lat = 109.69, 19.92  # 临高角
    for crs in (GCJ02, BD09):
        glon, glat = from_wgs84(lon, lat, crs)
        offset_m = haversine_km(lat, lon, glat, glon) * 1000
        assert 100 < offset_m < 1500, (crs, offset_m)
        back = to_wgs84(glon, glat, crs)
        assert haversine_km(lat, lon, back[1], back[0]) * 1000 < 0.1  # BD-09 inverse is an approximation (~7 cm)
    assert to_wgs84(lon, lat, WGS84) == (lon, lat)
    assert convert_coords([[lon, lat, 12.0]], GCJ02)[0][2] == 12.0  # elevation preserved
    assert validate_crs(None) == WGS84 and validate_crs("GCJ-02") == GCJ02
    with pytest.raises(ValueError):
        validate_crs("mars")


def test_import_with_gcj02_converts_display_geometry_and_export_keeps_source(ctx, routes_dir, places):
    from hainan_explorer.crs import from_wgs84, to_wgs84

    svc = RouteService(ctx)
    wgs_result = svc.import_directory(routes_dir, name="测试路书")
    d1_wgs = PlaceService(ctx).get_place(places["d1"])["route_distance_km"]
    assert 1.0 < d1_wgs < 1.1

    result = svc.import_directory(routes_dir, name="测试路书", version=wgs_result["version"], crs="gcj02")
    assert result["crs"] == "gcj02" and svc.crs() == "gcj02"
    seg = svc.segments(include_geometry=True)[0]
    source_start = seg["source_geometry"]["coordinates"][0]
    display_start = seg["geometry"]["coordinates"][0]
    assert source_start[:2] == [110.0, 19.0]  # the GPX coordinates are stored verbatim
    expected = to_wgs84(110.0, 19.0, "gcj02")
    assert display_start[0] == pytest.approx(expected[0], abs=1e-6) and display_start[1] == pytest.approx(expected[1], abs=1e-6)
    assert (seg["start_lon"], seg["start_lat"]) == (display_start[0], display_start[1])
    # The corridor, GeoJSON and place detours all follow the converted geometry.
    assert CorridorService(ctx).active()["geometry"]["coordinates"][0][0] == pytest.approx(expected[0], abs=1e-6)
    assert svc.geojson()["features"][0]["geometry"]["coordinates"][0][0] == pytest.approx(expected[0], abs=1e-6)
    d1_gcj = PlaceService(ctx).get_place(places["d1"])["route_distance_km"]
    assert abs(d1_gcj - d1_wgs) > 0.1
    summary = svc.summary()
    assert summary["crs"] == "gcj02" and "GCJ-02" in summary["crs_label"] and summary["crs_note"]

    # Switching back re-derives everything from the stored source coordinates.
    back = svc.set_crs("wgs84")
    assert back["crs"] == "wgs84" and back["places_updated"] == 3
    assert PlaceService(ctx).get_place(places["d1"])["route_distance_km"] == d1_wgs
    assert svc.segments(include_geometry=True)[0]["geometry"]["coordinates"][0][:2] == [110.0, 19.0]
    assert svc.summary()["crs_note"] is None

    # Export in GCJ-02: the track keeps the original numbers, waypoints are converted to match.
    svc.set_crs("gcj02")
    ctx_place = PlaceService(ctx).get_place(places["d1"])
    with ctx.db.transaction() as conn:
        conn.execute("UPDATE places SET interest_status='want_to_visit' WHERE id=?", (places["d1"],))
    path = svc.export_gpx(day=1)[0]
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    first = root.find("g:trk/g:trkseg/g:trkpt", ns)
    assert (first.attrib["lat"], first.attrib["lon"]) == ("19.000000", "110.000000")
    wpt = root.find("g:wpt", ns)
    glon, glat = from_wgs84(ctx_place["longitude"], ctx_place["latitude"], "gcj02")
    assert float(wpt.attrib["lat"]) == pytest.approx(glat, abs=1e-6) and float(wpt.attrib["lon"]) == pytest.approx(glon, abs=1e-6)
    assert "GCJ-02" in root.find("g:metadata/g:desc", ns).text


def test_api_route_crs(client, routes_dir, places):
    r = client.post("/api/import/routes?subdir=routes&crs=gcj02")
    assert r.status_code == 200 and r.json()["crs"] == "gcj02"
    assert client.get("/api/routes").json()["crs"] == "gcj02"
    detour_gcj = client.get(f"/api/places/{places['d1']}").json()["route_distance_km"]
    r = client.post("/api/routes/crs", json={"crs": "wgs84"})
    assert r.status_code == 200 and r.json()["places_updated"] == 3
    assert client.get(f"/api/places/{places['d1']}").json()["route_distance_km"] != detour_gcj
    assert client.post("/api/routes/crs", json={"crs": "mars"}).status_code == 422
    assert client.post("/api/import/routes?subdir=routes&crs=mars").status_code == 422


def test_position_place_assigns_single_place_after_research_style_update(ctx, routes_dir, places):
    svc = RouteService(ctx)
    assert svc.position_place(places["d2"]) is None  # no route book yet -> caller falls back to the corridor
    svc.import_directory(routes_dir)
    with ctx.db.transaction() as conn:
        conn.execute("UPDATE places SET latitude=19.2, longitude=110.3 WHERE id=?", (places["none"],))
    pos = svc.position_place(places["none"])
    assert pos["route_day"] == 2 and 31 < pos["route_day_km"] < 33 and pos["route_distance_km"] < 0.1
    assert PlaceService(ctx).get_place(places["none"])["route_day"] == 2


def test_nominatim_hit_compatibility_guard():
    from hainan_explorer.pipelines import nominatim_hit_compatible

    station = {"category": "railway", "type": "station"}
    assert not nominatim_hit_compatible("bay", station)
    assert not nominatim_hit_compatible("beach", {"class": "building", "type": "train_station"})
    assert nominatim_hit_compatible("transport", station)
    assert nominatim_hit_compatible("bay", {"category": "natural", "type": "bay"})
    assert nominatim_hit_compatible(None, {"category": "place", "type": "village"})


def test_manual_coordinates_via_api_position_the_place_on_the_route(client, routes_dir, places):
    assert client.post("/api/import/routes?subdir=routes").status_code == 200
    r = client.patch(f"/api/places/{places['none']}", json={"latitude": 19.2, "longitude": 110.3})
    assert r.status_code == 200
    body = r.json()
    assert body["route_day"] == 2 and 31 < body["route_day_km"] < 33 and body["route_distance_km"] < 0.1
    assert any(f["label"] == "路书位置" for f in body["facts"]["derived"])
