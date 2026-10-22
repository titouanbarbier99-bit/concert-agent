"""Villes et regions francaises utilisees par les tools et le moteur de regles."""

import re
import unicodedata

REGIONS = {
    "IDF": "Île-de-France",
    "ARA": "Auvergne-Rhône-Alpes",
    "PAC": "Provence-Alpes-Côte d'Azur",
    "OCC": "Occitanie",
    "NAQ": "Nouvelle-Aquitaine",
    "HDF": "Hauts-de-France",
    "GES": "Grand Est",
    "PDL": "Pays de la Loire",
    "BRE": "Bretagne",
    "NOR": "Normandie",
    "BFC": "Bourgogne-Franche-Comté",
    "CVL": "Centre-Val de Loire",
    "COR": "Corse",
}

CITY_TO_REGION = {
    "paris": "IDF", "saint-denis": "IDF", "nanterre": "IDF", "creteil": "IDF",
    "cergy": "IDF", "evry": "IDF",
    "lyon": "ARA", "grenoble": "ARA", "saint-etienne": "ARA",
    "clermont-ferrand": "ARA", "annecy": "ARA", "villeurbanne": "ARA",
    "marseille": "PAC", "nice": "PAC", "toulon": "PAC",
    "aix-en-provence": "PAC", "avignon": "PAC",
    "toulouse": "OCC", "montpellier": "OCC", "nimes": "OCC", "perpignan": "OCC",
    "bordeaux": "NAQ", "la rochelle": "NAQ", "poitiers": "NAQ",
    "limoges": "NAQ", "pau": "NAQ",
    "lille": "HDF", "amiens": "HDF", "dunkerque": "HDF", "valenciennes": "HDF",
    "strasbourg": "GES", "metz": "GES", "nancy": "GES", "reims": "GES",
    "amneville": "GES",
    "nantes": "PDL", "angers": "PDL", "le mans": "PDL",
    "rennes": "BRE", "brest": "BRE",
    "rouen": "NOR", "caen": "NOR", "le havre": "NOR",
    "dijon": "BFC", "besancon": "BFC",
    "orleans": "CVL", "tours": "CVL",
    "ajaccio": "COR", "bastia": "COR",
}

CITY_CANON = {
    "paris": "Paris", "saint-denis": "Saint-Denis", "nanterre": "Nanterre",
    "creteil": "Créteil", "cergy": "Cergy", "evry": "Évry",
    "lyon": "Lyon", "grenoble": "Grenoble", "saint-etienne": "Saint-Étienne",
    "clermont-ferrand": "Clermont-Ferrand", "annecy": "Annecy",
    "villeurbanne": "Villeurbanne",
    "marseille": "Marseille", "nice": "Nice", "toulon": "Toulon",
    "aix-en-provence": "Aix-en-Provence", "avignon": "Avignon",
    "toulouse": "Toulouse", "montpellier": "Montpellier", "nimes": "Nîmes",
    "perpignan": "Perpignan",
    "bordeaux": "Bordeaux", "la rochelle": "La Rochelle", "poitiers": "Poitiers",
    "limoges": "Limoges", "pau": "Pau",
    "lille": "Lille", "amiens": "Amiens", "dunkerque": "Dunkerque",
    "valenciennes": "Valenciennes",
    "strasbourg": "Strasbourg", "metz": "Metz", "nancy": "Nancy",
    "reims": "Reims", "amneville": "Amnéville",
    "nantes": "Nantes", "angers": "Angers", "le mans": "Le Mans",
    "rennes": "Rennes", "brest": "Brest",
    "rouen": "Rouen", "caen": "Caen", "le havre": "Le Havre",
    "dijon": "Dijon", "besancon": "Besançon",
    "orleans": "Orléans", "tours": "Tours",
    "ajaccio": "Ajaccio", "bastia": "Bastia",
}


def norm(value):
    """Minuscules, sans accents, sans tirets, espaces normalises."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower().replace("’", "'").replace("'", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_CITY_BY_NORM = {norm(k): v for k, v in CITY_CANON.items()}
_REGION_BY_NORM = {norm(k): k for k in REGIONS}
_REGION_NAME_BY_NORM = {norm(v): k for k, v in REGIONS.items()}


def find_city(text):
    """Retourne la ville canonique mentionnee, ou None (la plus longue d'abord)."""
    haystack = " " + norm(text) + " "
    for key in sorted(_CITY_BY_NORM, key=len, reverse=True):
        if " " + key + " " in haystack:
            return _CITY_BY_NORM[key]
    return None


def detect_region(text):
    """Retourne un code region (ARA, IDF...) depuis un nom de region ou une ville."""
    haystack = " " + norm(text) + " "
    for key in sorted(_REGION_NAME_BY_NORM, key=len, reverse=True):
        if " " + key + " " in haystack:
            return _REGION_NAME_BY_NORM[key]
    for key in sorted(_REGION_BY_NORM, key=len, reverse=True):
        if " " + key + " " in haystack:
            return _REGION_BY_NORM[key]
    city = find_city(text)
    if city:
        return CITY_TO_REGION.get(norm(city))
    return None


def region_name(code):
    return REGIONS.get(code, code or "")


def region_code(value):
    """Accepte un code (ARA), un nom (Auvergne-Rhone-Alpes) ou une ville."""
    if not value:
        return None
    key = norm(value)
    if key.upper() in REGIONS:
        return key.upper()
    if key in _REGION_NAME_BY_NORM:
        return _REGION_NAME_BY_NORM[key]
    if key in _REGION_BY_NORM:
        return _REGION_BY_NORM[key]
    return detect_region(value)


def city_region_code(city, state_name=""):
    code = detect_region(state_name or "") if state_name else None
    if code:
        return code
    return CITY_TO_REGION.get(norm(city))
