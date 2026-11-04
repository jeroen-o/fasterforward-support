#!/usr/bin/env python3
"""Zet een releasenote uit het helpcenter van eBlinqx Hypotheekadvies (support-fastlane.vh.blinqx.tech, Intercom)
om naar bronnen/fastlane/artikelen/<jjjj-mm-dd>.json. build.py voegt die per maand toe aan 'Releasenotes
Hypotheekadvies' voor maanden die (nog) niet op fastlane.hypotheekbond.nl staan.

Gebruik: python3 tools/fastlane_artikel.py <url> [opgeslagen-html]
(zonder opgeslagen html wordt de pagina opgehaald; tools/fastlane_sync.py doet dit automatisch voor alle releases)
"""
import html, json, os, re, sys, urllib.request

MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"]
UIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bronnen", "fastlane", "artikelen")


def haal(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf8", "replace")


def blok(b):
    t = b.get("type")
    if t == "paragraph":
        return f"<p>{b['text']}</p>" if b.get("text", "").strip() else ""
    if t == "heading":
        return f"<h3>{b['text']}</h3>"
    if t == "subheading":
        return f"<h4>{b['text']}</h4>"
    if t in ("unorderedList", "orderedList"):
        tag = "ul" if t == "unorderedList" else "ol"
        return f"<{tag}>" + "".join("<li>" + "".join(blok(c) for c in it.get("content", [])) + "</li>" for it in b.get("items", [])) + f"</{tag}>"
    if t == "table":
        rijen = []
        for i, r in enumerate(b.get("rows", [])):
            cel = "th" if i == 0 else "td"
            rijen.append("<tr>" + "".join(f"<{cel}>" + " ".join(re.sub(r"^<p>(.*)</p>$", r"\1", blok(c)) for c in x.get("content", [])) + f"</{cel}>" for x in r.get("cells", [])) + "</tr>")
        return "<table><thead>" + rijen[0] + "</thead><tbody>" + "".join(rijen[1:]) + "</tbody></table>" if rijen else ""
    if t == "image" and b.get("url"):
        return f'<p><img src="{html.escape(b["url"])}" alt=""></p>'
    return ""


def omzetten(url, pagina):
    a = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', pagina, re.S).group(1))["props"]["pageProps"]["articleContent"]
    body = "".join(blok(b) for b in a["blocks"])
    tekst = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))
    m = re.search(r"(\d{1,2}) (" + "|".join(MAANDEN) + r") (\d{4})", a["title"])
    dag, maand, jaar = int(m.group(1)), MAANDEN.index(m.group(2)) + 1, int(m.group(3))
    n = re.search(r"(\d+) wijzigingen", a.get("description", "") + " " + tekst)
    uit = {"titel": a["title"], "datum": f"{dag} {m.group(2)} {jaar}", "iso": f"{jaar}-{maand:02d}-{dag:02d}",
           "year": jaar, "month": maand, "count": int(n.group(1)) if n else None, "html": body, "src": url}
    os.makedirs(UIT, exist_ok=True)
    pad = os.path.join(UIT, uit["iso"] + ".json")
    json.dump(uit, open(pad, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    return pad, uit


if __name__ == "__main__":
    url = sys.argv[1]
    pagina = open(sys.argv[2], encoding="utf8").read() if len(sys.argv) > 2 else haal(url)
    pad, uit = omzetten(url, pagina)
    print(pad, uit["datum"], uit["count"], "wijzigingen")
