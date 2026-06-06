#!/usr/bin/env python3
"""
move-keepers.py — After culling a pulled selection, move the survivors to the project SSD.

Workflow:  archive (master) -> pull-selection.py -> working drive (CULL) -> move-keepers.py -> project SSD

Copies whatever is left in a pull folder to the project SSD (hash-verified), then removes it from
the working drive (a real move). The ARCHIVE master is never touched — these are working copies.

USAGE
  python3 move-keepers.py --from "/Volumes/T9/_PULLS/rmnp-landscapes" --to /Volumes/Project
  python3 move-keepers.py --from "/Volumes/T9/_PULLS/drone-meditation" --to /Volumes/Project --keep-source
"""
import os, sys, csv, time, hashlib, shutil, argparse, subprocess

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
def is_exfat(path):
    try:
        out=subprocess.run(["diskutil","info",path],capture_output=True,text=True).stdout
        return "exfat" in out.lower() or "ms-dos" in out.lower()
    except: return False

def main():
    ap=argparse.ArgumentParser(description="Move culled keepers to the project SSD.")
    ap.add_argument("--from", dest="src", required=True, help="the culled _PULLS/<label> folder")
    ap.add_argument("--to", required=True, help="project SSD mount, e.g. /Volumes/Project")
    ap.add_argument("--label", help="subfolder on the SSD (default: source folder name)")
    ap.add_argument("--keep-source", action="store_true", help="copy instead of move")
    a=ap.parse_args()
    if not os.path.isdir(a.src): print(f"Source not found: {a.src}"); sys.exit(1)
    if not os.path.isdir(a.to):  print(f"Project SSD not found: {a.to}"); sys.exit(1)
    label=a.label or os.path.basename(a.src.rstrip('/'))
    outdir=os.path.join(a.to, label); os.makedirs(outdir, exist_ok=True)

    exfat = is_exfat(a.to)
    files=[os.path.join(a.src,f) for f in os.listdir(a.src)
           if os.path.isfile(os.path.join(a.src,f)) and not f.startswith('.') and not f.endswith('_pull_manifest.csv')]
    big=[f for f in files if os.path.getsize(f) > 4*1024**3]
    if exfat and big:
        print(f"⚠  {a.to} is exFAT (4 GB file limit) and {len(big)} keeper(s) exceed 4 GB:")
        for f in big[:5]: print(f"     {os.path.getsize(f)/1e9:.1f} GB  {os.path.basename(f)}")
        print("   Reformat the project SSD to APFS first, or those files can't be copied.")
    c=dict(moved=0, bytes=0, fail=0, skipped_big=0)
    for f in files:
        if exfat and os.path.getsize(f) > 4*1024**3: c['skipped_big']+=1; continue
        dst=uniq(os.path.join(outdir, os.path.basename(f)))
        try:
            sh=H(f); shutil.copy2(f,dst)
            if H(dst)!=sh: os.remove(dst); c['fail']+=1; continue
            if not a.keep_source: os.remove(f)
            c['moved']+=1; c['bytes']+=os.path.getsize(dst)
        except Exception as e:
            c['fail']+=1; print(f"  ERROR {f}: {e}")
        if c['moved']%25==0 and c['moved']: print(f"  …{c['moved']} ({c['bytes']/1e9:.0f} GB)")
    print("\n============ KEEPERS MOVED ============")
    print(f"To project SSD    : {outdir}")
    print(f"Copied & verified : {c['moved']}  ({c['bytes']/1e9:.1f} GB)" + ("  (originals kept)" if a.keep_source else "  (removed from working drive)"))
    if c['skipped_big']: print(f"Skipped >4GB      : {c['skipped_big']}  (project SSD is exFAT — reformat APFS)")
    print(f"Failed            : {c['fail']}")

if __name__ == "__main__":
    main()
