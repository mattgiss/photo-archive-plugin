#!/usr/bin/env python3
"""
theme-index.py — Have Gemini LOOK at photos/videos and tag each with themes, into the catalog.

The `media` table knows facts (dates, GPS, camera); it can't answer "show me sunsets" or
"beach days with the kids". This renders small previews (sips for photos — works on RAW;
ffmpeg frames for videos), sends them to Gemini in batches, and stores lowercase theme tags
plus a one-line caption in a `themes` table (with an FTS5 index) in the same catalog DB.
Idempotent and resumable: already-indexed files are skipped, so it's safe to kill and re-run,
and after a new card dump only the delta costs anything.

Usage:
  python3 theme-index.py                          # index everything not yet indexed (photos first)
  python3 theme-index.py --kind photo --limit 500
  python3 theme-index.py --where "year='2025'"    # extra SQL filter on the media table
  python3 theme-index.py --force                  # re-index even already-tagged files
Key: GEMINI_API_KEY (or GOOGLE_API_KEY) in env, or --key-file PATH.
Requires: sips (macOS), ffmpeg (only for videos), google-genai (pip install --user google-genai)
"""
import os, sys, json, time, sqlite3, argparse, subprocess, tempfile
from datetime import datetime, timezone

CATALOG = os.environ.get("MEDIA_CATALOG", os.path.expanduser("~/photos/catalog/gdrive_catalog.db"))
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"

# Steer Gemini toward a consistent vocabulary so "sunset" is always spelled "sunset".
VOCAB = ("sunset, sunrise, golden-hour, blue-hour, night, milky-way, beach, ocean, lake, river, "
         "waterfall, mountains, desert, canyon, forest, snow, clouds, storm, rainbow, aerial, "
         "cityscape, skyline, architecture, interior, street, road-trip, portrait, group-photo, "
         "family, kids, pets, dog, cat, wildlife, birds, flowers, macro, food, event, wedding, "
         "concert, sports, action, hiking, camping, boat, car, airplane, construction, mapping-site, "
         "real-estate, landscape, seascape, silhouette, reflection, long-exposure, black-and-white")

PROMPT = (
    "You are theme-tagging a photographer's archive so it can be searched by subject. "
    "For each numbered image (frames from one video count as ONE item when told so), return: "
    "`themes` — 3 to 8 lowercase tags for what is actually visible: main subject(s), setting, and "
    "light/mood when distinctive. Prefer these terms when they fit: {vocab}. Hyphenate multi-word "
    "tags; invent a tag only when nothing listed fits. "
    "`caption` — one short searchable sentence describing the image (who/what, where-ish, light). "
    "Tag only what you can see — no guessing names or places. Return JSON."
).format(vocab=VOCAB)

SCHEMA_ITEM = {"type": "object", "properties": {
    "index": {"type": "integer", "description": "1-based image number as presented"},
    "themes": {"type": "array", "items": {"type": "string"}},
    "caption": {"type": "string"}}, "required": ["index", "themes", "caption"]}


def load_key(key_file):
    for v in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(v):
            return os.environ[v].strip()
    if key_file and os.path.exists(key_file):
        return open(key_file).read().strip()
    sys.exit("No API key. Set GEMINI_API_KEY or pass --key-file.")


def ensure_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS themes(
      path TEXT PRIMARY KEY, themes TEXT, caption TEXT, model TEXT, indexed_at TEXT)""")
    con.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS themes_fts
      USING fts5(themes, caption, path UNINDEXED, content='themes', content_rowid='rowid')""")
    con.execute("""CREATE TRIGGER IF NOT EXISTS themes_ai AFTER INSERT ON themes BEGIN
      INSERT INTO themes_fts(rowid, themes, caption, path)
      VALUES (new.rowid, new.themes, new.caption, new.path); END""")
    con.execute("""CREATE TRIGGER IF NOT EXISTS themes_ad AFTER DELETE ON themes BEGIN
      INSERT INTO themes_fts(themes_fts, rowid, themes, caption, path)
      VALUES ('delete', old.rowid, old.themes, old.caption, old.path); END""")
    con.execute("""CREATE TRIGGER IF NOT EXISTS themes_au AFTER UPDATE ON themes BEGIN
      INSERT INTO themes_fts(themes_fts, rowid, themes, caption, path)
      VALUES ('delete', old.rowid, old.themes, old.caption, old.path);
      INSERT INTO themes_fts(rowid, themes, caption, path)
      VALUES (new.rowid, new.themes, new.caption, new.path); END""")
    con.commit()


