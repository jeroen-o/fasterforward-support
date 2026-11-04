#!/usr/bin/env python3
"""Controleert verzekeringhypotheek.blinqx.tech/releasenotes op nieuwe releasedocumenten van FinConnect en DIAS
Assurantie (Word of pdf) en zet ze om naar bronnen/releasenotes-overig/<dienst>-<slug>.json, met een kopie van het
document in downloads/releasenotes/. Draait dagelijks via .github/workflows/releasenotes.yml.

Gebruik: python3 tools/rn_overig_sync.py
"""
import html, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(ROOT, "bronnen", "releasenotes-overig")
DL = os.path.join(ROOT, "downloads", "releasenotes")
OVERZICHT = "https://verzekeringhypotheek.blinqx.tech/releasenotes"
DIENSTEN = {"FinConnect": "finconnect", "DIAS Assurantie": "dias"}
MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"]
e = html.escape


def haal(url, binair=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (supportsite eBlinqx)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read()
    return b if binair else b.decode("utf8", "replace")


def docx_html(pad):
    x = zipfile.ZipFile(pad).read("word/document.xml").decode("utf8")
    regels = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", x, re.S):
        t = html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))).strip()
        stijl = re.search(r'<w:pStyle w:val="([^"]+)"', p)
        if t:
            regels.append((stijl.group(1) if stijl else "", t))
    titel = next((t for s, t in regels if s.lower().startswith(("titel", "title"))), regels[0][1] if regels else "")
    rest = [t for s, t in regels if t != titel]
    if not rest:
        return titel, ""
    eerste, lijst = rest[0], rest[1:]
    body = f"<p>{e(eerste)}</p>" + ("<ul>" + "".join(f"<li>{e(t.rstrip(';'))}</li>" for t in lijst) + "</ul>" if lijst else "")
    return titel, body


def pdf_html(pad):
    t = subprocess.run(["pdftotext", pad, "-"], capture_output=True, text=True).stdout.replace("\f", "\n")
    regels = [r.rstrip() for r in t.split("\n")]
    # inhoudsopgave overslaan: begin bij de tweede keer dat de eerste genummerde kop voorkomt
    koppen = [i for i, r in enumerate(regels) if re.fullmatch(r"1\.", r.strip())]
    start = koppen[-1] if koppen else 0
    out, para, lst = [], [], []

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>" + e(" ".join(para)) + "</p>")
            para = []
        if lst:
            out.append("<ul>" + "".join("<li>" + e(x) + "</li>" for x in lst) + "</ul>")
            lst = []
    i = start
    while i < len(regels):
        r = regels[i].strip()
        if not r or re.fullmatch(r"\d{1,3}", r):
            if not r:
                flush()
            i += 1
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)*)\.", r)
        if m:
            j = i + 1
            while j < len(regels) and not regels[j].strip():
                j += 1
            flush()
            n = min(m.group(1).count(".") + 2, 4)
            out.append(f"<h{n}>{e(m.group(1))}. {e(regels[j].strip() if j < len(regels) else '')}</h{n}>")
            i = j + 1
            continue
        if r.startswith("•"):
            if para:
                out.append("<p>" + e(" ".join(para)) + "</p>")
                para = []
            lst.append(r.lstrip("• ").strip())
        elif lst and not para and not r[:1].isupper():
            lst[-1] += " " + r
        else:
            if lst:
                flush()
            para.append(r)
        i += 1
    flush()
    eerste = next((r.strip() for r in regels if r.strip()), "")
    return eerste, "".join(out)


def main():
    pagina = haal(OVERZICHT)
    bekend = set()
    for f in os.listdir(UIT) if os.path.isdir(UIT) else []:
        if f.endswith(".json"):
            bekend.add(json.load(open(os.path.join(UIT, f), encoding="utf8"))["src"])
    gewijzigd = []
    for naam, dienst in DIENSTEN.items():
        m = re.search(r">\s*" + re.escape(naam) + r"\s*<.*?href=\"([^\"]+)\"", pagina, re.S)
        if not m:
            continue
        url = html.unescape(m.group(1))
        if url in bekend or not re.search(r"\.(pdf|docx)$", url, re.I):
            continue
        bestand = os.path.basename(urllib.parse.urlparse(url).path)
        os.makedirs(DL, exist_ok=True)
        lokaal = os.path.join(DL, bestand)
        open(lokaal, "wb").write(haal(url, binair=True))
        titel, body = (docx_html if bestand.lower().endswith(".docx") else pdf_html)(lokaal)
        jaar = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
        iso = f"{jaar.group(1)}-{jaar.group(2)}-01" if jaar else "2000-01-01"
        datum = f"{MAANDEN[int(iso[5:7]) - 1]} {iso[:4]}"
        versie = re.search(r"(\d+(?:\.\d+){2,})", bestand)
        slug = versie.group(1).replace(".", "-") if versie else iso[:7]
        if dienst == "dias" and versie:
            titel = f"DIAS Assurantie / DIAS Cloud – versie {versie.group(1)}"
        uit = {"dienst": dienst, "titel": titel or os.path.splitext(bestand)[0].replace("-", " "), "datum": datum,
               "iso": iso, "slug": slug, "html": body, "bestand": f"downloads/releasenotes/{bestand}", "src": url}
        json.dump(uit, open(os.path.join(UIT, f"{dienst}-{slug}.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
        gewijzigd.append(f"{naam} {datum}")
    print("Gewijzigd:", ", ".join(gewijzigd) if gewijzigd else "niets")


if __name__ == "__main__":
    main()
