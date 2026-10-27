# Implementation Plan — Hainan Explorer

## 0. Implementation status (updated 2026-10-27)

Legend: ✅ implemented and exercised · 🟡 implemented, tests only (blocked live) · ⬜ not started

| Milestone | Status | Notes |
|---|---|---|
| M0 skeleton, config, tests | ✅ | `.venv` (Python 3.11), `requirements.txt`, `config/sources.example.yaml`, `.env.example`, 63 pytest tests pass offline |
| M1 database + visual review loop | ✅ | SQLite schema `hainan_explorer/db/migrations/0001_initial.sql`; card grid, filters, sorts, keyboard decisions, undo, detail drawer, notes, export CSV/JSON/GeoJSON, backup/restore |
| M2 provider framework + jobs | ✅ | `jobs` table, worker thread in the server, CLI runner, retry/backoff, cancel, stale-job recovery, coverage matrix |
| M3 OSM + Wikidata discovery | ✅ OSM / 🟡 Wikidata | Overpass island-wide run done (7 tag groups → 990 candidates + 3141 village/town seeds, 18 county polygons cached). Wikidata SPARQL implemented and fixture-tested; live run blocked until `HAINAN_EXPLORER_CONTACT` is set (Wikimedia 403 without contact in User-Agent) |
| M4 Commons images + legal storage | 🟡 | Per-file license parsing, permission states, download guard, SHA-256/dHash, thumbnails, association scoring with reasons, UI badges and report/remove actions — all tested with fixtures; live run blocked by the same contact requirement |
| M5 web search + travelogues | 🟡 | Pluggable Brave/Serper adapter (needs API key), robots-aware page fetcher with domain disable list and SSRF guard, mention extraction to `needs_geographic_verification` leads, paste-a-URL job |
| M6 dedup + evidence review | ✅ | Provider-ID / Wikidata-tag linking, 100 m merge, 100–500 m pending relation, reversible merge with audit, duplicate review page |
| M7 map + corridor | ✅ | Leaflet (vendored) with clustering, OSM tiles configurable, rough corridor built from OSM town nodes (29 points) with straight-line distance labelled as an estimate, GPX/GeoJSON corridor import |
| M8 semantic ranking | ⬜ | Not started by design |
| Legacy catalogue re-research | 🟡 | 128 legacy leads imported as `user_import`; geocoding pass via Nominatim/Overpass runs (`research_batch`); Wikipedia descriptions and Commons images wait on the contact setting |

Known gaps: Wikimedia-backed steps need `HAINAN_EXPLORER_CONTACT`; web search needs an API key; social platforms stay link-only by policy; no route-network distances (straight-line triage only).

## 1. Goal and non-goals

### Goal

Build a Windows-local web app that discovers a broad set of Hainan Island destinations—including lesser-known coastal features, villages, viewpoints, historical/cultural places, unusual landforms, and roadside discoveries—associates candidate images and source evidence, supports fast visual decisions, and exports selected places for later cycling-route planning.

### Non-goals for the first release

- No public hosting or multi-user authentication.
- No automatic route optimization or accommodation booking.
- No promise that every public social platform can be crawled.
- No indiscriminate image downloading.
- No automatic claim that a place is safe, open, accessible, or worth visiting.
- No requirement to use a paid API.
- No autonomous AI agent that browses logged-in accounts or bypasses restrictions.

## 2. Product decisions

- Runtime: Windows, local Python server, browser UI.
- Default bind address: `127.0.0.1`.
- Database: SQLite, migrations, local backups.
- Local images: only user-owned or images whose applicable terms/license allow local retention.
- Link-only records: supported as a first-class state.
- Primary UI: visual card grid; secondary map and evidence views.
- Discovery priority: breadth and novelty over popularity ranking.
- Human review: required for uncertain image-place matches and ambiguous duplicate merges.
- Export: CSV, JSON, GeoJSON; include source URLs and image attribution/rights metadata.

## 3. Milestones

## Milestone 0 — Repository reconnaissance and project skeleton

### Tasks
1. Inspect the current repository and preserve useful existing work.
2. Confirm Python version, Windows constraints, and package manager.
3. Create project layout, configuration example, README skeleton, and architecture/source-policy docs.
4. Set up tests, formatting/linting, and dependency pinning.
5. Define source-adapter interfaces before implementing providers.

### Acceptance criteria
- Project can be installed and launched on Windows using documented commands.
- No API key or secret is committed.
- `CLAUDE.md`, this plan, and README agree on the chosen stack and directory structure.
- A test command is documented and succeeds.

