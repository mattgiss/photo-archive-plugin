# Photo & Video Archive — Claude Code plugin

Packages a photographer/videographer's media workflow as an installable Claude Code plugin:
back up camera cards, keep one date-sorted master archive, maintain a searchable SQLite catalog,
pull hash-verified selections to cull, and rank video clips by what only watching reveals — all
copy-only, verify-before-trust, and idempotent.

## What's inside

```
photo-archive-plugin/
├── .claude-plugin/
│   ├── plugin.json          # plugin manifest
│   └── marketplace.json     # single-plugin local marketplace
├── commands/                # slash-command entry points
│   ├── dump.md              # /photo-archive:dump            — ingest cards/drives
│   ├── pull.md              # /photo-archive:pull            — pull a selection to cull
│   ├── catalog.md           # /photo-archive:catalog         — plain-English catalog search
│   ├── rebuild-catalog.md   # /photo-archive:rebuild-catalog — full rescan
│   └── rate-video.md        # /photo-archive:rate-video      — rank clips by motion via Gemini
└── skills/
    ├── media-archive/       # ingest · catalog · pull/cull (auto-invoked by description)
    │   ├── SKILL.md
    │   ├── references/catalog.md
    │   └── scripts/{media-ingest,pull-selection,move-keepers,build-catalog}.py
    └── gemini-video-rater/  # rank/filter clips by on-screen motion Gemini watches
        ├── SKILL.md
        └── scripts/{gemini-rate,gemini-segment,stabilize}.py
```

The **skills** trigger automatically from natural language ("back up these cards", "what
landscapes do I have near Moab", "which of these flyovers are steadiest"). The **commands** are
deterministic entry points for the same actions. The two skills pair: query the catalog to a
candidate set, then have Gemini rate the clips — facts narrow, Gemini judges what's on screen.

`gemini-video-rater` needs `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `ffmpeg`, and `google-genai`.

## Install (local)

```bash
# 1. register this directory as a marketplace
/plugin marketplace add ~/photos/photo-archive-plugin

# 2. install the plugin from it
/plugin install photo-archive@gissentanna-local

# 3. reload (or restart Claude Code)
/reload-plugins
```

Then use `/photo-archive:dump`, `/photo-archive:pull`, `/photo-archive:catalog`,
`/photo-archive:rebuild-catalog`, or just talk to it in plain English.

### Dev / one-off (no install)

```bash
claude --plugin-dir ~/photos/photo-archive-plugin
```

## Configuration

The scripts read two environment variables (defaults shown):

```bash
export MEDIA_ARCHIVE="/Volumes/G-DRIVE PROJECT"          # archive root (use an APFS volume)
export MEDIA_CATALOG="$HOME/photos/catalog/gdrive_catalog.db"
```

Requires `exiftool` (`brew install exiftool`); `czkawka` and `uv` are optional (dedup / Apple
Photos export). The archive drive should be **APFS** — exFAT silently breaks files over 4 GB.

## Note on the source of truth

The skill here is a **copy** of `~/photos/skills/media-archive`, so the plugin is self-contained
and installable anywhere. If you edit one, sync the other (or make this plugin the canonical home
and delete the loose skill).
