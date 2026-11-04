#!/usr/bin/env python3
"""Controleert de releasenotes van eBlinqx Hypotheekadvies op nieuwe inhoud en werkt bronnen/fastlane/ bij.

1. fastlane.hypotheekbond.nl/hoe-het-werkt/releasenotes/: de jaarpagina's (ook een nieuw jaar) en de afbeeldingen;
2. het helpcenter (collectie Releasenotes op support-fastlane.vh.blinqx.tech): elke losse release die nog niet in
   bronnen/fastlane/artikelen/ staat.
Daarna: python3 tools/build.py. Draait dagelijks via .github/workflows/releasenotes.yml.
"""
import io, os, re, sys, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fastlane_artikel  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FL = os.path.join(ROOT, "bronnen", "fastlane")
BASIS = "https://fastlane.hypotheekbond.nl"
COLLECTIE = "https://support-fastlane.vh.blinqx.tech/nl/collections/1372893-releasenotes"
haal = fastlane_artikel.haal
gewijzigd = []

# 1. jaarpagina's
overzicht = haal(BASIS + "/hoe-het-werkt/releasenotes/")
for jaar in sorted(set(re.findall(r"/hoe-het-werkt/releasenotes/releasenotes-(\d{4})/", overzicht))):
    nieuw = haal(f"{BASIS}/hoe-het-werkt/releasenotes/releasenotes-{jaar}/")
    if '<div class="accordion">' not in nieuw:
        continue
    pad = os.path.join(FL, f"releasenotes-{jaar}.html")
    oud = open(pad, encoding="utf8", newline="").read() if os.path.exists(pad) else ""
    if nieuw != oud:
        open(pad, "w", encoding="utf8", newline="").write(nieuw)
        gewijzigd.append(f"releasenotes-{jaar}")
    for src in set(re.findall(r'<img[^>]*src="(/assets/files/[^"]+\.(?:png|jpe?g|gif|webp))"', nieuw)):
        stam = re.sub(r"\.\d+x\d+x\d+x\d+$", "", os.path.splitext(os.path.basename(src))[0])
        doel = os.path.join(FL, "img", stam + ".webp")
        if os.path.exists(doel):
            continue
        try:
            from PIL import Image
            req = urllib.request.Request(BASIS + src, headers={"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"})
            Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=90).read())).save(doel, quality=85)
            gewijzigd.append("img/" + stam)
        except Exception as e:  # noqa: BLE001
            print("afbeelding mislukt:", src, e)

# 2. helpcenter
bekend = set()
for f in os.listdir(os.path.join(FL, "artikelen")) if os.path.isdir(os.path.join(FL, "artikelen")) else []:
    if f.endswith(".json"):
        bekend.add(__import__("json").load(open(os.path.join(FL, "artikelen", f), encoding="utf8"))["src"])
for url in sorted(set(re.findall(r'href="(https://support-fastlane\.vh\.blinqx\.tech/nl/articles/[^"]+)"', haal(COLLECTIE)))):
    if url in bekend or "release" not in url:
        continue
    pad, uit = fastlane_artikel.omzetten(url, haal(url))
    gewijzigd.append(f"helpcenter {uit['datum']}")

print("Gewijzigd:", ", ".join(gewijzigd) if gewijzigd else "niets")
