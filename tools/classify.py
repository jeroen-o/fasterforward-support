"""Deelt kennisbankartikelen zonder categorie in bij de best passende subcategorie (TF-IDF, cosinus)."""
import math
import re
from collections import Counter

STOP = set("""de het een en van in op voor met je is te dat die dit deze er om aan bij of als ook naar dan zijn wordt worden kan kun
kunt hebt heeft niet wel nog meer hier daar wat hoe waar wanneer welke zo je jouw jij u uw we wij ons onze ze zij hun als tot uit
door over na via per dus alle elke elk staat staan gaat gaan kies klik vul knop scherm tabblad ga zie lees vind meer tekst onder
boven links rechts nieuwe nieuw eerst daarna vervolgens kunnen moet moeten zal zullen elements eblinqx faster forward""".split())


def woorden(t):
    return [w for w in re.findall(r"[a-zà-ÿ0-9]{3,}", (t or "").lower()) if w not in STOP and not w.isdigit()]


def vector(titel, tekst):
    c = Counter()
    for w in woorden(titel):
        c[w] += 4
    for w in woorden(" ".join(tekst.split()[:400])):
        c[w] += 1
    return c


def indelen(subs, losse, drempel=0.12, marge=1.15):
    """subs: {(cat, sub): [pagina's]}; losse: [pagina's]. Geeft {id(pagina): ((cat, sub), score)}."""
    docs = {k: sum((vector(p["t"], " ".join(p["lines"])) for p in v), Counter()) + Counter({w: 6 for w in woorden(k[1])})
            for k, v in subs.items() if v}
    df = Counter(w for d in docs.values() for w in d)
    n = len(docs)
    idf = {w: math.log((n + 1) / (c + 0.5)) for w, c in df.items()}

    def tfidf(c):
        v = {w: (1 + math.log(f)) * idf.get(w, math.log(n + 1)) for w, f in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {w: x / norm for w, x in v.items()}
    dv = {k: tfidf(d) for k, d in docs.items()}
    uit = {}
    for p in losse:
        q = tfidf(vector(p["t"], " ".join(p["lines"])))
        scores = sorted(((sum(x * dv[k].get(w, 0) for w, x in q.items()), k) for k in dv), reverse=True)
        if scores and scores[0][0] >= drempel and (len(scores) < 2 or scores[0][0] >= marge * scores[1][0]):
            uit[id(p)] = (scores[0][1], round(scores[0][0], 3))
    return uit


# Duidelijke gevallen op titel (gaan vóór de automatische indeling).
REGELS = [
    (r"on ?route", ("Basis", "On route app")),
    (r"\bhdn\b", ("Hypotheken", "Hypotheek aanvragen")),
    (r"echtscheiding", ("Hypotheken", "Case hypotheekadvies")),
    (r"versie(beheer)?|nieuwe versie", ("Hypotheken", "Hypotheken algemeen")),
    (r"e-?mail|mappen beheren", ("E-mail", "Mogelijkheden e-mail")),
    (r"aanspreken met", ("Communicatie", "Standaard teksten en templates")),
    (r"polis opschorten|pakketpolis|omnummeren|nieuwe maatschappij", ("Verzekeringen", "Producten verzekeringen")),
    (r"\badn\b|bedrijfscertificaat|assurantiebelasting|rc maatschappij", ("Verzekeringen", "Prolongeren")),
    (r"pensioen opvoeren|indexeren|aandachtspunten product|categorie van een verzekering", ("Dossier", "Producten dossier")),
    (r"geldigheid document|samenvatting dossier", ("Dossier", "Documenten")),
    (r"wwft|kredietcheck", ("Dossier", "Registraties")),
    (r"dossier|kvk|herkomst|voorkeurstaal|huisstijl", ("Dossier", "Mogelijkheden dossier")),
    (r"productgroep|administratie", ("Boekhouding", "Stamgegevens")),
    (r"taxateurs|skydoo|adviespakketten", ("Koppelingen", "Overige koppelingen")),
    (r"quinn", ("Communicatie", "Gespreksopnames")),
    (r"inlogscherm|starten met", ("Basis", "Beginnen met eBlinqx")),
    (r"pdf bestanden|pop-up|spellingscontrole|screenshot|\bsupport\b|conversie", ("Basis", "Tips en tricks")),
]


def regel(titel):
    t = (titel or "").lower()
    for pat, doel in REGELS:
        if re.search(pat, t):
            return doel
    return None
