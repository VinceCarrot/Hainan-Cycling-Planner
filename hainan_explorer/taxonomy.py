"""Place category taxonomy and mapping from provider tags / free text to categories."""
from __future__ import annotations

CATEGORIES: dict[str, dict[str, str | bool | float]] = {
    # key: label_zh, coastal?, interest weight for discovery score
    "beach": {"zh": "沙滩", "coastal": True, "weight": 1.0},
    "bay": {"zh": "海湾", "coastal": True, "weight": 1.0},
    "cape": {"zh": "海角/岬角", "coastal": True, "weight": 1.2},
    "reef": {"zh": "礁石/珊瑚礁", "coastal": True, "weight": 1.2},
    "cliff": {"zh": "海蚀崖/悬崖", "coastal": True, "weight": 1.2},
    "island": {"zh": "岛屿", "coastal": True, "weight": 1.0},
    "coast": {"zh": "海岸", "coastal": True, "weight": 1.0},
    "wetland": {"zh": "湿地/红树林", "coastal": True, "weight": 1.0},
    "lighthouse": {"zh": "灯塔", "coastal": True, "weight": 1.3},
    "harbor": {"zh": "渔港/码头", "coastal": True, "weight": 1.0},
    "fishing_village": {"zh": "渔村", "coastal": True, "weight": 1.2},
    "salt_field": {"zh": "盐田", "coastal": True, "weight": 1.2},
    "village": {"zh": "村落", "coastal": False, "weight": 0.6},
    "historic_village": {"zh": "古村落", "coastal": False, "weight": 1.2},
    "old_town": {"zh": "古镇/老街", "coastal": False, "weight": 1.0},
    "temple": {"zh": "寺庙/祠堂", "coastal": False, "weight": 0.8},
    "historic": {"zh": "历史遗迹", "coastal": False, "weight": 1.0},
    "fort": {"zh": "炮台/城堡", "coastal": False, "weight": 1.2},
    "archaeological": {"zh": "考古遗址", "coastal": False, "weight": 1.1},
    "memorial": {"zh": "纪念地", "coastal": False, "weight": 0.7},
    "museum": {"zh": "博物馆", "coastal": False, "weight": 0.7},
    "architecture": {"zh": "特色建筑", "coastal": False, "weight": 1.0},
    "peak": {"zh": "山峰", "coastal": False, "weight": 1.0},
    "mountain": {"zh": "山地", "coastal": False, "weight": 0.9},
    "forest": {"zh": "森林/雨林", "coastal": False, "weight": 1.0},
    "nature_reserve": {"zh": "自然保护区", "coastal": False, "weight": 1.0},
    "waterfall": {"zh": "瀑布", "coastal": False, "weight": 1.3},
    "river": {"zh": "河流/溪谷", "coastal": False, "weight": 0.8},
    "lake": {"zh": "湖泊", "coastal": False, "weight": 0.9},
    "reservoir": {"zh": "水库", "coastal": False, "weight": 0.9},
    "hot_spring": {"zh": "温泉", "coastal": False, "weight": 1.0},
    "cave": {"zh": "洞穴", "coastal": False, "weight": 1.2},
    "geological": {"zh": "地质景观", "coastal": False, "weight": 1.3},
    "volcano": {"zh": "火山", "coastal": False, "weight": 1.3},
    "viewpoint": {"zh": "观景点", "coastal": False, "weight": 1.2},
    "park": {"zh": "公园", "coastal": False, "weight": 0.6},
    "garden": {"zh": "植物园/庄园", "coastal": False, "weight": 0.7},
    "attraction": {"zh": "景点", "coastal": False, "weight": 0.8},
    "artwork": {"zh": "艺术/雕塑", "coastal": False, "weight": 0.8},
    "bridge": {"zh": "桥梁", "coastal": False, "weight": 0.6},
    "farm": {"zh": "农场/种植园", "coastal": False, "weight": 0.8},
    "cultural": {"zh": "民族文化", "coastal": False, "weight": 0.9},
    "theme_park": {"zh": "主题乐园", "coastal": False, "weight": 0.4},
    "settlement": {"zh": "城镇/乡镇", "coastal": False, "weight": 0.3},
    "transport": {"zh": "交通/港口", "coastal": False, "weight": 0.4},
    "other": {"zh": "其他", "coastal": False, "weight": 0.5},
    "unknown": {"zh": "未分类", "coastal": False, "weight": 0.5},
}

