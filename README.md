# Hainan Explorer

Local-first discovery and visual review of places for a counter-clockwise cycling trip
around Hainan Island, starting in Haikou. The app harvests candidate places from open
geographic sources (OpenStreetMap, Wikidata, Wikipedia), attaches openly licensed
photographs from Wikimedia Commons with per-file attribution, lets you judge places by
looking at pictures (想去 / 也许 / 跳过 / 待研究), and exports your selection for route
planning. It deliberately favours **lesser-known places** — capes, reefs, fishing
villages, old piers, salt fields, waterfalls, viewpoints — over mainstream tourist lists.

Everything runs on your machine: one Python process, a SQLite database and image files
under `data/`, a browser UI on `http://127.0.0.1:8765`. Nothing is uploaded anywhere.

The previous Flask prototype is kept in `legacy/` (see the last section).

## Requirements

- Windows (tested), Python **3.11** (the code uses 3.10+ syntax; the system Python 3.9 will
  not work).
- No Conda needed. A plain virtual environment created from any 3.11 interpreter is fine
  (`.venv` in this repo was created from an existing Anaconda interpreter because conda's
  package servers were unreachable).
- Internet access for discovery jobs; the UI itself works offline except map tiles and
  remote images.

Dependencies (`requirements.txt`): FastAPI, uvicorn, pydantic, httpx, PyYAML, Pillow,
rapidfuzz, python-multipart, pytest.

## Install

```powershell
cd C:\path\to\Hainan-Cycling-Planner
python -m venv .venv            # use a Python 3.11 interpreter
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then configure (both steps are needed before any Wikimedia data can be fetched):

```powershell
Copy-Item .env.example .env
Copy-Item config\sources.example.yaml config\sources.yaml   # optional; the example is used if absent
notepad .env
```

Set **`HAINAN_EXPLORER_CONTACT`** in `.env` — see the next section.

Create the database (also happens automatically on first start):

```powershell
.\.venv\Scripts\python.exe -m hainan_explorer migrate
```

## The mandatory `HAINAN_EXPLORER_CONTACT` setting

Wikimedia APIs (Wikidata, Wikipedia, Wikimedia Commons) require a `User-Agent` that
carries contact information (an email address or a project URL). Without it they answer
**HTTP 403**. The app therefore:

- builds the User-Agent from `config/sources.yaml` →
  `app.user_agent: "HainanExplorer/0.2 (personal cycling research; contact: ${HAINAN_EXPLORER_CONTACT})"`;
- treats the contact as unset when the variable is empty, still a `${…}` placeholder, or
  the literal `you@example.com`;
- in that case falls back to `HainanExplorer/0.2 (local personal research tool; contact not configured)`
  and **refuses to call Wikidata, Wikipedia or Commons** — jobs fail immediately with
  `ProviderDisabledError: <provider>: Wikimedia APIs require a contact address in the
  User-Agent. Set HAINAN_EXPLORER_CONTACT=<your email or project URL> in .env and restart.`
  (implemented in `hainan_explorer/config.py`, `AppConfig.require_wikimedia_contact`).

`.env`:

```
HAINAN_EXPLORER_CONTACT=your-email@example.com
```

`.env` is loaded by the app at start (existing environment variables win) and is
git-ignored. Overpass and Nominatim do not refuse to run without it, but their policies
also ask for an identifying User-Agent, so set it before running anything.

## Run

```powershell
.\.venv\Scripts\python.exe -m hainan_explorer serve
# or
.\.venv\Scripts\python.exe -m uvicorn hainan_explorer.main:create_app --factory --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765>. The server binds to `127.0.0.1` on port `8765` by default
(`app.host` / `app.port` in `config/sources.yaml`) and warns if you bind elsewhere.
Swagger UI for the local API is at `/api/docs`; the policy document at `/api/policy`.

A background worker thread starts with the server and executes queued jobs one at a
time. Stop with `Ctrl+C`; interrupted jobs are re-queued on the next start.

### Suggested first session

