---
description: Thematic smart search — find and browse photos/videos by what's IN them (sunsets, beaches, family, aerials…), via the Gemini-built theme index.
argument-hint: "<plain-English ask, e.g. 'sunsets over water' or 'beach days 2024'>  (empty = browse all themes)"
allowed-tools: Bash, Read
---

The user wants to find or browse media by **content/theme**: **$ARGUMENTS**

This runs on the `themes` table + `themes_fts` FTS index in the catalog (built by Gemini looking
at each file). Schema and cookbook: `${CLAUDE_PLUGIN_ROOT}/skills/media-archive/references/catalog.md`.

**1. Check the index exists and how much it covers:**

```bash
sqlite3 "${MEDIA_CATALOG:-$HOME/photos/catalog/gdrive_catalog.db}" \
  "SELECT (SELECT COUNT(*) FROM themes), (SELECT COUNT(*) FROM media WHERE kind IN ('photo','video'))"
```

If the table is missing or empty, offer to build it (needs `GEMINI_API_KEY` and `google-genai`;
photos batch cheaply — suggest starting with `--kind photo` or a `--limit`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/media-archive/scripts/theme-index.py" [--kind photo] [--limit N]
```

**2a. No arguments → browse.** Show the theme landscape like albums, then offer the visual overview:

```bash
sqlite3 "$MEDIA_CATALOG" "SELECT j.value theme, COUNT(*) n FROM themes t, json_each(t.themes) j
  GROUP BY 1 ORDER BY n DESC LIMIT 40"
python3 "${CLAUDE_PLUGIN_ROOT}/skills/media-archive/scripts/theme-gallery.py" --open   # contact sheet per theme
```

**2b. With a query → search.** Translate the ask into an FTS `MATCH` over tags + captions —
expand synonyms with `OR` (e.g. "sunsets over water" → `(sunset OR "golden-hour") AND (ocean OR
lake OR beach OR seascape)`) — and join `media` for the factual filters (year, kind, drone, GPS):

```bash
sqlite3 "$MEDIA_CATALOG" "SELECT m.path, t.themes, t.caption FROM themes_fts f
  JOIN themes t ON t.path=f.path JOIN media m ON m.path=f.path
  WHERE themes_fts MATCH '<query>' [AND m.year='2024'] [AND m.kind='photo'] ORDER BY rank LIMIT 50"
```

**3. Let them see it.** For more than a handful of hits, render a gallery instead of listing paths:

```bash
python3 ".../theme-gallery.py" --query "<same FTS query>" [--kind photo] [--year 2024] --open
```

Guidelines:
- FTS syntax: `OR` / `AND` / parentheses. **Quote every hyphenated tag and multi-word phrase** —
  `"golden-hour"`, `"golden hour"` (both match the same phrase); an unquoted `-` is a syntax
  error. Don't pass raw user text with stray quotes into MATCH — build the query yourself.
- Report coverage honestly: if only part of the archive is indexed, say "searched the N indexed
  files; M not yet indexed" and offer `theme-index.py` for the rest (it only pays for the delta).
- Themes narrow; they don't rank quality. For "the best sunsets", search here first, then look at
  previews (or `/photo-archive:rate-video` for clips) before recommending.
- `/photo-archive:catalog` handles factual asks (dates, camera, resolution, GPS); this command
  handles "what's in the frame". Combine both freely in one SQL query.
