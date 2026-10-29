#!/usr/bin/env python3
"""Haalt de pagina's van support.fasterforward.nl op uit het Internet Archive (Wayback Machine).

Gebruik (Python 3, geen extra pakketten):
    python3 tools/wayback-ophalen.py                       # alles wat gearchiveerd is, naar ./wayback-support
    python3 tools/wayback-ophalen.py --kennisbank          # alleen /kennisbank/ en de homepage
    python3 tools/wayback-ophalen.py --uit bronnen/wayback # andere doelmap (zo gebruikt de GitHub Action het)
    python3 tools/wayback-ophalen.py --max-minuten 25      # na 25 minuten netjes stoppen (exitcode 3 = nog niet klaar)

Per url wordt de laatste gearchiveerde versie met status 200 opgehaald, als ruwe HTML (zonder de Wayback-balk).
Afbeeldingen en pdf's worden ook opgeslagen; WordPress-cache, css/js, feeds en API-adressen worden overgeslagen.
De lijst met gearchiveerde adressen (CDX) wordt bewaard in <uit>/_cdx.json en hergebruikt, zodat een volgende
ronde direct verder kan. Al aanwezige bestanden worden overgeslagen. Er zit een pauze tussen de verzoeken,
uit respect voor het archief.
"""
import argparse, json, os, re, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HOST = 'support.fasterforward.nl'
ap = argparse.ArgumentParser()
ap.add_argument('--uit', default='wayback-support')
ap.add_argument('--kennisbank', action='store_true')
ap.add_argument('--pauze', type=float, default=1.0)
ap.add_argument('--werkers', type=int, default=4)
ap.add_argument('--max-minuten', type=float, default=0)
ap.add_argument('--verse-lijst', action='store_true', help='CDX-lijst opnieuw opvragen')
a = ap.parse_args()
START = time.time()
OVERSLAAN = re.compile(r'/(wp-content/cache|wp-includes|wp-json|wp-admin|xmlrpc|feed|comments/feed|embed)(/|$)|'
                       r'\.(css|js|woff2?|ttf|eot|map|xml|json|txt)$|[?&](ver|replytocom|s|p)=', re.I)


def haal(url, tries=4, timeout=90):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (herstel eigen site)'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get('Content-Type', '')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, ''
            err = e
        except Exception as e:
            err = e
        time.sleep(3 * (i + 1))
    print('mislukt:', url, err, file=sys.stderr)
    return None, ''


os.makedirs(a.uit, exist_ok=True)
cdx_file = os.path.join(a.uit, '_cdx.json')
if os.path.exists(cdx_file) and not a.verse_lijst:
    rijen = json.load(open(cdx_file))
else:
    q = urllib.parse.urlencode({'url': HOST + '/*', 'output': 'json', 'fl': 'timestamp,original,mimetype',
                                'filter': 'statuscode:200', 'collapse': 'urlkey', 'limit': '20000'})
    data, _ = haal('https://web.archive.org/cdx/search/cdx?' + q, tries=6, timeout=900)
    if not data:
        print('Kon de lijst met gearchiveerde pagina\'s niet ophalen.', file=sys.stderr)
        sys.exit(2)
    rijen = json.loads(data)[1:]
    json.dump(rijen, open(cdx_file, 'w'))
    print('CDX-lijst opgehaald:', len(rijen), 'regels', flush=True)
START = time.time()  # de tijdslimiet geldt voor het downloaden, niet voor het opvragen van de lijst

# per url de nieuwste versie
nieuwste = {}
for ts, orig, mime in rijen:
    orig = orig.replace('http://', 'https://').replace(':80/', '/')
    nieuwste[orig] = max(nieuwste.get(orig, (ts, mime)), (ts, mime))
urls = sorted(u for u in nieuwste if not OVERSLAAN.search(urllib.parse.urlparse(u).path + ('?' + urllib.parse.urlparse(u).query if urllib.parse.urlparse(u).query else '')))
if a.kennisbank:
    urls = [u for u in urls if '/kennisbank/' in u or u.rstrip('/').endswith(HOST)]


def doelpad(u):
    pad = urllib.parse.urlparse(u).path.lstrip('/') or 'index'
    if pad.endswith('/') or not os.path.splitext(pad)[1]:
        pad = pad.rstrip('/') + '/index.html'
    return re.sub(r'[<>:"|?*]', '_', pad)


todo = [u for u in urls if not os.path.exists(os.path.join(a.uit, doelpad(u)))]
print(len(urls), "url's;", len(urls) - len(todo), 'al aanwezig;', len(todo), 'op te halen', flush=True)
log, lock, klaar = [], threading.Lock(), [0]
gestopt = threading.Event()


def een(u):
    if gestopt.is_set():
        return
    if a.max_minuten and time.time() - START > a.max_minuten * 60:
        gestopt.set()
        return
    ts, mime = nieuwste[u]
    inhoud, ct = haal('https://web.archive.org/web/%sid_/%s' % (ts, u))
    if inhoud is not None:
        doel = os.path.join(a.uit, doelpad(u))
        os.makedirs(os.path.dirname(doel), exist_ok=True)
        with open(doel, 'wb') as f:
            f.write(inhoud)
        with lock:
            log.append({'url': u, 'tijdstip': ts, 'bestand': doelpad(u), 'type': mime})
    with lock:
        klaar[0] += 1
        if klaar[0] % 25 == 0:
            print('%d/%d' % (klaar[0], len(todo)), flush=True)
    time.sleep(a.pauze)


with ThreadPoolExecutor(a.werkers) as ex:
    list(ex.map(een, todo))

ov_file = os.path.join(a.uit, '_overzicht.json')
oud = json.load(open(ov_file)) if os.path.exists(ov_file) else []
json.dump(oud + log, open(ov_file, 'w'), indent=1, ensure_ascii=False)
rest = sum(1 for u in urls if not os.path.exists(os.path.join(a.uit, doelpad(u))))
print('Klaar met deze ronde:', len(log), 'nieuw;', rest, 'nog niet opgehaald.', flush=True)
sys.exit(3 if gestopt.is_set() and rest else 0)
