#!/usr/bin/env python3
"""Bouwt de reconstructie van support.fasterforward.nl uit de bronbestanden in /bronnen.

Bronnen (alle lokaal, geen netwerk nodig):
  bronnen/offline-archief/   473 pagina's (tekst + screenshot) met kruimelpad/categorie
  bronnen/volledige-tekst.html  556 pagina's met volledige tekst (JSON in #pagedata)
  bronnen/inventaris.html    801 URL's met titel, samenvatting en Wayback-link
  bronnen/afbeeldingen.html  26 afbeeldingen (via Google Afbeeldingen) met bronpagina

Uitvoer: statische site in de repo-root met dezelfde paden als het origineel
(bijv. kennisbank/matching-adn-posten/index.html), zodat oude links blijven werken.

Gebruik:  python3 tools/build.py
"""
import glob, html, json, os, re, shutil, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import htmlclean  # noqa: E402
import classify  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "bronnen")
TOOLS = os.path.join(ROOT, "tools")
BASE = "https://support.fasterforward.nl"

MONTHS = {m: i + 1 for i, m in enumerate(
    "januari februari maart april mei juni juli augustus september oktober november december".split())}

# Bovenste categorieën (tegels op de homepage) in de volgorde van het origineel.
TOP = [
    ("Basis", "list"), ("Hypotheken", "home"), ("Verzekeringen", "car"), ("Dossier", "folder"),
    ("Mijn omgeving", "desktop"), ("Communicatie", "comments"), ("E-mail", "envelope"),
    ("Boekhouding", "euro"), ("Facturatie", "file"), ("Koppelingen", "rss"),
]
# Supportkanalen per product (bron: verzekeringhypotheek.blinqx.tech/support via Adviesforum, okt 2026).
PRODUCT_SUPPORT = [
    ("eBlinqx Connect", "support-eblinqx@blinqx.tech", "1, dan 2"),
    ("eBlinqx Hypotheekadvies (Fastlane)", "support-hypotheekadvies@blinqx.tech", "1, dan 1"),
    ("Adviesbox", "support-adviesbox@blinqx.tech", "1, dan 1"),
    ("CRM (Finly)", "support-crm@blinqx.tech", "1, dan 3"),
    ("FinConnect", "support-finconnect@blinqx.tech", "1, dan 3"),
    ("Volmacht", "support-volmacht@blinqx.tech", "1, dan 6"),
]

# Webinar-replays op WebinarGeek die bij een bestaand artikel horen.
EBLINQX_SCHERMEN = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "eblinqx_schermen.json"), encoding="utf-8"))
REPLAYS = {
    "webinar-nieuwe-feature-mytp": "https://fasterforward.webinargeek.com/watch/replay/2652088/faaf06952e67e0ce558425566f97772a/",
}
# Pad waaronder de site draait (voor 404.html). GitHub Pages: /<repo>/; eigen domein: /
SITE_BASE = os.environ.get("SITE_BASE", "/")
WAYBACK_DIR = os.path.join(SRC, "wayback")      # uitvoer van tools/wayback-ophalen.py
# Dubbele artikelen: de oude versie verwijst door naar de nieuwe (oud pad -> nieuw pad)
VERVANGEN = {"kennisbank/handleiding-faster-forward-on-route": "kennisbank/handleiding-eblinqx-on-route"}
WPDB_DIR = os.path.join(SRC, "wpdb-2026-10-21")  # WordPress-databaseback-up (tools/wpdb_export.py)
HANDLEIDING_DATUM = "30 oktober 2026"  # datum waarop de handleidingteksten zijn toegevoegd
LIVE_DIR = os.path.join(SRC, "live-2026-10-20")  # pagina's van de live site, 20 oktober 2026
SKIP_PATH = re.compile(r"^(wp-content|wp-includes|wp-json|wp-admin|feed|comments|author|tag|tags|page|xmlrpc|"
                       r"search|\?|.*?/feed$|.*?/page/\d+$|.*?/amp$|.*?/embed$)")
FEEDS = {"Nieuws": "nieuws", "Tips": "tips", "Release notes": "releasenotes"}
OUTDIRS = ["tags", "tag", "releasenotes-hypotheekadvies", "elearning", "video", "kennisbank", "categorien", "category", "nieuws", "tips", "releasenotes", "zoeken",
           "contact", "trainingen", "assets"]


# ---------------------------------------------------------------- helpers

def esc(s):
    return html.escape(s or "", quote=True)


def norm(u):
    u = u.split("#")[0].split("?")[0].replace("http://", "https://").replace("://www.", "://")
    return u.rstrip("/") + "/"


def path_of(u):
    """Oorspronkelijke URL -> pad in de site ('' voor home)."""
    p = norm(u)[len(BASE):].strip("/")
    return p


def clean_title(t):
    t = html.unescape(t or "").strip()
    t = re.sub(r"\s*[-|–]\s*(Faster Forward Support|Support eBlinqx|Support|Blinqx Support)\s*\|?\s*$", "", t)
    t = re.sub(r"^\s*(Faster Forward Support|Support)\s*\|\s*", "", t)
    return t.strip(" |") or "Pagina"


def parse_date(s):
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", s or "", re.I)
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def fmt_date(d):
    if not d:
        return ""
    return f"{d.day} {list(MONTHS)[d.month - 1]} {d.year}"


FOOTER_MARKERS = ("CONTACTGEGEVENS", "SCHERM DELEN", "Copyright ©", "Was deze informatie nuttig", "Op de hoogte blijven?",
                  "AANMELDEN NIEUWSBRIEVEN", "Gerelateerd:", "Gerelateerde artikelen")
NAV_JUNK = {"HOME", "NIEUWS", "TIPS", "RELEASE NOTES", "TRAININGEN", "CONTACT SUPPORT", "Zoek naar",
            "Zoeken", "Menu", "Home", "Nieuws & Tips", "Release notes", "Trainingen", "Contact support",
            "Supportbeleid", "Opdrachtenbeleid", "Klachtenbeleid", "Wensenbeleid", "Ja", "Nee", "Lees verder"}


def clean_text(raw, title):
    """Ruwe paginatekst -> (lijst van regels/lege regels, geplaatst, bijgewerkt)."""
    t = html.unescape(raw).replace("\xa0", " ").replace("\r", "")
    t = re.sub(r"\[Let op: dit is de nieuwste door de Wayback Machine[^\]]*\]", "", t)
    if re.match(r"\s*(Title:.*?\n---\n)?\s*Niet gearchiveerd:", t, re.S):
        return [], None, None
    if t.startswith("Title:") and "\n---\n" in t[:2000]:
        t = t.split("\n---\n", 1)[1]
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in t.split("\n")]
    # Begin na de titel als die vroeg in de tekst staat (navigatie/kruimelpad ervoor weg).
    tl = title.lower()
    for i, l in enumerate(lines[:60]):
        if l.lower() == tl:
            lines = lines[i + 1:]
            break
    out = []
    for l in lines:
        if any(l.startswith(m) for m in FOOTER_MARKERS):
            break
        out.append(l)
    posted = updated = None
    body = []
    for l in out:
        m1 = re.match(r"^Geplaatst op (.+?)(?:\s*\(Laatste update:\s*(.+?)\))?$", l)
        m2 = re.match(r"^Laatste update:?\s*(.+)$", l)
        if m1:
            posted = parse_date(m1.group(1)); updated = parse_date(m1.group(2) or "")
            continue
        if m2 and len(l) < 60:
            updated = parse_date(m2.group(1))
            continue
        if l.startswith("Kennisbank >") or l in NAV_JUNK or re.match(r"^\d{3} \d{3} \d{2} \d{2}", l):
            continue
        body.append(l)
    # Lege regels samenvoegen
    res = []
    for l in body:
        if not l and (not res or not res[-1]):
            continue
        res.append(l)
    while res and not res[-1]:
        res.pop()
    while res and not res[0]:
        res.pop(0)
    return res, posted, updated


LINK_RE = re.compile(r"(https?://[^\s<>()]+[^\s<>().,;:!?'\"])|([\w.+-]+@[\w-]+\.[\w.-]*\w)")


def linkify(s):
    out, pos = [], 0
    for m in LINK_RE.finditer(s):
        out.append(esc(s[pos:m.start()]))
        if m.group(1):
            u = m.group(1)
            out.append(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(u)}</a>')
        else:
            out.append(f'<a href="mailto:{esc(m.group(2))}">{esc(m.group(2))}</a>')
        pos = m.end()
    out.append(esc(s[pos:]))
    return "".join(out)


def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "sectie"


def is_heading(block, nxt):
    if len(block) != 1:
        return False
    l = block[0]
    if len(l) > 70 or l.endswith((".", ",", ":", ";", "?", "!")) and not re.match(r"^(Stap \d+|\d+\.)", l):
        return len(l) <= 70 and l.endswith("?") and nxt is not None
    return nxt is not None and not l.startswith(("•", "-", "–"))


def text_to_html(lines):
    """Regels -> HTML met koppen, alinea's en lijsten. Geeft (html, toc) terug."""
    blocks, cur = [], []
    for l in lines:
        if not l:
            if cur:
                blocks.append(cur); cur = []
        else:
            cur.append(l)
    if cur:
        blocks.append(cur)
    parts, toc, used = [], [], set()
    for i, b in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if len(b) > 1 and len(b[0]) < 80 and re.match(r"^(\d+\.|Stap \d+)\s", b[0]):
            sid = slugify(b[0])
            while sid in used:
                sid += "-2"
            used.add(sid)
            toc.append((sid, b[0]))
            parts.append(f'<h3 id="{sid}">{esc(b[0])}</h3><p>' + "<br>".join(linkify(l) for l in b[1:]) + "</p>")
        elif is_heading(b, nxt):
            sid = slugify(b[0]); n = 2
            while sid in used:
                sid = f"{slugify(b[0])}-{n}"; n += 1
            used.add(sid)
            toc.append((sid, b[0]))
            parts.append(f'<h2 id="{sid}">{esc(b[0])}</h2>')
        elif len(b) > 1 and all(len(l) < 110 and not l.endswith((".", "?", ":")) for l in b):
            items = "".join(f"<li>{linkify(re.sub(r'^[•\-–]\s*', '', l))}</li>" for l in b)
            parts.append(f"<ul>{items}</ul>")
        elif len(b) > 1 and all(re.match(r"^[•\-–]\s", l) for l in b):
            items = "".join(f"<li>{linkify(l[2:])}</li>" for l in b)
            parts.append(f"<ul>{items}</ul>")
        else:
            parts.append("<p>" + "<br>".join(linkify(l) for l in b) + "</p>")
    # De oorspronkelijke inhoudsopgave staat soms als één aaneengeplakte regel in de tekst: weghalen.
    heads = {t.lower() for _, t in toc}

    def is_toc_list(x):
        items = [html.unescape(re.sub(r"<[^>]+>", "", i)).strip().lower() for i in re.findall(r"<li>(.*?)</li>", x)]
        return len(items) >= 3 and sum(i in heads for i in items) >= 0.6 * len(items)
    if len(toc) >= 3:
        parts = [x for x in parts if not (x.startswith("<ul>") and is_toc_list(x))]
    glued = "".join(t for _, t in toc).replace(" ", "")
    if len(toc) >= 3:
        parts = [x for x in parts if not (x.startswith("<p>") and len(x) > 20
                 and glued.startswith(html.unescape(re.sub(r"<[^>]+>", "", x)).replace(" ", "")))]
    return "\n".join(parts), toc


# ---------------------------------------------------------------- bronnen inlezen

def load_sources():
    pages = {}  # key = genormaliseerde URL

    def get(u):
        k = norm(u)
        if k not in pages:
            pages[k] = {"u": k, "path": path_of(k), "t": None, "texts": [], "crumb": None,
                        "kind": None, "shot": None, "wayback": None, "summary": "", "c": None,
                        "imgs": []}
        return pages[k]

    # 0a. Live site 20 oktober 2026 (nieuwste versie, ruwe HTML)
    lj = os.path.join(LIVE_DIR, "paginas.json")
    if os.path.exists(lj):
        for d in json.load(open(lj, encoding="utf8")):
            f = os.path.join(LIVE_DIR, d["html"])
            if os.path.exists(f):
                p = get(d["u"] if "u" in d else d["url"])
                p["raw"] = htmlclean.extract(open(f, encoding="utf8", errors="replace").read())
                p["rawsrc"] = "live"
                if d.get("categorie") == "Release":
                    p["c"] = "release"
    # 0b. Wayback Machine (ruwe HTML via tools/wayback-ophalen.py), alleen als er geen nieuwere versie is
    for f in sorted(glob.glob(os.path.join(WAYBACK_DIR, "**", "index.html"), recursive=True)):
        rel = os.path.relpath(os.path.dirname(f), WAYBACK_DIR).replace(os.sep, "/")
        rel = "" if rel in (".", "index") else rel
        if rel and SKIP_PATH.match(rel):
            continue
        try:
            doc = open(f, encoding="utf8", errors="replace").read()
        except OSError:
            continue
        if "<html" not in doc[:3000].lower() or "<title" not in doc.lower():
            continue  # geen (volledige) HTML-pagina, bijvoorbeeld een omleiding of foutmelding van het archief
        p = get(BASE + "/" + rel + ("/" if rel else ""))
        if p.get("raw"):
            continue
        p["raw"] = htmlclean.extract(doc)
        p["rawsrc"] = "wayback"
        if rel.startswith("kennisbank/"):
            p["c"] = p["c"] or "kennisbank"

    # 0c. WordPress-databaseback-up van 21 oktober 2026 (tools/wpdb_export.py): de nieuwste versie van elke
    #     gepubliceerde pagina; gaat voor de live-extract en het Internet Archive.
    dj = os.path.join(WPDB_DIR, "paginas.json")
    if os.path.exists(dj):
        for d in json.load(open(dj, encoding="utf8")):
            if not d["html"].strip():
                continue
            p = get(BASE + "/" + d["pad"] + "/")
            doc = (f'<html><head><title>{html.escape(d["titel"])}</title></head><body><div id="content">'
                   f'<h1>{html.escape(d["titel"])}</h1><div class="hkb-article__content">{d["html"]}</div>'
                   f'<div class="clear"></div></div></body></html>')
            raw = htmlclean.extract(doc)
            raw["title"] = d["titel"]
            if d["type"] == "post":
                raw["posted"] = d["geplaatst"] + (f' (Laatste update: {d["gewijzigd"]})' if d["gewijzigd"] != d["geplaatst"] else "")
            else:
                raw["posted"], raw["updated"] = "", "Laatste update: " + d["gewijzigd"]
            if d.get("afbeelding"):
                raw["ogimg"] = d["afbeelding"]
            p["raw"], p["rawsrc"] = raw, "wpdb"
            p["t"] = p["t"] or d["titel"]
            p["kind"] = p["kind"] or "Artikel"
            p["dbtitel"] = d["titel"]
            if d["type"] == "ht_kb":
                p["c"] = p["c"] or "kennisbank"
                if d["crumbs"]:
                    p["dbcrumb"] = d["crumbs"]
            elif d["categorie"]:
                p["c"] = p["c"] or d["categorie"]
            if d["uittreksel"]:
                p["summary"] = p["summary"] or d["uittreksel"]

    # 1. Offline-archief (zip): kruimelpad, type, screenshot, tekst
    for f in sorted(glob.glob(os.path.join(SRC, "offline-archief/pages/*.html"))):
        s = open(f, encoding="utf8").read()
        u = re.search(r'Oorspronkelijke URL: <a href="([^"]+)"', s).group(1)
        p = get(u)
        p["t"] = clean_title(re.search(r"<h1>(.*?)</h1>", s, re.S).group(1))
        b = re.search(r'class="badge">([^<]*)', s)
        p["kind"] = b.group(1) if b else "Artikel"
        c = re.search(r"› ([^<]*)</div>", s)
        p["crumb"] = [x.strip() for x in html.unescape(c.group(1)).split("›")] if c else None
        w = re.search(r'Wayback-capture: <a href="([^"]+)"', s)
        if w:
            p["wayback"] = w.group(1)
        sh = re.search(r'class="shot" src="\.\./shots/([^"]+)"', s)
        if sh:
            p["shot"] = sh.group(1)
        tx = re.search(r'<div class="textbox">(.*?)</div>', s, re.S)
        if tx:
            p["texts"].append(("zip", tx.group(1)))

    for p in pages.values():
        if p.get("raw") and not p["t"]:
            p["t"] = clean_title(p["raw"]["title"])

    # 2. Volledige tekst (JSON)
    s = open(os.path.join(SRC, "volledige-tekst.html"), encoding="utf8").read()
    for d in json.loads(re.search(r'id="pagedata">(.*?)</script>', s, re.S).group(1)):
        p = get(d["u"])
        p["t"] = p["t"] or clean_title(d["t"])
        p["c"] = d["c"]
        p["texts"].append(("json", html.escape(d["x"])))

    # 3. Inventaris: Wayback-link + samenvatting; pagina's zonder tekst als 'stub'
    s = open(os.path.join(SRC, "inventaris.html"), encoding="utf8").read()
    inv = json.loads(re.search(r"const DATA = (\[.*?\]);\n", s, re.S).group(1))
    for d in inv:
        k = norm(d["u"])
        if k in pages:
            pages[k]["wayback"] = pages[k]["wayback"] or d["a"]
            pages[k]["summary"] = d["s"]
            for im in d.get("im", []):
                pages[k]["imgs"].append({"src": im.get("s"), "w": im.get("w"), "alt": im.get("a", "")})
        elif d["c"] in ("artikel", "webinar", "training") and "niet gearchiveerd" not in d["s"]:
            p = get(d["u"]); p["t"] = clean_title(d["t"]); p["wayback"] = d["a"]
            p["summary"] = d["s"]; p["stub"] = True
            p["c"] = "nieuws" if d["c"] in ("webinar", "training") else "kennisbank"

    # 4. Afbeeldingen via Google
    s = open(os.path.join(SRC, "afbeeldingen.html"), encoding="utf8").read()
    for img, page in re.findall(r'\{img:"([^"]+)", page:"([^"]+)"', s):
        k = norm(page)
        if k in pages:
            if not any(im["src"] == img for im in pages[k]["imgs"]):
                pages[k]["imgs"].append({"src": img, "w": None, "alt": ""})
    # Afbeeldingen die op veel pagina's staan zijn sjabloon (logo's, iconen): niet tonen.
    freq = {}
    for p in pages.values():
        for im in {im["src"] for im in p["imgs"]}:
            freq[im] = freq.get(im, 0) + 1
    for p in pages.values():
        seen = set()
        p["imgs"] = [im for im in p["imgs"] if freq[im["src"]] <= 3 and not (im["src"] in seen or seen.add(im["src"]))
                     and re.search(r"\.(png|jpe?g|gif|webp)$", im["src"], re.I)]
    # De databaseback-up is leidend voor titel en categorie (de oudere bronnen hierboven overschrijven die anders).
    for p in pages.values():
        if p.get("dbtitel"):
            p["t"] = clean_title(p["dbtitel"])
        if p.get("dbcrumb"):
            p["crumb"] = p["dbcrumb"]
    # 5. Nieuwe en aangevulde kennisbankartikelen (klantgerichte delen uit de supporthandleidingen, bronnen/handleidingen/)
    for f in sorted(glob.glob(os.path.join(SRC, "handleidingen", "*.json"))):
        d = json.load(open(f, encoding="utf8"))
        if d.get("type") == "nieuw":
            p = get(BASE + "/kennisbank/" + d["slug"] + "/")
            if p.get("raw"):
                continue  # bestaat al: originele tekst gaat voor
            p["t"], p["kind"], p["c"] = d["titel"], "Artikel", "kennisbank"
            p["crumb"] = [c.strip() for c in d["categorie"].split(">")]
            p["summary"] = d.get("samenvatting", "")
            p["raw"] = {"title": d["titel"], "html": d["html"], "posted": "", "updated": HANDLEIDING_DATUM,
                        "hero": None, "ogimg": None, "crumbs": []}
            p["rawsrc"] = "handleiding"
        elif d.get("type") == "aanvulling":
            p = pages.get(norm(BASE + "/kennisbank/" + d["doel"] + "/"))
            if p and p.get("raw"):
                p["raw"]["html"] += f'<h2>{html.escape(d["titel"])}</h2>' + d["html"]
                p["raw"]["updated"] = HANDLEIDING_DATUM
    return pages


# ---------------------------------------------------------------- structuur bepalen

def build_structure(pages):
    cats = {name: {"name": name, "icon": icon, "subs": {}, "page": None, "loose": []} for name, icon in TOP}
    cats["Overig"] = {"name": "Overig", "icon": None, "subs": {}, "page": None, "loose": []}
    feeds = {k: [] for k in FEEDS}
    excerpts = {}

    for p in pages.values():
        p["body"], p["posted"], p["updated"], p["toc"] = "", None, None, []
        best = None
        for src, raw in p["texts"]:
            lines, posted, updated = clean_text(raw, p["t"])
            p["posted"] = p["posted"] or posted
            p["updated"] = p["updated"] or updated
            n = sum(len(l) for l in lines)
            # De zip bevat de recentste (eBlinqx-)versie; alleen de oudere JSON-tekst nemen als de zip-tekst veel korter is.
            score = n * (2.5 if src == "zip" else 1)
            if not best or score > best[0]:
                best = (score, lines)
        p["lines"] = best[1] if best else []
        raw = p.get("raw")
        if raw and len(raw["html"]) > 150:
            txt = html.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"</(p|h\d|li|tr|figcaption)>", "\n\n", raw["html"])))
            lines = [re.sub(r"\s+", " ", l).strip() for l in txt.split("\n")]
            p["lines"] = [l for i, l in enumerate(lines) if l or (i and lines[i - 1])]
            p["rawhtml"] = raw["html"]
            m = re.match(r"(?:Geplaatst op )?(.+?)(?:\s*\(Laatste update:\s*(.+?)\))?$", raw["posted"] or "")
            if m and raw["posted"]:
                p["posted"] = parse_date(m.group(1)) or p["posted"]
                p["updated"] = parse_date(m.group(2) or "") or p["updated"]
            if raw.get("updated"):
                p["updated"] = parse_date(raw["updated"]) or p["updated"]
            if not p["crumb"] and raw["crumbs"]:
                cr = [c for c in raw["crumbs"] if c.lower() not in ("home", "kennisbank", "support")]
                if cr and cr[-1].lower() == (p["t"] or "").lower():
                    cr = cr[:-1]
                if cr:
                    p["crumb"] = cr[:2]
            p.pop("stub", None)

    # Uittreksels uit (sub)categoriepagina's: 'Titel\nOmschrijving'
    for p in pages.values():
        if p["kind"] in ("Subcategoriepagina", "Categoriepagina"):
            for _, raw in p["texts"]:
                ls = [l.strip() for l in html.unescape(raw).split("\n")]
                for i, l in enumerate(ls[:-1]):
                    if l and ls[i + 1] and len(ls[i + 1]) > 40 and len(l) < 120:
                        excerpts.setdefault(l.lower(), ls[i + 1])

    title_to_crumb = {}
    for p in pages.values():
        cr = p["crumb"]
        if p["kind"] == "Artikel" and cr:
            title_to_crumb.setdefault(p["t"].lower(), cr)

    # Titels uit subcategoriepagina's koppelen aan subcategorie (voor JSON-only pagina's)
    for p in pages.values():
        if p["kind"] == "Subcategoriepagina" and p["crumb"] and len(p["crumb"]) == 2:
            for _, raw in p["texts"]:
                for l in html.unescape(raw).split("\n"):
                    title_to_crumb.setdefault(l.strip().lower(), p["crumb"])

    for p in pages.values():
        if p["path"] == "":
            p["skip"] = True
            continue
        if p["path"] in VERVANGEN:
            p["skip"] = True  # oude dubbele versie: wordt een doorverwijzing (render_redirects)
            continue
        if p["path"] in ("kennisbank", "video", "zoeken", "categorien", "category"):
            p["skip"] = True  # overzichtspagina's maken we zelf
            continue
        if "/page/" in p["u"] or p["path"].startswith(("tag/", "tags/")) or re.search(r"/(embed|feed|amp)$", p["path"]):
            p["skip"] = True
            continue
        p["excerpt"] = excerpts.get(p["t"].lower()) or (p["summary"] if p.get("stub") else "") or first_sentence(p["lines"])
        cr = p["crumb"]
        if p["kind"] == "Categoriepagina":
            name = cr[0] if cr else p["t"]
            if name in cats and name != "Overig":
                cats[name]["page"] = p; p["role"] = "cat"; p["cat"] = name
            elif name in FEEDS or p["t"] in FEEDS:
                p["role"] = "feed"; p["feed"] = name if name in FEEDS else p["t"]
            else:
                p["role"] = "article"; p["crumb"] = ["Overig"]
            continue
        if p["kind"] == "Subcategoriepagina":
            if cr and len(cr) >= 2 and cr[0] in cats:
                sub = cats[cr[0]]["subs"].setdefault(cr[1], {"name": cr[1], "page": None, "items": []})
                sub["page"] = p; p["role"] = "sub"; p["cat"] = cr[0]; p["sub"] = cr[1]
            elif cr and cr[0] in cats:
                p["role"] = "sub"; p["cat"] = cr[0]; p["sub"] = p["t"]
                sub = cats[cr[0]]["subs"].setdefault(p["t"], {"name": p["t"], "page": None, "items": []})
                sub["page"] = p
            else:
                p["skip"] = True
            continue
        if p["path"].startswith(("categorien/", "category/")):
            p["skip"] = True  # categorie-URL zonder plek in de structuur (oude Elements-indeling)
            continue
        p["role"] = "article"
        if not cr:
            cr = title_to_crumb.get(p["t"].lower())
        if not cr and p["c"] == "release":
            cr = ["Release notes"]
        if not cr:
            if p["c"] == "beleid" or p["path"] in ("contact", "trainingen", "aanspreekvorm"):
                cr = ["Overig"]
            elif p["c"] == "nieuws":
                tl = p["t"].lower()
                if re.search(r"release|update|features|verbeter|optimalisat|aanpassingen|nieuw in", tl):
                    cr = ["Release notes"]
                elif re.search(r"\btips?\b", tl):
                    cr = ["Tips"]
                else:
                    cr = ["Nieuws"]
            else:
                cr = ["Overig", "Overige kennisbankartikelen"]
        p["crumb"] = cr
        top = cr[0]
        if top in FEEDS:
            feeds[top].append(p)
        elif top in cats:
            if len(cr) >= 2:
                for subname in cr[1].split(" / "):
                    sub = cats[top]["subs"].setdefault(subname.strip(), {"name": subname.strip(), "page": None, "items": []})
                    sub["items"].append(p)
            else:
                cats[top]["loose"].append(p)
        else:
            cats["Overig"]["loose"].append(p)

    # Kennisbankartikelen zonder categorie (niet in de gearchiveerde overzichten) alsnog indelen:
    # eerst duidelijke titelregels, daarna op inhoudelijke overeenkomst (tools/classify.py).
    ov = cats["Overig"]["subs"].get("Overige kennisbankartikelen")
    if ov and ov["items"]:
        subs = {(c, sn): sub["items"] for c, cat in cats.items() if c != "Overig" for sn, sub in cat["subs"].items()}
        auto = classify.indelen(subs, ov["items"], drempel=0.15)
        blijft = []
        for p in ov["items"]:
            doel = classify.regel(p["t"])
            if not doel or doel not in subs:
                doel = auto.get(id(p), (None,))[0]
            if doel:
                p["crumb"] = list(doel)
                cats[doel[0]]["subs"][doel[1]]["items"].append(p)
            else:
                blijft.append(p)
        ov["items"] = blijft

    # Productnaam in de kennisbank: 'Elements' heet nu eBlinqx (nieuws en releasenotes blijven ongemoeid: dat is geschiedenis).
    for c, cat in cats.items():
        for sub in list(cat["subs"].values()) + [{"items": cat["loose"]}]:
            for p in sub["items"]:
                p["t"] = elements_tekst(p["t"])
                p["lines"] = [elements_tekst(l) for l in p["lines"]]
                if p.get("excerpt"):
                    p["excerpt"] = elements_tekst(p["excerpt"])
                p["summary"] = elements_tekst(p.get("summary") or "")
                for im in p["imgs"]:
                    im["alt"] = elements_tekst(im.get("alt") or "")
                if p.get("rawhtml"):
                    parts = re.split(r"(<[^>]+>)", p["rawhtml"])
                    p["rawhtml"] = "".join(x if i % 2 else elements_tekst(x) for i, x in enumerate(parts))

    # Volgorde van subcategorieën en artikelen zoals op de oorspronkelijke site.
    idx = open(os.path.join(SRC, "offline-archief/index.html"), encoding="utf8").read()
    order, cur = {}, None
    for m in re.finditer(r"<h2>([^<]*?)\s*<span|<h3>([^<]*)</h3>", idx):
        if m.group(1):
            cur = html.unescape(m.group(1)).strip(); order[cur] = []
        elif cur:
            order[cur] += [x.strip() for x in html.unescape(m.group(2)).split(" / ")]
    for name, c in cats.items():
        o = order.get(name, [])
        c["subs"] = dict(sorted(c["subs"].items(), key=lambda kv: o.index(kv[0]) if kv[0] in o else 999))
        for sub in c["subs"].values():
            lines = []
            if sub["page"]:
                for _, raw in sub["page"]["texts"]:
                    lines += [l.strip().lower() for l in html.unescape(raw).split("\n")]
            pos = {l: i for i, l in reversed(list(enumerate(lines)))}
            sub["items"].sort(key=lambda x: (pos.get(x["t"].lower(), 10**6), x["t"].lower()))
    # Uitgelichte afbeelding per bericht (zoals in de nieuwsoverzichten van de oorspronkelijke site).
    for f in feeds.values():
        for p in f:
            raw = p.get("raw") or {}
            m = re.search(r'src="IMG:([^"]+)"', p.get("rawhtml") or "")
            p["thumb"] = raw.get("ogimg") or (m.group(1) if m else None) or (p["imgs"][0]["src"] if p["imgs"] else None)
    for f in feeds.values():
        f.sort(key=lambda p: (p["posted"] or p["updated"] or wb_date(p) or date(1900, 1, 1)), reverse=True)
    return cats, feeds


def elements_tekst(t):
    """Oude productnamen in de kennisbank -> eBlinqx Connect; Faster Forward als bedrijf -> Blinqx."""
    t = re.sub(r"\b(?:Faster Forward|FFWD) Elements\b", "eBlinqx Connect", t)
    t = re.sub(r"\bFaster Forward On Route\b", "eBlinqx Connect On Route", t)
    t = re.sub(r"(?<!eBlinqx Connect )\bElements\b", "eBlinqx Connect", t)
    t = re.sub(r"\bFaster Forward\b(?! (?:Support|support))", "Blinqx", t)
    return t


