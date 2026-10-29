#!/usr/bin/env python3
"""Maakt delen van een schermafbeelding onleesbaar (pixelen) of dekt ze volledig af.

Gebruik: python3 tools/onleesbaar.py <bestand> x0,y0,x1,y1 [x0,y0,x1,y1 ...] [--dek x0,y0,x1,y1 ...]
Coördinaten in pixels van het originele bestand. Na --dek worden vlakken volledig grijs gemaakt
(voor QR-codes, tokens en wachtwoorden); daarvoor gepixeld (namen, adressen, e-mail, telefoon, IBAN).
"""
import sys
from PIL import Image, ImageDraw

pad, *rest = sys.argv[1:]
im = Image.open(pad)
fmt = im.format
im = im.convert("RGB")
dek = False
for a in rest:
    if a == "--dek":
        dek = True
        continue
    x0, y0, x1, y1 = (int(float(v)) for v in a.split(","))
    x1, y1 = min(x1, im.width), min(y1, im.height)
    if dek:
        ImageDraw.Draw(im).rectangle((x0, y0, x1, y1), fill=(225, 225, 225))
    else:
        r = im.crop((x0, y0, x1, y1))
        w, h = r.size
        im.paste(r.resize((max(1, w // 7), max(1, h // 7)), Image.BILINEAR).resize((w, h), Image.NEAREST), (x0, y0))
im.save(pad, quality=90) if fmt == "JPEG" else im.save(pad)
print("bijgewerkt:", pad)
