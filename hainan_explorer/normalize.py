"""Name normalization and alias matching (conservative, explainable)."""
from __future__ import annotations

import re
import unicodedata

try:  # optional dependency; fallback to difflib
    from rapidfuzz import fuzz as _fuzz
except Exception:  # pragma: no cover
    _fuzz = None
import difflib

# Administrative prefixes commonly glued onto place names in travelogues.
REGION_PREFIXES = (
    "海南省", "海南", "海口市", "海口", "三亚市", "三亚", "儋州市", "儋州", "文昌市", "文昌",
    "琼海市", "琼海", "万宁市", "万宁", "东方市", "东方", "五指山市", "五指山",
    "定安县", "定安", "屯昌县", "屯昌", "澄迈县", "澄迈", "临高县", "临高",
    "白沙黎族自治县", "白沙", "昌江黎族自治县", "昌江", "乐东黎族自治县", "乐东",
    "陵水黎族自治县", "陵水", "保亭黎族苗族自治县", "保亭", "琼中黎族苗族自治县", "琼中",
)

# Generic suffixes that do not change identity ("X景区" ~ "X").
GENERIC_SUFFIXES = (
    "旅游度假区", "国家森林公园", "国家级自然保护区", "自然保护区", "风景名胜区", "旅游区",
    "风景区", "景区", "度假区", "游览区", "观景台", "观景点", "公园", "海滩", "沙滩", "海湾", "村",
)

_PUNCT_RE = re.compile(r"[\s　·•・\-—–_()（）\[\]【】《》「」『』'\"“”‘’,，。.、:：;；!！?？/\\|]+")

# A small traditional→simplified table for characters common in Hainan place names.
_T2S = str.maketrans({
    "灣": "湾", "島": "岛", "嶺": "岭", "橋": "桥", "廟": "庙", "園": "园", "鎮": "镇", "縣": "县",
    "區": "区", "環": "环", "塔": "塔", "礁": "礁", "灘": "滩", "廈": "厦", "樓": "楼", "門": "门",
    "東": "东", "萬": "万", "寧": "宁", "瓊": "琼", "陵": "陵", "亞": "亚", "龍": "龙", "鳳": "凤",
    "鷺": "鹭", "鳴": "鸣", "興": "兴", "雲": "云", "書": "书", "院": "院", "聖": "圣", "鹽": "盐",
    "場": "场", "廠": "厂", "觀": "观", "臺": "台", "颳": "刮", "溫": "温", "際": "际", "際": "际",
})


def to_simplified(text: str) -> str:
    return text.translate(_T2S)


def normalize_name(name: str) -> str:
    """Lower-case, NFKC, simplified Chinese, no punctuation/whitespace. Keeps all content characters."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name)
    text = to_simplified(text)
    text = _PUNCT_RE.sub("", text)
    return text.lower().strip()


def strip_region_prefix(name: str) -> str:
    """Remove a leading administrative prefix such as 儋州 in 儋州东坡书院 (only if something remains)."""
    for prefix in REGION_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix) + 1:
            return name[len(prefix):]
    return name


def strip_generic_suffix(name: str) -> str:
    for suffix in GENERIC_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            return name[: -len(suffix)]
    return name


def core_name(name: str) -> str:
    """Normalized name with region prefix and generic suffix removed. Used only for candidate generation."""
    base = normalize_name(name)
    base = strip_region_prefix(base)
    base = strip_generic_suffix(base)
    return base


def name_variants(name: str, aliases: list[str] | None = None) -> list[str]:
    """Search variants for a place: original, prefix-stripped, suffix-stripped, aliases."""
    seen: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in seen:
            seen.append(value)

    add(name)
    for alias in aliases or []:
        add(alias)
    for base in list(seen):
        stripped = strip_region_prefix(base)
        add(stripped)
        add(strip_generic_suffix(stripped))
        # split on common separators like "·" or "与"
        for part in re.split(r"[·・与和及]", stripped):
            if len(part) >= 2:
                add(part)
    return seen


def similarity(a: str, b: str) -> float:
    """0..100 similarity between two normalized names."""
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    if _fuzz is not None:
        return float(_fuzz.ratio(a, b))
    return 100.0 * difflib.SequenceMatcher(None, a, b).ratio()


def best_name_match(query: str, candidates: list[str]) -> tuple[str | None, float]:
    best: tuple[str | None, float] = (None, 0.0)
    nq = normalize_name(query)
    for cand in candidates:
        score = similarity(nq, normalize_name(cand))
        if score > best[1]:
            best = (cand, score)
    return best


def contains_name(text: str, name: str) -> bool:
    """Whether text mentions the place name (normalized, or its core name if long enough)."""
    if not text or not name:
        return False
    ntext = normalize_name(text)
    nname = normalize_name(name)
    if nname and nname in ntext:
        return True
    core = core_name(name)
    return len(core) >= 2 and core in ntext