CATEGORY_LABELS_ZH = {k: str(v["zh"]) for k, v in CATEGORIES.items()}


def category_weight(key: str) -> float:
    return float(CATEGORIES.get(key, CATEGORIES["unknown"])["weight"])


def category_is_coastal(key: str) -> bool:
    return bool(CATEGORIES.get(key, CATEGORIES["unknown"])["coastal"])


# --- OSM tag mapping ---------------------------------------------------------
# Ordered: first match wins. (key, value or None for any) -> category
OSM_TAG_RULES: list[tuple[str, str | None, str]] = [
    ("man_made", "lighthouse", "lighthouse"),
    ("natural", "beach", "beach"),
    ("natural", "bay", "bay"),
    ("natural", "cape", "cape"),
    ("natural", "reef", "reef"),
    ("natural", "cliff", "cliff"),
    ("natural", "wetland", "wetland"),
    ("wetland", None, "wetland"),
    ("natural", "peak", "peak"),
    ("natural", "volcano", "volcano"),
    ("natural", "cave_entrance", "cave"),
    ("natural", "hot_spring", "hot_spring"),
    ("natural", "spring", "hot_spring"),
    ("natural", "waterfall", "waterfall"),
    ("waterway", "waterfall", "waterfall"),
    ("natural", "rock", "geological"),
    ("natural", "stone", "geological"),
    ("natural", "arch", "geological"),
    ("geological", None, "geological"),
    ("natural", "water", "lake"),
    ("water", "reservoir", "reservoir"),
    ("landuse", "reservoir", "reservoir"),
    ("natural", "wood", "forest"),
    ("landuse", "forest", "forest"),
    ("natural", "coastline", "coast"),
    ("natural", "shoal", "coast"),
    ("natural", "sand", "beach"),
    ("natural", "dune", "beach"),
    ("place", "island", "island"),
    ("place", "islet", "island"),
    ("tourism", "viewpoint", "viewpoint"),
    ("tourism", "museum", "museum"),
    ("tourism", "artwork", "artwork"),
    ("tourism", "theme_park", "theme_park"),
    ("tourism", "zoo", "theme_park"),
    ("tourism", "aquarium", "theme_park"),
    ("tourism", "attraction", "attraction"),
    ("tourism", "picnic_site", "park"),
    ("tourism", "camp_site", "park"),
    ("historic", "archaeological_site", "archaeological"),
    ("historic", "fort", "fort"),
    ("historic", "castle", "fort"),
    ("historic", "city_gate", "historic"),
    ("historic", "memorial", "memorial"),
    ("historic", "monument", "memorial"),
    ("historic", "ruins", "historic"),
    ("historic", "tomb", "historic"),
    ("historic", "temple", "temple"),
    ("historic", "building", "architecture"),
    ("historic", None, "historic"),
    ("heritage", None, "historic"),
    ("amenity", "place_of_worship", "temple"),
    ("building", "temple", "temple"),
    ("boundary", "protected_area", "nature_reserve"),
    ("boundary", "national_park", "nature_reserve"),
    ("leisure", "nature_reserve", "nature_reserve"),
    ("leisure", "park", "park"),
    ("leisure", "garden", "garden"),
    ("leisure", "beach_resort", "beach"),
    ("man_made", "pier", "harbor"),
    ("man_made", "breakwater", "harbor"),
    ("harbour", None, "harbor"),
    ("landuse", "harbour", "harbor"),
    ("landuse", "salt_pond", "salt_field"),
    ("man_made", "tower", "architecture"),
    ("man_made", "water_tower", "architecture"),
    ("man_made", "windmill", "architecture"),
    ("man_made", "bridge", "bridge"),
    ("bridge", None, "bridge"),
    ("landuse", "farmland", "farm"),
    ("landuse", "orchard", "farm"),
    ("landuse", "plantation", "farm"),
    ("place", "village", "village"),
    ("place", "hamlet", "village"),
    ("place", "locality", "other"),
    ("place", "town", "settlement"),
    ("place", "suburb", "settlement"),
    ("place", "neighbourhood", "settlement"),
    ("amenity", "ferry_terminal", "transport"),
]


