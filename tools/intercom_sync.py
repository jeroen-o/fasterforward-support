#!/usr/bin/env python3
"""Kennisbanken: haalt alle artikelen op uit de Intercom-helpcenters van Blinqx V&H (tools/helpcenters.json:
FinRust, Adviesbox Classic, Adviesbox Online, eBlinqx Hypotheekadvies, FinConnect en Finly).

Per artikel: titel, omschrijving, rubriek (collectie › subcollectie › ...), laatst bijgewerkt, html en platte tekst.
Afbeeldingen (Intercom-links verlopen) worden lokaal bewaard als webp in bronnen/helpcenters/<key>/img/; bijlagen in
downloads/<key>/; YouTube-, Vimeo- en Loom-video's blijven een verwijzing. Alleen nieuwe of gewijzigde artikelen
(lastUpdatedDate) worden opnieuw opgehaald. Resultaat: bronnen/helpcenters/<key>/helpcenter.json, gebruikt door build.py.
Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/intercom_sync.py [key ...]
"""
import html, io, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENTERS = json.load(open(os.path.join(ROOT, "tools", "helpcenters.json"), encoding="utf8"))
KEY = HOST = UIT = None
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
    rel = f"bronnen/helpcenters/{KEY}/img/{m.group(1)}.webp"
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
    if tp == "video" and b.get("id"):
        u = {"vimeo": "https://vimeo.com/", "loom": "https://www.loom.com/share/", "wistia": "https://fast.wistia.net/embed/iframe/"}.get(b.get("provider"))
        return f'<p><a href="{u}{html.escape(b["id"])}">Bekijk de video</a></p>' if u else ""
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
    if b.get("attachments"):
        uit = []
        for at in b["attachments"]:
            naam = re.sub(r"[^\w.\- ]", "", at.get("name", "")).strip()
            if not naam or not at.get("url"):
                continue
            rel = f"downloads/{KEY}/{naam}"
            doel = os.path.join(ROOT, rel)
            if not os.path.exists(doel):
                try:
                    os.makedirs(os.path.dirname(doel), exist_ok=True)
                    open(doel, "wb").write(haal(at["url"], binair=True))
                except Exception as e:  # noqa: BLE001
                    print("bijlage mislukt", naam, e)
                    continue
            uit.append(f'<li><a data-lokaal-bestand="{html.escape(rel)}">{html.escape(at.get("name", naam))}</a></li>')
        return f'<ul class="bijlagen">{"".join(uit)}</ul>' if uit else ""
    if b.get("text"):
        return f"<p>{b['text']}</p>"
    return ""


def collecties():
    """Alle (rubriek, artikel-samenvatting) paren, door alle collecties en subcollecties heen."""
    s = haal(f"https://{HOST}/nl/")
    top = list(dict.fromkeys(re.findall(r'href="(https://' + re.escape(HOST) + r'/nl/collections/[^"]+)"', s)))
    uit, gezien = [], set()

    def neem(rub, lijst):
        for a in lijst or []:
            if a["url"] not in gezien:
                gezien.add(a["url"])
                uit.append((rub, a))

    def loop(url, pad):
        c = props(haal(url)).get("collection") or {}
        rub = pad + [html.unescape(c.get("name", "")).strip()]
        neem(rub, c.get("articleSummaries"))
        for sub in c.get("subcollections") or []:
            if sub.get("subcollections") or len(sub.get("articleSummaries") or []) < sub.get("articleCount", 0):
                loop(sub["url"], rub)
            else:
                neem(rub + [html.unescape(sub["name"]).strip()], sub.get("articleSummaries"))
        time.sleep(0.2)
    for u in top:
        loop(u, [])
    return uit


def artikel(rub, a, volg):
    ac = props(haal(a["url"])).get("articleContent") or {}
    body = "".join(blok(b) for b in ac.get("blocks", []))
    slug = re.sub(r"^\d+-", "", a["url"].rstrip("/").rsplit("/", 1)[-1])[:90].strip("-") or a["id"]
    return {"url": a["url"], "id": a.get("id"), "slug": slug, "titel": html.unescape(ac.get("title") or a["title"]).strip(), "rubriek": rub,
            "volg": volg, "omschrijving": html.unescape(ac.get("description") or a.get("summary") or "").strip(),
            "bijgewerkt": a.get("lastUpdatedDate"), "html": body, "tekst": platte(body)[:15000]}


def center(c):
    global KEY, HOST, UIT
    KEY, HOST, UIT = c["key"], c["host"], os.path.join(ROOT, "bronnen", "helpcenters", c["key"])
    os.makedirs(UIT, exist_ok=True)
    f = os.path.join(UIT, "helpcenter.json")
    oud = {a["url"]: a for a in json.load(open(f, encoding="utf8"))} if os.path.exists(f) else {}
    lijst = collecties()
    nieuw, ophalen = [None] * len(lijst), []
    for volg, (rub, a) in enumerate(lijst):
        o = oud.get(a["url"])
        if o and o.get("bijgewerkt") == a.get("lastUpdatedDate"):
            nieuw[volg] = dict(o, rubriek=rub, volg=volg)
        else:
            ophalen.append((volg, rub, a))
    mislukt = 0

    def doe(x):
        volg, rub, a = x
        try:
            return volg, artikel(rub, a, volg)
        except Exception as e:  # noqa: BLE001
            print("mislukt", a["url"], e)
            o = oud.get(a["url"])
            return volg, (dict(o, rubriek=rub, volg=volg) if o else None)
    with ThreadPoolExecutor(3) as ex:
        for volg, art in ex.map(doe, ophalen):
            nieuw[volg] = art
            mislukt += art is None or art.get("bijgewerkt") != lijst[volg][1].get("lastUpdatedDate")
    nieuw = [a for a in nieuw if a]
    # unieke slugs binnen een helpcenter
    tel = {}
    for a in nieuw:
        tel[a["slug"]] = tel.get(a["slug"], 0) + 1
    for a in nieuw:
        if tel[a["slug"]] > 1 and a.get("id"):
            a["slug"] = f'{a["slug"]}-{a["id"]}'
    opgehaald = len(ophalen) - mislukt
    weg = len(set(oud) - {a["url"] for a in nieuw})
    if nieuw != list(oud.values()):
        json.dump(nieuw, open(f, "w", encoding="utf8"), ensure_ascii=False, indent=0)
    print(f"{c['naam']}: {len(nieuw)} artikelen, {opgehaald} opgehaald, {weg} verwijderd, {mislukt} mislukt")
    return opgehaald + weg


def main():
    keys = sys.argv[1:]
    gewijzigd = []
    for c in CENTERS:
        if keys and c["key"] not in keys:
            continue
        try:
            n = center(c)
        except Exception as e:  # noqa: BLE001
            print("helpcenter mislukt", c["host"], e)
            continue
        if n:
            gewijzigd.append(f"{c['naam']} ({n})")
    print("Gewijzigd:", ", ".join(gewijzigd) if gewijzigd else "niets")


if __name__ == "__main__":
    main()
