---
name: media-archive
description: >-
  Back up, sort, catalog, and pull from a personal photo/video archive. Use this
  whenever the user wants to offload camera cards or SD/CFexpress, "dump" or ingest
  media from a card or drive, sort photos/videos into their dated archive, keep the
  media catalog up to date, free up a drive, or pull a selection (e.g. "find me
  landscape prints", "pull drone flyover clips") to cull. Trigger even if the user
  doesn't say "archive" — e.g. "back up these cards", "get this footage off my SD",
  "move my Pictures to the G-drive", "what landscapes do I have near Moab", "copy my
  best drone shots to T9". Also covers **thematic search** — finding or browsing media by what's
  IN the frame ("show me sunsets", "beach days with the kids", "find waterfall clips", "browse my
  photos by theme") via a Gemini-built theme index in the same catalog. Also use it to set up an **automatic / scheduled card-dump**
  — a watch folder that auto-sorts on a timer (e.g. on an always-on Mac mini server) —
  and to make ingest jobs survive flaky external drives. The archive is the master; this
  skill keeps it clean, verified, and searchable without ever rescanning the whole drive.
---

# Media Archive

A safe, repeatable pipeline for a working photographer/videographer's master archive:

```
cards / drives ──► INGEST (sort + verify) ──► ARCHIVE (master, catalogued)
                                                 │
                                       PULL a selection ──► working drive ──► CULL ──► project SSD
```

Everything is **copy-only and hash-verified** — sources are never modified, and a file is
only trusted once its copy's hash matches. The whole thing is built so the user never has to
rescan the drive: a SQLite catalog is the source of truth for "what do I have."

## Layout (defaults, configurable)
- Archive root: `$MEDIA_ARCHIVE` (default `/Volumes/G-DRIVE PROJECT`)
- Photos → `PhotoArchive/Photos/YYYY/YYYY-MM-DD/`
- Videos → `VideoArchive/YYYY/YYYY-MM-DD/`
- Catalog → `$MEDIA_CATALOG` (default `~/photos/catalog/gdrive_catalog.db`)
- Bundled scripts live in `scripts/` next to this file. Requires `exiftool` (`brew install exiftool`).

## The scripts (use these — don't reinvent them)
| Task | Script |
|---|---|
| Dump cards / ingest a drive into the archive | `scripts/media-ingest.py [sources…]` (auto-detects cards if no source) |
| Build/rebuild the catalog from scratch | `scripts/build-catalog.py` |
| Pull a selection out to a working drive to cull | `scripts/pull-selection.py --preset … --dest /Volumes/T9` |
| Move culled keepers to the project SSD | `scripts/move-keepers.py --from … --to …` |
| Theme-index media (Gemini tags what's in each frame) | `scripts/theme-index.py [--kind photo] [--limit N]` |
| Browse/search themes as an HTML contact sheet | `scripts/theme-gallery.py [--theme sunset \| --query "…"] --open` |

Run with `--dry-run` first when the user is unsure. `media-ingest.py` reads dates with exiftool,
copies each file, **re-hashes the copy to verify**, skips anything already in the archive
(idempotent — safe to re-run), and updates the catalog so no rescan is needed.

## The rules that matter (these are hard-won — follow them)

**1. Never date-sort structured datasets. This is the big one.**
Date-sorting scatters a file by its capture date. That is *correct* for loose photos/clips, but
it **destroys** anything whose value is its folder structure. Before ingesting/sorting a source,
detect and treat these as **intact units** (move/keep the whole folder, never split it):
- **Lightroom** catalogs — folders containing `*.lrcat` / `*.lrdata` / `*.lrlibrary`.
- **Final Cut** libraries — `*.fcpbundle` packages (move whole; their render cache is regenerable).
- **DJI RTK / photogrammetry flights** — folders containing `*.MRK` / `*.RTK` / `*.OBS` / `*.NAV` /
  `*.PBK`, or DCIM flight folders named like `DJI_<timestamp>_<n>_<project>/`. The images, the RTK
  files, and the folder are one dataset — splitting them breaks the orthomosaic/3D pipeline. These
  are often client deliverables; getting this wrong is expensive.

If you must consolidate these, move them folder-intact into a `_Projects/` or `_Mapping/` area —
do **not** feed them to the date-sorter.

**2. Sidecars travel with their media.** When a media file moves, its sidecars move with it:
`.xmp` (Lightroom edits), `.aae` (Apple edits), `.lrf` (DJI low-res proxy), `.srt` (telemetry/subs).
For drone **mapping** data the "sidecars" are the per-flight `.MRK/.RTK/.OBS/.NAV/.PBK` — but those
belong to the *flight folder*, so per rule 1 you keep the whole flight folder together rather than
chasing individual files.

**3. "DJI" in a filename does NOT mean drone.** DJI makes drones *and* handhelds (Osmo Pocket,
Osmo Action). Both write `DJI_…` filenames, so the filename tells you nothing. Identify the camera
from **metadata**, not the name. On DJI video the model often lives in the `Encoder` tag
(e.g. `DJI OsmoPocket3` = handheld), while Make/Model can be blank. Real aircraft report models
like `FC####` (Mini/Phantom), `L1D/L2D/L3D` (Mavic Hasselblad), `M4E` (Mavic Enterprise). Classify
in this **priority order**: (a) a handheld model/encoder (Osmo/Pocket/Action/GoPro) is *never* a
drone; (b) a known aircraft model *is* a drone **at any altitude** — drones shoot low too, so don't
demote a low/zero-altitude Mavic; (c) only when the model is unknown (DJI video often has a blank
model) fall back to **flight altitude** — `RelativeAltitude` well above 0 = airborne = drone, ~0 =
handheld. Tag `is_drone` for real aircraft only; when the user asks for "drone" footage, exclude
Osmo/Pocket/Action/GoPro.

**4. Copy-only, verify, idempotent.** Never delete from a card or source until its bytes are
confirmed in the archive (size **and** hash). Re-running an ingest must be safe — skip what's
already there. Tell the user it's safe to format cards only after a clean ✅.

**5. Keep the catalog current, never full-rescan.** A full re-read of a multi-TB drive is slow and
wasteful (the user will notice). The ingest tool updates the catalog incrementally as it copies.
Only rebuild from scratch (`build-catalog.py`) if the catalog is lost or badly out of sync.

**6. The archive drive should be APFS.** exFAT can't hold files over 4 GB — that silently breaks
4K video. Flag this if the user points the archive at an exFAT volume.

**7. External drives drop — make every job survivable.** On an always-on server the archive
(spinning HDD) and the working SSD can spin down, sleep, or briefly disconnect mid-job — and a
multi-minute 4K encode or a big copy written *straight to that drive* dies the instant it does
(hard-won: five stabilization runs were killed this way when T9 dropped). Defend against it:
(a) **preflight** — before any job, confirm the volumes are mounted (`mount | grep -q "/Volumes/T9"`)
and abort with a clear message rather than half-writing; (b) **don't write long jobs straight to a
flaky external** — render/transcode to local disk, then copy the finished file across in one pass;
(c) on a server keep system + disk sleep off (`sudo pmset -a sleep 0 disksleep 0`) and wrap long runs
in `caffeinate -i`; (d) prefer **resumable** copies (`rsync --partial --append-verify`) so a blip
resumes instead of restarting. Because everything is already copy-only + hash-verified + idempotent
(rule 4), a killed job is always safe to just re-run — design for that, don't fear it.

## Finding things — query the catalog
The catalog answers "what do I have" instantly. See `references/catalog.md` for the full schema and
a query cookbook. Quick examples:
```bash
sqlite3 "$MEDIA_CATALOG" "SELECT path,model,megapixels FROM media
  WHERE kind='photo' AND orientation='landscape' AND megapixels>=24 ORDER BY capture_date DESC;"
sqlite3 "$MEDIA_CATALOG" "SELECT path,duration FROM media
  WHERE kind='video' AND is_drone=1 AND duration<600 ORDER BY duration;"   -- short drone clips
```

## Thematic search — find media by what's in the frame
The `media` table can't answer "show me sunsets". `theme-index.py` has Gemini look at each
photo (batched previews) and video (sampled frames) and writes lowercase theme tags + a one-line
caption to a `themes` table with an FTS5 index — same DB, idempotent, resumable, and after a new
dump only the delta needs indexing (run it as a post-ingest step). Needs `GEMINI_API_KEY` +
`google-genai`; previews render locally via `sips`/`ffmpeg`, so originals never upload.
```bash
sqlite3 "$MEDIA_CATALOG" "SELECT m.path, t.caption FROM themes_fts f
  JOIN themes t ON t.path=f.path JOIN media m ON m.path=f.path
  WHERE themes_fts MATCH '(sunset OR \"golden-hour\") AND beach' AND m.kind='photo' ORDER BY rank"
python3 scripts/theme-gallery.py --query 'sunset OR "golden-hour"' --open  # see it, not just list it
```
Expand the user's words into `OR` synonyms, combine freely with factual columns (year, `is_drone`,
GPS), and report coverage — un-indexed files are invisible to MATCH, so say "N of M indexed" when
the index is partial. Full schema + cookbook: `references/catalog.md`.

## Curating "best" / licensable selections
Metadata narrows the field; it cannot judge a photo. When the user wants the "best" prints or the
"good" clips, **actually look**: query a diverse candidate pool → render previews
(`sips -s format jpeg -Z 1500 SRC --out OUT.jpg`, works on RAW) → view them → curate. Hold results to
the user's gold standard if one exists (`SELECT * FROM media WHERE tag='gold-standard'`). For video,
"steady flyover" vs "orbit/work footage" is a visual call — sample frames or scrub, don't trust tags.

## Automated dump system (server / watch folder)
For an always-on setup (e.g. a Mac mini server) the manual "dump cards" step becomes hands-off:
- A **landing zone** on the fast working drive — e.g. `/Volumes/T9/_INGEST/` — is where new footage
  arrives, whether from a card reader or a **phone writing over a LAN share** (macOS File Sharing).
- A **scheduled job** (macOS `launchd`) periodically runs `media-ingest.py /Volumes/T9/_INGEST`,
  which date-sorts + hash-verifies everything into the archive, carries sidecars, updates the
  catalog, and — **only after a clean ✅** — clears the landing zone so it's ready for the next dump.
- Make it **self-healing** (so it "doesn't abend"): log each run to `~/photos/logs/`, guard with the
  rule-7 preflight (skip cleanly if a drive is absent instead of erroring), and emit a daily health
  line so a silent failure is visible. `launchd` `StartCalendarInterval` schedules it; `KeepAlive`
  restarts it. Cloud overflow (e.g. `rclone` to a remote) can be a later stage that pushes cold media
  off the local drives to free space.
The engine is the same `media-ingest.py` — automation just feeds it on a timer instead of by hand.

## Setup
```bash
brew install exiftool czkawka uv          # czkawka = dedup; uv only if exporting Apple Photos
export MEDIA_ARCHIVE="/Volumes/Your Drive" # if not the default
```
