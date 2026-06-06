#!/usr/bin/env python3
"""
pull-selection.py — Pull a selection from the archive onto a working drive to cull.

Workflow:  archive (master)  ->  [pull]  ->  working drive (cull here)  ->  project SSD (keepers)

Queries the catalog, copies matching files (hash-verified, copy-only — the archive master is
never touched) into  <dest>/_PULLS/<label>/  as a flat folder you can flip through and delete
rejects from. Writes a manifest so a later "move keepers" step knows where each file came from.

USAGE
  python3 pull-selection.py --preset rmnp-landscapes --dest /Volumes/T9
  python3 pull-selection.py --preset drone-meditation --dest /Volumes/T9 --max-gb 700
  python3 pull-selection.py --label myset --where "kind='photo' AND make LIKE 'SONY%'" --dest /Volumes/T9

  --max-gb N   stop after ~N GB (takes highest-priority items first)
  --dry-run    list what would be pulled, copy nothing
"""
import os, sys, csv, time, hashlib, shutil, sqlite3, argparse

CATALOG = os.environ.get("MEDIA_CATALOG", os.path.expanduser("~/photos/catalog/gdrive_catalog.db"))

PRESETS = {
  # label: (WHERE clause, ORDER BY priority)
  "rmnp-landscapes": (
     "kind='photo' AND orientation='landscape' AND has_gps=1 AND megapixels>=8 "
     "AND gps_lat BETWEEN 40.1 AND 40.6 AND gps_lon BETWEEN -105.9 AND -105.4",
     "megapixels DESC, capture_date DESC"),
  "drone-meditation": (
     "kind='video' AND is_drone=1 AND duration>60 AND height>=2160",
     "duration DESC"),
  "landscapes-print": (
     "kind='photo' AND orientation='landscape' AND megapixels>=20",
     "megapixels DESC, capture_date DESC"),
}

def H(p, bs=8*1024*1024):
    x=hashlib.blake2b()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(bs), b''): x.update(b)
    return x.hexdigest()

def uniq(d):
    if not os.path.exists(d): return d
    s,dot,e=d.rpartition('.'); i=1
    while True:
        c=f"{s}-{i}.{e}" if dot else f"{d}-{i}"
        if not os.path.exists(c): return c
        i+=1

def main():
    ap=argparse.ArgumentParser(description="Pull a selection from the archive to a working drive.")
    ap.add_argument("--preset", choices=list(PRESETS))
    ap.add_argument("--where", help="custom SQL WHERE (instead of --preset)")
    ap.add_argument("--order", default="capture_date DESC")
    ap.add_argument("--label", help="folder name under <dest>/_PULLS/ (defaults to preset name)")
    ap.add_argument("--dest", default="/Volumes/T9")
    ap.add_argument("--catalog", default=CATALOG)
    ap.add_argument("--max-gb", type=float, default=0, help="cap total size in GB (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true")
    a=ap.parse_args()

    if a.preset: where, order = PRESETS[a.preset]; label=a.label or a.preset
    elif a.where: where, order = a.where, a.order; label=a.label or "pull"
    else: print("Give --preset or --where"); sys.exit(1)
    if not os.path.isdir(a.dest): print(f"Destination not found: {a.dest}"); sys.exit(1)

    con=sqlite3.connect(a.catalog)
    rows=con.execute(f"SELECT path,size,filename,capture_date FROM media WHERE {where} ORDER BY {order}").fetchall()
    con.close()
    outdir=os.path.join(a.dest, "_PULLS", label)
    cap=a.max_gb*1e9 if a.max_gb else None

    print(f"Selection '{label}': {len(rows)} files, {sum(r[1] or 0 for r in rows)/1e9:.1f} GB")
    print(f"Destination: {outdir}" + (f"   (cap {a.max_gb} GB)" if cap else ""))
    if a.dry_run:
        for p,s,fn,d in rows[:20]: print(f"  {(s or 0)/1e6:7.0f} MB  {d}  {fn}")
        if len(rows)>20: print(f"  …and {len(rows)-20} more");
        return

    os.makedirs(outdir, exist_ok=True)
    man=open(os.path.join(outdir,"_pull_manifest.csv"),'w',newline='')
    mw=csv.writer(man); mw.writerow(['source_in_archive','copied_to','size','capture_date'])
    c=dict(copied=0, bytes=0, skipped=0, fail=0, capped=0)
    for p,s,fn,d in rows:
        if cap and c['bytes']+ (s or 0) > cap: c['capped']+=1; continue
        if not os.path.exists(p): c['fail']+=1; continue
        dst=os.path.join(outdir, os.path.basename(p))
        try:
            if os.path.exists(dst) and os.path.getsize(dst)==(s or os.path.getsize(p)):
                c['skipped']+=1; continue
            if os.path.exists(dst): dst=uniq(dst)
            sh=H(p); shutil.copy2(p,dst)
            if H(dst)!=sh: os.remove(dst); c['fail']+=1; continue
            c['copied']+=1; c['bytes']+= (s or os.path.getsize(dst))
            mw.writerow([p,dst,s,d])
        except Exception as e:
            c['fail']+=1; print(f"  ERROR {p}: {e}")
        if c['copied']%25==0 and c['copied']: print(f"  …{c['copied']} copied ({c['bytes']/1e9:.0f} GB)")
    man.close()
    print("\n============ PULL COMPLETE ============")
    print(f"Copied & verified : {c['copied']}  ({c['bytes']/1e9:.1f} GB)")
    print(f"Already present   : {c['skipped']}")
    if c['capped']: print(f"Skipped (over cap): {c['capped']}  — raise --max-gb or free space to get them")
    print(f"Failed            : {c['fail']}")
    print(f"Folder            : {outdir}")
    print("Cull here, then move the keepers to your project SSD. Archive master is untouched.")

if __name__ == "__main__":
    main()
