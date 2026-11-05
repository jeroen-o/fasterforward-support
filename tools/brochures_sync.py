#!/usr/bin/env python3
"""Brochures 2026 (jeroen-o.github.io/blinqx-brochures): leest de lijst met brochures van de startpagina en per brochure
de titel en platte tekst (bronnen/brochures.json, voor de zoeker) en spiegelt alle brochures met stijlen, scripts en
afbeeldingen naar bronnen/brochures-site/. build.py zet die op support-eblinqx-connect.nl/brochures/.
Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/brochures_sync.py
"""
import hashlib, html, json, os, re, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "brochures.json")
BASIS = "https://jeroen-o.github.io/blinqx-brochures/"
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}


SPIEGEL = os.path.join(ROOT, "bronnen", "brochures-site")


def haal(url, binair=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        b = r.read()
        return b if binair else b.decode("utf8", "replace")


def spiegel(bestanden):
    """Download de brochures en alles wat ze lokaal gebruiken (css, js, afbeeldingen, lettertypen). Geeft het aantal
    gewijzigde bestanden terug."""
    rij, gezien, gewijzigd = ["index.html"] + list(bestanden) + ["ds-styles.css"], set(), 0
    while rij:
        rel = rij.pop(0)
        if rel in gezien:
            continue
        gezien.add(rel)
        try:
            data = haal(BASIS + urllib.parse.quote(rel), binair=True)
        except Exception as e:  # noqa: BLE001
            print("spiegel mislukt", rel, e)
            continue
        doel = os.path.join(SPIEGEL, *rel.split("/"))
        if not os.path.exists(doel) or open(doel, "rb").read() != data:
            os.makedirs(os.path.dirname(doel), exist_ok=True)
            open(doel, "wb").write(data)
            gewijzigd += 1
        if rel.endswith((".html", ".css", ".js")):
            t = data.decode("utf8", "replace")
            refs = re.findall(r'(?:src|href)="([^"#?]+)', t) + re.findall(r"url\(['\"]?([^'\")?#]+)", t) \
                + re.findall(r"['\"](assets/[^'\"?#]+)['\"]", t)
            for r in refs:
                if r.startswith(("http:", "https:", "mailto:", "tel:", "data:", "//", "javascript:")) or r.endswith("/"):
                    continue
                pad = os.path.normpath(os.path.join(os.path.dirname(rel), urllib.parse.unquote(r))).replace(os.sep, "/")
                if not pad.startswith(".."):
                    rij.append(pad)
    return gewijzigd


def tekst(s):
    s = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", s, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def main():
    oud = json.load(open(UIT, encoding="utf8")) if os.path.exists(UIT) else []
    start = haal(BASIS)
    lijst = [(f + ".html", k, t, g) for g_blok in re.findall(r"\{name:'([^']*)',items:\[(.*?)\]\}", start, re.S)
             for g, blok in [g_blok] for f, k, t in re.findall(r"\{f:'([^']+)',k:'([^']*)',t:'([^']*)'", blok)]
    if not lijst:  # oudere opzet met tabbladen
        lijst = [(f, k, t, "") for f, k, t in re.findall(r'data-file="([^"]+)"[^>]*><small>(.*?)</small><span>(.*?)</span>', start)]
    uit = []
    for f, soort, naam, groep in lijst:
        try:
            s = haal(BASIS + f)
        except Exception as e:  # noqa: BLE001
            print("mislukt", f, e)
            uit += [o for o in oud if o["bestand"] == f]
            continue
        titel = re.sub(r"\s*—\s*Blinqx Verzekering & Hypotheek$", "", tekst((re.search(r"<title>(.*?)</title>", s, re.S) or [None, naam])[1])) or html.unescape(naam)
        uit.append({"bestand": f, "url": BASIS + f, "naam": html.unescape(naam), "soort": html.unescape(soort), "groep": groep,
                    "titel": titel, "tekst": tekst(s)[:15000]})
    gew = spiegel([b["bestand"] for b in uit]) if uit else 0
    if uit and (uit != oud or gew):
        json.dump(uit, open(UIT, "w", encoding="utf8"), ensure_ascii=False, indent=0)
        print(f"Brochures: {len(uit)}")
        print(f"Gewijzigd: Brochures ({len(uit)})")
    else:
        print(f"Brochures: {len(uit)}")
        print("Gewijzigd: niets")


if __name__ == "__main__":
    main()
