# Claude Code Project Guide — Hainan Explorer

## 1. Project purpose

Build a Windows-first, locally hosted web application for discovering, researching, visually reviewing, and prioritizing places of interest for a counter-clockwise Hainan Island cycling trip starting in Haikou.

The user's primary objective is **broad discovery, especially lesser-known places**, not merely reproducing popular tourist lists. The system should turn candidate places found across geographic datasets, open image repositories, public web pages, travel blogs, and user-provided materials into a deduplicated, evidence-backed local catalog.

The user must be able to judge places primarily by looking at images, then save decisions and later export selected places for route planning.

## 2. Product principles

1. **Place-centric, evidence-backed data.** A place is the primary entity. Web pages, image assets, mentions, coordinates, and route observations are separate records linked to it.
2. **Recall before precision, then human review.** Discovery should favor finding plausible candidates, including obscure places. Uncertain candidates must be labelled rather than silently discarded.
3. **Never fabricate.** Do not invent place names, coordinates, source URLs, photo attribution, licenses, route distances, opening status, or access permissions. Clearly distinguish sourced facts, derived estimates, and unknowns.
4. **Image correctness matters.** A photograph must not be presented as verified evidence for a place unless the association is supported. Mark inferred matches as unverified.
5. **Legal-by-design acquisition.** Do not bypass logins, CAPTCHAs, anti-bot systems, paywalls, rate limits, access controls, or platform restrictions. Do not assume public visibility means permission to download or republish.
6. **Local ownership.** Store application data in a user-controlled local directory. Provide backups and export formats. No mandatory cloud database.
7. **Resumable, observable jobs.** Discovery and image jobs must support retries, rate limits, cancellation, progress, logs, and restart after failure.
8. **Incremental implementation.** Build a working local visual review loop before adding many discovery connectors.
9. **Keep providers replaceable.** Use adapters/interfaces for discovery, image providers, routing, and map tiles. Do not hard-code a single provider into core logic.
10. **Do not over-engineer.** Prefer Python, SQLite, a simple web frontend, and a small number of dependencies until measured needs justify more.

## 3. User context and trip assumptions

- Trip: start in Haikou and ride counter-clockwise around Hainan Island.
- Likely route planning will be flexible, with day distances and detours assessed later.
- Interest categories include coastlines, reefs, capes, unusual rock formations, beaches, fishing villages, old ports, lighthouses, local architecture, historic sites, wetlands, forests, mountains, viewpoints, cultural sites, and unusual roadside discoveries.
- The first release is for one user on Windows. It should run locally and open in a desktop browser.
- The user wants to manage the database and legally stored images independently.

Do not hard-code a final trip date, daily mileage, accommodation plan, or fixed route. These are separate future inputs.

## 4. Suggested stack

Use the simplest stack that meets the requirements:

- Python 3.11+ (choose a supported version and pin dependencies).
- FastAPI for local HTTP API and app server.
- SQLite with migrations; use SQLAlchemy or a similarly maintainable data layer.
- Plain HTML/CSS/TypeScript or lightweight JavaScript. A frontend framework is acceptable only if it materially improves implementation quality.
- Leaflet for map interaction, with a configurable tile provider and visible attribution.
- Pillow for image metadata, thumbnails, and perceptual hashes.
- Optional later: `imagehash`, `rapidfuzz`, `httpx`, `beautifulsoup4`, `trafilatura`, `exifread`, and an embedding model for image-text similarity. Every dependency must have a clear purpose.
- Pytest for unit and integration tests.
- Configuration in YAML/TOML plus environment variables for secrets.

Do not add Docker, Redis, a cloud database, or a complex task queue to the MVP unless a demonstrated requirement demands it. A SQLite-backed job table and worker process are sufficient initially.

## 5. Required deliverables

Maintain these project artifacts:

