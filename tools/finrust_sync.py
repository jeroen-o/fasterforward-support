#!/usr/bin/env python3
"""FinRust-kennisbank: haalt alle artikelen op uit het FinRust-helpcenter (support-finrust.vh.blinqx.tech, Intercom).

Per artikel: titel, omschrijving, rubriek (collectie › subcollectie), laatst bijgewerkt, html en platte tekst.
Afbeeldingen (Intercom-links verlopen) worden lokaal bewaard als webp in bronnen/finrust/img/; YouTube-video's blijven
een verwijzing. Alleen nieuwe of gewijzigde artikelen (lastUpdatedDate) worden opnieuw opgehaald.
Resultaat: bronnen/finrust/helpcenter.json, gebruikt door build.py (pagina's finrust/ en de zoeker).
Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/finrust_sync.py
"""
import html, io, json, os, re, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "finrust")
HC = "https://support-finrust.vh.blinqx.tech/nl/"
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}


def haal(url, binair=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        b = r.read()
        return b if binair else b.decode("utf8", "replace")


def props(s):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', s, re.S)
    return json.loads(m.group(1))["props"]["pageProps"] if m else {}


def platte(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def afbeelding(url):
    m = re.search(r"/i/o/[^/]+/(\d+)/", url)
    if not m:
        return ""
    rel = f"bronnen/finrust/img/{m.group(1)}.webp"
    doel = os.path.join(ROOT, rel)
    if not os.path.exists(doel):
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(haal(url, binair=True)))
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            im.thumbnail((1400, 1400))
            os.makedirs(os.path.dirname(doel), exist_ok=True)
            im.save(doel, quality=82)
        except Exception as e:  # noqa: BLE001
            print("afbeelding mislukt", url[:90], e)
            return ""
    return rel


def blok(b):
    tp = b.get("type")
    if tp == "paragraph":
        return f"<p>{b['text']}</p>" if b.get("text", "").strip() else ""
    if tp == "heading":
        return f"<h2>{b['text']}</h2>"
    if tp == "subheading":
        return f"<h3>{b['text']}</h3>"
    if tp in ("unorderedList", "orderedList", "unorderedNestedList", "orderedNestedList"):
        tag = "ol" if tp.startswith("ordered") else "ul"
        return f"<{tag}>" + "".join("<li>" + "".join(blok(c) for c in it.get("content", [])) + "</li>" for it in b.get("items", [])) + f"</{tag}>"
    if tp == "image" and b.get("url"):
        rel = afbeelding(b["url"])
        return f'<p><img data-lokaal="{rel}" alt=""></p>' if rel else ""
    if tp == "video" and b.get("provider") == "youtube" and b.get("id"):
        return f'<div class="yt" data-yt="{html.escape(b["id"])}"></div>'
    if tp == "code":
        return f"<pre>{b.get('text', '')}</pre>"
    if tp == "callout":
        return '<div class="callout">' + "".join(blok(c) for c in b.get("content", [])) + "</div>"
    if tp == "horizontalRule":
        return "<hr>"
    if tp == "table":
        rijen = "".join("<tr>" + "".join("<td>" + "".join(blok(c) for c in cel.get("content", [])) + "</td>" for cel in r.get("cells", [])) + "</tr>"
                        for r in b.get("rows", []))
        return f'<div class="tabel"><table>{rijen}</table></div>'
    if b.get("text"):
        return f"<p>{b['text']}</p>"
    return ""


def collecties():
    """Alle (rubriek, artikel-samenvatting) paren, door de collecties en subcollecties heen."""
    s = haal(HC)
    top = list(dict.fromkeys(re.findall(r'href="(https://support-finrust\.vh\.blinqx\.tech/nl/collections/[^"]+)"', s)))
    uit, gezien = [], set()

    def loop(url, pad):
        c = props(haal(url)).get("collection") or {}
        naam = html.unescape(c.get("name", "")).strip()
        rub = pad + [naam]
        for a in c.get("articleSummaries") or []:
            if a["url"] not in gezien:
                gezien.add(a["url"])
                uit.append((rub, a))
        for sub in c.get("subcollections") or []:
            for a in sub.get("articleSummaries") or []:
                if a["url"] not in gezien:
                    gezien.add(a["url"])
                    uit.append((rub + [html.unescape(sub["name"]).strip()], a))
        time.sleep(0.3)
    for u in top:
        loop(u, [])
    return uit


def main():
    os.makedirs(UIT, exist_ok=True)
    f = os.path.join(UIT, "helpcenter.json")
    oud = {a["url"]: a for a in json.load(open(f, encoding="utf8"))} if os.path.exists(f) else {}
    nieuw, opgehaald, mislukt = [], 0, 0
    for volg, (rub, a) in enumerate(collecties()):
        o = oud.get(a["url"])
        if o and o.get("bijgewerkt") == a.get("lastUpdatedDate"):
            o["rubriek"], o["volg"] = rub, volg
            nieuw.append(o)
            continue
        try:
            ac = props(haal(a["url"])).get("articleContent") or {}
            body = "".join(blok(b) for b in ac.get("blocks", []))
        except Exception as e:  # noqa: BLE001
            print("mislukt", a["url"], e)
            mislukt += 1
            if o:
                nieuw.append(o)
            continue
        slug = re.sub(r"^\d+-", "", a["url"].rstrip("/").rsplit("/", 1)[-1])
        nieuw.append({"url": a["url"], "slug": slug, "titel": html.unescape(ac.get("title") or a["title"]), "rubriek": rub, "volg": volg,
                      "omschrijving": html.unescape(ac.get("description") or a.get("summary") or ""), "bijgewerkt": a.get("lastUpdatedDate"),
                      "html": body, "tekst": platte(body)[:15000]})
        opgehaald += 1
        time.sleep(0.4)
    weg = len(set(oud) - {a["url"] for a in nieuw})
    if nieuw != list(oud.values()):
        json.dump(nieuw, open(f, "w", encoding="utf8"), ensure_ascii=False, indent=0)
    print(f"FinRust-kennisbank: {len(nieuw)} artikelen, {opgehaald} opgehaald, {weg} verwijderd, {mislukt} mislukt")
    print("Gewijzigd:", f"FinRust-kennisbank ({opgehaald + weg})" if opgehaald or weg else "niets")


if __name__ == "__main__":
    main()
