# Architecture

Hainan Explorer is a single-process, local-first Python application: a FastAPI server
serving a vanilla-JS single page UI, a SQLite database, a background worker thread that
runs discovery/research/image jobs, and a CLI that drives the same services without the
server. Everything lives in the `hainan_explorer/` package.

## Components

```
hainan_explorer/
  config.py          YAML + .env loading, LicensePolicy, HAINAN_BBOX, Wikimedia contact guard
  http.py            shared httpx client: UA, per-host throttle, backoff, log redaction
  normalize.py       name normalisation, prefix/suffix stripping, rapidfuzz similarity
  geo.py             haversine, bbox, point-in-polygon, distance to polyline, grid points
  regions.py         18 county-level regions (OSM relation ids, centroids, route order),
                     RegionIndex (polygon cache -> nearest centroid), text -> region
  taxonomy.py        category taxonomy, OSM tag rules, Wikidata class rules, keyword rules,
                     OSM_DISCOVERY_QUERIES
  db/connection.py   sqlite3 helpers, migration runner, Database (per-thread conn, write lock)
  db/migrations/     0001_initial.sql
  services/
    context.py       AppContext: config + Database + HttpClient + RegionIndex
    common.py        now_iso, JSON helpers, place_code/image_code
    ingest.py        Candidate/SourceSpec, Ingestor (dedup), compute_scores
    places.py        PlaceService: listing/filters/sorts, detail, decisions+undo, notes,
                     merge/unmerge, relations, summary
    images.py        ImageCandidate, license evaluation, ImageService (upsert, associate,
                     download guard, hashes, thumbnails, remove, duplicates, leads)
    jobs.py          JobService: SQLite queue, worker thread, retry/cancel, JobRun handle
    coverage.py      discovery_runs + provider_state bookkeeping, coverage matrix
    corridor.py      CorridorService: active corridor, OSM default corridor, distances
    importer.py      legacy catalogue, CSV, GPX/GeoJSON corridor imports
    export.py        ExportService (CSV/JSON/GeoJSON), BackupService (backup/restore)
  discovery/
    osm.py           OverpassClient (+mirror fallback), category/nearby/name queries
    wikidata.py      SPARQL bbox paging, entity search, binding -> Candidate
    wikipedia.py     geosearch grid sweep, title search, page -> Candidate
    commons.py       CommonsClient (search/geosearch/category/imageinfo), page -> ImageCandidate
    nominatim.py     single-lead geocoding
    web_search.py    WebSearchAdapter (Brave/Serper), PageFetcher, mention extraction
  pipelines.py       job handlers; ImagePipeline (scoring with reasons); ResearchPipeline
  api/routes.py      REST API under /api; api/schemas.py Pydantic request models
  main.py            create_app() factory, static mounts, run()
  cli.py / __main__  python -m hainan_explorer <command>
  ui/index.html, ui/static/app.js, app.css, vendor/ (Leaflet 1.9.4, markercluster 1.5.3)
```

`AppContext` is created once per process. It loads config, ensures `data/*` directories,
runs pending migrations, builds the HTTP client with per-host rate limits, and loads the
region polygon cache (`data/cache/hainan_regions.geojson`) if present.

## Data flow

### Discovery → Ingestor → places

```
Overpass / Wikidata SPARQL / Wikipedia geosearch / Nominatim / page text
        │  provider-specific parsing (discovery/*.py)
        ▼
   Candidate(provider, external_id, name, aliases, lat/lon, precision, category,
             tags, description, sources=[SourceSpec...], wikidata_id, region_hint,
             image_hints, needs_geographic_verification, confidence)
        │
        ▼
   Ingestor.ingest()            (services/ingest.py, one transaction per candidate)
     1. bbox guard
     2. provider_ids exact match            -> update
     3. cross-provider Wikidata/OSM link    -> linked
     4. name + proximity                    -> merge, or create + pending duplicate_of
     5. insert; assign region (polygon -> centroid -> text hint); seed vs candidate
     6. upsert sources + place_sources evidence; refresh counters; compute scores
        │
        ▼
   places / provider_ids / sources / place_sources / place_relations
```

Each job records a `discovery_runs` row (provider, query, region, category, counts,
error) so the 任务与数据源 page can show coverage, failures and OSM groups never run.
After discovery jobs, `CorridorService.recompute_distances()` refreshes
`route_distance_km` and the discovery scores.

