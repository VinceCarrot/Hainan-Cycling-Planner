-- Route-book coordinate systems. Tracks drawn on Chinese web maps (Garmin Connect China, Amap,
-- Baidu) arrive in GCJ-02 or BD-09 and sit a few hundred metres off an OSM basemap. The user's
-- GPX files are never rewritten: the parsed coordinates are kept verbatim in source_geometry_json
-- and geometry_json holds the WGS-84 copy used for display and distance calculations.

ALTER TABLE route_segments ADD COLUMN source_crs TEXT;            -- 'wgs84' | 'gcj02' | 'bd09' as declared at import (NULL = wgs84)
ALTER TABLE route_segments ADD COLUMN source_geometry_json TEXT;  -- GeoJSON LineString exactly as parsed from the GPX
