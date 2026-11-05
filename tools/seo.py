#!/usr/bin/env python3
"""SEO/GEO-nabewerking van alle gegenereerde pagina's (aangeroepen door build.py, vóór de sitemap).

Per pagina:
- meta description en og:description: 70–160 tekens, eindigend op een hele zin of woord; te kort wordt aangevuld met
  de eerste alinea; dubbele beschrijvingen krijgen de paginatitel ervoor;
- <title>: zonder ' - Blinqx Support' als de titel anders langer dan 65 tekens is; dubbele titels krijgen de
  bovenliggende kruimel (of het onderdeel) erbij;
- JSON-LD: BreadcrumbList (alle pagina's met kruimelpad), Article (pagina's met een datum), WebPage (overige),
  Organization + WebSite met zoekfunctie (homepage);
- precies één <h1> (homepage krijgt een verborgen h1, extra h1's worden h2);
- llms.txt in de root met de belangrijkste pagina's per onderdeel.
"""
import collections, html, json, os, re

MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"]
SUFFIX = " - Blinqx Support"
ORG = {"@type": "Organization", "name": "Blinqx", "url": "https://www.blinqx.tech/",
       "logo": None}  # logo wordt in uitvoeren() ingevuld


def tekst(h):
    h = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def kort(d, maxl=160):
    d = re.sub(r"\s+", " ", d).strip()
    if len(d) <= maxl:
        return d
    deel = d[:maxl]
    zin = max(deel.rfind(". "), deel.rfind("! "), deel.rfind("? "))
    if zin >= 80:
        return deel[:zin + 1]
    return deel[:maxl - 1].rsplit(" ", 1)[0].rstrip(",;:–-") + "…"


def iso(datum):
    m = re.search(r"(\d{1,2}) (" + "|".join(MAANDEN) + r") (\d{4})", datum or "")
    return f"{m.group(3)}-{MAANDEN.index(m.group(2)) + 1:02d}-{int(m.group(1)):02d}" if m else None


def esc(s):
    return html.escape(s, quote=True)


def lees(root, overslaan):
    paginas = {}
    for dirpath, dirs, files in os.walk(root):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel != "." and rel.split("/")[0] in overslaan:
            dirs[:] = []
            continue
        if "index.html" in files:
            f = os.path.join(dirpath, "index.html")
            s = open(f, encoding="utf8").read()
            if 'http-equiv="refresh"' in s[:600]:
                continue
            paginas["" if rel == "." else rel] = [f, s]
    return paginas