- `CLAUDE.md`: this guide.
- `implementation_plan.md`: staged plan and acceptance criteria.
- `README.md`: installation, run, backup, restore, provider setup, and troubleshooting.
- `docs/DATA_SOURCES.md`: source inventory, endpoints, usage constraints, attribution, and last-checked dates.
- `docs/DATA_MODEL.md`: schema and relationships.
- `docs/LEGAL_AND_SOURCE_POLICY.md`: acquisition and image retention policy.
- `docs/ARCHITECTURE.md`: components, data flow, and design decisions.
- `config/sources.example.yaml`: safe example configuration without secrets.
- Automated tests for critical logic.

If any files already exist, inspect and preserve useful decisions before changing them. Do not overwrite user data or unrelated files.

## 6. Discovery strategy: maximize lesser-known-place recall

Implement a multi-source, multi-pass discovery pipeline. Do not rely on a single search engine, tourism portal, or map API.

### 6.1 Geographic seed coverage

Use a configurable Hainan Island geographic boundary and a list of administrative areas/towns as search seeds. Avoid assuming that a single bounding box accurately represents the island; support polygon/region filtering when practical.

Generate discovery jobs across:
- Administrative areas and towns.
- Coastal segments and capes.
- Named bays, beaches, reefs, islands, wetlands, estuaries, ports, lighthouses, and coastal villages.
- Inland mountains, forests, lakes, reservoirs, rivers, geological features, old villages, temples, forts, ruins, and viewpoints.
- Places near likely cycling corridors and optional detours.
- Unusual or low-frequency geographic features that do not appear on mainstream tourism lists.

Treat the main route as a search spine, not a hard exclusion boundary. Store a place's approximate distance to the cycling corridor when route geometry becomes available; do not exclude distant candidates too early.

### 6.2 OpenStreetMap

Use OSM-derived data for names, coordinates, feature types, and road/trail context. Prefer an appropriate Overpass instance, a regional extract, or a reputable provider for batch use. Do not use the main OSM editing API for bulk read-only harvesting. Respect provider-specific quotas and policies; use an identifying User-Agent, request timeouts, bounded concurrency, caching where permitted, and backoff on 429/5xx responses.

Query a broad but curated set of tags, for example:
- `natural=beach|cape|cliff|reef|wetland|wood|peak|cave|hot_spring|spring|waterfall|bay` where tags are valid and applicable.
- `tourism=attraction|viewpoint|museum|artwork|picnic_site|camp_site`.
- `historic=*`, `heritage=*`, `archaeological_site=*`.
- `man_made=lighthouse|pier|water_tower|tower`.
- `leisure=nature_reserve|park|nature_reserve` where applicable.
- `place=village|hamlet|locality|island`.
- `waterway=waterfall|river|stream`, plus relevant natural water features.
- Coastal infrastructure and named geographic features, without treating every POI as a tourism destination.

Do not blindly trust tags or treat a map feature as open to visitors. Store OSM element type and ID, source timestamp if available, and OSM attribution. OSM data is ODbL; show visible attribution and preserve applicable license notices.

### 6.3 Wikidata and Wikimedia Commons

Use Wikidata SPARQL/API for named geographic entities, administrative relationships, coordinates, official websites, Wikipedia sitelinks, and Commons category/image references when available. Query in bounded geographic batches and handle endpoint limits. Do not make the pipeline dependent on every entity having a Wikipedia page.

Use Wikimedia Commons API to search files and retrieve:
- file title and page URL;
- image URL and dimensions;
- creator/author;
- license short name and license URL;
- attribution/credit and copyright status where present;
- source page and description;
- categories and relevant structured metadata.

Persist the per-file license/attribution facts with the image record. Do not assume every Commons item has the same license or that all restrictions are identical. Only download locally when the individual file's license and terms have been checked against the application's retention policy. Set an identifying User-Agent and respect Wikimedia API policies/rate limits.

### 6.4 Search engines and public web pages

