# Hainan Cycling Planner — Claude Code project guide

## 1. Project purpose

Build a local-first web application for planning a bicycle tour around Hainan.
The primary user plans to ride in December or January and uses Garmin Connect
and a Garmin cycling computer.

The product should ultimately let the user:

1. View a map of Hainan, the island loop, and a route itinerary.
2. Browse a researched attraction catalog with locations, original summaries,
   visitor observations, source links, and rights-cleared or user-provided
   photos.
3. Select attractions and generate a practical itinerary along the island
   cycling roads, accounting for detours.
4. See lodging and resupply options along the route, including distances
   between lodging stops and an estimate of whether the next stop is reachable
   given the rider's current position and time.
5. Export the planned ride in a Garmin-compatible format.

Keep candidate research separate from approved travel recommendations. Never
present unverified locations, routes, operating hours, lodging, or supplies as
confirmed facts.

## 2. Product decisions and constraints

- **Local-first:** core catalog content and route data should remain usable
  offline. External source links are provenance, not runtime dependencies.
- **Garmin handoff:** use GPX as the initial interoperable export target for
  Garmin Connect/device transfer. Keep route geometry and export generation
  deterministic application code; do not generate route files with an LLM or
  create FIT files unless a later, verified device workflow requires them.
  Before implementing the final handoff UX, check the user's specific Garmin
  Connect/device import options and distinguish a navigable course from a
  recorded track.
- **Attraction research:** prioritize first-person visitor accounts, including
  cyclist logs and small informal coastal stops. Do not use official tourism
  promotional copy as visitor experience evidence.
- **Xiaohongshu:** use only the user's signed-in browser and ordinary UI;
  review one note at a time. Do not scrape, call unofficial APIs, batch-process,
  bypass access controls, or download/cache user-posted images. Do not simulate
  human activity to evade platform controls.
- **Source quality:** a search card, itinerary list, comment, or promotional
  post is not proof of a firsthand stop. Only attribute what the opened source
  body actually supports. Keep uncertain access, location, date, weather, and
  operating conditions explicit.
- **Images:** do not download or redistribute images unless reuse is
  authorized or the user uploaded them. Keep rights and attribution metadata.
- **Catalog order:** sort the canonical catalog and API by the Haikou-start,
  counterclockwise loop. Preserve stable order within regions unless reliable
  evidence supports a more precise stop sequence. Do not infer order from
  approximate or unverified coordinates.
- **No invented planning assumptions:** when route reachability is calculated,
  make the inputs and assumptions visible (for example, speed, daylight,
  elevation, rest, and weather); do not silently treat estimates as guarantees.
- Preserve current behavior and avoid unrelated changes. Read the relevant
  code, tests, and project docs before editing.

## 3. Current implementation status

This repository is an early Flask application, not yet the complete planner.
The current UI is a single page (`templates/index.html`) with a left sidebar
that switches between seven hash-routed views in `static/js/app.js`: 环岛地图
(map), 景点库 (approved library), 待审核景点 (candidate review), 行程规划
(itinerary), 住宿与补给 (lodging/resupply), Garmin 导出 (export), and
设置与假设 (settings). Only the library and review views load data from the
API; the other five are placeholders that describe planned behavior. The
review view has two controls per candidate: **通过审核** sets the record's
`status` to `approved` (via `POST /api/attractions/<id>/status`) so it appears
in the library, and **删除** permanently removes the record from
`data/attractions.json` (via `DELETE /api/attractions/<id>`) after a browser
confirmation. Both go through `set_attraction_status` / `delete_attraction` in
the repository, which re-validate the whole catalog and write it back atomically
in the existing file style (4-space indent, CRLF, no trailing newline). There is
no undo and no edit control yet. The app does **not** yet implement the Hainan
map, attraction selection, route generation, lodging/resupply management,
reachability estimates, or Garmin export. Treat these as product goals, not
existing features. When adding a view, add its nav link and `data-view` section
to the template and extend the sidebar test in `tests/test_app.py`.

Because the UI can now change statuses and delete records, the repository test
asserts the total record count across all statuses rather than a candidate
count. A UI deletion still changes the catalog and requires updating that count
and the research notes.

The canonical attraction catalog currently contains 128 candidates; 32 have
verified coordinates. The ongoing manual Xiaohongshu review target is 100 note
bodies, with **13/100** inspected as of 2026-10-23. This research is active:
continue one note at a time, maintain the count and disposition in
`docs/attraction-research.md`, and do not count search cards or inaccessible
notes. Update this snapshot when the count or project state changes.

## 4. Repository map

- `app.py` — local development entry point.
- `hainan_cycling/catalog/models.py` — authoritative Pydantic catalog schema
  and source/reference validation.