### Research pipeline (legacy leads and thin places)

`ResearchPipeline.research(place_id)` (job `research_place` / `research_batch`):

1. If the place has no Wikidata id: `wbsearchentities` for up to 3 name variants,
   accept labels with similarity ≥80, fetch their bindings, keep those inside the bbox,
   ingest with `discovery_reason = research_relink`.
2. If still no coordinates: Nominatim (≤3 variants, county suffix, similarity ≥80), then
   Overpass regex name search (similarity ≥85). A Nominatim hit whose class is infrastructure
   (railway, highway, building, aeroway, public_transport, office, shop) is skipped unless the
   place itself is infrastructure-like (`nominatim_hit_compatible`): "棋子湾" the bay must not be
   pinned to "棋子湾" the railway station. Skips are listed in the job result as `geocode_skipped`.
3. If no zh/en description: zh-Wikipedia title search, accept similarity ≥85 and a Hainan
   signal (bbox, "海南" or the county in the extract).
4. Images via `ImagePipeline.process_place`.
5. Mark `research_status = done`, raise `confidence_score`, and position the place on the
   route book (`RouteService.position_place`: day, km along the day, straight-line detour) or,
   without a route book, store the plain corridor distance. Coordinates pinned by hand in the
   detail drawer (`PATCH /api/places/{id}`) go through the same positioning.

When a research hit resolves to a *different* existing place, `_attach_or_relate` merges
only if similarity ≥92 and the other place has coordinates (reversible merge with audit);
otherwise it records a pending `duplicate_of` relation for the user.

### Image pipeline

`ImagePipeline.collect_for_place` gathers Commons candidates from four channels: files
linked from Wikidata P18 / Wikipedia page image (`linked`), members of the Wikidata P373
category (`from_category`), full-text file search for name variants, and geosearch
around the place. `score_image_for_place` returns a score **and the list of reasons**
(see `docs/DATA_MODEL.md` → `place_images.match_reasons_json`). Candidates below
`min_match_score` (2.0) are dropped unless `linked`; the rest are upserted as `images`,
associated with the score, and `download_for_place` fetches the permitted ones through
the single download guard. `commons_sweep` runs geosearch over the whole island and
attaches each geotagged file to the best-scoring place within ~0.01°, or keeps it as an
unassigned lead (图片线索).

### Jobs

- `jobs` table is the queue. `JobService.enqueue` dedupes on `dedupe_key`
  (the API builds it from job type + sorted payload).
- `JobService.start_worker()` (called in the FastAPI lifespan) re-queues jobs left
  `running` by a crash, then runs a daemon thread that claims the next job
  (`priority ASC, id ASC`, or `retry_wait` whose `next_run_at` has passed) inside a
  `BEGIN IMMEDIATE` transaction and executes its handler.
- Handlers receive a `JobRun` with `log()`, `progress(**fields)` and `check_cancelled()`.
  Cancellation is cooperative (`cancel_requested`), checked between items.
- Failures go to `retry_wait` with `min(600, 30·2^attempt)` seconds delay, up to
  `max_attempts` (3), then `failed`. 重试 / 重试失败任务 re-queue.
- The CLI runs the same handlers synchronously (`run`, `run-jobs`), so discovery can be
  driven from a terminal without the server. Both the worker and the CLI claim jobs
  transactionally.
- Handlers are idempotent: everything upserts, so re-running a job refreshes rather than
  duplicates.

Job types and payloads (`pipelines.register_handlers`):

| Job | Payload keys (defaults) |
|---|---|
| `discover_osm` | `groups` (all OSM groups), `region` (whole island) |
| `discover_wikidata` | — |
| `discover_wikipedia` | `lang` (`zh`) |
| `build_corridor` | — |
| `nearby_expansion` | `place_id`, `radius_m` (1500) |
| `images_for_place` | `place_id`, `download` (true) |
| `images_batch` | `only_without_images` (true), `region`, `with_coords_only`, `limit` (500), `download` (true) |
| `commons_sweep` | `step_km` (8), `radius_m` (6000), `download` (true) |
| `research_place` | `place_id`, `with_images` (true) |
| `research_batch` | `provider`, `pending_only` (true), `region`, `place_ids`, `limit` (1000), `with_images` (true) |
| `fetch_url` | `url`, `max_new` (40) |
| `web_search` | `region` (all regions); requires a configured search API |

