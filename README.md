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
| E-learnings (Storylane) | 18 |

Verder: zoekpagina (`/zoeken/`, werkt volledig in de browser), `sitemap.xml`, `404.html`.

## Mappen

- `index.html` + artikelmappen — de gegenereerde site (niet met de hand bewerken).
- `assets/` — CSS, logo, hero-foto's, lettertype (Open Sans, lokaal), video-thumbnails.
- `bronnen/` — ruwe bronnen:
  - `offline-archief/` — 473 pagina's met tekst + screenshot (Wayback Machine, okt 2026)
  - `volledige-tekst.html` — 556 pagina's volledige tekst
  - `inventaris.html` — 801 URL's met samenvatting en 1.718 afbeeldings-URL's
  - `afbeeldingen.html` — 26 afbeeldingen gevonden via Google Afbeeldingen
- `tools/` — `build.py` (genereert de site), `download_afbeeldingen.py`, `videos.json`, `elearning.txt`.

## Opnieuw bouwen

```bash
python3 tools/build.py
```

## Afbeeldingen

Artikelen tonen hun afbeeldingen nu via de Wayback Machine. Om ze lokaal in de repo te krijgen
(aanbevolen vóór livegang):

- **GitHub**: Actions → *Afbeeldingen ophalen en site bouwen* → *Run workflow*, of
- **lokaal**: `python3 tools/download_afbeeldingen.py && python3 tools/build.py`

De bestanden komen in `wp-content/uploads/...` (zelfde pad als op de oude site).

## Nog te doen

- URL van de **statuspagina** invullen (staat nu op `#`, in `tools/build.py`).
- LinkedIn-link controleren (`https://www.linkedin.com/company/blinqx/`).
- Teksten uit de Elements-periode verwijzen nog naar `support@fasterforward.nl` en *Elements*;
  inhoudelijk nalopen waar nodig.
