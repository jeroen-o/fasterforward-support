"""Haalt de inhoud uit een originele WordPress-pagina van support.fasterforward.nl en maakt die veilig.

Alleen inhoudelijke opmaak blijft over (koppen, alinea's, lijsten, tabellen, afbeeldingen, links,
YouTube/Vimeo-embeds). Scripts, formulieren, stijlen en sitechrome verdwijnen.
Links naar support.fasterforward.nl en afbeeldingen worden als placeholder teruggegeven
(SITE:/pad en IMG:url), zodat build.py ze per pagina relatief kan maken.
"""
import html
import re
from html.parser import HTMLParser

ALLOWED = {
    "p": (), "br": (), "hr": (), "h2": ("id",), "h3": ("id",), "h4": ("id",), "h5": ("id",),
    "ul": (), "ol": ("start",), "li": (), "strong": (), "b": (), "em": (), "i": (), "u": (),
    "a": ("href",), "img": ("src", "alt", "width", "height"), "figure": (), "figcaption": (),
    "table": (), "thead": (), "tbody": (), "tr": (), "td": ("colspan", "rowspan"), "th": ("colspan", "rowspan"),
    "blockquote": (), "code": (), "pre": (), "sup": (), "sub": (), "iframe": ("src",),
}
VOID = {"br", "hr", "img"}
DROP = {"script", "style", "form", "noscript", "button", "select", "textarea", "svg", "head", "nav", "h1"}
HOST_RE = re.compile(r"^https?://(?:www\.)?support\.fasterforward\.nl", re.I)
EMBED_RE = re.compile(r"^(https?:)?//(www\.)?(youtube(-nocookie)?\.com/embed/|player\.vimeo\.com/video/)", re.I)
# Blokken die we niet willen meenemen (eigen inhoudsopgave, 'laatste releases', feedback, deelknoppen).
SKIP_CLASS = re.compile(r"ub_table-of-contents|rnld-berichten|ht-voting|sharedaddy|jp-relatedposts|"
                        r"related|pagesidebar|sidebar|widget|breadcrumb|comments|nav-links|meta_tags|"
                        r"hkb-article__lastupdated|hkb-article-tags|hkb-feedback|hkb-article__title|ht-voting", re.I)


class Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0
        self.anchor_img = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.skip:
            if tag not in VOID:
                self.skip += 1
            return
        if tag in DROP or SKIP_CLASS.search(a.get("class", "") + " " + a.get("id", "")):
            if tag not in VOID:
                self.skip = 1
            return
        if tag == "table" and "rnld" in a.get("class", ""):
            self.skip = 1
            return
        if tag not in ALLOWED:
            if tag not in VOID:
                self.stack.append(None)
            return
        keep = []
        for k in ALLOWED[tag]:
            v = a.get(k)
            if v is None:
                continue
            if k == "href":
                v = fix_href(v)
                if v is None:
                    continue
            if k == "src" and tag == "img":
                v = "IMG:" + best_src(a)
            if k == "src" and tag == "iframe":
                if not EMBED_RE.match(v):
                    break
                v = v.replace("youtube.com/embed", "youtube-nocookie.com/embed")
            keep.append(f'{k}="{html.escape(v, quote=True)}"')
        else:
            if tag == "iframe" and not a.get("src"):
                self.skip = 1
                return
            extra = ""
            if tag == "img":
                extra = ' loading="lazy"'
            if tag == "iframe":
                extra = ' loading="lazy" allowfullscreen'
            if tag == "a" and a.get("href", "").startswith("http") and not HOST_RE.match(a.get("href", "")):
                extra = ' target="_blank" rel="noopener"'
            self.out.append(f"<{tag}{(' ' + ' '.join(keep)) if keep else ''}{extra}>")
            if tag not in VOID:
                self.stack.append(tag)
            return
        # iframe met een niet-toegestane bron
        self.skip = 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and not self.skip and self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.skip:
            self.skip -= 1
            return
        if self.stack:
            t = self.stack.pop()
            if t:
                self.out.append(f"</{t}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def best_src(a):
    """Grootste variant uit srcset, anders src; WordPress-maataanduiding (-300x200) weghalen kan niet altijd."""
    src = a.get("src", "")
    ss = a.get("srcset", "")
    best, bw = src, 0
    for part in ss.split(","):
        bits = part.strip().split()
        if len(bits) == 2 and bits[1].endswith("w"):
            try:
                w = int(bits[1][:-1])
            except ValueError:
                continue
            if w > bw and w <= 1600:
                best, bw = bits[0], w
    if a.get("data-src"):
        best = a["data-src"]
    return unwrap_wayback(best)


def unwrap_wayback(u):
    m = re.match(r"^(?:https?://web\.archive\.org)?/web/\d+(?:[a-z]{2}_)?/(.+)$", u)
    return m.group(1) if m else u


def fix_href(h):
    h = unwrap_wayback(h.strip())
    if h.startswith(("javascript:", "#respond")):
        return None
    if h.startswith("/") and not h.startswith("//"):
        h = "https://support.fasterforward.nl" + h
    if HOST_RE.match(h):
        path = HOST_RE.sub("", h)
        if path.startswith("/wp-content/"):
            return "IMG:https://support.fasterforward.nl" + path
        return "SITE:" + (path or "/")
    return h


def find_content(doc):
    """Stuk HTML met de eigenlijke inhoud van de pagina."""
    m = re.search(r'<div id="content"[^>]*>(.*)', doc, re.S)
    body = m.group(1) if m else doc
    for pat in (r'<article[^>]*class="[^"]*singlepost[^"]*"[^>]*>', r'<div class="hkb-article__content"[^>]*>',
                r'<div class="contact_form"[^>]*>',
                r'<div[^>]*class="[^"]*(?:entry-content|kb-content|ht-article-content|post-content)[^"]*"[^>]*>',
                r"<article[^>]*>"):
        mm = re.search(pat, body)
        if mm:
            body = body[mm.end():]
            break
    for end in ('<div class="clear"></div>', '<p class="posted">', '<table class="rnld', 'class="pagesidebar"',
                '<div class="hkb-article__lastupdated', '<div class="hkb-article-tags', '<div class="hkb-feedback',
                '<footer', 'id="footer"', 'class="ht-voting', '<div class="nieuwsbrief'):
        i = body.find(end)
        if i > 200:
            body = body[:i]
    return body


def extract(doc):
    """-> dict met title, html, posted, updated, hero, crumbs (lijst labels)."""
    t = re.search(r"<title>(.*?)</title>", doc, re.S)
    title = html.unescape(t.group(1)).strip() if t else ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", doc, re.S)
    if h1:
        h1t = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip()
        if h1t:
            title = h1t
    hero = re.search(r"class=['\"]header-image['\"][^>]*background-image:\s*url\(\"?'?([^\"')]+)", doc)
    posted = re.search(r'<p class="posted">\s*(.*?)</p>', doc, re.S)
    posted = html.unescape(re.sub(r"<[^>]+>", "", posted.group(1))).strip() if posted else ""
    updated = ""
    if not posted:
        lu = re.search(r'class="hkb-article__lastupdated"[^>]*>(.*?)</div>', doc, re.S)
        if lu:
            # 'Laatste update: 7 december 2022' -> zelfde vorm als bij de releases ('(Laatste update: …)')
            updated = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", lu.group(1)))).strip()
    crumbs = []
    bc = re.search(r'<(?:div|nav|ul|ol)[^>]*(?:id|class)="[^"]*breadcrumb[^"]*"[^>]*>(.*?)</(?:div|nav|ul|ol)>', doc, re.S)
    if bc:
        crumbs = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip()
                  for x in re.findall(r"<(?:a|span|li)[^>]*>(.*?)</(?:a|span|li)>", bc.group(1), re.S)]
        crumbs = [c for c in crumbs if c and c not in ("›", ">", "»", "/")]
    c = Cleaner()
    c.feed(find_content(doc))
    c.close()
    out = "".join(c.out)
    out = re.sub(r"(<br>\s*){2,}", "<br>", out)
    out = re.sub(r"<p>\s*(<br>)?\s*</p>", "", out)
    out = re.sub(r"<(strong|em|b|i|span)>\s*</\1>", "", out)
    out = re.sub(r"\n\s*\n+", "\n", out).strip()
    return {"title": title, "html": out, "posted": posted, "updated": updated,
            "hero": unwrap_wayback(hero.group(1)) if hero else None, "crumbs": crumbs}