1. 任务与数据源 → **Wikidata 全岛发现**, **OSM 全岛发现**, **中文维基 geosearch**
   (each is a job; watch progress on the same page).
2. **重建粗略走廊** to compute straight-line distances to a rough coastal ring.
3. **为无图地点找图** (Commons search per place) or **Commons 坐标扫描** (island-wide
   geotagged files).
4. Optionally `import-legacy` (below) and **重新研究未研究地点**.
5. 审核网格 → tick 只看未决定 and start deciding with the keyboard.

## CLI

All commands: `.\.venv\Scripts\python.exe -m hainan_explorer [--config PATH] [-v] <command>`

| Command | Purpose |
|---|---|
| `migrate` | Create/upgrade the database. |
| `serve` | Run the web app (same as `uvicorn … --factory`). |
| `summary` | Print catalogue statistics as JSON. |
| `import-legacy [path]` | Import the old catalogue as leads (default `data/attractions.json`). |
| `import-csv PATH [--apply]` | Import places from CSV; dry-run preview unless `--apply`. |
| `import-corridor PATH` | Use a GPX or GeoJSON line as the route corridor. |
| `enqueue JOB_TYPE [--payload JSON] [--priority N]` | Queue a job for the server worker. |
| `run JOB_TYPE [--payload JSON]` | Queue and run one job synchronously in this process. |
| `run-jobs [--max N]` | Drain queued jobs synchronously. |
| `jobs [--status S]` | List jobs. |
| `export [--format json\|csv\|geojson] [--interest …] [--include-seeds]` | Write an export to `data/exports/`. |
| `backup [--label L]` | Copy the database to `data/backups/`. |
| `backups` | List backups. |
| `restore NAME` | Restore a backup (current DB is backed up first). |

Job types: `discover_osm`, `build_regions`, `discover_wikidata`, `discover_wikipedia`, `build_corridor`,
`nearby_expansion`, `images_for_place`, `images_batch`, `commons_sweep`,
`research_place`, `research_batch`, `fetch_url`, `web_search`. Payload keys are listed in
`docs/ARCHITECTURE.md`. Examples:

```powershell
.\.venv\Scripts\python.exe -m hainan_explorer run discover_osm --payload '{"region":"wenchang","groups":["coast_features","infrastructure"]}'
.\.venv\Scripts\python.exe -m hainan_explorer run images_for_place --payload '{"place_id":123}'
.\.venv\Scripts\python.exe -m hainan_explorer export --format geojson --interest want_to_visit maybe
```

Region keys: `haikou chengmai lingao danzhou baisha qiongzhong changjiang dongfang ledong
wuzhishan baoting sanya lingshui wanning qionghai tunchang dingan wenchang`.

## Web UI

Single page, Chinese labels, hash-routed. Sidebar footer shows OSM/Wikidata/Wikipedia
attribution and links to the policy document and API.

