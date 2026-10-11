"""The local capture date of a photo or video: the day it was shot, where it was shot.

Photos carry local time (EXIF DateTimeOriginal). Videos (MP4/MOV) store QuickTime CreateDate in UTC, so a clip
shot after 6 pm in Colorado already has the next day's date there. For videos, in order:
  1. a Sony clip sidecar <stem>M01.XML: CreationDate is local time with its zone
  2. a DJI_YYYYMMDDHHMMSS_ file name (drones, Osmo): local time
  3. QuickTime CreationDate (Apple devices: local with zone) or DateTimeOriginal
  4. QuickTime CreateDate converted from UTC to this Mac's time zone (exiftool -api QuickTimeUTC)
and finally the file's modified date.

Callers read metadata with EXIF_ARGS (exiftool -csv -n) so 3 and 4 are available.
"""
import os, re, time

EXIF_ARGS = ["-api", "QuickTimeUTC", "-CreateDate", "-DateTimeOriginal", "-CreationDate"]
_DATE = re.compile(r"(\d{4})[:-](\d\d)[:-](\d\d)")


def _ymd(s):
    m = _DATE.match(str(s or "").strip())
    if not m or m.group(1) == "0000":
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def sony_xml_date(path):
    stem = path.rsplit(".", 1)[0]
    for x in (stem + "M01.XML", stem + "M01.xml"):
        if os.path.exists(x):
            try:
                txt = open(x, errors="ignore").read(8192)
            except OSError:
                return None
            m = re.search(r'<CreationDate\s+value="([^"]+)"', txt)
            return _ymd(m.group(1)) if m else None
    return None


def dji_name_date(path):
    m = re.match(r"DJI_(\d{4})(\d\d)(\d\d)\d{6}_", os.path.basename(path), re.I)
    if not m or not (1990 < int(m.group(1)) < 2100 and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31):
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _days(a, b):
    import datetime as dt
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


def local_date(path, m, kind, mtime_fallback=True):
    """YYYY-MM-DD of the capture, local time. m: the file's exiftool row read with EXIF_ARGS.
    mtime_fallback: without any capture date use the file's modified date (ingest needs a folder), else None."""
    if kind == "photo":
        d = _ymd(m.get("DateTimeOriginal")) or _ymd(m.get("CreateDate"))
    else:
        converted = _ymd(m.get("CreationDate")) or _ymd(m.get("DateTimeOriginal")) or _ymd(m.get("CreateDate"))
        named = dji_name_date(path)
        if named and converted and _days(named, converted) > 1:   # renamed file: trust the metadata
            named = None
        d = sony_xml_date(path) or named or converted
    if not d and mtime_fallback:
        try:
            d = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
        except OSError:
            d = None
    return d
