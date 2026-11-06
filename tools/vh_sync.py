#!/usr/bin/env python3
"""Zoekindex van de eBlinqx-website (verzekeringhypotheek.blinqx.tech) bijwerken.

Leest alle sitemaps van de site, haalt nieuwe of gewijzigde pagina's op (op basis van <lastmod>) en bewaart per pagina
titel, omschrijving, soort en de platte tekst in bronnen/vh-site/index.json. build.py zet die als externe resultaten
('eBlinqx website') in de zoeker; bij klikken opent de pagina op verzekeringhypotheek.blinqx.tech.
Pagina's die niet meer in de sitemaps staan, verdwijnen uit de index. Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/vh_sync.py [--max N]
"""
import html, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "vh-site", "index.json")
BASIS = "https://verzekeringhypotheek.blinqx.tech/"
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx; zoekindex)"}
SOORT = {"post": "Blogs & nieuws", "page": "Pagina", "toolkit": "Toolkits", "training": "Academy", "blinqx-event": "Events",
         "blinqx-product": "Oplossingen", "referentie": "Klantverhalen", "kennisbank": "Kennisbank",
         "toolkits_categorie": "Toolkits", "branche": "Voor wie?", "post_branche": "Blogs & nieuws"}
MAX_TEKST = 15000


def haal(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return r.read().decode("utf8", "replace")


def tekst(h):
    h = re.sub(r"<(script|style|svg|noscript|form|nav|picture)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</(p|h\d|li|div)>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    regels = [re.sub(r"[ \t\xa0]+", " ", r).strip() for r in t.split("\n")]
    return re.sub(r"\s+", " ", " ".join(r for r in regels if r)).strip()


def meta(s, naam):
    m = re.search(r'<meta (?:property|name)="' + re.escape(naam) + r'" content="([^"]*)"', s)
    return html.unescape(m.group(1)).strip() if m else ""


def pagina(url, s):
    titel = meta(s, "og:title") or html.unescape(re.search(r"<title>(.*?)</title>", s, re.S).group(1))
    titel = re.sub(r"\s*[-–|]\s*Blinqx Verzekering &(amp;)? Hypotheek\s*$", "", titel).strip()
    a = s.find('id="main-content"')
    a = s.find(">", a) + 1 if a > 0 else 0
    b = len(s)
    for eind in ("Blijf op de hoogte!", "<footer", 'id="main-footer"'):
        i = s.find(eind, a)
        if 0 < i < b:
            b = i
    t = tekst(s[a:b])
    return {"url": url, "titel": titel, "omschrijving": meta(s, "og:description") or meta(s, "description"),
            "tekst": t[:MAX_TEKST], "datum": meta(s, "article:modified_time")[:10] or meta(s, "article:published_time")[:10],
            "gepubliceerd": meta(s, "article:published_time")[:10], "afbeelding": meta(s, "og:image"), "h1": kop(s)}


def kop(s):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""


def ontdubbel(paginas):
    """Sommige pagina's hebben op de bronsite de titel van een andere pagina (bijv. een gekopieerde toolkit). Bij dubbele
    titels de eigen h1 van de pagina gebruiken (met 'Toolkit - ' ervoor bij toolkits)."""
    from collections import Counter
    tel = Counter(p["titel"] for p in paginas)
    for p in paginas:
        if tel[p["titel"]] < 2 or p["soort"] not in ("Blogs & nieuws", "Kennisbank", "Toolkits"):
            continue
        if "h1" not in p:
            try:
                p["h1"] = kop(haal(p["url"]))
            except Exception:  # noqa: BLE001
                p["h1"] = ""
        h = p["h1"].rstrip("!").strip()
        if h and h.lower() not in p["titel"].lower():
            p["titel"] = ("Toolkit - " + h) if p["soort"] == "Toolkits" else h


def miniatuur(p):
    """Kleine afbeelding voor het nieuws- en tipsoverzicht: bronnen/vh-site/img/<slug>.webp (blogs, nieuws, kennisbank, toolkits)."""
    if not p.get("afbeelding"):
        return
    slug = re.sub(r"[^a-z0-9]+", "-", p["url"].rstrip("/").rsplit("/", 1)[-1].lower()).strip("-")[:80]
    doel = os.path.join(os.path.dirname(UIT), "img", slug + ".webp")
    p["miniatuur"] = "bronnen/vh-site/img/" + slug + ".webp"
    if os.path.exists(doel):
        return
    try:
        import io
        from PIL import Image
        with urllib.request.urlopen(urllib.request.Request(p["afbeelding"], headers=UA), timeout=60) as r:
            im = Image.open(io.BytesIO(r.read())).convert("RGB")
        im.thumbnail((640, 640))
        os.makedirs(os.path.dirname(doel), exist_ok=True)
        im.save(doel, quality=80)
    except Exception as e:  # noqa: BLE001
        print("miniatuur mislukt:", p["url"], e)
        p.pop("miniatuur", None)


def main():
    maxn = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10 ** 6
    oud = {p["url"]: p for p in json.load(open(UIT, encoding="utf8"))} if os.path.exists(UIT) else {}
    oud_lijst = json.loads(json.dumps(sorted(oud.values(), key=lambda p: p["url"])))  # ongewijzigde kopie om mee te vergelijken
    index = haal(BASIS + "sitemap_index.xml")
    gezien, nieuw, gewijzigd, mislukt = {}, [], 0, 0
    for sm in re.findall(r"<loc>([^<]+)</loc>", index):
        soort = re.sub(r"\d*-sitemap\d*\.xml$", "", sm.rsplit("/", 1)[1])
        for blok in re.findall(r"<url>(.*?)</url>", haal(sm), re.S):
            url = re.search(r"<loc>([^<]+)</loc>", blok).group(1).strip()
            lm = (re.search(r"<lastmod>([^<]+)</lastmod>", blok) or [None, ""])[1]
            if "/partners/" in url:  # partners staan als eigen pagina's op de supportsite
                continue
            gezien[url] = (soort, lm)
    for url, (soort, lm) in gezien.items():
        o = oud.get(url)
        blog = SOORT.get(soort, soort) in ("Blogs & nieuws", "Kennisbank", "Toolkits")  # nieuws en tips: datum en miniatuur
        if o and o.get("lastmod") == lm and o.get("tekst") and (not blog or "gepubliceerd" in o):
            nieuw.append(o)
            continue
        if gewijzigd >= maxn:
            if o:
                nieuw.append(o)
            continue
        try:
            s = haal(url)
            if "One moment, please" in s[:3000]:  # wachtscherm: niet omzeilen, later opnieuw
                raise RuntimeError("wachtscherm")
            p = pagina(url, s)
            p.update({"soort": SOORT.get(soort, soort), "lastmod": lm})
            if blog:
                miniatuur(p)
            nieuw.append(p)
            gewijzigd += 1
        except Exception as e:  # noqa: BLE001
            mislukt += 1
            print("mislukt:", url, e)
            if o:
                nieuw.append(o)
        time.sleep(1)
    ontdubbel(nieuw)
    weg = len(set(oud) - set(gezien))
    nieuw.sort(key=lambda p: p["url"])
    os.makedirs(os.path.dirname(UIT), exist_ok=True)
    if nieuw != oud_lijst:
        with open(UIT, "w", encoding="utf8") as fh:
            json.dump(nieuw, fh, ensure_ascii=False, indent=0)
            fh.write("\n")
    print(f"eBlinqx-website: {len(nieuw)} pagina's, {gewijzigd} opgehaald, {weg} verwijderd, {mislukt} mislukt")
    print("Gewijzigd:", f"eBlinqx-website ({gewijzigd + weg})" if gewijzigd or weg or nieuw != oud_lijst else "niets")


if __name__ == "__main__":
    main()
