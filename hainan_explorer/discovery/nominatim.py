"""Nominatim geocoding (OSM). Policy (checked 2026-10-27, https://operations.osmfoundation.org/policies/nominatim/):
max 1 request/second, descriptive User-Agent, no bulk/autocomplete, results are ODbL.
Used only for individual leads whose coordinates are missing.
"""
from __future__ import annotations

import logging
from typing import Any

from ..geo import in_bbox
from ..http import ProviderDisabledError
from ..services.context import AppContext

log = logging.getLogger(__name__)


class NominatimClient:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.config.provider("nominatim")
        if not self.cfg.enabled:
            raise ProviderDisabledError("nominatim disabled")
        self.base = (self.cfg.endpoint or "https://nominatim.openstreetmap.org").rstrip("/")

    def search(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        south, west, north, east = self.ctx.config.bbox
        params = {
            "q": text, "format": "jsonv2", "limit": limit, "countrycodes": "cn", "accept-language": "zh-CN,zh,en",
            "viewbox": f"{west},{north},{east},{south}", "bounded": 1, "addressdetails": 1, "extratags": 1, "namedetails": 1,
        }
        data = self.ctx.http.get_json(f"{self.base}/search", params=params, timeout=self.cfg.timeout_seconds, max_attempts=2)
        out = []
        for item in data:
            try:
                lat, lon = float(item["lat"]), float(item["lon"])
            except (KeyError, ValueError):
                continue
            if in_bbox(lat, lon, self.ctx.config.bbox):
                out.append(item)
        return out
