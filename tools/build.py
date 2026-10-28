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
OUTDIRS = ["video", "kennisbank", "categorien", "category", "nieuws", "tips", "releasenotes", "zoeken",
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
        if target.endswith((".html", ".css", ".js", ".png", ".jpg", ".xml")):
            return pre + target
        return pre + (target + "/" if target else "") + "index.html"


def page_url(p):
    return p["path"]


NAV = [("Home", ""), ("Nieuws", "nieuws"), ("Tips", "tips"), ("Release notes", "releasenotes"),
       ("Trainingen", "trainingen"), ("Contact support", "contact")]


def layout(pg, title, body, active=None, description=""):
    nav = "".join(
        f'<li><a href="{pg.rel(t)}"{" aria-current=\"page\"" if active == t else ""}>{esc(n)}</a></li>'
        for n, t in NAV)
    return f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}{" - " if title else ""}Blinqx Support</title>
{f'<meta name="description" content="{esc(description[:300])}">' if description else ""}
<link rel="stylesheet" href="{pg.rel('assets/site.css')}">
<link rel="icon" href="{pg.rel('assets/favicon.png')}">
</head>
<body>
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
      <div class="status">Mogelijke incidenten en de systeemstatus vind je op onze <a href="#" title="URL statuspagina nog invullen">statuspagina</a>.</div>
    </div>
  </div>
</header>
{body}
<footer>
  <div class="wrap">
    <span>Copyright © 2024 Blinqx powered by Faster Forward</span>
    <nav aria-label="Beleid">
      <a href="{pg.rel('supportbeleid')}">Supportbeleid</a>
      <a href="{pg.rel('opdrachtenbeleid')}">Opdrachtenbeleid</a>
      <a href="{pg.rel('klachtenbeleid')}">Klachtenbeleid</a>
      <a href="{pg.rel('wensenbeleid')}">Wensenbeleid</a>
      <a href="{pg.rel('video')}">Video's &amp; e-learning</a>
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


def write(path, content):
    full = os.path.join(ROOT, path) if path.endswith((".html", ".xml")) else os.path.join(ROOT, path, "index.html")
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
        items.append((cr[0], FEEDS[cr[0]]))
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


def render_article(cats, feeds, p):
    pg = Page(p["path"])
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
            '<p class="note">De volledige tekst van deze pagina is nog niet teruggevonden. ' + \
            (f'Bekijk de <a href="{esc(p["wayback"])}" target="_blank" rel="noopener">gearchiveerde versie in de Wayback Machine</a>.' if p["wayback"] else "") + "</p>"
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
    if p["wayback"]:
        src = f'<p class="src">Bron: <a href="{esc(p["wayback"])}" target="_blank" rel="noopener">Wayback Machine-archief</a></p>'
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


FEED_META = {
    "Nieuws": ("Laatste nieuws", "Hieronder vind je onze laatste nieuwsberichten.", "hero-nieuws.jpg"),
    "Tips": ("Laatste tips", "Hieronder vind je onze laatste tips.", "hero-tips.jpg"),
    "Release notes": ("Laatste releases", "Hieronder vind je de laatste updates.", "hero-releasenotes.jpg"),
}


def render_feed(name, items):
    path = FEEDS[name]
    pg = Page(path)
    h2, intro, img = FEED_META[name]
    cards = []
    for x in items:
        d = x["posted"] or x["updated"]
        cards.append(
            f'<article class="card"><h3><a href="{pg.rel(x["path"])}">{esc(x["t"])}</a></h3>'
            f'{f"<p class=\"date\">{fmt_date(d)}</p>" if d else ""}'
            f'{f"<p>{esc(x["excerpt"])}</p>" if x.get("excerpt") else ""}'
            f'<a class="readmore" href="{pg.rel(x["path"])}">Lees verder</a></article>')
    body = f"""{hero(pg, name, img)}
<main class="feed"><div class="wrap">
  <h2 class="feed-h">{esc(h2)}</h2>
  <p>{esc(intro)}</p>
  <div class="cards">{"".join(cards)}</div>
</div></main>"""
    write(path, layout(pg, name, body, path))


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


