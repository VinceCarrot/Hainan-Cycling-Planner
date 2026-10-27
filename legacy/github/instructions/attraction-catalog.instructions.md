---
description: "Use when researching, adding, editing, or reviewing Hainan attraction-catalog candidates in JSON, including small coastal spots, informal viewpoints, cyclist check-ins, and visitor-source evidence."
applyTo: "data/attractions.json"
---

# Hainan attraction-catalog research instructions

Use these rules when building or extending the first-pass, user-reviewable
attraction candidate catalog. The project policy and image rules are in
[`docs/attraction-research.md`](../../docs/attraction-research.md); the
Pydantic schema in `hainan_cycling/catalog/models.py` is authoritative.

## What belongs in the catalog

- Cover the island cycling corridor and useful detours. Include small,
  informal, coastal, village, or rider-check-in places (for example, a named
  sea cave or viewpoint) as well as developed scenic areas.
- Research the coastal loop in this order: start in Haikou, go
  counterclockwise through Chengmai, Lingao, Danzhou, Changjiang, Dongfang,
  Ledong, Sanya, Lingshui, Wanning, Qionghai, and Wenchang, then return to
  Haikou. Also search inland areas and detours across Hainan, not only
  developed/coastal scenic areas.
- When the user prioritizes cycling-roadside or coastal coverage, focus first
  on beaches, small beach access points, headlands, reef shores, viewpoints,
  fishing harbors, and rider check-in stops that can be matched to the loop.
  Prefer evidence about an actual stop and its approach over generic lists of
  popular attractions.
- Prefer a precise, independently meaningful stop over a broad administrative
  area. Before adding a named viewpoint, beach access, landmark, or other
  sub-location, check whether it is simply one part of an existing candidate.
  If multiple visitor notes describe the same attraction complex, merge their
  source evidence and distinct observations into the existing attraction;
  record useful internal stop names in its summary or `research_notes` rather
  than creating duplicate candidates. For example, the two named viewpoints
  inside Dongjiao Coconut Grove are sub-stops of the same attraction and
  belong in its record, not as two extra attractions. Keep a sub-location as
  its own candidate only when it is a genuinely distinct, independently
  visitable stop with its own evidence and practical route-planning value.
- A user suggestion can be recorded as a candidate lead, but do not invent
  visitor feedback or claim popularity without a traceable visitor source.

## Sources and claims

- Prefer public, first-person visitor trip reports, cycling logs, vlogs, and
  personal blogs. Search Mafengwo, Ctrip travelogues, Bilibili, Xiaohongshu,
  and comparable platforms where access and use are lawful. Do not use
  official tourism promotional copy as visitor experience evidence.
- For Xiaohongshu research, use only the user's signed-in browser and normal
  interface, opening and reviewing one note at a time. Do not use crawlers,
  unofficial APIs, bulk processing, or attempts to bypass login, CAPTCHA, or
  access controls. For this project, analyze note text only: do not download,
  cache, or reuse user-posted images. Keep any summary short and in original
  wording, cite the note URL, and distinguish the author's firsthand visit
  from general itinerary or promotional claims.
- When cross-checking an existing candidate, search for the same named place
  or clearly matching beach/shore feature in Xiaohongshu and inspect the note
  itself before using it. Add a reviewed note as an `EvidenceSource` item in
  that attraction's `sources` array, including its canonical URL in `url`,
  exact title, platform, author/date when available, access date, and a concise
  provenance note. This `sources[].url` field is the catalog's source-link
  metadata; do not add an unsupported top-level metadata field. Update a
  summary's `source_ids` only when the note actually supports that claim.
  Record whether the independent source confirms the same place, only the
  wider area, or conflicts with the existing record. A failed or empty search
  is not corroboration: report the access issue and do not invent a link or
  mark the candidate cross-validated.
- Open and inspect the source itself before attributing an experience. Store
  the canonical source URL, platform, exact title, author when available,
  publication date when available, and access date. Do not cite search-result
  snippets as if the linked source was read.
