---
description: Rank or filter video clips by what only watching reveals — camera steadiness, motion type (flyover vs orbit vs shaky), action, pacing, or visible content — using Gemini.
argument-hint: "--goal \"what the clips are for\" <clip paths…>   (or --from-file list.txt)"
allowed-tools: Bash, Read
---

The user wants to judge clips by **on-screen motion or events** — something Claude can't see from still frames. Offload the watching to Gemini via the bundled `gemini-video-rater` skill.

Prerequisites (see `${CLAUDE_PLUGIN_ROOT}/skills/gemini-video-rater/SKILL.md`): `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the env, `ffmpeg`, and the `google-genai` SDK.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/gemini-video-rater/scripts/gemini-rate.py" --goal "<what the clips are for>" <clip paths…>
```

Guidelines:
- State a concrete **goal** ("calm meditation flyovers", "action highlight reel") so the `fit` score means something — don't ask for generic "quality".
- It compresses/samples each clip before upload, has Gemini watch it, prints a ranked table, and writes `gemini_ratings.json`. Use `gemini-2.5-flash`; on a `429`, retry with `gemini-flash-latest` before assuming the key is dead.
- **Gemini ranks, you curate** — sanity-check the top few before presenting.
- Pairs with `/photo-archive:catalog`: query the catalog to a candidate set first (by duration / drone / camera), then rate just those.
