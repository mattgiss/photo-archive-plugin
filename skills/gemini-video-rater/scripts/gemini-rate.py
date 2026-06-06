#!/usr/bin/env python3
"""
gemini-rate.py — Have Gemini WATCH video clips and rate them against a goal, then rank.

Claude can't see motion; Gemini can. This compresses each clip to a small sampled preview,
uploads it, asks Gemini for a structured rating against the stated --goal, and prints a ranked
table (+ writes gemini_ratings.json).

Usage:
  python3 gemini-rate.py --goal "steady aerial flyovers for a calm meditation video" clipA.mp4 clipB.mov
  python3 gemini-rate.py --goal "..." --from-file clips.txt --dimensions steadiness,scenery
Key: set GEMINI_API_KEY (or GOOGLE_API_KEY) in env, or pass --key-file PATH.
Requires: ffmpeg, google-genai (pip install --user google-genai)
"""
import os, sys, time, json, argparse, subprocess, tempfile

def load_key(key_file):
    for v in ("GEMINI_API_KEY","GOOGLE_API_KEY"):
        if os.environ.get(v): return os.environ[v].strip()
    if key_file and os.path.exists(key_file):
        return open(key_file).read().strip()
    sys.exit("No API key. Set GEMINI_API_KEY or pass --key-file.")

def compress(ff, src, out, sample, height):
    # fast-seek to a bit past the start, grab `sample` seconds at `height`p, drop audio
    try:
        dur = float(subprocess.run([ff.replace("ffmpeg","ffprobe"),"-v","error","-show_entries",
              "format=duration","-of","csv=p=0",src],capture_output=True,text=True).stdout.strip() or 0)
    except Exception:
        dur = 0
    ss = max(2, dur*0.12) if dur else 2
    subprocess.run([ff,"-nostdin","-ss",f"{ss:.1f}","-t",str(sample),"-i",src,
        "-vf",f"scale={height}:-2","-c:v","libx264","-preset","ultrafast","-crf","32","-an","-y",out],
        capture_output=True)
    return os.path.exists(out) and os.path.getsize(out)>0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--from-file")
    ap.add_argument("--goal", required=True, help="what the clips are FOR (drives the fit score)")
    ap.add_argument("--dimensions", default="", help="extra 1-10 scores to collect, comma-separated")
    ap.add_argument("--sample", type=int, default=90)
    ap.add_argument("--height", type=int, default=640)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--key-file")
    ap.add_argument("--out", default="gemini_ratings.json")
    a=ap.parse_args()

    files=list(a.files)
    if a.from_file: files += [l.strip() for l in open(a.from_file) if l.strip()]
    files=[f for f in files if os.path.exists(f)]
    if not files: sys.exit("No existing video files given.")

    from google import genai
    from google.genai import types
    client=genai.Client(api_key=load_key(a.key_file))
    ff="/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"

    dims=[d.strip() for d in a.dimensions.split(",") if d.strip()]
    props={"fit":{"type":"integer","description":f"1-10 fit for: {a.goal}"},
           "labels":{"type":"array","items":{"type":"string"}},
           "summary":{"type":"string","description":"one short sentence"}}
    for d in dims: props[d]={"type":"integer","description":f"1-10 {d}"}
    schema={"type":"object","properties":props,"required":["fit","labels","summary"]+dims}
    prompt=(f"You are selecting video clips for this purpose: {a.goal}. "
            f"Watch the clip carefully (motion matters). Rate `fit` 1-10 for that purpose, give a few "
            f"descriptive `labels`, and a one-sentence `summary` of what's on screen and how it moves."
            + (f" Also rate each 1-10: {', '.join(dims)}." if dims else "") + " Return JSON.")

    tmp=tempfile.mkdtemp(prefix="gvr_")
    results=[]
    for i,src in enumerate(files,1):
        prev=os.path.join(tmp,f"{i}.mp4")
        if not compress(ff,src,prev,a.sample,a.height):
            print(f"  [{i}/{len(files)}] compress FAILED: {os.path.basename(src)}"); continue
        try:
            fobj=client.files.upload(file=prev)
            while fobj.state and fobj.state.name=="PROCESSING":
                time.sleep(2); fobj=client.files.get(name=fobj.name)
            d=None
            for attempt in range(3):
                try:
                    r=client.models.generate_content(model=a.model, contents=[fobj,prompt],
                        config=types.GenerateContentConfig(response_mime_type="application/json",response_schema=schema))
                    d=json.loads(r.text); break
                except Exception as e:
                    if "429" in str(e) and attempt<2: time.sleep(20); continue
                    print(f"  [{i}/{len(files)}] rate error: {str(e)[:100]}"); break
            try: client.files.delete(name=fobj.name)
            except Exception: pass
            if d:
                d["file"]=src; results.append(d)
                print(f"  [{i}/{len(files)}] fit={d['fit']:>2}  {os.path.basename(src)[:40]:40}  {d['summary'][:60]}")
        except Exception as e:
            print(f"  [{i}/{len(files)}] upload error: {str(e)[:100]}")
        time.sleep(0.5)

    results.sort(key=lambda x:x.get("fit",0), reverse=True)
    json.dump(results, open(a.out,"w"), indent=1)
    print(f"\n=== ranked by fit (goal: {a.goal}) ===")
    for d in results:
        extra=" ".join(f"{k}={d[k]}" for k in dims if k in d)
        print(f"  fit {d['fit']:>2}  {extra}  {os.path.basename(d['file'])[:44]:44} | {', '.join(d.get('labels',[]))}")
    print(f"\nwrote {a.out}  ({len(results)} rated)")

if __name__=="__main__": main()