def wb_date(p):
    m = re.search(r"/web/(\d{4})(\d{2})(\d{2})", p.get("wayback") or "")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def first_sentence(lines):
    for l in lines:
        if len(l) > 60:
            return (l[:220] + "…") if len(l) > 220 else l
    return ""


def img_local(u):
    p = re.sub(r"^https?://[^/]+/", "", u.split("?")[0])
    return p if p.startswith("wp-content/") else None


def wayback_img(u):
    return "https://web.archive.org/web/2026im_/" + u


# ---------------------------------------------------------------- layout

ICONS = open(os.path.join(TOOLS, "icons.svg"), encoding="utf8").read()


class Page:
    def __init__(self, path):
        self.path = path  # '' of 'kennisbank/x'
        self.depth = 0 if path == "" else path.count("/") + 1

    def rel(self, target):
        """Link naar een sitepad ('' = home) of bestand."""
        pre = "../" * self.depth
        if re.search(r"\.[a-z0-9]{2,5}$", target.rsplit("/", 1)[-1], re.I):
            return pre + target
        return pre + (target + "/" if target else "") + "index.html"


NAV = [("Home", ""), ("Nieuws", "nieuws"), ("Tips", "tips"), ("E-learning", "elearning"),
       ("Releasenotes", "releasenotes"),
       ("Trainingen", "trainingen"), ("Contact support", "contact"),
       ("eBlinqx website", "https://verzekeringhypotheek.blinqx.tech/"),
       ("Overig support", "https://verzekeringhypotheek.blinqx.tech/support"),
       ("Overig contact", "https://verzekeringhypotheek.blinqx.tech/contact")]


# Openbaar adres van de site (voor de deelknoppen als JavaScript uit staat; met JavaScript wordt het echte adres gebruikt).
SITE_URL = os.environ.get("SITE_URL", "https://support-eblinqx-connect.nl/")


def share_block(pg, title, description):
    from urllib.parse import quote
    url = page_url(pg)
    t = title or "Alles over Blinqx Verzekering & Hypotheek - Support"
    d = re.sub(r"\s+", " ", description or "").strip()
    if len(d) > 200:
        d = d[:200].rsplit(" ", 1)[0] + "…"
    msg = f"Hoi, dit is misschien handig voor je: {t}" + (f" – {d}" if d else "")
    mail = f"mailto:?subject={quote(t + ' – Blinqx Support')}&body={quote(msg + chr(10) + chr(10) + url)}"
    wa = f"https://wa.me/?text={quote(msg + ' ' + url)}"
    return (f'<section class="share" aria-label="Deel deze pagina"><div class="wrap">'
            f'<span class="share-l">Deel dit met een collega:</span>'
            f'<a class="share-b mail" href="{esc(mail)}" data-msg="{esc(msg)}" data-t="{esc(t)}"><svg class="ic"><use href="#i-mail-o"/></svg>E-mail</a>'
            f'<a class="share-b wa" href="{esc(wa)}" target="_blank" rel="noopener" data-msg="{esc(msg)}"><svg class="ic"><use href="#i-wa"/></svg>WhatsApp</a>'
            f'</div></section>'
            '<script>(function(){var u=location.href.split("#")[0].replace(/index\\.html(?=$|\\?)/,"");'
            'document.querySelectorAll(".share-b").forEach(function(a){var m=a.dataset.msg;'
            'a.href=a.classList.contains("wa")?"https://wa.me/?text="+encodeURIComponent(m+" "+u)'
            ':"mailto:?subject="+encodeURIComponent(a.dataset.t+" – Blinqx Support")+"&body="+encodeURIComponent(m+"\\n\\n"+u);});})();</script>')


SITE_DESC = ("Support voor eBlinqx (Faster Forward / Elements): kennisbank, releasenotes, e-learning en video's "
             "van Blinqx Verzekering & Hypotheek.")


def page_url(pg):
    return SITE_URL + (pg.path + "/" if pg.path and not pg.path.endswith(".html") else "")


def head_meta(pg, title, description):
    """Beschrijving, canonical en Open Graph-tags (voorbeeldkaart bij delen via WhatsApp, Teams, mail)."""
    d = re.sub(r"\s+", " ", description or "").strip() or SITE_DESC
    if len(d) > 290:
        d = d[:290].rsplit(" ", 1)[0] + "…"
    t = title or "Alles over Blinqx Verzekering & Hypotheek - Support"
    u = page_url(pg)
    img = SITE_URL + "assets/og-blinqx-vh.png"
    return "\n".join([
        f'<meta name="description" content="{esc(d)}">',
        f'<link rel="canonical" href="{esc(u)}">',
        '<meta property="og:site_name" content="Blinqx Verzekering &amp; Hypotheek - Support">',
        '<meta property="og:locale" content="nl_NL">',
        f'<meta property="og:type" content="{"website" if not pg.path else "article"}">',
        f'<meta property="og:title" content="{esc(t)}">',
        f'<meta property="og:description" content="{esc(d)}">',
        f'<meta property="og:url" content="{esc(u)}">',
        f'<meta property="og:image" content="{img}">',
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
        '<meta property="og:image:type" content="image/png">',
        '<meta property="og:image:alt" content="Blinqx Verzekering &amp; Hypotheek – Alles over Blinqx Verzekering &amp; Hypotheek - Support">',
        f'<meta name="twitter:image" content="{img}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ])


_VERSIES = {}


def asset_versie(naam):
    """Korte hash van een bestand in tools/, zodat browsers na een wijziging direct de nieuwe versie laden."""
    if naam not in _VERSIES:
        import hashlib
        f = os.path.join(TOOLS, "assets", naam) if os.path.exists(os.path.join(TOOLS, "assets", naam)) else os.path.join(TOOLS, naam)
        _VERSIES[naam] = hashlib.md5(open(f, "rb").read()).hexdigest()[:8]
    return _VERSIES[naam]


def layout(pg, title, body, active=None, description=""):
    nav = "".join(
        (f'<li class="ext"><a href="{t}" target="_blank" rel="noopener">{esc(n)}</a></li>'
         if t.startswith("http") else
         f'<li><a href="{pg.rel(t)}"{" aria-current=\"page\"" if active == t else ""}>{esc(n)}</a></li>')
        for n, t in NAV)
    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}{" - " if title else ""}Blinqx Support</title>
{head_meta(pg, title, description)}
<link rel="stylesheet" href="{pg.rel('assets/site.css')}?v={asset_versie('site.css')}">
<link rel="icon" href="{pg.rel('assets/favicon.png')}">
</head>
<body>
<a class="skip" href="#inhoud">Naar de inhoud</a>
{ICONS}
<div class="topbar">
  <div class="wrap">
    <span class="item"><svg class="ic"><use href="#i-phone"/></svg><a class="tel" href="tel:+31850180069">085 018 00 69</a></span>
    <span class="sep" aria-hidden="true"></span>
    <span class="item"><svg class="ic"><use href="#i-mail-o"/></svg><a class="mail" href="mailto:support-eblinqx@blinqx.tech">support-eblinqx@blinqx.tech</a></span>
    <a class="li" href="https://www.linkedin.com/company/blinqx/" target="_blank" rel="noopener" aria-label="Blinqx op LinkedIn">in</a>
  </div>
</div>
<header class="site">
  <div class="wrap">
    <div class="head-row">
      <a class="brand" href="{pg.rel('')}" aria-label="Blinqx support — home">
        <img src="{pg.rel('assets/logo-mark.png')}" alt="Blinqx" width="470" height="119">
        <span>powered by Faster Forward</span>
      </a>
      <nav class="main" aria-label="Hoofdmenu"><ul>{nav}</ul></nav>
    </div>
    <div class="search-row">
      <form class="search" action="{pg.rel('zoeken')}" method="get" role="search">
        <label class="field">
          <svg class="ic"><use href="#i-search"/></svg>
          <input type="search" name="q" placeholder="Zoek hier op onderwerp" aria-label="Zoek op onderwerp">
        </label>
        <button type="submit">Zoeken</button>
      </form>
      <div class="status">Mogelijke incidenten en de systeemstatus vind je op onze <a href="https://status.fasterforward.nl/" target="_blank" rel="noopener">statuspagina</a>.</div>
    </div>
  </div>
</header>
<div id="inhoud" tabindex="-1"></div>
{body}
{share_block(pg, title, description)}
<footer>
  <div class="wrap">
    <span>Copyright © 2024 Blinqx powered by Faster Forward</span>
    <nav aria-label="Beleid">
      <a href="{pg.rel('supportbeleid')}">Supportbeleid</a>
      <a href="{pg.rel('opdrachtenbeleid')}">Opdrachtenbeleid</a>
      <a href="{pg.rel('klachtenbeleid')}">Klachtenbeleid</a>
      <a href="{pg.rel('wensenbeleid')}">Wensenbeleid</a>
      <a href="{pg.rel('video')}">Video's</a>
      <a href="{pg.rel('downloads')}">Downloads</a>
      <a href="{pg.rel('nieuwsbrief')}">Nieuwsbrief</a>
      <a href="{pg.rel('privacy')}">Privacy</a>
      <a href="{pg.rel('demo-kantoor')}">Demo-kantoor</a>
      <a href="{pg.rel('sites')}">Handige websites</a>
      <a href="https://verzekeringhypotheek.blinqx.tech/" target="_blank" rel="noopener">eBlinqx website</a>
    </nav>
  </div>
</footer>
<script src="{pg.rel('assets/site.js')}?v={asset_versie('site.js')}" defer></script>
</body>
</html>
"""


def crumbs(pg, items):
    """items: lijst (label, pad of None)."""
    parts = []
    for i, (label, target) in enumerate(items):
        if target is not None and i < len(items) - 1:
            parts.append(f'<a href="{pg.rel(target)}">{esc(label)}</a>')
        else:
            parts.append(f'<span aria-current="page">{esc(label)}</span>')
    sep = '<span class="sep" aria-hidden="true">›</span>'
    return f'<div class="crumbs"><div class="wrap"><nav aria-label="Kruimelpad">{sep.join(parts)}</nav></div></div>'


def hero_url(url, title):
    return (f'<div class="hero" style="background-image:url(\'{esc(url)}\')">'
            f'<div class="wrap"><h1>{esc(title)}</h1></div></div>')


PAGES_BY_PATH = {}


def resolve_img(pg, url):
    url = htmlclean.unwrap_wayback(url)
    if url.startswith("/"):
        url = BASE + url
    rel = img_local(url)
    if rel:
        # eigen vervangende schermafbeeldingen (tools/vervanging_plaatsen.py) gaan voor de archiefversie
        for cand in ("bronnen/vervanging/" + rel, rel, "bronnen/wayback/" + rel):
            if os.path.exists(os.path.join(ROOT, cand)):
                return pg.rel(cand)
    return wayback_img(url)


def resolve_site(pg, path):
    path, _, frag = path.partition("#")
    key = path.split("?")[0].strip("/")
    p = PAGES_BY_PATH.get(key)
    if key == "":
        return pg.rel("") + (("#" + frag) if frag else "")
    if p:
        return pg.rel(p["path"]) + (("#" + frag) if frag else "")
    return "https://web.archive.org/web/2026/" + BASE + "/" + key + "/"


def raw_to_html(pg, h):
    h = re.sub(r'<img[^>]*src="IMG:"[^>]*>', "", h)  # afbeelding zonder bron
    h = re.sub(r'href="IMG:"', 'href="#"', h)
    h = re.sub(r'(href|src)="IMG:([^"]+)"', lambda m: f'{m.group(1)}="{esc(resolve_img(pg, html.unescape(m.group(2))))}"', h)
    h = re.sub(r'href="SITE:([^"]*)"', lambda m: f'href="{esc(resolve_site(pg, html.unescape(m.group(1))))}"', h)
    # Afbeeldingen die niet meer bestaan (niet lokaal, alleen nog een archiefadres): weglaten in plaats van een leeg vak
    h = re.sub(r'<a href="https://web\.archive\.org/[^"]*"[^>]*>(.*?)</a>', r"\1", h, flags=re.S)
    # (data-origineel bewaart het oude adres, zodat tools/vervanging_plaatsen.py een nieuw scherm kan koppelen)
    h = re.sub(r'<img[^>]*src="https://web\.archive\.org/web/[^/]+/([^"]*)"[^>]*>',
               lambda m: f'<span class="img-volgt" role="img" aria-label="Afbeelding volgt" data-origineel="{m.group(1)}">Afbeelding volgt</span>', h)
    for _ in range(2):
        h = re.sub(r"<(figure|p|figcaption)>\s*(<br>\s*)*</\1>", "", h)
    toc, used = [], set()

    def add_id(m):
        tag, attrs, inner = m.group(1), m.group(2) or "", m.group(3)
        text = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        idm = re.search(r'id="([^"]+)"', attrs)
        sid = idm.group(1) if idm else slugify(text)
        while sid in used:
            sid += "-2"
        used.add(sid)
        if tag == "h2" and text:
            toc.append((sid, text))
        return f'<{tag} id="{sid}">{inner}</{tag}>'
    h = re.sub(r"<(h[23])((?:\s[^>]*)?)>(.*?)</\1>", add_id, h, flags=re.S)
    return h, toc


def hero(pg, title, img):
    return (f'<div class="hero" style="background-image:url(\'{pg.rel("assets/" + img)}\')">'
            f'<div class="wrap"><h1>{esc(title)}</h1></div></div>')


# Productnaam: overal beide namen tonen ("UwKluis / Online klantportaal"). Alleen in zichtbare tekst,
# niet in links of bestandsnamen; samenstellingen (Uwkluis-koppeling) blijven ongemoeid.
KLUIS = "UwKluis / Online klantportaal"
KLUIS_RE = re.compile(r"(?<![\w/.-])[Uu]w\s?[Kk]luis(?![\w-])(?!\s*/\s*Online klantportaal)")


# Verouderde contactgegevens van Faster Forward -> huidige gegevens van Blinqx support (eBlinqx Connect).
OUD_CONTACT = [
    # alle oude adressen (support@, opdrachten@, sales@ …) -> support van eBlinqx
    (re.compile(r"[\w.+-]+@fasterforward\.nl", re.I), "support-eblinqx@blinqx.tech"),
    (re.compile(r"0164[\s-]?271[\s-]?281"), "085 018 00 69"),
]


def kluis_tekst(t):
    for pat, nieuw in OUD_CONTACT:
        t = pat.sub(nieuw, t)
    return KLUIS_RE.sub(KLUIS, t)


def kluis_html(doc):
    parts = re.split(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", doc, flags=re.S | re.I)
    for i in range(0, len(parts), 2):
        parts[i] = kluis_tekst(parts[i])
    # ook in de deeltekst (data-msg) en de beschrijving van de pagina
    out = "".join(parts)
    out = re.sub(r'((?:data-msg|data-t|content)=")([^"]*)"', lambda m: m.group(1) + kluis_tekst(m.group(2)) + '"', out)
    for pat, nieuw in OUD_CONTACT:  # ook in mailto:/tel:-links
        out = re.sub(r'(href="(?:mailto|tel):)([^"]*)"', lambda m: m.group(1) + pat.sub(nieuw, m.group(2)) + '"', out)
    return out


def write(path, content, kluis=True):
    full = os.path.join(ROOT, path) if path.endswith((".html", ".xml")) else os.path.join(ROOT, path, "index.html")
    if full.endswith(".html") and kluis:
        content = kluis_html(content)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf8") as fh:
        fh.write(content)


# ---------------------------------------------------------------- pagina's

def cat_target(cats, name):
    c = cats.get(name)
    if c and c["page"]:
        return c["page"]["path"]
    return "kennisbank/" + slugify(name)


def sub_target(cats, catname, sub):
    if sub["page"]:
        return sub["page"]["path"]
    return cat_target(cats, catname) + "/" + slugify(sub["name"])


def crumb_items(cats, p):
    cr = p["crumb"] or []
    items = []
    if cr and cr[0] in FEEDS:
        items.append((FEED_LABEL.get(cr[0], cr[0]), FEEDS[cr[0]]))
    elif cr and cr[0] in cats:
        items.append(("Kennisbank", "kennisbank"))
        items.append((cr[0], cat_target(cats, cr[0])))
        if len(cr) > 1:
            subname = cr[1].split(" / ")[0].strip()
            sub = cats[cr[0]]["subs"].get(subname)
            if sub:
                items.append((subname, sub_target(cats, cr[0], sub)))
    items.append((p["t"], None))
    return items


def related(cats, feeds, p):
    cr = p["crumb"] or []
    pool = []
    if cr and cr[0] in FEEDS:
        pool = feeds[cr[0]]
    elif cr and cr[0] in cats and len(cr) > 1:
        sub = cats[cr[0]]["subs"].get(cr[1].split(" / ")[0].strip())
        pool = sub["items"] if sub else []
    elif cr and cr[0] in cats:
        pool = cats[cr[0]]["loose"]
    out = [x for x in pool if x is not p]
    if cr and cr[0] in FEEDS:
        i = pool.index(p) if p in pool else 0
        out = [x for x in pool[max(0, i - 3):i + 4] if x is not p]
    return out[:6]


VEROUDERD_VOOR = date(2023, 1, 1)
MAANDEN = list(MONTHS)


def verouderd(p):
    """(datumtekst) als dit een kennisbankartikel is dat vóór 2023 voor het laatst is bijgewerkt, anders None."""
    cr = p["crumb"] or []
    if not cr or cr[0] not in dict(TOP):
        return None
    d = p["updated"] or p["posted"]
    if d:
        return "op " + fmt_date(d) if d < VEROUDERD_VOOR else None
    w = wb_date(p)
    if w and w < VEROUDERD_VOOR and p.get("rawsrc") != "live":
        return f"in {MAANDEN[w.month - 1]} {w.year}"
    return None


def render_article(cats, feeds, p):
    pg = Page(p["path"])
    oud = verouderd(p)
    if p.get("rawhtml"):
        body_html, toc = raw_to_html(pg, p["rawhtml"])
    else:
        body_html, toc = text_to_html(p["lines"])
    p["toc"] = toc
    meta = []
    if p["posted"]:
        meta.append("Geplaatst op " + fmt_date(p["posted"]))
    if p["updated"]:
        meta.append("Laatste update: " + fmt_date(p["updated"]))
    toc_html = ""
    if len(toc) >= 3 and p["path"] != "contact":
        toc_html = '<nav class="toc" aria-label="Inhoud"><ul>' + "".join(
            f'<li><a href="#{sid}">{esc(t)}</a></li>' for sid, t in toc) + "</ul></nav>"
        # Inhoudsopgave na de eerste alinea plaatsen, zoals op het origineel.
        if "</p>" in body_html and body_html.index("</p>") < body_html.find("<h2"):
            i = body_html.index("</p>") + 4
            body_html = body_html[:i] + toc_html + body_html[i:]
        else:
            body_html = toc_html + body_html
    if (p.get("stub") or not p["lines"]) and not p.get("rawhtml"):
        body_html = (f'<p>{esc(p["summary"])}</p>' if p["summary"] else "") + \
            '<p class="note">De volledige tekst van deze pagina is nog niet teruggevonden.</p>'
    imgs = ""
    if p.get("rawhtml"):
        shown = set(re.findall(r'/wp-content/uploads/[^"\s]+', body_html))
        p["imgs"] = [im for im in p["imgs"] if not any(os.path.basename(im["src"]).split(".")[0][:20] in x for x in shown)]
    if p["imgs"]:
        figs = []
        for im in p["imgs"]:
            rel = img_local(im["src"])
            lokaal = [c for c in ("bronnen/vervanging/" + (rel or ""), rel or "", "bronnen/wayback/" + (rel or ""))
                      if rel and os.path.isfile(os.path.join(ROOT, c))]
            if not lokaal:
                continue  # afbeelding is verloren gegaan
            src = pg.rel(lokaal[0])
            figs.append(f'<figure><a href="{esc(src)}" target="_blank" rel="noopener"><img src="{esc(src)}" alt="{esc(im["alt"])}" loading="lazy" onerror="this.closest(\'figure\').remove()"></a>'
                        f'{f"<figcaption>{esc(im["alt"])}</figcaption>" if im["alt"] else ""}</figure>')
        if figs:
            imgs = '<section class="figs"><h2>Afbeeldingen bij dit artikel</h2>' + "".join(figs) + "</section>"
    nu = [("bronnen/eblinqx/" + n + ".webp", EBLINQX_SCHERMEN["schermen"][n])
          for n in EBLINQX_SCHERMEN["artikelen"].get(p["path"].strip("/"), [])]
    # extra actuele schermen per artikel (tools/vervanging_plaatsen.py)
    xmap = os.path.join("bronnen", "eblinqx-artikel", p["path"].strip("/").split("/")[-1])
    if os.path.isdir(os.path.join(ROOT, xmap)):
        bj = os.path.join(ROOT, xmap, "_bijschriften.json")
        bijschrift = json.load(open(bj, encoding="utf8")) if os.path.exists(bj) else {}
        nu += [(xmap + "/" + f, bijschrift.get(f, "")) for f in sorted(os.listdir(os.path.join(ROOT, xmap)))
               if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))]
    if nu:
        imgs = ('<section class="figs nu"><h2>Zo ziet het er nu uit in eBlinqx Connect</h2>' + "".join(
            f'<figure><a href="{pg.rel(src)}" target="_blank" rel="noopener">'
            f'<img src="{pg.rel(src)}" alt="{esc(cap)}" loading="lazy"></a>'
            + (f'<figcaption>{esc(cap)}</figcaption>' if cap else "") + '</figure>' for src, cap in nu) + "</section>") + imgs
    shot = ""  # screenshots van de Wayback-opname worden niet meer getoond; de echte afbeeldingen staan in het artikel
    if p["path"] not in ("contact",) and (p.get("rawhtml") or p["lines"]):
        imgs += ('<div class="feedback"><span class="fb-q">Was deze informatie nuttig?</span>'
                 '<button type="button" data-fb="ja">Ja</button><button type="button" data-fb="nee">Nee</button>'
                 '<p class="fb-out" role="status" hidden></p></div>')
    if p["path"] in REPLAYS:
        imgs = (f'<p class="replay"><a class="btn-out" href="{esc(REPLAYS[p["path"]])}" target="_blank" rel="noopener">'
                f'<svg class="ic"><use href="#i-play"/></svg> Bekijk de webinar-replay</a></p>') + imgs
    src = ""
    rel = related(cats, feeds, p)
    side = ""
    if rel:
        side = '<aside class="related"><h2>Gerelateerd:</h2><ul>' + "".join(
            f'<li><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></li>' for x in rel) + "</ul></aside>"
    cr = p["crumb"] or []
    active = FEEDS.get(cr[0]) if cr else None
    if p["path"] == "contact":
        active = "contact"
    if p["path"] == "trainingen":
        active = "trainingen"
    head = ""
    if p["path"] == "contact":
        head = hero(pg, "Contact", "hero-contact.jpg")
        side = ('<aside class="related contactbox"><h2>Contactgegevens</h2>'
                '<p>Blinqx powered by Faster Forward</p>'
                '<p>E-mail:<br><a href="mailto:support-eblinqx@blinqx.tech">support-eblinqx@blinqx.tech</a></p>'
                '<p>Telefoonnummer:<br><a href="tel:+31850180069">085 018 00 69</a></p>'
                '<p>Wij zijn bereikbaar op werkdagen van 8:30 tot 17:00</p>'
                '<h2 class="isl-h">Scherm delen</h2>'
                '<form id="isl-connect-form" class="isl" autocomplete="off"><label for="isl-code">Vul de sessiecode in die je van support hebt gekregen:</label>'
                '<input id="isl-code" name="code" type="text" inputmode="numeric" required>'
                '<button type="submit">Verbinden</button></form><p id="isl-feedback" role="status"></p></aside>')
    else:
        head = crumbs(pg, crumb_items(cats, p))
    raw = p.get("raw") or {}
    if raw.get("hero") and p["path"] != "contact":
        head = hero_url(resolve_img(pg, raw["hero"]), p["t"])
        h1 = ""
    else:
        h1 = "" if p["path"] == "contact" else f"<h1>{esc(p['t'])}</h1>"
    if p["path"] == "contact":
        rows = "".join(f"<tr><td>{esc(n)}</td><td><a href=\"mailto:{esc(m)}\">{esc(m)}</a></td><td>{esc(k)}</td></tr>" for n, m, k in PRODUCT_SUPPORT)
        body_html += ('<h2 id="andere-producten">Support voor andere Blinqx-producten</h2>'
                      '<p>Bel 085 018 00 69 en kies in het keuzemenu eerst 1 en daarna het nummer van het product.</p>'
                      f'<table class="ptable"><thead><tr><th>Product</th><th>E-mail</th><th>Keuzemenu</th></tr></thead><tbody>{rows}</tbody></table>'
                      '<p><a href="https://verzekeringhypotheek.blinqx.tech/support" target="_blank" rel="noopener">Supportoverzicht Blinqx Verzekering &amp; Hypotheek</a></p>')
    body = f"""{head}
<main class="article">
  <div class="wrap cols">
    <article>
      {h1}
      {f'<p class="meta">{" · ".join(meta)}</p>' if meta else ""}
      {f'<div class="oud" role="note"><strong>Let op: mogelijk verouderd.</strong> Dit artikel is voor het laatst bijgewerkt {esc(oud)} en beschrijft mogelijk een oudere versie van de software (Elements). Schermen en werkwijze kunnen in eBlinqx Connect afwijken. Twijfel je? <a href="{pg.rel("contact")}">Neem contact op met support</a>.</div>' if oud else ""}
      <div class="content">{body_html}</div>
      {imgs}
      {shot}
      {src}
    </article>
    {side}
  </div>
</main>"""
    write(p["path"], layout(pg, p["t"], body, active, p.get("excerpt", "")))


def render_category(cats, name):
    c = cats[name]
    path = cat_target(cats, name)
    pg = Page(path)
    blocks = []
    for sub in c["subs"].values():
        items = sub["items"]
        if not items:
            continue
        lis = "".join(f'<li><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></li>' for x in items[:5])
        more = f'<a class="more" href="{pg.rel(sub_target(cats, name, sub))}">Meer</a>'
        blocks.append(f'<section class="subcat"><h2>{esc(sub["name"])}</h2><ul>{lis}</ul>{more}</section>')
    if c["loose"]:
        lis = "".join(f'<li><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></li>' for x in c["loose"])
        blocks.append(f'<section class="subcat"><h2>{"Overige artikelen" if name != "Overig" else "Algemeen"}</h2><ul>{lis}</ul></section>')
    body = f"""{crumbs(pg, [("Kennisbank", "kennisbank"), (name, None)])}
<main class="catpage"><div class="wrap">
  <h1>{esc(name)}</h1>
  <div class="subgrid">{"".join(blocks)}</div>
</div></main>"""
    write(path, layout(pg, name, body))


def render_sub(cats, catname, sub):
    path = sub_target(cats, catname, sub)
    pg = Page(path)
    items = "".join(
        f'<article class="ex"><h2><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></h2>'
        f'{f"<p>{esc(x["excerpt"])}</p>" if x.get("excerpt") else ""}</article>' for x in sub["items"])
    body = f"""{crumbs(pg, [("Kennisbank", "kennisbank"), (catname, cat_target(cats, catname)), (sub["name"], None)])}
<main class="subpage"><div class="wrap">
  <h1>{esc(sub["name"])}</h1>
  <div class="exlist">{items or "<p>Geen artikelen gevonden.</p>"}</div>
</div></main>"""
    write(path, layout(pg, sub["name"], body))


FEED_LABEL = {"Release notes": "Releasenotes Connect"}
FEED_META = {
    "Nieuws": ("Laatste nieuws", "Hieronder vind je onze laatste nieuwsberichten.", "hero-nieuws.jpg"),
    "Tips": ("Laatste tips", "Hieronder vind je onze laatste tips.", "hero-tips.jpg"),
    "Release notes": ("Laatste releases", "Hieronder vind je de laatste updates.", "hero-releasenotes.jpg"),
}


def render_feed(name, items):
    path = FEEDS[name]
    pg = Page(path)
    h2, intro, img = FEED_META[name]

    def card(x):
        d = x["posted"] or x["updated"]
        img = ""
        if x.get("thumb") and not resolve_img(pg, x["thumb"]).startswith("http"):
            img = (f'<a class="card-img" href="{pg.rel(x["path"])}" tabindex="-1" aria-hidden="true">'
                   f'<img src="{esc(resolve_img(pg, x["thumb"]))}" alt="" loading="lazy" '
                   f'onerror="this.closest(\'.card\').classList.remove(\'has-img\');this.parentNode.remove()"></a>')
        return (f'<article class="card{" has-img" if img else ""}">{img}<div class="card-body"><h3><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></h3>'
                f'{f"<p class=\"date\">{fmt_date(d)}</p>" if d else ""}'
                f'{f"<p>{esc(x["excerpt"])}</p>" if x.get("excerpt") else ""}'
                f'<a class="readmore" href="{pg.rel(x["path"])}">Lees verder</a></div></article>')

    # Per jaar groeperen (zoals bij de releasenotes van Hypotheekadvies); zonder datum onderaan.
    groups = {}
    for x in items:
        d = x["posted"] or x["updated"]
        groups.setdefault(str(d.year) if d else "Overige berichten", []).append(x)
    keys = sorted((k for k in groups if k.isdigit()), reverse=True) + [k for k in groups if not k.isdigit()]
    jump = " · ".join(f'<a href="#jaar-{slugify(k)}">{esc(k)}</a>' for k in keys)
    blocks = "".join(f'<h2 class="feed-h" id="jaar-{slugify(k)}">{esc(k)}</h2><div class="cards">{"".join(card(x) for x in groups[k])}</div>'
                     for k in keys)
    title = FEED_LABEL.get(name, name)
    body = f"""{hero(pg, title, img)}
<main class="feed"><div class="wrap">
  {rn_tabs(pg, "connect") if name == "Release notes" else ""}
  <h2 class="feed-h">{esc(h2)}</h2>
  <p>{esc(intro)} {len(items)} berichten.</p>
  {f'<p class="jump">Ga naar: {jump}</p>' if len(keys) > 1 else ""}
  {f'<p class="note">Oudere releasenotes uit 2016 en 2017 staan als pdf bij de <a href="{pg.rel("downloads")}">downloads</a>.</p>' if name == "Release notes" else ""}
  {blocks}
  <div class="nb-cta"><h2>Op de hoogte blijven?</h2><p>Meld je aan voor onze nieuwsbrief om regelmatig tips te ontvangen.</p>
  <p><a class="btn-out cta" href="{pg.rel("nieuwsbrief")}">Aanmelden nieuwsbrief</a></p></div>
</div></main>"""
    write(path, layout(pg, title, body, path, f"{title}: {intro}"))


def render_kennisbank(cats):
    pg = Page("kennisbank")
    blocks = []
    for name, _ in TOP + [("Overig", None)]:
        c = cats[name]
        n = sum(len(s["items"]) for s in c["subs"].values()) + len(c["loose"])
        subs = "".join(f'<li><a href="{pg.rel(sub_target(cats, name, s))}">{esc(s["name"])}</a> <span class="n">({len(s["items"])})</span></li>'
                       for s in c["subs"].values() if s["items"])
        loose = f'<li><a href="{pg.rel(cat_target(cats, name))}">Overige artikelen</a> <span class="n">({len(c["loose"])})</span></li>' if c["loose"] else ""
        blocks.append(f'<section class="subcat"><h2><a href="{pg.rel(cat_target(cats, name))}">{esc(name)}</a> <span class="n">({n})</span></h2><ul>{subs}{loose}</ul></section>')
    body = f"""{crumbs(pg, [("Kennisbank", None)])}
<main class="catpage"><div class="wrap">
  <h1>Kennisbank</h1>
  <div class="subgrid">{"".join(blocks)}</div>
</div></main>"""
    write("kennisbank", layout(pg, "Kennisbank", body))


def search_kind(p):
    cr = p["crumb"] or []
    if cr and cr[0] in FEEDS:
        return {"Nieuws": "nieuws", "Tips": "tips", "Release notes": "release"}[cr[0]]
    if cr and cr[0] == "Overig":
        return "overig"
    return "kennisbank"


def render_search(pages, cats):
    pg = Page("zoeken")
    idx = []
    for p in pages.values():
        if p.get("skip") or p.get("role") != "article" or p["path"] == "trainingen":
            continue
        d = p["posted"] or p["updated"]
        idx.append({"t": p["t"], "h": p["path"] + "/index.html", "c": " › ".join(FEED_LABEL.get(c, c) for c in (p["crumb"] or [])),
                    "k": search_kind(p), "d": fmt_date(d) if d else "", "o": 1 if verouderd(p) else 0,
                    "x": re.sub(r"\s+", " ", " ".join(p["lines"]))[:200000]})
    for name, c in cats.items():
        if c["subs"] or c["loose"]:
            idx.append({"t": name, "h": cat_target(cats, name) + "/index.html", "c": "Kennisbank", "k": "categorie",
                        "x": " ".join(s_["name"] for s_ in c["subs"].values())})
        for sub in c["subs"].values():
            if sub["items"]:
                idx.append({"t": sub["name"], "h": sub_target(cats, name, sub) + "/index.html", "c": "Kennisbank › " + name,
                            "k": "categorie", "x": " ".join(x["t"] for x in sub["items"])})
    for v in video_lijst():
        idx.append({"t": v["t"], "h": "video/" + v["slug"] + "/index.html", "c": "Video's › " + v["groep"], "k": "video",
                    "d": fmt_date(date.fromisoformat(v["datum"])) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v["datum"]) else "",
                    "x": " ".join(x for x in (v.get("ch"), v["groep"], v.get("x"), v["tekst"]) if x)})
    frf = os.path.join(TOOLS, "finrust_videos.json")
    if os.path.exists(frf):
        idx.append({"t": "FinRust-video's", "h": "video/finrust/index.html", "c": "Video's", "k": "video",
                    "x": "finrust video's instructievideo adviessoftware youtube kanaal"})
        for v in json.load(open(frf, encoding="utf8"))["videos"]:
            idx.append({"t": v["t"], "h": "video/finrust/index.html#v-" + v["id"], "c": "Video's › FinRust", "k": "video",
                        "x": "finrust " + v["t"]})
    pvf = os.path.join(SRC, "procesversneller.html")
    if os.path.exists(pvf):
        pv = open(pvf, encoding="utf8").read()
        pv = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", pv, flags=re.S)
        idx.append({"t": "Proces-versneller: alles op een rij", "h": "procesversneller/index.html", "c": "Proces-versneller", "k": "kennisbank",
                    "x": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", pv)))[:200000] + " procesversneller ockto brondata"})
    wtf = os.path.join(SRC, "websitetools.json")
    if os.path.exists(wtf):
        wt = json.load(open(wtf, encoding="utf8"))
        idx.append({"t": "Makelaar Software: Yes-co", "h": "yes-co/index.html", "c": "Makelaar Software", "k": "kennisbank",
                    "x": YES_INTRO + " yesco yes co makelaarssoftware makelaar software crm funda pararius publiceren nieuwbouw "
                    "projecten digitaal ondertekenen wwft ubo app market pro plus prijs demo tools voor vastgoed toolsvoorvastgoed "
                    "woningwaarderapport waarderapport vastgoed publiceren tiara startende makelaar hypotheek toolset"})
        idx.append({"t": "Tools voor vastgoed: slimme online tools voor vastgoedprofessionals", "h": "tools-voor-vastgoed/index.html",
                    "c": "Tools voor vastgoed", "k": "kennisbank", "x": TVV_INTRO + " toolsvoorvastgoed tools voor vastgoed makelaar "
                    "hypotheek toolset rekentools leads woningwaarderapport woningwaarde vastgoed publiceren online klantdossier "
                    "mijnhuiszaken yes-co tiara startende makelaar prijzen € 80 per maand " + " ".join(t for t, _ in TVV_TOOLS)})
        idx.append({"t": "Demo-kantoor: een website met alles van Blinqx", "h": "demo-kantoor/index.html", "c": "Demo-kantoor", "k": "kennisbank",
                    "x": "demo kantoor demokantoor demowebsite voorbeeld website Steen Hypotheken FierFinance rekentools actuele rentes "
                    "mijnhuiszaken uwkluis financiële kluis duurzaamheidsprofiel pakketvergelijker website laten maken alles van Blinqx"})
        dmf = os.path.join(SRC, "demo", "index.json")
        if os.path.exists(dmf):
            for v in json.load(open(dmf, encoding="utf8")):
                idx.append({"t": v["titel"] + " (" + v["site"] + ")", "h": v["url"], "ext": 1, "c": "Demo-kantoor › " + v["site"],
                            "k": "overig", "x": "demo demokantoor " + (v.get("omschrijving") or "") + " " + v["tekst"]})
        for fn, label in (("site.json", "Adviesbox › Website"), ("helpcenter.json", "Adviesbox › Helpcenter")):
            abf = os.path.join(SRC, "adviesbox", fn)
            if os.path.exists(abf):
                for v in json.load(open(abf, encoding="utf8")):
                    idx.append({"t": v["titel"] + (" (Adviesbox)" if "dviesbox" not in v["titel"] else ""), "h": v["url"], "ext": 1,
                                "c": label + (" › " + v["collectie"] if v.get("collectie") else ""), "k": "overig",
                                "x": "adviesbox " + (v.get("omschrijving") or "") + " " + v["tekst"] + " " + " ".join(b["naam"] for b in v.get("bijlagen", []))})
        for st in sites_laden():
            idx.append({"t": f"{st['naam']}: {st['ondertitel']}", "h": f"sites/{st['slug']}/index.html", "c": "Handige websites", "k": "kennisbank",
                        "x": st["naam"] + " " + st["naam"].replace(".nl", "").replace(".net", "") + " " + st["url"] + " " + " ".join(st["tekst"])})
        idx.append({"t": "Banking & Insurance: Hypotheekcijfer.nl en Pensioencijfer.nl", "h": "banking-insurance/index.html", "c": "Banking & Insurance",
                    "k": "kennisbank", "x": "banking insurance bank verzekeraar geldverstrekker hypotheekcijfer pensioencijfer hypotheekcheck pensioen cijfer renteadministratie rentetool rente publicatie analyse"})
        idx.append({"t": "Handige websites", "h": "sites/index.html", "c": "Handige websites", "k": "kennisbank",
                    "x": "websites domeinen links " + " ".join(st["naam"] for st in sites_laden())})
        idx.append({"t": "Finly CRM: klantgegevens, workflows en communicatie op één plek", "h": "finly-crm/index.html", "c": "Finly CRM",
                    "k": "kennisbank", "x": FINLY_INTRO + " finly crm customer relationship management dias anva dstny awi my tp adviesbox "
                    "rapportage dashboard csv workflows signalen instelbaarheid demo " + " ".join(t + " " + x for t, x in FINLY_TOOLS)})
        idx.append({"t": "Partners van Blinqx Verzekering & Hypotheek", "h": "partners/index.html", "c": "Partners", "k": "kennisbank",
                    "x": "partners partner samenwerking koppeling eblinqx " + " ".join(p["titel"] + " " + " ".join(p["tags"]) for p in partners_laden())})
        for p in partners_laden():
            idx.append({"t": p["titel"], "h": f"partners/{p['slug']}/index.html", "c": "Partners", "k": "kennisbank",
                        "x": " ".join(p["tags"]) + " " + p["kort"] + " " + re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p["html"])))})
        idx.append({"t": "Woningwaarderapport: de waarde van de woning van je klant", "h": "woningwaarderapport/index.html",
                    "c": "Woningwaarderapport", "k": "kennisbank", "x": "woningwaarderapport woningwaarde rapport waardeschatting "
                    "woningwaarde berekenen waarde woning voorbeeldrapport tools voor vastgoed portefeuillesignalen verkopen verhuizen "
                    "hypotheek aanpassen leads geautomatiseerd overzicht taxatie"})
        idx.append({"t": "Hypotheekrente-app: alle actuele rentes bij de hand", "h": "hypotheekrente-app/index.html",
                    "c": "Hypotheekrente-app", "k": "kennisbank", "x": HRA_INTRO + " hypotheekrente app renteapp rentetarieven "
                    "rente overzicht geldverstrekkers app store google play android iphone eigen huisstijl white label hypotheekbond " +
                    " ".join(t for t, _ in HRA_TOOLS)})
        idx.append({"t": "Actiefbeheerscan: digitale formulieren voor nazorg en beheer", "h": "actiefbeheerscan/index.html",
                    "c": "Actiefbeheerscan", "k": "kennisbank", "x": ABS_INTRO + " actief beheer scan actiefbeheerscan nazorg klantbeheer "
                    "digitale formulieren webformulieren uitnodigingsmail reminder leads tarieven demo dutch media lab " +
                    " ".join(t + " " + x for t, _, _, x in ABS_FORMULIEREN)})
        idx.append({"t": "MijnHuiszaken: realtime woningaanbod voor je klanten", "h": "mijnhuiszaken/index.html", "c": "MijnHuiszaken",
                    "k": "kennisbank", "x": MHZ_INTRO + " woningaanbod NVM makelaar e-mailalerts zoekprofiel woningwaarde Wwft "
                    "aankoopdossier verkoopdossier digitaal ondertekenen leads tarieven demo mijn huiszaken mijnhuiszaken.nl video promovideo uitleg"})
        idx.append({"t": "Websitetools: rekentools voor op je website", "h": "websitetools/index.html", "c": "Websitetools", "k": "kennisbank",
                    "x": " ".join(g["g"] + " " + " ".join(t["t"] for t in g["tools"]) for g in wt["groepen"]) + " rekentool rekentools website hypotheekbond leads video uitleg"})
    vhf = os.path.join(SRC, "vh-site", "index.json")
    if os.path.exists(vhf):
        for v in json.load(open(vhf, encoding="utf8")):
            d = v.get("datum") or ""
            idx.append({"t": v["titel"], "h": v["url"], "ext": 1, "c": "eBlinqx website › " + v["soort"], "k": "website",
                        "d": fmt_date(date.fromisoformat(d)) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else "",
                        "x": (v.get("omschrijving") or "") + " " + v.get("tekst", "")})
        idx.append({"t": "Vacatures bij Blinqx", "h": "https://careers.blinqx.tech/", "ext": 1, "c": "eBlinqx website › Over ons",
                    "k": "website", "x": "vacatures vacature werken bij blinqx carrière careers baan solliciteren"})
    for i in downloads_items():
        idx.append({"t": i["t"], "h": "downloads/index.html", "c": "Downloads › " + i["rub"], "k": "overig",
                    "d": i["datum"], "x": i["t"] + " pdf download " + i["rub"]})
    tf = os.path.join(SRC, "academy", "trainingen.json")
    if os.path.exists(tf):
        for t in json.load(open(tf, encoding="utf8"))["trainingen"]:
            idx.append({"t": t["t"], "h": t["url"], "ext": 1, "c": "Trainingen › Blinqx Academy", "k": "video",
                        "x": " ".join(t["meta"] + t["labels"]) + " training cursus opleiding"})
    for m in fastlane_months()[0]:
        idx.append({"t": f'Releasenotes eBlinqx Hypotheekadvies – {m["label"]}', "h": f'releasenotes-hypotheekadvies/{m["slug"]}/index.html',
                    "c": "Releasenotes Hypotheekadvies (Fastlane)", "k": "release", "d": m["label"], "x": m["text"]})
    for k, naam, pad, extern in RN_DIENSTEN:
        if k in ("connect", "hypotheekadvies"):
            continue
        idx.append({"t": f"Releasenotes {naam}", "h": pad + "/index.html", "c": f"Releasenotes {naam}", "k": "release",
                    "x": RN_INTRO.get(k, "") + " releasenotes release updates " + naam})
        for d in rn_overig().get(k, []):
            idx.append({"t": d["titel"], "h": f'{pad}/{d["slug"]}/index.html', "c": f"Releasenotes {naam}", "k": "release",
                        "d": d["datum"], "x": d["text"]})
    for it in elearning_items():
        idx.append({"t": it["t"], "h": "elearning/" + it["slug"] + "/index.html", "c": "E-learning › " + it["prod"], "k": "video",
                    "x": " ".join(st["h"] + " " + st["text"] for st in it["steps"])[:200000] or it["t"]})
    os.makedirs(os.path.join(ROOT, "zoeken"), exist_ok=True)
    with open(os.path.join(ROOT, "zoeken", "zoekindex.js"), "w", encoding="utf8") as fh:
        for r in idx:
            for k in ("t", "c", "x"):
                if r.get(k):
                    r[k] = kluis_tekst(r[k])
        idx_js = "window.ZOEKINDEX=" + json.dumps(idx, ensure_ascii=False, separators=(",", ":")) + ";\n"
        fh.write(idx_js)
    import hashlib
    idx_v = hashlib.md5(idx_js.encode("utf8")).hexdigest()[:8]
    body = f"""{crumbs(pg, [("Zoeken", None)])}
<main class="subpage searchpage"><div class="wrap">
  <h1 id="sh">Zoeken</h1>
  <div class="sfilters" role="group" aria-label="Filter op soort">
    <button type="button" data-k="" aria-pressed="true">Alles</button>
    <button type="button" data-k="kennisbank" aria-pressed="false">Kennisbank</button>
    <button type="button" data-k="release" aria-pressed="false">Releasenotes</button>
    <button type="button" data-k="nieuws" aria-pressed="false">Nieuws &amp; tips</button>
    <button type="button" data-k="video" aria-pressed="false">Video's &amp; e-learning</button>
    <button type="button" data-k="website" aria-pressed="false">eBlinqx website</button>
  </div>
  <p id="scount" class="meta" aria-live="polite"></p>
  <div class="exlist" id="sres"></div>
  <p><button type="button" id="smore" class="smore" hidden>Toon meer resultaten</button></p>
</div></main>
<script src="zoekindex.js?v={idx_v}"></script>
<script src="zoeken.js?v={asset_versie('zoeken.js')}"></script>"""
    write("zoeken", layout(pg, "Zoeken", body))
    shutil.copy(os.path.join(TOOLS, "zoeken.js"), os.path.join(ROOT, "zoeken", "zoeken.js"))


# Korte versie van het verhaal op /websitetools/ voor de homepage
WT_KORT = [
    ("Meer en betere leads", "Aanvragen komen rechtstreeks in de leadinbox van eBlinqx Connect en/of je mail, inclusief de situatie van de klant."),
    ("Inzicht in je bezoekers", "Zie waar bezoekers mee bezig zijn: lenen, oversluiten, aflossen of verduurzamen."),
    ("Een professionele website", "Actuele rentes en betrouwbare berekeningen wekken vertrouwen."),
    ("Beter gevonden in Google", "Interactieve, actuele inhoud die aansluit op veelgezochte hypotheekvragen."),
    ("Zichtbaar in AI-zoekmachines", "ChatGPT, Gemini en Copilot noemen pagina’s met heldere uitleg en actuele cijfers als bron."),
    ("Klanten blijven betrokken", "Bespaarcheck, aflossen en verduurzamen: een natuurlijke aanleiding voor een vervolggesprek."),
]


def render_home(cats, feeds, pages):
    pg = Page("")

    def link_for(path, fallback_label=None):
        k = norm(BASE + "/" + path + "/")
        p = pages.get(k)
        if p and not p.get("skip"):
            return pg.rel(p["path"]), p["t"]
        return None, fallback_label

    tiles = "".join(
        f'<a class="tile" href="{pg.rel(cat_target(cats, name))}"><svg class="ic"><use href="#i-{icon}"/></svg>{esc(name)}</a>'
        for name, icon in TOP)
    tiles += (f'<a class="tile" href="{pg.rel("elearning")}"><svg class="ic"><use href="#i-cap"/></svg>E-learning</a>'
              f'<a class="tile" href="{pg.rel("video")}"><svg class="ic"><use href="#i-video"/></svg>Video\'s</a>'
              f'<a class="tile" href="{pg.rel("websitetools")}"><svg class="ic"><use href="#i-calc"/></svg>Websitetools</a>'
              f'<a class="tile" href="{pg.rel("mijnhuiszaken")}"><svg class="ic"><use href="#i-home"/></svg>MijnHuiszaken</a>'
              f'<a class="tile" href="{pg.rel("yes-co")}"><svg class="ic"><use href="#i-desktop"/></svg>Makelaar Software</a>'
              f'<a class="tile" href="{pg.rel("tools-voor-vastgoed")}"><svg class="ic"><use href="#i-folder"/></svg>Tools voor vastgoed</a>'
              f'<a class="tile" href="{pg.rel("woningwaarderapport")}"><svg class="ic"><use href="#i-houseval"/></svg>Woningwaarde rapport</a>'
              f'<a class="tile" href="{pg.rel("actiefbeheerscan")}"><svg class="ic"><use href="#i-list"/></svg>Actiefbeheerscan</a>'
              f'<a class="tile" href="{pg.rel("hypotheekrente-app")}"><svg class="ic"><use href="#i-percent"/></svg>Hypotheekrente-app</a>'
              f'<a class="tile" href="{pg.rel("finly-crm")}"><svg class="ic"><use href="#i-crm"/></svg>Finly CRM</a>'
              f'<a class="tile" href="{pg.rel("banking-insurance")}"><svg class="ic"><use href="#i-bank"/></svg>Banking &amp; Insurance</a>'
              f'<a class="tile" href="https://verzekeringhypotheek.blinqx.tech/" target="_blank" rel="noopener"><svg class="ic"><use href="#i-globe"/></svg>Website Blinqx Verzekering &amp; Hypotheek ↗</a>'
              f'<a class="tile" href="{pg.rel("partners")}"><svg class="ic"><use href="#i-partners"/></svg>Partners</a>'
              f'<a class="tile" href="{pg.rel("procesversneller")}"><svg class="ic"><use href="#i-bolt"/></svg>Proces-versneller</a>'
              f'<a class="tile" href="{pg.rel("sites/hypotheekbos-nl")}"><svg class="ic"><use href="#i-tree"/></svg>Hypotheekbos</a>')

    def a(path, label):
        href, _ = link_for(path)
        return f'<a href="{href or "#"}">{label}</a>'

    def latest(feed, n=5):
        return "".join(f'<li><a href="{pg.rel(x["path"])}">{esc(x["t"])} »</a></li>' for x in feeds[feed][:n])

    nieuws_home = [
        ("webinar-efficient-risicos-inventariseren-met-finly-formulieren", "Webinar: efficiënt risico’s inventariseren met Finly formulieren"),
        ("abn-amro-deelt-hypotheekdata-met-adviseurs-via-hdn", "ABN AMRO deelt hypotheekdata met adviseurs via HDN"),
        ("webinar-haal-meer-uit-je-website-met-rekentools-en-actueel-nieuws", "Webinar: haal meer uit je website met rekentools en actueel nieuws"),
        ("webinar-nieuwe-feature-mytp", "Webinar: met één klik verzekeringen vergelijken met My TP"),
        ("september-terugblik-nieuwe-elements-features", "Webinar: september terugblik nieuwe Elements features"),
    ]
    fl_latest = "".join(f'<li><a href="{pg.rel("releasenotes-hypotheekadvies/" + m["slug"])}">Releasenotes {esc(m["label"])}'
                        f'{f" ({m["count"]} verbeteringen)" if m["count"] else ""} »</a></li>'
                        for m in fastlane_months()[0][:5])
    nieuws_li = "".join(f'<li>{a(p, esc(l) + " »")}</li>' for p, l in nieuws_home)

    body = f"""<main class="home">
  <div class="wrap">
    <div class="notice">
      <b>In een nieuw jasje - gezamenlijke look &amp; feel</b>
      De labels van Blinqx Verzekering &amp; Hypotheek krijgen steeds meer het Blinqx-jasje. Zo wordt ook visueel duidelijker dat we vanuit dezelfde organisatie werken, en dat al deze labels bij elkaar horen. Je merkt het al als je onze kantoren bezoekt, en nu ook op deze website.
    </div>

    <h2>Kennisbank</h2>
    <div class="btn-row">
      {a("kennisbank/nieuwe-gebruiker-aanvragen", "Nieuwe gebruiker aanvragen").replace("<a ", '<a class="btn-out" ', 1)}
      {a("kennisbank/gebruiker-opzeggen", "Gebruiker opzeggen").replace("<a ", '<a class="btn-out" ', 1)}
      <a class="btn-out" href="{pg.rel('elearning')}">E-learning</a>
    </div>
    <div class="tiles">{tiles}</div>

    <section class="home-wt" aria-labelledby="home-wt-h">
      <h2 id="home-wt-h">Websitetools: meer leads uit je eigen website</h2>
      <p>Een hypotheek begint online. Met 22 rekentools op de website van je kantoor berekenen bezoekers zelf hun maximale hypotheek, maandlasten of de actuele rentes, en ben jij het kantoor dat ze als eerste verder helpt.</p>
      <div class="wtwhys">{"".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in WT_KORT)}</div>
      <p class="home-wt-cta btn-row"><a class="btn-out cta" href="{pg.rel('websitetools')}">Bekijk de rekentools en lees meer »</a>
        <a class="btn-out" href="{pg.rel('websitetools')}#video">▶ Bekijk de video</a></p>
      <p class="home-wt-note">De uitkomsten van de rekentools zijn indicatief en geen advies.</p>
    </section>

    <h2>Actualiteiten</h2>
    <div class="news-bars">
      {a("header-op-maat", "Meer informatie in de header van een dossier? Kan geregeld worden! »").replace("<a ", '<a class="bar" ', 1)}
      {a("maak-een-overzichtelijke-rapportage-met-deze-persoonlijke-filters", "Maak een overzichtelijke rapportage met deze persoonlijke filters »").replace("<a ", '<a class="bar" ', 1)}
      {a("aanspreekvorm", "Uw, jouw, jullie? Met deze instelling gaat het vanzelf goed »").replace("<a ", '<a class="bar" ', 1)}
    </div>

    <h2>Nieuws &amp; Tips</h2>
    <div class="nt">
      <div class="tabs" role="tablist" aria-label="Nieuws en tips">
        <button role="tab" id="tab-nieuws" aria-controls="p-nieuws" aria-selected="true">Nieuwsberichten</button>
        <button role="tab" id="tab-release" aria-controls="p-release" aria-selected="false" tabindex="-1">Releasenotes Connect</button>
        <button role="tab" id="tab-fl" aria-controls="p-fl" aria-selected="false" tabindex="-1">Releasenotes Hypotheekadvies</button>
        <button role="tab" id="tab-tips" aria-controls="p-tips" aria-selected="false" tabindex="-1">Tips</button>
      </div>
      <div>
        <section class="panel" id="p-nieuws" role="tabpanel" aria-labelledby="tab-nieuws">
          <h3>Laatste 5 nieuwsberichten</h3>
          <ul>{nieuws_li}<li class="all"><a href="{pg.rel('nieuws')}">Alle nieuwsberichten »</a></li></ul>
        </section>
        <section class="panel" id="p-release" role="tabpanel" aria-labelledby="tab-release" hidden>
          <h3>Laatste 5 releasenotes eBlinqx Connect</h3>
          <ul>{latest("Release notes")}<li class="all"><a href="{pg.rel('releasenotes')}">Alle releasenotes Connect »</a></li></ul>
        </section>
        <section class="panel" id="p-fl" role="tabpanel" aria-labelledby="tab-fl" hidden>
          <h3>Laatste 5 releasenotes eBlinqx Hypotheekadvies</h3>
          <ul>{fl_latest}<li class="all"><a href="{pg.rel('releasenotes-hypotheekadvies')}">Alle releasenotes Hypotheekadvies »</a></li></ul>
        </section>
        <section class="panel" id="p-tips" role="tabpanel" aria-labelledby="tab-tips" hidden>
          <h3>Laatste 5 tips</h3>
          <ul>{latest("Tips")}<li class="all"><a href="{pg.rel('tips')}">Alle tips »</a></li></ul>
        </section>
      </div>
    </div>
  </div>