def photo_preview(src, out, height):
    if os.path.exists(out):     # temp name is reused — a stale file would mask a sips failure
        os.remove(out)
    subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(height), src, "--out", out],
                   capture_output=True)
    return os.path.exists(out) and os.path.getsize(out) > 0


def video_frames(src, outdir, height, n=3):
    try:
        dur = float(subprocess.run([FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error",
              "-show_entries", "format=duration", "-of", "csv=p=0", src],
              capture_output=True, text=True).stdout.strip() or 0)
    except Exception:
        dur = 0
    frames = []
    for k in range(n):
        t = (dur * (0.15 + 0.7 * k / max(1, n - 1))) if dur else k * 2
        out = os.path.join(outdir, f"f{k}.jpg")
        if os.path.exists(out):
            os.remove(out)
        subprocess.run([FFMPEG, "-nostdin", "-ss", f"{t:.1f}", "-i", src, "-frames:v", "1",
                        "-vf", f"scale=-2:{height}", "-q:v", "5", "-y", out], capture_output=True)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            frames.append(out)
    return frames


def gemini_json(client, types_mod, model, parts, schema):
    for attempt in range(3):
        try:
            r = client.models.generate_content(model=model, contents=parts,
                config=types_mod.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema))
            return json.loads(r.text)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(20); continue
            print(f"    gemini error: {str(e)[:120]}")
            return None


