---
name: gemini-video-rater
description: >-
  Pick, rank, or filter VIDEO clips by something you can only judge by WATCHING them — camera
  steadiness/smoothness, motion type (flyover vs orbit vs shaky), action, pacing, visible content,
  or overall quality. Claude can read still frames and metadata but cannot see motion or temporal
  content; this skill offloads that to Gemini, which watches each clip and returns structured
  ratings. Use it whenever the user asks to "find the steady/smooth clips", "which of these is the
  best take", "rank these shots", "pull the good flyovers", "which clips have <X happening>", or
  any clip selection where the deciding factor is on-screen motion or events — especially over many
  clips where watching them all by hand is impractical. Pairs naturally with a media catalog:
  query to a candidate set, then rate with this.
---

# Gemini Video Rater

Claude can look at extracted frames and read metadata (duration, camera, resolution) — but it
**cannot watch motion**. "Is this a smooth flyover or a jerky orbit?" "Which take is steadiest?"
"Which clips actually show the dog catching the ball?" are temporal/motion questions that need a
model that ingests video. **Gemini does.** This skill is a thin, reliable harness around that:

```
candidate clips ──► compress to small previews ──► Gemini watches each ──► structured scores ──► rank
```

The division of labor: you (Claude) handle selection, orchestration, and presenting; Gemini
supplies the one thing you can't do — seeing the footage move.

## Setup
- **API key**: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the env. If absent, check for a key file
  the user keeps (ask, or look in obvious spots). Load it without printing the value.
- **SDK**: `pip3 install --user google-genai` (or `uv pip install`).
- **ffmpeg** for compression: `brew install ffmpeg`.
- **Model**: use `gemini-2.5-flash` (it ingests video and is cheap/fast). Note that on free tier the
  *2.0*-flash models often return `429 RESOURCE_EXHAUSTED` while 2.5 still has quota — if you hit a
  429, try `gemini-2.5-flash` / `gemini-flash-latest` before assuming the key is dead.

## Run it
```bash
python3 scripts/gemini-rate.py --goal "steady aerial flyovers for a calm meditation video" \
    /path/to/clipA.mp4 /path/to/clipB.mov ...
# or feed a list (one path per line):
python3 scripts/gemini-rate.py --goal "…" --from-file /tmp/clips.txt
```
It compresses each clip to a small sampled preview, has Gemini watch it, and prints a table ranked
by fit, plus writes `gemini_ratings.json`. Flags: `--sample <sec>` (preview length, default 90),
`--height <px>` (default 640), `--dimensions a,b` (extra 1–10 scores to collect), `--keep N` (only
upload the first N by some pre-sort you've done).

## Why each step is the way it is (don't skip these)
1. **Compress before uploading.** Source 4K clips are gigabytes — too big/slow to upload and
   unnecessary. A 480–640p preview preserves the *motion* (which is all Gemini needs to judge
   steadiness/action), uploads in seconds, and sidesteps file-size limits. Drop audio (`-an`).
2. **Sample, don't transcode the whole thing.** A representative ~90 s segment (start a little in,
   `-ss`) captures a clip's character and keeps the transcode fast. Full-length only if the user
   needs whole-clip certainty (e.g., "is it steady the *entire* time").
3. **State the goal in the prompt and rate against it.** Don't ask for generic "quality" — tell
   Gemini exactly what the clips are *for* ("calm meditation background", "action highlight reel",
   "real-estate walkthrough") so its `fit` score means something. Ask for a 1–10 fit, a few
   descriptive labels, and one-line reasoning. Request JSON so you can rank programmatically.
4. **Clean up + handle limits.** Delete each uploaded file after rating (Files API has a quota).
   Back off and retry on `429`; if quota is truly out, say so rather than silently returning fewer.
5. **Gemini ranks, you curate.** Use the scores to order candidates, then sanity-check the top few
   (a frame, the metadata) and present. Gemini occasionally misreads a scene; the scores are a
   strong signal, not gospel.

## Output
A ranked table (highest fit first) and `gemini_ratings.json` like:
```json
[{"file":"…/DJI_0001.mp4","fit":9,"labels":["steady","flyover","alpine"],
  "summary":"Smooth forward glide over a snow-capped basin; locked horizon."}]
```
Then copy the winners wherever the user wants (e.g. a working drive for final review).

## Pairs with a media catalog
If the user has a searchable media catalog (e.g. the `media-archive` skill), the natural flow is:
**query the catalog** to a candidate set (by kind/duration/camera/drone/etc.) → **rate with this
skill** → pull the winners. Catalog narrows by facts; Gemini judges what's on screen.
