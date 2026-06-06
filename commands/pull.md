---
description: Pull a hash-verified selection from the archive onto a working drive to cull — by preset or a custom SQL query.
argument-hint: "--preset rmnp-landscapes|drone-meditation|landscapes-print --dest /Volumes/T9 [--max-gb N] [--dry-run]   |   --where \"<SQL>\" --label name --dest …"
allowed-tools: Bash, Read
---

Pull a selection out of the archive into `<dest>/_PULLS/<label>/` (flat folder + manifest), copy-only and hash-verified. The archive is never modified.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/media-archive/scripts/pull-selection.py" $ARGUMENTS
```

Notes:
- Built-in presets: `rmnp-landscapes`, `drone-meditation`, `landscapes-print`. For anything else, build a `--where` clause against the `media` table (schema in `${CLAUDE_PLUGIN_ROOT}/skills/media-archive/references/catalog.md`).
- Respect `is_drone` rule 3 — exclude Osmo/Pocket/Action/GoPro when the user asks for "drone" footage.
- Suggest `--dry-run` and `--max-gb` when the selection could be large.
- After culling, promote keepers with: `python3 "${CLAUDE_PLUGIN_ROOT}/skills/media-archive/scripts/move-keepers.py" --from <_PULLS/label> --to <project SSD>`.
