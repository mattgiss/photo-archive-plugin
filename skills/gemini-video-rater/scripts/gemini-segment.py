#!/usr/bin/env python3
"""
gemini-segment.py — Have Gemini WATCH a full clip, mark the single best continuous
segment for a goal (e.g. the most peaceful/steady window), then trim the ORIGINAL to it.

Claude can't watch motion to know *where* a clip is steady vs. where it pans or catches a
vehicle. Gemini can. This compresses the WHOLE clip to a small preview (timestamps aligned
to the source — no seek offset), asks Gemini for the best [start,end] window within a length
range, then cuts that span out of the full-res original with ffmpeg.

Usage:
  python3 gemini-segment.py --goal "peaceful, perfectly steady aerial flyover for a meditation loop" \
      --min 20 --max 60 --trim /out/dir  clipA.mp4 clipB.mov
  python3 gemini-segment.py --goal "..." --from-file clips.txt --trim /out/dir
Key: GEMINI_API_KEY / GOOGLE_API_KEY in env, or --key-file PATH (loaded, never printed).
Requires: ffmpeg, google-genai
"""
import os, sys, time, json, argparse, subprocess, tempfile

def load_key(key_file):
    for v in ("GEMINI_API_KEY","GOOGLE_API_KEY"):
        if os.environ.get(v): return os.environ[v].strip()
    if key_file and os.path.exists(key_file):
        return open(key_file).read().strip()
    sys.exit("No API key. Set GEMINI_API_KEY or pass --key-file.")

def ffbin(name):
    p=f"/opt/homebrew/bin/{name}"
    return p if os.path.exists(p) else name

def duration(src):
    try:
        return float(subprocess.run([ffbin("ffprobe"),"-v","error","-show_entries",
            "format=duration","-of","csv=p=0",src],capture_output=True,text=True).stdout.strip() or 0)
    except Exception:
        return 0.0

def preview(src, out, height):
    # WHOLE clip, no -ss: preview timeline == source timeline so Gemini's timestamps map back 1:1
    subprocess.run([ffbin("ffmpeg"),"-nostdin","-i",src,"-vf",f"scale={height}:-2",
        "-c:v","libx264","-preset","ultrafast","-crf","32","-an","-y",out],capture_output=True)
    return os.path.exists(out) and os.path.getsize(out)>0

def trim(src, out, start, end):
    # accurate seek + re-encode at high quality, drop audio (meditation footage gets its own music)
    subprocess.run([ffbin("ffmpeg"),"-nostdin","-ss",f"{start:.2f}","-to",f"{end:.2f}","-i",src,
        "-c:v","libx264","-preset","slow","-crf","18","-pix_fmt","yuv420p","-an","-y",out],
        capture_output=True)
    return os.path.exists(out) and os.path.getsize(out)>0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--from-file")
    ap.add_argument("--goal", required=True, help="what the ideal segment should be")
    ap.add_argument("--min", type=float, default=20, help="min segment length (s)")
    ap.add_argument("--max", type=float, default=60, help="max segment length (s)")
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--key-file")
    ap.add_argument("--trim", help="output dir; if set, writes trimmed full-res clips here")
    ap.add_argument("--out", default="gemini_segments.json")
    a=ap.parse_args()

    files=list(a.files)
    if a.from_file: files += [l.strip() for l in open(a.from_file) if l.strip()]
    files=[f for f in files if os.path.exists(f)]
    if not files: sys.exit("No existing video files given.")
    if a.trim: os.makedirs(a.trim, exist_ok=True)

    from google import genai
    from google.genai import types
    client=genai.Client(api_key=load_key(a.key_file))

    schema={"type":"object","properties":{
        "start_sec":{"type":"number","description":"start of best segment, seconds from clip start"},
        "end_sec":{"type":"number","description":"end of best segment, seconds from clip start"},
        "steadiness":{"type":"integer","description":"1-10 camera stability across that segment"},
        "peace":{"type":"integer","description":"1-10 calm/consistency across that segment"},
        "summary":{"type":"string","description":"what's on screen in that window and how it moves"},
        "avoid":{"type":"string","description":"what's wrong with the REST of the clip (pans, vehicles, jitter, people)"}},
        "required":["start_sec","end_sec","steadiness","peace","summary","avoid"]}

    tmp=tempfile.mkdtemp(prefix="gseg_")
    results=[]
    for i,src in enumerate(files,1):
        dur=duration(src)
        prev=os.path.join(tmp,f"{i}.mp4")
        if not preview(src,prev,a.height):
            print(f"  [{i}/{len(files)}] preview FAILED: {os.path.basename(src)}"); continue
        prompt=(f"This clip is {dur:.0f} seconds long. I need the SINGLE BEST continuous segment for: {a.goal}. "
                f"Watch the whole clip and find one window, between {a.min:.0f} and {a.max:.0f} seconds long, where the "
                f"camera is most locked-off and the scene is most consistent — no abrupt pans/tilts/zooms, no jitter, "
                f"no vehicles/people/distracting motion entering frame, no exposure flicker. Return start_sec and end_sec "
                f"(seconds from the very start of the clip, within 0..{dur:.0f}), rate steadiness and peace 1-10 for THAT "
                f"window, summarize what's in it, and in `avoid` note what disqualifies the rest of the clip. Return JSON.")
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
            if not d: continue
            # clamp to clip bounds + requested length
            s=max(0.0, float(d["start_sec"])); e=min(dur if dur else float(d["end_sec"]), float(d["end_sec"]))
            if e-s < a.min and dur: e=min(dur, s+a.min)
            if e-s > a.max: e=s+a.max
            d.update({"file":src,"dur":round(dur,1),"start":round(s,2),"end":round(e,2),"len":round(e-s,2)})
            out_path=None
            if a.trim:
                base=os.path.splitext(os.path.basename(src))[0]
                out_path=os.path.join(a.trim, f"{base}_trim_{int(s)}-{int(e)}.mp4")
                if trim(src,out_path,s,e): d["trimmed"]=out_path
                else: d["trimmed"]=None; print(f"  [{i}] trim FAILED")
            results.append(d)
            print(f"  [{i}/{len(files)}] steady={d['steadiness']} peace={d['peace']}  "
                  f"{d['start']:.0f}-{d['end']:.0f}s ({d['len']:.0f}s)  {os.path.basename(src)[:34]:34} | {d['summary'][:50]}")
        except Exception as e:
            print(f"  [{i}/{len(files)}] error: {str(e)[:100]}")
        time.sleep(0.5)

    results.sort(key=lambda x:(x.get("peace",0),x.get("steadiness",0)), reverse=True)
    json.dump(results, open(a.out,"w"), indent=1)
    print(f"\n=== best segments (goal: {a.goal}) ===")
    for d in results:
        print(f"  peace {d['peace']:>2} steady {d['steadiness']:>2}  {d['start']:.0f}-{d['end']:.0f}s "
              f"({d['len']:.0f}s)  {os.path.basename(d['file'])[:40]:40}")
        print(f"      keep: {d['summary']}")
        print(f"      cut:  {d['avoid']}")
    print(f"\nwrote {a.out}  ({len(results)} segmented)" + (f", trims in {a.trim}" if a.trim else ""))

if __name__=="__main__": main()
