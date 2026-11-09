#!/usr/bin/env python3
"""Supportpagina van Blinqx V&H (verzekeringhypotheek.blinqx.tech/support): leest dagelijks de supportcontactgegevens
per product (e-mail, telefoon met keuzemenu) en de verwijzingen naar de supportsites per product, en controleert of die
supportsites bereikbaar zijn. Resultaat: bronnen/support-vh.json, gebruikt door build.py (wegwijzer, contactpagina en
zoeker). De Intercom-helpcenters zelf haalt tools/intercom_sync.py op.

Gebruik: python3 tools/support_sync.py
"""
import html, json, os, re, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "support-vh.json")
URL = "https://verzekeringhypotheek.blinqx.tech/support"
UA = {"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"}


def haal(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf8", "replace"), r.status


def regels(s):
    a = s.find('id="main-content"')
    b = s.find("Blijf op de hoogte", a)
    m = s[a:b if b > 0 else len(s)]
    m = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", m, flags=re.S)
    m = re.sub(r'<a[^>]*href="((?:mailto:|tel:|https?:)[^"]*)"[^>]*>', r" [[\1]] ", m)
    t = html.unescape(re.sub(r"<br\s*/?>|</(p|h\d|li|div)>", "\n", m))
    t = re.sub(r"<[^>]+>", " ", t)
    return [re.sub(r"\s+", " ", x).strip() for x in t.split("\n") if x.strip() and x.strip() != 'id="main-content">']


def bereikbaar(u):
    try:
        _, st = haal(u)
        return st < 400
    except Exception:  # noqa: BLE001
        return False


def main():
    s, _ = haal(URL)
    rl = regels(s)
    intro = [x for x in rl[:8] if "[[" not in x][:5]
    contacten, sites, i = [], [], 0
    # contactblokken: productnaam, dan regels met mailto/tel en '(toets x en y)'
    while i < len(rl):
        x = rl[i]
        if len(x) < 40 and "[[" not in x and i + 1 < len(rl) and "[[mailto:" in rl[i + 1] or len(x) < 40 and (i + 2 < len(rl) and "[[" not in x and "[[" not in rl[i + 1]
                                                                             and len(rl[i + 1]) < 30 and "[[mailto:" in rl[i + 2]):
            naam = x
            j = i + 1
            if "[[" not in rl[j]:  # tweede naamregel, bijv. '(Fastlane)'
                naam += " " + rl[j]
                j += 1
            mails, tel, toets = [], "", ""
            while j < len(rl) and ("[[" in rl[j] or rl[j].startswith("(toets")):
                r = rl[j]
                zichtbaar = re.sub(r"\[\[[^\]]*\]\]", " ", r)
                mails += [m for m in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", zichtbaar) if m not in mails]
                if "[[tel:" in r:
                    tel = re.sub(r"\s+", " ", zichtbaar).strip()
                if r.startswith("(toets"):
                    toets = r.strip("()")
                j += 1
            if mails and tel:
                contacten.append({"product": naam, "email": mails, "telefoon": tel, "keuze": toets})
            i = j
            continue
        m = re.search(r"\[\[(https?://[^\]]+)\]\]\s*(.*)", x)
        if m and i >= 2:
            naam, oms = rl[i - 2], rl[i - 1]
            sites.append({"product": naam, "omschrijving": oms, "url": m.group(1).strip(), "label": m.group(2).strip(),
                          "bereikbaar": bereikbaar(m.group(1).strip())})
        i += 1
    data = {"bron": URL, "intro": intro, "contacten": contacten, "supportsites": sites}
    oud = json.load(open(UIT, encoding="utf8")) if os.path.exists(UIT) else None
    if not contacten:
        print("Supportpagina: geen contactgegevens gevonden (opmaak gewijzigd?)")
        print("Gewijzigd: niets")
        return
    if data != oud:
        json.dump(data, open(UIT, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"Supportpagina: {len(contacten)} producten, {len(sites)} supportsites "
          f"({sum(1 for x in sites if not x['bereikbaar'])} niet bereikbaar)")
    print("Gewijzigd:", "Supportpagina V&H" if data != oud else "niets")


if __name__ == "__main__":
    main()