Implement a pluggable search adapter. Prefer documented search APIs or providers whose terms permit the intended use. Avoid scraping search result pages when prohibited or technically restricted. Keep API keys in environment variables and never commit them.

Use query templates combining:
- Hainan + county/town/village + small/hidden/less-known attractions.
- Hainan + bay/cape/reef/rock formation/lighthouse/fishing village/old port/ancient village/wetland/forest/viewpoint.
- Hainan island cycling + route/roadside/scenic point/detour.
- Place name + travelogue/photography/hiking/cycling/field notes.
- Place name + Chinese variants, former names, local names, and English transliterations where relevant.

Search in **regional batches**, not just a global “best attractions in Hainan” query. Use query expansion from newly discovered place names, aliases, nearby towns, and feature categories. Preserve query, provider, retrieval time, result rank, title, URL, and snippet where provider terms allow.

A result page is a lead, not proof. Extract only pages accessible under the source's rules. Use timeouts, bounded concurrency, domain-level throttling, retry budgets, and a clear per-domain disable switch. Respect robots directives and terms as applicable; do not bypass access controls or anti-bot measures. If extraction is disallowed or fails, keep a source link for manual review.

### 6.5 Travel blogs, forums, social platforms, and video sources

Potential discovery sources include public travel blogs, cycling trip reports, photography blogs, public forums, public tourism articles, video descriptions/transcripts when legally accessible, and publicly viewable pages on platforms such as Xiaohongshu or Mafengwo.

Do not assume these platforms permit bulk scraping, image downloading, or reuse. Do not automate logged-in sessions, defeat anti-bot systems, extract content behind access restrictions, or download images merely because a browser can display them. Use official APIs/exports if available and terms permit; otherwise store a source URL and manually supplied notes or user-exported material.

Build a **mention extraction workflow**:
1. Obtain an allowed page's text and metadata.
2. Extract candidate proper nouns and geographic phrases.
3. Match against known place names and aliases.
4. Create new candidates for unmatched names/phrases with `needs_geographic_verification=true`.
5. Save the evidence sentence and source URL.
6. Never treat an LLM-generated place name as confirmed without supporting source evidence.

If using an LLM to summarize or extract, store model/version, extraction timestamp, supporting excerpt, and confidence. Do not send private local data or secrets to an external model without explicit configuration and user consent.

### 6.6 Discovery of genuinely obscure places

To avoid popularity bias:
- Search geographic features, not only words like “attraction” or “must-see”.
- Search village and township names, small coastal settlements, old piers, capes, headlands, river mouths, reservoirs, abandoned/ruined structures, unusual terrain, and locally named places.
- Traverse source links from seed travelogues when permitted.
- Run “nearby named features” expansion around each confirmed seed.
- Compare sources: a place mentioned in a niche cycling/photography blog but absent from mainstream tourism lists should still be retained.
- Keep a `discovery_reason` such as `OSM_feature`, `Wikidata_entity`, `travelogue_mention`, `nearby_expansion`, `user_import`, or `manual_candidate`.
- Use a discovery score that does **not** simply reward popularity. Include novelty, geographic coverage, source evidence, and route relevance.
- Retain low-confidence leads in a review queue rather than dropping them.

### 6.7 Search coverage and stopping rules

Track coverage by administrative area, feature class, and source family. A run is not “complete” merely because an API returned no more results. Store:
- areas/categories/queries attempted;
- source/provider and request time;
- result counts and failures;
- pagination/cursor status;
- last successful scan;
- retry state.

Provide “re-run failed”, “discover more in this area”, and “expand around selected candidate” actions. Discovery should be incremental and idempotent.

## 7. Image discovery and local retention

### 7.1 Source priority

