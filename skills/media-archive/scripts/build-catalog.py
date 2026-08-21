#!/usr/bin/env python3
"""
build-catalog.py — Rebuild the media catalog from scratch by scanning the archive.
Self-contained: enumerates media, runs exiftool once, derives query fields. LAST RESORT —
normally the catalog stays current via media-ingest.py; a full rescan of a big drive is slow.

Usage:  python3 build-catalog.py [--archive /Volumes/...] [--catalog ~/photos/catalog/gdrive_catalog.db]
Requires: exiftool
"""
import os, re, csv, sqlite3, subprocess, argparse, tempfile

ARCHIVE = os.environ.get("MEDIA_ARCHIVE", "/Volumes/G-DRIVE PROJECT")
CATALOG = os.environ.get("MEDIA_CATALOG", os.path.expanduser("~/photos/catalog/gdrive_catalog.db"))
EXIFTOOL = "/opt/homebrew/bin/exiftool" if os.path.exists("/opt/homebrew/bin/exiftool") else "exiftool"

PHOTO = {'jpg','jpeg','heic','heif','png','tif','tiff','dng','cr2','cr3','nef','arw','raf','orf','rw2','gif','webp'}
VIDEO = {'mov','mp4','m4v','avi','mts','m2ts','3gp'}
# Drone vs handheld — classify by model/encoder, never the DJI_ filename (Osmo writes DJI_ too).
HANDHELD_RE = re.compile(r'osmo|pocket|action|ronin|gopro|hero|insta360', re.I)
DRONE_RE    = re.compile(r'mavic|phantom|inspire|avata|matrice|\bair\s?\d|\bmini\s?\d|m[234]e\b|fc[0-9]{3,4}|l[123]d-|drone', re.I)
# Folders whose structure must be preserved — exclude from the date-sorted catalog scan's noise,
# but DO still catalog their media so it's findable. (Caches/previews are excluded as junk.)
SKIP = ('.fcpcache','Render Files','Transcoded Media','Proxy Media','Analysis Files')

def f(x):
    try: return float(x)
    except: return None
def i(x):
    try: return int(float(x))
    except: return None
def ext(p):
    e=p.rsplit('.',1); return e[1].lower() if len(e)==2 else ''

def classify_drone(make, model, encoder, rel_alt):
    blob=f"{make} {model} {encoder}".strip()
    if HANDHELD_RE.search(blob): return 0            # Osmo/Pocket/Action/GoPro = handheld
    if DRONE_RE.search(blob):    return 1            # known aircraft model = drone, at ANY altitude
    try:                                              # model unknown: airborne => drone
        if abs(float(str(rel_alt).lstrip('+'))) > 1.5: return 1
    except (ValueError, TypeError):
        pass
    return 0

def orient(w,h,o):
    if not w or not h: return None
    if o in (6,8): w,h=h,w
    return 'landscape' if w>h else ('portrait' if h>w else 'square')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--archive", default=ARCHIVE)
    ap.add_argument("--catalog", default=CATALOG)
    a=ap.parse_args()
    arch=a.archive
    if not os.path.isdir(arch):
        import sys; sys.exit(f"Archive not found at {arch} — is the drive mounted? "
                             f"(--archive / $MEDIA_ARCHIVE to point elsewhere)")
    os.makedirs(os.path.dirname(os.path.abspath(a.catalog)), exist_ok=True)
    print(f"Scanning {arch} … (this reads the whole drive — slow on multi-TB)")

    paths=[]
    for dp,dn,fn in os.walk(arch):
        if any(s in dp for s in SKIP): dn[:]=[]; continue
        for fn_ in fn:
            if fn_.startswith('._') or fn_.startswith('.'): continue
            if ext(fn_) in PHOTO or ext(fn_) in VIDEO:
                paths.append(os.path.join(dp,fn_))
    print(f"  {len(paths)} media files found. Reading metadata with exiftool…")

    lf=tempfile.NamedTemporaryFile('w',delete=False,suffix='.txt'); lf.write("\n".join(paths)); lf.close()
    cmd=[EXIFTOOL,"-csv","-n","-d","%Y-%m-%d",
         "-FileType","-FileSize#","-ImageWidth","-ImageHeight","-Megapixels","-Orientation",
         "-CreateDate","-DateTimeOriginal","-Make","-Model","-LensModel",
         "-GPSLatitude","-GPSLongitude","-Duration","-VideoFrameRate",
         "-Encoder","-RelativeAltitude","-@",lf.name]
    out=subprocess.run(cmd,capture_output=True,text=True).stdout
    meta={r.get('SourceFile',''):r for r in csv.DictReader(out.splitlines())}

    con=sqlite3.connect(a.catalog); con.execute("DROP TABLE IF EXISTS media")
    con.execute("""CREATE TABLE media(
      path TEXT PRIMARY KEY, rel TEXT, location TEXT, in_archive TEXT, filename TEXT, ext TEXT,
      kind TEXT, size INTEGER, filetype TEXT, width INTEGER, height INTEGER, megapixels REAL,
      orientation TEXT, capture_date TEXT, year TEXT, make TEXT, model TEXT, lens TEXT,
      gps_lat REAL, gps_lon REAL, has_gps INTEGER, duration REAL, fps REAL, is_drone INTEGER, tag TEXT)""")
    rows=[]
    for p in paths:
        m=meta.get(p,{}); e=ext(p)
        rel=p.split(arch+'/',1)[-1] if p.startswith(arch+'/') else p
        loc=rel.split('/')[0] if '/' in rel else '(root)'
        kind='photo' if e in PHOTO else ('video' if e in VIDEO else 'other')
        w,h,o=i(m.get('ImageWidth')),i(m.get('ImageHeight')),i(m.get('Orientation'))
        make,model=(m.get('Make') or '').strip(),(m.get('Model') or '').strip()
        d=(m.get('DateTimeOriginal') or m.get('CreateDate') or '')[:10].replace(':','-') or None
        lat,lon=f(m.get('GPSLatitude')),f(m.get('GPSLongitude'))
        rows.append((p,rel,loc, loc if loc in ('PhotoArchive','VideoArchive') else 'straggler',
            os.path.basename(p),e,kind, i(m.get('FileSize')) or (os.path.getsize(p) if os.path.exists(p) else None),
            m.get('FileType',''),w,h,f(m.get('Megapixels')),orient(w,h,o),
            d,(d[:4] if d else None),make,model,m.get('LensModel') or '',
            lat,lon,1 if (lat and lon) else 0,f(m.get('Duration')),f(m.get('VideoFrameRate')),
            classify_drone(make,model,m.get('Encoder') or '',m.get('RelativeAltitude')), None))
    con.executemany("INSERT OR REPLACE INTO media VALUES (%s)"%",".join("?"*25),rows)
    for c in ['location','in_archive','kind','orientation','is_drone','has_gps','year','tag']:
        con.execute(f"CREATE INDEX IF NOT EXISTS idx_{c} ON media({c})")
    con.commit()
    n=con.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    dr=con.execute("SELECT COUNT(*) FROM media WHERE is_drone=1").fetchone()[0]
    con.close()
    os.unlink(lf.name)
    print(f"Catalog built: {a.catalog}  ({n} media, {dr} drone)")

if __name__=="__main__": main()
