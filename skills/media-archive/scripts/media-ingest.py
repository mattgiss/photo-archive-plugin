#!/usr/bin/env python3
"""
media-ingest.py — Securely back up & sort photos/videos from cards or any drive
into the date-sorted archive, and keep the media catalog up to date.

WHAT IT DOES
  * Auto-detects inserted camera cards (any volume with a DCIM/ or PRIVATE/ folder),
    or takes explicit source folders/drives as arguments.
  * Copies every photo/video into:
        <ARCHIVE>/PhotoArchive/Photos/YYYY/YYYY-MM-DD/   (photos)
        <ARCHIVE>/VideoArchive/YYYY/YYYY-MM-DD/          (videos)
    sorted by the capture date in each file's metadata.
  * HASH-VERIFIES every copy (BLAKE2b) before counting it done -> secure backup.
  * Skips files already in the archive (byte-identical), so re-running is safe & fast.
  * Updates the SQLite catalog so you never have to rescan the drive.
  * NEVER deletes from the source card. (Format cards in-camera once you've verified.)

USAGE
  python3 media-ingest.py                 # auto-detect & dump all inserted cards
  python3 media-ingest.py /Volumes/SOMEDRIVE/folder   # ingest a specific source
  python3 media-ingest.py --archive "/Volumes/G-DRIVE PROJECT"   # override archive
  python3 media-ingest.py --dry-run       # show what would happen, copy nothing

Requires: exiftool  (brew install exiftool)
"""
import os, sys, csv, time, hashlib, shutil, sqlite3, subprocess, argparse, re, glob

# ---------- config (override with env vars or flags) ----------
ARCHIVE = os.environ.get("MEDIA_ARCHIVE", "/Volumes/G-DRIVE PROJECT")
CATALOG = os.environ.get("MEDIA_CATALOG", os.path.expanduser("~/photos/catalog/gdrive_catalog.db"))
EXIFTOOL = "/opt/homebrew/bin/exiftool" if os.path.exists("/opt/homebrew/bin/exiftool") else "exiftool"

PHOTO_EXT = {'jpg','jpeg','heic','heif','png','tif','tiff','dng','cr2','cr3','nef','arw','raf','orf','rw2','gif','webp'}
VIDEO_EXT = {'mov','mp4','m4v','avi','mts','m2ts','3gp'}
SIDE_EXT  = {'xmp','aae','lrf','srt','xml','thm','wav'}   # sidecars that travel with their media
# Drone vs handheld: classify by camera model/encoder, NOT the "DJI_" filename — DJI Osmo
# (handheld) writes DJI_ filenames too. On DJI video the model is often in the Encoder tag.
HANDHELD_RE = re.compile(r'osmo|pocket|action|ronin|gopro|hero|insta360', re.I)
DRONE_RE    = re.compile(r'mavic|phantom|inspire|avata|matrice|\bair\s?\d|\bmini\s?\d|m[234]e\b|fc[0-9]{3,4}|l[123]d-|drone', re.I)
def classify_drone(make, model, encoder, rel_alt):
    blob = f"{make} {model} {encoder}".strip()
    if HANDHELD_RE.search(blob): return 0            # Osmo/Pocket/Action/GoPro = handheld, never drone
    if DRONE_RE.search(blob):    return 1            # known aircraft model = drone, at ANY altitude
    # Model unknown (often blank on DJI video): use flight altitude — airborne => drone, else handheld.
    # (A ground Osmo writes RelativeAltitude ~0, so a low/zero altitude with no drone model is handheld.)
    try:
        if abs(float(str(rel_alt).lstrip('+'))) > 1.5: return 1
    except (ValueError, TypeError):
        pass
    return 0

def log(msg, logfile):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    if logfile: open(logfile,'a').write(line+"\n")

def ext(p):
    e = p.rsplit('.',1); return e[1].lower() if len(e)==2 else ''

def H(path, bs=8*1024*1024):
    x = hashlib.blake2b()
    with open(path,'rb') as f:
        for b in iter(lambda: f.read(bs), b''): x.update(b)
    return x.hexdigest()

def uniq(dst):
    if not os.path.exists(dst): return dst
    s,dot,e = dst.rpartition('.'); i=1
    while True:
        c = f"{s}-{i}.{e}" if dot else f"{dst}-{i}"
        if not os.path.exists(c): return c
        i+=1