</main>
<script>
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function select(tab){{
    tabs.forEach(t => {{
      const on = t === tab;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    }});
  }}
  tabs.forEach((t, i) => {{
    t.addEventListener("click", () => select(t));
    t.addEventListener("keydown", e => {{
      const d = {{ArrowDown:1, ArrowRight:1, ArrowUp:-1, ArrowLeft:-1}}[e.key];
      if (!d) return;
      e.preventDefault();
      const n = tabs[(i + d + tabs.length) % tabs.length];
      n.focus(); select(n);
    }});
  }});
</script>"""
    write("index.html", layout(pg, "", body, ""))


def fmt_dur(d):
    if not d:
        return ""
    d = int(d)
    return f"{d // 3600}:{d % 3600 // 60:02d}:{d % 60:02d}" if d >= 3600 else f"{d // 60}:{d % 60:02d}"


VIDEO_EXTRA = [  # eigen video's die op een productpagina staan
    {"id": "mijnhuiszaken-promo", "mp4": "bronnen/mijnhuiszaken/mijnhuiszaken-promo.mp4", "poster": "bronnen/mijnhuiszaken/mijnhuiszaken-promo.webp",
     "t": "MijnHuiszaken voor hypotheekadviseurs", "d": 186, "ch": "MijnHuiszaken", "groep": "Productvideo's", "pagina": ("mijnhuiszaken", "MijnHuiszaken"),
     "beschrijving": "Altijd in beeld vanaf de eerste zoekopdracht. In drie minuten zie je hoe MijnHuiszaken werkt voor hypotheekadviseurs: "
                     "één klantomgeving gekoppeld aan jouw naam, realtime NVM-woningaanbod voor je klanten, je eigen logo in hun omgeving en "
                     "in de e-mailalerts, de klantreis tijdens de oriëntatie en de tarieven (€ 79 per maand voor 1.000 klanten, € 350 eenmalig)."},
    {"id": "rekentools-video", "mp4": "bronnen/websitetools/rekentools-video.mp4", "poster": "bronnen/websitetools/rekentools-video.webp",
     "t": "Rekentools voor op de website van de adviseur", "d": 156, "ch": "Blinqx Verzekering & Hypotheek", "groep": "Productvideo's",
     "pagina": ("websitetools", "Websitetools"),
     "beschrijving": "Een compleet pakket rekentools van Blinqx voor de website van je kantoor, gekoppeld aan eBlinqx. De video laat per "
                     "categorie zien welke tools er zijn: hypotheek berekenen (maximale hypotheek, maandlasten, kan ik deze woning kopen?), "
                     "aflossen en besparen, woning en verduurzamen, en klantinzicht. De uitkomsten zijn indicatief en geen advies."},
]
VIDEO_BESCHRIJVING = {  # eigen omschrijving waar YouTube er geen (bruikbare) heeft
    "kassa-2016": "Fragment uit het consumentenprogramma Kassa (BNNVARA, 2016) over te dure premies voor overlijdensrisicoverzekeringen. "
                  "Namens de Nationale Hypotheekbond schuiven Jos van Driesum, Wouter Abbink en Jeroen Oversteegen aan.",
    "gouden-lotus-2018": "De Nationale Hypotheekbond won in 2018 de Gouden Lotus. Jos van Driesum nam de prijs in ontvangst en vertelt erover.",
    "quinn-mail-90s": "In 90 seconden zie je hoe je Quinn Mail gebruikt in eBlinqx: een e-mail openen, met AI een antwoord laten opstellen, "
                      "een taak aanmaken vanuit de mail en de mail koppelen aan het dossier.",
}
STOP = set("de het een en van in op met voor naar je jouw u uw hoe wat is bij aan te over of dat deze die zo ook als door om tot "
           "maak ik wij we elements faster forward eblinqx connect video uitleg nieuw nieuwe".split())


def video_lijst():
    """Alle video's met een eigen pagina: tools/videos.json (+ meta) en VIDEO_EXTRA. Slugs zijn stabiel en uniek."""
    meta_f = os.path.join(TOOLS, "video_meta.json")
    meta = json.load(open(meta_f, encoding="utf8")) if os.path.exists(meta_f) else {}
    uit, gezien = [], set()
    alle = [dict(v, groep=g["group"]) for g in json.load(open(os.path.join(TOOLS, "videos.json"), encoding="utf8")) for v in g["videos"]]
    for v in alle + [dict(v) for v in VIDEO_EXTRA]:
        m = meta.get(v["id"], {})
        import unicodedata
        slug = slugify(unicodedata.normalize("NFKD", v["t"]).encode("ascii", "ignore").decode())
        if slug in gezien:
            slug = (slug[:48] + "-" + slugify(v["id"]))[:60]
        gezien.add(slug)
        tekst = VIDEO_BESCHRIJVING.get(v["id"]) or v.get("beschrijving") or m.get("beschrijving", "")
        tekst = re.sub(r"https?://\S+", "", tekst)
        tekst = "\n".join(l.strip() for l in tekst.split("\n") if l.strip() and not re.match(r"^(#|Meer (info|informatie)|Kijk op|Bezoek|Volg ons)", l.strip(), re.I))
        tekst = re.sub(r"\s*#\w+", "", tekst).strip()
        if len(tekst) < 40:
            tekst = (f"{v['t']}: een video van {v.get('ch') or 'Blinqx'} uit de rubriek ‘{v['groep']}’ op de supportsite van "
                     "eBlinqx Connect (voorheen Faster Forward Elements).")
        uit.append(dict(v, slug=slug, tekst=tekst[:900], datum=m.get("datum") or v.get("datum") or "",
                        duur=m.get("duur") or v.get("d") or 0))
    return uit