### API and UI

`api/routes.py` exposes `/api/meta`, `/api/summary`, `/api/places` (filters, sorts,
pagination), `/api/places/{id}` (detail with facts/sources/images/relations/nearby/
reviews), decisions (`/decision`, `/bulk-decision`, `/undo`), `PATCH /api/places/{id}`
(notes, verification, name, category, coordinates), merge/unmerge, `/api/relations`,
image association/report/download/remove-local, image leads and duplicates, jobs CRUD,
`/api/leads/url`, `/api/coverage`, `/api/corridor`, `/api/routes` (route-book summary
with per-day counts), `/api/routes/geojson` (one LineString per day), `/api/map/places`
(GeoJSON, optional `day`), `POST /api/import/routes` (import `data/<subdir>/*.gpx` as the
route book; `crs` = wgs84 | gcj02 | bd09), `POST /api/routes/crs` (re-interpret the imported
coordinates and rebuild detours), `POST /api/export/gpx` (per-day GPX with chosen places as waypoints), `POST /api/export/trip-plan`
(build the single-file phone trip page from `manual_planning.txt`),
export/import/backup/restore, and `/api/policy` (this repo's policy document). Swagger UI
is at `/api/docs`. Local files are served from `/media/images`, `/media/thumbnails` and
`/static`.

The UI (`ui/static/app.js`) is hash-routed (`#/review`, `#/map`, `#/duplicates`,
`#/leads`, `#/jobs`, `#/data`, `#/review/<id>` opens the drawer), keeps filters in
`localStorage` (`hx.filters`), polls `/api/summary` every 15 s and the jobs page every 5 s.

### Route book (per-day tracks)

`services/routes.py` (`RouteService`) owns the user's own route. `import_directory` parses
every GPX in a folder, derives the day number from `Day<N>` in the file or track name,
stores each track in `route_segments` (`route_version`, `day_number`, full geometry with
elevation, length, hysteresis-filtered climb, start/end), records the version in
`settings.active_route_version`, and inserts the merged, simplified line as the active
`route_corridors` row with `is_estimated=0`. `recompute_positions` then assigns every place
with coordinates to its nearest day using Douglas-Peucker-simplified tracks (25 m) with a
bbox pre-filter: `route_day`, `route_day_km` (km from the day's start to the projection
point) and `route_distance_km` (straight-line detour). `CorridorService.recompute_distances`
delegates to it whenever the active corridor is the route book, so discovery jobs keep the
fields current; importing a single corridor file clears the route book instead.
`export_gpx` writes one GPX per day with the track and the selected places as `<wpt>`.
Everything is a geometric estimate and is labelled as such in the API (`distance_note`),
the facts panel ("路书位置", derived) and the UI.

Coordinate systems live in `crs.py` (WGS-84 ⇄ GCJ-02 ⇄ BD-09, GeoJSON lon/lat order, iterative
GCJ-02 inverse). A route book declares the system its files were drawn in
(`settings.active_route_crs`, `route_segments.source_crs`); `source_geometry_json` keeps the
parsed GPX verbatim and `geometry_json` holds the WGS-84 conversion that the map, the corridor
and `recompute_positions` use. `set_crs` rebuilds everything from the source geometry, so the
choice is reversible and the user's files are never rewritten. `export_gpx` writes the track
from the source geometry and converts waypoints into that system. Which system a given file
uses was checked empirically for the user's Garmin Connect China courses (27 sample points vs
OSM highways: median 120 m raw, 2.8 m after GCJ-02 → WGS-84, 228 m with BD-09), but the
default stays WGS-84 and the user chooses explicitly.

### Phone trip page

`trip_plan.py` turns the user's free-text plan into `data/exports/trip-plan.html` by inlining
`ui/trip_template.html`, the vendored Leaflet CSS/JS and a JSON payload. `parse_plan` is a small
line parser (day headers, 景点/住宿/补给 sections, bullet checklists; a colon or spaces inside a
checklist line become sub-items). `TripPlanBuilder` resolves each attraction line against
`places` (exact canonical name or alias first, then LIKE; among matches prefer the one on that
route day, then exact precision, then smallest detour), anchors lodging on the route segment's
end point, embeds a 20 m-simplified WGS-84 track per day, and flags days whose route end is
more than 2 km from a lodging reference. The page itself is plain JS with hash routes and
localStorage (checklists, pins, start date); the OSM tile server is its only network dependency.