def uitvoeren(root, site_url, overslaan=("bronnen", "tools", "assets", ".github")):
    ORG["logo"] = site_url + "assets/logo-mark.png"
    paginas = lees(root, overslaan)
    info = {}
    for u, (f, s) in paginas.items():
        head, rest = s.split("</head>", 1)
        main = re.search(r"<main\b.*?</main>", rest, re.S)
        main = main.group(0) if main else rest
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", re.sub(r"<script\b.*?</script>", "", rest, flags=re.S), re.S)
        cr = re.search(r'<nav aria-label="Kruimelpad">(.*?)</nav>', rest, re.S)
        kruimels = []
        if cr:
            for a in re.finditer(r'<a href="([^"]+)">(.*?)</a>|<span aria-current="page">(.*?)</span>', cr.group(1)):
                if a.group(1):
                    doel = os.path.normpath(os.path.join(os.path.dirname(f), a.group(1)))
                    doel = os.path.relpath(os.path.dirname(doel) if doel.endswith("index.html") else doel, root)
                    doel = "" if doel == "." else doel.replace(os.sep, "/") + "/"
                    kruimels.append((tekst(a.group(2)), site_url + doel))
                else:
                    kruimels.append((tekst(a.group(3)), site_url + (u + "/" if u else "")))
        meta = re.search(r'<p class="meta">(.*?)</p>', rest, re.S)
        mt = tekst(meta.group(1)) if meta else ""
        gepl = iso(re.search(r"Geplaatst op ([^·]+)", mt).group(1)) if "Geplaatst op" in mt else None
        upd = iso(re.search(r"(?:Laatste update|Bijgewerkt)[: ]+(.+)", mt).group(1)) if re.search(r"Laatste update|Bijgewerkt", mt) else None
        if not gepl and not upd and mt:
            gepl = iso(mt)
        alineas = [tekst(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", main, re.S)]
        alineas = [a for a in alineas if len(a) > 40 and not a.startswith(("Geplaatst op", "Laatste update", "Bron:"))]
        titel = re.search(r"<title>(.*?)</title>", head, re.S).group(1)
        desc = re.search(r'<meta name="description" content="([^"]*)"', head)
        info[u] = {"titel": html.unescape(titel), "desc": html.unescape(desc.group(1)) if desc else "",
                   "h1": tekst(h1.group(1)) if h1 else "", "kruimels": kruimels, "gepl": gepl, "upd": upd,
                   "alineas": alineas, "img": (re.search(r'<meta property="og:image" content="([^"]+)"', head) or [None, None])[1],
                   "links": [tekst(x) for x in re.findall(r'<a [^>]*href="[^"#]*"[^>]*>(.*?)</a>', main, re.S)][:40]}

    # beschrijvingen
    standaard = collections.Counter(i["desc"] for i in info.values())
    for u, i in info.items():
        d = i["desc"]
        naam = i["h1"] or i["titel"].replace(SUFFIX, "")
        if u and standaard[d] > 1 and (u.startswith("categorien/") or u.startswith("kennisbank") and len(i["alineas"]) == 0
                                       or d.startswith("Support voor eBlinqx")):
            items = [x for x in i["links"] if 8 < len(x) < 80 and x not in (naam, "Lees meer")][:4]
            d = f"{naam} in eBlinqx Connect: handleidingen en uitleg" + (", waaronder " + ", ".join(items) if items else "") + "."
        elif standaard[d] > 1 and u:
            d = f"{naam}: {d}"
        if len(d) < 70:
            for a in i["alineas"]:
                if a[:40].rstrip(". ") not in d:
                    d = (d.rstrip(". ") + ". " if d else "") + a
                if len(d) >= 110:
                    break
        i["desc_nieuw"] = kort(d)

    # titels
    def basis(i):
        t = i["titel"]
        return t[:-len(SUFFIX)] if t.endswith(SUFFIX) else t
    groepen = collections.defaultdict(list)
    for u, i in info.items():
        groepen[basis(i)].append(u)
    for t, us in groepen.items():
        for u in us:
            i = info[u]
            nt = t
            if len(us) > 1:
                ouder = i["kruimels"][-2][0] if len(i["kruimels"]) >= 2 else ""
                if not ouder or ouder == t:
                    ouder = {"kennisbank": "Kennisbank", "categorien": "Categorie", "elearning": "E-learning",
                             "releasenotes": "Releasenotes"}.get(u.split("/")[0], "Nieuws")
                nt = f"{t} ({ouder})"
            i["titel_nieuw"] = nt + SUFFIX if len(nt + SUFFIX) <= 65 or not u else nt
            if not u:
                i["titel_nieuw"] = "Blinqx Support: kennisbank en handleidingen voor eBlinqx Connect"
    # nog steeds dubbel (zelfde ouder): pad als laatste redmiddel
    tel = collections.Counter(i["titel_nieuw"] for i in info.values())
    for u, i in info.items():
        if tel[i["titel_nieuw"]] > 1:
            i["titel_nieuw"] = i["titel_nieuw"].replace(SUFFIX, "") + f" ({u.rstrip('/').split('/')[-1]})"

    # schrijven
    for u, (f, s) in paginas.items():
        i = info[u]
        head, rest = s.split("</head>", 1)
        head = re.sub(r'\s*<script type="application/ld\+json" id="seo-ld">.*?</script>', "", head, flags=re.S)
        head = re.sub(r"<title>.*?</title>", lambda m: f"<title>{esc(i['titel_nieuw'])}</title>", head, count=1, flags=re.S)
        head = re.sub(r'(<meta (?:name="description"|property="og:description") content=")[^"]*(")',
                      lambda m: m.group(1) + esc(i["desc_nieuw"]) + m.group(2), head)
        url = site_url + (u + "/" if u else "")
        graaf = []
        if not u:
            graaf += [dict(ORG, **{"@id": site_url + "#org", "sameAs": ["https://www.linkedin.com/company/blinqx/"],
                                   "contactPoint": {"@type": "ContactPoint", "telephone": "+31-85-018-00-69",
                                                    "email": "support-eblinqx@blinqx.tech", "contactType": "customer support",
                                                    "availableLanguage": "nl"}}),
                      {"@type": "WebSite", "@id": site_url + "#site", "url": site_url, "name": "Blinqx Support",
                       "inLanguage": "nl-NL", "publisher": {"@id": site_url + "#org"},
                       "potentialAction": {"@type": "SearchAction", "target": site_url + "zoeken/?q={search_term_string}",
                                           "query-input": "required name=search_term_string"}}]
        else:
            naam = i["h1"] or i["titel_nieuw"].replace(SUFFIX, "")
            basis_obj = {"@id": url + "#pagina", "url": url, "name": naam, "headline": naam[:110],
                         "description": i["desc_nieuw"], "inLanguage": "nl-NL", "isPartOf": {"@type": "WebSite", "url": site_url, "name": "Blinqx Support"}}
            if i["img"]:
                basis_obj["image"] = i["img"]
            if i["gepl"] or i["upd"]:
                art = dict(basis_obj, **{"@type": "TechArticle" if u.startswith(("kennisbank/", "elearning/", "finrust/", "adviesbox-classic/", "adviesbox-online/", "hypotheekadvies-helpcenter/", "finconnect/", "finly/")) else "Article",
                                         "author": {"@type": "Organization", "name": "Blinqx"},
                                         "publisher": {"@type": "Organization", "name": "Blinqx", "logo": {"@type": "ImageObject", "url": ORG["logo"]}},
                                         "mainEntityOfPage": url})
                if i["gepl"]:
                    art["datePublished"] = i["gepl"]
                art["dateModified"] = i["upd"] or i["gepl"]
                art.pop("name")
                graaf.append(art)
            else:
                basis_obj.pop("headline")
                graaf.append(dict(basis_obj, **{"@type": "CollectionPage" if u.startswith("categorien/") else "WebPage"}))
            if i["kruimels"]:
                lijst = [("Home", site_url)] + [k for k in i["kruimels"] if k[1] != site_url]
                graaf.append({"@type": "BreadcrumbList", "itemListElement": [
                    {"@type": "ListItem", "position": n + 1, "name": k[0], "item": k[1]} for n, k in enumerate(lijst)]})
        ld = json.dumps({"@context": "https://schema.org", "@graph": graaf}, ensure_ascii=False).replace("</", "<\\/")
        head += f'\n<script type="application/ld+json" id="seo-ld">{ld}</script>\n'
        # alt-teksten: lege of ontbrekende alt aanvullen vanuit de context (kaarttitel, bijschrift, kop of paginatitel)
        naam_pg = i["h1"] or i["titel_nieuw"].replace(SUFFIX, "")
        mm = re.search(r"<main\b.*?</main>", rest, re.S)
        if mm:
            main = mm.group(0)
            artikel = 'class="article"' in main[:200]

            def alt(m):
                tag = m.group(0)
                a = re.search(r'\salt="([^"]*)"', tag)
                if a and a.group(1).strip():
                    return tag
                na = main[m.end():m.end() + 900]
                voor = main[max(0, m.start() - 2500):m.start()]
                ctx = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", na, re.S) or re.search(r"<h[2-4][^>]*>(.*?)</h[2-4]>", na[:500], re.S)
                kop = re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", voor, re.S)
                if artikel:
                    k = tekst(kop[-1]) if kop else ""
                    txt = f"Schermafbeelding: {k} ({naam_pg})" if k and k != naam_pg else f"Schermafbeelding bij {naam_pg}"
                else:
                    txt = tekst(ctx.group(1)) if ctx else (tekst(kop[-1]) if kop else naam_pg)
                txt = esc(txt[:140])
                if a:
                    return tag[:a.start()] + f' alt="{txt}"' + tag[a.end():]
                return tag.replace("<img", f'<img alt="{txt}"', 1)
            nieuw_main = re.sub(r"<img\b[^>]*>", alt, main)
            rest = rest.replace(main, nieuw_main, 1)
            # eigen deelafbeelding voor video-, websites-, partner- en productpagina's
            if u in ("sites", "partners", "adviescoach") or u.startswith(("video/", "sites/", "partners/", "finrust/", "adviesbox-classic/", "adviesbox-online/", "hypotheekadvies-helpcenter/", "finconnect/", "finly/", "banking-insurance", "adviescoach", "mijnhuiszaken", "yes-co", "tools-voor-vastgoed",
                             "woningwaarderapport", "actiefbeheerscan", "hypotheekrente-app", "finly-crm", "demo-kantoor", "websitetools")):
                eerste = re.search(r'<(?:img[^>]*\ssrc|video[^>]*\sposter)="([^"]+\.(?:webp|jpe?g|png))"', nieuw_main)
                if eerste:
                    absu = site_url + os.path.normpath(os.path.join(os.path.dirname(os.path.relpath(f, root)), eerste.group(1))).replace(os.sep, "/")
                    head = re.sub(r'<meta property="og:image" content="[^"]*">', f'<meta property="og:image" content="{absu}">', head)
                    head = re.sub(r'<meta name="twitter:image" content="[^"]*">', f'<meta name="twitter:image" content="{absu}">', head)
                    head = re.sub(r'<meta property="og:image:width" content="\d+"><meta property="og:image:height" content="\d+">\n?', "", head)
                    head = re.sub(r'<meta property="og:image:type" content="[^"]*">\n?', "", head)
                    head = re.sub(r'<meta property="og:image:alt" content="[^"]*">', f'<meta property="og:image:alt" content="{esc(naam_pg)}">', head)
        # h1
        zonder_script = re.sub(r"<script\b.*?</script>", "", rest, flags=re.S)
        n_h1 = len(re.findall(r"<h1[\s>]", zonder_script))
        if n_h1 == 0 and '<main class="home">' in rest:
            rest = rest.replace('<main class="home">', '<main class="home"><h1 class="sr-only">Blinqx Support: kennisbank, '
                                'handleidingen en releasenotes voor eBlinqx Connect</h1>', 1)
        elif n_h1 > 1:
            teller = [0]

            def h(m):
                teller[0] += 1
                return m.group(0) if teller[0] == 1 else "<h2" + m.group(1) + "</h2>"
            delen = re.split(r"(<script\b.*?</script>)", rest, flags=re.S)
            for k in range(0, len(delen), 2):
                delen[k] = re.sub(r"<h1([\s>].*?)</h1>", h, delen[k], flags=re.S)
            rest = "".join(delen)
        open(f, "w", encoding="utf8").write(head + "</head>" + rest)
    return info


def llms_txt(root, site_url, info, secties):
    """secties: lijst (kop, [paden]) in volgorde van belang."""
    regels = ["# Blinqx Support (eBlinqx Connect)", "",
              "> Officiële supportsite van Blinqx voor eBlinqx Connect (voorheen Faster Forward Elements): kennisbank, "
              "handleidingen, releasenotes, e-learning en productinformatie voor hypotheekadviseurs, verzekeringsadviseurs "
              "en financieel dienstverleners. Contact: support-eblinqx@blinqx.tech, 085 018 00 69.", ""]
    for kop, paden in secties:
        items = [(p, info[p]) for p in paden if p in info]
        if not items:
            continue
        regels += [f"## {kop}", ""]
        for p, i in items:
            naam = i["h1"] or i["titel_nieuw"].replace(SUFFIX, "")
            regels.append(f"- [{naam}]({site_url}{p + '/' if p else ''}): {i['desc_nieuw']}")
        regels.append("")
    regels += ["## Overig", "", f"- [Sitemap]({site_url}sitemap.xml): alle pagina's", ""]
    open(os.path.join(root, "llms.txt"), "w", encoding="utf8").write("\n".join(regels))