def gerelateerd(v, artikelen):
    woorden = {w for w in re.findall(r"[a-zà-ÿ]{4,}", (v["t"] + " " + v.get("x", "")).lower()) if w not in STOP}
    if not woorden:
        return []
    score = []
    for p in artikelen:
        tw = {w for w in re.findall(r"[a-zà-ÿ]{4,}", p["t"].lower()) if w not in STOP}
        n = len(woorden & tw)
        if n >= 2 or (n == 1 and len(tw) <= 2):
            score.append((n, p))
    score.sort(key=lambda x: (-x[0], len(x[1]["t"])))
    return [p for _, p in score[:3]]


def render_videopaginas(pages):
    artikelen = [p for p in pages.values() if not p.get("skip") and p.get("role") == "article" and p["path"].startswith("kennisbank/")]
    for v in video_lijst():
        pg = Page("video/" + v["slug"])
        groot = f"bronnen/video/groot/{v['id']}.jpg"
        bron = v.get("poster") or (groot if os.path.exists(os.path.join(ROOT, groot)) else f"assets/video/{v['id']}.jpg")
        thumb, thumb_abs = pg.rel(bron), SITE_URL + bron
        if v.get("mp4"):
            speler = (f'<div class="vplayer"><video controls preload="none" playsinline poster="{thumb}" width="1280" height="720">'
                      f'<source src="{pg.rel(v["mp4"])}" type="video/mp4"></video></div>')
            ld_extra = {"contentUrl": SITE_URL + v["mp4"]}
            extern = ""
        elif v.get("vimeo"):
            speler = (f'<div class="vplayer frame" data-vimeo="{esc(v["vimeo"])}"><img src="{thumb}" alt="" loading="lazy">'
                      f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>')
            ld_extra = {"embedUrl": f"https://player.vimeo.com/video/{v['vimeo']}"}
            extern = f'<a href="https://vimeo.com/{esc(v["vimeo"])}" target="_blank" rel="noopener">Bekijk op Vimeo ↗</a>'
        elif v.get("url"):
            speler = (f'<div class="vplayer frame"><a href="{esc(v["url"])}" target="_blank" rel="noopener"><img src="{thumb}" alt="" loading="lazy">'
                      f'<span class="play"><svg class="ic"><use href="#i-play"/></svg></span></a></div>')
            ld_extra = {"embedUrl": v["url"]}
            extern = f'<a href="{esc(v["url"])}" target="_blank" rel="noopener">Bekijk de replay op WebinarGeek ↗</a>'
        else:
            speler = (f'<div class="vplayer frame" data-yt="{esc(v["id"])}"><img src="{thumb}" alt="" loading="lazy">'
                      f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>')
            ld_extra = {"embedUrl": f"https://www.youtube-nocookie.com/embed/{v['id']}"}
            extern = f'<a href="https://www.youtube.com/watch?v={esc(v["id"])}" target="_blank" rel="noopener">Bekijk op YouTube ↗</a>'
        meta = " · ".join(x for x in (v.get("ch"), fmt_dur(v["duur"]) if v["duur"] else "",
                                      fmt_date(date.fromisoformat(v["datum"])) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v["datum"]) else "") if x)
        alineas = "".join(f"<p>{esc(a)}</p>" for a in v["tekst"].split("\n") if a.strip())
        rel = gerelateerd(v, artikelen)
        lees = ""
        if v.get("pagina"):
            lees += f'<li><a href="{pg.rel(v["pagina"][0])}">{esc(v["pagina"][1])}</a></li>'
        lees += "".join(f'<li><a href="{pg.rel(p["path"])}">{esc(p["t"])}</a></li>' for p in rel)
        ld = {"@context": "https://schema.org", "@type": "VideoObject", "name": v["t"], "description": v["tekst"][:500],
              "thumbnailUrl": thumb_abs, "uploadDate": v["datum"] or "2026-11-04", "inLanguage": "nl-NL"}
        if v["duur"]:
            ld["duration"] = f"PT{int(v['duur']) // 60}M{int(v['duur']) % 60}S"
        ld.update(ld_extra)
        body = f"""{crumbs(pg, [("Video's", "video"), (v["t"], None)])}
<main class="subpage vpagina"><div class="wrap">
  <h1>{esc(v["t"])}</h1>
  <p class="meta">{esc(meta)}{" · " + extern if extern else ""}</p>
  {speler}
  <div class="vtekst">{alineas}</div>
  {f'<h2 class="wth">Lees ook</h2><ul>{lees}</ul>' if lees else ""}
  <p><a href="{pg.rel("video")}#v-{esc(v["id"])}">← Alle video's</a> · rubriek: {esc(v["groep"])}</p>
</div></main>
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\\\/")}</script>
<script>
document.addEventListener("click", e => {{
  const b = e.target.closest("[data-yt] .play, [data-vimeo] .play"); if (!b) return;
  const f = b.closest("[data-yt], [data-vimeo]");
  f.innerHTML = f.dataset.vimeo
    ? `<iframe src="https://player.vimeo.com/video/${{f.dataset.vimeo}}?autoplay=1&dnt=1" title="Video" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>`
    : `<iframe src="https://www.youtube-nocookie.com/embed/${{f.dataset.yt}}?autoplay=1&rel=0" title="Video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
}});
</script>"""
        write("video/" + v["slug"], layout(pg, f"{v['t']} (video)", body, None, v["tekst"]))


def render_video():
    pg = Page("video")
    groups = json.load(open(os.path.join(TOOLS, "videos.json"), encoding="utf8"))
    vl = {v["id"]: v for v in video_lijst()}
    vslug = {k: v["slug"] for k, v in vl.items()}
    for g in groups:  # nieuwste eerst; video's zonder bekende datum achteraan
        g["videos"].sort(key=lambda v: vl[v["id"]]["datum"] or "0000", reverse=True)
    groups.sort(key=lambda g: max((vl[v["id"]]["datum"] or "0000") for v in g["videos"]), reverse=True)
    el = [l.rstrip("\n").split("|") for l in open(os.path.join(TOOLS, "elearning.txt"), encoding="utf8")
          if l.strip() and not l.startswith("#")]
    cards = []
    for label, url, title, pw in el:
        t = re.sub(r"^eBlinqx Connect:\s*", "", title).rstrip(".") or label
        t = t[:1].upper() + t[1:]
        prod = "eBlinqx Hypotheekadvies" if "Hypotheekadvies" in title else ("eBlinqx Connect" if title else "eBlinqx Advies")
        yt = re.search(r"youtu\.be/([\w-]+)", url)
        thumb = (f'<img src="{pg.rel("assets/video/" + yt.group(1) + ".jpg")}" alt="" loading="lazy">' if yt
                 else '<span class="el-ic"><svg class="ic"><use href="#i-desktop"/></svg></span>')
        cards.append(
            f'<div class="video el"><a class="frame" href="{esc(url)}" target="_blank" rel="noopener">{thumb}'
            f'<span class="play"><svg class="ic"><use href="#i-play"/></svg></span></a>'
            f'<h3><a href="{esc(url)}" target="_blank" rel="noopener">{esc(t)}</a></h3>'
            f'<p>{esc(prod)} · {"interactieve demo" if not yt else "video"}{f" · wachtwoord: <b>{esc(pw)}</b>" if pw else ""}</p></div>')
    sections = [f'<p class="note">Op zoek naar de interactieve instructies? Die staan op de pagina <a href="{pg.rel("elearning")}">E-learning</a>. '
                f'Alle instructievideo\'s van FinRust vind je op <a href="{pg.rel("video/finrust")}">FinRust-video\'s</a>.</p>']
    for g in groups:
        vs = []
        for v in g["videos"]:
            dt = vl[v["id"]]["datum"]
            meta = " · ".join(x for x in (v.get("ch"), fmt_dur(v.get("d") or vl[v["id"]]["duur"]),
                                          fmt_date(date.fromisoformat(dt)) if len(dt) == 10 else dt) if x)
            thumb = pg.rel(f'assets/video/{v["id"]}.jpg')
            if v.get("mp4"):
                vs.append(f'<div class="video" id="v-{esc(v["id"])}"><div class="frame"><video controls preload="none" playsinline poster="{thumb}" '
                          f'aria-label="{esc(v["t"])}"><source src="{pg.rel(v["mp4"])}" type="video/mp4"></video></div>'
                          f'<h3><a href="{pg.rel("video/" + vslug[v["id"]])}">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
            elif v.get("vimeo"):
                vs.append(f'<div class="video" id="v-{esc(v["id"])}"><div class="frame" data-vimeo="{esc(v["vimeo"])}"><img src="{thumb}" alt="" loading="lazy">'
                          f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>'
                          f'<h3><a href="{pg.rel("video/" + vslug[v["id"]])}">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
            elif v.get("url"):
                vs.append(f'<div class="video" id="v-{esc(v["id"])}"><a class="frame" href="{esc(v["url"])}" target="_blank" rel="noopener"><img src="{thumb}" alt="" loading="lazy">'
                          f'<span class="play"><svg class="ic"><use href="#i-play"/></svg></span></a>'
                          f'<h3><a href="{pg.rel("video/" + vslug[v["id"]])}">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
            else:
                vs.append(f'<div class="video" id="v-{esc(v["id"])}"><div class="frame" data-yt="{esc(v["id"])}"><img src="{thumb}" alt="" loading="lazy">'
                          f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>'
                          f'<h3><a href="{pg.rel("video/" + vslug[v["id"]])}">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
        sections.append(f'<section class="vgroup"><h2>{esc(g["group"])}</h2><div class="vgrid">{"".join(vs)}</div></section>')
    body = f"""{crumbs(pg, [("Video's", None)])}
<main class="subpage"><div class="wrap">
  <h1>Video's</h1>
  <nav class="kanalen" aria-label="Videokanalen">
    <p><strong>Onze kanalen:</strong></p>
    <div class="wtbtns">
      <a class="wtbtn" href="https://www.youtube.com/@BlinqxVerzekeringHypotheek" target="_blank" rel="noopener">YouTube: Blinqx Verzekering &amp; Hypotheek ↗</a>
      <a class="wtbtn" href="https://www.youtube.com/@Blinqx" target="_blank" rel="noopener">YouTube: Blinqx ↗</a>
      <a class="wtbtn" href="https://www.youtube.com/@FasterForwardTV" target="_blank" rel="noopener">YouTube: FasterForwardTV ↗</a>
      <a class="wtbtn" href="https://www.youtube.com/@FFWDelements" target="_blank" rel="noopener">YouTube: FFWD Elements ↗</a>
    </div>
    <p><strong>Partners:</strong></p>
    <div class="wtbtns">
      <a class="wtbtn" href="{pg.rel("video/finrust")}">FinRust: alle video's op deze site</a>
      <a class="wtbtn" href="https://www.youtube.com/@FinRust" target="_blank" rel="noopener">YouTube: FinRust ↗</a>
      <a class="wtbtn" href="https://www.youtube.com/@nationalehypotheekbond4615" target="_blank" rel="noopener">YouTube: Nationale Hypotheekbond ↗</a>
      <a class="wtbtn" href="https://vimeo.com/user93926830" target="_blank" rel="noopener">Vimeo: Nationale Hypotheekbond ↗</a>
    </div>
  </nav>
  <p class="lead">Instructievideo's, webinars en presentaties over Faster Forward Elements en eBlinqx. Video's worden pas van YouTube of Vimeo geladen als je op afspelen klikt.</p>
  {"".join(sections)}
</div></main>
<script>
document.addEventListener("click", e => {{
  const b = e.target.closest("[data-yt] .play, [data-vimeo] .play");
  if (!b) return;
  const f = b.closest("[data-yt], [data-vimeo]");
  f.innerHTML = f.dataset.vimeo
    ? `<iframe src="https://player.vimeo.com/video/${{f.dataset.vimeo}}?autoplay=1&dnt=1" title="Video" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>`
    : `<iframe src="https://www.youtube-nocookie.com/embed/${{f.dataset.yt}}?autoplay=1&rel=0" title="Video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
}});
</script>"""
    write("video", layout(pg, "Video's", body))


ELEARN_DIR = os.path.join(SRC, "elearning")


def elearning_items():
    """E-learnings uit tools/elearning.txt, aangevuld met de uitgelezen stappen (bronnen/elearning/<id>/stappen.json)."""
    items = []
    for l in open(os.path.join(TOOLS, "elearning.txt"), encoding="utf8"):
        if not l.strip() or l.startswith("#"):
            continue
        label, url, title, pw = l.rstrip("\n").split("|")
        t = re.sub(r"^eBlinqx Connect:\s*", "", title).rstrip(".") or label
        t = t[:1].upper() + t[1:]
        yt = re.search(r"youtu\.be/([\w-]+)", url)
        sid = url.rstrip("/").split("/")[-1]
        prod = "eBlinqx Hypotheekadvies" if "Hypotheekadvies" in title else ("eBlinqx Connect" if title else "eBlinqx Advies")
        it = {"t": t, "url": url, "id": sid, "yt": yt.group(1) if yt else None, "prod": prod, "pw": pw,
              "slug": slugify(t), "steps": []}
        f = os.path.join(ELEARN_DIR, sid, "stappen.json")
        if os.path.exists(f):
            data = json.load(open(f, encoding="utf8"))
            prev = None
            for st in data["steps"]:
                img = None
                if st.get("page") and st["page"] != prev and os.path.exists(os.path.join(ELEARN_DIR, sid, st["page"] + ".webp")):
                    img = f'bronnen/elearning/{sid}/{st["page"]}.webp'
                prev = st.get("page") or prev
                it["steps"].append({"h": st.get("title", ""), "html": st.get("html", ""), "img": img,
                                    "flow": st.get("flow", ""), "text": html.unescape(re.sub(r"<[^>]+>", " ", st.get("html", "")))})
        items.append(it)
    return items


def render_elearning():
    items = elearning_items()
    pg = Page("elearning")
    cards = []
    for it in items:
        first_img = next((st["img"] for st in it["steps"] if st["img"]), None)
        thumb = (pg.rel(first_img) if first_img else
                 pg.rel(f'assets/video/{it["yt"]}.jpg') if it["yt"] else "")
        n = f'{len(it["steps"])} stappen' if it["steps"] else ("video" if it["yt"] else "interactieve demo")
        cards.append(
            f'<div class="video el"><a class="frame" href="{pg.rel("elearning/" + it["slug"])}">'
            f'{f"<img src=\"{thumb}\" alt=\"\" loading=\"lazy\">" if thumb else ""}'
            f'<span class="play"><svg class="ic"><use href="#i-play"/></svg></span></a>'
            f'<h3><a href="{pg.rel("elearning/" + it["slug"])}">{esc(it["t"])}</a></h3>'
            f'<p>{esc(it["prod"])} · {n}</p></div>')
    body = f"""{crumbs(pg, [("E-learning", None)])}
<main class="subpage"><div class="wrap">
  <h1>E-learning</h1>
  <p class="lead">Interactieve instructies per onderwerp: klik je stap voor stap door de software, of lees de stappen rustig na op de pagina van de e-learning. Zie ook de <a href="{pg.rel('video')}">video's</a>.</p>
  <div class="vgrid elgrid">{"".join(cards)}</div>
</div></main>"""
    write("elearning", layout(pg, "E-learning", body, "elearning", "Interactieve e-learnings voor eBlinqx Connect en eBlinqx Hypotheekadvies."))

    for it in items:
        path = "elearning/" + it["slug"]
        pg = Page(path)
        if it["yt"]:
            demo = (f'<div class="video demo"><div class="frame" data-yt="{esc(it["yt"])}"><img src="{pg.rel("assets/video/" + it["yt"] + ".jpg")}" alt="">'
                    f'<button class="play" type="button" aria-label="Video afspelen"><svg class="ic"><use href="#i-play"/></svg></button></div></div>')
        else:
            demo_url = f'https://blinqx.storylane.io/demo/{it["id"]}?embed=inline'
            fi = next((st["img"] for st in it["steps"] if st["img"]), None)
            first = pg.rel(fi) if fi else ""
            demo = (f'<div class="video demo"><div class="frame" data-sl="{esc(demo_url)}">'
                    f'{f"<img src=\"{first}\" alt=\"\">" if first else ""}'
                    f'<button class="play" type="button" aria-label="Start de interactieve e-learning"><svg class="ic"><use href="#i-play"/></svg><span>Start de interactieve e-learning</span></button></div>'
                    f'<p><a href="{esc(it["url"])}" target="_blank" rel="noopener">Open in een nieuw tabblad</a>'
                    f'{f" · wachtwoord: <b>{esc(it["pw"])}</b>" if it["pw"] else ""}</p></div>')
        steps = ""
        if it["steps"]:
            parts, flow = [], None
            flows = {st["flow"] for st in it["steps"]}
            for i, st in enumerate(it["steps"], 1):
                if len(flows) > 1 and st["flow"] != flow:
                    flow = st["flow"]
                    parts.append(f'<li class="sflow"><h2 id="{slugify(flow)}">{esc(flow)}</h2></li>')
                shot = (f'<a class="sshot" href="{pg.rel(st["img"])}" target="_blank" rel="noopener"><img src="{pg.rel(st["img"])}" alt="Scherm bij stap {i}" loading="lazy"></a>'
                        if st["img"] else "")
                parts.append(f'<li id="stap-{i}"><h3><span class="snum">Stap {i}</span>{esc(st["h"])}</h3>{st["html"]}{shot}</li>')
            steps = f'<h2 id="stappen">Alle stappen</h2><ol class="steps">{"".join(parts)}</ol>'
        others = "".join(f'<li><a href="{pg.rel("elearning/" + o["slug"])}">{esc(o["t"])}</a></li>' for o in items if o is not it)
        meta = f'{esc(it["prod"])} · {"video" if it["yt"] else "interactieve demo"}{f" · {len(it["steps"])} stappen" if it["steps"] else ""}'
        body = f"""{crumbs(pg, [("E-learning", "elearning"), (it["t"], None)])}
<main class="article"><div class="wrap cols">
  <article>
    <h1>{esc(it["t"])}</h1>
    <p class="meta">{meta}</p>
    {demo}
    <div class="content">{steps}</div>
  </article>
  <aside class="related"><h2>Andere e-learnings:</h2><ul>{others}</ul></aside>
</div></main>
<script>
document.addEventListener("click", e => {{
  const b = e.target.closest(".play");
  const f = b && b.closest("[data-sl],[data-yt]");
  if (!f) return;
  const src = f.dataset.sl || `https://www.youtube-nocookie.com/embed/${{f.dataset.yt}}?autoplay=1&rel=0`;
  f.innerHTML = `<iframe src="${{src}}" title="E-learning" allow="autoplay; fullscreen; clipboard-write; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
}});
</script>"""
        write(path, layout(pg, it["t"], body, "elearning", f'E-learning {it["prod"]}: {it["t"]}'))


FL_DIR = os.path.join(SRC, "fastlane")
FL_BASE = "https://fastlane.hypotheekbond.nl"
FL_TITLE = "Releasenotes eBlinqx Hypotheekadvies (Fastlane)"


def fastlane_months():
    """Releasenotes per maand uit bronnen/fastlane/releasenotes-<jaar>.html (fastlane.hypotheekbond.nl)."""
    from urllib.parse import urljoin
    out, intro = [], ""
    for f in sorted(glob.glob(os.path.join(FL_DIR, "releasenotes-20*.html")), reverse=True):
        year = re.search(r"(\d{4})", os.path.basename(f)).group(1)
        doc = open(f, encoding="utf8").read()
        if not intro:
            m = re.search(r'<div class="heading-1 dark">[^<]*</div>\s*<div class="text-3 dark">(.*?)</div>', doc, re.S)
            intro = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
        acc = doc[doc.find('<div class="accordion">'):]
        for head, box in re.findall(r'<article>\s*<div class="handler[^"]*">(.*?)</div>\s*<div class="box listener">(.*?)</article>', acc, re.S):
            head = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", head))).strip()
            mm = re.match(r"(\w+)\s+(\d{4})", head)
            month = MONTHS.get(mm.group(1).lower()) if mm else None
            cnt = re.search(r"\((\d+)\s*verbetering", head)
            box = re.sub(r'(href|src|srcset)="(/[^"]*)"', lambda m: f'{m.group(1)}="{urljoin(FL_BASE, m.group(2))}"', box)
            box = re.sub(r'<p class="heading-2[^"]*">\s*Releasenotes\s*</p>', "", box)
            box = re.sub(r"<(/?)h1\b", r"<\1h2", box)  # h1 in een release (soms met alleen een afbeelding) niet weggooien
            c = htmlclean.Cleaner()
            c.feed(box)
            c.close()
            body = "".join(c.out)
            body = re.sub(r"(<br>\s*){3,}", "<br><br>", body)
            body = re.sub(r"<p>\s*(<br>\s*)*</p>", "", body)
            text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
            label = f"{mm.group(1).capitalize()} {mm.group(2)}" if mm else head
            out.append({"label": label, "head": head, "year": year, "month": month or 0,
                        "count": int(cnt.group(1)) if cnt else None, "html": body, "text": text,
                        "slug": f"{mm.group(2)}-{month:02d}" if month else slugify(head),
                        "src": f"{FL_BASE}/hoe-het-werkt/releasenotes/releasenotes-{year}/"})
    # Losse releases uit het helpcenter (tools/fastlane_sync.py): per maand gebundeld, alleen voor maanden die
    # (nog) niet op fastlane.hypotheekbond.nl staan.
    bestaand = {x["slug"] for x in out}
    per_maand = {}
    for f in sorted(glob.glob(os.path.join(FL_DIR, "artikelen", "*.json")), reverse=True):
        d = json.load(open(f, encoding="utf8"))
        slug = f'{d["year"]}-{d["month"]:02d}'
        if slug not in bestaand:
            per_maand.setdefault(slug, []).append(d)
    for slug, rel in per_maand.items():
        delen = []
        for d in rel:  # nieuwste release eerst
            kop = f'Release {d["datum"]}' + (f' ({d["count"]} wijzigingen)' if d["count"] else "")
            delen.append(f'<h2>{html.escape(kop)}</h2>{d["html"]}<p><a href="{html.escape(d["src"])}">Bekijk deze release in het helpcenter</a></p>')
        c = htmlclean.Cleaner()
        c.feed("".join(delen))
        c.close()
        body = "".join(c.out)
        y, m = slug.split("-")
        totaal = sum(d["count"] or 0 for d in rel) or None
        out.append({"label": f"{[k for k, v in MONTHS.items() if v == int(m)][0].capitalize()} {y}", "head": rel[0]["titel"],
                    "year": y, "month": int(m), "count": totaal, "html": body,
                    "text": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip(),
                    "slug": slug, "src": rel[0]["src"]})
    out.sort(key=lambda x: (x["year"], x["month"]), reverse=True)
    return out, intro


def fl_resolve(pg, h):
    def img(m):
        u = html.unescape(m.group(2))
        if u.startswith("/"):
            u = FL_BASE + u
        if u.startswith(FL_BASE + "/assets/"):
            stem = os.path.splitext(os.path.basename(u.split("?")[0]))[0]
            name = re.sub(r"\.\d+x\d+x\d+x\d+$", "", stem) + ".webp"  # verkleinde variant -> origineel
            if os.path.exists(os.path.join(FL_DIR, "img", name)):
                return f'{m.group(1)}="{pg.rel("bronnen/fastlane/img/" + name)}"'
        return f'{m.group(1)}="{esc(u)}"'
    h = re.sub(r'(src|href)="IMG:([^"]+)"', img, h)
    h = re.sub(r'href="SITE:([^"]*)"', lambda m: f'href="{esc(resolve_site(pg, html.unescape(m.group(1))))}"', h)
    return h


def fl_excerpt(t):
    t = re.sub(r"^📢\s*", "", t)
    t = re.sub(r"\[IT-\d+\]", "", t)
    return (t[:240].rsplit(" ", 1)[0] + "…") if len(t) > 240 else t


def render_fastlane():
    months, intro = fastlane_months()
    if not months:
        return
    pg = Page("releasenotes-hypotheekadvies")
    years = []
    for y in sorted({m["year"] for m in months}, reverse=True):
        cards = "".join(
            f'<article class="card"><h3><a href="{pg.rel("releasenotes-hypotheekadvies/" + m["slug"])}">Releasenotes {esc(m["label"])}</a></h3>'
            f'{f"<p class=\"date\">{m["count"]} verbeteringen</p>" if m["count"] else ""}'
            f'<p>{esc(fl_excerpt(m["text"]))}</p>'
            f'<a class="readmore" href="{pg.rel("releasenotes-hypotheekadvies/" + m["slug"])}">Lees verder</a></article>'
            for m in months if m["year"] == y)
        years.append(f'<h2 class="feed-h" id="jaar-{y}">{y}</h2><div class="cards">{cards}</div>')
    jump = " · ".join(f'<a href="#jaar-{y}">{y}</a>' for y in sorted({m["year"] for m in months}, reverse=True))
    body = f"""{crumbs(pg, [(FL_TITLE, None)])}
<main class="feed"><div class="wrap">
  {rn_tabs(pg, "hypotheekadvies")}
  <h1>{esc(FL_TITLE)}</h1>
  <p class="lead">{esc(intro)}</p>
  <p class="jump">Ga naar: {jump}</p>
  {"".join(years)}
  <p class="src">Bron: <a href="{FL_BASE}/hoe-het-werkt/releasenotes/" target="_blank" rel="noopener">fastlane.hypotheekbond.nl</a></p>
</div></main>"""
    write("releasenotes-hypotheekadvies", layout(pg, FL_TITLE, body, "releasenotes", intro))
    for i, m in enumerate(months):
        path = "releasenotes-hypotheekadvies/" + m["slug"]
        pg = Page(path)
        others = "".join(f'<li><a href="{pg.rel("releasenotes-hypotheekadvies/" + o["slug"])}">{esc(o["label"])}</a></li>'
                         for o in months[max(0, i - 4):i + 6] if o is not m)
        nav = []
        if i + 1 < len(months):
            nav.append(f'<a href="{pg.rel("releasenotes-hypotheekadvies/" + months[i + 1]["slug"])}">« {esc(months[i + 1]["label"])}</a>')
        if i > 0:
            nav.append(f'<a href="{pg.rel("releasenotes-hypotheekadvies/" + months[i - 1]["slug"])}">{esc(months[i - 1]["label"])} »</a>')
        body = f"""{crumbs(pg, [(FL_TITLE, "releasenotes-hypotheekadvies"), (m["label"], None)])}
<main class="article"><div class="wrap cols">
  <article>
    <h1>Releasenotes eBlinqx Hypotheekadvies – {esc(m["label"])}</h1>
    {f'<p class="meta">{m["count"]} verbeteringen</p>' if m["count"] else ""}
    <div class="content flnotes">{fl_resolve(pg, m["html"])}</div>
    <p class="pager">{" &nbsp; ".join(nav)}</p>
    <p class="src">Bron: <a href="{esc(m["src"])}" target="_blank" rel="noopener">{"helpcenter eBlinqx Hypotheekadvies" if "support-fastlane" in m["src"] else "fastlane.hypotheekbond.nl"}</a></p>
  </article>
  <aside class="related"><h2>Andere maanden:</h2><ul>{others}</ul><p><a href="{pg.rel("releasenotes-hypotheekadvies")}">Alle releasenotes »</a></p></aside>
</div></main>"""
        write(path, layout(pg, f'Releasenotes {m["label"]} – eBlinqx Hypotheekadvies', body, "releasenotes", fl_excerpt(m["text"])))


# Releasenotes per dienst (zoals verzekeringhypotheek.blinqx.tech/releasenotes): tabjes bovenaan elke releasenotespagina
RN_DIENSTEN = [
    ("connect", "eBlinqx Connect", "releasenotes", None),
    ("hypotheekadvies", "Hypotheekadvies (Fastlane)", "releasenotes-hypotheekadvies", None),
    ("adviesbox", "Adviesbox", "releasenotes-adviesbox", "https://support.adviesbox.nl/portal/nl/kb/articles/releasenotes"),
    ("finconnect", "FinConnect", "releasenotes-finconnect", None),
    ("finly", "Finly", "releasenotes-finly", "https://blinqx.finly.nl/releases"),
    ("dias", "DIAS Assurantie", "releasenotes-dias", None),
]
RN_INTRO = {
    "adviesbox": ("De releasenotes van Adviesbox staan in het supportportaal van Adviesbox. Daar vind je per versie welke "
                  "verbeteringen en nieuwe functies zijn doorgevoerd."),
    "finly": ("De releasenotes van Finly (CRM) staan in Finly zelf. Je moet daarvoor eerst inloggen met je Blinqx-account "
              "(single sign-on)."),
    "finconnect": "Een overzicht met de meest recente updates binnen FinConnect (slimme formulieren en naverrekenen).",
    "dias": "Releasenotes van DIAS Assurantie en DIAS Cloud (volmacht en provinciaal).",
}
RN_OVERIG_DIR = os.path.join(SRC, "releasenotes-overig")


def rn_tabs(pg, actief):
    items = "".join(
        f'<a class="rn-tab{" actief" if k == actief else ""}" href="{pg.rel(pad)}"{" aria-current=\"page\"" if k == actief else ""}>{esc(naam)}</a>'
        for k, naam, pad, _ in RN_DIENSTEN)
    return f'<nav class="rn-tabs" aria-label="Releasenotes per dienst">{items}</nav>'


def rn_overig():
    """Releasenotes van FinConnect en DIAS (bronnen/releasenotes-overig/*.json), nieuwste eerst."""
    uit = {}
    for f in sorted(glob.glob(os.path.join(RN_OVERIG_DIR, "*.json"))):
        d = json.load(open(f, encoding="utf8"))
        c = htmlclean.Cleaner()
        c.feed(d["html"])
        c.close()
        d["body"] = "".join(c.out)
        d["text"] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", d["body"]))).strip()
        uit.setdefault(d["dienst"], []).append(d)
    for v in uit.values():
        v.sort(key=lambda d: d["iso"], reverse=True)
    return uit


def render_releasenotes_overig():
    data = rn_overig()
    for k, naam, pad, extern in RN_DIENSTEN:
        if k in ("connect", "hypotheekadvies"):
            continue
        pg = Page(pad)
        titel = f"Releasenotes {naam}"
        items = data.get(k, [])
        if extern:
            inhoud = (f'<p class="lead">{esc(RN_INTRO[k])}</p>'
                      f'<p><a class="btn-out" href="{esc(extern)}" target="_blank" rel="noopener">Bekijk de releasenotes van {esc(naam)}</a></p>')
        else:
            cards = "".join(
                f'<article class="card"><h3><a href="{pg.rel(pad + "/" + d["slug"])}">{esc(d["titel"])}</a></h3>'
                f'<p class="date">{esc(d["datum"])}</p><p>{esc(fl_excerpt(d["text"]))}</p>'
                f'<a class="readmore" href="{pg.rel(pad + "/" + d["slug"])}">Lees verder</a></article>' for d in items)
            inhoud = f'<p class="lead">{esc(RN_INTRO.get(k, ""))}</p><div class="cards">{cards}</div>'
        body = f"""{crumbs(pg, [(titel, None)])}
<main class="feed"><div class="wrap">
  {rn_tabs(pg, k)}
  <h1>{esc(titel)}</h1>
  {inhoud}
  <p class="src">Overzicht van alle diensten: <a href="https://verzekeringhypotheek.blinqx.tech/releasenotes" target="_blank" rel="noopener">verzekeringhypotheek.blinqx.tech/releasenotes</a></p>
</div></main>"""
        write(pad, layout(pg, titel, body, "releasenotes", RN_INTRO.get(k, titel)))
        for d in items:
            ap = pad + "/" + d["slug"]
            pg = Page(ap)
            dl = (f'<p><a class="btn-out" href="{pg.rel(d["bestand"])}">Download het originele document</a></p>'
                  if d.get("bestand") else "")
            body = f"""{crumbs(pg, [(titel, pad), (d["datum"], None)])}
<main class="article"><div class="wrap cols">
  <article>
    {rn_tabs(pg, k)}
    <h1>{esc(d["titel"])}</h1>
    <p class="meta">{esc(d["datum"])}</p>
    <div class="content flnotes">{raw_to_html(pg, d["body"])[0]}</div>
    {dl}
    <p class="src">Bron: <a href="{esc(d["src"])}" target="_blank" rel="noopener">verzekeringhypotheek.blinqx.tech</a></p>
  </article>
  <aside class="related"><h2>Releasenotes {esc(naam)}</h2><ul>{"".join(f'<li><a href="{pg.rel(pad + "/" + o["slug"])}">{esc(o["titel"])}</a></li>' for o in items)}</ul></aside>
</div></main>"""
            write(ap, layout(pg, d["titel"], body, "releasenotes", fl_excerpt(d["text"])))


def render_trainingen():
    """Trainingen: actueel aanbod van de Blinqx Academy (bronnen/academy, via tools/academy_ophalen.py)."""
    f = os.path.join(SRC, "academy", "trainingen.json")
    if not os.path.exists(f):
        return
    data = json.load(open(f, encoding="utf8"))
    pg = Page("trainingen")
    d = date.fromisoformat(data["opgehaald"])
    cards = []
    for t in data["trainingen"]:
        chips = "".join(f'<span class="chip">{esc(m)}</span>' for m in t["meta"])
        labels = "".join(f'<span class="tlabel">{esc(l)}</span>' for l in t["labels"])
        img = f'<img src="{pg.rel("bronnen/academy/" + t["img"])}" alt="" loading="lazy">' if t["img"] else ""
        cards.append(f'<a class="training" href="{esc(t["url"])}" target="_blank" rel="noopener">'
                     f'<span class="timg">{img}{f"<span class=tlabels>{labels}</span>" if labels else ""}</span>'
                     f'<span class="tbody"><span class="ttitle">{esc(t["t"])}</span><span class="chips">{chips}</span>'
                     f'<span class="tmore">Bekijk en meld je aan ↗</span></span></a>')
    body = f"""{crumbs(pg, [("Trainingen", None)])}
<main class="subpage"><div class="wrap">
  <h1>Trainingen</h1>
  <p class="lead">Haal meer uit de software met een training van de Blinqx Academy: van een korte online kennismaking tot een volledige basistraining op locatie. Data, prijzen en aanmelden vind je in de Academy.</p>
  <p><a class="btn-out cta" href="{esc(data["bron"])}" target="_blank" rel="noopener">Naar de Blinqx Academy ↗</a></p>
  <div class="tgrid">{"".join(cards)}</div>
  <p class="note">Liever direct zelf aan de slag? Bekijk de <a href="{pg.rel("elearning")}">e-learnings</a> en <a href="{pg.rel("video")}">video's</a>.</p>
  <p class="src">Overzicht van het trainingsaanbod op {fmt_date(d)}; het actuele aanbod staat in de <a href="{esc(data["bron"])}" target="_blank" rel="noopener">Blinqx Academy</a>.</p>
</div></main>"""
    write("trainingen", layout(pg, "Trainingen", body, "trainingen",
                               "Trainingen voor eBlinqx, Adviesbox en Financiële Planner bij de Blinqx Academy."))


def render_procesversneller():
    """Procesversneller-uitleg (bronnen/procesversneller.html, eigen opmaak) als losse pagina met een terugbalk."""
    f = os.path.join(SRC, "procesversneller.html")
    if not os.path.exists(f):
        return
    pg = Page("procesversneller")
    doc = open(f, encoding="utf8").read()
    # links naar de oude supportsite -> deze site (absoluut, zodat ze ook in de afgedrukte brochure werken)
    doc = re.sub(r"https://support\.fasterforward\.nl/((?:kennisbank/)?[a-z0-9-]+/)",
                 lambda m: SITE_URL + m.group(1) if os.path.isdir(os.path.join(ROOT, m.group(1))) else m.group(0), doc)
    bar = (f'<div class="pv-bar" style="background:#111;padding:8px 16px;font:14px/1.4 \'Open Sans\',system-ui,sans-serif">'
           f'<a href="{pg.rel("")}" style="color:#FFCD00;text-decoration:none;font-weight:600">← Blinqx Support</a>'
           f'<span style="color:#bbb"> &nbsp;·&nbsp; </span><a href="{pg.rel("kennisbank/ockto-koppeling")}" style="color:#fff">Ockto-koppeling in de kennisbank</a></div>')
    i = doc.rfind("</style>", 0, doc.find("<main")) + len("</style>")
    doc = doc[:i] + "\n" + bar + doc[i:]
    title = "Procesversneller: alles op een rij"
    desc = "Hoe werkt de Procesversneller in eBlinqx: brondata ophalen via Ockto, wat het je kantoor oplevert en antwoorden op veelgestelde vragen."
    head = ('<!doctype html>\n<html lang="nl">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<link rel="icon" href="{pg.rel("assets/favicon.png")}">\n{head_meta(pg, title, desc)}\n'
            '<style>html,body{margin:0;padding:0}</style>\n')
    doc = re.sub(r"<title>[^<]*</title>", f"<title>{esc(title)} - Blinqx Support</title>\n</head>\n<body>", doc, count=1)
    # deze pagina noemt zelf al beide namen (Online klantportaal / UwKluis): niet automatisch aanvullen
    write("procesversneller", head + doc + "\n</body>\n</html>\n", kluis=False)


MHZ_URL = "https://aansluiten.mijnhuiszaken.nl/"
MHZ_INTRO = ("MijnHuiszaken is een online klantomgeving voor hypotheekadviseurs en makelaars. Je klant vindt er het actuele "
             "woningaanbod van NVM-makelaars, e-mailalerts, rekentools en de geschatte waarde van zijn eigen woning. "
             "De klant gaat zelf aan de slag, en jij blijft al vanaf de oriëntatie in beeld.")


YES_URL = "https://www.yes-co.nl/"
YES_INTRO = ("Yes-co is CRM-software voor makelaars: objecten en relaties beheren en woningen publiceren naar Funda en meer dan "
             "twintig andere woningsites, voor een vast en laag maandbedrag. Met koppelingen naar MijnHuiszaken, hypotheektools en "
             "digitaal ondertekenen werkt de makelaar nauw samen met de hypotheekadviseur.")


def render_yesco():
    """Yes-co: makelaarssoftware (bron: www.yes-co.nl, november 2026)."""
    pg = Page("yes-co")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/yes-co/" + f)}" alt="{esc(alt)}" loading="lazy">'
    voordelen = [
        ("Uitgebreid CRM voor makelaars", "Objecten en relaties beheren, overzichten, templates, exports, agenda en factuurregels, "
         "in de eigen huisstijl van je kantoor. Geschikt voor meerdere gebruikers en vestigingen met verschillende toegangsniveaus."),
        ("Publiceren naar 20+ kanalen", "Per object kies je naar welke kanalen je publiceert, of je publiceert in één keer naar alle "
         "gekoppelde kanalen: NVM/Funda, Funda in Business, Pararius, Huislijn, Huispedia, MijnHuiszaken, Woningbond en meer."),
        ("Samenwerken met de hypotheekadviseur", "Via MijnHuiszaken zoeken klanten woningen en delen ze documenten met makelaar en "
         "adviseur. Hypotheektools op de website laten bezoekers direct zien welke woningen financieel haalbaar zijn."),
        ("Digitaal ondertekenen en Wwft", "Koop- en huurakte wizard, digitaal ondertekenen, een digitaal opleveringsrapport en "
         "geïntegreerde Wwft- en UBO-checks."),
        ("Nieuwbouw en projecten", "Met de projectmodules beheren makelaars en projectontwikkelaars nieuwbouw- en uitpondprojecten "
         "van A tot Z, inclusief overzichten van geïnteresseerden, optanten en de status van bouwnummers."),
        ("Betalen wat je gebruikt", "Een volledig CRM voor een vast maandbedrag; extra functionaliteit en publicatiekanalen zet je "
         "aan via de App Market en betaal je alleen als je ze gebruikt."),
    ]
    blokken = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in voordelen)
    voor_wie = [("Startende makelaars en zzp’ers", "startende-makelaars"), ("Grote makelaarskantoren", "grote-makelaarskantoren"),
                ("Projectontwikkelaars", "projectontwikkelaars"), ("Vastgoedbeheerders", "vastgoedbeheerders")]
    wie = "".join(f'<a class="wtbtn" href="{YES_URL}{u}/" target="_blank" rel="noopener">{esc(t)} <span aria-hidden="true">↗</span></a>' for t, u in voor_wie)
    pakket = ["Funda-koppeling", "Object- en relatiebeheer", "Overzichten", "Koop- en huurakte wizard", "Templates en snel printen",
              "Exports", "Digitaal opleveringsrapport", "Agenda", "Digitaal samenwerken via MijnHuiszaken.nl", "Factuurregels",
              "Gratis vermelding op Makelaarsbond.nl", "Gratis woningen publiceren op Woningbond.nl"]
    li = "".join(f"<li>{esc(x)}</li>" for x in pakket)
    faq = [
        ("Wat is Yes-co?", YES_INTRO),
        ("Wat heeft een hypotheekadviseur aan Yes-co?",
         "Werk je samen met een makelaar die Yes-co gebruikt, of heb je zelf makelaars in dienst, dan deel je klanten, woningen en "
         "documenten via MijnHuiszaken en de hypotheektools. Vanuit eBlinqx Connect kun je bovendien klantgegevens naar Yes-co exporteren."),
        ("Wat kost Yes-co?",
         "Er zijn twee abonnementen, Pro en Pro Plus, vanaf € 75 per maand (volgens yes-co.nl, november 2026). Extra functionaliteit en "
         "publicatiekanalen betaal je alleen als je ze gebruikt."),
        ("Wat kosten de hypotheektools van Yes-co?",
         "De volledige hypotheek toolset (zes rekentools) kost € 80 per maand en is per maand opzegbaar."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Makelaar Software: Yes-co", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Makelaar Software: Yes-co</h1>
  <p class="lead">Hét CRM-systeem voor de makelaar: werk op jouw manier, met volledige vrijheid, voor een vast en laag maandbedrag.</p>
  <div class="mhz-intro"><div><p>{esc(YES_INTRO)}</p>
    <p class="btn-row"><a class="btn-out cta" href="{YES_URL}contact/" target="_blank" rel="noopener">Gratis demo aanvragen</a>
    <a class="btn-out" href="https://login.yes-co.com/" target="_blank" rel="noopener">Inloggen in Yes-co</a></p></div>
    <figure>{img("crm-apparaten.webp", "Yes-co op laptop, tablet en telefoon")}</figure></div>
  <h2 class="wth">Daarom kiezen kantoren voor Yes-co</h2>
  <div class="wtwhys">{blokken}</div>
  <div class="mhz-duo">
    <div><h2 class="wth">Publiceren naar alle kanalen</h2>
      <p>Via Yes-co publiceer je objecten naar diverse marketingkanalen, inclusief je eigen website. Per object kies je de kanalen, of je publiceert, trekt in of meldt af bij alle gekoppelde kanalen in één keer. Kanalen activeer en deactiveer je zelf, en er komen regelmatig nieuwe koppelingen bij.</p></div>
    <figure>{img("mcp-kanalen-new.webp", "Logo's van publicatiekanalen: Woningbond, MijnHuiszaken, Makelaarsbond, Huislijn, Funda, Pararius, Huispedia en meer")}</figure>
  </div>
  <div class="mhz-duo">
    <figure>{img("projecten.webp", "Schermen van de projectmodule in Yes-co")}</figure>
    <div><h2 class="wth">Projecten en nieuwbouw</h2>
      <p>Met de module Nieuwbouw Project beheer je als projectontwikkelaar of makelaar al je nieuwbouwprojecten en werk je geautomatiseerd samen met ontwikkelaar, makelaar en consument. Voor het uitponden van huurcomplexen gebruik je de module Bestaande Bouw Project. Dossier-, archief- en sleutelnummers worden automatisch toegekend.</p></div>
  </div>
  <div class="mhz-duo">
    <div><h2 class="wth">Digitaal ondertekenen</h2>
      <p>Maak koop- en huurcontracten met de wizard, altijd volgens de laatste regels, en laat ze met één druk op de knop digitaal ondertekenen. Met het digitaal opleveringsrapport en de geïntegreerde Wwft- en UBO-checks heb je alles in één systeem.</p></div>
    <figure>{img("tvv-ondertekenen.webp", "Digitaal ondertekenen op een tablet")}</figure>
  </div>
  <h2 class="wth">Voor wie?</h2>
  <div class="wtbtns">{wie}</div>
  <h2 class="wth">Abonnementen</h2>
  <div class="mhz-duo"><div class="mhz-prijs"><p class="mhz-bedrag">vanaf € 75,- <small>per maand</small></p>
    <p><strong>Yes-co Pro</strong> (max. 10 gebruikers) en <strong>Yes-co Pro Plus</strong> (onbeperkt aantal gebruikers, plus website-responseformulieren en Mailchimp-koppeling). Beide met:</p>
    <ul>{li}</ul>
    <p><a class="btn-out cta" href="{YES_URL}prijs/" target="_blank" rel="noopener">Bekijk de prijzen</a></p></div>
    <figure>{img("app-market.webp", "De Yes-co App Market met extra functionaliteiten")}<figcaption>Extra functies en kanalen zet je aan via de App Market.</figcaption></figure></div>
  <h2 class="wth" id="tools-voor-vastgoed">Tools voor vastgoed</h2>
  <p>Yes-co is samen met De Nationale Hypotheekbond het initiatief <a href="{pg.rel("tools-voor-vastgoed")}">Tools voor vastgoed</a>: vastgoed publiceren, een online klantdossier, rekentools voor je website en woningwaarderapporten. <a href="{pg.rel("tools-voor-vastgoed")}">Bekijk alle tools en prijzen</a>.</p>
  <p class="mhz-tip">Werk je als hypotheekadviseur samen met een makelaar? Combineer Yes-co met <a href="{pg.rel("mijnhuiszaken")}">MijnHuiszaken</a> en de <a href="{pg.rel("websitetools")}">websitetools</a>, en lees hoe je <a href="{pg.rel("kennisbank/gemakkelijk-klantgegevens-exporteren-naar-yes-co")}">klantgegevens vanuit eBlinqx Connect naar Yes-co exporteert</a>.</p>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <h2 class="wth">Meer weten?</h2>
  <p>Vraag een vrijblijvende online demo aan via <a href="{YES_URL}contact/" target="_blank" rel="noopener">yes-co.nl</a>, mail <a href="mailto:info@yes-co.nl">info@yes-co.nl</a> of bel <a href="tel:+31365238455">036 523 84 55</a>.</p>
  <p class="src">Bron: <a href="{YES_URL}" target="_blank" rel="noopener">www.yes-co.nl</a> (stand 4 november 2026). Prijzen en voorwaarden kunnen wijzigen.</p>
</div></main>"""
    write("yes-co", layout(pg, "Makelaar Software: Yes-co", body, None,
                           "Yes-co: CRM-software voor makelaars. Objecten en relaties beheren, publiceren naar Funda en 20+ woningsites, "
                           "digitaal ondertekenen, Wwft-checks en samenwerken met de hypotheekadviseur via MijnHuiszaken."))


ABS_URL = "https://www.actiefbeheerscan.nl/"
ABS_INTRO = ("Actiefbeheerscan is een tool voor nazorg, klantbeheer en leads van Blinqx Verzekering & Hypotheek. Je stuurt je "
             "klant een uitnodiging voor een digitaal formulier, de klant vult zijn actuele situatie in en jij ziet direct waar "
             "verbeteringen of besparingen mogelijk zijn.")
ABS_FORMULIEREN = [
    ("Jaarlijkse nazorg", "yearly", "PzSDxcFYAsLw6jCq", "Periodieke check van de situatie van je klant."),
    ("Status hypotheek", "house", "GlYSvar7ShpvgOdk", "Past de hypotheek nog bij de situatie en wensen van je klant?"),
    ("Extra aflossen?", "aflossingsvrij", "bBPNYc7RHSPSaU9g", "Inventariseer of je klant wil of kan aflossen."),
    ("Gerust met pensioen?", "retirement", "dKQGiagOZA1wjcEl", "Breng de pensioenwensen en -situatie in kaart."),
    ("Overlijdensrisico", "orv", "YeGIdMf9qGpZvKtW", "Controleer of de dekking nog aansluit."),
    ("Uitvaartverzekering", "funeral", "EdvsaUPDAl10ANAi", "Check de uitvaartdekking van je klant."),
    ("Schadeverzekering", "injury", "C2X3Ldey3KEre5cV", "Actualiseer de gegevens voor de schadeverzekeringen."),
    ("Bedrijfsverzekering", "business-2", "AtfDGyjfOkO5mwAE", "Nazorg voor zakelijke klanten."),
    ("Autoverzekering", "car", "FmvJRpOQLjHWpCfP", "Klopt de autoverzekering nog met de situatie?"),
    ("Klanttevredenheid", "customer", "pmIZrVhGuf00mDkj", "Meet hoe tevreden je klanten zijn."),
]


def render_actiefbeheerscan():
    """Actiefbeheerscan: digitale formulieren voor nazorg en beheer (bron: www.actiefbeheerscan.nl, november 2026)."""
    pg = Page("actiefbeheerscan")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/actiefbeheerscan/" + f)}" alt="{esc(alt)}" loading="lazy">'
    voordelen = [
        ("Eenvoud", "Start met Actiefbeheerscan zonder enige technische kennis. De digitale formulieren worden volledig voor je "
         "ingericht en afgestemd op je kantoor."),
        ("Flexibiliteit", "Richt Actiefbeheerscan in zoals dat past binnen jouw organisatie. Pas de templates naar eigen inzicht "
         "aan of stel zelf nieuwe formulieren samen."),
        ("Veilig & zeker", "Ontvang en bewaar actuele klantgegevens op een veilige wijze."),
        ("Nazorg op de automatische piloot", "Verstuur uitnodigingen in één keer, eventueel met een automatische reminder. Zo "
         "voldoe je eenvoudig aan je periodieke nazorg en houd je meer tijd over voor het gesprek met je klant."),
        ("Leads uit je bestaande klanten", "Bestaande klanten zijn je meest waardevolle bezit. De antwoorden laten zien waar "
         "een hypotheek, pensioen of verzekering niet meer past: aanleiding voor een nieuw gesprek."),
        ("Ook op je website", "Je gebruikt de formulieren onbeperkt op je eigen website, zodat ook bezoekers hun situatie aan "
         "je doorgeven."),
    ]
    blokken = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in voordelen)
    stappen = [
        ("Stuur een uitnodigingsmail", "Stuur via het systeem een uitnodigingsmail naar de klant met een toelichting op het "
         "formulier en het belang daarvan. Eventueel met automatische reminder."),
        ("De klant vult het digitale formulier in", "De klant doorloopt het formulier en vult actuele informatie in over zijn "
         "of haar situatie."),
        ("Vind verbeteringen of besparingen", "Je krijgt hiervan bericht en hebt direct inzicht in mogelijke verbeteringen "
         "of besparingen."),
    ]
    stap_html = "".join(f"<li><strong>{esc(t)}</strong><br>{esc(x)}</li>" for t, x in stappen)
    forms = "".join(
        f'<a class="abs-form" href="https://formulier.actiefbeheerscan.nl/s/{code}" target="_blank" rel="noopener">'
        f'<img src="{pg.rel("bronnen/actiefbeheerscan/" + ic + ".svg")}" alt="" loading="lazy">'
        f'<span><strong>{esc(t)}</strong><small>{esc(x)}</small><em>Bekijk formulier ›</em></span></a>'
        for t, ic, code, x in ABS_FORMULIEREN)
    faq = [
        ("Wat is Actiefbeheerscan?", ABS_INTRO),
        ("Welke digitale formulieren zijn er?",
         "Er zijn templates voor jaarlijkse nazorg, status hypotheek, extra aflossen, pensioen, overlijdensrisico, "
         "uitvaartverzekering, schadeverzekering, bedrijfsverzekering, autoverzekering en klanttevredenheid. Je past ze naar "
         "eigen inzicht aan en kunt ook eigen formulieren toevoegen."),
        ("Heb ik technische kennis nodig?",
         "Nee. De digitale formulieren worden volledig voor je ingericht en afgestemd op je kantoor."),
        ("Wat kost Actiefbeheerscan?",
         "€ 39,- per maand plus eenmalig € 159,- inrichtingskosten. Daarvoor verstuur je 1.000 formulieren per maand, gebruik je "
         "de formulieren onbeperkt op je website en stel je zelf formulieren samen (tarief volgens actiefbeheerscan.nl, "
         "november 2026)."),
        ("Bij wie kan ik terecht met vragen?",
         "Voor ondersteuning bij het maken of koppelen van formulieren: 085 401 16 71 (maandag t/m vrijdag 09:00–17:30) of "
         "service@dutchmedialab.nl. Voor informatie en een demo: relatie-vh@blinqx.tech of 020 758 21 11."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Actiefbeheerscan", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Actiefbeheerscan</h1>
  <p class="lead">Jouw klanten ontzorgen, nu en in de toekomst: eenvoudige nazorg, beheer en leads met digitale formulieren.</p>
  <div class="mhz-intro"><div><p>{esc(ABS_INTRO)}</p>
    <p>Bestaande klanten zijn je meest waardevolle bezit. Met Actiefbeheerscan geef je periodieke nazorg snel en gemakkelijk invulling, zorg je voor een positieve klantervaring en houd je meer tijd over om met je klant in gesprek te gaan.</p>
    <p class="btn-row"><a class="btn-out cta" href="{ABS_URL}contact/" target="_blank" rel="noopener">Demo aanvragen</a>
    <a class="btn-out" href="https://formulier.actiefbeheerscan.nl/login" target="_blank" rel="noopener">Inloggen</a></p></div>
    <figure>{img("header.webp", "Digitaal formulier van Actiefbeheerscan op laptop en telefoon")}</figure></div>
  <h2 class="wth">Waarom Actiefbeheerscan?</h2>
  <div class="wtwhys">{blokken}</div>
  <div class="mhz-duo">
    <div><h2 class="wth">Hoe werkt Actiefbeheerscan?</h2><ol class="abs-stappen">{stap_html}</ol></div>
    <figure>{img("resultaat.webp", "Tevreden adviseur")}</figure>
  </div>
  <h2 class="wth" id="digitale-formulieren">De digitale formulieren</h2>
  <p>Je kunt de templates naar eigen inzicht aanpassen en eigen formulieren toevoegen. Bekijk de voorbeelden:</p>
  <div class="abs-forms">{forms}</div>
  <p class="mhz-tip">Let op: dit zijn voorbeeldformulieren. Wat je hier invult, komt niet bij een adviseur terecht.</p>
  <h2 class="wth">Tarieven</h2>
  <div class="mhz-prijs"><p class="mhz-bedrag">€ 39,- <small>per maand</small></p>
    <ul><li>1.000 formulieren per maand versturen</li><li>Onbeperkt gebruik op je website</li><li>Toegang tot de digitale formulieren</li><li>Zelf digitale formulieren samenstellen</li></ul>
    <p>Eenmalige inrichtingskosten: € 159,-</p>
    <p><a class="btn-out cta" href="{ABS_URL}contact/" target="_blank" rel="noopener">Neem contact op</a></p></div>
  <p class="mhz-tip">Tip: combineer Actiefbeheerscan met de <a href="{pg.rel("websitetools")}">websitetools</a> en <a href="{pg.rel("mijnhuiszaken")}">MijnHuiszaken</a>. Zo houd je zowel nieuwe als bestaande klanten in beeld.</p>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <h2 class="wth">Contact</h2>
  <p><strong>Ondersteuning</strong> bij het maken van een digitaal formulier of het koppelen van Actiefbeheerscan: bel <a href="tel:+31854011671">085 401 16 71</a> (maandag t/m vrijdag 09:00–17:30) of mail <a href="mailto:service@dutchmedialab.nl">service@dutchmedialab.nl</a>.</p>
  <p><strong>Informatie en demo:</strong> neem contact op met Milan Akavia (<a href="mailto:milan.akavia@blinqx.tech">milan.akavia@blinqx.tech</a>) of Jeroen Oversteegen (<a href="mailto:jeroen.oversteegen@blinqx.tech">jeroen.oversteegen@blinqx.tech</a>), mail <a href="mailto:relatie-vh@blinqx.tech">relatie-vh@blinqx.tech</a>, bel <a href="tel:+31207582111">020 758 21 11</a> of kijk op <a href="{ABS_URL}contact/" target="_blank" rel="noopener">actiefbeheerscan.nl/contact</a>.</p>
  <p class="src">Bron: <a href="{ABS_URL}" target="_blank" rel="noopener">www.actiefbeheerscan.nl</a> (stand 4 november 2026). Tarieven en voorwaarden kunnen wijzigen.</p>
</div></main>"""
    write("actiefbeheerscan", layout(pg, "Actiefbeheerscan: digitale formulieren voor nazorg en beheer", body, None,
                                     "Actiefbeheerscan: eenvoudige nazorg, klantbeheer en leads met digitale formulieren voor "
                                     "hypotheek, pensioen en verzekeringen. € 39 per maand, volledig voor je ingericht."))


HRA_URL = "https://www.hypotheekrente-app.nl/"
HRA_INTRO = ("De Hypotheekrente-app van De Nationale Hypotheekbond zet alle actuele hypotheekrentes bij de hand: dagelijks "
             "bijgewerkt, van variabel tot 30 jaar vast, van alle actieve en inactieve geldverstrekkers. De app is gratis te "
             "downloaden in de App Store en Google Play, en is ook verkrijgbaar als eigen app in de look & feel van je kantoor.")
HRA_TOOLS = [
    ("Renteoverzicht met rentevergelijker", "https://consumenten.hypotheekbond.nl/rekentools/hypotheekrente-overzicht-met-rentevergelijker/"),
    ("Renteoverzicht", "https://consumenten.hypotheekbond.nl/rekentools/hypotheekrente-overzicht/"),
    ("Maximale hypotheek", "https://consumenten.hypotheekbond.nl/rekentools/bereken-je-maximale-hypotheek/"),
    ("Oversluitcheck", "https://consumenten.hypotheekbond.nl/rekentools/hypotheekcheck-bespaarcheck/"),
    ("Kan ik deze woning kopen?", "https://consumenten.hypotheekbond.nl/rekentools/kan-ik-deze-woning-kopen/"),
    ("Maandlast berekenen", "https://consumenten.hypotheekbond.nl/rekentools/maandlasten-hypotheek-berekenen/"),
    ("Woningwaarde berekenen", "http://www.rwwr.nl/woningwaarderapport/"),
    ("ORV-premie berekenen", "https://consumenten.hypotheekbond.nl/rekentools/kan-ik-besparen-op-mijn-overlijdensrisico-verzekering/"),
]


def render_hypotheekrenteapp():
    """Hypotheekrente-app van De Nationale Hypotheekbond (bron: www.hypotheekrente-app.nl, november 2026)."""
    pg = Page("hypotheekrente-app")
    voordelen = [
        ("Altijd actueel", "De rentes worden elke dag bijgewerkt."),
        ("Alle rentes", "Van variabel tot 30 jaar vast: alles is in één oogopslag inzichtelijk."),
        ("Alle geldverstrekkers", "Zowel actieve als inactieve geldverstrekkers worden getoond."),
        ("Gratis voor je klant", "De app is gratis te downloaden voor iPhone en Android."),
        ("In je eigen huisstijl", "Wil je een eigen app met actuele rentetarieven? Die is te krijgen in de look & feel van je "
         "kantoor, zodat je klant jouw naam ziet bij elke renteberekening."),
        ("Reden voor contact", "Rente is hét moment om met je klant in gesprek te gaan: bij een renteverlenging, oversluiten "
         "of een aankoop. Met de app blijf jij het aanspreekpunt."),
    ]
    blokken = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in voordelen)
    tools = "".join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(t)}</a></li>' for t, u in HRA_TOOLS)
    faq = [
        ("Wat is de Hypotheekrente-app?", HRA_INTRO),
        ("Hoe vaak worden de rentes bijgewerkt?", "Elke dag."),
        ("Kan ik de app in mijn eigen huisstijl krijgen?",
         "Ja, de app is beschikbaar in de look & feel van je eigen kantoor. Neem contact op voor de mogelijkheden en kosten."),
        ("Waar download ik de app?", "Gratis in de App Store (iPhone) en Google Play (Android)."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Hypotheekrente-app", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Hypotheekrente-app</h1>
  <p class="lead">Alle actuele rentetarieven bij de hand, voor jou en je klant.</p>
  <div class="mhz-intro"><div><p>{esc(HRA_INTRO)}</p>
    <p class="btn-row"><a class="btn-out cta" href="https://apps.apple.com/nl/app/hypotheekbond/id1047122249" target="_blank" rel="noopener">Download in de App Store</a>
    <a class="btn-out" href="https://play.google.com/store/apps/details?id=nl.hypotheekbond.renteoverzicht" target="_blank" rel="noopener">Download in Google Play</a></p></div>
    <figure><img src="{pg.rel("bronnen/hypotheekrente-app/mockup.webp")}" alt="De Hypotheekrente-app op een telefoon met het renteoverzicht" loading="lazy"></figure></div>
  <h2 class="wth">Waarom de Hypotheekrente-app?</h2>
  <div class="wtwhys">{blokken}</div>
  <p class="mhz-tip">Let op: de rentes in de app zijn indicatief en geen aanbod of advies. De werkelijke rente hangt af van de situatie van je klant en de voorwaarden van de geldverstrekker.</p>
  <h2 class="wth">Een eigen app met actuele rentetarieven?</h2>
  <p>Neem contact op voor een app in de look & feel van je kantoor: mail <a href="mailto:hello@blinqx.tech">hello@blinqx.tech</a>, bel <a href="tel:+31207582111">020 758 21 11</a> of gebruik het contactformulier op <a href="{HRA_URL}" target="_blank" rel="noopener">hypotheekrente-app.nl</a>.</p>
  <h2 class="wth">Meer tools van De Nationale Hypotheekbond</h2>
  <p>Tools voor consumenten die je eenvoudig op je website integreert (zie ook <a href="{pg.rel("websitetools")}">Websitetools</a>):</p>
  <ul>{tools}</ul>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <p class="src">Bron: <a href="{HRA_URL}" target="_blank" rel="noopener">www.hypotheekrente-app.nl</a> (stand 4 november 2026).</p>
</div></main>"""
    write("hypotheekrente-app", layout(pg, "Hypotheekrente-app: alle actuele rentes bij de hand", body, None,
                                       "De gratis Hypotheekrente-app van De Nationale Hypotheekbond: dagelijks bijgewerkte "
                                       "hypotheekrentes van alle geldverstrekkers, ook als app in je eigen huisstijl."))


TVV_URL = "https://www.toolsvoorvastgoed.nl/"
TVV_INTRO = ("Tools voor vastgoed is een initiatief van Yes-co en De Nationale Hypotheekbond: slimme online tools voor álle "
             "vastgoedprofessionals. Een vastgoed-CRM, een online klantomgeving, rekentools, geautomatiseerde woningwaarderapporten "
             "en je eigen vastgoedwebsite, om efficiënt en kostenbewust te werken en je klant tegelijk een optimale beleving te bieden.")
TVV_TOOLS = [("Bereken de maandlasten", "maandlasten-berekenen"), ("Kan ik deze woning kopen?", "kan-ik-deze-woning-kopen"),
             ("Duurzaamheidsrapport van je woning", "duurzaamheidsprofiel"), ("Wat kan ik lenen met mijn huurlasten?", "huren-naar-kopen"),
             ("Bereken je maximale hypotheek", "maximale-hypotheek"), ("Hypotheekrente top 5", "hypotheekrente")]


def render_toolsvoorvastgoed():
    """Tools voor vastgoed: initiatief van Yes-co en De Nationale Hypotheekbond (bron: www.toolsvoorvastgoed.nl, november 2026)."""
    pg = Page("tools-voor-vastgoed")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/yes-co/" + f)}" alt="{esc(alt)}" loading="lazy">'
    tools = "".join(f'<li><a href="{TVV_URL}tools/{u}/" target="_blank" rel="noopener">{esc(t)}</a></li>' for t, u in TVV_TOOLS)
    faq = [
        ("Wat is Tools voor vastgoed?", TVV_INTRO),
        ("Welke rekentools zitten in de hypotheek toolset?",
         "Maandlasten berekenen, Kan ik deze woning kopen?, duurzaamheidsrapport van je woning, Wat kan ik lenen met mijn "
         "huurlasten?, maximale hypotheek en hypotheekrente top 5."),
        ("Wat kost de hypotheek toolset?", "De volledige hypotheek toolset (zes rekentools) kost € 80 per maand en is per maand opzegbaar."),
        ("Moet de bezoeker inloggen?", "Nee. De bezoeker krijgt direct een actuele berekening en wordt uitgenodigd om contact met je "
         "op te nemen voor persoonlijk advies."),
        ("Werken de tools op mijn website?", "Ja. De tools zijn geschikt voor iedere website, direct en volledig embedded te "
         "installeren en met ieder systeem te koppelen."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Tools voor vastgoed", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Tools voor vastgoed</h1>
  <p class="lead">Slimme online tools voor álle vastgoedprofessionals: werk efficiënt en geef je klant een optimale beleving.</p>
  <div class="mhz-intro"><div><p>{esc(TVV_INTRO)}</p>
    <p class="btn-row"><a class="btn-out cta" href="{TVV_URL}contact/" target="_blank" rel="noopener">Neem contact op</a>
    <a class="btn-out" href="{TVV_URL}" target="_blank" rel="noopener">Naar toolsvoorvastgoed.nl</a></p></div>
    <figure>{img("hypotheektoolset.webp", "De hypotheektoolset op verschillende schermen")}</figure></div>
  <h2 class="wth">Het aanbod</h2>
  <div class="wtwhys">
    <div class="wtwhy">{img("tvv-publiceren.webp", "Woningzoekers bekijken het aanbod")}<h3>Vastgoed publiceren</h3><p>Met Yes-co beheer je vastgoedobjecten en relaties en publiceer je met één druk op de knop naar Funda, Jaap, Huislijn, Pararius of je eigen website. Inclusief wizard voor koop- en huurovereenkomsten, Wwft-checks en digitaal ondertekenen; geschikt voor verkoop, verhuur, aankoop, aanhuur, nieuwbouw en bedrijfsonroerendgoed.</p></div>
    <div class="wtwhy">{img("mijnhuiszaken-hypotheek-berekenen.webp", "Hypotheek berekenen in MijnHuiszaken")}<h3>Online klantdossier</h3><p>Met <a href="{pg.rel("mijnhuiszaken")}">MijnHuiszaken</a> nodig je je klant per mail uit voor een eigen, beveiligde omgeving: hypotheekberekening met actuele rentes, het volledige woningaanbod met realtime alerts, en losse diensten zoals een waarderapport, kadastrale kaart of uittreksel van de hypotheek- of eigendomsakte. Makelaar en adviseur wisselen onderling leads uit.</p></div>
    <div class="wtwhy">{img("hypotheektoolset.webp", "De hypotheektoolset op verschillende schermen")}<h3>Rekentools voor je website</h3><p>Maandlasten, ‘Kan ik deze woning kopen?’, duurzaamheidsrapport, ‘Wat kan ik lenen met mijn huurlasten?’, maximale hypotheek en hypotheekrente top 5. De tools rekenen realtime met actuele rentes en alle aanbieders, en nodigen de bezoeker altijd uit om contact met jou op te nemen. Zie ook de <a href="{pg.rel("websitetools")}">websitetools</a>.</p></div>
    <div class="wtwhy">{img("tvv-woningwaarderapport.webp", "Woningwaarderapport")}<h3>Woningwaarderapport</h3><p>Geef je klant een geautomatiseerd overzicht van de waarde van zijn woning, een sterke aanleiding voor een gesprek over verkopen, verhuizen of de hypotheek aanpassen. <a href="{pg.rel("woningwaarderapport")}">Meer over het woningwaarderapport</a>.</p></div>
  </div>
  <div class="mhz-duo"><div><h3>Starten als makelaar?</h3>
  <p>Yes-co is geschikt voor alle makelaars, aangesloten bij NVM, Vastgoedpro of VBO, of ongebonden. Zo start je:</p>
  <ol><li>Vraag via Funda een Tiara-aansluitnummer aan.</li><li>Neem contact op voor een demo van de software.</li><li>Voer je klanten en vastgoedobjecten in.</li><li>Publiceer je objecten zodra je er klaar voor bent.</li></ol></div>
  <figure>{img("tvv-startende-makelaar.webp", "Yes-co op laptop, tablet en telefoon voor de startende makelaar")}</figure></div>
  <table class="mhz-tabel"><thead><tr><th>Dienst (toolsvoorvastgoed.nl)</th><th>Prijs</th></tr></thead><tbody>
    <tr><td>Hypotheek toolset (6 rekentools, per maand opzegbaar)</td><td>€ 80 per maand</td></tr>
    <tr><td>MijnHuiszaken online klantdossier</td><td>€ 79 per maand</td></tr></tbody></table>
  <h2 class="wth">Kansrijke leads met de hypotheektools</h2>
  <p>De online hypotheektools geven geen standaard hypotheekberekening: het zijn universele plug-ins die rekenen met actuele rentes en aanbieders. Je biedt je klant optimale service, ontvangt direct kansrijke leads, en je klant is beter voorbereid als jullie in gesprek gaan.</p>
  <div class="mhz-duo">
    <div><h3>Voor de consument</h3><ul><li>Hoeft niet in te loggen</li><li>Krijgt direct een actuele berekening</li><li>Wordt altijd uitgenodigd om contact met je op te nemen voor persoonlijk advies</li></ul></div>
    <div><h3>Voor de vastgoedprofessional</h3><ul><li>Geschikt voor iedere website, direct te installeren</li><li>Volledig embedded, met ieder systeem te koppelen</li><li>Realtime berekeningen met actuele rentes en alle aanbieders</li></ul></div>
  </div>
  <p>Probeer de tools:</p>
  <ul>{tools}</ul>
  <p class="mhz-tip">Let op: de uitkomsten van de rekentools zijn indicatief en geen hypotheekadvies. De tools nodigen de bezoeker daarom altijd uit voor persoonlijk advies.</p>
  <p>Zie ook: <a href="{pg.rel("yes-co")}">Makelaar Software: Yes-co</a>, <a href="{pg.rel("mijnhuiszaken")}">MijnHuiszaken</a> en de <a href="{pg.rel("websitetools")}">websitetools</a>.</p>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <h2 class="wth">Meer weten?</h2>
  <p>Neem vrijblijvend contact op: mail <a href="mailto:info@toolsvoorvastgoed.nl">info@toolsvoorvastgoed.nl</a>, bel <a href="tel:+31365238455">036 523 84 55</a> of kijk op <a href="{TVV_URL}contact/" target="_blank" rel="noopener">toolsvoorvastgoed.nl</a>.</p>
  <p class="src">Bron: <a href="{TVV_URL}" target="_blank" rel="noopener">www.toolsvoorvastgoed.nl</a> (stand 4 november 2026). Prijzen en voorwaarden kunnen wijzigen.</p>
</div></main>"""
    write("tools-voor-vastgoed", layout(pg, "Tools voor vastgoed: slimme online tools voor vastgoedprofessionals", body, None,
                                        "Tools voor vastgoed van Yes-co en De Nationale Hypotheekbond: vastgoed publiceren, online "
                                        "klantdossier, hypotheek toolset (€ 80 per maand) en woningwaarderapport."))


def render_woningwaarderapport():
    """Woningwaarderapport (bron: www.toolsvoorvastgoed.nl/woningwaarde-rapport, november 2026)."""
    pg = Page("woningwaarderapport")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/yes-co/" + f)}" alt="{esc(alt)}" loading="lazy">'
    url = TVV_URL + "woningwaarde-rapport/"
    voordelen = [
        ("Overzicht van de woningwaarde", "Je klant krijgt een geautomatiseerd rapport met de geschatte waarde van zijn of haar woning."),
        ("Aanleiding voor een gesprek", "Een woningwaarde is hét moment om te praten over verkopen, verhuizen, extra lenen of de "
         "hypotheek aanpassen."),
        ("Weten wat je klant van plan is", "Bij de aanvraag geeft de klant aan waarom hij een waardeschatting wil (hypotheek "
         "aanpassen, kopen, verkopen of nieuwsgierig) en of en wanneer hij wil verhuizen."),
        ("Ook voor bestaande klanten", "Laat klanten in je portefeuille zien wat hun woning nu waard is en ontdek wie er in "
         "beweging komt."),
    ]
    blokken = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in voordelen)
    faq = [
        ("Wat is het woningwaarderapport?", "Een geautomatiseerd overzicht van de geschatte waarde van een woning, aangeboden via "
         "Tools voor vastgoed (Yes-co en De Nationale Hypotheekbond)."),
        ("Kan ik een voorbeeld zien?", "Ja. Op toolsvoorvastgoed.nl vraag je gratis een voorbeeldrapport aan, zoals je klant het ook "
         "ontvangt. Je vult postcode, huisnummer, de reden van de waardeschatting en je contactgegevens in."),
        ("Kan ik het rapport ook vanuit eBlinqx Connect ophalen?", "Ja, met PortefeuilleSignalen haal je de woningwaarde van een "
         "dossier op via de knop ‘Woningwaarde’ onder het tabblad Berekeningen. Zie het kennisbankartikel over woningwaarde berekenen."),
        ("Is het woningwaarderapport een taxatie?", "Nee. Het is een geautomatiseerde schatting en geen gevalideerd taxatierapport. "
         "Voor een hypotheekaanvraag is meestal een taxatie door een erkend taxateur nodig."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Woningwaarderapport", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Woningwaarderapport</h1>
  <p class="lead">Bied je klant een overzicht van de waarde van zijn woning, en een goede reden om met jou in gesprek te gaan.</p>
  <div class="mhz-intro"><div><p>Met het woningwaarderapport van <a href="{pg.rel("tools-voor-vastgoed")}">Tools voor vastgoed</a> geef je je klant een geautomatiseerd overzicht van de waarde van zijn of haar woning. Een sterke aanleiding voor een gesprek over verkopen, verhuizen of de hypotheek aanpassen.</p>
    <p>Benieuwd hoe het eruitziet? Vraag gratis een voorbeeldrapport aan, precies zoals je klant het ontvangt.</p>
    <p class="btn-row"><a class="btn-out cta" href="{url}" target="_blank" rel="noopener">Gratis voorbeeldrapport aanvragen</a>
    <a class="btn-out" href="{TVV_URL}contact/" target="_blank" rel="noopener">Neem contact op</a></p></div>
    <figure>{img("tvv-woningwaarderapport.webp", "Woningwaarderapport in de hand")}</figure></div>
  <h2 class="wth">Waarom een woningwaarderapport?</h2>
  <div class="wtwhys">{blokken}</div>
  <h2 class="wth">Zo vraag je een voorbeeldrapport aan</h2>
  <ol class="abs-stappen">
    <li><strong>Vul het adres in</strong><br>Postcode, huisnummer en eventueel een toevoeging.</li>
    <li><strong>Geef de reden op</strong><br>Hypotheek aanpassen, verkopen, kopen, verkopen en kopen, of nieuwsgierig; en of en wanneer er een verhuizing gepland is.</li>
    <li><strong>Vul je contactgegevens in</strong><br>Bedrijfsnaam, naam, e-mailadres en eventueel telefoonnummer. Je ontvangt het rapport per e-mail.</li>
  </ol>
  <h2 class="wth">In eBlinqx Connect</h2>
  <p>Werk je met PortefeuilleSignalen, dan haal je de woningwaarde van een dossier op via de knop ‘Woningwaarde’ onder het tabblad Berekeningen. Lees meer in <a href="{pg.rel("kennisbank/woningwaarde-duurzaamheid-en-maximale-hypotheek-berekenen")}">Woningwaarde, duurzaamheid en maximale hypotheek berekenen</a>.</p>
  <p class="mhz-tip">Let op: het woningwaarderapport is een geautomatiseerde schatting, geen taxatierapport en geen advies. Communiceer de waarde als indicatie naar je klant.</p>
  <p>Zie ook: <a href="{pg.rel("tools-voor-vastgoed")}">Tools voor vastgoed</a>, <a href="{pg.rel("mijnhuiszaken")}">MijnHuiszaken</a> (met woningwaarde in het klantdashboard) en de <a href="{pg.rel("websitetools")}">websitetools</a>.</p>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <h2 class="wth">Meer weten?</h2>
  <p>Mail <a href="mailto:info@toolsvoorvastgoed.nl">info@toolsvoorvastgoed.nl</a> of bel <a href="tel:+31365238455">036 523 84 55</a>.</p>
  <p class="src">Bron: <a href="{url}" target="_blank" rel="noopener">toolsvoorvastgoed.nl/woningwaarde-rapport</a> (stand 4 november 2026).</p>
</div></main>"""
    write("woningwaarderapport", layout(pg, "Woningwaarderapport: de waarde van de woning van je klant", body, None,
                                        "Woningwaarderapport van Tools voor vastgoed: geef je klant een geautomatiseerd overzicht "
                                        "van de woningwaarde en ontdek wie wil verkopen, verhuizen of de hypotheek aanpassen."))


PARTNERS_URL = "https://verzekeringhypotheek.blinqx.tech/partners"
PARTNER_EIGEN = {  # partner-slug -> eigen pagina op deze site
    "mijnhuiszaken": ("mijnhuiszaken", "MijnHuiszaken"),
    "yes-co-eblinqx-makelaars-software": ("yes-co", "Makelaar Software: Yes-co"),
    "gratis-woningwaarde-rapport": ("woningwaarderapport", "Woningwaarderapport"),
    "rekentools-voor-op-de-website": ("websitetools", "Websitetools"),
}
PARTNER_SAMENVATTING = {"rekentools-voor-op-de-website": "Rekentools van Hypotheekbond voor op de website van je advieskantoor: "
                        "hypotheek berekenen, rentes vergelijken, aflossen, verduurzamen en klantinzicht."}


def partners_laden():
    f = os.path.join(SRC, "partners", "partners.json")
    if not os.path.exists(f):
        return []
    lijst = json.load(open(f, encoding="utf8"))
    for p in lijst:
        h = p["html"]
        h = re.sub(r"<p>(?:(?!</p>).)*(?:via onderstaande? knop|Download onderstaande buttons)(?:(?!</p>).)*</p>", "", h, flags=re.S)

        def knop(m):
            url = re.search(r'href="(https://formulier\.actiefbeheerscan\.nl/[^"]+)"', m.group(0)).group(1)
            extra = re.search(r'of kijk op (<a [^>]+>.*?</a>)', m.group(0))
            return (f'<p class="btn-row"><a class="btn-out cta" href="{url}" target="_blank" rel="noopener">Meer weten over deze samenwerking</a></p>'
                    + (f"<p>Of kijk op {extra.group(1)}.</p>" if extra else ""))
        h = re.sub(r"<p>(?:(?!</p>).)*klik hier(?:(?!</p>).)*</p>", knop, h, flags=re.S)
        p["html"] = h
        s = PARTNER_SAMENVATTING.get(p["slug"]) or p["samenvatting"]
        if not s or s.endswith(("...", "…")):
            eerste = next((html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"^<strong>.*?</strong><br>", "", x))) for x in re.findall(r"<p>(.*?)</p>", p["html"], re.S)
                           if len(x) > 60 and "relatie-vh@" not in x), s)
            s = eerste
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) > 200:
            deel = s[:200]
            zin = max(deel.rfind(". "), deel.rfind("! "), deel.rfind("? "))
            s = deel[:zin + 1] if zin >= 80 else deel[:199].rsplit(" ", 1)[0] + "…"
        p["kort"] = s
        samen = {"Kennispatner": "Kennispartner", "Makelaar": "Makelaars", "Verzekering": "Verzekeren", "Hypotheek": "Hypotheekadvies",
                 "Websitetools": "Rekentools", "Expertbox": None, "Draagplicht": None}
        p["tags"] = sorted({samen.get(t, t) for t in (x.strip().capitalize() for x in p["tags"])} - {None})
    return lijst


def render_partners():
    """Partners van Blinqx Verzekering & Hypotheek (bron: verzekeringhypotheek.blinqx.tech/partners, november 2026)."""
    lijst = partners_laden()
    if not lijst:
        return
    pg = Page("partners")
    alle_tags = sorted({t for p in lijst for t in p["tags"]})
    knoppen = '<button type="button" class="wtbtn ptag actief" data-tag="">Alle</button>' + "".join(
        f'<button type="button" class="wtbtn ptag" data-tag="{esc(t)}">{esc(t)}</button>' for t in alle_tags)
    kaarten = "".join(
        f'<a class="wtwhy pkaart" href="{pg.rel("partners/" + p["slug"])}" data-tags="{esc("|".join(p["tags"]))}">'
        + (f'<img src="{pg.rel("bronnen/partners/" + p["afbeelding"])}" alt="" loading="lazy">' if p["afbeelding"] else "")
        + f'<h3>{esc(p["titel"])}</h3><p class="ptags">{esc(" · ".join(p["tags"]))}</p><p>{esc(p["kort"])}</p></a>'
        for p in lijst)
    body = f"""{crumbs(pg, [("Partners", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Partners</h1>
  <p class="lead">Door de samenwerking en koppeling met het eBlinqx-platform maken onze partners het proces voor de klant en het intermediair beter en efficiënter.</p>
  <p>Hieronder vind je alle {len(lijst)} partners van Blinqx Verzekering &amp; Hypotheek: van woningwaarde, taxatie en verduurzamen tot kennispartners, bankgaranties, websites en software. Filter op onderwerp:</p>
  <div class="wtbtns ptags-filter" role="group" aria-label="Filter op onderwerp">{knoppen}</div>
  <div class="wtwhys pkaarten">{kaarten}</div>
  <p class="mhz-tip">Meer weten over een partner of een samenwerking? Mail <a href="mailto:relatie-vh@blinqx.tech">relatie-vh@blinqx.tech</a>.</p>
  <p class="src">Bron: <a href="{PARTNERS_URL}" target="_blank" rel="noopener">verzekeringhypotheek.blinqx.tech/partners</a> (stand 4 november 2026).</p>
</div></main>
<script>
document.querySelectorAll('.ptag').forEach(function(b){{b.addEventListener('click',function(){{
  var t=b.getAttribute('data-tag');document.querySelectorAll('.ptag').forEach(function(x){{x.classList.toggle('actief',x===b);x.setAttribute('aria-pressed',x===b)}});
  document.querySelectorAll('.pkaart').forEach(function(k){{k.hidden=t&&k.getAttribute('data-tags').split('|').indexOf(t)<0}});
}})}});
</script>"""
    write("partners", layout(pg, "Partners van Blinqx Verzekering & Hypotheek", body, None,
                             f"Alle {len(lijst)} partners van Blinqx Verzekering & Hypotheek die aansluiten op eBlinqx: woningwaarde, "
                             "taxatie, verduurzamen, bankgaranties, kennispartners, websites en software."))
    for p in lijst:
        pp = Page("partners/" + p["slug"])
        eigen = PARTNER_EIGEN.get(p["slug"])
        inh = p["html"]
        # eerste kop die gelijk is aan de titel weglaten (staat al in de h1)
        inh = re.sub(r"^<h2>(.*?)</h2>", lambda m: "" if re.sub(r"\W", "", m.group(1).lower()) == re.sub(r"\W", "", p["titel"].lower()) else m.group(0), inh)
        body = f"""{crumbs(pp, [("Partners", "partners"), (p["titel"], None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>{esc(p["titel"])}</h1>
  <p class="ptags">{esc(" · ".join(p["tags"]))}</p>
  <div class="mhz-intro pintro"><div><p class="lead">{esc(p["kort"])}</p>
    {f'<p class="mhz-tip">Uitgebreide informatie vind je ook op onze pagina <a href="{pp.rel(eigen[0])}">{esc(eigen[1])}</a>.</p>' if eigen else ""}</div>
    {f'<figure><img src="{pp.rel("bronnen/partners/" + p["afbeelding"])}" alt="{esc(p["titel"])}" loading="lazy"></figure>' if p["afbeelding"] else ""}</div>
  {MHZ_VIDEO(pp) if p["slug"] == "mijnhuiszaken" else ""}
  <div class="partner-tekst">{inh}</div>
  <h2 class="wth">Contact en samenwerking</h2>
  <p>Door de samenwerking en koppeling met het eBlinqx-platform maken onze partners het proces voor de klant en het intermediair beter en efficiënter.{" Voor meer informatie, neem contact op met:" if p.get("contact") else " Meer weten over deze partner? Mail <a href=\"mailto:relatie-vh@blinqx.tech\">relatie-vh@blinqx.tech</a>."}</p>
  {"<ul>" + "".join(f'<li>{esc(n)} – <a href="mailto:{esc(m)}">{esc(m)}</a></li>' for n, m in p.get("contact", [])) + "</ul><p>Zij vertellen je alles over de mogelijkheden.</p>" if p.get("contact") else ""}
  <p><a href="{pp.rel("partners")}">← Alle partners</a></p>
  <p class="src">Bron: <a href="{esc(p["bron"])}" target="_blank" rel="noopener">verzekeringhypotheek.blinqx.tech</a> (stand 4 november 2026).</p>
</div></main>"""
        write("partners/" + p["slug"], layout(pp, f"{p['titel']} | Partner van Blinqx", body, None, p["kort"]))


def MHZ_VIDEO(pg):
    """Promovideo MijnHuiszaken (3:06) met VideoObject-gegevens voor Google en AI-zoekmachines."""
    mp4, poster = pg.rel("bronnen/mijnhuiszaken/mijnhuiszaken-promo.mp4"), pg.rel("bronnen/mijnhuiszaken/mijnhuiszaken-promo.webp")
    ld = json.dumps({"@context": "https://schema.org", "@type": "VideoObject", "name": "MijnHuiszaken voor hypotheekadviseurs",
                     "description": "Altijd in beeld vanaf de eerste zoekopdracht: realtime NVM-woningaanbod voor je klanten, je eigen "
                                    "logo in hun omgeving, inzicht in zoekgedrag en de tarieven (€ 79 per maand voor 1.000 klanten).",
                     "thumbnailUrl": SITE_URL + "bronnen/mijnhuiszaken/mijnhuiszaken-promo.webp",
                     "contentUrl": SITE_URL + "bronnen/mijnhuiszaken/mijnhuiszaken-promo.mp4",
                     "uploadDate": "2026-11-04", "duration": "PT3M6S", "inLanguage": "nl-NL"}, ensure_ascii=False)
    return (f'<figure class="mhz-video"><video controls preload="none" playsinline poster="{poster}" width="1920" height="1080">'
            f'<source src="{mp4}" type="video/mp4">Je browser kan deze video niet afspelen. '
            f'<a href="{mp4}">Download de video (mp4)</a>.</video>'
            f'<figcaption>MijnHuiszaken voor hypotheekadviseurs: de propositie, de klantreis, de online omgeving van je klant en de tarieven (3 minuten).</figcaption></figure>'
            f'<script type="application/ld+json">{ld}</script>')


FINLY_URL = "https://www.getfinly.com/crm"
FINLY_INTRO = ("Finly CRM is het CRM van Finly, a Blinqx company: één centrale plek waar jij en je collega's contact- en "
               "relatiegegevens, verzekeringen, workflows, documenten, formulieren, signalen en de communicatiegeschiedenis van je "
               "klanten beheren. Zo begrijp je klanten beter en geef je gepersonaliseerd advies.")
FINLY_TOOLS = [
    ("Engage", "Ontvang signalen en verstuur (geautomatiseerd) uitnodigingen aan prospects en klanten, met toegang tot de agenda van je verkopers en adviseurs."),
    ("Plan", "Prospects en klanten plannen zelf online een afspraak in de met Outlook gekoppelde agenda van je adviseurs."),
    ("Prepare", "Klanten uploaden, downloaden en ondertekenen documenten en vullen formulieren in op een beveiligde voorbereidingspagina."),
    ("Meet", "Co-browsen, schermdelen, videochat en veilig documenten uitwisselen tijdens online verkoop- en adviesgesprekken."),
    ("Close", "Een gestructureerd verkoop- of adviesproces met gepersonaliseerde adviesrapporten en voorstellen."),
    ("Flow", "Workflows als extra brein: geen klant of prospect valt tussen wal en schip en je houdt grip op je portefeuille."),
]


def render_finly():
    """Finly CRM (bron: www.getfinly.com/crm, november 2026)."""
    pg = Page("finly-crm")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/finly/" + f)}" alt="{esc(alt)}" loading="lazy">'
    tools = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in FINLY_TOOLS)
    faq = [
        ("Wat is Finly CRM?", FINLY_INTRO),
        ("Met welke systemen koppelt Finly?", "Met bronsystemen als DIAS en ANVA, en daarnaast onder meer met telefonie (Dstny), "
         "vergelijkingssoftware (AWI en MY TP) en hypotheeksoftware (Adviesbox)."),
        ("Kan ik rapportages maken in Finly?", "Ja. Vrijwel elk onderdeel is te exporteren naar CSV, het dashboard is vrij in te richten "
         "met werklijsten, en de data is te koppelen aan managementrapportagesystemen."),
        ("Waar vind ik support voor Finly?", "In het helpcenter op support-finly.vh.blinqx.tech. De actuele systeemstatus staat op status.finly.nl."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\\\/")
    body = f"""{crumbs(pg, [("Finly CRM", None)])}
<main class="subpage mhz finly"><div class="wrap">
  <h1>Finly CRM</h1>
  <p class="lead">Alle klantgegevens, workflows en communicatie op één plek: voor persoonlijk advies en duurzame klantrelaties.</p>
  <div class="mhz-intro"><div><p>{esc(FINLY_INTRO)}</p>
    <p>Finly CRM helpt ook bij het beheren van verkoopkansen, het maken van offertes en het opvolgen van acties, bij het bewaken van compliance en het stroomlijnen van administratieve taken. Het CRM is eenvoudig schaalbaar en wordt continu verbeterd, zonder dat je daar als gebruiker last van hebt.</p>
    <p class="btn-row"><a class="btn-out cta" href="https://www.getfinly.com/online-demo" target="_blank" rel="noopener">Plan een online demo</a>
    <a class="btn-out" href="https://www.finly.nl/login" target="_blank" rel="noopener">Inloggen in Finly</a></p></div>
    <figure>{img("egra3.webp", "Team werkt samen aan een klantdossier in Finly")}</figure></div>
  <div class="mhz-duo">
    <figure>{img("egra2.webp", "Laptop met verbindingen naar verschillende systemen")}</figure>
    <div><h2 class="wth">Integraties</h2>
      <p>Finly koppelt met de belangrijke bronsystemen van de Nederlandse financiële dienstverlening, zoals <strong>DIAS</strong> en <strong>ANVA</strong>. De integraties:</p>
      <ul><li>brengen gegevens uit verschillende bronsystemen samen, zodat je altijd actuele en volledige klantgegevens hebt;</li><li>voorkomen dubbele invoer: dat bespaart tijd en verkleint de kans op fouten;</li><li>helpen bij compliance doordat het CRM samenwerkt met compliance- en reguleringshulpmiddelen.</li></ul>
      <p>Daarnaast koppelt Finly met telefonie (Dstny), vergelijkingssoftware (AWI en MY TP) en hypotheeksoftware (Adviesbox).</p></div>
  </div>
  <div class="mhz-duo">
    <div><h2 class="wth">Rapportage en analyse</h2>
      <p>Finly geeft inzicht in je bedrijfsprestaties, zoals verkoopcijfers en klantsegmentatie, zodat je beslissingen op data baseert. Vrijwel elk onderdeel is te exporteren naar CSV. Het dashboard richt je vrij in, met werklijsten voor je medewerkers en grafieken of tabellen om op te acteren. Uit de data ontstaan bovendien signalen voor medewerkers of klanten, en je koppelt Finly eenvoudig aan managementrapportagesystemen.</p></div>
    <figure>{img("egra6.webp", "Dashboard met grafieken en rapportages")}</figure>
  </div>
  <h2 class="wth">Tools in Finly CRM</h2>
  <div class="wtwhys">{tools}</div>
  <div class="mhz-duo">
    <figure>{img("egra8.webp", "Mengpaneel als symbool voor instelbaarheid")}</figure>
    <div><h2 class="wth">Unieke instelbaarheid</h2>
      <p>Pas functionaliteiten, workflows en schermen aan op de specifieke behoeften van je kantoor en je doelgroep. Zo sluit Finly naadloos aan op je organisatie en werk je effectiever en efficiënter.</p></div>
  </div>
  <p class="mhz-tip">Lees ook de <a href="https://support-finly.vh.blinqx.tech/nl/" target="_blank" rel="noopener">Finly-helpcenter</a> en bekijk de <a href="https://status.finly.nl" target="_blank" rel="noopener">systeemstatus van Finly</a>.</p>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <h2 class="wth">Contact</h2>
  <p>Finly, a Blinqx company · Oude Fabriekstraat 7, 3812 NR Amersfoort. <a href="https://www.getfinly.com/online-demo" target="_blank" rel="noopener">Plan een online demo</a> of bekijk de <a href="https://verzekeringhypotheek.blinqx.tech/contact" target="_blank" rel="noopener">contactgegevens</a>.</p>
  <p class="src">Bron: <a href="{FINLY_URL}" target="_blank" rel="noopener">getfinly.com/crm</a> (stand 4 november 2026).</p>
</div></main>"""
    write("finly-crm", layout(pg, "Finly CRM: klantgegevens, workflows en communicatie op één plek", body, None,
                              "Finly CRM van Blinqx: klantgegevens, verzekeringen, workflows, documenten en signalen centraal, "
                              "met koppelingen met DIAS, ANVA, Dstny, AWI en Adviesbox."))


DEMO_STEEN = "https://www.steenhypotheken.nl/"
DEMO_FIER = "https://app.mach3blocks.io/preview/?wid=112166&pid=3075367&pkey=8z2fs9ihio62x559t26ksewyz15r5peo&language=nl"


def render_demokantoor():
    """Demo-kantoren: voorbeeldwebsites van adviseurs met alle tools van Blinqx erin."""
    pg = Page("demo-kantoor")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/demo/" + f)}" alt="{esc(alt)}" loading="lazy">'
    steen_onderdelen = ["Actuele rentestanden en het volledige renteoverzicht", "Rekentools: zelf berekenen", "Inzichttool en Financiële rust",
                        "Financiële kluis (UwKluis) en brondata", "Duurzaamheidsprofiel", "Pakketvergelijker en schade melden",
                        "MijnHuiszaken: woning zoeken en ‘Wat is mijn woning waard?’", "Nazorg en onderhoud", "Direct een afspraak maken"]
    fier_onderdelen = ["Maximale hypotheek en ‘Kan ik deze woning kopen?’", "Mijn hypotheek nu & straks en ‘Kan ik besparen?’",
                       "Rentekorting door topafslag", "Huren of kopen?", "Wat is deze woning waard?", "Overlijdensrisicopremie",
                       "Actuele rentes, looptijdrente en spaarrente top 10", "Duurzaamheidsprofiel"]
    li = lambda xs: "".join(f"<li>{esc(x)}</li>" for x in xs)
    body = f"""{crumbs(pg, [("Demo-kantoor", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Demo-kantoor: zo ziet een website met alles van Blinqx eruit</h1>
  <p class="lead">Bekijk hoe de tools van Blinqx samenkomen op de website van een advieskantoor: rekentools, actuele rentes, MijnHuiszaken, UwKluis en de koppeling met eBlinqx.</p>
  <div class="mhz-duo">
    <div><h2 class="wth">Steen Hypotheken &amp; Verzekeringen</h2>
      <p>Steen Hypotheken is het demo-kantoor van Blinqx Verzekering &amp; Hypotheek. Op deze website zie je hoe een adviseur alle onderdelen van Blinqx inzet voor zijn klanten, van de eerste oriëntatie tot nazorg:</p>
      <ul>{li(steen_onderdelen)}</ul>
      <p class="btn-row"><a class="btn-out cta" href="{DEMO_STEEN}" target="_blank" rel="noopener">Bekijk Steen Hypotheken ↗</a></p></div>
    <figure><a href="{DEMO_STEEN}" target="_blank" rel="noopener">{img("steen-hypotheken.webp", "Homepage van demo-kantoor Steen Hypotheken & Verzekeringen")}</a></figure>
  </div>
  <div class="mhz-duo">
    <figure><a href="{DEMO_FIER}" target="_blank" rel="noopener">{img("fierfinance.webp", "Demowebsite FierFinance met de pagina Zelf berekenen")}</a></figure>
    <div><h2 class="wth">Demowebsite FierFinance</h2>
      <p>Een tweede, moderne demowebsite laat zien hoe de rekentools een vaste plek krijgen op een kantoorwebsite. Op de pagina ‘Zelf berekenen’ rekent de bezoeker alvast zelf, en maakt daarna direct een afspraak:</p>
      <ul>{li(fier_onderdelen)}</ul>
      <p class="btn-row"><a class="btn-out cta" href="{DEMO_FIER}" target="_blank" rel="noopener">Bekijk de demowebsite ↗</a></p></div>
  </div>
  <p class="mhz-tip">Let op: dit zijn demowebsites. Namen, adressen en wettelijke gegevens zijn voorbeelden, en de uitkomsten van de rekentools zijn indicatief en geen advies.</p>
  <h2 class="wth">Wil je ook een website met alles van Blinqx?</h2>
  <p>Laat het ons weten. We vertellen je graag welke onderdelen je op je eigen website kunt inzetten en hoe ze aansluiten op eBlinqx. Neem contact op met Milan Akavia (<a href="mailto:milan.akavia@blinqx.tech">milan.akavia@blinqx.tech</a>) of Jeroen Oversteegen (<a href="mailto:jeroen.oversteegen@blinqx.tech">jeroen.oversteegen@blinqx.tech</a>), of mail <a href="mailto:relatie-vh@blinqx.tech?subject=Website%20met%20alles%20van%20Blinqx">relatie-vh@blinqx.tech</a>.</p>
  <p class="btn-row"><a class="btn-out cta" href="mailto:relatie-vh@blinqx.tech?subject=Website%20met%20alles%20van%20Blinqx">Ja, ik wil ook zo'n website</a></p>
  <p>Lees ook: <a href="{pg.rel("websitetools")}">Websitetools</a>, <a href="{pg.rel("mijnhuiszaken")}">MijnHuiszaken</a>, <a href="{pg.rel("actiefbeheerscan")}">Actiefbeheerscan</a> en <a href="{pg.rel("hypotheekrente-app")}">Hypotheekrente-app</a>.</p>
</div></main>"""
    write("demo-kantoor", layout(pg, "Demo-kantoor: een website met alles van Blinqx", body, None,
                                 "Bekijk het demo-kantoor Steen Hypotheken en de demowebsite FierFinance: rekentools, actuele rentes, "
                                 "MijnHuiszaken en UwKluis op de website van een adviseur. Wil je dit ook? Laat het ons weten."))


def sites_laden():
    f = os.path.join(TOOLS, "sites.json")
    return json.load(open(f, encoding="utf8")) if os.path.exists(f) else []


def adviesbox_extra(pg):
    """Extra inhoud voor sites/adviesbox-nl: functies, modules, ondersteuning, handleidingen en het helpcenter."""
    hcf = os.path.join(SRC, "adviesbox", "helpcenter.json")
    hc = json.load(open(hcf, encoding="utf8")) if os.path.exists(hcf) else []
    blokken = [
        ("Klantprofiel volgens de Wft", "Aan de hand van de adviesaanleiding stel je een volledig klantprofiel op, met de richtlijnen van de Wft als basis. Dat profiel gebruik je bij het vormen en motiveren van het advies."),
        ("Scenario's en tekorten", "Vanuit de inventarisatie en het klantprofiel zie je direct of er tekorten ontstaan, met scenario's voor aflossen, overlijden, arbeidsongeschiktheid, werkloosheid en pensioen."),
        ("Elektronisch aanvragen", "Vraag een hypotheek, bankgarantie of taxatie elektronisch aan via HDN of rechtstreeks bij de aanbieder. Adviesbox is volledig HDN-gecertificeerd."),
        ("Rapporten", "Kies uit standaardrapporten: inventarisatierapport, kort rapport, hypotheekrapport en financieel plan. Rapporten pas je naar wens aan."),
        ("Netto besteedbaar inkomen", "Een van de invalshoeken bij het advies, met gebruik van de geschatte uitgaven van het Nibud."),
        ("Hypotheekvergelijker", "Vergelijkt alle hypotheeklabels over de hele looptijd op rente, voorwaarden en maximale verstrekking, inclusief automatische rentedaling. Zo vergelijk je op totale kosten in plaats van alleen op de beginrente."),
    ]
    wt = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in blokken)
    bijlagen = {}
    for a in hc:
        for b in a.get("bijlagen", []):
            bijlagen[b["bestand"]] = b["naam"]
    dl = "".join(f'<li><a href="{pg.rel(f)}">{esc(n)}</a> (pdf)</li>' for f, n in sorted(bijlagen.items(), key=lambda x: x[1]))
    coll = {}
    for a in hc:
        coll.setdefault(a["collectie"], []).append(a)
    hc_html = "".join(
        f'<details class="wtfaq"><summary>{esc(c)} ({len(lst)})</summary><ul>'
        + "".join(f'<li><a href="{esc(a["url"])}" target="_blank" rel="noopener">{esc(a["titel"])}</a></li>' for a in sorted(lst, key=lambda x: x["titel"].lower()))
        + "</ul></details>" for c, lst in coll.items())
    return f"""
  <h2 class="wth">Wat kun je met Adviesbox?</h2>
  <div class="wtwhys">{wt}</div>
  <div class="mhz-duo">
    <div><h2 class="wth">Module Klantdossier</h2>
      <p>Klantdossier is een uitbreiding van Adviesbox voor het opbouwen van het klantdossier: een uitgebreide administratie, taken en notities, een productoverzicht met alle lopende producten en portefeuillemeldingen die je waarschuwen als je aandacht nodig is. De Wft verplicht je het hele adviestraject te documenteren; elke klant krijgt automatisch een klantmap voor documenten en correspondentie.</p>
      <p>Met de online inventarisatie in je eigen huisstijl vult je klant zelf zijn gegevens en klantprofiel in. Met de extra module Brondata haalt de klant zijn gegevens op bij verschillende overheidsinstanties, via een beveiligde verbinding.</p></div>
    <div><h2 class="wth">Overstappen naar Adviesbox</h2>
      <p>Met de overstapservice stap je eenvoudig over: tijdens een persoonlijk intakegesprek komen installatie, server of cloud, koppelingen en de samenwerking met je serviceprovider aan bod. Loopt het contract met je huidige leverancier nog, dan gebruik je Adviesbox tot de einddatum gratis, met een maximum van 6 maanden (volgens adviesbox.nl).</p>
      <p>Wil je eerst proberen? Vraag een gratis proeflicentie aan: je ontvangt per e-mail een licentiecode voor 14 dagen Adviesbox.</p></div>
  </div>
  <h2 class="wth">Koppelingen</h2>
  <p>Vanuit Adviesbox vraag je aan bij geldverstrekkers en verzekeraars. Daarnaast koppelt Adviesbox onder meer met Advieskeuze.nl (reviewplatform), ANVA CRM, Assistant, EDR Creditservice (kredietwaardigheid), Elements / eBlinqx en de Nationale Hypotheekbond (signalering). Het actuele overzicht staat in de <a href="https://www.adviesbox.nl/productkaartefficientbemiddelen" target="_blank" rel="noopener">productkaart efficiënt bemiddelen</a>.</p>
  <h2 class="wth">Ondersteuning</h2>
  <p>Voor Adviesbox heb je een licentiecode nodig; die ontvang je na een proeflicentie of bestelling. Een vraag, probleem of suggestie meld je in Adviesbox via <strong>Help &gt; Melding maken</strong>; daarna wordt contact met je opgenomen. Er zijn trainingen, waaronder een gratis starttraining, en je kunt een persoonlijk consult inplannen.</p>
  {f'<h3>Handleidingen</h3><ul>{dl}</ul>' if dl else ""}
  <h2 class="wth">Helpcenter Adviesbox</h2>
  <p>Alle {len(hc)} artikelen uit het <a href="https://support-adviesbox.vh.blinqx.tech/nl/" target="_blank" rel="noopener">Adviesbox-helpcenter</a>, per rubriek. Ze zijn ook doorzoekbaar via de zoekfunctie van deze site.</p>
  {hc_html}
  <h2 class="wth">Contact</h2>
  <p>Adviesbox (Blinqx), Harderwijkweg 5b, 2803 PW Gouda · <a href="tel:+31850180069">085 018 00 69</a> · <a href="mailto:secretariaat@blinqx.tech">secretariaat@blinqx.tech</a></p>"""


def render_sites():
    """Per website uit tools/sites.json een pagina sites/<slug>/ met beschrijving, afbeelding en knop (geen tegel)."""
    lijst = sites_laden()
    for s in lijst:
        pg = Page("sites/" + s["slug"])
        rel = "".join(f'<li><a href="{pg.rel(p)}">{esc(l)}</a></li>' for p, l in s["gerelateerd"])
        beeld = s.get("logo") or s.get("afbeelding")
        klein = ""
        if beeld:
            from PIL import Image
            if s.get("logo") or Image.open(os.path.join(ROOT, beeld)).width < 500:
                klein = ' style="max-width:340px;margin:0 auto;display:block"'  # logo niet opblazen
        fig = (f'<figure><a href="{esc(s["url"])}" target="_blank" rel="noopener"><img src="{pg.rel(beeld)}" '
               f'alt="Logo {esc(s["naam"])}" loading="lazy"{klein}></a></figure>' if beeld else "")
        body = f"""{crumbs(pg, [("Handige websites", "sites"), (s["naam"], None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>{esc(s["naam"])}</h1>
  <p class="lead">{esc(s["ondertitel"])}</p>
  <div class="mhz-intro"><div>{"".join(f"<p>{esc(t)}</p>" for t in s["tekst"])}</div>
    {fig}</div>
  {adviesbox_extra(pg) if s["slug"] == "adviesbox-nl" else ""}
  {f'<h2 class="wth">Lees ook</h2><ul>{rel}</ul>' if rel else ""}
  <p class="btn-row bezoek"><a class="btn-out cta" href="{esc(s["url"])}" target="_blank" rel="noopener" aria-label="Bezoek website {esc(s["naam"])}">Bezoek website ↗</a></p>
  <p><a href="{pg.rel("sites")}">← Alle handige websites</a></p>
  <p class="src">Bron: <a href="{esc(s["url"])}" target="_blank" rel="noopener">{esc(s["naam"].lower())}</a> (stand 4 november 2026).</p>
</div></main>"""
        write("sites/" + s["slug"], layout(pg, f"{s['naam']}: {s['ondertitel']}", body, None, " ".join(s["tekst"])), kluis=False)
    # overzicht (alleen via footer en zoeker bereikbaar, geen tegel)
    pg = Page("sites")
    kaarten = "".join(
        f'<div class="wtwhy sitekaart">'
        + (f'<a class="sitebeeld{" logo" if s.get("logo") else ""}" href="{pg.rel("sites/" + s["slug"])}" tabindex="-1" aria-hidden="true">'
           f'<img src="{pg.rel(s.get("logo") or s["afbeelding"])}" alt="" loading="lazy"></a>' if (s.get("logo") or s.get("afbeelding")) else "")
        + f'<h3><a href="{pg.rel("sites/" + s["slug"])}">{esc(s["naam"])}</a></h3><p>{esc(s["ondertitel"])}</p>'
        f'<p class="sitebtn"><a class="btn-out cta" href="{pg.rel("sites/" + s["slug"])}" aria-label="Meer info over {esc(s["naam"])}">Meer info</a></p></div>'
        for s in sorted(lijst, key=lambda x: x["naam"].lower()))
    body = f"""{crumbs(pg, [("Handige websites", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Handige websites</h1>
  <p class="lead">Alle websites rondom eBlinqx, de Nationale Hypotheekbond en Blinqx Verzekering &amp; Hypotheek op een rij, plus de belangrijke partijen in de keten. Klik op ‘Meer info’ voor alles over de partij en de link naar hun website.</p>
  <div class="wtwhys pkaarten">{kaarten}</div>
</div></main>"""
    write("sites", layout(pg, "Handige websites", body, None,
                          "Overzicht van alle websites rondom eBlinqx, de Nationale Hypotheekbond en Blinqx Verzekering & Hypotheek."), kluis=False)


def render_banking():
    """Tegel Banking & Insurance: Hypotheekcijfer.nl en Pensioencijfer.nl."""
    pg = Page("banking-insurance")
    volg = ["hypotheekcijfer-nl", "pensioencijfer-nl", "renteadministratie-nl"]
    lijst = sorted((s for s in sites_laden() if s["slug"] in volg), key=lambda s: volg.index(s["slug"]))
    blokken = "".join(
        f'<div class="mhz-duo"><div><h2 class="wth">{esc(s["naam"])}</h2><p><strong>{esc(s["ondertitel"])}</strong></p>'
        + "".join(f"<p>{esc(t)}</p>" for t in s["tekst"])
        + f'<p class="btn-row"><a class="btn-out cta" href="{esc(s["url"])}" target="_blank" rel="noopener" aria-label="Bezoek website {esc(s["naam"])}">Bezoek website ↗</a>'
        f'<a class="btn-out" href="{pg.rel("sites/" + s["slug"])}">Meer over {esc(s["naam"])}</a></p></div>'
        + (f'<figure><img src="{pg.rel(s.get("logo") or s["afbeelding"])}" alt="{esc(s["naam"])}" loading="lazy"'
           f'{chr(32) + "style=" + chr(34) + "max-width:340px;margin:0 auto;display:block" + chr(34) if s.get("logo") else ""}></figure>'
           if (s.get("logo") or s.get("afbeelding")) else "")
        + "</div>" for s in lijst)
    leden = [("Igor Driessen", "Director Banking &amp; Financial Services", "igor-driessen", "+31620615614", "06 20 61 56 14", "igor.driessen@blinqx.tech"),
             ("Bob van Dam", "Product Enablement Manager", "bob-van-dam", "+31643811940", "06 43 81 19 40", "bob.van.dam@blinqx.tech"),
             ("Oscar Kuypers", "Business Development Manager", "oscar-kuypers", "+31628321881", "06 28 32 18 81", "oscar.kuypers@blinqx.tech"),
             ("Jeroen Oversteegen", "Non Executive Director Business Partners", "jeroen-oversteegen", "+31621247257", "06 21 24 72 57", "jeroen.oversteegen@blinqx.tech"),
             ("Jos van Driesum", "Directeur Products", "jos-van-driesum", "+31644081447", "06 44 08 14 47", "jos.van.driesum@blinqx.tech"),
             ("Dennes Roes", "Directeur Hypotheken · Founder eBlinqx Hypotheekadvies", "dennes-roes", "+31651117893", "06 51 11 78 93", "dennes.roes@blinqx.tech")]
    team = "".join(f'<div class="lid"><img src="{pg.rel("bronnen/team/" + f + ".webp")}" alt="{esc(n)}" loading="lazy">'
                   f'<h3>{esc(n)}</h3><p class="rol">{r}</p><p><a href="tel:{tel}">M: {telt}</a>{"<br><a href=" + chr(34) + "mailto:" + m + chr(34) + ">" + m + "</a>" if m else ""}</p></div>'
                   for n, r, f, tel, telt, m in leden)
    body = f"""{crumbs(pg, [("Banking &amp; Insurance", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>Banking &amp; Insurance</h1>
  <p class="lead">Oplossingen voor banken, geldverstrekkers en verzekeraars: klanten zelf inzicht geven in hun financiële situatie met één helder cijfer, en grip op het renteproces van analyse tot publicatie.</p>
  {blokken}
  <p class="mhz-tip">Meer weten? Mail <a href="mailto:relatie-vh@blinqx.tech">relatie-vh@blinqx.tech</a> of bel <a href="tel:+31207582111">020 758 21 11</a>.</p>
  <h2 class="wth">Ons team</h2>
  <div class="team">{team}</div>
</div></main>"""
    write("banking-insurance", layout(pg, "Banking & Insurance: Hypotheekcijfer.nl, Pensioencijfer.nl en Renteadministratie.nl", body, None,
                                      "Hypotheekcijfer.nl en Pensioencijfer.nl: klanten van banken en verzekeraars krijgen met één cijfer inzicht in de betaalbaarheid van hun hypotheek en in hun pensioen."))


def render_mijnhuiszaken():
    """MijnHuiszaken: klantomgeving met realtime woningaanbod (bron: aansluiten.mijnhuiszaken.nl, november 2026)."""
    pg = Page("mijnhuiszaken")
    img = lambda f, alt: f'<img src="{pg.rel("bronnen/mijnhuiszaken/" + f)}" alt="{esc(alt)}" loading="lazy">'
    voordelen = [
        ("Realtime woningaanbod", "Door de samenwerking met NVM-makelaars ziet je klant direct het nieuwste woningaanbod dat past bij "
         "zijn of haar zoekwensen, met e-mailalerts zodra er een geschikte woning op de markt komt."),
        ("Voortdurend in beeld", "Tijdens het zoeken naar een woning ben jij continu in beeld: je logo en contactgegevens staan in "
         "de omgeving van de klant én in de e-mailalerts. Zo houd je mogelijke concurrentie buiten de deur."),
        ("Inzicht in zoekgedrag", "Weet eerder dan de markt wie er in beweging komt. Je krijgt inzicht in het zoekgedrag van je "
         "klanten en kunt op het juiste moment contact opnemen."),
        ("Begeleiding bij aan- en verkoop", "Inclusief een Wwft-check, een aan- en verkoopdossier en digitaal ondertekenen."),
        ("Ook voor bestaande klanten", "Je klanten zien de geschatte waarde van hun woning en hoeveel mensen er op zoek zijn naar "
         "een woning zoals de hunne. Willen ze verhuizen? Dan weet jij het als eerste."),
        ("Contact met één klik", "Worden de plannen concreet en is advies op maat nodig, dan neemt je klant met één klik contact "
         "met je op."),
    ]
    blokken = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in voordelen)
    faq = [
        ("Wat is MijnHuiszaken?", MHZ_INTRO),
        ("Wat levert MijnHuiszaken een hypotheekadviseur op?",
         "Je bindt leads al tijdens hun oriëntatie op de woningmarkt, blijft voortdurend in beeld en krijgt inzicht in wie er "
         "gaat verhuizen. Zo bouw je een voorsprong op ten opzichte van andere adviseurs en stel je je hypotheekadvies zeker."),
        ("Hoe nodig ik klanten uit?",
         "Via een button op je website, een link in een e-mail of gewoon bij jou aan tafel. De klant maakt daarna zelf een "
         "zoekprofiel aan en ziet in zijn omgeving jouw logo en contactgegevens."),
        ("Wat kost MijnHuiszaken?",
         "Voor de klant is MijnHuiszaken gratis. Voor jou als adviseur geldt € 79,- per maand voor 1.000 klanten, plus "
         "eenmalig € 350,- voor het inrichten (tarief volgens aansluiten.mijnhuiszaken.nl, november 2026)."),
    ]
    faq_html = "".join(f'<details class="wtfaq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("MijnHuiszaken", None)])}
<main class="subpage mhz"><div class="wrap">
  <h1>MijnHuiszaken</h1>
  <p class="lead">Voorzie huizenzoekers van realtime woningaanbod en blijf vanaf dag één in beeld.</p>
  <div class="mhz-intro"><div><p>{esc(MHZ_INTRO)}</p>
    <p>Meer dan de helft van de mensen die bij je langskomen of je website bezoeken, oriënteert zich al op de woningmarkt. Met hypotheekvragen zijn ze bij jou aan het juiste adres. Met MijnHuiszaken help je ze voortaan ook met het vinden van een woning, en bouw je een voorsprong op ten opzichte van andere hypotheekadviseurs.</p>
    <p class="btn-row"><a class="btn-out cta" href="{MHZ_URL}" target="_blank" rel="noopener">Demo aanvragen of aansluiten</a>
    <a class="btn-out" href="https://mijnhuiszaken.nl/" target="_blank" rel="noopener">Bekijk het woningaanbod</a></p></div>
    <figure>{img("images-hero-desktop.webp", "Woningzoeker en hypotheekadviseur, verbonden via MijnHuiszaken")}</figure></div>
  <h2 class="wth">Bekijk de video</h2>
  {MHZ_VIDEO(pg)}
  <h2 class="wth">Waarom MijnHuiszaken?</h2>
  <div class="wtwhys">{blokken}</div>
  <div class="mhz-duo">
    <figure>{img("image-daarommhz.webp", "Hypotheekadviseur voor woningen met te-koopborden")}</figure>
    <div><h2 class="wth">Neem de regie in eigen hand</h2>
      <p>Van iedereen die bij je langskomt of je website bezoekt, oriënteert meer dan de helft zich al op de woningmarkt. Help hen voortaan ook met het vinden van een woning. Zo bouw je een grotere voorsprong op ten opzichte van andere hypotheekadviseurs, en is MijnHuiszaken ideaal om je klant bij aan- en verkoop te begeleiden.</p></div>
  </div>
  <div class="mhz-duo">
    <div><h2 class="wth">Ook voor bestaande klanten</h2>
      <p>Je klanten zien in hun dashboard de geschatte waarde van hun eigen woning, hun hypotheek, gevonden woningen en hoeveel mensen er op zoek zijn naar een woning zoals de hunne. Willen ze verhuizen? Dan weet jij dat als eerste.</p></div>
    <figure>{img("image-dashboard.webp", "Dashboard van MijnHuiszaken met woningwaarde, hypotheek, gevonden woningen en zoekopdrachten")}</figure>
  </div>
  <div class="mhz-duo">
    <div><h2 class="wth">Verstevig de band met je klant</h2>
      <p>Bind leads tijdens hun oriëntatie en stel zo je hypotheekadvies zeker. Uitnodigen is zo gebeurd: via een button op je website, een link in een e-mail of gewoon bij jou aan tafel. In MijnHuiszaken maakt de klant eenvoudig een zoekprofiel aan en vindt hij jouw logo en contactgegevens. Zo blijf je steeds in beeld, ook in de e-mailalerts met woningaanbod, en ben je altijd dichtbij voor vragen.</p></div>
    <figure>{img("image-voortdurendinthepicture.webp", "Adviseur en klant geven elkaar een hand")}</figure>
  </div>
  <div class="mhz-duo">
    <figure>{img("image-klantreis.webp", "Woningen met te-koopborden van NVM-makelaars")}</figure>
    <div><h2 class="wth">Alles voor je klant op één plek</h2>
      <p>In hun eigen online omgeving vinden je klanten alles wat ze nodig hebben: het Nederlandse woningaanbod van NVM-makelaars, filters voor hun voorkeuren, e-mailalerts, een aan- en verkoopdossier met digitaal ondertekenen, handige rekentools, hypotheeknieuws en de geschatte waarde van hun eigen woning.</p>
      <p>MijnHuiszaken koppelt woningzoekers, hun hypotheekadviseur en hun aan- of verkoopmakelaar aan elkaar, zodat ze met één klik met elkaar in contact zijn.</p></div>
  </div>
  <h2 class="wth">Tarieven</h2>
  <div class="mhz-prijs"><p class="mhz-bedrag">€ 79,- <small>per maand voor 1.000 klanten</small></p>
    <ul><li>Gratis voor de klant</li><li>Compleet woningaanbod</li><li>Rekentools</li><li>Woningwaarde berekenen</li><li>Hypotheeknieuws</li></ul>
    <p>Eenmalig inrichten: € 350,-</p>
    <p><a class="btn-out cta" href="{MHZ_URL}tarieven/" target="_blank" rel="noopener">Account aanvragen</a></p></div>
  <p class="mhz-tip">Tip: combineer MijnHuiszaken met de <a href="{pg.rel("websitetools")}">websitetools</a> op je eigen website. Bezoekers rekenen eerst zelf, zoeken daarna woningen in MijnHuiszaken, en jij blijft in beide stappen in beeld.</p>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <h2 class="wth">Eerst zien, dan geloven?</h2>
  <p>Boek vrijblijvend een online demo; binnen 20 minuten weet je hoe alles werkt. Bel <a href="tel:+31365238455">036 523 8455</a>, mail <a href="mailto:info@mijnhuiszaken.nl">info@mijnhuiszaken.nl</a> of vraag een demo aan via <a href="{MHZ_URL}contact/" target="_blank" rel="noopener">aansluiten.mijnhuiszaken.nl</a>.</p>
  <p class="src">Bron: <a href="{MHZ_URL}" target="_blank" rel="noopener">aansluiten.mijnhuiszaken.nl</a> (stand 4 november 2026). Tarieven en voorwaarden kunnen wijzigen.</p>
</div></main>"""
    write("mijnhuiszaken", layout(pg, "MijnHuiszaken: realtime woningaanbod voor je klanten", body, None,
                                  "MijnHuiszaken: klantomgeving voor hypotheekadviseurs met realtime NVM-woningaanbod, e-mailalerts, "
                                  "rekentools en woningwaarde. Bind leads vanaf de oriëntatie en blijf in beeld bij aan- en verkoop."))


def video_fig(pg, mp4, poster, naam, omschrijving, duur, bijschrift, anker="video"):
    """Eigen video (mp4 in bronnen/) met VideoObject-gegevens voor Google en AI-zoekmachines."""
    ld = json.dumps({"@context": "https://schema.org", "@type": "VideoObject", "name": naam, "description": omschrijving,
                     "thumbnailUrl": SITE_URL + poster, "contentUrl": SITE_URL + mp4, "uploadDate": "2026-11-04",
                     "duration": duur, "inLanguage": "nl-NL"}, ensure_ascii=False)
    return (f'<figure class="mhz-video" id="{anker}"><video controls preload="none" playsinline poster="{pg.rel(poster)}" width="1920" height="1080">'
            f'<source src="{pg.rel(mp4)}" type="video/mp4">Je browser kan deze video niet afspelen. '
            f'<a href="{pg.rel(mp4)}">Download de video (mp4)</a>.</video><figcaption>{esc(bijschrift)}</figcaption></figure>'
            f'<script type="application/ld+json">{ld}</script>')


def render_finrust():
    """Alle video's van het YouTube-kanaal FinRust (tools/finrust_videos.json, bijgewerkt door tools/yt_sync.py)."""
    f = os.path.join(TOOLS, "finrust_videos.json")
    if not os.path.exists(f):
        return
    d = json.load(open(f, encoding="utf8"))
    pg = Page("video/finrust")
    kaarten = "".join(
        f'<div class="video" id="v-{esc(v["id"])}" data-zoek="{esc(v["t"].lower())}"><div class="frame" data-yt="{esc(v["id"])}">'
        f'<img src="{pg.rel("assets/video/" + v["id"] + ".jpg")}" alt="" loading="lazy">'
        f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>'
        f'<h3><a href="https://www.youtube.com/watch?v={esc(v["id"])}" target="_blank" rel="noopener">{esc(v["t"])}</a></h3>'
        f'<p>FinRust{" · " + fmt_date(date.fromisoformat(v["datum"])) if v.get("datum") else ""}</p></div>' for v in d["videos"])
    body = f"""{crumbs(pg, [("Video's", "video"), ("FinRust", None)])}
<main class="subpage"><div class="wrap">
  <h1>FinRust-video's</h1>
  <p class="lead">Alle {len(d["videos"])} instructievideo's van <a href="https://finrust.nl/" target="_blank" rel="noopener">FinRust</a>: adviessoftware die adviseurs met een snel proces en heldere rapporten helpt klanten beter en completer te bedienen, ‘execution only’ te vermijden en onderhoud op de hypotheek- en verzekeringsportefeuille vorm te geven. Video's worden pas van YouTube geladen als je op afspelen klikt.</p>
  <p><label for="frfilter"><strong>Filter op onderwerp:</strong></label><br><input id="frfilter" type="search" placeholder="bijvoorbeeld lijfrente, ORV, pensioen" style="width:100%;max-width:420px;padding:10px;font:inherit;border:1px solid #999;border-radius:4px"> <span id="frtel" aria-live="polite"></span></p>
  <div class="vgrid">{kaarten}</div>
  <p class="src">Bron: <a href="{d["url"]}" target="_blank" rel="noopener">YouTube-kanaal FinRust</a>. Nieuwe video's komen er automatisch bij.</p>
</div></main>
<script>
document.addEventListener("click", e => {{
  const b = e.target.closest("[data-yt] .play"); if (!b) return;
  const f = b.closest("[data-yt]");
  f.innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${{f.dataset.yt}}?autoplay=1&rel=0" title="Video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
}});
const fi = document.getElementById("frfilter"), tel = document.getElementById("frtel");
fi.addEventListener("input", () => {{
  const q = fi.value.toLowerCase().trim(); let n = 0;
  document.querySelectorAll("[data-zoek]").forEach(k => {{ const ok = !q || q.split(/\s+/).every(w => k.dataset.zoek.includes(w)); k.hidden = !ok; if (ok) n++; }});
  tel.textContent = q ? n + " video's" : "";
}});
</script>"""
    write("video/finrust", layout(pg, "FinRust-video's: instructievideo's adviessoftware", body, None,
                                  f"Alle {len(d['videos'])} instructievideo's van FinRust: hypotheek, pensioen, lijfrente, ORV, "
                                  "vermogen en financiële planning in de adviessoftware van FinRust."))


def render_websitetools():
    """Websitetools: rekentools voor op de website van de adviseur (bronnen/websitetools.json)."""
    f = os.path.join(SRC, "websitetools.json")
    if not os.path.exists(f):
        return
    data = json.load(open(f, encoding="utf8"))
    pg = Page("websitetools")
    groups = "".join(
        f'<section class="wtgroup"><h2>{esc(g["g"])}</h2><div class="wtbtns">'
        + "".join(f'<a class="wtbtn" href="{esc(t["url"])}" target="_blank" rel="noopener">{esc(t["t"])} <span aria-hidden="true">↗</span></a>'
                  for t in g["tools"]) + "</div></section>"
        for g in data["groepen"])
    n = sum(len(g["tools"]) for g in data["groepen"])
    contact = " of ".join(f'{esc(c["naam"])} (<a href="mailto:{esc(c["mail"])}">{esc(c["mail"])}</a>)' for c in data["contact"])
    waarom = [
        ("Meer en betere leads",
         "Wie rekent, heeft een concrete vraag. Direct na de uitkomst kan de bezoeker een afspraak of adviesgesprek aanvragen. "
         "De aanvraag komt rechtstreeks binnen in de leadinbox van eBlinqx Connect en/of in je mailbox, met niet alleen "
         "contactgegevens maar ook de situatie van de klant. Zo ga je het eerste gesprek goed voorbereid in."),
        ("Inzicht in je bezoekers",
         "Je ziet waar bezoekers mee bezig zijn: hun maximale hypotheek, oversluiten, aflossen of verduurzamen. "
         "Gebruik dat inzicht voor je marketing en om klanten op het juiste moment te benaderen."),
        ("Een volwassen, professionele website",
         "Actuele rentes en betrouwbare berekeningen laten zien dat je kantoor bij de tijd is. Een website die meer doet dan "
         "informeren, wekt vertrouwen, juist bij een financiële beslissing van deze omvang."),
        ("Beter gevonden in Google (SEO)",
         "Rekentools zijn waardevolle, interactieve inhoud. Bezoekers blijven langer, komen terug voor de actuele rentes en zoeken "
         "op termen als ‘maximale hypotheek berekenen’ of ‘actuele hypotheekrente’. Dat zijn signalen die zoekmachines belonen."),
        ("Zichtbaar in AI-zoekmachines (GEO)",
         "ChatGPT, Gemini en Copilot beantwoorden hypotheekvragen steeds vaker zelf en verwijzen daarbij naar bronnen. Pagina’s met "
         "heldere uitleg, actuele cijfers en een rekenmodule zijn precies het soort bron dat zij noemen."),
        ("Klanten blijven betrokken",
         "Ook na het afsluiten: met de bespaarcheck en de tools voor aflossen en verduurzamen hebben bestaande klanten een reden om "
         "terug te komen, en heb jij een natuurlijke aanleiding voor een vervolggesprek."),
    ]
    waarom_html = "".join(f'<div class="wtwhy"><h3>{esc(t)}</h3><p>{esc(x)}</p></div>' for t, x in waarom)
    tips = [
        "Geef elke tool een eigen pagina met een duidelijke titel en een korte uitleg in je eigen woorden, bijvoorbeeld "
        "‘Bereken je maximale hypotheek’. Dat helpt zowel Google als AI-zoekmachines om je pagina te begrijpen en te tonen.",
        "Zet direct onder de uitkomst een duidelijke vervolgstap, zoals ‘Plan een vrijblijvend oriëntatiegesprek’.",
        "Laat de aanvragen uit de tools rechtstreeks binnenkomen in de leadinbox van eBlinqx Connect en/of in je e-mail, zodat "
        "elke lead direct in je werkproces staat.",
        "Link vanuit je nieuwsberichten en blogs naar de tools, bijvoorbeeld bij een renteverandering naar het renteoverzicht.",
        "Vermeld bij elke tool dat de uitkomst een indicatie is en geen advies, en verwijs voor persoonlijk advies naar een gesprek.",
    ]
    tips_html = "".join(f"<li>{esc(t)}</li>" for t in tips).replace(
        "de leadinbox van eBlinqx Connect",
        f'<a href="{pg.rel("kennisbank/leadinbox-gebruiken-vanaf-contactformulier-op-website")}">de leadinbox van eBlinqx Connect</a>')
    faq = [
        ("Wat zijn websitetools?",
         f"Websitetools zijn rekentools die je op de website van je advieskantoor plaatst. Bezoekers berekenen er zelf hun maximale "
         f"hypotheek, maandlasten, besparing bij aflossen of oversluiten, of bekijken de actuele hypotheekrentes. Er zijn {n} tools in "
         f"{len(data['groepen'])} rubrieken. Aanvragen van bezoekers komen rechtstreeks binnen in de leadinbox van eBlinqx Connect "
         f"en/of in je e-mail."),
        ("Waarom zijn rekentools belangrijk voor een hypotheekadviseur?",
         "Woningzoekers oriënteren zich online, vaak al lang voordat ze een adviseur bellen. Met rekentools op je eigen website help je "
         "ze in die fase al verder, maak je je kantoor zichtbaar en zet je bezoekers om in concrete adviesaanvragen."),
        ("Helpen rekentools om beter gevonden te worden?",
         "Ja. Interactieve en actuele inhoud zorgt ervoor dat bezoekers langer blijven en terugkomen, en sluit aan op veelgebruikte "
         "zoekvragen. Met een duidelijke uitleg bij elke tool wordt je pagina ook eerder als bron genoemd door AI-zoekmachines."),
        ("Zijn de uitkomsten een hypotheekadvies?",
         "Nee. De uitkomsten zijn een indicatie op basis van de gegevens die de bezoeker invult. Voor een persoonlijk advies is altijd "
         "een gesprek met een adviseur nodig."),
        ("Hoe plaats ik een rekentool op mijn website?",
         "De rekentools worden in de huisstijl van je kantoor op je website geplaatst. Neem contact op met Blinqx Verzekering & "
         "Hypotheek; de contactgegevens staan onderaan deze pagina."),
    ]
    faq_html = "".join(f"<details class=\"wtfaq\"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in faq)
    faq_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Websitetools", None)])}
<main class="subpage"><div class="wrap">
  <h1>Websitetools</h1>
  <p class="lead">Rekentools voor op je eigen website: laat bezoekers zelf hun maximale hypotheek, maandlasten of de actuele rentes bekijken en zet ze zo om in leads. Er zijn {n} tools in {len(data["groepen"])} rubrieken. Klik op een tool om een voorbeeld te bekijken (opent in een nieuw tabblad).</p>
  <h2 class="wth">Bekijk de video</h2>
  {video_fig(pg, "bronnen/websitetools/rekentools-video.mp4", "bronnen/websitetools/rekentools-video.webp",
             "Rekentools voor op de website van de adviseur",
             "Een compleet pakket rekentools van Blinqx voor de website van je kantoor, gekoppeld aan eBlinqx: hypotheek berekenen, "
             "aflossen en besparen, woning en verduurzamen, klantinzicht.", "PT2M36S",
             "Rekentools voor op de website: het complete pakket per categorie, gekoppeld aan eBlinqx (2,5 minuut).")}
  <h2 class="wth">Waarom rekentools op je website?</h2>
  <p>Een hypotheek begint online. Woningzoekers oriënteren zich vaak al weken voordat ze een adviseur bellen: hoeveel kan ik lenen, wat worden mijn maandlasten, wat doet de rente? Met de rekentools geef je die antwoorden op je eigen website en ben jij het kantoor dat ze als eerste verder helpt.</p>
  <div class="wtwhys">{waarom_html}</div>
  <h2 class="wth">De rekentools</h2>
  {groups}
  <h2 class="wth">Zo haal je er het meeste uit</h2>
  <ul class="wttips">{tips_html}</ul>
  <h2 class="wth">Veelgestelde vragen</h2>
  {faq_html}
  <script type="application/ld+json">{faq_ld}</script>
  <div class="oud wtnote" role="note">{esc(data["disclaimer"])}</div>
  <p class="mhz-tip">Zie de rekentools live op een kantoorwebsite: bekijk ons <a href="{pg.rel("demo-kantoor")}">demo-kantoor</a>.</p>
  <h2 class="wth">Websitetools op je eigen website?</h2>
  <p>De rekentools zijn in de huisstijl van je kantoor op je eigen website te plaatsen. Neem voor meer informatie contact op met {contact}.</p>
  <p class="src">Bron: <a href="{esc(data["bron"])}" target="_blank" rel="noopener">verzekeringhypotheek.blinqx.tech</a> (stand {fmt_date(date.fromisoformat(data["opgehaald"]))}).</p>
</div></main>"""
    write("websitetools", layout(pg, "Websitetools: rekentools voor je website", body, None,
                                 "Rekentools voor de website van je advieskantoor: meer en betere leads, inzicht in bezoekers, een professionele "
                                 "uitstraling en betere vindbaarheid in Google en AI-zoekmachines. Hypotheek berekenen, rentes, aflossen en verduurzamen."))


def downloads_items():
    """Pdf's uit tools/downloads.json: lokaal (bronnen/wayback/wp-content/uploads) of anders uit het archief."""
    f = os.path.join(TOOLS, "downloads.json")
    if not os.path.exists(f):
        return []
    cdx = {}
    cf = os.path.join(WAYBACK_DIR, "_cdx.json")
    if os.path.exists(cf):
        for ts, orig, _ in json.load(open(cf)):
            if orig.lower().endswith(".pdf"):
                cdx[orig.split("/wp-content/uploads/")[-1]] = (ts, orig.replace("http://", "https://"))
    out = []
    for rub in json.load(open(f, encoding="utf8"))["rubrieken"]:
        for pad, titel in rub["items"]:
            lokaal = os.path.join(WAYBACK_DIR, "wp-content", "uploads", pad)
            y, m = pad.split("/")[:2]
            item = {"rub": rub["naam"], "t": titel, "pad": pad, "datum": f"{MAANDEN[int(m) - 1]} {y}"}
            if os.path.exists(lokaal):
                item["href"] = "bronnen/wayback/wp-content/uploads/" + pad
                item["kb"] = max(1, os.path.getsize(lokaal) // 1024)
            elif pad in cdx:
                ts, orig = cdx[pad]
                item["url"] = f"https://web.archive.org/web/{ts}id_/{orig}"
            else:
                continue
            out.append(item)
    return out


def render_downloads():
    items = downloads_items()
    if not items:
        return
    pg = Page("downloads")
    rubs = []
    for naam in dict.fromkeys(i["rub"] for i in items):
        lis = []
        for i in items:
            if i["rub"] != naam:
                continue
            href = pg.rel(i["href"]) if i.get("href") else i["url"]
            meta = i["datum"] + (f' · pdf, {i["kb"]:,} kB'.replace(",", ".") if i.get("kb") else " · pdf")
            lis.append(f'<li><a class="dl" href="{esc(href)}" target="_blank" rel="noopener">'
                       f'<svg class="ic"><use href="#i-file"/></svg><span><b>{esc(i["t"])}</b><small>{esc(meta)}</small></span></a></li>')
        rubs.append(f'<section class="dlgroup"><h2>{esc(naam)}</h2><ul class="dllist">{"".join(lis)}</ul></section>')
    body = f"""{crumbs(pg, [("Downloads", None)])}
<main class="subpage"><div class="wrap">
  <h1>Downloads</h1>
  <p class="lead">Handleidingen, voorbeeldrapporten en oudere releasenotes als pdf. Een deel van deze documenten stamt uit de tijd van Elements en kan verouderd zijn; kijk voor de actuele werkwijze in de <a href="{pg.rel("kennisbank")}">kennisbank</a>.</p>
  {"".join(rubs)}
</div></main>"""
    write("downloads", layout(pg, "Downloads", body, None, "Handleidingen, voorbeeldrapporten en oudere releasenotes van eBlinqx / Elements als pdf."))


def render_nieuwsbrief():
    pg = Page("nieuwsbrief")
    body = f"""{crumbs(pg, [("Nieuwsbrief", None)])}
<main class="subpage"><div class="wrap">
  <h1>Op de hoogte blijven?</h1>
  <p class="lead">Meld je aan voor de nieuwsbrief van Blinqx Verzekering &amp; Hypotheek en ontvang regelmatig tips, nieuws en de belangrijkste releases van eBlinqx.</p>
  <div id="nb-form"></div>
  <p><button type="button" class="btn-out cta" data-nieuwsbrief>Aanmelden voor de nieuwsbrief</button></p>
  <p id="nb-fallback" hidden>Aanmelden kan ook via de website van <a href="https://verzekeringhypotheek.blinqx.tech/" target="_blank" rel="noopener">Blinqx Verzekering &amp; Hypotheek</a> (onderaan de pagina).</p>
  <p class="src">Het aanmeldformulier wordt pas geladen als je op de knop klikt. Je gegevens worden verwerkt door Blinqx Verzekering &amp; Hypotheek via HubSpot. Afmelden kan altijd via de link in de nieuwsbrief (zie ook <a href="{pg.rel("kennisbank/nieuwsbrief-afmelden")}">nieuwsbrief afmelden</a>).</p>
</div></main>"""
    write("nieuwsbrief", layout(pg, "Nieuwsbrief", body, None, "Meld je aan voor de nieuwsbrief van Blinqx Verzekering & Hypotheek."))


def render_privacy():
    pg = Page("privacy")
    body = f"""{crumbs(pg, [("Privacy", None)])}
<main class="subpage"><div class="wrap"><article class="content" style="max-width:780px">
  <h1>Privacy en cookies</h1>
  <p>Deze supportsite plaatst zelf geen cookies en gebruikt geen statistieken of advertentiediensten. Een paar onderdelen komen van andere diensten; die worden zo veel mogelijk pas geladen als je ze zelf gebruikt.</p>
  <h2>Diensten van derden op deze site</h2>
  <ul>
    <li><b>Chatknop</b> (rechtsonder): de chatbot van Blinqx. Wat je in de chat typt, wordt door Blinqx verwerkt. De chatknop onthoudt in je browser alleen waar je de knop hebt neergezet.</li>
    <li><b>Nieuwsbrief</b>: het aanmeldformulier van Blinqx Verzekering &amp; Hypotheek (HubSpot) wordt pas geladen als je op de aanmeldknop klikt.</li>
    <li><b>Scherm delen</b> (contactpagina): verbinding via ISL Online, alleen als je een sessiecode invult.</li>
    <li><b>Video's en e-learnings</b>: YouTube (in de privacyvriendelijke modus) en Storylane worden pas geladen als je op afspelen of starten klikt.</li>
    <li><b>Rekentools en trainingen</b>: openen op de website van Hypotheekbond en de Blinqx Academy.</li>
    <li><b>Afbeeldingen</b> die nog niet op deze site staan, worden geladen uit het Internet Archive (web.archive.org).</li>
  </ul>
  <h2>Privacyverklaring en cookieverklaring van Blinqx</h2>
  <p>Voor de verwerking van persoonsgegevens door Blinqx gelden de <a href="https://verzekeringhypotheek.blinqx.tech/privacy-statement" target="_blank" rel="noopener">privacyverklaring</a> en de <a href="https://verzekeringhypotheek.blinqx.tech/cookieverklaring" target="_blank" rel="noopener">cookieverklaring</a> van Blinqx Verzekering &amp; Hypotheek.</p>
</article></div></main>"""
    write("privacy", layout(pg, "Privacy en cookies", body, None, "Welke diensten deze supportsite gebruikt en waar je de privacyverklaring van Blinqx vindt."))


def render_404():
    # GitHub Pages serveert 404.html vanaf de root; absolute paden zijn daar niet bekend, dus root-relatief.
    pg = Page("")
    body = """<main class="subpage"><div class="wrap">
  <h1>Pagina niet gevonden</h1>
  <p>Deze pagina bestaat (nog) niet in de herstelde supportsite. Gebruik de zoekfunctie hierboven of ga terug naar de <a href="/index.html">homepage</a>.</p>
  <div id="sugg" hidden><h2>Bedoelde je misschien:</h2><ul class="sugg"></ul></div>
</div></main>
<script src="zoeken/zoekindex.js"></script>
<script>
(function () {
  var IDX = window.ZOEKINDEX || [];
  var strip = function (s) { return (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); };
  var words = strip(decodeURIComponent(location.pathname)).split(/[^a-z0-9]+/)
    .filter(function (w) { return w.length > 2 && ["fasterforward", "support", "kennisbank", "index", "html", "categorien", "page"].indexOf(w) < 0; });
  if (!words.length) return;
  var res = IDX.map(function (r) {
    var t = " " + strip(r.t).replace(/[^a-z0-9]+/g, " ") + " ", h = strip(r.h), sc = 0;
    words.forEach(function (w) { if (h.indexOf(w) >= 0) sc += 3; if (t.indexOf(" " + w) >= 0) sc += 2; });
    if (sc && r.k === "kennisbank") sc += 2;
    return [sc, r];
  }).filter(function (x) { return x[0] >= Math.min(4, words.length * 2); }).sort(function (a, b) { return b[0] - a[0]; }).slice(0, 6);
  if (!res.length) return;
  var ul = document.querySelector("#sugg ul");
  res.forEach(function (x) {
    var li = document.createElement("li"), a = document.createElement("a");
    a.href = x[1].ext ? x[1].h : document.querySelector(".brand").getAttribute("href").replace("index.html", "") + x[1].h;
    a.textContent = x[1].t; li.appendChild(a); ul.appendChild(li);
  });
  document.getElementById("sugg").hidden = false;
})();
</script>"""
    html_ = layout(pg, "Pagina niet gevonden", body)
    html_ = re.sub(r'(href|src|action)="(?!https?:|mailto:|tel:|#|/)([^"]*)"', lambda m: f'{m.group(1)}="{SITE_BASE}{m.group(2)}"', html_)
    html_ = html_.replace('href="/index.html"', f'href="{SITE_BASE}index.html"')
    write("404.html", html_)


def redirect_doel(path, cats):
    """Oud adres -> (doelpad, zoekterm of None). None als er geen zinnig doel is."""
    p = path.strip("/")
    if re.match(r"(wp-|feed|comments|xmlrpc)", p) or "wp-login" in p:
        return None
    m = re.match(r"(.*)/embed$", p)
    if m:
        return (m.group(1), None)
    m = re.match(r"tags?/([^/]+)", p)
    if m:
        return ("zoeken", m.group(1).replace("-", " "))
    p = re.sub(r"/page/\d+$", "", p)
    vast = {"category/release": "releasenotes", "category/algemeen": "nieuws", "categorien/elements": "kennisbank",
            "categorien/eblinqx": "kennisbank"}
    if p in vast:
        return (vast[p], None)
    if os.path.exists(os.path.join(ROOT, p, "index.html")):
        return (p, None)
    # oude (sub)categorie: best passende huidige categorie of subcategorie op naam
    slug = re.sub(r"^(category|categorien)/", "", p)
    slug = re.sub(r"^artikelen-?|\d+$|-(eblinqx|elements)\d*$", "", slug)
    woorden = set(slug.split("-")) - {""}
    best, score = None, 0
    for cname, c in cats.items():
        kand = [(cname, cat_target(cats, cname))] + [(sn, sub_target(cats, cname, sb)) for sn, sb in c["subs"].items() if sb["items"]]
        for naam, doel in kand:
            n = set(slugify(naam).split("-"))
            sc = len(woorden & n) / max(1, len(woorden | n))
            if sc > score and os.path.exists(os.path.join(ROOT, doel, "index.html")):
                best, score = doel, sc
    return (best if score >= 0.5 else "kennisbank", None)


def render_redirects(cats):
    """Doorverwijzingen voor oude adressen die geen eigen pagina meer hebben (tags, paginering, oude categorieën)."""
    from urllib.parse import quote
    oud = set()
    s = open(os.path.join(SRC, "inventaris.html"), encoding="utf8").read()
    for d in json.loads(re.search(r"const DATA = (\[.*?\]);\n", s, re.S).group(1)):
        oud.add(d["u"])
    cf = os.path.join(WAYBACK_DIR, "_cdx.json")
    if os.path.exists(cf):
        oud |= {o for _, o, m in json.load(open(cf)) if "html" in (m or "")}
    # Doorverwijzingen die al op de oude site stonden (plugin Redirection, uit de databaseback-up)
    oudsite = {}
    rf = os.path.join(WPDB_DIR, "doorverwijzingen.json")
    if os.path.exists(rf):
        for r in json.load(open(rf, encoding="utf8")):
            oudsite[r["van"]] = r["naar"]
            oud.add(BASE + "/" + r["van"] + "/")
    for van, naar in VERVANGEN.items():
        oudsite[van] = naar
        oud.add(BASE + "/" + van + "/")
    n = 0
    for u in sorted(oud):
        path = re.sub(r"^https?://(www\.)?support\.fasterforward\.nl", "", u.split("#")[0].split("?")[0]).strip("/")
        if not path or os.path.exists(os.path.join(ROOT, path, "index.html")) or re.search(r"\.\w{2,4}$", path):
            continue
        naar = oudsite.get(path)
        if naar is not None and not naar.startswith("http"):
            naar = naar.strip("/")
            doel = (naar, None) if (naar == "" or os.path.exists(os.path.join(ROOT, naar, "index.html"))) else redirect_doel(naar, cats)
        else:
            doel = redirect_doel(path, cats)
        if not doel or doel[0] == path:
            continue
        pg = Page(path)
        href = pg.rel(doel[0]) + (f"?q={quote(doel[1])}" if doel[1] else "")
        absu = SITE_URL + (doel[0] + "/" if doel[0] else "") + (f"?q={quote(doel[1])}" if doel[1] else "")
        write(path, f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>Doorverwijzen… - Blinqx Support</title>
<meta name="robots" content="noindex"><link rel="canonical" href="{esc(absu)}">
<meta http-equiv="refresh" content="0; url={esc(href)}">
<script>location.replace({json.dumps(href)} + location.hash);</script></head>
<body><p>Deze pagina is verhuisd. Ga naar <a href="{esc(href)}">de nieuwe pagina</a>.</p></body></html>
""", kluis=False)
        n += 1
    print(f"doorverwijzingen: {n}")


LASTMOD = os.path.join(TOOLS, "sitemap_lastmod.json")


def render_sitemap(pages):
    """sitemap.xml met <lastmod>. Per pagina wordt een hash van de inhoud bewaard in tools/sitemap_lastmod.json; verandert
    de inhoud, dan wordt lastmod de builddatum. Eerste keer: de wijzigingsdatum uit de WordPress-database, anders vandaag."""
    import hashlib, datetime
    vandaag = datetime.date.today().isoformat()
    wp = {}
    wpf = os.path.join(WPDB_DIR, "paginas.json")
    if os.path.exists(wpf):
        for d in json.load(open(wpf, encoding="utf8")):
            m = re.fullmatch(r"(\d{1,2}) (\w+) (\d{4})", (d.get("gewijzigd") or "").strip())
            if m and m.group(2) in MAANDEN:
                wp[d["pad"].strip("/")] = f"{m.group(3)}-{MAANDEN.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}"
    oud = json.load(open(LASTMOD, encoding="utf8")) if os.path.exists(LASTMOD) else {}
    nieuw = {}
    for f in glob.glob(os.path.join(ROOT, "**", "index.html"), recursive=True):
        rel = os.path.relpath(os.path.dirname(f), ROOT).replace(os.sep, "/")
        if rel.split("/")[0] in ("bronnen", "tools", "zoeken", "assets", ".github"):
            continue
        with open(f, "rb") as fh:
            inhoud = fh.read()
        if b'http-equiv="refresh"' in inhoud[:600]:
            continue  # doorverwijzing, geen eigen pagina
        u = "" if rel == "." else rel
        h = hashlib.sha1(inhoud).hexdigest()[:16]
        vorig = oud.get(u)
        if vorig and vorig["h"] == h:
            nieuw[u] = vorig
        else:
            nieuw[u] = {"h": h, "d": vandaag if vorig else min(wp.get(u, vandaag), vandaag)}
    with open(LASTMOD, "w", encoding="utf8") as fh:
        json.dump(dict(sorted(nieuw.items())), fh, ensure_ascii=False, indent=0)
        fh.write("\n")
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"  <url><loc>{SITE_URL}{u + '/' if u else ''}</loc><lastmod>{nieuw[u]['d']}</lastmod></url>" for u in sorted(nieuw)]
    xml.append("</urlset>")
    write("sitemap.xml", "\n".join(xml) + "\n")
    with open(os.path.join(ROOT, "robots.txt"), "w", encoding="utf8") as fh:
        fh.write(f"User-agent: *\nAllow: /\nDisallow: /tools/\n\nSitemap: {SITE_URL}sitemap.xml\n")


# ---------------------------------------------------------------- main

def clean_output():
    for d in OUTDIRS:
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    # losse artikelmappen in de root (alles met een gegenereerde index.html en markering)
    for d in os.listdir(ROOT):
        f = os.path.join(ROOT, d, ".generated")
        if os.path.isfile(f):
            shutil.rmtree(os.path.join(ROOT, d))


def main():
    clean_output()
    pages = load_sources()
    cats, feeds = build_structure(pages)

    shutil.copytree(os.path.join(TOOLS, "assets"), os.path.join(ROOT, "assets"))

    n = {"article": 0, "cat": 0, "sub": 0}
    for p in pages.values():
        if not p.get("skip") and p.get("role"):
            PAGES_BY_PATH[p["path"]] = p
    for p in pages.values():
        if p.get("skip"):
            continue
        if p.get("role") == "article":
            render_article(cats, feeds, p); n["article"] += 1
    for name in cats:
        if cats[name]["subs"] or cats[name]["loose"]:
            render_category(cats, name); n["cat"] += 1
            for sub in cats[name]["subs"].values():
                if sub["items"]:
                    render_sub(cats, name, sub); n["sub"] += 1
    for name, items in feeds.items():
        render_feed(name, items)
    render_kennisbank(cats)
    render_video()
    render_videopaginas(pages)
    render_finrust()
    render_elearning()
    render_fastlane()
    render_releasenotes_overig()
    render_trainingen()
    render_procesversneller()
    render_websitetools()
    render_mijnhuiszaken()
    render_yesco()
    render_toolsvoorvastgoed()
    render_woningwaarderapport()
    render_actiefbeheerscan()
    render_hypotheekrenteapp()
    render_partners()
    render_finly()
    render_demokantoor()
    render_sites()
    render_banking()
    render_downloads()
    render_nieuwsbrief()
    render_privacy()
    render_search(pages, cats)
    render_home(cats, feeds, pages)
    render_404()
    render_redirects(cats)
    import seo
    info = seo.uitvoeren(ROOT, SITE_URL)
    kb = sorted((u for u in info if u.startswith("kennisbank/")), key=lambda u: info[u]["h1"].lower())
    seo.llms_txt(ROOT, SITE_URL, info, [
        ("Start", ["", "kennisbank", "contact", "zoeken"]),
        ("Partners", ["partners"] + sorted(u for u in info if u.startswith("partners/"))),
        ("Productinformatie", ["websitetools", "mijnhuiszaken", "yes-co", "tools-voor-vastgoed", "woningwaarderapport",
                               "actiefbeheerscan", "hypotheekrente-app", "finly-crm", "demo-kantoor", "banking-insurance", "procesversneller"]),
        ("Handige websites", ["sites"] + sorted(u for u in info if u.startswith("sites/"))),
        ("Releasenotes", ["releasenotes", "releasenotes-hypotheekadvies", "releasenotes-finconnect", "releasenotes-dias"]),
        ("Nieuws, tips en leren", ["nieuws", "tips", "elearning", "video", "trainingen", "downloads"]),
        ("Beleid", ["supportbeleid", "opdrachtenbeleid", "klachtenbeleid", "wensenbeleid", "privacy"]),
        ("Kennisbank-artikelen", kb),
    ])
    render_sitemap(pages)

    # markeer root-mappen met gegenereerde inhoud zodat een volgende build ze kan opruimen
    for p in pages.values():
        if not p.get("skip") and p.get("role") and p["path"] and "/" not in p["path"]:
            open(os.path.join(ROOT, p["path"], ".generated"), "w").close()
    print(f"artikelen: {n['article']}, categorieën: {n['cat']}, subcategorieën: {n['sub']}, "
          f"nieuws: {len(feeds['Nieuws'])}, tips: {len(feeds['Tips'])}, releasenotes: {len(feeds['Release notes'])}")


if __name__ == "__main__":
    main()
