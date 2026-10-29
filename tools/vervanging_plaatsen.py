#!/usr/bin/env python3
"""Zet nieuwe schermafbeeldingen op de plek van ontbrekende originele afbeeldingen.

Gebruik: python3 tools/vervanging_plaatsen.py <map>
De map bevat per artikel een submap met de slug (bijv. startpagina/) en daarin de afbeeldingen met de
oorspronkelijke bestandsnaam (bijv. Dashboard-1-1024x520.png). Het script zoekt in de gebouwde pagina
kennisbank/<slug>/ het originele adres op en kopieert het bestand naar bronnen/vervanging/wp-content/…,
waar build.py het vóór de Wayback-versie gebruikt. Daarna: python3 tools/build.py
"""
import os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bron = sys.argv[1]
klaar, mis = 0, []
for dirpath, _, files in os.walk(bron):
    slug = os.path.basename(dirpath)
    for f in files:
        if not f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            continue
        kandidaten = [os.path.join(ROOT, "kennisbank", slug, "index.html")] + \
            [os.path.join(ROOT, d, "index.html") for d in (slug,)]
        pad = None
        for k in kandidaten:
            if os.path.exists(k):
                m = re.search(r'/(wp-content/uploads/[^"\s]*/' + re.escape(f) + r')"', open(k, encoding="utf8").read())
                if m:
                    pad = m.group(1)
                    break
        if not pad:
            mis.append(os.path.join(slug, f))
            continue
        doel = os.path.join(ROOT, "bronnen", "vervanging", pad)
        os.makedirs(os.path.dirname(doel), exist_ok=True)
        shutil.copyfile(os.path.join(dirpath, f), doel)
        klaar += 1
        print("geplaatst:", pad)
print(klaar, "geplaatst;", len(mis), "niet gevonden", mis)
