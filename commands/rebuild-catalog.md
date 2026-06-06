---
description: Rebuild the media catalog from scratch by rescanning the whole archive drive. Slow — only when the catalog is lost or badly out of sync.
allowed-tools: Bash
---

This does a **full rescan** of the archive drive, which is slow on a multi-TB volume. Normal ingests (`/photo-archive:dump`) keep the catalog current incrementally, so a full rebuild is rarely needed.

Confirm with the user that the catalog is actually lost or out of sync — not just missing a recent card (use `/photo-archive:dump` for that). If they confirm:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/media-archive/scripts/build-catalog.py"
```
