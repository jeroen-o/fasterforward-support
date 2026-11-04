#!/usr/bin/env python3
"""Haalt de openbare inhoud uit de WordPress-databaseback-up van support.fasterforward.nl (UpdraftPlus, 21 okt 2026).

Gebruik: python3 tools/wpdb_export.py <content.json> [uitmap]
<content.json> is de uitvoer van de SQL-parser (alleen de tabellen sup_posts, sup_postmeta, sup_terms,
sup_term_taxonomy, sup_term_relationships en sup_redirects). De back-up zelf bevat ook gebruikers,
wachtwoordhashes, formulierinzendingen en chatlogs: die komen NOOIT in deze repository.

Uitvoer: bronnen/wpdb-2026-10-21/paginas.json met alleen gepubliceerde kennisbankartikelen, berichten en pagina's
(zonder wachtwoord), plus de doorverwijzingen van de oude site. build.py gebruikt dit als nieuwste bron.
"""
import json, os, re, sys

MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober",
           "november", "december"]
OVERSLAAN = {"home", "test-pagina", "trainingen-oud"}
TABLEPRESS = {"1": "3024", "2": "3060", "3": "5007"}  # uit sup_options 'tablepress_tables' (back-up 21-10-2026)
HOOFD = {"eBlinqx": "Basis", "Apps": "Basis"}  # oude hoofdcategorieën -> indeling van de nieuwe site


def nl_datum(s):
    j, m, d = s[:10].split("-")
    return f"{int(d)} {MAANDEN[int(m) - 1]} {j}"


def autop(t):
    """Vereenvoudigde wpautop voor klassieke (niet-blok) inhoud."""
    t = t.replace("\r\n", "\n")
    blok = r"(?:table|thead|tbody|tr|td|th|ul|ol|li|h[1-6]|p|div|blockquote|pre|figure|figcaption|hr|iframe)"
    delen = re.split(r"\n\s*\n", t)
    uit = []
    for d in delen:
        d = d.strip()
        if not d:
            continue
        if re.match(rf"<{blok}[\s>/]", d, re.I):
            uit.append(d)
        else:
            uit.append("<p>" + d.replace("\n", "<br>") + "</p>")
    return "\n".join(uit)


TABELLEN = {}  # TablePress: tabel-id -> HTML


def tabel_html(rijen):
    kop, *rest = rijen
    th = "".join(f"<th>{c}</th>" for c in kop)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rest)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def inhoud(t):
    blokken = "<!-- wp:" in t
    t = re.sub(r"\[table id=(\d+)\s*/?\]", lambda m: "\n\n" + TABELLEN.get(m.group(1), "") + "\n\n", t)
    t = re.sub(r"<!--\s*/?wp:.*?-->", "", t, flags=re.S)
    t = re.sub(r"\[caption[^\]]*\](.*?)\[/caption\]", r"<figure>\1</figure>", t, flags=re.S)
    t = re.sub(r"\[embed\](.*?)\[/embed\]", r'<p><a href="\1">\1</a></p>', t, flags=re.S)
    t = re.sub(r"\[/?[a-z_][\w-]*(?:\s[^\]]*)?\]", "", t)  # overige shortcodes
    return t if blokken else autop(t)


def main():
    src = json.load(open(sys.argv[1], encoding="utf8"))
    uit = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bronnen", "wpdb-2026-10-21")
    os.makedirs(uit, exist_ok=True)
    naam = {t["term_id"]: t["name"] for t in src["sup_terms"]}
    tt = {t["term_taxonomy_id"]: t for t in src["sup_term_taxonomy"]}
    per_post = {}
    for r in src["sup_term_relationships"]:
        t = tt.get(r["term_taxonomy_id"])
        if t:
            per_post.setdefault(r["object_id"], []).append(t)
    posts = {p["ID"]: p for p in src["sup_posts"]}
    thumb = {m["post_id"]: m["meta_value"] for m in src["sup_postmeta"] if m["meta_key"] == "_thumbnail_id"}

    # TablePress-tabellen ([table id=N /]); de koppeling id -> bericht staat in de optie tablepress_tables
    for tid, pid in TABLEPRESS.items():
        if pid in posts:
            TABELLEN[tid] = tabel_html(json.loads(posts[pid]["post_content"]))
    paginas = []
    for p in src["sup_posts"]:
        if p["post_status"] != "publish" or p["post_type"] not in ("ht_kb", "post", "page") or p["post_password"]:
            continue
        if p["post_name"] in OVERSLAAN or not p["post_name"]:
            continue
        pad = ("kennisbank/" if p["post_type"] == "ht_kb" else "") + p["post_name"]
        termen = per_post.get(p["ID"], [])
        crumbs, cat = [], None
        kbcat = [t for t in termen if t["taxonomy"] == "ht_kb_category"]
        if kbcat:
            t = sorted(kbcat, key=lambda t: t["parent"] == "0")[0]  # liefst een subcategorie
            if t["parent"] != "0":
                hoofd = naam.get(t["parent"], "")
                crumbs = [HOOFD.get(hoofd, hoofd), naam[t["term_id"]]]
            else:
                crumbs = [HOOFD.get(naam[t["term_id"]], naam[t["term_id"]])]
        cats = [naam[t["term_id"]] for t in termen if t["taxonomy"] == "category"]
        if p["post_type"] == "post":
            cat = "release" if "Release" in cats else ("tips" if "Tips" in cats else "nieuws")
        img = None
        if thumb.get(p["ID"]) in posts:
            img = posts[thumb[p["ID"]]]["guid"].replace("http://", "https://")
        paginas.append({
            "pad": pad, "type": p["post_type"], "titel": p["post_title"], "html": inhoud(p["post_content"]),
            "geplaatst": nl_datum(p["post_date"]), "gewijzigd": nl_datum(p["post_modified"]),
            "crumbs": crumbs, "categorie": cat, "uittreksel": p["post_excerpt"], "afbeelding": img,
        })
    def doel(n):
        if n.isdigit() and n in posts:  # verwijzing naar een bericht-ID
            q = posts[n]
            return ("kennisbank/" if q["post_type"] == "ht_kb" else "") + q["post_name"]
        return re.sub(r"^https?://(www\.)?support\.fasterforward\.nl", "", n).strip("/") if "support.fasterforward.nl" in n or n.startswith("/") else n
    redirects = [{"van": r["url_from"].strip("/"), "naar": doel(r["url_to"]), "status": r["status"]} for r in src["sup_redirects"]]
    json.dump(paginas, open(os.path.join(uit, "paginas.json"), "w", encoding="utf8"), ensure_ascii=False, indent=0)
    json.dump(redirects, open(os.path.join(uit, "doorverwijzingen.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(len(paginas), "pagina's,", len(redirects), "doorverwijzingen ->", uit)


if __name__ == "__main__":
    main()