| Page | Hash | What you do there |
|---|---|---|
| 审核网格 (review grid) | `#/review` | Card grid with image, name, county, category, source count, image-verification badge, corridor distance. Filters: search, 市县, 类别, 状态, 图片 (本地 / 仅远程 / 无图), sort (未审核优先, 综合发现分, 小众优先, 靠近环岛走廊, 图片优先, 置信度, 最新发现, 按环岛顺序, 名称), 只看未决定, 只看海岸相关, 只看有坐标, 包含村镇种子, 走廊 ≤ km, 来源 ≥ n. 批量选择 for bulk decisions; 撤销 undoes the last decision. Filters persist in the browser. |
| Detail drawer | `#/review/<id>` or click a card | Gallery with attribution, license link, match reasons and 确认是此地 / 不是此地 / 报告问题 / 删除本地副本; 有来源的事实 / 推断·估算 / 未知; aliases, category, scores, 核实状态; 重新研究此地点, 扩展周边地物, 为此地点找图; mini map (or manual coordinate entry); 来源证据 with excerpts and links; 关系与重复候选 with 合并（可撤销）/ 不是重复 / 撤销合并; 附近 3 km 内的候选; 我的笔记; 审核历史. |
| 地图 | `#/map` | Leaflet map with clustering; filter by status, category, county; toggle the rough corridor (dashed, labelled 估算) and village seeds. Solid dots = exact coordinates, hollow = approximate/centroid. |
| 去重审核 | `#/duplicates` | Pending duplicate pairs side by side with distance and reasons: 合并 A → B / B → A (reversible), 相关但分开保留, 无关. |
| 图片线索 | `#/leads` | Geotagged Commons files not yet matched to any place, with license, attribution, source page and an OSM link for the location. |
| 任务与数据源 | `#/jobs` | Buttons to queue discovery/image/research/corridor jobs; 提交网页线索 (paste a public URL); job list with progress, cancel, retry; provider table (enabled / 需要 API key / 已禁用, intervals, last success, errors, HTTP stats); per-county coverage. |
| 导入 · 导出 · 备份 | `#/data` | Export CSV/JSON/GeoJSON (all, 仅想去, 想去 + 也许); import CSV (预览 then 导入) or GPX/GeoJSON corridor from `data/imports/`; backup now; restore a listed backup. |

### Keyboard shortcuts

Active on the review grid and in the detail drawer (not while typing in a field):

| Key | Action |
|---|---|
| `1` or `W` | 想去 (want to visit) |
| `2` or `M` | 也许 (maybe) |
| `3` or `S` | 跳过 (skip) |
| `4` or `R` | 待研究 (needs research) |
| `U` | 撤销 — undo the most recent decision |
| `J` / `→` , `K` / `←` | Move focus to the next / previous card (also pages the drawer) |
| `Enter` | Open the focused card's detail drawer |
| `Esc` | Close the drawer (or leave an input field) |

Deciding on the grid moves focus to the next card automatically.

## Configuration

Config file lookup order: `--config PATH`, `HAINAN_EXPLORER_CONFIG`, `config/sources.yaml`,
`config/sources.example.yaml`. Copy the example to `config/sources.yaml` to customise; the
copy is git-ignored. `${VAR}` placeholders are expanded from the environment, so secrets
stay out of YAML.

Environment variables (`.env` or the shell):

| Variable | Purpose |
|---|---|
| `HAINAN_EXPLORER_CONTACT` | **Required** for Wikidata/Wikipedia/Commons (see above). |
| `HAINAN_EXPLORER_CONFIG` | Alternative config file path. |
| `HAINAN_EXPLORER_DATA_DIR` | Override `data_dir`. |
| `HAINAN_EXPLORER_USER_AGENT` | Override the User-Agent when `app.user_agent` is not set. |
| `BRAVE_SEARCH_API_KEY` | Only if you enable the optional web-search adapter. |

Main YAML sections (`config/sources.example.yaml`):

- `data_dir`, `db_file` — where everything is stored (default `data/explorer.db`).
- `app.host`, `app.port`, `app.user_agent`.
- `bbox` — `[south, west, north, east]`, Hainan Island plus near-shore islets.
- `providers.*` — `enabled`, `endpoint`, `min_interval_seconds`, `timeout_seconds`,
  `max_attempts` and provider-specific options: `overpass.fallback_endpoints`,
  `wikipedia.languages`, `commons.geosearch_radius_m`, `web_search.kind/api_key`,
  `web_pages.respect_robots/disabled_domains`.
- `license_policy` — `local_copy_allowed`, `blocked_markers`, `max_download_bytes`,
  `download_width`, `thumbnail_width`, `max_images_per_place`, `min_match_score`.
- `map_tiles` — Leaflet XYZ template, attribution, max zoom.

Details per provider: `docs/DATA_SOURCES.md`. Image/license rules:
`docs/LEGAL_AND_SOURCE_POLICY.md`.

## Data directory layout

