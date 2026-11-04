#!/usr/bin/env python3
"""Houdt de YouTube-kanalen bij (via de openbare RSS-feed met de 15 nieuwste video's) en haalt ontbrekende miniaturen op
naar tools/assets/video/<id>.jpg:
- FinRust -> tools/finrust_videos.json (pagina video/finrust);
- Blinqx Verzekering & Hypotheek -> tools/videos.json, groep 'Nieuw op YouTube' (als de video nog nergens op de videopagina staat).
Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/yt_sync.py
"""
import html, json, os, re, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "tools", "finrust_videos.json")
THUMBS = os.path.join(ROOT, "tools", "assets", "video")
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}


def haal(url, binair=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        b = r.read()
    return b if binair else b.decode("utf8", "replace")


def main():
    d = json.load(open(F, encoding="utf8"))
    bekend = {v["id"] for v in d["videos"]}
    nieuw = []
    try:
        feed = haal("https://www.youtube.com/feeds/videos.xml?channel_id=" + d["channel_id"])
        for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
            vid = re.search(r"<yt:videoId>([^<]+)", e).group(1)
            titel = html.unescape(re.search(r"<title>([^<]*)", e).group(1))
            datum = re.search(r"<published>(\d{4}-\d{2}-\d{2})", e).group(1)
            if vid not in bekend:
                nieuw.append({"id": vid, "t": titel, "datum": datum})
            else:
                for v in d["videos"]:
                    if v["id"] == vid and not v.get("datum"):
                        v["datum"] = datum
    except Exception as ex:  # noqa: BLE001
        print("feed mislukt:", ex)
    nieuw.sort(key=lambda v: v["datum"], reverse=True)
    d["videos"] = nieuw + d["videos"]
    thumbs = 0
    for v in d["videos"]:
        doel = os.path.join(THUMBS, v["id"] + ".jpg")
        if os.path.exists(doel):
            continue
        try:
            open(doel, "wb").write(haal(f"https://i.ytimg.com/vi/{v['id']}/mqdefault.jpg", binair=True))
            thumbs += 1
            time.sleep(0.2)
        except Exception as ex:  # noqa: BLE001
            print("miniatuur mislukt:", v["id"], ex)
    json.dump(d, open(F, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"FinRust: {len(d['videos'])} video's, {len(nieuw)} nieuw, {thumbs} miniaturen opgehaald")
    nb = blinqx()
    totaal = [f"FinRust ({len(nieuw)})"] * bool(nieuw) + [f"Blinqx V&H ({nb})"] * bool(nb)
    print("Gewijzigd:", ", ".join(totaal) if totaal else "niets")


BLINQX_KANAAL = "UClDzofTmYFRwVJx8V_RDleg"


def blinqx():
    """Nieuwe video's van het kanaal Blinqx Verzekering & Hypotheek toevoegen aan tools/videos.json."""
    f = os.path.join(ROOT, "tools", "videos.json")
    groepen = json.load(open(f, encoding="utf8"))
    bekend = {v["id"] for g in groepen for v in g["videos"]}
    try:
        feed = haal("https://www.youtube.com/feeds/videos.xml?channel_id=" + BLINQX_KANAAL)
    except Exception as ex:  # noqa: BLE001
        print("feed Blinqx mislukt:", ex)
        return 0
    nieuw = []
    for e in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", e).group(1)
        if vid in bekend:
            continue
        nieuw.append({"id": vid, "t": html.unescape(re.search(r"<title>([^<]*)", e).group(1)), "d": None,
                      "ch": "Blinqx Verzekering & Hypotheek"})
        try:
            open(os.path.join(THUMBS, vid + ".jpg"), "wb").write(haal(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", binair=True))
        except Exception as ex:  # noqa: BLE001
            print("miniatuur mislukt:", vid, ex)
    if nieuw:
        g = next((g for g in groepen if g["group"] == "Nieuw op YouTube"), None)
        if not g:
            g = {"group": "Nieuw op YouTube", "videos": []}
            groepen.insert(0, g)
        g["videos"] = nieuw + g["videos"]
        json.dump(groepen, open(f, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"Blinqx V&H: {len(nieuw)} nieuwe video's")
    return len(nieuw)


if __name__ == "__main__":
    main()
