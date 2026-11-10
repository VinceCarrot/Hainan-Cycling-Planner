"""Build a self-contained, phone-friendly trip page from the user's manual plan.

Input: a plain-text plan (``manual_planning.txt``): ``day N A -> B`` headers with 景点 / 住宿 / 补给
sections, plus two checklists (到站后 / 出发前). Output: one HTML file with Leaflet inlined, the
route book (converted to WGS-84 so it sits on OpenStreetMap roads), per-day attractions resolved
against the catalog, lodging anchored on the route's day endpoints, and the checklists.

Nothing here invents coordinates: an attraction gets a position only from a catalog record, a
lodging only from the route book's start/end points, and anything else is marked "没有坐标" so the
user can pin it on the map themselves (stored in the phone's localStorage).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .geo import haversine_km, simplify_polyline
from .services.common import now_iso
from .services.context import AppContext
from .services.routes import RouteService

UI_DIR = Path(__file__).parent / "ui"
TEMPLATE = UI_DIR / "trip_template.html"
LEAFLET_CSS = UI_DIR / "static" / "vendor" / "leaflet.css"
LEAFLET_JS = UI_DIR / "static" / "vendor" / "leaflet.js"
HINTS_FILE = "trip_plan_hints.json"
OUTPUT_NAME = "trip-plan.html"
TRACK_TOLERANCE_KM = 0.02
LODGING_MISMATCH_KM = 2.0

_DAY_RE = re.compile(r"^day\s*(\d+)\s*(.*)$", re.IGNORECASE)
_ARROW_RE = re.compile(r"\s*(?:->|→|－>|—>|=>|－＞|->)\s*")
_BULLETS = ("·", "•", "-", "・", "*")
_ADDRESS_MARKERS = "路号镇村区市县街店方向米岛城湾园中心广场楼"
_SUFFIX_NOTES = ("看日落", "看日出", "打卡")
_PRECISION_RANK = {"exact": 0, "centroid": 1, "approximate": 2, None: 3}

DEFAULT_PREP = [
    {"title": "证件与预订", "items": ["身份证、少量现金，手机支付可用", "逐晚核对酒店预订（Day 0 到 Day 8 共 9 晚）", "把本页面和 9 天 GPX 存到手机"]},
    {"title": "自行车", "items": ["整车检查：刹车、变速、链条磨损、螺丝", "备胎 ×2、补胎片、撬胎棒、便携气泵", "链条油与抹布", "多功能工具、备用刹车片、备用变速线", "码表装好 9 天路书并在设备上逐天打开确认"]},
    {"title": "电子设备", "items": ["手机、全景相机、蓝牙快门、手表、码表、功率计、充电宝、气泵、耳机全部充满", "车前灯 ×2、车后灯 ×2 充满", "充电线、插排、相机存储卡清空"]},
    {"title": "骑行装备", "items": ["头盔、手套、骑行服 ×2、风衣或雨衣", "防晒霜、袖套、唇膏、太阳镜", "水壶 ×2", "急救包与常用药"]},
]

NOTES = {
    "route": "里程与爬升来自你的路书轨迹（Garmin Connect 导出），爬升按 5 m 滞回估算。景点的沿途公里与偏离距离是对轨迹的直线几何估算，不是导航里程。",
    "map": "路线已从 GCJ-02 转换为 WGS-84 显示，与底图道路对齐；底图需要联网，可在地图页“底图”里切换（国内建议天地图，需免费密钥）。",
    "prep": [
        "路书 GPX 由佳明中国网页版生成，坐标系为 GCJ-02。本页显示时已转换为 WGS-84 以便与 OSM 道路重合；原始 GPX 文件没有改动，码表直接使用原文件。",
        "Garmin Connect 导入含航点的 GPX 时对 course point 的处理因版本而异，出发前在 Connect 网页版打开路线核对。",
        "住宿位置按路书每天的起终点标注；笔记里的住宿与路书终点不一致的天数已在总览里提示，请以实际预订为准修改路书或笔记。",
        "没有坐标的点（部分景点、所有超市）可以在地图页手动标定，标定只保存在这台手机的浏览器里。",
        "底图：本地文件打开时 OpenStreetMap 官方瓦片会拒绝（浏览器不发送 Referer），默认改用 CARTO；在国内骑行时建议到 console.tianditu.gov.cn 申请免费密钥并在地图页“底图”里填入天地图。",
    ],
}


# ---------------------------------------------------------------- parsing
def _split_lodging(text: str) -> tuple[str, str | None]:
    text = text.strip()
    parts = re.split(r"\s{2,}", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    parts = text.split(None, 1)
    if len(parts) == 2 and any(ch in parts[1] for ch in _ADDRESS_MARKERS):
        return parts[0].strip(), parts[1].strip()
    return text, None


def _checklist_item(prefix: str, index: int, text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.match(r"^(.+?)[：:](.+)$", text)
    if m:
        sub = [s.strip() for s in re.split(r"[，,、]", m.group(2)) if s.strip()]
        return {"id": f"{prefix}{index}", "text": m.group(1).strip(), "sub": sub}
    # "安装车灯 码表 相机": several short things on one line become sub-items that can be ticked separately
    tokens = text.split()
    if len(tokens) > 1 and all(len(t) <= 6 for t in tokens):
        return {"id": f"{prefix}{index}", "text": text, "sub": tokens}
    return {"id": f"{prefix}{index}", "text": text, "sub": []}


def parse_plan(text: str) -> dict[str, Any]:
    plan: dict[str, Any] = {"day0": None, "days": [], "checklists": {"arrival": [], "departure": []}}
    current: dict[str, Any] | None = None
    section: str | None = None
    checklist: str | None = None
    for raw in text.splitlines():
        line = raw.strip().replace("﻿", "")
        m = _DAY_RE.match(line)
        if m:
            n = int(m.group(1))
            rest = m.group(2).strip()
            checklist = None
            section = None
            if n == 0:
                current = {"day": 0, "lodging_raw": None, "lines": []}
                plan["day0"] = current
            else:
                parts = _ARROW_RE.split(rest, maxsplit=1)
                current = {"day": n, "from": parts[0].strip() if parts and parts[0] else "", "to": parts[1].strip() if len(parts) > 1 else "",
                           "attractions_raw": [], "lodging_raw": None, "supplies_raw": [], "notes": []}
                plan["days"].append(current)
            continue
        if "到站后" in line and ("清单" in line or "checklist" in line.lower() or "准备" in line):
            checklist, current, section = "arrival", None, None
            continue
        if "出发前" in line and ("清单" in line or "checklist" in line.lower() or "准备" in line):
            checklist, current, section = "departure", None, None
            continue
        if checklist and line and line[0] in _BULLETS:
            items = plan["checklists"][checklist]
            items.append(_checklist_item("a" if checklist == "arrival" else "d", len(items) + 1, line[1:]))
            continue
        if current is None or not line:
            continue
        if current["day"] == 0:
            if "入住" in line:
                current["lodging_raw"] = line.split("入住", 1)[1].strip()
            current["lines"].append(line)
            continue
        sm = re.match(r"^(景点|住宿|补给)\s*[：:]\s*(.*)$", line)
        if sm:
            section = {"景点": "attractions", "住宿": "lodging", "补给": "supplies"}[sm.group(1)]
            value = sm.group(2).strip()
            if value:
                _add_section_value(current, section, value)
            continue
        if section:
            _add_section_value(current, section, line)
    return plan


def _add_section_value(day: dict[str, Any], section: str, value: str) -> None:
    if section == "attractions":
        for part in re.split(r"[，,]", value):
            part = part.strip()
            if not part:
                continue
            if "出发" in part and len(part) <= 12:
                day["notes"].append(part)
            else:
                day["attractions_raw"].append(part)
    elif section == "lodging":
        day["lodging_raw"] = value if not day["lodging_raw"] else day["lodging_raw"] + " " + value
    elif section == "supplies":
        day["supplies_raw"].append(value)


def clean_attraction_label(raw: str) -> tuple[str, str | None]:
    """'鱼鳞洲看日落' -> ('鱼鳞洲', '看日落')."""
    label = raw.strip()
    for suffix in _SUFFIX_NOTES:
        if label.endswith(suffix) and len(label) > len(suffix):
            return label[: -len(suffix)].strip(), suffix
    return label, None


# ---------------------------------------------------------------- resolving against the catalog
class TripPlanBuilder:
    def __init__(self, ctx: AppContext, hints: dict[str, Any] | None = None):
        self.ctx = ctx
        self.routes = RouteService(ctx)
        self.hints = hints if hints is not None else self._load_hints()

    def _load_hints(self) -> dict[str, Any]:
        path = self.ctx.config.data_dir / HINTS_FILE
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    # ---- catalog lookups
    def _rows_by_name(self, name: str, exact: bool) -> list[dict[str, Any]]:
        conn = self.ctx.db.conn()
        if exact:
            rows = conn.execute(
                """SELECT id, canonical_name, aliases_json, latitude, longitude, coordinate_precision, route_day, route_day_km, route_distance_km
                     FROM places WHERE merged_into_place_id IS NULL AND (canonical_name=? OR aliases_json LIKE ?)""",
                (name, f'%"{name}"%'),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, canonical_name, aliases_json, latitude, longitude, coordinate_precision, route_day, route_day_km, route_distance_km
                     FROM places WHERE merged_into_place_id IS NULL AND (canonical_name LIKE ? OR aliases_json LIKE ?)""",
                (f"%{name}%", f"%{name}%"),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _pick(rows: list[dict[str, Any]], day: int) -> dict[str, Any] | None:
        if not rows:
            return None
        rows = sorted(rows, key=lambda r: (
            r["latitude"] is None,
            0 if r["route_day"] == day else 1,
            _PRECISION_RANK.get(r["coordinate_precision"], 3),
            r["route_distance_km"] if r["route_distance_km"] is not None else 1e9,
        ))
        return rows[0]

    def resolve_attraction(self, raw: str, day: int, day_geo: dict[str, Any]) -> list[dict[str, Any]]:
        label, note = clean_attraction_label(raw)
        overrides = self.hints.get("attractions", {})
        references = self.hints.get("references", {})
        rule = overrides.get(raw, overrides.get(label))
        out: list[dict[str, Any]] = []

        def entry(lbl: str, row: dict[str, Any] | None) -> dict[str, Any]:
            e: dict[str, Any] = {"label": lbl, "raw": raw, "note": note}
            if row:
                e.update({"place_id": row["id"], "place_name": row["canonical_name"], "lat": row["latitude"], "lon": row["longitude"],
                          "precision": row["coordinate_precision"], "route_day": row["route_day"], "km": row["route_day_km"], "detour": row["route_distance_km"],
                          "coord_source": "catalog"})
            ref = references.get(lbl) or references.get(raw)
            if ref and (not row or row["latitude"] is None):
                e.update({"lat": ref["lat"], "lon": ref["lon"], "reference": ref["name"], "coord_source": "reference", "km": None, "detour": None, "route_day": None})
            return e

        if rule == "END" or rule == "START":
            pt = day_geo["end" if rule == "END" else "start"]
            e = entry(label, None)
            e.update({"lat": pt["lat"], "lon": pt["lon"], "coord_source": "route_end" if rule == "END" else "route_start",
                      "km": day_geo["km"] if rule == "END" else 0.0, "detour": 0.0, "route_day": day, "place_name": f"路书 Day {day} {'终点' if rule == 'END' else '起点'}"})
            return [e]
        if isinstance(rule, list):
            if not rule:
                return [entry(label, None)]
            for name in rule:
                out.append(entry(name if len(rule) > 1 else label, self._pick(self._rows_by_name(name, exact=True), day)))
            return out
        row = self._pick(self._rows_by_name(label, exact=True), day) or self._pick(self._rows_by_name(label, exact=False), day)
        return [entry(label, row)]

    # ---- build
    def build_data(self, plan: dict[str, Any], title: str) -> dict[str, Any]:
        segs = {s["day_number"]: s for s in self.routes.segments(include_geometry=True)}
        lodging_refs = self.hints.get("lodging_refs", {})
        days_out: list[dict[str, Any]] = []
        for d in plan["days"]:
            n = d["day"]
            seg = segs.get(n)
            geo = self._day_geo(seg)
            lodging = None
            if d["lodging_raw"]:
                name, address = _split_lodging(d["lodging_raw"])
                lodging = {"name": name, "address": address, "lat": geo["end"]["lat"] if geo["end"] else None, "lon": geo["end"]["lon"] if geo["end"] else None,
                           "coord_source": "route_end" if geo["end"] else None}
                ref = lodging_refs.get(str(n))
                if ref and geo["end"]:
                    gap = haversine_km(geo["end"]["lat"], geo["end"]["lon"], ref["lat"], ref["lon"])
                    lodging["ref"] = {"name": ref["name"], "lat": ref["lat"], "lon": ref["lon"], "source": ref.get("source", ""), "gap_km": round(gap, 1)}
                    if gap > LODGING_MISMATCH_KM:
                        lodging["warning"] = f"路书 Day {n} 终点距离笔记中的住宿参考点「{ref['name']}」约 {gap:.0f} km；请确认当天以路书终点还是以预订的住宿为准。"
            attractions: list[dict[str, Any]] = []
            for raw in d["attractions_raw"]:
                attractions.extend(self.resolve_attraction(raw, n, geo))
            attractions.sort(key=lambda a: (0 if (a.get("km") is not None and a.get("route_day") == n) else 1, a.get("km") if a.get("km") is not None else 1e9))
            supplies = []
            for raw in d["supplies_raw"]:
                name, address = _split_lodging(raw)
                supplies.append({"name": name, "address": address, "lat": None, "lon": None})
            days_out.append({
                "day": n, "from": d["from"], "to": d["to"], "km": geo["km"], "climb_m": geo["climb"], "start": geo["start"], "end": geo["end"],
                "track": geo["track"], "lodging": lodging, "supplies": supplies, "attractions": attractions, "day_notes": d["notes"],
            })
        day0 = None
        if plan["day0"] and plan["day0"]["lodging_raw"]:
            name, address = _split_lodging(plan["day0"]["lodging_raw"])
            first = days_out[0] if days_out else None
            day0 = {"lodging": {"name": name, "address": address, "lat": first["start"]["lat"] if first and first["start"] else None,
                                "lon": first["start"]["lon"] if first and first["start"] else None, "coord_source": "route_start"},
                    "lines": plan["day0"]["lines"]}
        return {
            "title": title, "generated_at": now_iso(), "route_version": self.routes.active_version(), "route_crs": self.routes.crs(),
            "day0": day0, "days": days_out, "checklists": plan["checklists"],
            "prep": [{"title": g["title"], "items": [{"id": f"p{gi}_{ii}", "text": t} for ii, t in enumerate(g["items"])]} for gi, g in enumerate(self.hints.get("prep", DEFAULT_PREP))],
            "notes": NOTES,
        }

    @staticmethod
    def _day_geo(seg: dict[str, Any] | None) -> dict[str, Any]:
        if not seg or not seg.get("geometry"):
            return {"km": None, "climb": None, "start": None, "end": None, "track": []}
        coords = seg["geometry"]["coordinates"]
        simplified = simplify_polyline([c[:2] for c in coords], TRACK_TOLERANCE_KM)
        return {
            "km": seg["distance_km"], "climb": seg["elevation_gain_m"],
            "start": {"lat": seg["start_lat"], "lon": seg["start_lon"]}, "end": {"lat": seg["end_lat"], "lon": seg["end_lon"]},
            "track": [[round(c[1], 5), round(c[0], 5)] for c in simplified],
        }

    def render(self, data: dict[str, Any]) -> str:
        template = TEMPLATE.read_text(encoding="utf-8")
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        html = template.replace("__TITLE__", _html_escape(data["title"]))
        html = html.replace("/*__LEAFLET_CSS__*/", LEAFLET_CSS.read_text(encoding="utf-8"))
        html = html.replace("/*__LEAFLET_JS__*/", LEAFLET_JS.read_text(encoding="utf-8"))
        return html.replace("/*__DATA__*/{}", payload)

    def build(self, plan_path: Path, *, out_path: Path | None = None, title: str | None = None) -> dict[str, Any]:
        plan = parse_plan(Path(plan_path).read_text(encoding="utf-8"))
        if not plan["days"]:
            raise ValueError(f"no 'day N' sections found in {plan_path}")
        data = self.build_data(plan, title or "海南环岛 路书")
        out = out_path or (self.ctx.config.exports_dir / OUTPUT_NAME)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.render(data), encoding="utf-8")
        located = sum(1 for d in data["days"] for a in d["attractions"] if a.get("lat") is not None and a.get("coord_source") == "catalog")
        total = sum(len(d["attractions"]) for d in data["days"])
        return {
            "path": str(out), "bytes": out.stat().st_size, "days": len(data["days"]), "attractions": total, "attractions_located": located,
            "lodging_warnings": [f"Day {d['day']}: {d['lodging']['warning']}" for d in data["days"] if d.get("lodging") and d["lodging"].get("warning")],
            "checklist_items": {k: len(v) for k, v in data["checklists"].items()},
        }


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
