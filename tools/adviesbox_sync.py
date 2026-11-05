#!/usr/bin/env python3
"""Adviesbox: haalt de pagina's van www.adviesbox.nl op. Resultaat: bronnen/adviesbox/site.json, gebruikt door build.py
(pagina sites/adviesbox-nl en de zoeker). Het Adviesbox-helpcenter (Intercom) haalt tools/intercom_sync.py op; de functie
helpcenter() hieronder is alleen nog voor losse controles.

Gebruik: python3 tools/adviesbox_sync.py
"""
import html, json, os, re, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "adviesbox")
DL = os.path.join(ROOT, "downloads", "adviesbox")
HC = "https://support-adviesbox.vh.blinqx.tech/nl/"
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}


def haal(url, binair=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        b = r.read()
        return b if binair else (b.decode("utf8", "replace"), r.geturl())


def t(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def blok(b):
    tp = b.get("type")
    if tp == "paragraph":
        return f"<p>{b['text']}</p>" if b.get("text", "").strip() else ""
    if tp == "heading":
        return f"<h3>{b['text']}</h3>"
    if tp == "subheading":
        return f"<h4>{b['text']}</h4>"
    if tp in ("unorderedList", "orderedList", "unorderedNestedList", "orderedNestedList"):
        tag = "ol" if tp.startswith("ordered") else "ul"
        return f"<{tag}>" + "".join("<li>" + "".join(blok(c) for c in it.get("content", [])) + "</li>" for it in b.get("items", [])) + f"</{tag}>"
    return ""


def next_data(s):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', s, re.S)
    return json.loads(m.group(1))["props"]["pageProps"] if m else {}


def helpcenter():
    s, _ = haal(HC)
    collecties = list(dict.fromkeys(re.findall(r'href="(https://support-adviesbox\.vh\.blinqx\.tech/nl/collections/[^"]+)"', s)))
    artikelen, gezien = [], set()
    for c in collecties:
        cs, _ = haal(c)
        cnaam = t((re.search(r"<h1[^>]*>(.*?)</h1>", cs, re.S) or [None, c.rsplit("-", 1)[-1]])[1])
        for a in dict.fromkeys(re.findall(r'href="(https://support-adviesbox\.vh\.blinqx\.tech/nl/articles/[^"#]+)"', cs)):
            if a in gezien:
                continue
            gezien.add(a)
            try:
                asrc, _ = haal(a)
                ac = next_data(asrc).get("articleContent") or {}
            except Exception as e:  # noqa: BLE001
                print("mislukt", a, e)
                continue
            body = "".join(blok(b) for b in ac.get("blocks", []))
            bijlagen = []
            for b in ac.get("blocks", []):
                for at in b.get("attachments", []) or []:
                    naam = re.sub(r"[^\w.\- ]", "", at["name"]).strip()
                    doel = os.path.join(DL, naam)
                    if not os.path.exists(doel):
                        try:
                            open(doel, "wb").write(haal(at["url"], binair=True))
                        except Exception as e:  # noqa: BLE001
                            print("bijlage mislukt", naam, e)
                            continue
                    bijlagen.append({"naam": at["name"], "bestand": "downloads/adviesbox/" + naam})
            artikelen.append({"url": a, "titel": ac.get("title") or a, "collectie": cnaam, "omschrijving": ac.get("description", ""),
                              "html": body, "tekst": t(body)[:15000], "bijlagen": bijlagen})
            time.sleep(0.4)
        print(cnaam, len(artikelen))
    return artikelen


def site():
    paginas = ["https://www.adviesbox.nl/", "https://www.adviesbox.nl/klantdossier.aspx", "https://www.adviesbox.nl/specificaties.aspx",
               "https://www.adviesbox.nl/overstapservice.aspx", "https://www.adviesbox.nl/ondersteuning.aspx",
               "https://www.adviesbox.nl/hypotheekvergelijker", "https://www.adviesbox.nl/productkaartefficientbemiddelen",
               "https://www.adviesbox.nl/bestellen", "https://www.adviesbox.nl/proefperiode", "https://www.adviesbox.nl/contact"]
    uit = []
    for u in paginas:
        try:
            s, eind = haal(u)
        except Exception as e:  # noqa: BLE001
            print("mislukt", u, e)
            continue
        titel = t((re.search(r"<title[^>]*>(.*?)</title>", s, re.S) or [None, u])[1]).replace("Adviesbox - ", "")
        s2 = re.sub(r"<(script|style|svg|noscript|nav|header|footer|form)\b.*?</\1>", " ", s, flags=re.S | re.I)
        tekst = re.sub(r"^.*?-->\s*-->\s*-->", "", t(s2))
        tekst = re.sub(r"Afwijkende openingstijden.*?16\.30u", "", tekst)
        uit.append({"url": eind, "titel": titel, "tekst": tekst[:15000]})
        time.sleep(0.4)
    return uit


def main():
    os.makedirs(UIT, exist_ok=True)
    os.makedirs(DL, exist_ok=True)
    json.dump(site(), open(os.path.join(UIT, "site.json"), "w", encoding="utf8"), ensure_ascii=False, indent=0)
    print("Adviesbox: website bijgewerkt (het helpcenter haalt tools/intercom_sync.py op)")


if __name__ == "__main__":
    main()
