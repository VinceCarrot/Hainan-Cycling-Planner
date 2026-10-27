# Data sources

Inventory of every provider the code can talk to, with the endpoints, intervals and
retention rules as configured in `config/sources.example.yaml` and enforced in
`hainan_explorer/`. Policy links were last checked **2026-10-27**. Re-check them before
changing a connector and update the date here.

Global HTTP behaviour (`hainan_explorer/http.py`, `services/context.py`):

- One `httpx` client, `User-Agent` from config. Without `HAINAN_EXPLORER_CONTACT` the UA
  is `HainanExplorer/0.2 (local personal research tool; contact not configured)` and the
  Wikimedia connectors refuse to start.
- Per-host minimum interval: the provider's `min_interval_seconds` for its endpoint
  host; 1.0 s for any host not configured; `commons.wikimedia.org`, `zh/en.wikipedia.org`,
  `www.wikidata.org` share `max(0.5, commons.min_interval_seconds)`; `query.wikidata.org`
  `max(1.0, wikidata.min_interval_seconds)`; `nominatim.openstreetmap.org`
  `max(1.1, nominatim.min_interval_seconds)`; `upload.wikimedia.org` 0.3 s.
- Retries on 429/500/502/503/504 with `Retry-After` (≤120 s) or `2^attempt + jitter`
  (≤60 s), up to the provider's `max_attempts` (default 4). Timeouts and network errors
  are retried the same way.
- Request counts, 429s and errors per host are shown on the 任务与数据源 page.

## OpenStreetMap via Overpass API (`discovery/osm.py`)

| | |
|---|---|
| Provider key | `overpass` (runs are recorded as provider `osm`) |
| Endpoint | `https://overpass-api.de/api/interpreter`, fallback `https://overpass.openstreetmap.fr (returned HTTP 403 "white-listed usage only" on 2026-10-27; no longer configured)/api/interpreter` (tried in order when one fails) |
| Queried | Island-wide bbox `18.10,108.55,20.18,111.10` (or ±0.45° around a region centroid), node/way/relation with `out center tags`, in category groups from `taxonomy.OSM_DISCOVERY_QUERIES`: `coast_features`, `water_and_land`, `tourism`, `historic`, `infrastructure`, `protected_and_parks`, `settlements`. Also: `around:<radius>` queries for nearby expansion (default 1 500 m), regex name search for research, and a `place` lookup of ~33 towns to build the default corridor. |
| Interval / limits | `min_interval_seconds: 6.0`, `timeout_seconds: 240` (Overpass `[timeout:180]`, 90 for nearby, 60 for name search), `max_attempts: 4`. One query at a time (single worker thread). |
| License | ODbL 1.0 |
| Attribution | `© OpenStreetMap contributors, ODbL 1.0` stored in `sources.license_notes`, shown in the sidebar, map and exports |
| Persisted | Name (`name:zh` > `name` > `name:en`), aliases, coordinates (node = exact, way/relation centre = centroid), category, a whitelist of tags in `feature_tags_json`, raw tags in `provider_ids.raw_json`, element URL as source. Unnamed elements are kept only for lighthouse/waterfall/cape/arch with a placeholder name such as `无名灯塔（OSM node/123）`. |
| Local retention | Data only; no tiles, no bulk extracts. Region boundary polygons may be cached as `data/cache/hainan_regions.geojson` with attribution (file present; see ARCHITECTURE "Known limitations"). |
| Policy | https://www.openstreetmap.org/copyright · https://operations.osmfoundation.org/policies/api/ (not used for harvesting — read-only Overpass instead) · https://dev.overpass-api.de/overpass-doc/en/preface/commons.html |
| Last checked | 2026-10-27 |

## Nominatim (`discovery/nominatim.py`)

