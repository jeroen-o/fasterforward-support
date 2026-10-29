#!/usr/bin/env python3
"""Haalt de e-learnings (Storylane-demo's) uit tools/elearning.txt op naar bronnen/elearning/<id>/.

Per demo: stappen.json (volgorde, titel, tekst, pagina) en de schermafbeeldingen per pagina (WebP, max 1200 px).
De demo-data staat in de HTML van https://blinqx.storylane.io/demo/<id> (__NEXT_DATA__); er hoeft niet
geklikt te worden. Al aanwezige afbeeldingen worden overgeslagen.

Gebruik:  python3 tools/storylane_ophalen.py
"""
import ast
import html
import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import htmlclean  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "bronnen", "elearning")
UA = {"User-Agent": "Mozilla/5.0 (herstel supportsite)"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()


def as_obj(v):
    """Storylane geeft sommige velden als Python-achtige string terug."""
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)
        except ValueError:
            try:
                return ast.literal_eval(v)
            except (ValueError, SyntaxError):
                return v
    return v


def clean(fragment):
    c = htmlclean.Cleaner()
    c.feed(fragment or "")
    c.close()
    out = "".join(c.out)
    out = re.sub(r'(href|src)="(IMG|SITE):', r'\1="', out)
    out = re.sub(r"<p>\s*(<br>)?\s*</p>", "", out)
    return out.strip()


def demo(sid):
    doc = get(f"https://blinqx.storylane.io/demo/{sid}").decode("utf8", "replace")
    nd = json.loads(re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', doc, re.S).group(1))
    pp = nd["props"]["pageProps"]
    if not pp.get("ssResponseDataStr"):
        return None
    data = json.loads(pp["ssResponseDataStr"])["data"]
    ent = data["entities"]
    project = next(iter(ent["projects"].values()))
    pages = {p["id"]: p for p in project.get("pages", [])}
    flows = list(ent["flows"].values())
    order = as_obj(project.get("flows")) or [f["id"] for f in flows]
    order = [f if isinstance(f, str) else f.get("id") for f in order]
    flows.sort(key=lambda f: order.index(f["id"]) if f["id"] in order else 99)
    steps = []
    for fl in flows:
        for wid in as_obj(fl["widgets"]) or []:
            w = ent["widgets"].get(wid)
            if not w:
                continue
            loc = w.get("widget_locale") or {}
            desc = loc.get("description") or w.get("description") or ""
            body = clean(desc)
            title = html.unescape((loc.get("title") or w.get("title") or "").strip())
            if not body and not title:
                # stap zonder eigen tekst: automatische aanwijzing van Storylane ('Click "Opslaan"')
                auto = as_obj((as_obj(w.get("options")) or {}).get("description")) if isinstance(as_obj(w.get("options")), dict) else None
                auto = auto.get("value") if isinstance(auto, dict) else ""
                auto = re.sub(r"^(<p>)?\s*Click\s+", r"\1Klik op ", auto or "")
                body = clean(auto)
                if not body:
                    continue
            steps.append({"flow": fl.get("name", ""), "kind": w.get("kind"), "title": title, "html": body,
                          "page": w.get("page_id")})
    os.makedirs(os.path.join(OUT, sid), exist_ok=True)
    used = []
    for st in steps:
        pg = pages.get(st["page"])
        if not pg or not pg.get("file_url"):
            st["page"] = None
            continue
        f = os.path.join(OUT, sid, st["page"] + ".webp")
        if not os.path.exists(f):
            try:
                im = Image.open(io.BytesIO(get(pg["file_url"]))).convert("RGB")
                if im.width > 1200:
                    im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
                im.save(f, "WEBP", quality=78, method=5)
            except Exception as e:  # pagina zonder bruikbare afbeelding
                print("  afbeelding mislukt:", e)
                st["page"] = None
                continue
        used.append(st["page"])
    info = {"id": sid, "name": project.get("name"), "steps": steps}
    json.dump(info, open(os.path.join(OUT, sid, "stappen.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    return info


def main():
    for line in open(os.path.join(ROOT, "tools", "elearning.txt"), encoding="utf8"):
        if line.startswith("#") or "storylane" not in line:
            continue
        sid = line.split("|")[1].rstrip("/").split("/")[-1]
        try:
            info = demo(sid)
        except Exception as e:
            print(sid, "MISLUKT", e)
            continue
        print(sid, "geen openbare data (wachtwoord?)" if info is None else f'{len(info["steps"])} stappen  {info["name"]}')


if __name__ == "__main__":
    main()