1. **User-owned images and user-imported files**: local storage is allowed subject to the user's rights and any third-party content.
2. **Wikimedia Commons / other explicitly open-license repositories**: download only after collecting license and attribution metadata and applying a license policy.
3. **Other documented APIs**: use only within their terms, including attribution, display, caching, and storage restrictions.
4. **Public web pages, blogs, tourism portals, social platforms**: use as discovery evidence and keep source links by default. Do not bulk-download unless the relevant rights and terms explicitly permit it.
5. **Search-engine image results**: use as leads only; the search result itself does not grant reuse rights.

Do not use Google Places photos as a permanent local image archive. Google Places content has specific display, attribution, and caching restrictions; if a Google provider is implemented, isolate it behind an adapter and follow the current official policy. Do not persist restricted photo bytes or metadata beyond what the applicable terms permit.

### 7.2 Image record and states

Each image must track:
- image ID and related place(s);
- source provider and source page URL;
- original URL when permitted;
- local path only if locally stored;
- title/description;
- creator and attribution text/URL;
- license identifier, license URL, and license-verification state;
- permission state: `local_copy_allowed`, `link_only`, `api_display_only`, `unknown`, `blocked`;
- dimensions, file type, byte size;
- content SHA-256 and perceptual hash when a local image is available;
- view type: `landscape`, `closeup`, `aerial`, `roadside`, `sunrise_sunset`, `architecture`, `trail`, `unknown`;
- association confidence and manual verification state;
- retrieval time and last link check.

Unknown or restricted images must never be silently copied into `data/images`.

### 7.3 Image matching

For each candidate place, query standard name, aliases, nearby town, category, and alternate spellings. Rank candidate images using transparent signals:
- name/alias match in image title or caption;
- page text explicitly mentions the place;
- coordinate or structured metadata agrees;
- image category/visual content agrees with the place type;
- independent sources support the same association.

Store scores and reasons, not only a single opaque score. Display a warning for weak matches. Never label a match “verified” solely because an image model says it looks like a coast or lighthouse.

### 7.4 Image storage and UI behavior

- Store legal local copies under stable IDs, e.g. `data/images/HN000123/IMG000456.jpg`.
- Generate thumbnails only from local images the app is allowed to process, or where the provider's terms explicitly permit the operation.
- Do not proxy, screenshot, or re-host restricted remote images to circumvent source limitations.
- Remote image display must follow source terms, hotlinking rules, attribution requirements, and any API display policy.
- If a remote image cannot legally or technically be displayed in the app, show a neutral placeholder plus a “Open source page” link.
- Keep license/attribution visible in the image detail panel and include it in relevant exports.
- Provide a “report wrong image / wrong place / rights issue” action and an ability to remove a local copy without deleting the place.

## 8. Data model

Use SQLite with migrations. At minimum create these tables:

### `places`
`id`, `canonical_name`, `normalized_name`, `aliases_json`, `country`, `province`, `city`, `county`, `town`, `latitude`, `longitude`, `geometry_json`, `category`, `subcategory`, `description`, `description_language`, `discovery_status`, `verification_status`, `confidence_score`, `interest_status`, `interest_score`, `personal_notes`, `discovery_reason`, `is_accessible_unknown`, `created_at`, `updated_at`, `merged_into_place_id`.

### `sources`
`id`, `provider`, `source_type`, `url`, `canonical_url`, `title`, `publisher`, `author`, `published_at`, `retrieved_at`, `access_status`, `terms_url`, `license_notes`, `excerpt`, `content_hash`, `last_checked_at`.

### `place_sources`
`place_id`, `source_id`, `relationship_type`, `evidence_excerpt`, `confidence_score`, `created_at`.

### `images`
`id`, `provider`, `source_id`, `source_page_url`, `original_url`, `local_path`, `thumbnail_path`, `title`, `description`, `creator`, `attribution_text`, `attribution_url`, `license_id`, `license_url`, `permission_status`, `license_verified_at`, `width`, `height`, `mime_type`, `bytes`, `sha256`, `perceptual_hash`, `view_type`, `match_score`, `match_reasons_json`, `association_status`, `retrieved_at`, `last_checked_at`.

