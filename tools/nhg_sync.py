#!/usr/bin/env python3
"""NHG-pagina's dagelijks controleren (bronnen/nhg/pages.json): haalt elke opgenomen pagina van nhg.nl opnieuw op en
werkt titel en tekst bij als die zijn veranderd. Nieuwe berichten op nhg.nl/nhg-actueel/ komen er automatisch bij.
De tekst gaat de zoeker in (build.py); de samenvatting op sites/nhg-nl staat in tools/sites.json en wordt met de hand
bijgewerkt. Wijzigingen worden gemeld in de uitvoer ('Gewijzigd: NHG (...)'), zodat ze in de commitmelding staan.

Gebruik: python3 tools/nhg_sync.py
"""
import hashlib, html, json, os, re, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "bronnen", "nhg", "pages.json")
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}
BASIS = "https://www.nhg.nl"
MAX_TEKST = 15000


def haal(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf8", "replace")


def lees(s):
    titel = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
    titel = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", titel.group(1)))).strip() if titel else ""
    a = s.find("<main")
    m = s[a if a > 0 else 0:]
    m = re.sub(r"<(script|style|svg|noscript|nav|footer|header|template)\b.*?</\1>", " ", m, flags=re.S)
    m = re.sub(r'\sx-[\w:.-]+="[^"]*"', " ", m)  # Alpine-attributen bevatten code, geen tekst
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m))).strip()
    for begin in ("Deze pagina", "Lees voor"):
        i = t.find(begin)
        if 0 <= i < 400:
            t = t[i + len(begin):].strip()
    return titel, t[:MAX_TEKST]


def main():
    pages = json.load(open(F, encoding="utf8"))
    bekend = {p["url"] for p in pages}
    # nieuwe berichten op NHG actueel
    try:
        lijst = haal(BASIS + "/nhg-actueel/")
        for pad in dict.fromkeys(re.findall(r'href="(?:https://www\.nhg\.nl)?(/nhg-actueel/[a-z0-9-]+/)"', lijst)):
            url = BASIS + pad
            if url not in bekend:
                pages.append({"url": url, "titel": "", "tekst": ""})
                bekend.add(url)
    except Exception as e:  # noqa: BLE001
        print("NHG actueel niet bereikbaar:", e)
    gewijzigd, mislukt = [], 0
    for p in pages:
        try:
            titel, tekst = lees(haal(p["url"]))
        except Exception as e:  # noqa: BLE001
            mislukt += 1
            print("mislukt:", p["url"], e)
            continue
        if not tekst:
            continue
        h = hashlib.sha1(tekst.encode()).hexdigest()[:12]
        if h != p.get("hash"):
            if p.get("hash"):  # eerste keer alleen de vingerafdruk vastleggen
                gewijzigd.append(titel or p["url"])
            elif not p.get("tekst"):
                gewijzigd.append((titel or p["url"]) + " (nieuw)")
            p.update({"titel": titel or p.get("titel", ""), "tekst": tekst, "hash": h})
        time.sleep(0.5)
    json.dump(pages, open(F, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"NHG: {len(pages)} pagina's, {len(gewijzigd)} gewijzigd, {mislukt} mislukt")
    for g in gewijzigd:
        print("  -", g)
    print("Gewijzigd:", f"NHG ({len(gewijzigd)})" if gewijzigd else "niets")


if __name__ == "__main__":
    main()