## Milestone 1 — Local database and usable visual-review loop

This is the first end-to-end deliverable. It must work even before web discovery is automated.

### Tasks
1. Implement SQLite schema and migrations for places, sources, place_sources, images, place_images, discovery_runs, jobs, reviews, place_relations; route_segments can be added now or deferred.
2. Add repository/service layer and validation.
3. Add CSV/JSON import with preview, validation errors, and duplicate warnings.
4. Build the card-grid UI with placeholders for missing images.
5. Implement search, region/category/status/image-state filters, sorting, pagination or virtualized loading.
6. Implement interest decisions: undecided, want to visit, maybe, skip, needs research.
7. Add place detail view with source list, aliases, coordinates, image metadata, notes, and audit/review history.
8. Add undo for decisions and avoid destructive deletes.
9. Add backup, restore, and export.

### Acceptance criteria
- A sample dataset can be imported and displayed.
- Decisions survive app restart.
- A place can have multiple sources and multiple images.
- A link-only image appears as a source link, not a broken local image.
- A user can filter to only undecided places and quickly mark several places.
- Export preserves IDs, aliases, coordinates, source URLs, interest state, and image rights metadata.
- Automated tests cover schema, import/export, decisions, and basic API behavior.

## Milestone 2 — Provider framework and job queue

### Tasks
1. Define a common discovery-provider contract, e.g. `search(region, categories, cursor) -> candidates`.
2. Define a common image-provider contract, e.g. `search_images(place) -> image_candidates`.
3. Add SQLite-backed jobs with queued/running/succeeded/failed/cancelled states.
4. Add progress reporting, retry budgets, per-provider concurrency/rate settings, and resume after restart.
5. Store a run record for each query and a normalized record for each result.
6. Add provider enable/disable controls and show provider-specific errors.
7. Add fixtures and mocked tests; do not require live network access in normal tests.

### Acceptance criteria
- Jobs are idempotent and can resume after interruption.
- Re-running the same query does not create unlimited duplicate records.
- A failed provider does not prevent other providers from running.
- Rate-limit responses trigger backoff and do not cause an aggressive retry loop.
- Logs do not expose secrets or cookies.

## Milestone 3 — Geographic discovery: OSM + Wikidata

### Tasks
1. Build configurable Hainan boundary/region seeds and administrative-area seed data.
2. Implement OSM/Overpass or regional-extract import using an appropriate read-only source; do not bulk-query the OSM editing API.
3. Query broad categories of natural features, villages/localities, historical sites, viewpoints, coastal infrastructure, and attractions.
4. Implement Wikidata discovery for geographic entities, coordinates, administrative relationships, official websites, sitelinks, and Commons references where available.
5. Store provider IDs and raw source evidence.
6. Build regional/category coverage reports.
7. Add nearby-feature expansion around known places.
8. Include unknown-coordinate candidates in a review queue instead of discarding them.

### Acceptance criteria
- User can run discovery for one region/category without scanning all Hainan.
- The system records what region, category, query, and provider were attempted.
- Candidates preserve provider IDs, coordinates, feature types, and attribution metadata.
- A candidate with no photo is still retained.
- OSM attribution and license information are visible in the UI/docs.
- Coverage view shows successful, failed, and not-yet-run regions/categories.

## Milestone 4 — Open image discovery and legal local storage

### Tasks
1. Implement Wikimedia Commons image search and metadata parsing.
2. Capture file/page URLs, title, creator, license, license URL, attribution, dimensions, categories, and description.
3. Implement image permission states: local_copy_allowed, link_only, api_display_only, unknown, blocked.
4. Implement an explicit download policy: no local copy for unknown or restricted rights states.
5. Add local image storage by stable IDs and generate thumbnails only when permitted.
6. Add SHA-256 and perceptual hashes for local files.
7. Implement image association scoring and show its reasons.
8. Add “verify image/place association” and “report wrong image” controls.
9. Add placeholder states for no image, link-only, remote/API display, and unverified match.

### Acceptance criteria
- An open-license image record shows creator, license, and source link.
- Unknown-license candidates are not downloaded.
- Re-running image search is idempotent.
- Exact duplicate local files are detected by SHA-256.
- Near-duplicate images can be grouped for review without deleting source records.
- Weak image matches are visibly marked unverified.
- Attribution metadata survives export.

## Milestone 5 — Web search and public travelogue discovery

