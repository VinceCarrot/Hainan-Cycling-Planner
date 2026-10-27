from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hainan_explorer.config import AppConfig, LicensePolicy, ProviderConfig  # noqa: E402
from hainan_explorer.services.context import AppContext  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def make_config(tmp_path: Path) -> AppConfig:
    data = tmp_path / "data"
    cfg = AppConfig(
        data_dir=data,
        db_path=data / "test.db",
        images_dir=data / "images",
        thumbnails_dir=data / "thumbnails",
        exports_dir=data / "exports",
        backups_dir=data / "backups",
        imports_dir=data / "imports",
        cache_dir=data / "cache",
        logs_dir=tmp_path / "logs",
        user_agent="HainanExplorerTests/0 (tests)",
        providers={
            "overpass": ProviderConfig("overpass", True, "https://overpass.test/api/interpreter", 0.0, 5, 1),
            "wikidata": ProviderConfig("wikidata", True, "https://wdqs.test/sparql", 0.0, 5, 1, {"api_endpoint": "https://wikidata.test/w/api.php"}),
            "wikipedia": ProviderConfig("wikipedia", True, None, 0.0, 5, 1, {"languages": ["zh"]}),
            "commons": ProviderConfig("commons", True, "https://commons.test/w/api.php", 0.0, 5, 1),
            "nominatim": ProviderConfig("nominatim", True, "https://nominatim.test", 0.0, 5, 1),
            "web_search": ProviderConfig("web_search", False),
            "web_pages": ProviderConfig("web_pages", True, None, 0.0, 5, 1, {"respect_robots": True, "disabled_domains": ["xiaohongshu.com"]}),
        },
        license_policy=LicensePolicy(),
    )
    return cfg


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("HAINAN_EXPLORER_CONTACT", "tests@example.org")
    cfg = make_config(tmp_path)
    context = AppContext(cfg)
    yield context
    context.close()


@pytest.fixture
def ctx_no_contact(tmp_path, monkeypatch):
    monkeypatch.delenv("HAINAN_EXPLORER_CONTACT", raising=False)
    cfg = make_config(tmp_path)
    context = AppContext(cfg)
    yield context
    context.close()


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