| | |
|---|---|
| Provider key | `nominatim` |
| Endpoint | `https://nominatim.openstreetmap.org/search` (`format=jsonv2`, `countrycodes=cn`, `viewbox` = bbox, `bounded=1`, `addressdetails`, `extratags`, `namedetails`, `limit≤5`) |
| Queried | Only inside the research pipeline, for a single lead whose coordinates are missing: up to 3 name variants, optionally suffixed with the county name. Results outside the bbox are discarded. Never bulk, never autocomplete. |
| Interval / limits | `min_interval_seconds: 1.1` (policy: ≤1 request/s), `timeout_seconds: 30`, 2 attempts |
| License | ODbL 1.0 |
| Attribution | `© OpenStreetMap contributors, ODbL 1.0 (via Nominatim)` on the source row |
| Persisted | The matched OSM element (`osm_type/osm_id`) as an `osm` provider id, coordinates, a few extratags; a subset of the response in `raw_json`. |
| Local retention | Data only. |
| Policy | https://operations.osmfoundation.org/policies/nominatim/ |
| Last checked | 2026-10-27 |

## OSM tiles (map background)

| | |
|---|---|
| Config | `map_tiles.url` default `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, `attribution`, `max_zoom: 19` |
| Use | Leaflet 1.9.4 (vendored) renders tiles in the browser for the 地图 page and the detail mini-map. No server-side fetching, caching or bulk download. |
| Policy | https://operations.osmfoundation.org/policies/tiles/ — light personal use only; switch `map_tiles` to another provider for heavier use. |
| Last checked | 2026-10-27 |

## Wikidata (`discovery/wikidata.py`)

| | |
|---|---|
| Provider key | `wikidata` |
| Endpoints | SPARQL `https://query.wikidata.org/sparql`; `wbsearchentities` on `https://www.wikidata.org/w/api.php` (research only) |
| Queried | All items with `P625` inside the bbox (`wikibase:box`), paged `LIMIT 200 OFFSET n`, at most 50 pages. Per item: zh/en labels, description, `P31` classes with zh labels, `P18` image, `P373` Commons category, zh/en sitelinks, `P131` admin label, aliases. Humans, events, organisations, schools, stations etc. are filtered out by class and by label keyword. |
| Interval / limits | `min_interval_seconds: 1.0`, `timeout_seconds: 120`, sequential pages |
| Requires | `HAINAN_EXPLORER_CONTACT` (else `ProviderDisabledError`) |
| License | CC0 1.0 |
| Attribution | `Wikidata, CC0 1.0` on the source row and in exports |
| Persisted | Label, aliases, description, coordinates (`approximate`), classes, QID, sitelink flags, image/category hints in `raw_json` (used by the image pipeline). |
| Local retention | Data only. |
| Policy | https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy · https://meta.wikimedia.org/wiki/User-Agent_policy · https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual |
| Last checked | 2026-10-27 |

## Wikipedia zh / en (`discovery/wikipedia.py`)

| | |
|---|---|
| Provider key | `wikipedia` (`languages: [zh, en]`; runs/sources recorded as `wikipedia_zh` / `wikipedia_en`) |
| Endpoint | `https://<lang>.wikipedia.org/w/api.php` |
| Queried | `list=geosearch` on a 14 km grid with 10 km radius (`gslimit 500`) over the bbox, then `prop=extracts|coordinates|pageprops|pageimages|info` (`exintro`, `explaintext`, `variant=zh-cn`, 20 pages per call). Research: `list=search` (5 hits) for a lead's name. Disambiguation pages and titles with school/hospital/company/station keywords are skipped. |
| Interval / limits | `min_interval_seconds: 0.5`, `timeout_seconds: 60` |
| Requires | `HAINAN_EXPLORER_CONTACT` |
| License | Text CC BY-SA 4.0 (page images are Commons files with their own licenses) |
| Attribution | `Wikipedia text, CC BY-SA 4.0 — attribution: article URL` on the source row; the article link is displayed with the excerpt; exports repeat the notice |
| Persisted | Title, intro extract ≤600 chars as `description`, ≤300 chars as `sources.excerpt`, coordinates (`approximate`), QID, page-image hint. |
| Local retention | Short excerpts only; no full articles. |
| Policy | https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy · https://meta.wikimedia.org/wiki/User-Agent_policy |
| Last checked | 2026-10-27 |

