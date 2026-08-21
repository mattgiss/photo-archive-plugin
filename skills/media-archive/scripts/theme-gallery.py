#!/usr/bin/env python3
"""
theme-gallery.py — Render a browsable HTML contact sheet of the archive, grouped by theme.

Turns the theme index (built by theme-index.py) into something you can LOOK at: an overview
page with a section per theme, or a single-query sheet. Thumbnails are rendered locally
(sips for photos — works on RAW; ffmpeg middle frame for videos) into the output folder, so
the page keeps working offline; each thumb links to the original file on the archive drive.

Usage:
  python3 theme-gallery.py                                  # overview: all themes, sampled
  python3 theme-gallery.py --theme sunset                   # everything tagged sunset
  python3 theme-gallery.py --query "beach OR ocean" --kind photo --year 2025
  python3 theme-gallery.py --theme aerial --out ~/photos/galleries/aerial --open
Requires: sips (macOS); ffmpeg only for video thumbs.
"""
import os, sys, html, hashlib, sqlite3, argparse, subprocess

CATALOG = os.environ.get("MEDIA_CATALOG", os.path.expanduser("~/photos/catalog/gdrive_catalog.db"))
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"

CSS = """
body{background:#111;color:#ddd;font:14px -apple-system,Helvetica,sans-serif;margin:0;padding:24px}
h1{font-weight:600} h2{margin:28px 0 10px;font-weight:600;color:#fff}
h2 small{color:#888;font-weight:400}
.grid{display:flex;flex-wrap:wrap;gap:8px}
.grid a{position:relative;display:block;line-height:0}
.grid img{height:180px;border-radius:6px;display:block}
.grid .vid::after{content:"▶";position:absolute;top:6px;left:8px;color:#fff;
  text-shadow:0 0 4px #000;font-size:16px;line-height:1}
.meta{color:#888;margin:4px 0 16px}
"""


def thumb(src, kind, out, height):
    if os.path.exists(out):
        return True
    if kind == "video":
        try:
            dur = float(subprocess.run([FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "error",
                  "-show_entries", "format=duration", "-of", "csv=p=0", src],
                  capture_output=True, text=True).stdout.strip() or 0)
        except Exception:
            dur = 0
        subprocess.run([FFMPEG, "-nostdin", "-ss", f"{dur/2:.1f}", "-i", src, "-frames:v", "1",
                        "-vf", f"scale=-2:{height}", "-q:v", "5", "-y", out], capture_output=True)
    else:
        subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(height), src, "--out", out],
                       capture_output=True)
    return os.path.exists(out) and os.path.getsize(out) > 0


def cell(row, tdir_rel, tname, ok):
    path, kind, date, caption = row
    if not ok:
        return ""
    title = html.escape(f"{os.path.basename(path)} · {date or '?'} — {caption or ''}")
    cls = ' class="vid"' if kind == "video" else ""
    return (f'<a{cls} href="file://{html.escape(path)}" title="{title}">'
            f'<img src="{tdir_rel}/{tname}" loading="lazy"></a>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=CATALOG)
    ap.add_argument("--theme", help="single theme tag, exact (e.g. sunset)")
    ap.add_argument("--query", help="FTS query over themes+captions (e.g. \"beach OR ocean\")")
    ap.add_argument("--kind", choices=["photo", "video"])
    ap.add_argument("--year")
    ap.add_argument("--per-theme", type=int, default=12, help="overview: thumbs sampled per theme")
    ap.add_argument("--limit", type=int, default=400, help="max thumbs on a query/theme sheet")
    ap.add_argument("--height", type=int, default=360, help="thumb height in px")
    ap.add_argument("--out", default=os.path.expanduser("~/photos/galleries/themes"))
    ap.add_argument("--open", action="store_true", help="open the page when done")
    a = ap.parse_args()

    if not os.path.exists(a.catalog):
        sys.exit(f"No catalog at {a.catalog} — build it first (build-catalog.py), or point "
                 f"--catalog / $MEDIA_CATALOG at where it lives.")
    con = sqlite3.connect(a.catalog)
    if not con.execute("SELECT name FROM sqlite_master WHERE name='themes'").fetchone() or \
       not con.execute("SELECT COUNT(*) FROM themes").fetchone()[0]:
        sys.exit("No theme index yet — build it first: python3 theme-index.py")

    extra, args = "", []
    if a.kind:
        extra += " AND m.kind=?"; args.append(a.kind)
    if a.year:
        extra += " AND m.year=?"; args.append(a.year)

    os.makedirs(os.path.join(a.out, "thumbs"), exist_ok=True)
    sections = []   # (title, count, [rows])

    if a.theme or a.query:
        if a.theme:
            q = ("SELECT m.path, m.kind, m.capture_date, t.caption FROM themes t "
                 "JOIN media m ON m.path=t.path WHERE EXISTS "
                 "(SELECT 1 FROM json_each(t.themes) j WHERE j.value=?)" + extra +
                 " ORDER BY m.capture_date DESC")
            rows = con.execute(q, [a.theme.lower()] + args).fetchall()
            title = f"#{a.theme}"
        else:
            q = ("SELECT m.path, m.kind, m.capture_date, t.caption FROM themes_fts f "
                 "JOIN themes t ON t.path=f.path JOIN media m ON m.path=f.path "
                 "WHERE themes_fts MATCH ?" + extra + " ORDER BY rank")
            rows = con.execute(q, [a.query] + args).fetchall()
            title = a.query
        if rows:
            sections.append((title, len(rows), rows[:a.limit]))
    else:
        themes = con.execute(
            "SELECT j.value, COUNT(*) n FROM themes t, json_each(t.themes) j "
            "GROUP BY j.value ORDER BY n DESC").fetchall()
        for theme, n in themes:
            rows = con.execute(
                "SELECT m.path, m.kind, m.capture_date, t.caption FROM themes t "
                "JOIN media m ON m.path=t.path WHERE EXISTS "
                "(SELECT 1 FROM json_each(t.themes) j WHERE j.value=?)" + extra +
                " ORDER BY m.capture_date DESC LIMIT ?", [theme] + args + [a.per_theme]).fetchall()
            if rows:
                sections.append((f"#{theme}", n, rows))

    if not sections:
        sys.exit("No matches in the theme index for that query/filters.")

    body, made, miss = [], 0, 0
    for title, count, rows in sections:
        cells = []
        for r in rows:
            if not os.path.exists(r[0]):
                miss += 1; continue
            tname = hashlib.md5(r[0].encode()).hexdigest()[:16] + ".jpg"
            ok = thumb(r[0], r[1], os.path.join(a.out, "thumbs", tname), a.height)
            made += 1 if ok else 0
            cells.append(cell(r, "thumbs", tname, ok))
        if cells:
            shown = f" <small>({len(rows)} of {count})</small>" if count > len(rows) else \
                    f" <small>({count})</small>"
            body.append(f"<h2>{html.escape(title)}{shown}</h2><div class=grid>{''.join(cells)}</div>")

    page = (f"<!doctype html><meta charset=utf-8><title>Archive themes</title><style>{CSS}</style>"
            f"<h1>Archive — themes</h1><p class=meta>hover for caption · click opens the original"
            f"{' · some files were offline' if miss else ''}</p>" + "".join(body))
    out = os.path.join(a.out, "index.html")
    open(out, "w").write(page)
    print(f"Gallery: {out}  ({made} thumbs{', ' + str(miss) + ' files offline' if miss else ''})")
    if a.open:
        subprocess.run(["open", out])


if __name__ == "__main__":
    main()