### `place_images`
`place_id`, `image_id`, `is_primary`, `association_type`, `confidence_score`, `verified_by_user`, `notes`.

### `discovery_runs`
`id`, `provider`, `query`, `region_key`, `category`, `started_at`, `finished_at`, `status`, `result_count`, `error_summary`, `cursor_json`, `config_snapshot_json`.

### `jobs`
`id`, `job_type`, `status`, `priority`, `payload_json`, `attempt_count`, `max_attempts`, `created_at`, `started_at`, `finished_at`, `last_error`, `progress_json`.

### `reviews`
`id`, `place_id`, `decision`, `score`, `reason`, `reviewed_at`.

### `place_relations`
`id`, `place_id_a`, `place_id_b`, `relation_type`, `confidence_score`, `created_at`, `review_status`.

### `route_segments`
`id`, `route_version`, `sequence_no`, `day_number`, `name`, `source_file`, `point_count`, `start_lat/lon`, `end_lat/lon`, `distance_km`, `elevation_gain_m`, `surface`, `source_id`, `is_estimated`, `geometry_json` (WGS-84, used for display/distances), `source_crs` (`wgs84` | `gcj02` | `bd09`), `source_geometry_json` (GPX coordinates verbatim), `notes`, `created_at`. Populated by the route-book import (one row per day's GPX; see `services/routes.py`, conversions in `crs.py`). Never rewrite the user's GPX files; convert only the stored copy. Places carry `route_day`, `route_day_km` and `route_distance_km` derived from these tracks; all are straight-line geometric estimates and must stay labelled as such.

Use foreign keys and indexes. Keep raw source identifiers in provider-specific fields or a `provider_ids` table rather than assuming one global identifier. Store coordinates as numeric values and use WGS84. Do not store private credentials in the database.

## 9. Deduplication

Use a conservative, explainable pipeline:

1. Normalize Unicode, whitespace, punctuation, traditional/simplified Chinese variants where useful, and common suffixes without destroying the original name.
2. Use provider-native stable IDs as strong evidence, scoped by provider.
3. Candidate generation by name/alias similarity, administrative area, and spatial proximity.
4. Compare coordinates, feature class, parent/child relations, source excerpts, and official links.
5. Auto-merge only when evidence is very strong and the merge is reversible; otherwise create a possible-duplicate review item.
6. Distinguish `duplicate_of`, `part_of`, and `nearby_to`. A village, its beach, and a lighthouse nearby may be three separate useful destinations.
7. On merge, preserve all aliases, sources, images, reviews, and old IDs in an audit record. Never hard-delete merged places.
8. Support undo and a review screen.

Starting heuristics (configurable, not universal truths):
- identical provider ID: high-confidence match;
- highly similar name plus coordinates within 100 m: likely duplicate candidate;
- 100–500 m: require category/context agreement;
- missing coordinates: use names, administrative areas, aliases, and evidence; do not auto-merge based only on name;
- a large attraction/region can contain multiple independent destinations, so distance alone must not trigger merging.

## 10. UI requirements

### Main discovery/review screen
- Responsive card grid with image, canonical name, county/town, category, short description, image verification badge, and source count.
- Keyboard actions for `Want to visit`, `Maybe`, `Skip`, `Needs research`.
- Filters for region, category, status, image availability, source count, confidence, distance from route, and duplicate review.
- Sort by recently discovered, novelty, confidence, proximity to route, or unreviewed first.
- Bulk actions, undo, and persistent filters.
- Explicit “show only undecided places” mode.
- Distinguish local image, remote/API image, link-only, and no-image states.

### Place detail drawer/page
- Gallery with attribution and open-source link.
- Facts vs derived estimates vs unknowns clearly separated.
- Alias list, coordinates, map, nearby candidates, source evidence excerpts, source links, and duplicate candidates.
- Interest decision, score, notes, verification status, and report-error actions.
- User should be able to correct a place/image association and restore prior state.

### Map
- Show selected and candidate places with filters and clustering.
- Display map provider attribution.
- Make tile source configurable; do not bulk-download public tile servers or assume tile data may be stored indefinitely.
- Do not infer route distance from straight-line distance. Label estimates clearly.
- Route planner is secondary to discovery and visual review in the MVP.

### Source and job management
- List providers, enable/disable controls, last run, quota/rate-limit notes, errors, and source policy link.
- Start/cancel/resume discovery jobs.
- Show progress, counts, and failure reasons.
- No secret API keys rendered in the UI or written to logs.

## 11. Security, reliability, and local data safety

- Bind to `127.0.0.1` by default; do not expose to the LAN unless the user explicitly configures it.
- Validate and sanitize URLs; protect against SSRF by blocking loopback/private-network targets for user-supplied remote URLs unless a deliberate local import path is used.
- Limit download sizes, content types, redirect count, request timeouts, and archive extraction.
- Do not execute downloaded files or HTML.
- Use parameterized SQL and safe file paths.
- Keep secrets in environment variables or a local ignored `.env` file.
- Provide database backup, restore, and export commands.
- Do not silently delete or overwrite user files.
- Use atomic writes for downloads and database changes where possible.
- Log provider errors without leaking API keys, cookies, authorization headers, or private user data.
- Make jobs idempotent and safe to retry.

## 12. Testing expectations

At minimum test:
- name normalization and alias matching;
- candidate duplicate scoring and merge undo;
- license-state policy: unknown/restricted assets cannot be locally downloaded;
- provider response parsing using saved fixtures;
- rate-limit/backoff behavior;
- image hash and duplicate detection;
- database migrations and backup/restore;
- API validation and safe local file paths;
- UI filters, decisions, and persistence;
- export integrity and attribution fields.

Tests must not rely on live web services. Use fixtures and mocked HTTP clients. Live integration tests should be opt-in and clearly separated.

## 13. Engineering workflow for Claude Code

Before implementation:
1. Inspect repository structure, existing code, and existing documentation.
2. Read `implementation_plan.md`.
3. Write a concise implementation checklist and identify assumptions.
4. Confirm current source policies from official documentation when implementing a connector; record the policy URL and date in `docs/DATA_SOURCES.md`.
5. Implement the smallest complete vertical slice, then test it.

During implementation:
- Keep functions small and typed where practical.
- Use clear names and structured logging.
- Do not invent undocumented API endpoints.
- Do not hard-code API keys, credentials, or secrets.
- Add tests for every core behavior.
- Keep source adapters isolated.
- If a source's terms or permission state is unclear, implement link-only behavior rather than guessing.
- Update README and data-source notes as behavior changes.

At the end of each phase:
- Run tests and lint/type checks that are configured.
- Summarize files changed, behavior implemented, tests run, and remaining limitations.
- Do not claim a feature works unless it was exercised or tested.
- Do not silently move to a later phase if the current phase's acceptance criteria fail.

## 14. Official policy references to re-check before coding

These URLs are starting points, not a substitute for checking the current terms for each chosen provider:

- OpenStreetMap copyright/license: https://www.openstreetmap.org/copyright
- OSM tile usage policy: https://operations.osmfoundation.org/policies/tiles/
- OSM API usage policy: https://operations.osmfoundation.org/policies/api/
- Wikimedia API access policy: https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy
- Wikimedia reuse of free content: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- Google Places API policies: https://developers.google.com/maps/documentation/places/web-service/policies
- Google Maps JavaScript API policies: https://developers.google.com/maps/documentation/javascript/policies

Before enabling any new provider, record its terms, license, rate limit, caching restrictions, attribution rules, and permitted local retention in `docs/DATA_SOURCES.md`.
