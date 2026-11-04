#!/usr/bin/env python3
"""Zet een releasenote van het helpcenter van eBlinqx Hypotheekadvies (support-fastlane.vh.blinqx.tech, Intercom)
om naar bronnen/fastlane/artikelen/<jaar>-<maand>.json, dat build.py toevoegt aan 'Releasenotes Hypotheekadvies'.

Gebruik: python3 tools/fastlane_artikel.py <url> <opgeslagen-html>
"""
import html, json, os, re, sys

MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"]
url, bestand = sys.argv[1], sys.argv[2]
s = open(bestand, encoding="utf8").read()
a = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', s, re.S).group(1))["props"]["pageProps"]["articleContent"]


def blok(b):
    t = b.get("type")
    if t == "paragraph":
        return f"<p>{b['text']}</p>" if b.get("text", "").strip() else ""
    if t == "heading":
        return f"<h2>{b['text']}</h2>"
    if t == "subheading":
        return f"<h3>{b['text']}</h3>"
    if t in ("unorderedList", "orderedList"):
        tag = "ul" if t == "unorderedList" else "ol"
        return f"<{tag}>" + "".join("<li>" + "".join(blok(c) for c in it.get("content", [])) + "</li>" for it in b.get("items", [])) + f"</{tag}>"
    if t == "table":
        rijen = []
        for i, r in enumerate(b.get("rows", [])):
            cel = "th" if i == 0 else "td"
            rijen.append("<tr>" + "".join(f"<{cel}>" + " ".join(re.sub(r"^<p>(.*)</p>$", r"\1", blok(c)) for c in x.get("content", [])) + f"</{cel}>" for x in r.get("cells", [])) + "</tr>")
        return "<table><thead>" + rijen[0] + "</thead><tbody>" + "".join(rijen[1:]) + "</tbody></table>" if rijen else ""
    return ""


body = "".join(blok(b) for b in a["blocks"])
tekst = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))
m = re.search(r"(\d{1,2}) (" + "|".join(MAANDEN) + r") (\d{4})", a["title"])
maand, jaar = MAANDEN.index(m.group(2)) + 1, m.group(3)
n = re.search(r"(\d+) wijzigingen", a.get("description", "") + " " + tekst)
uit = {"label": f"{m.group(2).capitalize()} {jaar}", "titel": a["title"], "year": jaar, "month": maand,
       "count": int(n.group(1)) if n else None, "html": body, "src": url, "datum": f"{int(m.group(1))} {m.group(2)} {jaar}"}
pad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bronnen", "fastlane", "artikelen", f"{jaar}-{maand:02d}.json")
json.dump(uit, open(pad, "w", encoding="utf8"), ensure_ascii=False, indent=1)
print(pad, uit["label"], uit["count"], "wijzigingen")