def detect_cards():
    # volumes to never treat as a card: the boot drive and the archive drive itself
    skip = {"/Volumes/Macintosh HD"}
    m = re.match(r'(/Volumes/[^/]+)', ARCHIVE)
    if m: skip.add(m.group(1))
    cards = set()
    # DCIM = universal camera marker (Canon/Sony/Nikon/Fuji/DJI/GoPro). Sony/AVCHD video roots too.
    # Use specific subpaths (not bare "PRIVATE") so the system /private folder isn't matched.
    for pat in ("/Volumes/*/DCIM", "/Volumes/*/PRIVATE/M4ROOT", "/Volumes/*/PRIVATE/AVCHD"):
        for hit in glob.glob(pat):
            vol = "/Volumes/" + hit.split('/Volumes/',1)[1].split('/')[0]
            if vol not in skip and os.path.isdir(vol):
                cards.add(vol)
    return sorted(cards)

def media_files(src):
    out = []
    for dp, dn, fn in os.walk(src):
        # Skip structured datasets — never date-sort inside Lightroom/FCP/Photos packages.
        if any(x in dp for x in ('.fcpbundle','.photoslibrary','.lrlibrary','.lrdata')): dn[:] = []; continue
        for f in fn:
            if f.startswith('._') or f.startswith('.'): continue
            if ext(f) in PHOTO_EXT or ext(f) in VIDEO_EXT:
                out.append(os.path.join(dp,f))
    return out

def read_meta(paths, logfile):
    """Batch exiftool -> dict keyed by path."""
    if not paths: return {}
    listfile = "/tmp/_ingest_list.txt"
    open(listfile,'w').write("\n".join(paths))
    cmd = [EXIFTOOL,"-csv","-n","-d","%Y-%m-%d",
           "-FileType","-FileSize#","-ImageWidth","-ImageHeight","-Megapixels","-Orientation",
           "-CreateDate","-DateTimeOriginal","-Make","-Model","-LensModel",
           "-GPSLatitude","-GPSLongitude","-Duration","-VideoFrameRate",
           "-Encoder","-RelativeAltitude","-@",listfile]
    r = subprocess.run(cmd, capture_output=True, text=True)
    meta = {}
    for row in csv.DictReader(r.stdout.splitlines()):
        meta[row.get('SourceFile','')] = row
    return meta

def date_of(path, m):
    d = (m.get('DateTimeOriginal') or m.get('CreateDate') or '')[:10].replace(':','-')
    if not d or len(d)<10 or not d[:4].isdigit() or d[:4]=='0000':
        try: d = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
        except: d = None
    return d

def orient(w,h,o):
    if not w or not h: return None
    if o in (6,8): w,h = h,w
    return 'landscape' if w>h else ('portrait' if h>w else 'square')

def fnum(x):
    try: return float(x)
    except: return None
def inum(x):
    try: return int(float(x))
    except: return None

def catalog_row(path, kind, m, date):
    rel = path.split(ARCHIVE+'/',1)[-1] if path.startswith(ARCHIVE+'/') else path
    loc = rel.split('/')[0] if '/' in rel else '(root)'
    w,h,o = inum(m.get('ImageWidth')), inum(m.get('ImageHeight')), inum(m.get('Orientation'))
    make, model = (m.get('Make') or '').strip(), (m.get('Model') or '').strip()
    lat, lon = fnum(m.get('GPSLatitude')), fnum(m.get('GPSLongitude'))
    drone = classify_drone(make, model, m.get('Encoder') or '', m.get('RelativeAltitude'))
    inarch = loc if loc in ('PhotoArchive','VideoArchive') else 'straggler'
    return (path, rel, loc, inarch, os.path.basename(path), ext(path), kind,
            inum(m.get('FileSize')) or (os.path.getsize(path) if os.path.exists(path) else None),
            m.get('FileType',''), w, h, fnum(m.get('Megapixels')), orient(w,h,o),
            date, (date[:4] if date else None), make, model, m.get('LensModel') or '',
            lat, lon, 1 if (lat and lon) else 0, fnum(m.get('Duration')), fnum(m.get('VideoFrameRate')), drone)

def ensure_catalog(con):
    con.execute("""CREATE TABLE IF NOT EXISTS media(
      path TEXT PRIMARY KEY, rel TEXT, location TEXT, in_archive TEXT, filename TEXT, ext TEXT,
      kind TEXT, size INTEGER, filetype TEXT, width INTEGER, height INTEGER, megapixels REAL,
      orientation TEXT, capture_date TEXT, year TEXT, make TEXT, model TEXT, lens TEXT,
      gps_lat REAL, gps_lon REAL, has_gps INTEGER, duration REAL, fps REAL, is_drone INTEGER)""")

