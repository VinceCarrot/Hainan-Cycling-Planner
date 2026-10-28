"""Application context: config, database, HTTP client, region index. One per process."""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import AppConfig, load_config
from ..db.connection import Database
from ..http import HttpClient
from ..regions import RegionIndex

log = logging.getLogger(__name__)


class AppContext:
    def __init__(self, config: AppConfig | None = None, db_path: Path | None = None):
        self.config = config or load_config()
        self.config.ensure_dirs()
        self.db = Database(db_path or self.config.db_path)
        self.db.migrate()
        self.http = HttpClient(self.config.user_agent, default_interval=max(1.0, self.config.provider("web_pages").min_interval_seconds))
        for name, provider in self.config.providers.items():
            if provider.endpoint:
                from urllib.parse import urlsplit

                host = urlsplit(provider.endpoint).hostname
                if host:
                    self.http.set_rate(host, provider.min_interval_seconds)
        # Wikimedia hosts share a polite default even if not configured individually
        for host in ("commons.wikimedia.org", "zh.wikipedia.org", "en.wikipedia.org", "www.wikidata.org"):
            self.http.set_rate(host, max(1.5, self.config.provider("commons").min_interval_seconds))
        self.http.set_rate("query.wikidata.org", max(1.0, self.config.provider("wikidata").min_interval_seconds))
        self.http.set_rate("nominatim.openstreetmap.org", max(1.1, self.config.provider("nominatim").min_interval_seconds))
        self.http.set_rate("upload.wikimedia.org", 0.3)
        self.regions = RegionIndex(self.config.cache_dir / "hainan_regions.geojson")

    def close(self) -> None:
        self.http.close()
        self.db.close()


_context: AppContext | None = None


def get_context() -> AppContext:
    global _context
    if _context is None:
        _context = AppContext()
    return _context


def set_context(ctx: AppContext | None) -> None:
    global _context
    _context = ctx