def category_from_osm_tags(tags: dict[str, str]) -> str:
    for key, value, category in OSM_TAG_RULES:
        actual = tags.get(key)
        if actual is None:
            continue
        if value is None or actual == value:
            return category
    return "unknown"


# --- Wikidata P31 (instance of) mapping ---------------------------------------
WIKIDATA_CLASS_RULES: dict[str, str] = {
    "Q40080": "beach", "Q39816": "bay", "Q17018380": "bay", "Q185113": "cape", "Q191992": "cape",
    "Q184358": "reef", "Q107679": "reef", "Q924946": "cliff", "Q107425": "coast", "Q23442": "island",
    "Q207524": "island", "Q170321": "wetland", "Q4421": "forest", "Q39594": "lighthouse",
    "Q44782": "harbor", "Q283202": "harbor", "Q532": "village", "Q5084": "village", "Q3957": "settlement",
    "Q515": "settlement", "Q15284": "settlement", "Q123705": "settlement", "Q702492": "settlement",
    "Q13220204": "settlement", "Q735428": "settlement", "Q1348006": "settlement", "Q14350": "settlement",
    "Q11563757": "settlement", "Q1210950": "settlement", "Q22699": "settlement",
    "Q44539": "temple", "Q1370598": "temple", "Q16970": "temple", "Q845945": "temple", "Q5393308": "temple",
    "Q11755880": "temple", "Q2231525": "temple", "Q3947": "architecture", "Q41176": "architecture",
    "Q839954": "archaeological", "Q57821": "fort", "Q23413": "fort", "Q1785071": "fort", "Q5003624": "memorial",
    "Q4989906": "memorial", "Q33506": "museum", "Q8502": "peak", "Q46831": "mountain", "Q1437459": "mountain",
    "Q34038": "waterfall", "Q4022": "river", "Q23397": "lake", "Q131681": "reservoir", "Q177380": "hot_spring",
    "Q35509": "cave", "Q8072": "volcano", "Q169358": "geological", "Q1055216": "geological", "Q473972": "nature_reserve",
    "Q46169": "nature_reserve", "Q22698": "park", "Q22746": "park", "Q570116": "attraction", "Q1200957": "attraction",
    "Q2416723": "theme_park", "Q43501": "theme_park", "Q12280": "bridge", "Q1129743": "bridge",
    "Q39614": "historic", "Q15024900": "historic", "Q3303557": "historic", "Q16622264": "historic",
    "Q1370595": "historic", "Q7563": "historic", "Q575759": "memorial", "Q2007068": "architecture",
    "Q1497364": "architecture", "Q274153": "garden", "Q167346": "garden", "Q188509": "settlement",
    "Q188040": "farm", "Q1021645": "cultural", "Q188913": "harbor", "Q2175765": "harbor",
    "Q355304": "river", "Q47521": "river", "Q1322134": "bay", "Q159719": "wetland", "Q2042028": "peak",
    "Q24056001": "settlement", "Q1073094": "settlement", "Q21869758": "settlement",
    "Q13100073": "village", "Q17343829": "settlement", "Q1172138": "settlement", "Q11828004": "cultural",
}


def category_from_wikidata_classes(class_ids: list[str]) -> str:
    for cid in class_ids:
        if cid in WIKIDATA_CLASS_RULES:
            return WIKIDATA_CLASS_RULES[cid]
    return "unknown"


