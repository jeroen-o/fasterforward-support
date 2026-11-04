#!/usr/bin/env python3
"""Haalt van een lijst websites (SITES) de homepage op: titel, omschrijving, kopjes en tekst, en een afbeelding
(og:image of de eerste grote afbeelding). Resultaat: bronnen/sites/index.json + bronnen/sites/<slug>.webp.
build.py maakt er per website een pagina van (sites/<slug>/) met beschrijving en knop, en zet ze in de zoeker.

Gebruik: python3 tools/sites_import.py
"""
import html, io, json, os, re, sys, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "sites")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) supportsite eBlinqx", "Accept-Language": "nl"}
SITES = ["hypotheekbond.nl", "fasterforward.nl", "uwkluis.nl", "veiligophalen.nl", "fastlane-hypotheekadvies.nl", "dias.nl",
         "adviesbox.nl", "findata.nl", "my-tp.net", "finrust.nl", "finly.nl", "yes-co.nl", "mijnhuiszaken.nl", "hypotheekcijfer.nl",
         "pensioencijfer.nl", "duurzaamheidsprofiel.nl", "finconnect.nl", "rwwr.nl", "looptijdrente.nl",
         "hypotheekbos.nl", "schermdelen.nl", "nazorg-formulieren.nl", "beheer.mijnhuiszaken.nl", "tulpmakelaars.nl",
         "hypotheekservicegesprek.nl", "webdelen.nl"]


def haal(url, binair=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        b = r.read()
        return (b, r.geturl()) if binair else (b.decode("utf8", "replace"), r.geturl())


def t(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def meta(s, naam):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(naam) + r'["\'][^>]+content=["\']([^"\']*)', s, re.I) or \
        re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']' + re.escape(naam) + '["\']', s, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def main():
    os.makedirs(UIT, exist_ok=True)
    uit = []
    for dom in SITES:
        slug = re.sub(r"[^a-z0-9]+", "-", dom.lower()).strip("-")
        rec = {"domein": dom, "slug": slug, "url": f"https://{dom if '.' in dom.split('.')[0] or dom.count('.') > 1 else 'www.' + dom}/"}
        try:
            s, eind = haal(f"https://{dom}/")
        except Exception as e:  # noqa: BLE001
            try:
                s, eind = haal(f"https://www.{dom}/")
            except Exception as e2:  # noqa: BLE001
                rec.update({"fout": str(e2)[:120]})
                uit.append(rec)
                print("FOUT", dom, e2)
                continue
        rec["url"] = f"https://{dom}/"
        rec["eind_url"] = eind
        s2 = re.sub(r"<(script|style|svg|noscript|iframe)\b.*?</\1>", " ", s, flags=re.S | re.I)
        rec["titel"] = t((re.search(r"<title[^>]*>(.*?)</title>", s2, re.S | re.I) or [None, dom])[1])
        rec["omschrijving"] = meta(s, "og:description") or meta(s, "description")
        koppen = [t(x) for x in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", s2, re.S | re.I)]
        rec["koppen"] = [k for k in dict.fromkeys(koppen) if 3 < len(k) < 120][:12]
        alineas = [t(x) for x in re.findall(r"<p[^>]*>(.*?)</p>", s2, re.S | re.I)]
        rec["alineas"] = [a for a in dict.fromkeys(alineas) if len(a) > 60 and "cookie" not in a.lower()][:10]
        rec["tekst"] = t(re.sub(r"<(nav|header|footer)\b.*?</\1>", " ", s2, flags=re.S | re.I))[:15000]
        img = meta(s, "og:image")
        if not img:
            kand = re.findall(r'<img[^>]+(?:data-src|src)=["\']([^"\']+\.(?:jpe?g|png|webp))', s, re.I)
            kand = [k for k in kand if not re.search(r"logo|icon|favicon|sprite|pixel", k, re.I)]
            img = kand[0] if kand else ""
        if img:
            try:
                from PIL import Image
                b, _ = haal(urllib.parse.urljoin(eind, img), binair=True)
                im = Image.open(io.BytesIO(b))
                if im.width >= 300:
                    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
                    im.thumbnail((1000, 1000))
                    im.save(os.path.join(UIT, slug + ".webp"), quality=82)
                    rec["afbeelding"] = slug + ".webp"
            except Exception as e:  # noqa: BLE001
                print("afbeelding mislukt", dom, e)
        uit.append(rec)
        print(dom, "|", rec["titel"][:60], "|", len(rec["tekst"]), "|", rec.get("afbeelding", "-"), "|", eind)
    json.dump(uit, open(os.path.join(UIT, "index.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
