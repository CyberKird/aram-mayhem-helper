"""Tier de augment dupa numele afisat, citit prin OCR.

Doua surse, in ordinea asta:

  1. data/augments/<campion>.json -- clasamentul u.gg pentru campionul jucat
  2. data/augments-global.json    -- clasamentul pe tot modul, ca rezerva

Specific bate global, si nu e o subtilitate: global spune "Steel Your Heart
= S+" si cand joci Kalista, unde itemul din spate nici nu functioneaza (u.gg
il pune B pe Kalista). Global ramane doar pentru campionii inca neadusi in
cache si pentru lista completa de nume pe care o cauta OCR-ul.
"""

import json
import pathlib

TIER_ORDER = ["S+", "S", "A", "B", "C", "D"]
UNKNOWN = "?"

CHAMP_DIR = pathlib.Path(__file__).with_name("data") / "augments"

_champ_cache = {}


AUGMENT_MAP = pathlib.Path(__file__).with_name("data") / "augment-map.json"

# Riot are augmente (majoritatea din Arena) al caror nume e un cuvant care
# apare oricum pe ecran: eticheta de categorie de pe cardul de augment
# ("Damage", "Utility", "Speed"), nume de statistici din descrieri, sau text
# din magazin. Adaugate in vocabular, produceau augmente inventate din text
# perfect normal. Cele clasate de u.gg trec oricum, lista asta filtreaza
# doar completarile din datele Riot.
UI_WORDS = {
    # etichetele de categorie de pe cardul de augment
    "damage", "utility", "speed", "tank", "mage", "support", "fighter",
    "marksman", "assassin", "hybrid",
    # nume de statistici, care apar in descrierile oricarui augment
    "ability haste", "life steal", "attack damage", "ability power", "armor",
    "magic resist", "health", "max health", "mana", "move speed",
    "movement speed", "critical strike", "critical chance", "attack speed",
    "shield", "heal", "area size", "duration", "exp", "long range",
    "pickup radius", "projectile count",
    # rarități si text de magazin
    "mythical", "epic", "legendary", "common", "rare", "prismatic",
    "gold", "silver",
    # rezerve de dezvoltare din datele Riot, fara corespondent in joc
    "???", "null augment", "replace augment", "level augments", "augment 405",
}


def flatten_names(global_augments):
    """Toate numele pe care OCR-ul incearca sa le potriveasca.

    Reuniunea a doua surse, si asta conteaza: u.gg claseaza ~206 augmente,
    dar jocul are peste 500. Un augment pe care u.gg nu-l claseaza (nou la
    patch, sau pur si simplu nelistat) nu era recunoscut DELOC -- vedeai
    doua carduri din trei si parea ca OCR-ul a ratat, cand de fapt numele
    nici nu era cautat. Acum apare, cu tier necunoscut, ceea ce e mult mai
    bine decat sa lipseasca.
    """
    names = []
    for rarity, block in global_augments.items():
        if not isinstance(block, dict):
            continue
        for tier_names in block.values():
            names.extend(tier_names)

    # dedupe fara majuscule: Riot are si "Ok Boomerang" si "OK Boomerang",
    # iar amandoua ajungeau in lista si apareau ca doua augmente diferite
    seen = {n.lower() for n in names}
    if AUGMENT_MAP.exists():
        riot = json.loads(AUGMENT_MAP.read_text(encoding="utf-8"))
        for entry in riot.values():
            name = entry.get("name")
            key = (name or "").lower()
            if name and key not in seen and key not in UI_WORDS:
                seen.add(key)
                names.append(name)
    return names


def load_champion_tiers(champion):
    """{nume augment: tier} pentru campion, sau None daca nu e in cache."""
    if not champion:
        return None
    if champion in _champ_cache:
        return _champ_cache[champion]

    from build_scraper import slug   # aceeasi regula de nume ca la scraping
    path = CHAMP_DIR / f"{slug(champion)}.json"
    table = None
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        table = {name: tier
                 for tier, names in data.get("tiers", {}).items()
                 for name in names}
    _champ_cache[champion] = table
    return table


def lookup_tier(name, global_augments, champion_tiers=None):
    if champion_tiers and name in champion_tiers:
        return champion_tiers[name]

    for rarity, block in global_augments.items():
        if not isinstance(block, dict):
            continue
        for tier, names in block.items():
            if name in names:
                return tier
    return UNKNOWN


def rate(names, global_augments, champion=None):
    """Augmentele oferite, cu tier si care e cel mai bun.

    `champion` face diferenta dintre "cel mai bun augment din joc" si "cel
    mai bun augment pentru campionul pe care il joc acum".
    """
    champion_tiers = load_champion_tiers(champion)
    rated = [{"name": n, "tier": lookup_tier(n, global_augments, champion_tiers)}
             for n in names]

    best_i, best_rank = None, None
    for i, r in enumerate(rated):
        rank = TIER_ORDER.index(r["tier"]) if r["tier"] in TIER_ORDER else len(TIER_ORDER)
        if best_rank is None or rank < best_rank:
            best_i, best_rank = i, rank
    for i, r in enumerate(rated):
        r["is_best"] = (i == best_i)
    return rated