## Design decisions

- **`sqlite3` from the standard library, no ORM.** One schema file, explicit SQL,
  `sqlite3.Row`, WAL mode, a process-wide write lock (`Database.transaction`) and
  per-thread connections. Simple to back up (`Connection.backup`) and inspect.
- **Vanilla JS UI, vendored Leaflet.** No build step; `index.html` + one JS and one CSS
  file. Leaflet 1.9.4 (BSD-2) and Leaflet.markercluster 1.5.3 (MIT) are committed under
  `ui/static/vendor` so the UI works offline apart from map tiles and remote images.
- **Providers behind small clients.** Each connector maps provider payloads to
  `Candidate` / `ImageCandidate`; the ingest and image services never see provider
  specifics. Enabling/disabling and intervals are configuration.
- **Rough corridor from OSM towns, straight-line triage only.** The default corridor is
  a polyline through ~33 OSM town/village nodes along the coastal ring, resolved live
  from Overpass (nothing invented). `route_distance_km` is the shortest straight-line
  distance to that polyline, labelled as an estimate everywhere (UI, facts panel,
  exports). The user can replace it with a GPX/GeoJSON track. No routing engine.
- **Conservative merging, reversible audit.** Automatic merges only on provider id,
  Wikidata cross-link, or near-identical name within 100 m; everything weaker becomes a
  pending relation for the 去重审核 page. `merge()` keeps the source row, copies links,
  moves provider ids and stores an `audit_json`; `unmerge()` restores from it.
- **Decisions are an append-only log.** `reviews` records every interest decision with
  the previous value; undo flips `undone` and restores the previous status.
- **Scores are transparent and anti-popularity.** Novelty penalises Wikipedia coverage
  and `tourism=attraction`; image matches store reason codes; nothing uses view counts
  or ratings.
- **Legal-by-design acquisition.** A single download guard, a configurable license
  allow-list, Wikimedia-only download hosts, robots/SSRF/login-wall checks, and
  link-only as a first-class state. See `docs/LEGAL_AND_SOURCE_POLICY.md`.
- **Secrets only in the environment.** YAML may reference `${VAR}`; `.env` is loaded
  into the environment and git-ignored; URLs are redacted in logs.

## Known limitations

- **Wikimedia connectors are off until `HAINAN_EXPLORER_CONTACT` is set** (by policy).
- **Region polygons**: `RegionIndex` reads `data/cache/hainan_regions.geojson`. The
  `build_regions` job (also run automatically at the start of `discover_osm` when the cache
  is missing) fetches the 18 county relations from Overpass and writes the cache. Until it
  exists, places are assigned to the nearest county centroid (≤80 km), which is wrong near
  borders.
- **Bounding box, not a polygon**, is the island filter; near-shore islets are inside, but
  so is some sea.
- **Web page throttle**: `providers.web_pages.min_interval_seconds` is the default per-host
  interval for every host without its own provider entry (minimum 1 s).
- **No web search without an API key**; only Brave and Serper are implemented, `custom`
  is not. The `{place}`-level query templates are defined but no job uses them.
- `permission_status` values `api_display_only` and `blocked` are never produced;
  restricted licenses become `link_only`.
- `places.town`, `geometry_json`, `description_source_id`, `sources.content_hash`,
  `images.source_id`, `discovery_runs.cursor_json` and
  `provider_state.enabled/rate_limited_count` exist in the schema but are not populated
  (`route_segments` and `settings` are used by the route book).
- The default corridor is a straight-line polyline between towns; it does not follow
  roads, and inland regions have no corridor at all. Importing the route book replaces it
  with the real tracks, but detour distances remain straight-line, not routed.
- Garmin Connect's treatment of `<wpt>` in imported GPX files is not verified for the
  Edge 1050; exported course points must be checked in Garmin Connect before a ride.
- `logs/` is created but the app logs to stderr only.
- Single worker thread: long jobs (Wikipedia grid sweep, Commons sweep) block other jobs
  until finished or cancelled.
- `BackupService.restore` closes only the calling thread's connection; restoring while
  the worker thread holds a connection may fail on Windows. Prefer restoring from the CLI
  with the server stopped.
- Tests (`tests/`) run against fixtures with no network; live integration tests do not
  exist.
