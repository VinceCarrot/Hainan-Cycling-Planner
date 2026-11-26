# Data model

Source of truth: `hainan_explorer/db/migrations/0001_initial.sql`, applied by
`hainan_explorer/db/connection.py` (plain `sqlite3`, WAL mode, foreign keys on). The
migration runner records applied versions in `schema_migrations`.

All timestamps are ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SS.mmmZ`). All coordinates
are WGS84 decimal degrees. JSON columns end in `_json` and are read with a tolerant
`loads()` that falls back to a default when the text is empty or invalid.

## ID and path conventions

| Thing | Convention | Produced by |
|---|---|---|
| Place code | `HN000123` (`HN` + 6-digit zero-padded `places.id`) | `services/common.py: place_code()` |
| Image code | `IMG000456` (`IMG` + 6-digit zero-padded `images.id`) | `services/common.py: image_code()` |
| Local image file | `data/images/<place code>/<image code>.<ext>`, e.g. `data/images/HN000123/IMG000456.jpg`. Images with no associated place go under `data/images/unassigned/`. `<ext>` comes from the MIME type (`.jpg`, `.png`, `.webp`, `.gif`, `.tif`). | `services/images.py: ImageService.download()` |
| Thumbnail | `data/thumbnails/<place code>/<image code>.jpg` (always JPEG, max 480 px) | same |
| Provider-native IDs | `provider_ids(provider, external_id)`, e.g. `osm` / `node/123456`, `wikidata` / `Q42200`, `wikipedia_zh` / `<pageid>`, `legacy_catalog` / `<old id>`, `user_import` / `<file>:<line>:<name>`, `web_mention` / `sha1(url|phrase)[:16]` | each connector |

`places.id` and `images.id` are SQLite `AUTOINCREMENT` integers; the codes are only a
presentation layer and appear in the UI, exports and file paths.

## Sourced fact vs derived estimate vs unknown

The detail API (`PlaceService._facts`) splits a place into three buckets that the UI
renders as 有来源的事实 / 推断·估算 / 未知:

- **Sourced** – coordinates whose `coordinate_precision = 'exact'` (with the provider in
  `coordinate_source`); the description (with its language).
- **Derived** – coordinates that are `approximate` or `centroid`; the county (assigned
  from a boundary polygon or nearest centroid, or inferred from text); `route_distance_km`
  (straight-line distance to the rough corridor, labelled "不是骑行距离").
- **Unknown** – missing coordinates ("需地理核实"); missing county; missing route
  distance; and always "是否开放/可进入: 未知" — the app never claims a place is open or
  reachable (`is_accessible_unknown` defaults to 1 and nothing sets it to 0).

Scores (`confidence_score`, `discovery_score`, `novelty_score`) and image `match_score`
are derived values with stored reasons; they are never presented as facts.

## Tables

### `places`

One row per place candidate. Merged places are kept (never deleted) with
`merged_into_place_id` set; all listing queries filter on `merged_into_place_id IS NULL`.

| Column | Meaning |
|---|---|
| `id` | Primary key; `HN` code is derived from it. |
| `canonical_name` | Display name as found (Chinese preferred: OSM `name:zh`/`name`, Wikidata zh label, Wikipedia title). |
| `normalized_name` | `normalize.normalize_name()` output: NFKC, traditional→simplified table, punctuation/whitespace stripped, lower-cased. Indexed; used for dedup. |
| `name_en` | English name when a provider supplies one (`name:en`, Wikidata en label, en-Wikipedia title). |
| `aliases_json` | JSON list of alternative names (other-language names, `alt_name`, `old_name`, Wikidata aliases, names of merged places, previous canonical names). |
| `country`, `province` | Defaults `CN`, `海南省`. |
| `city`, `county` | Both set to the county-level region name (`regions.REGIONS`, e.g. `文昌市`, `陵水黎族自治县`); the code writes the same value into both. |
| `town` | Reserved; the only write is `COALESCE(town, '')` for nearest-centroid assignments. |
| `latitude`, `longitude` | WGS84; `NULL` when unknown. Coordinates outside the configured bbox are discarded at ingest and the place flagged for geographic verification. |
| `coordinate_source` | Provider that supplied the coordinate: `osm`, `wikidata`, `wikipedia_zh`, `wikipedia_en`, `legacy_catalog`, `user_import`, or `user` (edited in the UI). |
| `coordinate_precision` | `exact` (OSM node, user input), `centroid` (OSM way/relation centre), `approximate` (Wikidata, Wikipedia, CSV, legacy), `unknown`. |
| `geometry_json` | Reserved for a full geometry; not written by current code. |
| `category` | Key from `taxonomy.CATEGORIES` (e.g. `beach`, `cape`, `lighthouse`, `fishing_village`, `historic_village`, `temple`, `waterfall`, `viewpoint`, `village`, `settlement`, `attraction`, `other`, `unknown`). Chinese label via `CATEGORY_LABELS_ZH`. |
| `subcategory` | Free text: OSM discovery group (`coast_features`, `historic`, …), Wikidata class label, or legacy category. |
| `feature_tags_json` | JSON object of retained provider tags: selected OSM tags, `wikidata`, `wikidata_classes`, `has_wikipedia_zh`/`wikipedia_zh`, `has_wikipedia_en`, `legacy_catalog`, … Existing keys win on merge. |
| `description`, `description_language` | First description found (OSM `description`, Wikidata description, Wikipedia intro extract ≤600 chars, legacy summary) and its language (`zh`/`en`). |
| `description_source_id` | Reserved FK to `sources`; not written by current code. |
| `discovery_status` | `new` (default, unused in practice) · `candidate` · `seed` (bare settlement/village/other/unknown with no description; hidden unless 包含村镇种子 is ticked) · `verified` · `excluded` (the last two are not set automatically). |
| `verification_status` | `unverified` · `partially_verified` · `verified` · `disputed`; set by the user (报告问题 sets `disputed`). |
| `needs_geographic_verification` | 1 when coordinates are missing, were outside the bbox, or the candidate came from text mention extraction. |
| `confidence_score` | 0–1; max over contributing candidates (OSM 0.7/0.5, Wikidata 0.75, Wikipedia 0.75, Nominatim 0.65, legacy 0.4, CSV 0.5, web mention 0.3). Research raises it to `0.3 + 0.15×min(4, sources) + 0.2 if coords`. |
| `interest_status` | User decision: `undecided` · `want_to_visit` (想去) · `maybe` (也许) · `skip` (跳过) · `needs_research` (待研究). |
| `interest_score` | Optional 0–10 integer supplied with a decision. |
| `personal_notes` | Free text (我的笔记); legacy import seeds it with research notes and "亮点/注意（来源待核实）" lines. |
| `discovery_reason` | `OSM_feature` · `Wikidata_entity` · `Wikipedia_geosearch` · `Wikipedia_search` · `nearby_expansion` · `travelogue_mention` · `user_import` · `research_relink` · `manual_candidate` (default). |
| `discovery_score` | Transparent ranking score, see "Scores" below. |
| `novelty_score` | 0.1–1.0; lower when the place has a Wikipedia article, is `tourism=attraction`, came from the legacy catalogue, or has ≥6 sources. |
| `route_distance_km` | Straight-line distance to the active `route_corridors` geometry. **Estimate only**, never a cycling distance. `NULL` when no corridor or no coordinates. |
| `is_accessible_unknown` | Always 1; access/opening status is never inferred. |
| `is_coastal` | 1 if the category is coastal or the name contains a coastal hint (海 湾 滩 港 岛 角 礁 洲 灯塔 渔 盐). |
| `source_count`, `image_count`, `local_image_count` | Denormalised counters refreshed by `Ingestor.refresh_counters()` (images exclude `rejected` associations). |
| `research_status`, `researched_at` | `pending` · `done` · `failed`; driven by the research pipeline. |
| `created_at`, `updated_at` | Timestamps. |
| `merged_into_place_id` | FK to the surviving place after a merge; `NULL` for live rows. |

Indexes: `normalized_name`, `county`, `category`, `interest_status`, `(latitude, longitude)`, `merged_into_place_id`.

### `provider_ids`

Stable provider-native identifiers; the strongest dedup evidence.

| Column | Meaning |
|---|---|
| `place_id` | FK → `places` (cascade). Moved to the target on merge, moved back on unmerge. |
| `provider` | `osm`, `wikidata`, `wikipedia_zh`, `wikipedia_en`, `legacy_catalog`, `user_import`, `web_mention`, or the web-search adapter kind (`brave`/`serper`). |
| `external_id` | e.g. `node/123`, `way/456`, `Q42200`, Wikipedia `pageid`, legacy record id. `UNIQUE(provider, external_id)`. |
| `external_url` | Canonical page for the identifier. |
| `raw_json` | Raw provider payload (OSM tags, SPARQL bindings, legacy record, Nominatim subset). The image pipeline reads Wikidata `image`/`commonsCat` from here. |
| `fetched_at` | Last time this id was seen. |

Index: `place_id`.

### `sources`

One row per URL (`UNIQUE(url)`), shared between places.

| Column | Meaning |
|---|---|
| `provider` | `osm`, `wikidata`, `wikipedia_zh/en`, `legacy_catalog`, `user_import`, `user_url`, `web_mention`, `brave`, `serper`. |
| `source_type` | `map_feature` · `knowledge_base` · `encyclopedia` · `web_page` · `travelogue` · `image_page` · `user_note`. |
| `url`, `canonical_url` | Page URL (canonical currently equals `url`). |
| `title`, `publisher`, `author`, `published_at` | Metadata when known (legacy records carry platform/author/date). |
| `retrieved_at`, `last_checked_at` | Timestamps. |
| `access_status` | `fetched` (text was read under the source's rules) · `link_only` (kept as a link, e.g. legacy catalogue, search results) · `blocked` (robots/disabled domain/login wall) · `failed` (HTTP/network/content-type error). |
| `terms_url` | License/terms page (OSM copyright, CC0, CC BY-SA 4.0). |
| `license_notes` | Attribution text, e.g. `© OpenStreetMap contributors, ODbL 1.0`, or the reason a fetch was blocked/failed. |
| `excerpt` | Short text (≤300 chars) supporting the link. |
| `content_hash` | Reserved; not written by current code. |

### `place_sources`

Many-to-many link with evidence. Primary key `(place_id, source_id)`; cascades.

| Column | Meaning |
|---|---|
| `relationship_type` | `describes` (encyclopedic/knowledge-base description) · `mentions` (page text mentions the name) · `locates` (map feature supplies position) · `depicts` (reserved) · `user_note`. |
| `evidence_excerpt` | The sentence or snippet that supports the link (≤300 chars). |
| `confidence_score` | 0–1; updated to the max on re-ingest. |
| `created_at` | Timestamp; used by unmerge to remove links copied during a merge. |

### `images`

One row per remote image file (`UNIQUE(provider, external_id)`), independent of places.

| Column | Meaning |
|---|---|
| `provider` | `commons` is the only provider implemented. (`user_upload`, `web` are reserved.) |
| `external_id` | Commons file title, e.g. `File:Example.jpg`. |
| `source_id` | Optional FK → `sources`; not written by current code. |
| `source_page_url` | Commons file description page. |
| `original_url` | Full-resolution file URL on `upload.wikimedia.org`. |
| `display_url` | Remote URL permitted for display: the Commons thumbnail at `license_policy.download_width` (1600 px). Also the URL that is downloaded. |
| `local_path`, `thumbnail_path` | Relative paths under `data/images` / `data/thumbnails`; `NULL` unless a local copy exists. |
| `title`, `description` | File title without `File:`; `ImageDescription` or `ObjectName`. |
| `creator` | `Artist` or `Credit` from Commons extmetadata (HTML stripped). |
| `attribution_text` | Commons `Attribution` field, else `"<creator>, via Wikimedia Commons, <license>"`. |
| `attribution_url` | File page URL. |
| `license_id` | Normalised identifier: `cc0`, `public domain`, `cc-by-4.0`, `cc-by-sa-3.0`, `cc-by-nc-sa-2.0`, `gfdl`, `fal`, `attribution`, or the raw lower-cased short name. |
| `license_url`, `license_short` | `LicenseUrl` and `LicenseShortName` as supplied. |
| `permission_status` | `local_copy_allowed` · `link_only` · `api_display_only` · `unknown` · `blocked`. Current code produces only the first two plus `unknown` (no license metadata); see `docs/LEGAL_AND_SOURCE_POLICY.md`. |
| `permission_reason` | Human-readable reason for the status (includes Commons `Restrictions` when present). |
| `license_verified_at` | When the license metadata was last evaluated. |
| `width`, `height`, `mime_type`, `bytes` | From Commons; overwritten with the real values after download. |
| `sha256` | SHA-256 of the downloaded bytes (exact-duplicate detection). |
| `perceptual_hash` | 64-bit difference hash (dHash, 16 hex chars) of the downloaded image; near-duplicates at Hamming distance ≤6. |
| `view_type` | Keyword guess from title/description/categories: `aerial`, `sunrise_sunset`, `architecture`, `trail`, `roadside`, `closeup`, `landscape`, `unknown`. Set on insert only. |
| `latitude`, `longitude` | Camera/subject geotag (Commons `coordinates` or GPS extmetadata). |
| `categories_json` | JSON list of Commons categories (≤20). |
| `date_taken` | `DateTimeOriginal`. |
| `retrieved_at`, `last_checked_at` | Timestamps. |
| `download_status` | `not_downloaded` · `downloaded` · `failed` · `removed` (local copy deleted, record kept) · `not_allowed` (download attempted while permission ≠ `local_copy_allowed`). |
| `download_error` | Last error or removal reason. |
| `reported_issue` | Free text from 报告问题. |

Indexes: `sha256`, `perceptual_hash`, `(latitude, longitude)`.

### `place_images`

Association between a place and an image with the transparent match score.
Primary key `(place_id, image_id)`; cascades.

| Column | Meaning |
|---|---|
| `is_primary` | 1 for the card image. Auto-chosen (user-verified → has local file → highest score) when none is set. |
| `association_type`, `association_status` | Both hold the same value: `suggested` · `user_verified` · `rejected`. |
| `match_score` | Sum of the scoring signals in `pipelines.score_image_for_place()`; frozen once `verified_by_user = 1`. |
| `match_reasons_json` | JSON list of reason codes: `name_in_title`, `name_in_description`, `name_in_commons_category`, `english_name_match`, `geotag_within_150m/400m/1km`, `geotag_far`, `linked_from_wikidata_or_wikipedia`, `member_of_linked_commons_category`, `looks_like_map_or_graphic`, `low_resolution`, `county_mentioned`. |
| `confidence_score` | `min(1, match_score / 8)` unless supplied. |
| `verified_by_user` | 1 when the user clicked 确认是此地. |
| `notes` | Association notes (e.g. `reported by user`). |
| `created_at` | Used by unmerge to drop associations copied during a merge. |

Index: `image_id`.

### `discovery_runs`

One row per provider query attempt (coverage bookkeeping).

| Column | Meaning |
|---|---|
| `provider` | `osm`, `wikidata`, `wikipedia_zh`, `wikipedia_en`, `commons`, `brave`, `serper`. |
| `query` | e.g. `overpass:coast_features`, `sparql:bbox`, `geosearch:grid`, or the literal web query. |
| `region_key` | Region key (`haikou`, `wenchang`, …) or `NULL` for island-wide. |
| `category` | OSM group, `all`, `images`, or `web`. |
| `started_at`, `finished_at` | Timestamps. |
| `status` | `running` · `succeeded` · `failed` · `cancelled` · `partial` (only the first three are written by current code). |
| `result_count`, `new_place_count` | Results returned / places created. |
| `error_summary` | Truncated error text. |
| `cursor_json` | Reserved for pagination cursors; not written. |
| `config_snapshot_json` | e.g. the bbox or sweep parameters used. |
| `job_id` | The `jobs.id` that produced the run. |

Index: `(provider, region_key, category)`.

### `jobs`

SQLite-backed queue processed by one worker thread or the CLI.

| Column | Meaning |
|---|---|
| `job_type` | `discover_osm`, `discover_wikidata`, `discover_wikipedia`, `build_corridor`, `nearby_expansion`, `images_for_place`, `images_batch`, `commons_sweep`, `research_place`, `research_batch`, `fetch_url`, `web_search`. |
| `status` | `queued` · `running` · `succeeded` · `failed` · `cancelled` · `retry_wait`. |
| `priority` | 0 (highest) – 10; default 5. Claimed in `priority ASC, id ASC` order. |
| `payload_json` | Job parameters (see `docs/ARCHITECTURE.md`). |
| `dedupe_key` | If an active job (queued/running/retry_wait) has the same key, `enqueue` returns that job instead. |
| `attempt_count`, `max_attempts` | Default 3 attempts; failures wait `min(600, 30·2^attempt)` seconds in `retry_wait`. |
| `created_at`, `started_at`, `finished_at`, `next_run_at` | Timestamps. |
| `last_error` | Last exception text; `recovered after restart` for jobs re-queued after a crash. |
| `progress_json` | Free-form progress (`stage`, `done`, `total`, counters, `result`). |
| `cancel_requested` | Cooperative cancel flag checked by handlers. |

Indexes: `(status, priority, created_at)`, `dedupe_key`.

### `job_logs`

Log lines per job (`job_id` FK cascade, `level`, `message` ≤2000 chars, `created_at`). Index on `job_id`.

### `reviews`

Append-only audit of user actions on a place.

| Column | Meaning |
|---|---|
| `decision` | An `interest_status` value, or `verify`, `merge`, `unmerge`, `coordinates`. |
| `previous_decision` | Interest status before the change (used by undo). |
| `score`, `reason` | Optional score / reason text (for `verify`: the new status; for `coordinates`: old → new). |
| `reviewed_at` | Timestamp. |
| `undone` | 1 after 撤销 (undo). |

Index: `place_id`.

### `place_relations`

Pairwise relations and the duplicate review queue. `UNIQUE(place_id_a, place_id_b, relation_type)`.

| Column | Meaning |
|---|---|
| `relation_type` | `duplicate_of` · `nearby_to` · `part_of` · `alternative_name_of` (the last two are not created automatically). |
| `confidence_score` | 0–1 (0.6 for ingest-time candidates, name similarity/100 for research hits, 0.9 for `nearby_to`, 1.0 for merges). |
| `reasons_json` | e.g. `["name_similar","within_500m","category_agrees"]`, `["research_hit_via_wikidata","name_similarity_88"]`, `["within_1500m"]`. |
| `review_status` | `pending` (awaiting user) · `confirmed` (related but kept separate) · `rejected` (unrelated) · `merged` (a was merged into b) · `undone` (merge reverted). |
| `audit_json` | Merge audit: source snapshot, moved provider ids, copied source/image ids, target aliases before, `merged_at`. Used by unmerge. |

Index: `place_id_b`.

### `route_corridors`

Rough route polylines for triage. Only the `is_active = 1` row is used.

| Column | Meaning |
|---|---|
| `name`, `version` | e.g. `粗略环岛走廊（OSM 城镇连线估算）` / date, or `用户导入路线`. |
| `geometry_json` | GeoJSON `LineString` (`[lon, lat]` pairs). |
| `source_note` | Provenance (OSM attribution or `imported from <file>`). |
| `is_estimated` | Always 1 in current code. |
| `is_active` | Setting a new corridor deactivates the others. |

### `route_segments`

Defined for future route planning (`route_version`, `sequence_no`, start/end place FKs,
`distance_km`, `elevation_gain_m`, `surface`, `source_id`, `is_estimated`, `geometry_json`,
`notes`). Not read or written by current code.

### `settings`

Key/value JSON store (`key`, `value_json`, `updated_at`). Not used by current code.

### `provider_state`

One row per provider, updated when a discovery run finishes: `enabled` (not toggled by
code), `last_run_at`, `last_success_at`, `last_error`, `request_count`,
`rate_limited_count` (not written), `notes`. Shown on the 任务与数据源 page.

### `schema_migrations`

`version`, `name`, `applied_at`; created by the migration runner.

## Relationships

```
places 1──* provider_ids
places *──* sources        (place_sources, with evidence)
places *──* images         (place_images, with score + reasons)
places 1──* reviews
places *──* places         (place_relations: duplicate_of / nearby_to / …)
places *──1 places         (merged_into_place_id)
jobs   1──* job_logs
jobs   1──* discovery_runs (job_id, no FK constraint)
route_corridors (active row) ──> places.route_distance_km (recomputed)
```

## Scores

`services/ingest.py: compute_scores(row)`:

```
novelty = 1.0
  − 0.35 if feature_tags.has_wikipedia_zh
  − 0.15 if feature_tags.has_wikipedia_en
  − 0.10 if tourism=attraction or legacy_catalog
  − 0.10 if source_count ≥ 6
  floor 0.1