```
data/
  explorer.db            SQLite database (WAL mode; -wal / -shm side files appear while running)
  images/HN000123/IMG000456.jpg      legal local image copies, by place code / image code
  thumbnails/HN000123/IMG000456.jpg  480 px JPEG thumbnails of local copies
  exports/places-<timestamp>[-interest].{csv,json,geojson}
  backups/explorer-<timestamp>[-label].db
  imports/               put CSV / GPX / GeoJSON files here to import them from the UI
  cache/hainan_regions.geojson       county boundary polygons (OSM, ODbL) used for region assignment
  attractions.json       legacy catalogue (input for import-legacy)
logs/                    created on start; the app currently logs to the console
```

`data/explorer.db*`, `images/`, `thumbnails/`, `exports/`, `backups/`, `imports/`,
`cache/` and `logs/` are git-ignored. Back up `data/` as a whole to keep images with the
database.

## Backup and restore

- UI: 导入 · 导出 · 备份 → 立即备份数据库 / 恢复. CLI: `backup`, `backups`, `restore NAME`.
- Backups use SQLite's online backup API, written atomically to `data/backups/`.
- Restore first writes a `-pre-restore` backup of the current database, then replaces
  `explorer.db` (removing stale `-wal`/`-shm` files) and runs migrations. Local images
  under `data/images` are never touched by backup or restore.
- Prefer restoring from the CLI with the server stopped.

## Exports

`export` (CLI) or 导出 (UI) write to `data/exports/` and the UI lists them for download.
Merged places are excluded; village/town seeds are excluded unless `--include-seeds`.

- **JSON** — `exported_at`, an `attribution` block (OSM ODbL, Wikidata CC0, Wikipedia
  CC BY-SA 4.0, Commons per-file), and for every place: all columns, aliases, feature tags,
  `sources` (provider, type, URL, title, publisher, author, dates, access status, license
  notes, relationship, evidence excerpt), `provider_ids`, `images` (title, source page,
  original URL, local path, creator, attribution text, license short/id/URL, permission
  status, sha256, primary flag, association status, match score, verified flag), and a
  `route_distance_note` reminding that corridor distance is a straight-line estimate.
- **GeoJSON** — point features for places with coordinates; properties as above plus
  `source_urls` and `primary_image`; the attribution block at the top level. Loads
  directly into QGIS, umap or most route planners.
- **CSV** (UTF-8 with BOM for Excel) — one row per place: code, names, aliases, county,
  category, coordinates with source/precision, interest status/score/notes, verification,
  scores, corridor distance + note, discovery reason, description, counts, `source_urls`
  (pipe-separated), primary image local path / attribution / license / source page.

## Importing your own data

- **CSV** columns (header row, UTF-8): `name, latitude, longitude, category, county,
  description, url, aliases` (aliases separated by `|`). Only `name` is required. Drop
  the file in `data/imports/`, preview, then import. Rows go through the same
  deduplication as discovered places.
- **GPX / GeoJSON** track or line: 作为走廊导入 replaces the rough corridor with your
  planned route; corridor distances are recomputed (still straight-line).
- **Public web page URL**: 任务与数据源 → 提交网页线索. The page is fetched only if its
  domain is allowed and robots.txt permits; place names found in the text become leads
  with the evidence sentence. Otherwise the URL is kept as a link-only source.

## What is and is not automated

Automated (with explicit limits):

- OSM/Overpass category harvest, Wikidata bbox harvest, Wikipedia geosearch harvest,
  Nominatim geocoding of single leads, Commons image search/geosearch with per-file
  license evaluation and legal download, conservative deduplication with a review queue,
  transparent scoring, rough corridor from OSM towns, coverage bookkeeping, retries and
  rate limiting.

Not automated / not available:

- **No web search without an API key.** `web_search` is disabled by default; Brave or
  Serper keys enable it. No search-result pages are scraped.
- **Xiaohongshu, Mafengwo, Weibo, Douyin are disabled for fetching**
  (`providers.web_pages.disabled_domains`). Their URLs are stored as link-only leads;
  read them yourself and write notes.
- **Link-only leads**: anything that cannot be fetched legally (robots, login wall, disabled
  domain, non-HTML) is kept as a source link, never bypassed.