## Wikimedia Commons (`discovery/commons.py`, `services/images.py`)

| | |
|---|---|
| Provider key | `commons` |
| Endpoint | `https://commons.wikimedia.org/w/api.php`; file bytes from `upload.wikimedia.org` |
| Queried | Per place: `imageinfo` for files linked from Wikidata `P18` / Wikipedia page image; `categorymembers` of the Wikidata `P373` category (≤40); `list=search` in namespace 6 for up to 5 name variants (≤25 hits each; ASCII names get `"name" Hainan`); `geosearch` namespace 6 within `geosearch_radius_m` (1 500 m, ≤60). Island sweep (`commons_sweep`): `geosearch` on an 8 km grid, 6 km radius, 500 per cell. For every file: `imageinfo` with `iiprop=url|size|mime|extmetadata|sha1`, `iiurlwidth=1600`, and extmetadata `LicenseShortName, License, LicenseUrl, Artist, Credit, ImageDescription, ObjectName, DateTimeOriginal, Categories, Restrictions, AttributionRequired, Attribution, Copyrighted, UsageTerms, GPSLatitude, GPSLongitude`. |
| Interval / limits | `min_interval_seconds: 0.5`, `timeout_seconds: 60`; `upload.wikimedia.org` 0.3 s; downloads ≤15 MiB, ≤8 per place, match score ≥2.0 |
| Requires | `HAINAN_EXPLORER_CONTACT` |
| License | **Per file**; read from extmetadata and normalised (`cc0`, `cc-by-sa-4.0`, …). Never assumed uniform. |
| Attribution | Commons `Attribution` field or `"<Artist/Credit>, via Wikimedia Commons, <license>"`, plus file page URL and license URL; shown under every image and included in exports |
| Persisted | Metadata for every candidate file (title, URLs, creator, license id/short/url, dimensions, geotag, categories, date). **Bytes only** when `permission_status = 'local_copy_allowed'` (see `docs/LEGAL_AND_SOURCE_POLICY.md` §5). |
| Local retention | 1 600 px thumbnail + 480 px local thumbnail under `data/images` / `data/thumbnails`; removable per image. Link-only files are displayed from `upload.wikimedia.org` directly, not copied. |
| Policy | https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia · https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy · https://meta.wikimedia.org/wiki/User-Agent_policy |
| Last checked | 2026-10-27 |

## Web search adapter (`discovery/web_search.py: WebSearchAdapter`) — disabled by default

| | |
|---|---|
| Provider key | `web_search` (`enabled: false` in the example; `kind: brave` or `serper`) |
| Endpoints | Brave: `https://api.search.brave.com/res/v1/web/search` (`X-Subscription-Token`, `country=CN`, `search_lang=zh-hans`, `count≤20`). Serper: `POST https://google.serper.dev/search` (`X-API-KEY`, `gl=cn`, `hl=zh-cn`, `num≤20`). `kind: custom` is listed in the example but has no implementation. |
| Key | `api_key: ${BRAVE_SEARCH_API_KEY}` — environment variable only; the adapter refuses to start if the key is missing or still a `${…}` placeholder. The jobs page shows 需要 API key. |
| Queried | `web_search` job: for each region (or one region), the Chinese templates `海南 {region} 小众景点`, `海南 {region} 海湾 岬角 礁石 灯塔`, `海南 {region} 渔村 老码头 古村 遗迹`, `海南环岛骑行 {region} 沿途 观景点`, `{region} 海岸线 自然景观 地质景观`, `海南 {region} 日出 日落 海岸 湿地`. Place-level templates (`{place} 游记` etc.) are defined but not scheduled by any job. |
| Interval / limits | `min_interval_seconds: 1.2`; `max_results_per_query: 20` in the example is not read by code (the adapter asks for 20). |
| License / terms | Those of the chosen API; check before enabling. |
| Persisted | Query, provider kind, rank, title, URL, snippet (as a `link_only` source with the snippet as excerpt) and a `discovery_runs` row per query. |
| Local retention | Result metadata only; result pages go through the page fetcher below. |
| Policy | Provider's own terms (not recorded here because no provider is enabled). |
| Last checked | n/a — disabled |