discovery_score = category_weight × (0.6 + 0.6 × novelty)
  + min(1.0, 0.25 × source_count)
  + 0.3 if coordinates
  + 0.2 if image_count > 0
  + route bonus: 0.6 (≤3 km) / 0.4 (≤10 km) / 0.2 (≤25 km) from the corridor
  + 0.2 if is_coastal
```

Category weights live in `taxonomy.CATEGORIES` (lighthouse/waterfall/geological/volcano
1.3; cape/reef/cliff/fishing village/salt field/historic village/viewpoint 1.2; …;
village 0.6; settlement 0.3). Popularity (view counts, ratings, search rank) is never an
input.

## Deduplication rules (`services/ingest.py: Ingestor`)

Order of checks for each incoming `Candidate`:

1. **Bbox guard.** Coordinates outside `config.bbox` are dropped and
   `needs_geographic_verification = 1`; the lead is kept without coordinates.
2. **Provider ID match** (`provider_ids`): same `(provider, external_id)` → *update* the
   existing place (following `merged_into_place_id` chains). Never creates a duplicate.
3. **Cross-provider link**: the candidate carries a Wikidata QID that an existing place
   already has; or the candidate *is* a Wikidata entity and an OSM-sourced place has
   `feature_tags.wikidata` equal to that QID → *linked* (update the existing place).
4. **Name + proximity**. Candidate names = normalised canonical name + aliases; "core
   names" additionally strip an administrative prefix (儋州…) and a generic suffix
   (…景区, …公园, …村, …). Existing places are fetched by exact normalised name and by
   `LIKE %core%` (≤50 rows per core). A pair qualifies when names are exact, cores match,
   or `rapidfuzz.ratio ≥ 92`.
   - Both sides have coordinates:
     - ≤ **100 m** and (exact or ≥92 or core match) → **merge** (update existing).
     - ≤ **500 m** and (exact or core match) and categories compatible
       (`_category_compatible`: same, `unknown`/`attraction` involved, or same group such
       as beach/bay/coast/cape/reef/cliff) → **create the new place and a pending
       `duplicate_of` relation** (confidence 0.6).
     - Otherwise, not a duplicate.
   - One side lacks coordinates: county from the region hint must match (or be unknown).
     Exact name and not two bare settlements/villages → **merge**; exact or core match →
     **pending relation**. Two villages with the same name are never merged on name alone.
5. Otherwise **insert** a new place.

Additional rules:

- The research pipeline (`ResearchPipeline._attach_or_relate`) merges a legacy lead into
  a harvested entity only when name similarity ≥92 and the other place has coordinates;
  weaker hits become `duplicate_of` relations with `confidence = similarity/100`.
- `nearby_expansion` records `nearby_to` relations (`confirmed`, 0.9) rather than merging.
- Merges are **reversible** (`PlaceService.merge/unmerge`): the source row stays with
  `merged_into_place_id`, provider ids move, source/image links are copied, the target
  gains the source's aliases, and an `audit_json` snapshot allows exact restoration.
  Nothing is hard-deleted.
- Image duplicates: exact by `sha256`, near by dHash Hamming distance ≤6
  (`ImageService.find_duplicates`), grouped for review without deleting records.
