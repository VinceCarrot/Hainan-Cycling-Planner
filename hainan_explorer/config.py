"""Configuration loading: YAML file + environment variables (secrets only via env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATHS = (
    PROJECT_ROOT / "config" / "sources.yaml",
    PROJECT_ROOT / "config" / "sources.example.yaml",
)

# Bounding box that contains Hainan Island and its near-shore islets but not the
# Leizhou Peninsula or the South China Sea islands. (south, west, north, east)
HAINAN_BBOX = (18.10, 108.55, 20.18, 111.10)


@dataclass
class ProviderConfig:
    name: str
    enabled: bool = True
    endpoint: str | None = None
    min_interval_seconds: float = 1.0
    timeout_seconds: float = 60.0
    max_attempts: int = 4
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class LicensePolicy:
    """Which license identifiers permit a local copy. Everything else is link-only."""

    local_copy_allowed: list[str] = field(
        default_factory=lambda: [
            "cc0",
            "cc-by",
            "cc-by-sa",
            "pd",
            "public domain",
            "fal",
            "attribution",
        ]
    )
    blocked_markers: list[str] = field(
        default_factory=lambda: ["-nc", "-nd", "fair use", "non-free", "copyrighted"]
    )
    max_download_bytes: int = 15 * 1024 * 1024
    download_width: int = 1024
    thumbnail_width: int = 480
    max_images_per_place: int = 4
    min_match_score: float = 2.5


@dataclass
class AppConfig:
    data_dir: Path
    db_path: Path
    images_dir: Path
    thumbnails_dir: Path
    exports_dir: Path
    backups_dir: Path
    imports_dir: Path
    cache_dir: Path
    logs_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    user_agent: str = "HainanExplorer/0.2 (local personal research tool)"
    bbox: tuple[float, float, float, float] = HAINAN_BBOX
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    license_policy: LicensePolicy = field(default_factory=LicensePolicy)
    map_tiles: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def provider(self, name: str) -> ProviderConfig:
        return self.providers.get(name, ProviderConfig(name=name, enabled=False))

    @property
    def contact_configured(self) -> bool:
        return contact_configured()

    def require_wikimedia_contact(self, provider: str) -> None:
        """Wikimedia APIs (Wikidata, Wikipedia, Commons) require a User-Agent with contact info."""
        if not self.contact_configured:
            from .http import ProviderDisabledError

            raise ProviderDisabledError(
                f"{provider}: Wikimedia APIs require a contact address in the User-Agent. "
                "Set HAINAN_EXPLORER_CONTACT=<your email or project URL> in .env and restart."
            )

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.images_dir,
            self.thumbnails_dir,
            self.exports_dir,
            self.backups_dir,
            self.imports_dir,
            self.cache_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def _expand_env(value: Any) -> Any:
    """Expand ${ENV_VAR} placeholders in strings; never store the secret itself in YAML."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from a local .env file into os.environ (existing variables win)."""
    path = path or PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def contact_configured() -> bool:
    value = os.environ.get("HAINAN_EXPLORER_CONTACT", "").strip()
    return bool(value) and not value.startswith("${") and value != "you@example.com"


def load_config(path: Path | str | None = None) -> AppConfig:
    load_dotenv()
    candidates = [Path(path)] if path else []
    env_path = os.environ.get("HAINAN_EXPLORER_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(DEFAULT_CONFIG_PATHS)
    raw: dict[str, Any] = {}
    for candidate in candidates:
        if candidate.is_file():
            with candidate.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            break
    raw = _expand_env(raw)

    data_dir = Path(os.environ.get("HAINAN_EXPLORER_DATA_DIR") or raw.get("data_dir") or PROJECT_ROOT / "data")
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    app_raw = raw.get("app", {})
    providers: dict[str, ProviderConfig] = {}
    for name, p in (raw.get("providers") or {}).items():
        p = p or {}
        providers[name] = ProviderConfig(
            name=name,
            enabled=bool(p.get("enabled", True)),
            endpoint=p.get("endpoint"),
            min_interval_seconds=float(p.get("min_interval_seconds", 1.0)),
            timeout_seconds=float(p.get("timeout_seconds", 60.0)),
            max_attempts=int(p.get("max_attempts", 4)),
            options={k: v for k, v in p.items() if k not in {"enabled", "endpoint", "min_interval_seconds", "timeout_seconds", "max_attempts"}},
        )
    lp_raw = raw.get("license_policy") or {}
    license_policy = LicensePolicy(**{k: v for k, v in lp_raw.items() if k in LicensePolicy.__dataclass_fields__})
    bbox_raw = raw.get("bbox")
    bbox = tuple(float(x) for x in bbox_raw) if bbox_raw else HAINAN_BBOX
    user_agent = str(app_raw.get("user_agent") or os.environ.get("HAINAN_EXPLORER_USER_AGENT") or "")
    if not contact_configured() or "${" in user_agent:
        # Wikimedia's User-Agent policy requires contact info; without it we identify honestly and
        # the Wikimedia connectors refuse to run (see AppConfig.contact_configured).
        user_agent = "HainanExplorer/0.2 (local personal research tool; contact not configured)"

    cfg = AppConfig(
        data_dir=data_dir,
        db_path=data_dir / (raw.get("db_file") or "explorer.db"),
        images_dir=data_dir / "images",
        thumbnails_dir=data_dir / "thumbnails",
        exports_dir=data_dir / "exports",
        backups_dir=data_dir / "backups",
        imports_dir=data_dir / "imports",
        cache_dir=data_dir / "cache",
        logs_dir=PROJECT_ROOT / "logs",
        host=str(app_raw.get("host", "127.0.0.1")),
        port=int(app_raw.get("port", 8765)),
        user_agent=user_agent,
        bbox=bbox,  # type: ignore[arg-type]
        providers=providers,
        license_policy=license_policy,
        map_tiles=raw.get("map_tiles") or {},
        raw=raw,
    )
    return cfg
