#!/usr/bin/env python3
"""Zet nieuwe schermafbeeldingen in de kennisbank.

Gebruik: python3 tools/vervanging_plaatsen.py <map>
De map bevat per artikel een submap (de slug uit de link, of de artikeltitel als slug) met afbeeldingen.

1. Heeft een afbeelding de oorspronkelijke bestandsnaam (bijv. Dashboard-1-1024x520.png), of staat in de
   LEESMIJ.txt van de categorie bij die afbeelding welk origineel hij vervangt ("matcht exact image-24.png"),
   dan komt hij op de plek van het origineel: bronnen/vervanging/wp-content/… (build.py gebruikt die vóór
   de Wayback-versie).
2. Anders komt hij als extra actueel scherm bij het artikel: bronnen/eblinqx-artikel/<slug>/, met als
   bijschrift de omschrijving uit de LEESMIJ (_bijschriften.json). build.py toont die in het blok
   "Zo ziet het er nu uit in eBlinqx Connect".
Daarna: python3 tools/build.py
"""
import glob, html, json, os, re, shutil, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def slug(t):
    t = unicodedata.normalize("NFKD", html.unescape(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


# artikelslug -> {bestandsnaam: wp-pad}; titelslug -> artikelslug
per_art, titel_naar_art = {}, {}
for f in glob.glob(os.path.join(ROOT, "kennisbank", "*", "index.html")):
    s = open(f, encoding="utf8").read()
    art = os.path.basename(os.path.dirname(f))
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
    if h1:
        titel_naar_art[slug(re.sub(r"<[^>]+>", "", h1.group(1)))] = art
    per_art[art] = {os.path.basename(p): p for p in re.findall(r'/(wp-content/uploads/[^"\s]+)"', s)}


def leesmij_omschrijvingen(cat_map):
    """bestandsnaam -> omschrijving, uit '- naam.png: tekst' blokken in LEESMIJ*.txt."""
    uit = {}
    for lm in glob.glob(os.path.join(cat_map, "LEESMIJ*")) + glob.glob(os.path.join(cat_map, "README*")):
        tekst = open(lm, encoding="utf8", errors="ignore").read()
        for m in re.finditer(r"^- ([^\s:]+\.(?:png|jpe?g|gif|webp)):\s*(.*?)(?=^\s*- \S+\.(?:png|jpe?g|gif|webp)[:\s]|^\s*$|^=+|^[A-Z][^\n]*:\s*$|\Z)",
                             tekst, re.S | re.M | re.I):
            uit.setdefault(m.group(1), re.sub(r"\s+", " ", m.group(2)).strip())
    return uit


def originelen_in(tekst, bekend):
    """Oorspronkelijke bestandsnamen die in de omschrijving als 'match' worden genoemd."""
    namen = set()
    tekst = re.sub(r"-\s+", "-", tekst)  # bestandsnamen die over twee regels zijn afgebroken
    for m in re.finditer(r"(?:matcht?|matches|vervangt|komt overeen met)\s*(?:exact\w*|precies)?\s*", tekst, re.I):
        stuk = re.split(r"(?<!\w)\.(?:\s|$)|;|\(", tekst[m.end():m.end() + 200])[0]
        namen.update(re.findall(r"[\w\-]+\.(?:png|jpe?g|gif)", stuk, re.I))
        for nrs in re.findall(r"image-(\d+(?:/\d+)+)", stuk):
            for nr in nrs.split("/"):
                namen.update(k for k in bekend if k.startswith(f"image-{nr}."))
    return [n for n in namen if n in bekend]


def eerste_zin(t):
    t = re.sub(r"\s*[—–-]\s*(matcht|matches)\b.*", "", t, flags=re.I)
    zin = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0].strip().rstrip(".")
    if re.search(r"zoom|crop|hergebruik|hetzelfde|dezelfde", zin, re.I) or len(zin) < 8:
        return ""  # geen bruikbare omschrijving: bijschrift uit de bestandsnaam
    zin = re.sub(r"^(het|de|een)\s+", "", zin, flags=re.I)
    zin = zin[:1].upper() + zin[1:]
    return zin if len(zin) <= 200 else zin[:200].rsplit(" ", 1)[0] + " …"


bron = sys.argv[1]
geplaatst = extra = 0
mis = []
for dirpath, _, files in os.walk(bron):
    map_ = os.path.basename(dirpath)
    art = map_ if map_ in per_art else titel_naar_art.get(map_)
    beschr = leesmij_omschrijvingen(os.path.dirname(dirpath))
    for f in sorted(files):
        if not f.lower().endswith(IMG):
            continue
        src = os.path.join(dirpath, f)
        if not art:
            mis.append(f"{map_}/{f} (geen artikel met deze mapnaam)")
            continue
        bekend = per_art[art]
        doelen = [f] if f in bekend else originelen_in(beschr.get(f, ""), bekend)
        if doelen:
            for d in doelen:
                doel = os.path.join(ROOT, "bronnen", "vervanging", bekend[d])
                os.makedirs(os.path.dirname(doel), exist_ok=True)
                shutil.copyfile(src, doel)
                geplaatst += 1
                print("vervangt origineel:", bekend[d], "<-", f"{map_}/{f}")
            continue
        doelmap = os.path.join(ROOT, "bronnen", "eblinqx-artikel", art)
        os.makedirs(doelmap, exist_ok=True)
        shutil.copyfile(src, os.path.join(doelmap, f))
        bj = os.path.join(doelmap, "_bijschriften.json")
        data = json.load(open(bj, encoding="utf8")) if os.path.exists(bj) else {}
        data[f] = eerste_zin(beschr.get(f, "")) or re.sub(r"[-_]+", " ", os.path.splitext(f)[0]).capitalize()
        json.dump(data, open(bj, "w", encoding="utf8"), ensure_ascii=False, indent=1)
        extra += 1
        print("extra scherm:", f"{art}/{f}")
print(geplaatst, "originelen vervangen;", extra, "extra schermen;", len(mis), "niet geplaatst", mis)