# --- Free-text keyword mapping (legacy catalogue categories, Wikipedia extracts) -
KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("灯塔",), "lighthouse"),
    (("盐田", "盐场"), "salt_field"),
    (("渔村",), "fishing_village"),
    (("渔港", "码头", "港口", "港"), "harbor"),
    (("古村", "古村落"), "historic_village"),
    (("古镇", "老街", "古城", "骑楼"), "old_town"),
    (("瀑布",), "waterfall"),
    (("温泉",), "hot_spring"),
    (("火山",), "volcano"),
    (("溶洞", "洞穴", "海蚀洞", "洞"), "cave"),
    (("地质", "地貌", "礁石", "海蚀", "石头", "红石", "岩"), "geological"),
    (("珊瑚", "礁"), "reef"),
    (("岬", "海角", "角"), "cape"),
    (("观景台", "观景点", "观海", "观山", "观景"), "viewpoint"),
    (("湿地", "红树林"), "wetland"),
    (("沙滩", "海滩", "滩"), "beach"),
    (("海湾", "湾"), "bay"),
    (("离岛", "海岛", "岛", "洲"), "island"),
    (("寺", "庙", "祠", "殿", "孔庙", "书院"), "temple"),
    (("炮台", "城堡", "堡"), "fort"),
    (("遗址", "遗迹", "古", "历史", "旧址", "祖居", "故居", "井"), "historic"),
    (("博物馆", "展馆", "科普中心"), "museum"),
    (("纪念", "公墓", "烈士"), "memorial"),
    (("雨林", "森林", "林"), "forest"),
    (("保护区",), "nature_reserve"),
    (("山峰", "岭", "山", "峡谷"), "mountain"),
    (("河", "溪", "江"), "river"),
    (("湖",), "lake"),
    (("水库",), "reservoir"),
    (("植物园", "庄园", "花园"), "garden"),
    (("公园", "绿道", "广场"), "park"),
    (("桥",), "bridge"),
    (("黎族", "苗族", "民族", "文化", "侨"), "cultural"),
    (("乐园", "欢乐世界", "度假区", "免税", "购物"), "theme_park"),
    (("农场", "种植", "椰林", "咖啡", "茶园"), "farm"),
    (("海岸", "海", "滨海"), "coast"),
    (("村",), "village"),
    (("镇", "乡"), "settlement"),
    (("景区", "景点", "风景", "游览区", "旅游区"), "attraction"),
]


def category_from_text(text: str | None) -> str:
    if not text:
        return "unknown"
    for keywords, category in KEYWORD_RULES:
        if any(k in text for k in keywords):
            return category
    return "unknown"


# Query seeds per category used for Overpass discovery. Each entry: (label, overpass filter list)
OSM_DISCOVERY_QUERIES: dict[str, list[str]] = {
    "coast_features": [
        '["natural"~"^(beach|bay|cape|reef|cliff|shoal|sand|dune|arch)$"]',
        '["place"~"^(island|islet)$"]',
    ],
    "water_and_land": [
        '["natural"~"^(wetland|peak|volcano|cave_entrance|hot_spring|spring|waterfall|rock|stone|wood)$"]',
        '["waterway"="waterfall"]',
        '["geological"]',
        '["water"="reservoir"]["name"]',
        '["natural"="water"]["name"]',
    ],
    "tourism": [
        '["tourism"~"^(attraction|viewpoint|museum|artwork|picnic_site|camp_site|theme_park|zoo|aquarium)$"]',
    ],
    "historic": [
        '["historic"]',
        '["heritage"]',
        '["amenity"="place_of_worship"]["name"]',
    ],
    "infrastructure": [
        '["man_made"~"^(lighthouse|pier|tower|water_tower|windmill|breakwater)$"]',
        '["landuse"~"^(salt_pond|harbour)$"]',
        '["harbour"]["name"]',
        '["amenity"="ferry_terminal"]',
    ],
    "protected_and_parks": [
        '["leisure"~"^(nature_reserve|park|garden|beach_resort)$"]["name"]',
        '["boundary"~"^(protected_area|national_park)$"]',
    ],
    "settlements": [
        '["place"~"^(village|hamlet|locality)$"]["name"]',
    ],
}