## Web page fetcher (`discovery/web_search.py: PageFetcher`)

| | |
|---|---|
| Provider key | `web_pages` (`enabled: true`, `respect_robots: true`, `disabled_domains: xiaohongshu.com, douyin.com, weibo.com, mafengwo.cn`) |
| Used by | `fetch_url` job (user-pasted URL from 提交网页线索 or `POST /api/leads/url`) and `web_search` job results |
| Rules | http/https only; disabled-domain list (incl. subdomains); SSRF guard against private/loopback/link-local/reserved/multicast targets; `robots.txt` honoured with the app's UA; 2 attempts; `content-type` must be html/text; body ≤2 MiB; login/verification walls detected and recorded as `blocked`. See `docs/LEGAL_AND_SOURCE_POLICY.md` §4. |
| Interval / limits | `min_interval_seconds: 3.0` is declared in the example but, because `web_pages` has no endpoint host, the effective throttle is the client default of 1.0 s per host. |
| Persisted | `sources` row (`title`, `access_status`, ≤300-char excerpt, block reason in `license_notes`), `place_sources` evidence sentences for known names, new candidates for unmatched geographic phrases (`needs_geographic_verification = 1`). |
| Local retention | Plain-text excerpts only; no HTML, no images. |
| Policy | Each site's robots.txt and terms. |
| Last checked | 2026-10-27 (rules), n/a (sites) |

## Legacy catalogue import (`services/importer.py: import_legacy_catalog`)

| | |
|---|---|
| Command | `python -m hainan_explorer import-legacy [path]` (default `data/attractions.json`, produced by the Flask app now in `legacy/`) |
| Persisted | One place per record with provider id `legacy_catalog/<id>`, `discovery_reason = user_import`, `confidence 0.4`, `coordinate_precision` `exact` only when the record's coordinate source was an OpenStreetMap URL (else `approximate`); every source URL as a `link_only` source with its platform as publisher (`OpenStreetMap → map_feature`, `Wikimedia Commons → image_page`, 马蜂窝/携程旅行/小红书/哔哩哔哩/今日头条 → `travelogue`, 搜狐 → `web_page`); summary text as description; research notes and highlight/drawback claims as 我的笔记 marked 来源待核实. |
| Not persisted | No images, no page text. Records are leads with `research_status = pending`; run `research_batch` to locate/describe/picture them from the open sources above. |
| License | Mixed — treated as link-only evidence. |
| Last checked | 2026-10-27 |

## User imports

- **CSV** (`import-csv`, 导入 CSV): columns `name, latitude, longitude, category, county, description, url, aliases` (`|`-separated). Provider `user_import`, `confidence 0.5`, `coordinate_precision approximate`, optional URL as a `link_only` `user_note` source. Dry-run preview by default.
- **GPX / GeoJSON corridor** (`import-corridor`, 作为走廊导入): track/route/waypoints or LineString/MultiLineString become the active `route_corridors` row, `is_estimated = 1`.

## Not implemented

- **Google Places / Google Maps**: no connector. If ever added it must be isolated behind an adapter and follow
  https://developers.google.com/maps/documentation/places/web-service/policies and
  https://developers.google.com/maps/documentation/javascript/policies (no persistent photo archive, display/attribution/caching rules). Not implemented as of 2026-10-27.
- Xiaohongshu, Mafengwo, Weibo, Douyin, Ctrip, Bilibili APIs or scraping: none; domains are disabled for fetching.
- Search-engine image results, routing engines, LLM-based extraction, user image upload: none.
