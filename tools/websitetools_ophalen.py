#!/usr/bin/env python3
"""Haalt de rekentools voor op de website op van verzekeringhypotheek.blinqx.tech (partners/rekentools-voor-op-de-website).

Schrijft bronnen/websitetools.json: intro, rubrieken met tools (naam + demo-URL op tools.hypotheekbond.nl) en de disclaimer.

Gebruik:  python3 tools/websitetools_ophalen.py
"""
import html
import json
import os
import re
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://verzekeringhypotheek.blinqx.tech/partners/rekentools-voor-op-de-website"


def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (herstel supportsite)"})
    s = urllib.request.urlopen(req, timeout=60).read().decode("utf8", "replace")
    body = s[s.find("et_pb_section_0_tb_body"):s.find("Contact en samenwerking")]
    body = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<noscript\b.*?</noscript>", "", body, flags=re.S)
    tools_part = body[body.find('id="section-1"'):]
    groups = []
    for h, blk in re.findall(r"<h3[^>]*>(.*?)</h3>\s*<div[^>]*>(.*?)</div>", tools_part, re.S):
        items = [{"t": txt(a).replace("↗", "").strip(), "url": html.unescape(u)}
                 for u, a in re.findall(r'<a href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)]
        if items:
            groups.append({"g": txt(h), "tools": items})
    rest = re.sub(r"<h3[^>]*>.*?</h3>\s*<div[^>]*>.*?</div>", "", tools_part, flags=re.S)
    disclaimer = next((txt(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", rest, re.S) if "indicatief" in txt(p)), "")
    contact = [m.groups() for m in (re.match(r"(.+?)\s*[–-]\s*([\w.+-]+@blinqx\.tech)$", txt(li))
                                    for li in re.findall(r"<li[^>]*>(.*?)</li>", s, re.S)) if m]
    data = {"opgehaald": date.today().isoformat(), "bron": URL, "groepen": groups, "disclaimer": disclaimer,
            "contact": [{"naam": n.strip(), "mail": m} for n, m in contact]}
    json.dump(data, open(os.path.join(ROOT, "bronnen", "websitetools.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(sum(len(g["tools"]) for g in groups), "tools in", len(groups), "rubrieken;", len(data["contact"]), "contactpersonen")


if __name__ == "__main__":
    main()
