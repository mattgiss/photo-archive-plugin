---
description: Search the media catalog in plain English — translate the request to SQL over the `media` table and run it.
argument-hint: "<what you're looking for, e.g. '4K drone clips over 30s' or 'landscape prints near Moab'>"
allowed-tools: Bash, Read
---

The user is looking for: **$ARGUMENTS**

Translate this into a SQL query over the `media` table and run it against the catalog. The full schema and a query cookbook are in `${CLAUDE_PLUGIN_ROOT}/skills/media-archive/references/catalog.md` — read it if you need column names.

```bash
sqlite3 "${MEDIA_CATALOG:-$HOME/photos/catalog/gdrive_catalog.db}" "<YOUR SQL>"
```

Guidelines:
- Useful columns: `path, kind, orientation, megapixels, width, height, capture_date, make, model, gps_lat, gps_lon, has_gps, duration, is_drone, tag`.
- For "drone" requests, filter `is_drone=1` (real aircraft only — not Osmo/handheld).
- For "prints/best/good", metadata only narrows the field — render previews with `sips -s format jpeg -Z 1500 SRC --out OUT.jpg` and actually look before recommending.
- Show the matching `path`s plus the columns that justify the match. Never full-rescan the drive; the catalog is the source of truth.
