import json
import os
from pathlib import Path

from hainan_cycling.catalog.models import Attraction, ReviewStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "data" / "attractions.json"
REGION_ROUTE_ORDER = (
    "海口市",
    "澄迈县",
    "临高县",
    "儋州市",
    "白沙黎族自治县",
    "琼中黎族苗族自治县",
    "昌江黎族自治县",
    "东方市",
    "乐东黎族自治县",
    "五指山市",
    "保亭黎族苗族自治县",
    "三亚市",
    "陵水黎族自治县",
    "万宁市",
    "琼海市",
    "屯昌县",
    "定安县",
    "文昌市",
)
_REGION_ROUTE_INDEX = {
    region: index for index, region in enumerate(REGION_ROUTE_ORDER)
}


class AttractionNotFoundError(LookupError):
    """Raised when an attraction ID is not present in the canonical catalog."""


def _read_records() -> list[dict]:
    with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        records = json.load(catalog_file)

    if not isinstance(records, list):
        raise ValueError(f"{CATALOG_PATH.name} must contain a JSON array")
    return records


def _validate_records(records: list[dict]) -> list[Attraction]:
    attractions: list[Attraction] = []
    seen_ids: set[str] = set()

    for record in records:
        attraction = Attraction.model_validate(record)
        if attraction.id in seen_ids:
            raise ValueError(f"Duplicate attraction ID: {attraction.id}")
        if attraction.region not in _REGION_ROUTE_INDEX:
            raise ValueError(f"Unknown attraction region: {attraction.region}")
        seen_ids.add(attraction.id)
        attractions.append(attraction)
    return attractions


def _write_records(records: list[dict]) -> None:
    """Write the catalog back in its existing on-disk style.

    The canonical file uses four-space indentation, CRLF line endings, and no
    trailing newline. The write goes through a temporary file and an atomic
    replace so a failure cannot leave a truncated catalog behind.
    """
    text = json.dumps(records, ensure_ascii=False, indent=4).replace("\n", "\r\n")
    temp_path = CATALOG_PATH.with_suffix(".json.tmp")
    temp_path.write_text(text, encoding="utf-8", newline="")
    os.replace(temp_path, CATALOG_PATH)


def list_attractions(status: str | None = None) -> list[Attraction]:
    attractions = _validate_records(_read_records())
    attractions.sort(key=lambda item: _REGION_ROUTE_INDEX[item.region])

    if status is not None:
        attractions = [item for item in attractions if item.status == status]
    return attractions


def set_attraction_status(attraction_id: str, status: str) -> Attraction:
    """Change one attraction's review status and persist the catalog."""
    new_status = ReviewStatus(status)
    records = _read_records()

    target = next((record for record in records if record.get("id") == attraction_id), None)
    if target is None:
        raise AttractionNotFoundError(attraction_id)

    target["status"] = new_status.value
    _validate_records(records)
    _write_records(records)
    return Attraction.model_validate(target)


def delete_attraction(attraction_id: str) -> None:
    """Remove one attraction from the canonical catalog permanently."""
    records = _read_records()
    remaining = [record for record in records if record.get("id") != attraction_id]
    if len(remaining) == len(records):
        raise AttractionNotFoundError(attraction_id)

    _validate_records(remaining)
    _write_records(remaining)
