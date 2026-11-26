#!/usr/bin/env python3
"""Zoekindex van de demowebsites (pagina 'Demo-kantoor'): alle pagina's van Steen Hypotheken (via de sitemap) en, als
tools/demo_fierfinance.json bestaat, de pagina's van de demowebsite FierFinance. Resultaat: bronnen/demo/index.json,
dat build.py als externe resultaten ('Demo-kantoor') in de zoeker zet.

Gebruik: python3 tools/demo_sync.py
"""
import html, json, os, re, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "demo", "index.json")
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx; zoekindex)"}


def haal(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf8", "replace")


def tekst(h):
    h = re.sub(r"<(script|style|svg|noscript|form|nav|header|footer)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<div[^>]*cookie.*?</div>", " ", h, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def steen():
    out = []
    sm = haal("https://www.steenhypotheken.nl/sitemap.xml")
    for url in dict.fromkeys(re.findall(r"<loc>([^<]+)</loc>", sm)):
        try:
            s = haal(url)
        except Exception as e:  # noqa: BLE001
            print("mislukt:", url, e)
            continue
        titel = html.unescape((re.search(r"<title>(.*?)</title>", s, re.S) or [None, url])[1]).strip()
        titel = re.sub(r"\s*-\s*Steen Hypotheken\s*$", "", titel)
        d = re.search(r'<meta name="description" content="([^"]*)"', s)
        t = tekst(s)
        t = re.sub(r"^.*?Deze website maakt gebruik van cookies.*?Niet akkoord", "", t)
        out.append({"site": "Steen Hypotheken", "url": url, "titel": titel, "omschrijving": html.unescape(d.group(1)) if d else "",
                    "tekst": t[:12000]})
        time.sleep(0.5)
    return out


def demo_hypotheek_kantoor():
    """Alle Nederlandstalige pagina's van Demo-hypotheek-kantoor.nl (voorbeeldwebsite, fictieve gegevens)."""
    basis = "https://demo-hypotheek-kantoor.nl/"
    out = []
    start = haal(basis)
    paginas = ["index.html"] + [p for p in dict.fromkeys(re.findall(r'href="([a-z0-9-]+\.html)"', start))
                                if p not in ("index.html", "en.html", "de.html", "pl.html", "es.html", "fr.html")]
    for pad in paginas:
        url = basis if pad == "index.html" else basis + pad
        try:
            s = haal(url)
        except Exception as e:  # noqa: BLE001
            print("mislukt:", url, e)
            continue
        titel = html.unescape((re.search(r"<title>(.*?)</title>", s, re.S) or [None, url])[1]).strip()
        titel = re.sub(r"\s*[—-]\s*Demo Hypotheek kantoor(\s*\(demo\))?\s*$", "", titel)
        titel = re.sub(r"^Demo Hypotheek kantoor\s*[—-]\s*", "", titel)
        d = re.search(r'<meta name="description" content="([^"]*)"', s)
        out.append({"site": "Demo Hypotheek kantoor", "url": url, "titel": titel, "omschrijving": html.unescape(d.group(1)) if d else "",
                    "tekst": tekst(s)[:12000]})
        time.sleep(0.3)
    return out


def main():
    alle = steen()
    try:
        alle += demo_hypotheek_kantoor()
    except Exception as e:  # noqa: BLE001
        print("Demo Hypotheek kantoor mislukt:", e)
    ff = os.path.join(ROOT, "tools", "demo_fierfinance.json")
    if os.path.exists(ff):
        for x in json.load(open(ff, encoding="utf8")):
            x["tekst"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<iframe.*?</iframe>", " ", x["tekst"], flags=re.S))).strip()
            alle.append(x)
    for x in alle:  # Holland Webservices niet tonen (verzoek Jeroen, 5-11-2026)
        x["tekst"] = re.sub(r"\s*-?\s*Holland ?webservices(\.nl)?\s*-?", " ", x["tekst"], flags=re.I)
    json.dump(alle, open(UIT, "w", encoding="utf8"), ensure_ascii=False, indent=0)
    print(f"demowebsites: {len(alle)} pagina's")


if __name__ == "__main__":
    main()
