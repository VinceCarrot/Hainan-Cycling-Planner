# Legal and source policy (as implemented)

This document describes what the code in `hainan_explorer/` actually does when it
acquires data and images. It is served inside the app at `/api/policy` and linked from
the sidebar (数据来源与图片政策). Where the code is more permissive or more restrictive
than one might expect, this document follows the code; see `docs/DATA_SOURCES.md` for the
per-provider terms and `docs/DATA_MODEL.md` for the fields mentioned here.

## 1. Principles

1. A search result or a public page is a **lead**, not a license. Pages that cannot be
   read under their own rules are stored as `link_only` sources for manual review.
2. The app **never bypasses** logins, CAPTCHAs, anti-bot measures, paywalls or robots
   directives, and never automates a logged-in session.
3. **Image bytes are only written to disk** when the individual file's license has been
   checked against the local allow-list (`permission_status = 'local_copy_allowed'`).
   Unknown or restricted images stay as records with a source link.
4. Attribution and license metadata travel with every record and every export.
5. The user can remove a local copy at any time; the record and its provenance remain.
6. Nothing is hard-deleted: merged places, rejected images and blocked sources are kept
   with their status.

## 2. Identification and rate limiting

- All HTTP traffic goes through one `httpx` client (`hainan_explorer/http.py`) with an
  identifying `User-Agent`, per-host minimum intervals, bounded retries (429/5xx with
  exponential backoff or `Retry-After`), ≤5 redirects and a 20 s connect timeout.
- Wikimedia's User-Agent policy requires contact information. Until
  `HAINAN_EXPLORER_CONTACT` is set, the User-Agent reads
  `HainanExplorer/0.2 (local personal research tool; contact not configured)` and the
  Wikidata, Wikipedia and Commons connectors **refuse to run**
  (`AppConfig.require_wikimedia_contact` raises `ProviderDisabledError`).
- Query strings are stripped from URLs before logging so API keys never reach logs.
  API keys are read from environment variables only (`${VAR}` placeholders in YAML).

## 3. Place data

| Source | License | What is stored | Attribution shown |
|---|---|---|---|
| OpenStreetMap via Overpass / Nominatim | ODbL 1.0 | Name, coordinates, selected tags, element id/URL | `© OpenStreetMap contributors, ODbL 1.0` in `sources.license_notes`, the sidebar footer, the map tile layer and every export (`attribution` block) |
| Wikidata | CC0 1.0 | Labels, aliases, description, coordinates, classes, QID | `Wikidata, CC0 1.0` in `sources.license_notes` and exports |
| Wikipedia zh/en | CC BY-SA 4.0 (text) | Intro extract ≤600 chars as `places.description`; ≤300 chars as `sources.excerpt`; article URL | `Wikipedia text, CC BY-SA 4.0 — attribution: article URL` on the source row; the article link is always displayed next to the excerpt. Re-users of exports must keep the article URL and license. |
| Public web pages (user-pasted URL or search results) | Page's own terms | Title, ≤300-char excerpt, the sentence that mentions a place, `access_status` | Source link and publisher shown in the detail drawer; excerpts are short evidence quotes, not article copies |
| Legacy catalogue (`data/attractions.json`) | Mixed; link-only | Names, coordinates, source URLs and notes from the old catalogue | Every legacy source row is `access_status = 'link_only'` with its platform as `publisher` |

Facts, derived estimates and unknowns are kept apart in the UI (有来源的事实 / 推断·估算 /
未知). The app never asserts that a place is open, safe or accessible.

## 4. Web page fetching (`discovery/web_search.py: PageFetcher`)

A URL is fetched only if **all** of the following hold (`is_allowed`):

1. Scheme is `http` or `https` and a host is present.
2. The host is not in `providers.web_pages.disabled_domains` (example config:
   `xiaohongshu.com`, `douyin.com`, `weibo.com`, `mafengwo.cn`, including subdomains).
3. `providers.web_pages.enabled` is true.
4. **SSRF guard**: the host must resolve, and none of its addresses may be private,
   loopback, link-local, reserved or multicast.