- Write a short, original Chinese summary of only what the visitor actually
  observed. Distinguish a route mention from a stop or detailed review.
  Attribute time-sensitive observations (closures, access, prices, road
  condition) to the visit date; do not present them as current facts.
- Aim for three independent visitor sources per attraction. A single-source
  lead is acceptable at candidate stage, but mark that limitation and any
  unresolved location or access facts in `research_notes`. Never invent
  consensus, ratings, visits, or details to reach a target count.
- Use `visitor_experience` sources for summaries, highlights, and drawbacks.
  Use `objective_reference` sources only to cross-check facts such as
  coordinates; objective sources do not substantiate visitor sentiment.

## Coordinates, images, and offline use

- Add latitude and longitude only as a verified pair, with
  `coordinate_source_id` referencing an `objective_reference` source that
  identifies the matching map feature. Prefer the named entrance or actual
  stop. If only a broad-area representative point is known, say so in notes.
  Never guess coordinates or accept a same-name match outside Hainan.
- An unlocated candidate may remain in the catalog without coordinates. Do
  not imply it has a map pin.
- Keep visitor image URLs only as references when reuse rights are unclear.
  Never download or embed private/user-posted images without explicit
  permission. Local image files require authorized reuse or user upload and
  complete attribution in the schema.
- Store the original, concise summary locally so the candidate can be read
  offline; source URLs are provenance for later review, not required content.

## Data quality and verification

- Every new entry must validate against `Attraction` in
  `hainan_cycling/catalog/models.py`. Use a globally unique kebab-case `id`,
  an accurate region and category, and `status: "candidate"` unless the user
  explicitly directs a review-status change.
- Before adding a candidate, compare its name, aliases, location, and parent
  attraction against every record in `data/attractions.json`. Do not
  duplicate a place under a slightly different spelling. Maintain a coverage
  checklist by city/county for both the counterclockwise coastal route and
  inland detours; a target count never overrides deduplication or evidence
  quality.
- Keep the complete catalog in the single canonical file
  `data/attractions.json`; do not create numbered attraction batch files.
  Preserve existing records when updating the catalog. Keep all source IDs
  unique within an attraction and ensure every claim, image, and coordinate
  reference resolves.
- Keep JSON records in the Haikou-start, counterclockwise regional route order:
  Haikou, Chengmai, Lingao, Danzhou, Baisha, Qiongzhong, Changjiang, Dongfang,
  Ledong, Wuzhishan, Baoting, Sanya, Lingshui, Wanning, Qionghai, Tunchang,
  Ding'an, and Wenchang, then return to Haikou. Inland counties are positioned
  as detours between the adjacent coastal legs. Keep records within each
  region in a stable order unless reliable route evidence supports a more
  precise stop-by-stop sequence; do not infer a route from unverified
  coordinates. The catalog repository/API must return this same order, and
  UI lists should render the API order rather than defining a competing sort.
  When adding a region, update the shared route order and its tests.
- Update repository tests and research documentation when the catalog
  changes. Validate the catalog and API, not just JSON syntax. In this project,
  use the `cycling` Conda environment and run `python -m pytest -q`.
- During an ongoing research session, report progress as sources or locations
  are inspected, not only in a final summary. For each meaningful lead, state
  what was opened, whether the place is already represented, and whether the
  result was a new candidate, a source/observation added to an existing
  candidate, a duplicate left unchanged, or not added (with the evidence or
  access reason). Distinguish a search-result lead from a source whose contents
  were actually inspected. When the user requests a number of notes to review,
  count only notes whose full text was opened and inspected; report the
  cumulative reviewed count and disposition, not search cards or inaccessible
  pages. Keep the running catalog count and remaining target count accurate;
  do not imply that a search produced additions when it did not.
- Report the total candidate count, how many have verified coordinates, the
  source coverage limitations, and test results accurately. Never describe
  candidates as approved or broadly recommended.
