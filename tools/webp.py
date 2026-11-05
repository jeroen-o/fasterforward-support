"""WebP-stap na het bouwen: elke lokale JPG/PNG in een <img> of <video poster> van de gegenereerde pagina's krijgt een
WebP-versie ernaast (<naam>.<ext>.webp, kwaliteit 82, maximaal 2000 px) en de pagina verwijst daarnaar. Afbeeldingen
zonder afmetingen krijgen width/height, zodat de pagina niet verspringt tijdens het laden (CLS).
Originelen blijven staan: de build leest ze, en og:image / JSON-LD (delen op LinkedIn en WhatsApp) gebruiken ze.
Een WebP wordt alleen (opnieuw) gemaakt als die ontbreekt of ouder is dan het origineel.
"""
import os, re

OVERSLAAN = (".git", "tools", "node_modules")
MAX = 2000


def _maak(bron, doel):
    from PIL import Image
    im = Image.open(bron)
    if getattr(im, "is_animated", False):
        return None
    im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
    if max(im.size) > MAX:
        im.thumbnail((MAX, MAX))
    im.save(doel, "WEBP", quality=82, method=5)
    return im.size


def uitvoeren(root):
    from PIL import Image
    maten, gemaakt, pagina_n, img_n = {}, 0, 0, 0

    assets, bron_assets = os.path.join(root, "assets") + os.sep, os.path.join(root, "tools", "assets") + os.sep

    def webp_van(abs_bron):
        nonlocal gemaakt
        doel = abs_bron + ".webp"
        if abs_bron in maten:
            return maten[abs_bron]
        if abs_bron.startswith(assets) and os.path.exists(bron_assets + abs_bron[len(assets):]):
            # assets/ wordt elke build opnieuw gekopieerd uit tools/assets/: de WebP daar bewaren, zodat hij blijft staan
            import shutil
            tb = bron_assets + abs_bron[len(assets):]
            try:
                if not os.path.exists(tb + ".webp") or os.path.getmtime(tb + ".webp") < os.path.getmtime(tb):
                    if _maak(tb, tb + ".webp") is None:
                        maten[abs_bron] = None
                        return None
                    gemaakt += 1
                if not os.path.exists(doel):
                    shutil.copy2(tb + ".webp", doel)
                with Image.open(doel) as im:
                    maten[abs_bron] = im.size
            except Exception as e:  # noqa: BLE001
                print("webp mislukt:", abs_bron, e)
                maten[abs_bron] = None
            return maten[abs_bron]
        try:
            if not os.path.exists(doel) or os.path.getmtime(doel) < os.path.getmtime(abs_bron):
                if _maak(abs_bron, doel) is None:
                    maten[abs_bron] = None
                    return None
                gemaakt += 1
            with Image.open(doel) as im:
                maten[abs_bron] = im.size
        except Exception as e:  # noqa: BLE001
            print("webp mislukt:", abs_bron, e)
            maten[abs_bron] = None
        return maten[abs_bron]

    for map_, dirs, files in os.walk(root):
        rel_map = os.path.relpath(map_, root)
        if rel_map.split(os.sep)[0] in OVERSLAAN or rel_map.startswith(("bronnen", os.path.join("brochures", "viewer"))):
            dirs[:] = []
            continue
        for fn in files:
            if not fn.endswith(".html"):
                continue
            pad = os.path.join(map_, fn)
            s = open(pad, encoding="utf8").read()
            veranderd = [False]

            def tag(m):
                t = m.group(0)
                attr = "poster" if t.startswith("<video") else "src"
                a = re.search(r'\s' + attr + r'="([^"]+)"', t)
                if not a:
                    return t
                src = a.group(1)
                if src.startswith(("http:", "https:", "data:", "//")):
                    return t
                if attr == "src" and re.search(r"\.(webp|gif)$", src.split("?")[0], re.I) and not re.search(r'\s(width|height)="', t):
                    w = os.path.normpath(os.path.join(map_, src.split("?")[0]))
                    if w not in maten:
                        try:
                            with Image.open(w) as im:
                                maten[w] = im.size
                        except Exception:  # noqa: BLE001
                            maten[w] = None
                    if maten[w]:
                        veranderd[0] = True
                        return t.replace("<img", f'<img width="{maten[w][0]}" height="{maten[w][1]}"', 1)
                    return t
                if not re.search(r"\.(jpe?g|png)$", src.split("?")[0], re.I):
                    return t
                abs_bron = os.path.normpath(os.path.join(map_, src.split("?")[0]))
                if not os.path.exists(abs_bron):
                    return t
                maat = webp_van(abs_bron)
                if not maat:
                    return t
                nieuw = t[:a.start()] + f' {attr}="{src.split("?")[0]}.webp"' + t[a.end():]
                if attr == "src" and not re.search(r'\swidth="', nieuw) and not re.search(r'\sheight="', nieuw):
                    nieuw = nieuw.replace("<img", f'<img width="{maat[0]}" height="{maat[1]}"', 1)
                veranderd[0] = True
                return nieuw
            # alleen in de body (niet in <head>: og:image en JSON-LD blijven het origineel)
            i = s.find("<body")
            if i < 0:
                continue
            body = re.sub(r"<(?:img|video)\b[^>]*>", tag, s[i:])
            if veranderd[0]:
                open(pad, "w", encoding="utf8").write(s[:i] + body)
                pagina_n += 1
                img_n += body.count(".webp\"")
    print(f"webp: {gemaakt} nieuw gemaakt, {pagina_n} pagina's bijgewerkt")