5. If `respect_robots` is true (default), `robots.txt` is fetched for the host and
   `can_fetch(user_agent, url)` must allow the URL. If `robots.txt` cannot be retrieved
   (network error or HTTP 5xx) the page is **not** fetched and the source is kept link-only
   with the reason `robots.txt unreachable`; a 4xx `robots.txt` is treated as "no
   restrictions".

During the fetch: at most 2 attempts, `content-type` must contain `html` or `text`, the
body is capped at **2 MiB**, scripts/styles are stripped to plain text. If the first
1 500 characters of a short page (<2 500 chars) contain login/verification markers
(请登录, 登录后查看, 扫码登录, 验证码, 访问过于频繁, 安全验证, 请完成验证) the page is
recorded as `blocked` with reason "login or verification wall detected; not bypassed".

Outcomes are stored on the `sources` row as `fetched`, `blocked` (policy/robots/login
wall) or `failed` (HTTP error, content type, size, network). Blocked and failed pages
remain as link-only leads. Downloaded HTML is never executed or saved.

Place names extracted from page text become candidates with
`needs_geographic_verification = 1`, `confidence 0.3`, the evidence sentence and the
source URL. No LLM is used for extraction.

### Social platforms (Xiaohongshu, Mafengwo, Weibo, Douyin, Ctrip, Bilibili …)

These domains are disabled for fetching by default and the app has no API integration
for them. What the user must do manually:

- Keep the post/article URL as a source (paste it in 任务与数据源 → 提交网页线索; it
  will be stored link-only with the block reason, or add it to a CSV `url` column).
- Read the page yourself and type the relevant facts into 我的笔记.
- Do **not** save images from these platforms into `data/images`; the download guard
  rejects non-Wikimedia hosts anyway. If you own the photo, keep it outside the app or
  wait for a user-upload feature.
- Do not relax `disabled_domains` or `respect_robots` unless you have confirmed the
  platform's terms permit automated access.

## 5. Image acquisition and retention

### 5.1 Permission states (`images.permission_status`)

| State | Meaning | Produced by current code |
|---|---|---|
| `local_copy_allowed` | License permits a local copy with attribution | yes |
| `link_only` | Record + source link only; display via the provider's own URL where allowed | yes |
| `unknown` | No license metadata | yes |
| `api_display_only` | Display permitted only through a provider API | defined, not produced |
| `blocked` | Must not be shown or stored | defined, not produced |

### 5.2 License policy (`config.LicensePolicy`, `services/images.py: evaluate_permission`)

The Commons `LicenseShortName`/`LicenseUrl` is normalised to an identifier
(`normalize_license`: `cc0`, `public domain`, `cc-by-4.0`, `cc-by-sa-3.0`,
`cc-by-nc-nd-2.0`, `gfdl`, `fal`, `attribution`, or the raw lower-cased text). A file with
`Copyrighted = False` and no license is treated as `public domain`. Then:

1. No identifier → `unknown`, reason "no license metadata".
2. Identifier contains a **blocked marker** → `link_only`. Defaults:
   `-nc`, `-nd`, `fair use`, `non-free`, `copyrighted`.
3. Identifier equals or is a prefix match (`<allowed>-…` / `<allowed> …`) of the
   **allow-list** → `local_copy_allowed`. Defaults: `cc0`, `cc-by`, `cc-by-sa`, `pd`,
   `public domain`, `fal`, `attribution`. Commons `Restrictions` (e.g. trademark,
   personality rights) are appended to `permission_reason` but do not block the copy.
4. Any other `cc-by…` without `-nc`/`-nd` → `local_copy_allowed`.
5. Everything else (e.g. `gfdl` alone) → `link_only`, reason "not in local-copy allow list".

Both lists are configurable under `license_policy:` in `config/sources.yaml`. GFDL-only
files are intentionally link-only.

If a file is re-fetched and its license no longer permits a copy, the existing local
files are deleted automatically and the record kept (`download_status = 'removed'`).