def render_search(pages):
    pg = Page("zoeken")
    idx = []
    for p in pages.values():
        if p.get("skip") or p.get("role") not in ("article",):
            continue
        txt = " ".join(p["lines"])
        idx.append({"t": p["t"], "p": p["path"], "c": " › ".join(p["crumb"] or []),
                    "e": p.get("excerpt", "")[:200], "x": txt[:6000]})
    data = json.dumps(idx, ensure_ascii=False).replace("</", "<\\/")
    body = f"""{crumbs(pg, [("Zoeken", None)])}
<main class="subpage"><div class="wrap">
  <h1 id="sh">Zoeken</h1>
  <p id="scount" class="meta"></p>
  <div class="exlist" id="sres"></div>
</div></main>
<script>
const IDX = {data};
const PRE = "../";
function esc(s){{return (s||"").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}})[c]);}}
for (const r of IDX){{ r._t = r.t.toLowerCase(); r._x = r.x.toLowerCase(); }}
function run(q){{
  const terms = q.toLowerCase().split(/\\s+/).filter(Boolean);
  document.querySelector('.search input').value = q;
  document.getElementById("sh").textContent = q ? `Zoekresultaten voor “${{q}}”` : "Zoeken";
  if (!terms.length){{ document.getElementById("scount").textContent = "Typ een zoekterm in het zoekveld hierboven."; document.getElementById("sres").innerHTML=""; return; }}
  const res = [];
  for (const r of IDX){{
    let score = 0, ok = true;
    for (const t of terms){{
      const inT = r._t.includes(t), inX = r._x.includes(t);
      if (!inT && !inX){{ ok = false; break; }}
      score += (inT ? 10 : 0) + (inX ? 1 : 0);
    }}
    if (ok) res.push([score, r]);
  }}
  res.sort((a,b)=>b[0]-a[0]);
  document.getElementById("scount").textContent = res.length + (res.length === 1 ? " resultaat" : " resultaten");
  document.getElementById("sres").innerHTML = res.slice(0,100).map(([,r]) =>
    `<article class="ex"><h2><a href="${{PRE + r.p}}/index.html">${{esc(r.t)}}</a></h2>` +
    (r.c ? `<p class="cpath">${{esc(r.c)}}</p>` : "") +
    (r.e ? `<p>${{esc(r.e)}}</p>` : "") + `</article>`).join("") || "<p>Geen resultaten gevonden.</p>";
}}
run(new URLSearchParams(location.search).get("q") || "");
</script>"""
    write("zoeken", layout(pg, "Zoeken", body))


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
      <a class="btn-out" href="{pg.rel('video')}">E-learning &amp; video's</a>
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
        <button role="tab" id="tab-release" aria-controls="p-release" aria-selected="false" tabindex="-1">Releasenotes</button>
        <button role="tab" id="tab-tips" aria-controls="p-tips" aria-selected="false" tabindex="-1">Tips</button>
      </div>
      <div>
        <section class="panel" id="p-nieuws" role="tabpanel" aria-labelledby="tab-nieuws">
          <h3>Laatste 5 nieuwsberichten</h3>
          <ul>{nieuws_li}<li class="all"><a href="{pg.rel('nieuws')}">Alle nieuwsberichten »</a></li></ul>
        </section>
        <section class="panel" id="p-release" role="tabpanel" aria-labelledby="tab-release" hidden>
          <h3>Laatste 5 releasenotes</h3>
          <ul>{latest("Release notes")}<li class="all"><a href="{pg.rel('releasenotes')}">Alle releasenotes »</a></li></ul>
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
    sections = [f'<section class="vgroup" id="elearning"><h2>E-learning</h2><p class="lead">Interactieve instructies per onderwerp. Elke e-learning opent in een nieuw tabblad.</p><div class="vgrid">{"".join(cards)}</div></section>']
    for g in groups:
        vs = []
        for v in g["videos"]:
            meta = " · ".join(x for x in (v.get("ch"), fmt_dur(v.get("d"))) if x)
            thumb = pg.rel(f'assets/video/{v["id"]}.jpg')
            if v.get("url"):
                vs.append(f'<div class="video"><a class="frame" href="{esc(v["url"])}" target="_blank" rel="noopener"><img src="{thumb}" alt="" loading="lazy">'
                          f'<span class="play"><svg class="ic"><use href="#i-play"/></svg></span></a>'
                          f'<h3><a href="{esc(v["url"])}" target="_blank" rel="noopener">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
            else:
                vs.append(f'<div class="video"><div class="frame" data-yt="{esc(v["id"])}"><img src="{thumb}" alt="" loading="lazy">'
                          f'<button class="play" type="button" aria-label="Speel {esc(v["t"])} af"><svg class="ic"><use href="#i-play"/></svg></button></div>'
                          f'<h3><a href="https://www.youtube.com/watch?v={esc(v["id"])}" target="_blank" rel="noopener">{esc(v["t"])}</a></h3><p>{esc(meta)}</p></div>')
        sections.append(f'<section class="vgroup"><h2>{esc(g["group"])}</h2><div class="vgrid">{"".join(vs)}</div></section>')
    body = f"""{crumbs(pg, [("Video's & e-learning", None)])}
<main class="subpage"><div class="wrap">
  <h1>Video's &amp; e-learning</h1>
  <p class="lead">Instructievideo's, e-learnings, webinars en presentaties over Faster Forward Elements en eBlinqx. Video's worden pas van YouTube geladen als je op afspelen klikt.</p>
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
    write("video", layout(pg, "Video's & e-learning", body))


def render_404():
    # GitHub Pages serveert 404.html vanaf de root; absolute paden zijn daar niet bekend, dus root-relatief.
    pg = Page("")
    body = """<main class="subpage"><div class="wrap">
  <h1>Pagina niet gevonden</h1>
  <p>Deze pagina bestaat (nog) niet in de herstelde supportsite. Gebruik de zoekfunctie hierboven of ga terug naar de <a href="/index.html">homepage</a>.</p>
</div></main>"""
    html_ = layout(pg, "Pagina niet gevonden", body)
    html_ = re.sub(r'(href|src|action)="(?!https?:|mailto:|tel:|#|/)([^"]*)"', lambda m: f'{m.group(1)}="{SITE_BASE}{m.group(2)}"', html_)
    html_ = html_.replace('href="/index.html"', f'href="{SITE_BASE}index.html"')
    write("404.html", html_)


def render_sitemap(pages):
    urls = [""] + sorted({p["path"] for p in pages.values() if not p.get("skip") and p.get("role")})
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"  <url><loc>{BASE}/{u + '/' if u else ''}</loc></url>" for u in urls]
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
    render_search(pages)
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
