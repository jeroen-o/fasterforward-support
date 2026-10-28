#!/usr/bin/env python3
"""
Download alle afbeeldingen van support.fasterforward.nl vanaf web.archive.org
naar wp-content/uploads/... in de repo (hetzelfde pad als op de oude site).

Gebaseerd op het eerdere download_afbeeldingen.py, maar leest de lijst direct uit
bronnen/inventaris.html en bronnen/afbeeldingen.html (geen CSV nodig).
Na afloop: python3 tools/build.py  -> de site gebruikt dan de lokale kopieën.

Gebruik:
    python3 tools/download_afbeeldingen.py          # alles
    python3 tools/download_afbeeldingen.py --max 50 # proefrun
"""
import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "bronnen")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ff-image-export/1.0)"}


def local_path(img_url):
    """https://support.fasterforward.nl/wp-content/uploads/2020/08/x.png -> wp-content/uploads/2020/08/x.png"""
    p = unquote(urlparse(img_url).path).lstrip("/")
    return p if p.startswith("wp-content/") else None


def image_list():
    s = open(os.path.join(SRC, "inventaris.html"), encoding="utf8").read()
    inv = json.loads(re.search(r"const DATA = (\[.*?\]);\n", s, re.S).group(1))
    seen = {}
    for d in inv:
        for im in d.get("im", []):
            if im.get("s") and im["s"] not in seen:
                seen[im["s"]] = [im.get("w")]
    s = open(os.path.join(SRC, "afbeeldingen.html"), encoding="utf8").read()
    for img in re.findall(r'\{img:"([^"]+)"', s):
        seen.setdefault(img, [])
    return seen


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as r:
        ctype = r.headers.get("Content-Type", "")
        data = r.read()
    if "text/html" in ctype:
        raise ValueError("geen afbeelding (html ontvangen)")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0)
    args = ap.parse_args()

    imgs = image_list()
    ok = skipped = 0
    failed = []
    for i, (src, waybacks) in enumerate(imgs.items()):
        if args.max and i >= args.max:
            break
        rel = local_path(src)
        if not rel:
            continue
        dest = os.path.join(ROOT, rel)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        tries = [w for w in waybacks if w] + [f"https://web.archive.org/web/2026im_/{src}", src]
        last = None
        for url in tries:
            try:
                data = fetch(url)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(data)
                ok += 1
                last = None
                break
            except Exception as e:  # volgende bron proberen
                last = e
        if last:
            failed.append((src, str(last)))
        if i % 50 == 0:
            print(f"... {i}/{len(imgs)} verwerkt ({ok} nieuw, {skipped} al aanwezig, {len(failed)} mislukt)", flush=True)
        time.sleep(0.2)  # lichte throttling, aardig voor archive.org

    print(f"\nKlaar: {ok} nieuw, {skipped} al aanwezig, {len(failed)} mislukt.")
    if failed:
        with open(os.path.join(ROOT, "tools", "mislukte_afbeeldingen.txt"), "w", encoding="utf-8") as f:
            for url, err in failed:
                f.write(f"{url}\t{err}\n")
        print("Mislukte downloads staan in tools/mislukte_afbeeldingen.txt")


if __name__ == "__main__":
    main()
