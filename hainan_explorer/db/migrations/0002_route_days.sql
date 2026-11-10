-- Per-day route book support: places learn which day of the user's route they sit on,
-- how far along that day they are, and route_segments gains the metadata needed to
-- store one imported GPX track per day.

ALTER TABLE places ADD COLUMN route_day INTEGER;        -- day number of the nearest route segment (NULL = no route imported / no coords)
ALTER TABLE places ADD COLUMN route_day_km REAL;        -- km from that day's start to the nearest point on the track (estimate)
CREATE INDEX idx_places_route_day ON places(route_day, route_day_km);

ALTER TABLE route_segments ADD COLUMN name TEXT;
ALTER TABLE route_segments ADD COLUMN day_number INTEGER;
ALTER TABLE route_segments ADD COLUMN source_file TEXT;
ALTER TABLE route_segments ADD COLUMN point_count INTEGER;
ALTER TABLE route_segments ADD COLUMN start_lat REAL;
ALTER TABLE route_segments ADD COLUMN start_lon REAL;
ALTER TABLE route_segments ADD COLUMN end_lat REAL;
ALTER TABLE route_segments ADD COLUMN end_lon REAL;
ALTER TABLE route_segments ADD COLUMN created_at TEXT;
CREATE INDEX idx_route_segments_version ON route_segments(route_version, sequence_no);
