# Extract support.fasterforward.nl

Gemaakt op 28 oktober 2026 uit twee bronnen: de pagina's die ik op 20 oktober 2026 van de live site heb gedownload, en alles wat Adviesforum over die site bewaart.

## Inhoud
- `paginas-html/`: de ruwe HTML van 47 opgehaalde pagina's (releasenotes-overzicht, alle releaseberichten 2023-2026, contact en beleidspagina's), zoals ze op 20 oktober online stonden.
- `paginas-tekst/`: dezelfde pagina's als schone tekst (titel, url, inhoud).
- `paginas.json`: lijst van die pagina's met url, titel, categorie, plaatsingsdatum en bestandsnamen.
- `verwijzingen-in-adviesforum.csv`: alle 26 unieke verwijzingen naar support.fasterforward.nl in Adviesforum, met titel, aantal keer, waar ze staan en of de inhoud in dit pakket zit.
- `inhoud-uit-adviesforum.md`: onze eigen samenvattingen en 70 veelgestelde vragen die op die supportpagina's zijn gebaseerd (in eigen woorden, geen kopie).

## Wat ontbreekt
- De site is op dit moment niet bereikbaar vanuit mijn omgeving (verbinding wordt afgebroken), dus ik kon geen nieuwe pagina's ophalen.
- Van 24 verwijzingen heb ik alleen de url en titel, niet de inhoud: de kennisbankartikelen (`/kennisbank/...`), de homepage en de supportpagina's. Zie de kolom "inhoud in dit pakket" in het csv-bestand.
- Het Internet Archive heeft volgens zijn index een kopie van 29 juni 2026 (web.archive.org/web/2026*/support.fasterforward.nl/*). Mijn omgeving kan die niet downloaden; vanaf een gewone computer kan dat met bijvoorbeeld `waybackpy` of `wayback_machine_downloader`.
- Afbeeldingen, css en bijlagen zitten niet in het pakket, alleen de HTML van de pagina's.

## Let op
De teksten van de supportpagina's zijn van de eigenaar van die site (Blinqx / Faster Forward). Gebruik ze alleen om die site zelf te herstellen of met toestemming van de eigenaar.
