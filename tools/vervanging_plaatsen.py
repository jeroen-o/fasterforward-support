#!/usr/bin/env python3
"""Zet nieuwe schermafbeeldingen op de plek van ontbrekende originele afbeeldingen.

Gebruik: python3 tools/vervanging_plaatsen.py <map>
De map bevat per artikel een submap (de slug uit de link, of de artikeltitel als slug) met daarin de
afbeeldingen met de oorspronkelijke bestandsnaam (bijv. Dashboard-1-1024x520.png). Het script zoekt in de
gebouwde kennisbankpagina's het originele adres op en kopieert het bestand naar bronnen/vervanging/wp-content/…,
waar build.py het vóór de Wayback-versie gebruikt. Daarna: python3 tools/build.py
"""
import glob, html, os, re, shutil, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slug(t):
    t = unicodedata.normalize("NFKD", html.unescape(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


# bestandsnaam -> [(artikelslug, titelslug, wp-pad)]
index = {}
for f in glob.glob(os.path.join(ROOT, "kennisbank", "*", "index.html")):
    s = open(f, encoding="utf8").read()
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
    titel = slug(re.sub(r"<[^>]+>", "", h1.group(1))) if h1 else ""
    art = os.path.basename(os.path.dirname(f))
    for p in set(re.findall(r'/(wp-content/uploads/[^"\s]+)"', s)):
        index.setdefault(os.path.basename(p), []).append((art, titel, p))

bron = sys.argv[1]
klaar, mis = 0, []
for dirpath, _, files in os.walk(bron):
    map_ = os.path.basename(dirpath)
    for f in files:
        if not f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            continue
        kand = index.get(f, [])
        eigen = [k for k in kand if map_ in (k[0], k[1])]
        paden = {k[2] for k in (eigen or kand)}
        if len(paden) != 1:
            mis.append(f"{map_}/{f}" + (f" (meerdere mogelijkheden: {len(paden)})" if paden else ""))
            continue
        pad = paden.pop()
        doel = os.path.join(ROOT, "bronnen", "vervanging", pad)
        os.makedirs(os.path.dirname(doel), exist_ok=True)
        shutil.copyfile(os.path.join(dirpath, f), doel)
        klaar += 1
        print("geplaatst:", pad, "<-", f"{map_}/{f}")
print(klaar, "geplaatst;", len(mis), "niet geplaatst", mis)
