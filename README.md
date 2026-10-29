# Blinqx Support (support.fasterforward.nl) — herstelde website

Reconstructie van de supportsite **support.fasterforward.nl** (Blinqx powered by Faster Forward),
opgebouwd uit gearchiveerde opnames. Statische HTML, geen build-stap nodig om te hosten: zet de
repo-root op een webserver of GitHub Pages en de site werkt. De URL-structuur is gelijk aan het
origineel (bijv. `/kennisbank/matching-adn-posten/`), zodat oude links en zoekresultaten blijven werken.

## Inhoud

| Onderdeel | Aantal |
|---|---|
| Artikelen / pagina's met volledige tekst | 558 |
| Kennisbankcategorieën (tegels) | 10 + Overig |
| Subcategorieën | 62 |
| Nieuws / Tips / Release notes | 115 / 16 / 66 |
| Video's (YouTube + WebinarGeek-replays) | 60 |
| E-learnings (Storylane + video), met alle stappen als tekst | 18 |
| Releasenotes eBlinqx Hypotheekadvies (Fastlane), per maand | 37 |

Verder: zoekpagina (`/zoeken/`, werkt volledig in de browser), `sitemap.xml`, `404.html`.

## Mappen

- `index.html` + artikelmappen — de gegenereerde site (niet met de hand bewerken).
- `assets/` — CSS, logo, hero-foto's, lettertype (Open Sans, lokaal), video-thumbnails.
- `bronnen/` — ruwe bronnen (in volgorde van voorrang bij het bouwen):
  - `live-2026-10-20/` — 47 pagina's van de live site op 20 oktober 2026 (ruwe HTML; o.a. alle releasenotes 2023–2026)
  - `wayback/` — originele HTML en bestanden uit de Wayback Machine (gevuld door de GitHub Action)
  - `elearning/` — 17 e-learnings (Storylane): stappen + schermafbeeldingen, via `tools/storylane_ophalen.py`
  - `fastlane/` — releasenotes eBlinqx Hypotheekadvies 2023–2026 van fastlane.hypotheekbond.nl + afbeeldingen (WebP)
  - `offline-archief/` — 473 pagina's met tekst + screenshot (Wayback Machine, okt 2026)
  - `volledige-tekst.html` — 556 pagina's volledige tekst
  - `inventaris.html` — 801 URL's met samenvatting en 1.718 afbeeldings-URL's
  - `afbeeldingen.html` — 26 afbeeldingen gevonden via Google Afbeeldingen
- `tools/` — `build.py` (genereert de site), `download_afbeeldingen.py`, `videos.json`, `elearning.txt`.

## Opnieuw bouwen

```bash
python3 tools/build.py
```

## Internet Archive ophalen (kennisbankartikelen, afbeeldingen)

**GitHub**: Actions → *Internet Archive ophalen en site bouwen* → *Run workflow*. De workflow draait
`tools/wayback-ophalen.py` (per URL de nieuwste gearchiveerde versie, naar `bronnen/wayback/`), vult
ontbrekende afbeeldingen aan, bouwt de site en commit het resultaat. Mag opnieuw gestart worden: wat al
binnen is wordt overgeslagen.

**Lokaal**:

```bash
python3 tools/wayback-ophalen.py --uit bronnen/wayback
python3 tools/build.py
```

Pagina's met originele HTML krijgen de echte opmaak terug (koppen, tabellen, afbeeldingen op hun plek);
voor de rest valt de build terug op de tekstbronnen. Afbeeldingen die nog niet lokaal staan, worden via de
Wayback Machine geladen.

## Hosting

De site draait op GitHub Pages: https://jeroen-o.github.io/fasterforward-support/ . Bij een eigen domein
(bijv. support.fasterforward.nl) bouwen met `SITE_BASE=/ python3 tools/build.py` (alleen nodig voor `404.html`).

## Nog te doen

- URL van de **statuspagina** invullen (staat nu op `#`, in `tools/build.py`).
- LinkedIn-link controleren (`https://www.linkedin.com/company/blinqx/`).
- Teksten uit de Elements-periode verwijzen nog naar `support@fasterforward.nl` en *Elements*;
  inhoudelijk nalopen waar nodig.