### Tasks
1. Choose a search provider whose documented terms permit the intended queries and storage of result metadata; make it configurable.
2. Build query templates in Chinese, with variants for Hainan administrative areas, localities, geographic features, cycling, photography, and travelogues.
3. Search in regional/category batches to reduce popularity bias.
4. Parse permitted public pages for title, publisher/author, date, short relevant excerpts, named places, aliases, and image references.
5. Build candidate-place extraction with source evidence.
6. Add “nearby/related place” expansion from new names and linked pages where allowed.
7. Add domain-level throttle, access-status tracking, robots/terms notes, and a disable switch.
8. For sources that do not allow automated extraction or image reuse, save the source link for manual review only.
9. Optionally support user-imported bookmarks, CSVs, GPX, GeoJSON, or manually pasted URLs.

### Query families to implement

Use configurable templates rather than a hard-coded list. Examples:

- `海南 {市县/乡镇} 小众景点`
- `海南 {地名} 海湾/岬角/礁石/海蚀地貌/灯塔`
- `海南 {地名} 渔村/老码头/古村/历史遗迹`
- `海南环岛骑行 {地名/区域} 沿途/支线/观景点`
- `{地名} 游记/摄影/徒步/骑行/航拍`
- `{乡镇名} 海岸线/自然景观/地质景观`
- `海南 {地名} 日出/日落/海岸/湿地/山林`
- Alternate Chinese spellings, old names, local names, and English transliterations when useful.

### Acceptance criteria
- A run can search a selected region and category and save all permitted result metadata.
- Every extracted candidate has a supporting source or is explicitly labelled as an unverified suggestion.
- A user can open the original source page from the app.
- Restricted pages are not bypassed.
- Query, provider, timestamp, and result URL are recorded.
- The app reports search failures and partial coverage rather than claiming completeness.

## Milestone 6 — Conservative deduplication and evidence review

### Tasks
1. Normalize names while retaining original strings.
2. Add alias and transliteration matching.
3. Generate duplicate candidates using provider IDs, name similarity, coordinates, category, admin area, and source evidence.
4. Distinguish duplicate, part-of, and nearby relationships.
5. Create a duplicate review UI with side-by-side names, coordinates, images, and source evidence.
6. Add reversible merge/undo and audit history.
7. Add duplicate-image grouping using file hashes and perceptual hashes.

### Acceptance criteria
- Same provider IDs are matched reliably.
- Similar names in different towns are not blindly merged.
- A parent scenic area and its distinct sub-location can remain separate.
- Merge preserves source and image associations and can be undone.
- All automatic merge thresholds are configurable and documented.

## Milestone 7 — Map and cycling relevance

### Tasks
1. Add Leaflet map with clustering and category/status filters.
2. Use a configurable tile provider; display required attribution.
3. Show selected places and unreviewed candidates.
4. Add route corridor import via GPX/GeoJSON.
5. Calculate approximate straight-line distance to route as a triage metric only.
6. Later, optionally calculate road-network detours with an appropriate routing provider or local routing engine.
7. Label estimates and route-data timestamps clearly.
8. Export selected places in route order or grouped by region.

### Acceptance criteria
- Map positions match stored coordinates.
- Missing or low-confidence coordinates are visibly indicated.
- Straight-line distance is never labelled as cycling distance.
- Map attribution is visible.
- User can export selected places and associated evidence.

## Milestone 8 — Optional semantic ranking and polish

Only start after core discovery, rights metadata, and manual review are stable.

### Tasks
1. Add optional local image-text embeddings or a vision-language model to rank likely matches and classify view types.
2. Keep model outputs as suggestions, with confidence and explanation; never make them proof of identity.
3. Add novelty/coverage score so obscure places are not buried under popular attractions.
4. Add broken-link checks with conservative rate limits.
5. Add optional scheduled local discovery runs.
6. Improve keyboard navigation, accessibility, performance, and database maintenance.

### Acceptance criteria
- AI-assisted rankings can be disabled.
- No AI-generated name is considered confirmed without source evidence.
- User decisions are not overwritten by automated re-ranking.
- The system remains usable without a GPU or external AI service.

## 4. Discovery data policy

### Candidate inclusion

Keep candidates if they have at least one of:
- a geographic entity or map feature with a name or meaningful feature type;
- a source page explicitly mentioning the place;
- a plausible named feature extracted from a permitted travelogue;
- a user-supplied name, coordinate, GPX waypoint, or URL.

Unverified leads should be retained with lower confidence and a clear status. Do not invent names to fill coverage gaps.

### Priority scoring

