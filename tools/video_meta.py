#!/usr/bin/env python3
"""Haalt per YouTube-/Vimeo-video uit tools/videos.json de beschrijving, publicatiedatum en duur op en bewaart die in
tools/video_meta.json (cache; bestaande video's worden niet opnieuw opgehaald). Gebruikt door build.py voor de
losse videopagina's (video/<slug>/). YouTube geeft via deze route soms geen beschrijving (dan via een
browser, bijv. Playwright, aanvullen). Zonder beschrijving maakt build.py een korte standaardomschrijving.
"""
import html, json, os, re, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "tools", "video_meta.json")
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)", "Accept-Language": "nl"}


def haal(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf8", "replace")


def youtube(vid):
    s = haal(f"https://www.youtube.com/watch?v={vid}&hl=nl")
    m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', s)
    beschr = json.loads('"' + m.group(1) + '"') if m else ""
    datum = (re.search(r'"(?:publishDate|uploadDate)":"(\d{4}-\d{2}-\d{2})', s) or [None, ""])[1]
    duur = int((re.search(r'"lengthSeconds":"(\d+)"', s) or [None, "0"])[1])
    return {"beschrijving": beschr, "datum": datum, "duur": duur}


def vimeo(vid):
    d = json.loads(haal(f"https://vimeo.com/api/oembed.json?url=https://vimeo.com/{vid}"))
    return {"beschrijving": d.get("description", ""), "datum": (d.get("upload_date") or "")[:10], "duur": d.get("duration", 0)}


def main():
    meta = json.load(open(F, encoding="utf8")) if os.path.exists(F) else {}
    n = 0
    for g in json.load(open(os.path.join(ROOT, "tools", "videos.json"), encoding="utf8")):
        for v in g["videos"]:
            if v["id"] in meta or v.get("mp4") or v.get("url"):
                continue
            try:
                meta[v["id"]] = vimeo(v["vimeo"]) if v.get("vimeo") else youtube(v["id"])
                n += 1
                time.sleep(1)
            except Exception as e:  # noqa: BLE001
                print("mislukt:", v["id"], e)
    json.dump(meta, open(F, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"videometa: {len(meta)} video's, {n} opgehaald")
    print("Gewijzigd:", f"videometa ({n})" if n else "niets")


if __name__ == "__main__":
    main()
