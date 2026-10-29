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
    with urllib.request.urlopen(req, timeout=30) as r:
        ctype = r.headers.get("Content-Type", "")
        data = r.read()
    if "text/html" in ctype:
        raise ValueError("geen afbeelding (html ontvangen)")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--werkers", type=int, default=6)
    ap.add_argument("--max-minuten", type=float, default=0)
    args = ap.parse_args()
    from concurrent.futures import ThreadPoolExecutor
    start = time.time()

    todo = []
    skipped = 0
    for src, waybacks in image_list().items():
        rel = local_path(src)
        if not rel:
            continue
        # afbeeldingen komen in bronnen/wayback/ (zelfde plek als tools/wayback-ophalen.py); build.py vindt ze daar
        dest = os.path.join(ROOT, "bronnen", "wayback", rel)
        if os.path.exists(dest) or os.path.exists(os.path.join(ROOT, rel)):
            skipped += 1
            continue
        todo.append((src, waybacks, dest))
    if args.max:
        todo = todo[:args.max]
    print(f"{len(todo)} op te halen, {skipped} al aanwezig", flush=True)
    ok, failed = [], []

    def one(item):
        src, waybacks, dest = item
        if args.max_minuten and time.time() - start > args.max_minuten * 60:
            return
        last = None
        for url in [w for w in waybacks if w][:1] + [f"https://web.archive.org/web/2026im_/{src}"]:
            try:
                data = fetch(url)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(data)
                ok.append(src)
                return
            except Exception as e:  # volgende bron proberen
                last = e
        failed.append((src, str(last)))
        time.sleep(0.3)  # lichte throttling, aardig voor archive.org

    with ThreadPoolExecutor(args.werkers) as ex:
        for i, _ in enumerate(ex.map(one, todo), 1):
            if i % 100 == 0:
                print(f"... {i}/{len(todo)} ({len(ok)} nieuw, {len(failed)} mislukt)", flush=True)

    print(f"\nKlaar: {len(ok)} nieuw, {skipped} al aanwezig, {len(failed)} mislukt.")
    if failed:
        with open(os.path.join(ROOT, "tools", "mislukte_afbeeldingen.txt"), "w", encoding="utf-8") as f:
            for url, err in failed:
                f.write(f"{url}\t{err}\n")
        print("Mislukte downloads staan in tools/mislukte_afbeeldingen.txt")


if __name__ == "__main__":
    main()