Use transparent components, for example:
- evidence strength;
- novelty relative to mainstream tourism lists;
- under-covered area/category;
- likely relevance to the cycling route;
- whether the place is unreviewed or lacks useful imagery.

Do not rank purely by review count, popularity, search rank, or number of commercial listings.

### Coverage

Track coverage by:
- administrative area;
- coast/inland;
- feature category;
- source family;
- candidates with verified coordinates;
- candidates with at least one correctly associated image;
- unreviewed/low-confidence candidates.

Do not report “all Hainan attractions found.” Report measurable coverage and limitations.

## 5. Image and licensing policy

Before implementing each image provider, verify its current official terms and record them in `docs/DATA_SOURCES.md`.

Each image must have a permission state. The application must not download or persist bytes when permission is unknown, restricted, or only allows API display. Search results are leads, not licenses. A public page is not automatically a reuse license.

For open-license images, retain license identifier/URL, creator, attribution text, source page, retrieval time, and any applicable share-alike or other requirements. Display attribution next to the image or in a clearly accessible details panel.

Do not store Google Places photos as a permanent archive. If an API provider has caching/display constraints, isolate its integration and obey current policies. Do not use screenshotting, proxying, or hotlink workarounds to evade restrictions.

## 6. Suggested database enum values

- `interest_status`: `undecided`, `want_to_visit`, `maybe`, `skip`, `needs_research`.
- `discovery_status`: `new`, `candidate`, `verified`, `excluded`.
- `verification_status`: `unverified`, `partially_verified`, `verified`, `disputed`.
- `permission_status`: `local_copy_allowed`, `link_only`, `api_display_only`, `unknown`, `blocked`.
- `association_status`: `suggested`, `user_verified`, `rejected`.
- `job.status`: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `retry_wait`.
- `place_relations.relation_type`: `duplicate_of`, `part_of`, `nearby_to`, `alternative_name_of`.

## 7. Initial project layout

```text
HainanExplorer/
  CLAUDE.md
  implementation_plan.md
  README.md
  pyproject.toml
  config/
    sources.example.yaml
  docs/
    ARCHITECTURE.md
    DATA_MODEL.md
    DATA_SOURCES.md
    LEGAL_AND_SOURCE_POLICY.md
  app/
    main.py
    api/
    db/
    models/
    services/
    discovery/
      base.py
      osm.py
      wikidata.py
      commons.py
      web_search.py
      imports.py
    images/
    dedup/
    routing/
    ui/
  data/
    explorer.db
    images/
    thumbnails/
    imports/
    exports/
    backups/
  logs/
  tests/
    fixtures/
```

Keep generated/user data outside version control. Include a `.gitignore` for databases, local images, exports, logs, `.env`, and caches, while retaining empty-directory documentation if needed.

## 8. First vertical slice: exact implementation order

Claude Code should implement this sequence first:

1. Inspect repo and report existing assets.
2. Create schema/migrations and a small synthetic fixture dataset.
3. Build list/card/detail UI and decisions.
4. Add import/export and backup/restore.
5. Add source links and image-rights states.
6. Add job table and provider interface.
7. Implement one OSM discovery path and test it with fixtures.
8. Implement Commons search/metadata and legal download guard.
9. Add regional query templates and coverage report.
10. Add duplicate review and reversible merge.
11. Add permitted web search adapter.
12. Add map and route corridor import.

Do not start with the most complex web scraping. The app should be useful after step 4.

## 9. Definition of done for MVP

The MVP is done when:
- It runs locally on Windows with documented setup.
- A user can import, view, search, filter, decide, annotate, and export places.
- It can discover geographic candidates from at least one open geographic source.
- It can search an open image source and preserve per-image licensing/attribution.
- It refuses to locally download images with unknown or restricted permission states.
- It records provenance for each candidate and image.
- It supports duplicate review and does not silently discard ambiguous candidates.
- Jobs are resumable and rate-limited.
- Tests cover core business logic and do not depend on live services.
- Documentation clearly states what is and is not automated.

## 10. Current source-policy references

Re-check before implementing and record the date checked:
- OSM license: https://www.openstreetmap.org/copyright
- OSM tile policy: https://operations.osmfoundation.org/policies/tiles/
- OSM API policy: https://operations.osmfoundation.org/policies/api/
- Wikimedia API access policy: https://www.mediawiki.org/wiki/Wikimedia_APIs/Access_policy
- Wikimedia Commons reuse: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- Google Places API policies: https://developers.google.com/maps/documentation/places/web-service/policies
- Google Maps JavaScript API policies: https://developers.google.com/maps/documentation/javascript/policies
