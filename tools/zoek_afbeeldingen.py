#!/usr/bin/env python3
"""Zoekt de nog ontbrekende afbeeldingen van de kennisbank op andere plekken op internet.

Bronnen:
  1. Wayback Machine, alle (sub)domeinen van fasterforward.nl, alle statuscodes (niet alleen de opnames
     van support.fasterforward.nl met status 200 die wayback-ophalen.py gebruikt);
  2. andere maten van dezelfde afbeelding (WordPress maakt -300x200, -1024x683 enz.);
  3. Common Crawl (de recentste indexen), die soms afbeeldingen bevat die het Internet Archive mist.
Gevonden afbeeldingen komen in bronnen/wayback/<wp-content-pad>, waar build.py ze oppikt.
Resultaat per afbeelding: tools/afbeeldingen_zoekresultaat.json.

Gebruik: python3 tools/zoek_afbeeldingen.py [--max-minuten 300]
"""
import argparse, glob, gzip, io, json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "wayback")
ap = argparse.ArgumentParser()
ap.add_argument("--max-minuten", type=float, default=300)
a = ap.parse_args()
START = time.time()


def haal(url, tries=4, timeout=120, headers=None):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (herstel eigen site)", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 403):
                return None
        except Exception:
            pass
        time.sleep(5 * (i + 1))
    return None


def tijd_op():
    return time.time() - START > a.max_minuten * 60


# 1. welke afbeeldingen ontbreken nog (de gebouwde pagina's verwijzen er dan nog naar het archief)
ontbreekt = set()
for f in glob.glob(os.path.join(ROOT, "kennisbank", "*", "index.html")):
    for u in re.findall(r'<img[^>]+src="https://web\.archive\.org/web/[^/]+/(https?://[^"]+)"', open(f, encoding="utf8", errors="ignore").read()):
        p = urllib.parse.urlparse(u).path
        if "/wp-content/uploads/" in p:
            ontbreekt.add(p)
print(len(ontbreekt), "ontbrekende afbeeldingen", flush=True)


def stam(p):
    return re.sub(r"-\d+x\d+(?=\.\w+$)", "", p).lower()


def maat(p):
    m = re.search(r"-(\d+)x(\d+)\.\w+$", p)
    return int(m.group(1)) * int(m.group(2)) if m else 10 ** 9  # origineel = grootst


# 2. alle gearchiveerde uploads van het hele domein
kandidaten = {}  # pad -> [(bron, url, timestamp)]
for q in ({"url": "fasterforward.nl", "matchType": "domain", "filter": "original:.*wp-content/uploads.*"},
          {"url": "support.fasterforward.nl/wp-content/uploads/", "matchType": "prefix"}):
    q.update({"output": "json", "fl": "timestamp,original,statuscode,mimetype", "collapse": "digest", "limit": "200000"})
    data = haal("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(q), tries=6, timeout=900)
    rijen = json.loads(data)[1:] if data else []
    print("Wayback", q["url"], len(rijen), "opnames", flush=True)
    for ts, orig, status, mime in rijen:
        if status not in ("200", "-") or not mime.startswith("image"):
            continue
        p = urllib.parse.urlparse(orig).path
        kandidaten.setdefault(p, []).append(("wayback", orig, ts))
per_stam = {}
for p in kandidaten:
    per_stam.setdefault(stam(p), []).append(p)

# 3. Common Crawl
cc = haal("https://index.commoncrawl.org/collinfo.json", timeout=120)
indexen = [c["cdx-api"] for c in json.loads(cc)][:24] if cc else []
for api in indexen:
    if tijd_op():
        break
    data = haal(api + "?" + urllib.parse.urlencode({"url": "support.fasterforward.nl/wp-content/uploads/*", "output": "json"}), tries=2, timeout=300)
    n = 0
    for regel in (data or b"").decode("utf8", "ignore").splitlines():
        try:
            r = json.loads(regel)
        except ValueError:
            continue
        if r.get("status") != "200" or not r.get("mime", "").startswith("image"):
            continue
        p = urllib.parse.urlparse(r["url"]).path
        kandidaten.setdefault(p, []).append(("commoncrawl", r, r["timestamp"]))
        per_stam.setdefault(stam(p), []).append(p)
        n += 1
    print("Common Crawl", api.rsplit("/", 1)[-1], n, flush=True)


def download(bron, ref, ts):
    if bron == "wayback":
        return haal(f"https://web.archive.org/web/{ts}id_/{ref}", tries=3)
    off, ln = int(ref["offset"]), int(ref["length"])
    raw = haal("https://data.commoncrawl.org/" + ref["filename"], tries=3, headers={"Range": f"bytes={off}-{off + ln - 1}"})
    if not raw:
        return None
    rec = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    delen = rec.split(b"\r\n\r\n", 2)  # WARC-kop, HTTP-kop, inhoud
    return delen[2] if len(delen) == 3 else None


def is_afbeelding(b):
    return b and (b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff" or b[:4] in (b"GIF8", b"RIFF"))


resultaat = {}
gevonden = 0
for p in sorted(ontbreekt):
    if tijd_op():
        print("Tijd op; volgende ronde gaat verder.", flush=True)
        break
    doel = os.path.join(UIT, p.lstrip("/"))
    if os.path.exists(doel):
        continue
    opties = list(kandidaten.get(p, []))
    # andere maat van dezelfde afbeelding, grootste eerst
    for q in sorted(set(per_stam.get(stam(p), [])) - {p}, key=maat, reverse=True):
        opties += kandidaten.get(q, [])
    for bron, ref, ts in opties:
        b = download(bron, ref, ts)
        if is_afbeelding(b):
            os.makedirs(os.path.dirname(doel), exist_ok=True)
            open(doel, "wb").write(b)
            resultaat[p] = {"bron": bron, "url": ref if bron == "wayback" else ref["url"], "tijdstip": ts}
            gevonden += 1
            print("gevonden:", p, "via", bron, flush=True)
            break
        time.sleep(0.5)
    else:
        resultaat[p] = {"bron": None, "kandidaten": len(opties)}

json.dump(resultaat, open(os.path.join(ROOT, "tools", "afbeeldingen_zoekresultaat.json"), "w"), indent=1, ensure_ascii=False)
print(f"Klaar: {gevonden} van {len(ontbreekt)} teruggevonden.", flush=True)