def norm_themes(themes):
    seen, out = set(), []
    for t in themes or []:
        t = str(t).strip().lower().replace(" ", "-")
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=CATALOG)
    ap.add_argument("--kind", choices=["photo", "video", "all"], default="all")
    ap.add_argument("--where", default="", help="extra SQL filter on the media table")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=6, help="photos per Gemini request")
    ap.add_argument("--height", type=int, default=768, help="preview height in px")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--key-file")
    ap.add_argument("--force", action="store_true", help="re-index already-tagged files")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.catalog):
        sys.exit(f"No catalog at {a.catalog} — build it first (build-catalog.py, with the archive "
                 f"drive mounted), or point --catalog / $MEDIA_CATALOG at where it lives.")
    con = sqlite3.connect(a.catalog)
    ensure_schema(con)

    kinds = ["photo", "video"] if a.kind == "all" else [a.kind]
    q = ("SELECT path, kind FROM media WHERE kind IN (%s)" % ",".join("?" * len(kinds)))
    if not a.force:
        q += " AND path NOT IN (SELECT path FROM themes)"
    if a.where:
        q += f" AND ({a.where})"
    q += " ORDER BY kind, capture_date DESC"           # photos first, newest first
    if a.limit:
        q += f" LIMIT {a.limit}"
    todo = con.execute(q, kinds).fetchall()
    if not todo:
        print("Nothing to index — everything matching is already tagged. (--force re-tags.)")
        return

    # Rule-7 preflight: if the archive drive isn't mounted the paths won't exist — abort
    # cleanly instead of burning API calls on nothing.
    sample = todo[:50]
    missing = sum(1 for p, _ in sample if not os.path.exists(p))
    if missing == len(sample):
        sys.exit(f"None of the first {len(sample)} files exist — is the archive drive mounted?")

    n_photo = sum(1 for _, k in todo if k == "photo")
    print(f"{len(todo)} files to theme-index ({n_photo} photos, {len(todo)-n_photo} videos) "
          f"→ {a.catalog}")
    if a.dry_run:
        for p, k in todo[:40]:
            print(f"  would index [{k}] {p}")
        if len(todo) > 40:
            print(f"  … and {len(todo)-40} more")
        return

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=load_key(a.key_file))
    tmp = tempfile.mkdtemp(prefix="theme_")

    def save(path, themes, caption):
        # UPSERT, not INSERT OR REPLACE: REPLACE skips delete triggers unless
        # recursive_triggers is on (off by default), which would leave ghost FTS rows.
        con.execute("""INSERT INTO themes VALUES (?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                       themes=excluded.themes, caption=excluded.caption,
                       model=excluded.model, indexed_at=excluded.indexed_at""",
                    (path, json.dumps(norm_themes(themes)), (caption or "").strip(), a.model,
                     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))

    done = fail = 0
    photos = [p for p, k in todo if k == "photo" and os.path.exists(p)]
    videos = [p for p, k in todo if k == "video" and os.path.exists(p)]
    skipped = len(todo) - len(photos) - len(videos)
    if skipped:
        print(f"  (skipping {skipped} files not currently on disk)")

    # Photos: several per request, numbered in order.
    for b0 in range(0, len(photos), a.batch):
        batch = photos[b0:b0 + a.batch]
        parts, kept = [], []
        for p in batch:
            prev = os.path.join(tmp, "p.jpg")
            if photo_preview(p, prev, a.height):
                parts.append(types.Part.from_bytes(data=open(prev, "rb").read(),
                                                   mime_type="image/jpeg"))
                kept.append(p)
            else:
                print(f"    preview FAILED: {os.path.basename(p)}"); fail += 1
        if not kept:
            continue
        parts.append(f"{PROMPT}\nYou were sent {len(kept)} separate photos, numbered 1..{len(kept)} "
                     f"in order. Return one JSON array entry per photo.")
        res = gemini_json(client, types, a.model, parts,
                          {"type": "array", "items": SCHEMA_ITEM})
        if not res:
            fail += len(kept); continue
        by_idx = {d.get("index"): d for d in res if isinstance(d, dict)}
        for i, p in enumerate(kept, 1):
            d = by_idx.get(i)
            if d:
                save(p, d.get("themes"), d.get("caption")); done += 1
            else:
                fail += 1
        con.commit()
        last = by_idx.get(len(kept)) or {}
        print(f"  [{min(b0+a.batch,len(photos))}/{len(photos)} photos] "
              f"e.g. {os.path.basename(kept[-1])[:36]:36} → {', '.join(norm_themes(last.get('themes'))[:5])}")
        time.sleep(0.3)

    # Videos: one file per request, a few sampled frames = one item.
    for i, p in enumerate(videos, 1):
        frames = video_frames(p, tmp, a.height)
        if not frames:
            print(f"  [{i}/{len(videos)} videos] frames FAILED: {os.path.basename(p)}"); fail += 1
            continue
        parts = [types.Part.from_bytes(data=open(f_, "rb").read(), mime_type="image/jpeg")
                 for f_ in frames]
        parts.append(f"{PROMPT}\nThese {len(frames)} images are sampled frames from ONE video — "
                     f"treat them as a single item with index 1.")
        d = gemini_json(client, types, a.model, parts, SCHEMA_ITEM)
        if d:
            save(p, d.get("themes"), d.get("caption")); done += 1
            con.commit()
            print(f"  [{i}/{len(videos)} videos] {os.path.basename(p)[:36]:36} "
                  f"→ {', '.join(norm_themes(d.get('themes'))[:5])}")
        else:
            fail += 1
        time.sleep(0.3)

    total = con.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
    media = con.execute("SELECT COUNT(*) FROM media WHERE kind IN ('photo','video')").fetchone()[0]
    con.close()
    print(f"\nTagged {done} this run ({fail} failed). Theme index covers {total}/{media} files.")
    print("Search with /photo-archive:themes, or:")
    print("  sqlite3 CATALOG \"SELECT m.path FROM themes_fts f JOIN media m ON m.path=f.path "
          "WHERE themes_fts MATCH 'sunset OR \\\"golden-hour\\\"'\"")


if __name__ == "__main__":
    main()
