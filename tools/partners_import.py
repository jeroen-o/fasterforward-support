#!/usr/bin/env python3
"""Zet de partnerpagina's van verzekeringhypotheek.blinqx.tech/partners om naar bronnen/partners/partners.json
(+ afbeelding per partner als webp). Persoonlijke namen/e-mailadressen van Blinqx-medewerkers worden niet overgenomen.

Gebruik: python3 tools/partners_import.py <map met cards.json en det/<slug>.html>
"""
import html, io, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "partners")
BRON = "https://verzekeringhypotheek.blinqx.tech/partners/"
CONTACT = 'Meer weten over deze partner? Mail <a href="mailto:relatie-vh@blinqx.tech">relatie-vh@blinqx.tech</a>.'


def t(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip()


def inline(x):
    """Behoud alleen <strong>, <em>, <br> en externe links."""
    def a(m):
        href = html.unescape(m.group(1))
        tekst = t(m.group(2))
        if not href.startswith("http") or "blinqx.tech" in href and "/partners" not in href:
            return tekst
        return f'<a href="{html.escape(href)}" target="_blank" rel="noopener">{html.escape(tekst)}</a>'
    x = re.sub(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', a, x, flags=re.S)
    x = re.sub(r"<(?!/?(?:strong|b|em|i|br|a)\b)[^>]+>", "", x)
    x = re.sub(r"<(/?)b>", r"<\1strong>", x)
    x = re.sub(r"<(strong|em|i|b)\s[^>]*>", r"<\1>", x)
    x = re.sub(r"<(strong|em|a)\b([^>]*)>\s*</\1>", "", x)
    return re.sub(r"\s+", " ", x).strip()


TOEGESTAAN = {"Milan Akavia": "milan.akavia@blinqx.tech", "Jeroen Oversteegen": "jeroen.oversteegen@blinqx.tech",
              "Diana Blom": "diana.blom@blinqx.tech"}  # mogen genoemd worden (akkoord Jeroen, 4-11-2026)


def persoonlijk(x):
    tekst = t(x)
    for naam, mail in TOEGESTAAN.items():
        tekst = tekst.replace(naam, "").replace(mail, "")
    if re.search(r"[\w.-]+@blinqx\.tech", tekst) and "relatie-vh@" not in tekst:
        return True
    return bool(re.search(r"(contact op met|neem contact met|vraag het aan) [A-Z][a-z]+ [A-Z]", tekst))


def contactpersonen(s):
    i = s.find("Contact en samenwerking")
    if i < 0:
        return []
    j = s.find("Wil je meer weten over deze partner", i)
    seg = s[i:j if j > 0 else i + 4000]
    uit = []
    for li in re.findall(r"<li\b[^>]*>(.*?)</li>", seg, re.S):
        for naam, mail in TOEGESTAAN.items():
            if naam in t(li) and (naam, mail) not in uit:
                uit.append((naam, mail))
    return uit


def haal_img(url, doel):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"})
    from PIL import Image
    im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=90).read()))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    im.thumbnail((900, 900))
    im.save(doel, quality=85)


def main(map_):
    cards = json.load(open(os.path.join(map_, "cards.json"), encoding="utf8"))
    os.makedirs(UIT, exist_ok=True)
    uit = []
    for c in cards:
        slug = c["href"].rstrip("/").rsplit("/", 1)[1]
        s = open(os.path.join(map_, "det", slug + ".html"), encoding="utf8").read()
        m = re.search(r'<meta property="og:title" content="([^"]+)"', s) or re.search(r"<title>(.*?)</title>", s, re.S)
        titel = re.sub(r"\s*[-–|]\s*Blinqx Verzekering &(amp;)? Hypotheek\s*$", "", t(m.group(1)))
        regels = [r.strip() for r in c["txt"].split("\n") if r.strip() and not r.strip().startswith("Lees meer")]
        # kaart = tags…, titel, samenvatting
        titel, samenvatting, tags = (regels[-2], regels[-1], regels[:-2]) if len(regels) >= 2 else (titel, "", [])
        if persoonlijk(samenvatting):
            samenvatting = ""
        a = s.find('id="main-content"')
        b = min([i for i in (s.find("Contact en samenwerking", a), s.find("Wil je meer weten over deze partner", a)) if i > 0] or [len(s)])
        deel = s[a:b]
        deel = re.sub(r"<(script|style|svg|noscript|picture|form)\b.*?</\1>", " ", deel, flags=re.S)
        blokken = []
        for m in re.finditer(r"<(h1|h2|h3|h4|p|ul|ol)\b[^>]*>(.*?)</\1>", deel, re.S):
            tag, inh = m.group(1), m.group(2)
            if tag in ("ul", "ol"):
                items = [inline(li) for li in re.findall(r"<li\b[^>]*>(.*?)</li>", inh, re.S)]
                items = [i for i in items if i and not persoonlijk(i)]
                if items:
                    blokken.append(f"<{tag}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{tag}>")
                continue
            x = inline(inh)
            if not x or t(x) in ("Ga naar het verhaal", "Lees meer") or t(x).startswith("Ga naar het verhaal"):
                continue
            if persoonlijk(inh):
                if CONTACT not in blokken:
                    blokken.append(f"<p>{CONTACT}</p>")
                continue
            if tag == "h1":
                tag = "h2"
            blokken.append(f"<{tag}>{x}</{tag}>")
        # eerste alinea = samenvatting in de hero: dubbel weghalen
        if not samenvatting or samenvatting.endswith("..."):
            eerste = next((t(x) for x in blokken if x.startswith("<p>") and CONTACT not in x and len(t(x)) > 40), "")
            if eerste and (not samenvatting or eerste.startswith(samenvatting[:-3].strip()[:30])):
                samenvatting = eerste
        img = re.search(r'<meta property="og:image" content="([^"]+)"', s)
        afb = None
        if img:
            afb = slug + ".webp"
            if not os.path.exists(os.path.join(UIT, afb)):
                try:
                    haal_img(img.group(1), os.path.join(UIT, afb))
                except Exception as e:  # noqa: BLE001
                    print("afbeelding mislukt", slug, e)
                    afb = None
        uit.append({"slug": slug, "titel": titel, "tags": tags, "samenvatting": samenvatting, "html": "".join(blokken),
                    "afbeelding": afb, "bron": BRON + slug, "contact": contactpersonen(s)})
        print(slug, "|", titel, "|", tags, "|", len(blokken), "blokken")
    json.dump(uit, open(os.path.join(UIT, "partners.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