- `hainan_cycling/catalog/repository.py` — reads and validates the canonical
  catalog, rejects duplicate IDs/unknown regions, and sorts by route order.
- `hainan_cycling/web/routes.py` — Flask page and JSON API.
- `data/attractions.json` — the single canonical attraction catalog.
- `data/media/` — ignored location for user-provided or authorized local
  images; do not add unlicensed images.
- `templates/`, `static/css/`, `static/js/` — browser UI.
- `tests/` — schema, repository, route-order, and HTTP behavior tests.
- `docs/architecture.md` — architectural boundaries and offline contract.
- `docs/attraction-research.md` — evidence policy and research log.
- `.github/instructions/attraction-catalog.instructions.md` — required
  detailed instructions for editing or researching `data/attractions.json`.
- `README.md` — setup, run instructions, and current catalog overview.

## 5. Architecture and implementation guidance

- Keep catalog schemas/data access, Flask routes, browser presentation, map
  rendering, and route calculations in separate modules.
- Keep deterministic route calculations separate from any optional Claude
  workflow. Claude may help propose structured edits, but must not bypass
  application validation or directly mutate canonical data through an
  unvalidated workflow.
- Use the existing Pydantic models and repository helpers rather than
  duplicating validation or route-order logic.
- For a new map/routing provider, check licensing, attribution, offline
  behavior, and whether its data can be cached before adding a dependency.
- Prefer a simple, testable route model with explicit route segments and
  waypoints. Preserve the distinction between an attraction stop, a lodging
  stop, a resupply point, and the road/track geometry.
- Treat lodging and resupply availability as time-sensitive observations;
  the planner should expose source/date and avoid guaranteeing current service.
- Keep the approved mobile/offline export self-contained; source URLs alone do
  not make descriptions or images available offline.

## 6. Attraction catalog rules

Before changing the catalog, read
`.github/instructions/attraction-catalog.instructions.md` and
`docs/attraction-research.md`. These files govern detailed discovery,
deduplication, source, image, coordinate, and review practices.

Key invariants:

- Add candidates only to `data/attractions.json`; do not create numbered batch
  files.
- Every attraction has a unique kebab-case ID, valid region/category, and
  `status: "candidate"` unless the user explicitly requests a status change.
- Check names, aliases, location, and parent attractions before adding a
  record. Merge evidence for the same place into the existing record. Keep a
  sub-location separate only when it is a genuinely distinct, independently
  visitable stop with its own route-planning value.
- A source-backed experience claim references its local
  `visitor_experience` source ID. Store the exact title, platform, canonical
  URL, author/date when available, access date, and a short, original summary.
  Never invent missing author/date/location details.
- `latitude` and `longitude` must be a verified pair; `coordinate_source_id`
  must reference an `objective_reference` source identifying the matching map
  feature. Leave coordinates empty rather than guessing.
- Preserve regional route order:
  Haikou → Chengmai → Lingao → Danzhou → Baisha → Qiongzhong → Changjiang →
  Dongfang → Ledong → Wuzhishan → Baoting → Sanya → Lingshui → Wanning →
  Qionghai → Tunchang → Ding'an → Wenchang → Haikou.
- Update repository/API count assertions, route/order assertions, README and
  research notes when catalog records are added or removed. Validate source
  references and all records against the model.
- While conducting requested research, report meaningful findings as work
  progresses: what note was opened, what it supports, whether a candidate was
  added, an existing record updated, a duplicate left alone, or a lead not
  used. Keep the inspected-note count exact.

## 7. Python environment and commands

Use the project's Conda environment named `cycling` and Python 3.11. The
environment is declared in `environment.yml`; Python dependencies are in
`requirements.txt`.

From PowerShell at the repository root:

```powershell
conda env list
conda env create -f environment.yml
conda run -n cycling python -m pip install -r requirements.txt
conda run -n cycling python app.py
```

Create the environment only if it does not already exist; if setup changes,
follow the manifests and do not create a second environment under another name.
Open <http://127.0.0.1:5000> for the local app.

Run the full test suite:

```powershell
conda run -n cycling python -m pytest -q
```

Run the smallest relevant test selection first when practical, then the full
suite if changes affect shared catalog/API behavior. Do not claim validation
passed unless the command actually completed successfully.

## 8. Documentation and completion checklist

When behavior or data policy changes, update the directly related documentation.
Before finishing a code or catalog task:

1. Confirm the requested behavior and inspect relevant existing patterns.
2. Make a focused change without overwriting unrelated user work.
3. Add or update tests for the behavior and invariants changed.
4. Run the relevant tests in `cycling`; report failures honestly.
5. For catalog edits, verify model validation, unique IDs, source references,
   coordinate references, record count, verified-coordinate count, and regional
   ordering.
6. Summarize what changed, what remains unverified, and the validation result.
