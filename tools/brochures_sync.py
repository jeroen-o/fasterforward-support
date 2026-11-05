#!/usr/bin/env python3
"""Brochures 2026 (jeroen-o.github.io/blinqx-brochures): leest de lijst met brochures van de startpagina en per brochure
de titel en platte tekst. Resultaat: bronnen/brochures.json, gebruikt door build.py voor de zoeker (externe resultaten).
Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/brochures_sync.py
"""
import html, json, os, re, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "brochures.json")
BASIS = "https://jeroen-o.github.io/blinqx-brochures/"
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}


def haal(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf8", "replace")


def tekst(s):
    s = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", s, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def main():
    oud = json.load(open(UIT, encoding="utf8")) if os.path.exists(UIT) else []
    start = haal(BASIS)
    uit = []
    for f, soort, naam in re.findall(r'data-file="([^"]+)"[^>]*><small>(.*?)</small><span>(.*?)</span>', start):
        try:
            s = haal(BASIS + f)
        except Exception as e:  # noqa: BLE001
            print("mislukt", f, e)
            uit += [o for o in oud if o["bestand"] == f]
            continue
        titel = re.sub(r"\s*—\s*Blinqx Verzekering & Hypotheek$", "", tekst((re.search(r"<title>(.*?)</title>", s, re.S) or [None, naam])[1])) or html.unescape(naam)
        uit.append({"bestand": f, "url": BASIS + f, "naam": html.unescape(naam), "soort": html.unescape(soort),
                    "titel": titel, "tekst": tekst(s)[:15000]})
    if uit and uit != oud:
        json.dump(uit, open(UIT, "w", encoding="utf8"), ensure_ascii=False, indent=0)
        print(f"Brochures: {len(uit)}")
        print(f"Gewijzigd: Brochures ({len(uit)})")
    else:
        print(f"Brochures: {len(uit)}")
        print("Gewijzigd: niets")


if __name__ == "__main__":
    main()
