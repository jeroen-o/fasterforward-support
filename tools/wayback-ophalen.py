#!/usr/bin/env python3
"""Haalt de pagina's van support.fasterforward.nl op uit het Internet Archive (Wayback Machine).

Gebruik (Python 3, geen extra pakketten):
    python3 wayback-ophalen.py                 # alles wat gearchiveerd is, naar de map ./wayback-support
    python3 wayback-ophalen.py --kennisbank    # alleen /kennisbank/ en de homepage
    python3 wayback-ophalen.py --uit mijnmap   # andere doelmap

Per url wordt de laatste gearchiveerde versie met status 200 opgehaald, als ruwe HTML (zonder de Wayback-balk).
Afbeeldingen, css en pdf's worden ook opgeslagen. Er zit een pauze tussen de verzoeken, uit respect voor het archief.
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request

HOST = 'support.fasterforward.nl'
ap = argparse.ArgumentParser()
ap.add_argument('--uit', default='wayback-support')
ap.add_argument('--kennisbank', action='store_true')
ap.add_argument('--pauze', type=float, default=1.0)
a = ap.parse_args()

def haal(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (herstel eigen site)'})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read(), r.headers.get('Content-Type', '')
        except Exception as e:
            time.sleep(3 * (i + 1))
            err = e
    print('mislukt:', url, err, file=sys.stderr)
    return None, ''

q = urllib.parse.urlencode({'url': HOST + '/*', 'output': 'json', 'fl': 'timestamp,original,mimetype', 'filter': 'statuscode:200', 'collapse': 'urlkey', 'limit': '20000'})
data, _ = haal('https://web.archive.org/cdx/search/cdx?' + q)
if not data:
    sys.exit('Kon de lijst met gearchiveerde pagina\'s niet ophalen.')
rijen = json.loads(data)[1:]
# per url de nieuwste versie
nieuwste = {}
for ts, orig, mime in rijen:
    nieuwste[orig] = max(nieuwste.get(orig, (ts, mime)), (ts, mime))
urls = sorted(nieuwste)
if a.kennisbank:
    urls = [u for u in urls if '/kennisbank/' in u or u.rstrip('/').endswith(HOST)]
print(len(urls), 'url\'s')
os.makedirs(a.uit, exist_ok=True)
log = []
for n, u in enumerate(urls, 1):
    ts, mime = nieuwste[u]
    pad = urllib.parse.urlparse(u).path.lstrip('/') or 'index'
    if pad.endswith('/') or not os.path.splitext(pad)[1]:
        pad = pad.rstrip('/') + '/index.html'
    pad = re.sub(r'[<>:"|?*]', '_', pad)
    doel = os.path.join(a.uit, pad)
    if os.path.exists(doel):
        continue
    inhoud, ct = haal('https://web.archive.org/web/%sid_/%s' % (ts, u))
    if inhoud is None:
        continue
    os.makedirs(os.path.dirname(doel), exist_ok=True)
    with open(doel, 'wb') as f:
        f.write(inhoud)
    log.append({'url': u, 'tijdstip': ts, 'bestand': pad, 'type': mime})
    print('%d/%d %s' % (n, len(urls), u))
    time.sleep(a.pauze)
with open(os.path.join(a.uit, '_overzicht.json'), 'w') as f:
    json.dump(log, f, indent=1, ensure_ascii=False)
print('Klaar:', len(log), 'bestanden in', a.uit)
