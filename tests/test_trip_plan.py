"""Phone trip page: plan parsing, catalog resolution, lodging anchoring and self-contained HTML output."""
from __future__ import annotations

import json
import re

import pytest

from hainan_explorer.services.ingest import Candidate, Ingestor
from hainan_explorer.services.routes import RouteService
from hainan_explorer.trip_plan import TripPlanBuilder, clean_attraction_label, parse_plan

PLAN = """day 0
降落海口，入住海口希尔顿酒店 滨海大道109-9号

每天到站后的骑行相关准备（做成checklist，有一键清零功能）
· 清洁链条杂物
· 需要充电的设备：手机，码表，车前灯x2

每天出发前的骑行相关准备（做成checklist，有一键清零功能）
· 安装车灯 码表 相机

day 1 海口 -> 博纵村
景点：
一日路边海滩看日落
无名小岛打卡
博纵村看日落

住宿：屿都·海拾光民宿(临高博纵村店)  博纵村博纵赶海渔家餐厅东北方向30米
补给：

day 2 博纵村 -> 海花岛
景点：
日出前出发，二日灯塔
住宿： 海花岛欧堡酒店 滨海大道海花岛1号岛
补给： 一号岛 赵一鸣
"""


def _gpx(name, points):
    body = "".join(f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele></trkpt>' for lat, lon, ele in points)
    return f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>{name}</name><trkseg>{body}</trkseg></trk></gpx>'


@pytest.fixture
def built(ctx, tmp_path):
    routes = tmp_path / "routes"
    routes.mkdir()
    (routes / "Day1.gpx").write_text(_gpx("Day1", [(19.0, 110.0, 10), (19.1, 110.0, 30), (19.2, 110.0, 12)]), encoding="utf-8")
    (routes / "Day2.gpx").write_text(_gpx("Day2", [(19.2, 110.0, 5), (19.2, 110.2, 5), (19.2, 110.4, 5)]), encoding="utf-8")
    RouteService(ctx).import_directory(routes, name="测试")
    ing = Ingestor(ctx)
    ing.ingest(Candidate(provider="osm", external_id="node/1", name="一日路边海滩", latitude=19.1, longitude=110.01, category="beach"))
    ing.ingest(Candidate(provider="osm", external_id="node/2", name="二日灯塔", latitude=19.23, longitude=110.3, category="lighthouse"))
    RouteService(ctx).recompute_positions()
    plan_path = tmp_path / "plan.txt"
    plan_path.write_text(PLAN, encoding="utf-8")
    hints = {
        "attractions": {"博纵村": "END", "无名小岛": []},
        "references": {"无名小岛": {"name": "参考渔村（OSM）", "lat": 19.15, "lon": 110.02, "source": "test"}},
        "lodging_refs": {"2": {"name": "海花岛参考", "lat": 19.5, "lon": 110.4, "source": "test"}},
    }
    builder = TripPlanBuilder(ctx, hints=hints)
    result = builder.build(plan_path, title="测试行程")
    html = (ctx.config.exports_dir / "trip-plan.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'const DATA = (\{.*?\});\s*\n', html, re.S).group(1).replace("<\\/", "</"))
    return result, html, data


def test_parse_plan_sections_and_checklists():
    plan = parse_plan(PLAN)
    assert plan["day0"]["lodging_raw"] == "海口希尔顿酒店 滨海大道109-9号"
    assert [d["day"] for d in plan["days"]] == [1, 2]
    d1, d2 = plan["days"]
    assert (d1["from"], d1["to"]) == ("海口", "博纵村")
    assert d1["attractions_raw"] == ["一日路边海滩看日落", "无名小岛打卡", "博纵村看日落"]
    assert d1["supplies_raw"] == [] and d2["supplies_raw"] == ["一号岛 赵一鸣"]
    assert d2["notes"] == ["日出前出发"] and d2["attractions_raw"] == ["二日灯塔"]
    arrival, departure = plan["checklists"]["arrival"], plan["checklists"]["departure"]
    assert [i["text"] for i in arrival] == ["清洁链条杂物", "需要充电的设备"]
    assert arrival[1]["sub"] == ["手机", "码表", "车前灯x2"] and arrival[1]["id"] == "a2"
    assert departure[0]["text"] == "安装车灯 码表 相机" and departure[0]["sub"] == ["安装车灯", "码表", "相机"]
    assert clean_attraction_label("鱼鳞洲看日落") == ("鱼鳞洲", "看日落")
    assert clean_attraction_label("好汉坡") == ("好汉坡", None)


def test_build_resolves_catalog_lodging_and_references(built):
    result, html, data = built
    assert result["days"] == 2 and result["attractions"] == 4 and result["attractions_located"] == 2
    d1, d2 = data["days"]
    # catalog match carries position along the day; sorted by km, unlocated/reference items last
    beach = d1["attractions"][0]
    assert beach["label"] == "一日路边海滩" and beach["note"] == "看日落" and beach["route_day"] == 1 and 11 < beach["km"] < 11.2 and beach["coord_source"] == "catalog"
    end = next(a for a in d1["attractions"] if a["label"] == "博纵村")
    assert end["coord_source"] == "route_end" and end["lat"] == pytest.approx(19.2) and end["km"] == d1["km"]
    island = next(a for a in d1["attractions"] if a["label"] == "无名小岛")
    assert island["reference"] == "参考渔村（OSM）" and island["coord_source"] == "reference" and island["km"] is None
    # lodging anchored on the route's day end; day 0 lodging on day 1 start
    assert d1["lodging"]["name"] == "屿都·海拾光民宿(临高博纵村店)" and d1["lodging"]["address"].startswith("博纵村")
    assert d1["lodging"]["coord_source"] == "route_end" and d1["lodging"]["lat"] == pytest.approx(19.2) and "warning" not in d1["lodging"]
    assert data["day0"]["lodging"]["name"] == "海口希尔顿酒店" and data["day0"]["lodging"]["lat"] == pytest.approx(19.0)
    # mismatch between route end and the lodging reference is reported, not hidden
    assert d2["lodging"]["warning"] and "海花岛参考" in d2["lodging"]["warning"] and result["lodging_warnings"]
    assert d2["supplies"] == [{"name": "一号岛 赵一鸣", "address": None, "lat": None, "lon": None}]
    assert d2["day_notes"] == ["日出前出发"]
    assert d2["attractions"][0]["label"] == "二日灯塔" and d2["attractions"][0]["route_day"] == 2
    assert len(d1["track"]) >= 2 and d1["track"][0] == [19.0, 110.0] and d1["climb_m"] == 20
    assert data["route_crs"] == "wgs84" and data["checklists"]["arrival"][1]["sub"] == ["手机", "码表", "车前灯x2"]


def test_html_is_self_contained(built):
    result, html, data = built
    assert "<script src=" not in html and '<link rel="stylesheet"' not in html
    assert "L.map" in html and "leaflet" in html.lower()
    assert "测试行程" in html and "一键清零" in html
    assert "basemaps.cartocdn.com" in html and "tianditu.gov.cn" in html  # basemap tiles are the only network dependency
    assert result["bytes"] > 100_000
