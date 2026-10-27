from hainan_explorer import geo
from hainan_explorer.normalize import (
    best_name_match,
    contains_name,
    core_name,
    name_variants,
    normalize_name,
    similarity,
    strip_region_prefix,
)
from hainan_explorer.regions import REGIONS, assemble_rings, region_from_text
from hainan_explorer.taxonomy import category_from_osm_tags, category_from_text, category_from_wikidata_classes


def test_normalize_handles_width_case_punctuation_and_traditional():
    assert normalize_name("  Tónggǔ 岭 ") == "tónggǔ岭"
    assert normalize_name("萬寧·石梅灣") == "万宁石梅湾"
    assert normalize_name("（东郊）椰林 风景区") == "东郊椰林风景区"


def test_core_name_strips_region_prefix_and_generic_suffix():
    assert strip_region_prefix("儋州东坡书院") == "东坡书院"
    assert strip_region_prefix("海南") == "海南"  # never empty
    assert core_name("儋州东坡书院景区") == "东坡书院"
    assert core_name("棋子湾大角公园") == "棋子湾大角"


def test_name_variants_include_prefix_stripped_and_split_parts():
    variants = name_variants("陵水虎岭与尖岭海岸", ["Huling"])
    assert "虎岭与尖岭海岸" in variants
    assert "虎岭" in variants and "尖岭海岸" in variants
    assert "Huling" in variants


def test_similarity_and_best_match():
    assert similarity("东坡书院", "东坡书院") == 100
    assert similarity("铜鼓岭", "铜鼓岭景区") > 70
    name, score = best_name_match("文昌铜鼓岭", ["铜鼓岭", "石头公园"])
    assert name == "铜鼓岭" and score > 60


def test_contains_name_uses_core_name():
    assert contains_name("Tonggu Ridge view 铜鼓岭 from the sea", "文昌铜鼓岭景区")
    assert not contains_name("Haikou clock tower", "铜鼓岭")


def test_region_from_text_and_route_order():
    assert region_from_text("海南省儋州市白马井镇").key == "danzhou"
    assert region_from_text("陵水").key == "lingshui"
    assert region_from_text("北京") is None
    assert [r.key for r in REGIONS][:4] == ["haikou", "chengmai", "lingao", "danzhou"]


def test_assemble_rings_joins_ways_in_any_direction():
    w1 = [[0, 0], [1, 0]]
    w2 = [[1, 1], [1, 0]]  # reversed direction
    w3 = [[1, 1], [0, 1], [0, 0]]
    rings = assemble_rings([w1, w2, w3])
    assert len(rings) == 1
    assert rings[0][0] == rings[0][-1]
    assert len(rings[0]) == 5


def test_point_in_geometry_and_haversine():
    square = {"type": "Polygon", "coordinates": [[[109, 19], [110, 19], [110, 20], [109, 20], [109, 19]]]}
    assert geo.point_in_geometry(19.5, 109.5, square)
    assert not geo.point_in_geometry(20.5, 109.5, square)
    assert abs(geo.haversine_km(20.0, 110.0, 20.0, 111.0) - 104.6) < 1.0


def test_distance_to_polyline_is_straight_line_only():
    line = [[110.0, 19.0], [110.0, 20.0]]
    d = geo.distance_to_polyline_km(19.5, 110.1, line)
    assert 10.0 < d < 11.0
    assert geo.distance_to_geometry_km(19.5, 110.1, {"type": "LineString", "coordinates": line}) == d


def test_grid_points_cover_bbox():
    pts = geo.grid_points((18.1, 108.55, 20.18, 111.1), 50)
    assert 15 <= len(pts) <= 40
    assert all(18.1 <= lat <= 20.18 and 108.55 <= lon <= 111.1 for lat, lon in pts)


def test_taxonomy_mappings():
    assert category_from_osm_tags({"man_made": "lighthouse", "name": "x"}) == "lighthouse"
    assert category_from_osm_tags({"natural": "beach"}) == "beach"
    assert category_from_osm_tags({"place": "village"}) == "village"
    assert category_from_osm_tags({"shop": "bakery"}) == "unknown"
    assert category_from_wikidata_classes(["Q5", "Q39594"]) == "lighthouse"
    assert category_from_text("乐东莺歌海盐场") == "salt_field"
    assert category_from_text("小众海岸与海蚀洞") == "cave"