- Images are downloaded **only** from Wikimedia hosts and only when the file's license
  passes the allow-list; everything else is displayed from the source (Commons) or shown
  as a placeholder with a link.
- No Google Places, no routing engine (corridor distances are straight-line estimates),
  no LLM extraction, no automatic claims about opening hours or access, no user image
  upload yet.

## Troubleshooting

**HTTP 403 from Wikidata / Wikipedia / Commons, or jobs fail with
"Wikimedia APIs require a contact address"** — set `HAINAN_EXPLORER_CONTACT` in `.env`
(a real email or URL, not `you@example.com`) and restart the server. Note that the
provider table on 任务与数据源 reads `enabled` from the YAML only; it still shows the
three Wikimedia providers as 启用 when the contact is missing — the refusal surfaces as
the job's `last_error`.

**Overpass timeouts or HTTP 504/429** — the island-wide query per category group can
take minutes. The client waits `timeout_seconds: 240`, retries with backoff, then tries
the fallback mirror `overpass.openstreetmap.fr (returned HTTP 403 "white-listed usage only" on 2026-10-27; no longer configured)`. If it still fails: run `discover_osm`
per region (`{"region":"sanya"}`) or with fewer `groups`; keep
`min_interval_seconds` at 6 s or more; do not run several OSM jobs at once. Failed group
runs are listed under 最近失败 and can be re-queued with 重试失败任务.

**Nominatim errors / "429"** — Nominatim allows 1 request per second; the client enforces
≥1.1 s and only geocodes single leads during research. Large `research_batch` runs are
slow by design. If you see repeated 429s, do not shorten the interval; wait and retry
the failed jobs later.

**"needs API key" on web_search** — expected unless you set `BRAVE_SEARCH_API_KEY` (or a
Serper key) and `providers.web_search.enabled: true`.

**Page kept link-only** — the job log tells you why: `domain … disabled by policy`,
`disallowed by robots.txt`, `login or verification wall detected`, `content-type …`, or an
HTTP error. None of these are bypassed.

**Jobs stuck in `running` after a crash** — they are re-queued automatically on the next
start (`last_error = recovered after restart`).

**Port 8765 in use** — change `app.port` or pass `--port` to uvicorn.

**`SyntaxError` / `TypeError` on start** — you are running Python < 3.10. Use the
`.venv` interpreter (3.11).

**Images show 🔗 instead of a picture** — the file's license does not permit a local
copy (`link_only`) or has no license metadata (`unknown`). Open the detail drawer: the
Commons thumbnail is displayed remotely where allowed, with a link to the source page.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests use fixtures under `tests/fixtures/` and never touch the network.

## The `legacy/` folder

`legacy/` contains the superseded Flask prototype exactly as it was: `app.py`,
`hainan_cycling/`, `templates/`, `static/`, its `docs/`, `environment.yml` and tests. It
is not used by Hainan Explorer and is not maintained. Its catalogue file is still at
`data/attractions.json`; import it as leads with

```powershell
.\.venv\Scripts\python.exe -m hainan_explorer import-legacy
```

Every record becomes a place with provider id `legacy_catalog/<id>`, its source URLs as
link-only evidence, its summary as description, and its highlights/drawbacks in 我的笔记
marked 来源待核实. Then run 重新研究未研究地点 (`research_batch`) to locate, describe and
picture them from OSM, Wikidata, Wikipedia and Commons.

## Documentation

- `docs/ARCHITECTURE.md` — components, data flow, design decisions, known limitations.
- `docs/DATA_MODEL.md` — every table and column, enum values, ID conventions, dedup rules.
- `docs/DATA_SOURCES.md` — providers, endpoints, rate limits, licenses, retention, policy URLs.
- `docs/LEGAL_AND_SOURCE_POLICY.md` — acquisition and image retention policy as implemented.
- `implementation_plan.md` — staged plan and acceptance criteria. `CLAUDE.md` — project guide.
