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
REPLAYS = {
    "webinar-nieuwe-feature-mytp": "https://fasterforward.webinargeek.com/watch/replay/2652088/faaf06952e67e0ce558425566f97772a/",
}
# Pad waaronder de site draait (voor 404.html). GitHub Pages: /<repo>/; eigen domein: /
SITE_BASE = os.environ.get("SITE_BASE", "/fasterforward-support/")
WAYBACK_DIR = os.path.join(SRC, "wayback")      # uitvoer van tools/wayback-ophalen.py
LIVE_DIR = os.path.join(SRC, "live-2026-10-20")  # pagina's van de live site, 20 oktober 2026
SKIP_PATH = re.compile(r"^(wp-content|wp-includes|wp-json|wp-admin|feed|comments|author|tag|tags|page|xmlrpc|"
                       r"search|\?|.*?/feed$|.*?/page/\d+$|.*?/amp$|.*?/embed$)")
FEEDS = {"Nieuws": "nieuws", "Tips": "tips", "Release notes": "releasenotes"}
OUTDIRS = ["releasenotes-hypotheekadvies", "elearning", "video", "kennisbank", "categorien", "category", "nieuws", "tips", "releasenotes", "zoeken",
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
        p = get(BASE + "/" + rel + ("/" if rel else ""))
        if p.get("raw"):
            continue
        try:
            doc = open(f, encoding="utf8", errors="replace").read()
        except OSError:
            continue
        if "<html" not in doc[:3000].lower():
            continue
        p["raw"] = htmlclean.extract(doc)
        p["rawsrc"] = "wayback"
        if rel.startswith("kennisbank/"):
            p["c"] = p["c"] or "kennisbank"

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
        if p["path"] in ("kennisbank", "video", "zoeken", "categorien", "category"):
            p["skip"] = True  # overzichtspagina's maken we zelf
            continue
        if "/page/" in p["u"] or p["path"].startswith(("tag/", "tags/")):
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
    for f in feeds.values():
        f.sort(key=lambda p: (p["posted"] or p["updated"] or wb_date(p) or date(1900, 1, 1)), reverse=True)
    return cats, feeds


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
       ("Releasenotes Hypotheekadvies", "releasenotes-hypotheekadvies"), ("Releasenotes Connect", "releasenotes"),
       ("Trainingen", "trainingen"), ("Contact support", "contact"),
       ("Overig support", "https://verzekeringhypotheek.blinqx.tech/support"),
       ("Overig contact", "https://verzekeringhypotheek.blinqx.tech/contact")]


# Openbaar adres van de site (voor de deelknoppen als JavaScript uit staat; met JavaScript wordt het echte adres gebruikt).
SITE_URL = os.environ.get("SITE_URL", "https://jeroen-o.github.io/fasterforward-support/")


