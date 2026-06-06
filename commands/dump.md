---
description: Back up and date-sort inserted camera cards (or a given drive/folder) into the master archive — hash-verified, idempotent, catalog updated.
argument-hint: "[source folder/drive …]  (omit to auto-detect cards)  [--dry-run]"
allowed-tools: Bash, Read
---

Ingest media into the archive using the bundled engine. If no source is given, it auto-detects inserted cards (anything with a `DCIM` folder).

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/media-archive/scripts/media-ingest.py" $ARGUMENTS
```

Follow the **media-archive** skill rules while doing this:
- **Copy-only and hash-verified** — never delete from a card/source until its bytes are confirmed in the archive. Tell the user it's safe to format cards only after a clean ✅.
- **Never split structured datasets** — Lightroom catalogs, Final Cut libraries, and DJI RTK / photogrammetry flight folders move *intact*, never through the date-sorter.
- If the user is unsure, run with `--dry-run` first and show what would happen.
