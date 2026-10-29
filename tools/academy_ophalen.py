#!/usr/bin/env python3
"""Haalt het trainingsaanbod op van de Blinqx Academy (verzekeringhypotheek.blinqx.tech/academy).

Schrijft bronnen/academy/trainingen.json en een kleine afbeelding per training (WebP).
De pagina Trainingen op de supportsite wordt hieruit opgebouwd; aanmelden gaat via de Academy zelf.

Gebruik:  python3 tools/academy_ophalen.py
"""
import html
import io
import json
import os
import re
import urllib.request
from datetime import date
from urllib.parse import urljoin

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "bronnen", "academy")
URL = "https://verzekeringhypotheek.blinqx.tech/academy"
UA = {"User-Agent": "Mozilla/5.0 (herstel supportsite)"}


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()


def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def main():
    doc = get(URL).decode("utf8", "replace")
    os.makedirs(OUT, exist_ok=True)
    out = []
    for href, body in re.findall(r"<a class='wtfy-training' href='([^']+)'>(.*?)</a>", doc, re.S):
        title = txt(re.search(r'class="wtfy-training-title">(.*?)</h3>', body, re.S).group(1))
        meta = [txt(m) for m in re.findall(r"<span class='wtfy-training-meta-entry'>(.*?)</span>", body, re.S)]
        labels = [txt(m) for m in re.findall(r'<span class="wtfy-image-label[^"]*">(.*?)</span>', body, re.S)]
        img = re.search(r'<noscript><img[^>]+src="([^"]+)"', body)
        href = href.split("#")[0]
        slug = re.sub(r"[^a-z0-9-]+", "-", href.rstrip("/").split("/")[-1].lower()).strip("-")
        fn = None
        if img:
            try:
                im = Image.open(io.BytesIO(get(urljoin(URL, img.group(1))))).convert("RGB")
                im.thumbnail((640, 640))
                fn = slug + ".webp"
                im.save(os.path.join(OUT, fn), "WEBP", quality=80)
            except Exception as e:  # zonder afbeelding verder
                print("  afbeelding mislukt:", slug, e)
        out.append({"t": title, "url": href, "meta": meta, "labels": labels, "img": fn})
    json.dump({"opgehaald": date.today().isoformat(), "bron": URL, "trainingen": out},
              open(os.path.join(OUT, "trainingen.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(len(out), "trainingen")


if __name__ == "__main__":
    main()
