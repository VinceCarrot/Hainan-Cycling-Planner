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
· 组装自行车
· 充电：手机，码表

每天到站后的骑行相关准备（做成checklist）
· 清洁链条杂物
· 需要充电的设备：
    手机，码表，
    车前灯x2

睡觉前 checklist
· 定闹钟

每天出发前的骑行相关准备（做成checklist）
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
    assert [(i["text"], i["sub"]) for i in plan["day0"]["items"]] == [("组装自行车", []), ("充电", ["手机", "码表"])]
    assert [d["day"] for d in plan["days"]] == [1, 2]
    d1, d2 = plan["days"]
    assert (d1["from"], d1["to"]) == ("海口", "博纵村")
    assert d1["attractions_raw"] == ["一日路边海滩看日落", "无名小岛打卡", "博纵村看日落"]
    assert d1["supplies_raw"] == [] and d2["supplies_raw"] == ["一号岛 赵一鸣"]
    assert d2["notes"] == ["日出前出发"] and d2["attractions_raw"] == ["二日灯塔"]
    assert [(c["kind"], c["short"]) for c in plan["checklists"]] == [("arrival", "到站后"), ("bedtime", "睡觉前"), ("departure", "出发前")]
    arrival, bedtime, departure = (c["items"] for c in plan["checklists"])
    assert [i["text"] for i in arrival] == ["清洁链条杂物", "需要充电的设备"]
    assert arrival[1]["sub"] == ["手机", "码表", "车前灯x2"] and arrival[1]["id"] == "a2"  # indented continuation lines
    assert bedtime[0]["text"] == "定闹钟" and bedtime[0]["id"] == "b1"
    assert departure[0]["text"] == "安装车灯 码表 相机" and departure[0]["sub"] == ["安装车灯", "码表", "相机"]
    assert plan["checklists"][0]["title"] == "每天到站后的骑行相关准备"
    assert clean_attraction_label("鱼鳞洲看日落") == ("鱼鳞洲", "看日落")
    assert clean_attraction_label("好汉坡") == ("好汉坡", None)


def test_parse_departure_prep_as_nested_checklist():
    plan = parse_plan("""出发前：

出发时的行李准备：
1. 随车行李：
自行车及配件：
    大行K9
    工具包（棘轮扳手，撬胎棒）

洗漱用品：
    毛巾

2. 寄存在海口的行李：
电子产品：
    笔记本电脑

day 0
降落海口，入住酒店
""")
    departure = plan["departure_prep"]
    assert departure["title"] == "出发前准备"
    root = departure["items"][0]
    assert root["text"] == "出发时的行李准备"
    carry, stored = root["children"]
    assert carry["text"] == "随车行李"
    bike, toiletries = carry["children"]
    assert bike["text"] == "自行车及配件"
    assert [item["text"] for item in bike["children"]] == ["大行K9", "工具包（棘轮扳手，撬胎棒）"]
    assert [item["text"] for item in toiletries["children"]] == ["毛巾"]
    assert stored["text"] == "寄存在海口的行李"
    assert stored["children"][0]["children"][0]["text"] == "笔记本电脑"
    assert len({node["id"] for node in [root, carry, bike, *bike["children"], toiletries, *toiletries["children"], stored]}) == 8


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
    assert data["route_crs"] == "wgs84" and data["checklists"][0]["items"][1]["sub"] == ["手机", "码表", "车前灯x2"]
    assert result["checklist_items"] == {"arrival": 2, "bedtime": 1, "departure": 1}
    assert data["day0_prep"]["from_plan"] is True and data["day0_prep"]["items"][1]["id"] == "z2"


def test_html_is_self_contained(built):
    result, html, data = built
    assert "<script src=" not in html and '<link rel="stylesheet"' not in html
    assert "L.map" in html and "leaflet" in html.lower()
    assert "测试行程" in html and "反选" in html and "出发前准备" in html
    assert "一键清零" not in html
    assert "data-tree" in html and "tree-children" in html and "tree-leaf" in html and "tree-leaves" in html
    assert "怎么用" not in html and "路书与设备" not in html
    assert "清单内容来自 manual_planning.txt，修改后重新生成本页即可。" not in html
    assert 'id="save-html"' in html and 'data-edit-action="${active ? "cancel" : "start"}"' in html
    assert "add-tree-child" in html and "add-check-sub" in html and "editable.checklists" in html
    assert 'const filename = "trip-plan.html"' in html
    assert "server.arcgisonline.com" in html
    assert "tianditu.gov.cn" not in html and "tdt-key" not in html
    assert "basemaps.cartocdn.com" not in html
    assert result["bytes"] > 100_000
