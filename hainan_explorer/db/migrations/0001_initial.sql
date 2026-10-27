-- Hainan Explorer initial schema. Coordinates are WGS84 decimal degrees.

CREATE TABLE places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    name_en TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    country TEXT NOT NULL DEFAULT 'CN',
    province TEXT NOT NULL DEFAULT '海南省',
    city TEXT,
    county TEXT,
    town TEXT,
    latitude REAL,
    longitude REAL,
    coordinate_source TEXT,              -- provider that supplied the coordinate
    coordinate_precision TEXT,           -- exact | approximate | centroid | unknown
    geometry_json TEXT,
    category TEXT NOT NULL DEFAULT 'unknown',
    subcategory TEXT,
    feature_tags_json TEXT NOT NULL DEFAULT '{}',
    description TEXT,
    description_language TEXT,
    description_source_id INTEGER,
    discovery_status TEXT NOT NULL DEFAULT 'new',          -- new | candidate | seed | verified | excluded
    verification_status TEXT NOT NULL DEFAULT 'unverified', -- unverified | partially_verified | verified | disputed
    needs_geographic_verification INTEGER NOT NULL DEFAULT 0,
    confidence_score REAL NOT NULL DEFAULT 0,
    interest_status TEXT NOT NULL DEFAULT 'undecided',     -- undecided | want_to_visit | maybe | skip | needs_research
    interest_score INTEGER,
    personal_notes TEXT,
    discovery_reason TEXT NOT NULL DEFAULT 'manual_candidate',
    discovery_score REAL NOT NULL DEFAULT 0,
    novelty_score REAL NOT NULL DEFAULT 0,
    route_distance_km REAL,              -- straight-line distance to the rough corridor; an estimate only
    is_accessible_unknown INTEGER NOT NULL DEFAULT 1,
    is_coastal INTEGER,
    source_count INTEGER NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    local_image_count INTEGER NOT NULL DEFAULT 0,
    research_status TEXT NOT NULL DEFAULT 'pending',       -- pending | done | failed
    researched_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    merged_into_place_id INTEGER REFERENCES places(id)
);
CREATE INDEX idx_places_normalized_name ON places(normalized_name);
CREATE INDEX idx_places_county ON places(county);
CREATE INDEX idx_places_category ON places(category);
CREATE INDEX idx_places_interest ON places(interest_status);
CREATE INDEX idx_places_latlon ON places(latitude, longitude);
CREATE INDEX idx_places_merged ON places(merged_into_place_id);

CREATE TABLE provider_ids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,              -- osm | wikidata | wikipedia_zh | wikipedia_en | legacy_catalog | ...
    external_id TEXT NOT NULL,           -- e.g. node/123, Q42200, page title
    external_url TEXT,
    raw_json TEXT,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(provider, external_id)
);
CREATE INDEX idx_provider_ids_place ON provider_ids(place_id);

CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,           -- map_feature | knowledge_base | encyclopedia | web_page | travelogue | image_page | user_note
    url TEXT NOT NULL,
    canonical_url TEXT,
    title TEXT,
    publisher TEXT,
    author TEXT,
    published_at TEXT,
    retrieved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    access_status TEXT NOT NULL DEFAULT 'link_only',   -- fetched | link_only | blocked | failed
    terms_url TEXT,
    license_notes TEXT,
    excerpt TEXT,
    content_hash TEXT,
    last_checked_at TEXT,
    UNIQUE(url)
);

CREATE TABLE place_sources (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL DEFAULT 'mentions',  -- describes | mentions | locates | depicts | user_note
    evidence_excerpt TEXT,
    confidence_score REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (place_id, source_id)
);

CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,              -- commons | user_upload | web
    external_id TEXT,                    -- e.g. Commons file title
    source_id INTEGER REFERENCES sources(id),
    source_page_url TEXT,
    original_url TEXT,
    display_url TEXT,                    -- remote URL permitted for display (e.g. Commons thumb)
    local_path TEXT,
    thumbnail_path TEXT,
    title TEXT,
    description TEXT,
    creator TEXT,
    attribution_text TEXT,
    attribution_url TEXT,
    license_id TEXT,
    license_url TEXT,
    license_short TEXT,
    permission_status TEXT NOT NULL DEFAULT 'unknown',  -- local_copy_allowed | link_only | api_display_only | unknown | blocked
    permission_reason TEXT,
    license_verified_at TEXT,
    width INTEGER,
    height INTEGER,
    mime_type TEXT,
    bytes INTEGER,
    sha256 TEXT,
    perceptual_hash TEXT,
    view_type TEXT NOT NULL DEFAULT 'unknown',
    latitude REAL,
    longitude REAL,
    categories_json TEXT,
    date_taken TEXT,
    retrieved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_checked_at TEXT,
    download_status TEXT NOT NULL DEFAULT 'not_downloaded', -- not_downloaded | downloaded | failed | removed | not_allowed
    download_error TEXT,
    reported_issue TEXT,
    UNIQUE(provider, external_id)
);
CREATE INDEX idx_images_sha ON images(sha256);
CREATE INDEX idx_images_phash ON images(perceptual_hash);
CREATE INDEX idx_images_latlon ON images(latitude, longitude);

CREATE TABLE place_images (
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    association_type TEXT NOT NULL DEFAULT 'suggested',  -- suggested | user_verified | rejected
    association_status TEXT NOT NULL DEFAULT 'suggested',
    match_score REAL NOT NULL DEFAULT 0,
    match_reasons_json TEXT NOT NULL DEFAULT '[]',
    confidence_score REAL NOT NULL DEFAULT 0,
    verified_by_user INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (place_id, image_id)
);
CREATE INDEX idx_place_images_image ON place_images(image_id);

CREATE TABLE discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    query TEXT,
    region_key TEXT,
    category TEXT,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',  -- running | succeeded | failed | cancelled | partial
    result_count INTEGER NOT NULL DEFAULT 0,
    new_place_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    cursor_json TEXT,
    config_snapshot_json TEXT,
    job_id INTEGER
);
CREATE INDEX idx_runs_provider ON discovery_runs(provider, region_key, category);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | succeeded | failed | cancelled | retry_wait
    priority INTEGER NOT NULL DEFAULT 5,
    payload_json TEXT NOT NULL DEFAULT '{}',
    dedupe_key TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at TEXT,
    finished_at TEXT,
    next_run_at TEXT,
    last_error TEXT,
    progress_json TEXT NOT NULL DEFAULT '{}',
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_jobs_status ON jobs(status, priority, created_at);
CREATE INDEX idx_jobs_dedupe ON jobs(dedupe_key);

CREATE TABLE job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_job_logs_job ON job_logs(job_id);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,             -- interest_status value, or 'note' / 'verify' / 'merge' / 'unmerge'
    previous_decision TEXT,
    score INTEGER,
    reason TEXT,
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    undone INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_reviews_place ON reviews(place_id);

CREATE TABLE place_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id_a INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    place_id_b INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,        -- duplicate_of | part_of | nearby_to | alternative_name_of
    confidence_score REAL NOT NULL DEFAULT 0,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    review_status TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected | merged | undone
    audit_json TEXT,
    UNIQUE(place_id_a, place_id_b, relation_type)
);
CREATE INDEX idx_relations_b ON place_relations(place_id_b);

CREATE TABLE route_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_version TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    start_place_id INTEGER REFERENCES places(id),
    end_place_id INTEGER REFERENCES places(id),
    distance_km REAL,
    elevation_gain_m REAL,
    surface TEXT,
    source_id INTEGER REFERENCES sources(id),
    is_estimated INTEGER NOT NULL DEFAULT 1,
    geometry_json TEXT,
    notes TEXT
);

CREATE TABLE route_corridors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    geometry_json TEXT NOT NULL,        -- GeoJSON LineString/MultiLineString
    source_note TEXT,
    is_estimated INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE provider_state (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    request_count INTEGER NOT NULL DEFAULT 0,
    rate_limited_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
