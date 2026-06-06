# Catalog reference

The catalog is a SQLite DB (`$MEDIA_CATALOG`, default `~/photos/catalog/gdrive_catalog.db`) with one
table, `media`, holding one row per photo/video. It is the source of truth — query it instead of
walking the drive.

## Table `media`
| column | meaning |
|---|---|
| path | full path on the archive drive |
| rel | path relative to the archive root |
| location | top-level folder (PhotoArchive, VideoArchive, …) |
| in_archive | `PhotoArchive` / `VideoArchive` / `straggler` (not yet sorted in) |
| filename, ext | name and lowercase extension |
| kind | `photo` / `video` / `other` |
| size | bytes |
| filetype | exiftool FileType (ARW, DNG, MOV, HEIC…) |
| width, height, megapixels | pixel dimensions |
| orientation | `landscape` / `portrait` / `square` (rotation-corrected) |
| capture_date, year | `YYYY-MM-DD` of capture (DateTimeOriginal/CreateDate; file date fallback) |
| make, model, lens | camera info |
| gps_lat, gps_lon, has_gps | geotag |
| duration, fps | video length (seconds) and frame rate |
| is_drone | 1 for real aircraft only (see SKILL rule 3 — NOT Osmo/handheld) |
| tag | freeform tag, e.g. `gold-standard` for benchmark portfolio shots |

Keep dates as `YYYY-MM-DD` with **dashes**. exiftool's `-n` flag makes it emit `YYYY:MM:DD`
(colons) — always normalize `:`→`-`, or you get duplicate colon-named folders on macOS.

## Query cookbook
```sql
-- Print candidates: high-res landscapes, newest first
SELECT path, model, megapixels, capture_date FROM media
WHERE kind='photo' AND orientation='landscape' AND megapixels>=24 ORDER BY capture_date DESC;

-- Short drone clips (real aircraft, under 10 min) for an edit
SELECT path, width||'x'||height res, ROUND(duration) secs FROM media
WHERE kind='video' AND is_drone=1 AND duration<600 ORDER BY duration;

-- Geotagged near a place (bounding box)
SELECT path, gps_lat, gps_lon FROM media
WHERE has_gps=1 AND gps_lat BETWEEN 40.1 AND 40.6 AND gps_lon BETWEEN -105.9 AND -105.4;

-- The user's gold-standard benchmark shots
SELECT * FROM media WHERE tag='gold-standard';

-- What's still outside the archive (to consolidate)
SELECT location, COUNT(*) , ROUND(SUM(size)/1e9,1) gb FROM media
WHERE in_archive='straggler' GROUP BY location ORDER BY gb DESC;
```

## Updating without a rescan
- `media-ingest.py` inserts new rows as it copies. Prefer this.
- After moving files yourself, update rows in place: `UPDATE media SET path=?, rel=?, location=?,
  in_archive=? WHERE path=?`; delete rows for removed files. Re-derive `rel`/`location` from `path`.
- Only `build-catalog.py` does a full rescan — last resort.
