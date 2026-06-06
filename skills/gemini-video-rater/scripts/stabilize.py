#!/usr/bin/env python3
"""
stabilize.py — Two-pass vidstab stabilization to give already-good aerial clips a locked,
"floating on rails" broadcast feel. Run AFTER you've trimmed to a clean window.

Pipeline per clip:
  pass 1  vidstabdetect  — analyze motion, write a .trf transform file
  pass 2  vidstabtransform (smoothing + optzoom to hide the edge correction) + a light unsharp
          (vidstab softens a touch; a small sharpen restores crispness) → full-res H.264.

Needs an ffmpeg built WITH libvidstab. Stock Homebrew ffmpeg usually ISN'T — pass --ffmpeg to a
vidstab-enabled binary (e.g. an evermeet.cx static build) if `ffmpeg -filters | grep vidstab` is empty.

Usage:
  python3 stabilize.py --ffmpeg /tmp/ffvs/ffmpeg --out /out/dir  clipA.mp4 clipB.mp4
  python3 stabilize.py --from-file trims.txt --out /out/dir --smoothing 40
"""
import os, sys, argparse, subprocess, tempfile

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def has_vidstab(ff):
    return "vidstab" in run([ff,"-hide_banner","-filters"]).stdout

def stabilize(ff, src, out, smoothing, shakiness, zoom_mode):
    trf = os.path.join(tempfile.gettempdir(), "vidstab_"+os.path.basename(src)+".trf")
    # pass 1: detect. shakiness 1-10 (higher = assume shakier); accuracy 1-15 (higher = better/slower)
    p1 = run([ff,"-nostdin","-i",src,"-vf",
        f"vidstabdetect=shakiness={shakiness}:accuracy=15:result={trf}",
        "-f","null","-","-y"])
    if not os.path.exists(trf):
        return False, f"detect failed: {p1.stderr[-200:]}"
    # pass 2: transform. smoothing = #frames averaged each side (bigger = smoother/more locked).
    # optzoom=1 + zoom adaptively crops in so the stabilized edges never show black borders.
    vf = (f"vidstabtransform=input={trf}:smoothing={smoothing}:optzoom={zoom_mode}:zoom=0:"
          f"interpol=bicubic:crop=black,unsharp=5:5:0.8:3:3:0.4")
    p2 = run([ff,"-nostdin","-i",src,"-vf",vf,
        "-c:v","libx264","-preset","slow","-crf","17","-pix_fmt","yuv420p","-an","-y",out])
    try: os.remove(trf)
    except OSError: pass
    ok = os.path.exists(out) and os.path.getsize(out) > 0
    return ok, ("" if ok else f"transform failed: {p2.stderr[-200:]}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--from-file")
    ap.add_argument("--out", required=True, help="output dir for stabilized clips")
    ap.add_argument("--ffmpeg", default="ffmpeg", help="path to a vidstab-enabled ffmpeg")
    ap.add_argument("--smoothing", type=int, default=40, help="frames averaged; higher = more locked")
    ap.add_argument("--shakiness", type=int, default=4, help="1-10; gimbal footage is low, use 3-5")
    ap.add_argument("--optzoom", type=int, default=1, help="1 = adaptive zoom to hide edges")
    ap.add_argument("--suffix", default="_stab")
    a=ap.parse_args()

    files=list(a.files)
    if a.from_file: files += [l.strip() for l in open(a.from_file) if l.strip()]
    files=[f for f in files if os.path.exists(f)]
    if not files: sys.exit("No existing files given.")
    if not has_vidstab(a.ffmpeg):
        sys.exit(f"{a.ffmpeg} has no vidstab filters. Point --ffmpeg at a vidstab-enabled build.")
    os.makedirs(a.out, exist_ok=True)

    for i,src in enumerate(files,1):
        base=os.path.splitext(os.path.basename(src))[0]
        out=os.path.join(a.out, base+a.suffix+".mp4")
        ok,err=stabilize(a.ffmpeg, src, out, a.smoothing, a.shakiness, a.optzoom)
        print(f"  [{i}/{len(files)}] {'OK ' if ok else 'FAIL'} {os.path.basename(src)[:42]:42}"
              + ("" if ok else f"  {err}"))
    print(f"\nstabilized clips in {a.out}  (smoothing={a.smoothing}, shakiness={a.shakiness}, optzoom={a.optzoom})")

if __name__=="__main__": main()