def share_block(pg, title, description):
    from urllib.parse import quote
    url = page_url(pg)
    t = title or "Blinqx Support"
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
    t = title or "Blinqx Support"
    u = page_url(pg)
    img = SITE_URL + "assets/og-image.png"
    return "\n".join([
        f'<meta name="description" content="{esc(d)}">',
        f'<link rel="canonical" href="{esc(u)}">',
        '<meta property="og:site_name" content="Blinqx Support">',
        '<meta property="og:locale" content="nl_NL">',
        f'<meta property="og:type" content="{"website" if not pg.path else "article"}">',
        f'<meta property="og:title" content="{esc(t)}">',
        f'<meta property="og:description" content="{esc(d)}">',
        f'<meta property="og:url" content="{esc(u)}">',
        f'<meta property="og:image" content="{img}">',
        '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
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
    </nav>
  </div>
</footer>
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
        for cand in (rel, "bronnen/wayback/" + rel):
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
    h = re.sub(r'(href|src)="IMG:([^"]+)"', lambda m: f'{m.group(1)}="{esc(resolve_img(pg, html.unescape(m.group(2))))}"', h)
    h = re.sub(r'href="SITE:([^"]*)"', lambda m: f'href="{esc(resolve_site(pg, html.unescape(m.group(1))))}"', h)
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


def kluis_tekst(t):
    return KLUIS_RE.sub(KLUIS, t)


def kluis_html(doc):
    parts = re.split(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", doc, flags=re.S | re.I)
    for i in range(0, len(parts), 2):
        parts[i] = kluis_tekst(parts[i])
    # ook in de deeltekst (data-msg) en de beschrijving van de pagina
    out = "".join(parts)
    out = re.sub(r'((?:data-msg|data-t|content)=")([^"]*)"', lambda m: m.group(1) + kluis_tekst(m.group(2)) + '"', out)
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
            src = pg.rel(rel) if rel and os.path.exists(os.path.join(ROOT, rel)) else (im["w"] or wayback_img(im["src"]))
            figs.append(f'<figure><a href="{esc(src)}" target="_blank" rel="noopener"><img src="{esc(src)}" alt="{esc(im["alt"])}" loading="lazy" onerror="this.closest(\'figure\').remove()"></a>'
                        f'{f"<figcaption>{esc(im["alt"])}</figcaption>" if im["alt"] else ""}</figure>')
        imgs = '<section class="figs"><h2>Afbeeldingen bij dit artikel</h2>' + "".join(figs) + "</section>"
    shot = ""  # screenshots van de Wayback-opname worden niet meer getoond; de echte afbeeldingen staan in het artikel
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
                '<p>Wij zijn bereikbaar op werkdagen van 8:30 tot 17:00</p></aside>')
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
      {f'<div class="oud" role="note"><strong>Let op: mogelijk verouderd.</strong> Dit artikel is voor het laatst bijgewerkt {esc(oud)} en beschrijft mogelijk een oudere versie van de software (Elements). Schermen en werkwijze kunnen in eBlinqx afwijken. Twijfel je? <a href="{pg.rel("contact")}">Neem contact op met support</a>.</div>' if oud else ""}
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
        return (f'<article class="card"><h3><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></h3>'
                f'{f"<p class=\"date\">{fmt_date(d)}</p>" if d else ""}'
                f'{f"<p>{esc(x["excerpt"])}</p>" if x.get("excerpt") else ""}'
                f'<a class="readmore" href="{pg.rel(x["path"])}">Lees verder</a></article>')

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
  <h2 class="feed-h">{esc(h2)}</h2>
  <p>{esc(intro)} {len(items)} berichten.</p>
  {f'<p class="jump">Ga naar: {jump}</p>' if len(keys) > 1 else ""}
  {blocks}
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
                    "x": re.sub(r"\s+", " ", " ".join(p["lines"]))[:15000]})
    for name, c in cats.items():
        if c["subs"] or c["loose"]:
            idx.append({"t": name, "h": cat_target(cats, name) + "/index.html", "c": "Kennisbank", "k": "categorie",
                        "x": " ".join(s_["name"] for s_ in c["subs"].values())})
        for sub in c["subs"].values():
            if sub["items"]:
                idx.append({"t": sub["name"], "h": sub_target(cats, name, sub) + "/index.html", "c": "Kennisbank › " + name,
                            "k": "categorie", "x": " ".join(x["t"] for x in sub["items"])})
    for g in json.load(open(os.path.join(TOOLS, "videos.json"), encoding="utf8")):
        for v in g["videos"]:
            idx.append({"t": v["t"], "h": "video/index.html#v-" + v["id"], "c": "Video's › " + g["group"], "k": "video",
                        "x": " ".join(x for x in (v.get("ch"), g["group"]) if x)})
    pvf = os.path.join(SRC, "procesversneller.html")
    if os.path.exists(pvf):
        pv = open(pvf, encoding="utf8").read()
        pv = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", pv, flags=re.S)
        idx.append({"t": "Proces-versneller: alles op een rij", "h": "procesversneller/index.html", "c": "Proces-versneller", "k": "kennisbank",
                    "x": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", pv)))[:15000] + " procesversneller ockto brondata"})
    wtf = os.path.join(SRC, "websitetools.json")
    if os.path.exists(wtf):
        wt = json.load(open(wtf, encoding="utf8"))
        idx.append({"t": "Websitetools: rekentools voor op je website", "h": "websitetools/index.html", "c": "Websitetools", "k": "kennisbank",
                    "x": " ".join(g["g"] + " " + " ".join(t["t"] for t in g["tools"]) for g in wt["groepen"]) + " rekentool rekentools website hypotheekbond leads"})
    tf = os.path.join(SRC, "academy", "trainingen.json")
    if os.path.exists(tf):
        for t in json.load(open(tf, encoding="utf8"))["trainingen"]:
            idx.append({"t": t["t"], "h": t["url"], "ext": 1, "c": "Trainingen › Blinqx Academy", "k": "video",
                        "x": " ".join(t["meta"] + t["labels"]) + " training cursus opleiding"})
    for m in fastlane_months()[0]:
        idx.append({"t": f'Releasenotes eBlinqx Hypotheekadvies – {m["label"]}', "h": f'releasenotes-hypotheekadvies/{m["slug"]}/index.html',
                    "c": "Releasenotes Hypotheekadvies (Fastlane)", "k": "release", "d": m["label"], "x": m["text"][:20000]})
    for it in elearning_items():
        idx.append({"t": it["t"], "h": "elearning/" + it["slug"] + "/index.html", "c": "E-learning › " + it["prod"], "k": "video",
                    "x": " ".join(st["h"] + " " + st["text"] for st in it["steps"])[:15000] or it["t"]})
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
  </div>
  <p id="scount" class="meta" aria-live="polite"></p>
  <div class="exlist" id="sres"></div>
  <p><button type="button" id="smore" class="smore" hidden>Toon meer resultaten</button></p>
</div></main>
<script src="zoekindex.js?v={idx_v}"></script>
<script src="zoeken.js?v={asset_versie('zoeken.js')}"></script>"""
    write("zoeken", layout(pg, "Zoeken", body))
    shutil.copy(os.path.join(TOOLS, "zoeken.js"), os.path.join(ROOT, "zoeken", "zoeken.js"))


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
              f'<a class="tile tile-wide" href="{pg.rel("procesversneller")}"><svg class="ic"><use href="#i-bolt"/></svg>'
              f'<span class="tw"><span>Proces-versneller</span><small>Brondata ophalen via Ockto: zo werkt het in eBlinqx</small></span></a>')

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


def render_video():
    pg = Page("video")
    groups = json.load(open(os.path.join(TOOLS, "videos.json"), encoding="utf8"))
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
    sections = [f'<p class="note">Op zoek naar de interactieve instructies? Die staan op de pagina <a href="{pg.rel("elearning")}">E-learning</a>.</p>']
    for g in groups:
        vs = []
        for v in g["videos"]:
            meta = " · ".join(x for x in (v.get("ch"), fmt_dur(v.get("d"))) if x)
            thumb = pg.rel(f'assets/video/{v["id"]}.jpg')
            if v.get("url"):
                vs.append(f'<div class="video" id="v-{esc(v["id"])}"><a class="frame" href="{esc(v["url"])}" target="_blank" rel="noopener"><img src="{thumb}" alt="" loading="lazy">'
                          f'<span class="play"><svg class="ic"><use href="#i-play"/></svg></span></a>'
                          f'<h3><a href="{esc(v["url"])}" target="_blank" rel="noopener">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
            else:
                vs.append(f'<div class="video" id="v-{esc(v["id"])}"><div class="frame" data-yt="{esc(v["id"])}"><img src="{thumb}" alt="" loading="lazy">'
                          f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>'
                          f'<h3><a href="https://www.youtube.com/watch?v={esc(v["id"])}" target="_blank" rel="noopener">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
        sections.append(f'<section class="vgroup"><h2>{esc(g["group"])}</h2><div class="vgrid">{"".join(vs)}</div></section>')
    body = f"""{crumbs(pg, [("Video's", None)])}
<main class="subpage"><div class="wrap">
  <h1>Video's</h1>
  <p class="lead">Instructievideo's, webinars en presentaties over Faster Forward Elements en eBlinqx. Video's worden pas van YouTube geladen als je op afspelen klikt.</p>
  {"".join(sections)}
</div></main>
<script>
document.addEventListener("click", e => {{
  const b = e.target.closest("[data-yt] .play");
  if (!b) return;
  const f = b.closest("[data-yt]");
  f.innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${{f.dataset.yt}}?autoplay=1&rel=0" title="Video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
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
  <h1>{esc(FL_TITLE)}</h1>
  <p class="lead">{esc(intro)}</p>
  <p class="jump">Ga naar: {jump}</p>
  {"".join(years)}
  <p class="src">Bron: <a href="{FL_BASE}/hoe-het-werkt/releasenotes/" target="_blank" rel="noopener">fastlane.hypotheekbond.nl</a></p>
</div></main>"""
    write("releasenotes-hypotheekadvies", layout(pg, FL_TITLE, body, "releasenotes-hypotheekadvies", intro))
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
    <p class="src">Bron: <a href="{esc(m["src"])}" target="_blank" rel="noopener">fastlane.hypotheekbond.nl</a></p>
  </article>
  <aside class="related"><h2>Andere maanden:</h2><ul>{others}</ul><p><a href="{pg.rel("releasenotes-hypotheekadvies")}">Alle releasenotes »</a></p></aside>
</div></main>"""
        write(path, layout(pg, f'Releasenotes {m["label"]} – eBlinqx Hypotheekadvies', body, "releasenotes-hypotheekadvies", fl_excerpt(m["text"])))


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
    body = f"""{crumbs(pg, [("Websitetools", None)])}
<main class="subpage"><div class="wrap">
  <h1>Websitetools</h1>
  <p class="lead">Rekentools voor op je eigen website: laat bezoekers zelf hun maximale hypotheek, maandlasten of de actuele rentes bekijken en zet ze zo om in leads. Er zijn {n} tools in {len(data["groepen"])} rubrieken. Klik op een tool om een voorbeeld te bekijken (opent in een nieuw tabblad).</p>
  {groups}
  <div class="oud wtnote" role="note">{esc(data["disclaimer"])}</div>
  <h2 class="wth">Websitetools op je eigen website?</h2>
  <p>De rekentools zijn in de huisstijl van je kantoor op je eigen website te plaatsen. Neem voor meer informatie contact op met {contact}.</p>
  <p class="src">Bron: <a href="{esc(data["bron"])}" target="_blank" rel="noopener">verzekeringhypotheek.blinqx.tech</a> (stand {fmt_date(date.fromisoformat(data["opgehaald"]))}).</p>
</div></main>"""
    write("websitetools", layout(pg, "Websitetools", body, None,
                                 "Rekentools voor op de website van je advieskantoor: hypotheek berekenen, rentes vergelijken, aflossen, verduurzamen en klantinzicht."))


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


def render_sitemap(pages):
    urls = set()
    for f in glob.glob(os.path.join(ROOT, "**", "index.html"), recursive=True):
        rel = os.path.relpath(os.path.dirname(f), ROOT).replace(os.sep, "/")
        if rel.split("/")[0] in ("bronnen", "tools", "zoeken", "assets", ".github"):
            continue
        urls.add("" if rel == "." else rel)
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"  <url><loc>{SITE_URL}{u + '/' if u else ''}</loc></url>" for u in sorted(urls)]
    xml.append("</urlset>")
    write("sitemap.xml", "\n".join(xml) + "\n")


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
    render_elearning()
    render_fastlane()
    render_trainingen()
    render_procesversneller()
    render_websitetools()
    render_search(pages, cats)
    render_home(cats, feeds, pages)
    render_404()
    render_sitemap(pages)

    # markeer root-mappen met gegenereerde inhoud zodat een volgende build ze kan opruimen
    for p in pages.values():
        if not p.get("skip") and p.get("role") and p["path"] and "/" not in p["path"]:
            open(os.path.join(ROOT, p["path"], ".generated"), "w").close()
    print(f"artikelen: {n['article']}, categorieën: {n['cat']}, subcategorieën: {n['sub']}, "
          f"nieuws: {len(feeds['Nieuws'])}, tips: {len(feeds['Tips'])}, releasenotes: {len(feeds['Release notes'])}")


if __name__ == "__main__":
    main()