### 5.3 The single download guard (`ImageService.download`)

Every byte written under `data/images` passes through this one method:

1. `permission_status` must be `local_copy_allowed`; otherwise `download_status` is set
   to `not_allowed` and `DownloadNotAllowed` is raised (HTTP 403 via the API).
2. The URL (`display_url`, else `original_url`) must be on a host ending in
   `wikimedia.org` or `wikipedia.org`. Any other host is refused unless the YAML root
   contains `allow_any_image_host: true` (not present in the example config).
3. Response `content-type` must be one of `image/jpeg`, `image/png`, `image/webp`,
   `image/gif`, `image/tiff`; anything else (including SVG) is rejected.
4. Declared and streamed size must not exceed `license_policy.max_download_bytes`
   (15 MiB).
5. The image is opened with Pillow; SHA-256 and a 64-bit dHash are computed; a ≤480 px
   JPEG thumbnail is generated from the local bytes only.
6. Files are written atomically (`.part` + `fsync` + `os.replace`) to
   `data/images/<HN code>/<IMG code>.<ext>` and `data/thumbnails/<HN code>/<IMG code>.jpg`.
7. Only Commons thumbnails at `download_width` (1 600 px) are fetched, not originals.

Batch downloads (`download_for_place`) additionally require the association not to be
`rejected`, `match_score ≥ license_policy.min_match_score` (2.0), and stop at
`max_images_per_place` (8) per place, user-verified images first.

### 5.4 Display in the UI

- Local copies are served from `/media/images` and `/media/thumbnails`.
- Images without a local copy are shown **directly from `upload.wikimedia.org`**
  (`display_url`) when the provider is `commons` and the state is `link_only` or
  `local_copy_allowed`. Nothing is proxied, screenshotted or re-hosted.
- Anything else shows a neutral placeholder with 打开来源页.
- Every gallery item shows: match score and reasons (or 已人工核实), permission state,
  attribution text, a link to the source page and a link to the license.
- Match badges are explicit about uncertainty: 图片匹配较强/一般/弱（未核实）. A match is
  only called verified after the user clicks 确认是此地.

### 5.5 User controls

- 确认是此地 + 设主图 / 不是此地 — set `association_status` to `user_verified` /
  `rejected`; rejected images are excluded from counts and exports.
- 报告问题 — writes `images.reported_issue` and rejects the association.
- 删除本地副本 — deletes the file and thumbnail (`_safe_join` prevents path escape) and
  sets `download_status = 'removed'`; the image record, license data and source link stay.
- Image leads (图片线索) list geotagged Commons files not yet matched to a place; they are
  records with links, not downloads.

### 5.6 Not implemented, by design

- Google Places photos: no connector exists. If one is ever added it must sit behind its
  own adapter and follow the current Google policies (see `docs/DATA_SOURCES.md`); photo
  bytes must not be persisted.
- Search-engine image results, social-platform images and arbitrary web images are never
  downloaded.
- No AI/vision model decides whether an image "looks like" a place.

## 6. Exports

JSON/GeoJSON exports carry an `attribution` block (OSM ODbL, Wikidata CC0, Wikipedia
CC BY-SA 4.0, "each Commons image carries its own license") and per-image `creator`,
`attribution_text`, `license_short`, `license_id`, `license_url`, `permission_status`,
`source_page_url`. CSV exports include the primary image's attribution, license and source
page. Keep these fields when sharing the data.

## 7. Map tiles

The default Leaflet tile layer is `https://tile.openstreetmap.org/{z}/{x}/{y}.png` with
visible OSM attribution. The OSMF tile usage policy allows light personal use only; the
app does not bulk-download or cache tiles. Set `map_tiles:` in `config/sources.yaml` to
use another provider and its required attribution.

## 8. Local data ownership

All application data lives under `data/` (SQLite database, images, thumbnails, exports,
backups, imports, cache). Backups and restores are explicit user actions; a restore first
backs up the current database. The server binds to `127.0.0.1` unless `app.host` is
changed, and warns when it is.