def main():
    global ARCHIVE
    ap = argparse.ArgumentParser(description="Securely back up & sort media from cards/drives.")
    ap.add_argument("sources", nargs="*", help="source folders/drives (default: auto-detect cards)")
    ap.add_argument("--archive", default=ARCHIVE)
    ap.add_argument("--catalog", default=CATALOG)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ARCHIVE = a.archive
    logfile = f"/tmp/media-ingest-{time.strftime('%Y%m%d-%H%M%S')}.log"

    if not os.path.isdir(ARCHIVE):
        log(f"ERROR: archive not found: {ARCHIVE}", logfile); sys.exit(1)
    if not shutil.which(EXIFTOOL) and not os.path.exists(EXIFTOOL):
        log("ERROR: exiftool not installed (brew install exiftool)", logfile); sys.exit(1)

    sources = a.sources or detect_cards()
    if not sources:
        log("No cards detected and no sources given. Insert a card (must have a DCIM folder) "
            "or pass a folder path.", logfile); sys.exit(0)
    log(f"Archive : {ARCHIVE}", logfile)
    log(f"Sources : {', '.join(sources)}", logfile)

    files = []
    for s in sources: files += media_files(s)
    log(f"Found {len(files)} media files to evaluate.", logfile)
    if not files: sys.exit(0)

    log("Reading metadata (exiftool)…", logfile)
    meta = read_meta(files, logfile)

    PA = f"{ARCHIVE}/PhotoArchive/Photos"; VA = f"{ARCHIVE}/VideoArchive"
    con = None
    if not a.dry_run and os.path.exists(os.path.dirname(a.catalog) or '.'):
        con = sqlite3.connect(a.catalog); ensure_catalog(con)

    c = dict(copied=0, bytes=0, skipped=0, renamed=0, fail=0)
    new_rows = []
    for p in files:
        m = meta.get(p, {})
        kind = 'photo' if ext(p) in PHOTO_EXT else 'video'
        d = date_of(p, m)
        y, fol = (d[:4], d[:10]) if d else ('0000','0000-UNKNOWN')
        base = PA if kind=='photo' else VA
        dst = f"{base}/{y}/{fol}/{os.path.basename(p)}"
        try:
            sz = os.path.getsize(p)
            if os.path.exists(dst) and os.path.getsize(dst)==sz and H(dst)==H(p):
                c['skipped']+=1; continue                      # already securely backed up
            if a.dry_run:
                c['copied']+=1; c['bytes']+=sz; continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst): dst = uniq(dst); c['renamed']+=1
            src_hash = H(p); shutil.copy2(p, dst)
            if os.path.getsize(dst)!=sz or H(dst)!=src_hash:   # verify
                os.remove(dst); c['fail']+=1; log(f"VERIFY FAILED: {p}", logfile); continue
            c['copied']+=1; c['bytes']+=sz
            # carry sidecars (xmp/aae/lrf/srt…)
            stem = p.rsplit('.',1)[0]
            for sc in (stem+'.xmp', stem+'.XMP', p+'.xmp', stem+'.aae', stem+'.AAE',
                       stem+'.lrf', stem+'.LRF', stem+'.srt', stem+'.SRT'):
                if os.path.exists(sc):
                    sd = uniq(dst.rsplit('.',1)[0] + '.' + ext(sc))
                    try: shutil.copy2(sc, sd)
                    except: pass
            if con is not None:
                new_rows.append(catalog_row(dst, kind, m, d))
        except Exception as e:
            c['fail']+=1; log(f"ERROR {p}: {e}", logfile)
        if (c['copied']+c['skipped']) % 100 == 0:
            log(f"  …{c['copied']} copied, {c['skipped']} already backed up", logfile)

    if con is not None and new_rows:
        con.executemany("INSERT OR REPLACE INTO media VALUES (%s)"%",".join("?"*24), new_rows)
        con.commit(); con.close()

    log("", logfile)
    log("============ DUMP COMPLETE ============", logfile)
    log(f"Copied & verified : {c['copied']}  ({c['bytes']/1e9:.1f} GB)", logfile)
    log(f"Already backed up : {c['skipped']}  (skipped)", logfile)
    log(f"Renamed (clash)   : {c['renamed']}", logfile)
    log(f"Failed            : {c['fail']}", logfile)
    log(f"Catalog updated   : {len(new_rows)} new entries" if con is not None else "Catalog: (skipped)", logfile)
    log(f"Cards/sources were NOT modified. Log: {logfile}", logfile)
    if c['fail']: sys.exit(2)

if __name__ == "__main__":
    main()
