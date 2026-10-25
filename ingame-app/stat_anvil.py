"""Recomandare shard pentru Stat Anvil, pe baza campionului si a inamicilor.

Stat Anvil (750g, nivel 9+, cumparat din shop) ofera 3 Stat Shards random,
toate de acelasi tier -- alegerea intre ele NU e tinuta de niciun tier list
public (spre deosebire de augmente pe u.gg), deci nu exista date de scrapuit.
Euristici scrise de mana, in acelasi spirit ca rules_engine.py: nu inventam
date, doar punctam optiunile deja oferite dupa cat de bine se potrivesc cu
campionul si compozitia inamica.
"""

# nume de pe carduri -> categorie de scor. Un singur nume per shard indiferent
# de tier (Silver/Gold/Prismatic dau acelasi nume, doar valoarea difera).
SHARD_CATEGORY = {
    "Ability Haste Shard": "haste",
    "Ability Power Shard": "ap",
    "Armor Shard": "armor",
    "Attack Damage Shard": "ad",
    "Attack Speed Shard": "as",
    "Critical Strike Shard": "crit",
    "Health Shard": "hp",
    "Lethality Shard": "pen_ad",
    "Magic Penetration Shard": "pen_ap",
    "Magic Resist Shard": "mr",
    "Might Shard": "hybrid_dmg",
    "Swiftness Shard": "hybrid_utility",
    "Unbreakable Shard": "hybrid_defense",
    "Armor Penetration Shard": "pen_ad",
    "Critical Damage Shard": "crit",
    "Health & Size Shard": "hp",
    "Move Speed Shard": "mobility",
    "Omnivamp Shard": "sustain",
    "Spirit Shard": "heal_power",
    "Tenacity Shard": "cc_resist",
}

SHARD_NAMES = list(SHARD_CATEGORY)

# scor de baza per categorie, dupa damageType-ul campionului (AD/AP/mixed)
CATEGORY_BY_DAMAGE = {
    "ap":              {"AP": 10, "mixed": 6, "AD": 0},
    "ad":              {"AD": 10, "mixed": 6, "AP": 0},
    "haste":           {"AP": 8, "mixed": 6, "AD": 4},
    "as":              {"AD": 7, "mixed": 4, "AP": 1},
    "crit":            {"AD": 5, "mixed": 3, "AP": 0},
    "hp":              {"AP": 5, "AD": 5, "mixed": 5},
    "pen_ad":          {"AD": 8, "mixed": 5, "AP": 0},
    "pen_ap":          {"AP": 8, "mixed": 5, "AD": 0},
    "mr":              {"AP": 3, "AD": 3, "mixed": 3},
    "armor":           {"AP": 3, "AD": 3, "mixed": 3},
    "hybrid_dmg":      {"AD": 6, "AP": 6, "mixed": 8},
    "hybrid_utility":  {"AD": 6, "AP": 6, "mixed": 6},
    "hybrid_defense":  {"AD": 4, "AP": 4, "mixed": 4},
    "mobility":        {"AD": 4, "AP": 4, "mixed": 4},
    "sustain":         {"AD": 5, "AP": 2, "mixed": 4},
    "heal_power":      {"AD": 1, "AP": 3, "mixed": 2},
    "cc_resist":       {"AD": 3, "AP": 3, "mixed": 3},
}

# bonus dupa tag-urile campionului (Fighter/Mage/Marksman/Tank/Support/Assassin)
TAG_BONUS = {
    "Marksman": {"crit": 6, "as": 4, "ad": 2},
    "Mage":     {"ap": 3, "pen_ap": 3, "haste": 2},
    "Assassin": {"pen_ad": 3, "pen_ap": 3, "sustain": 2},
    "Fighter":  {"hybrid_defense": 2, "sustain": 3, "hp": 2},
    "Tank":     {"hp": 5, "armor": 4, "mr": 4, "hybrid_defense": 5, "cc_resist": 3},
    "Support":  {"heal_power": 5, "hp": 2, "cc_resist": 2},
}

# per punct de inamic cu damage type-ul respectiv, pe langa scorul de baza --
# tancul de armura conteaza mai mult contra o echipa toata AD
ENEMY_DAMAGE_WEIGHT = {"armor": ("AD", 1.5), "mr": ("AP", 1.5),
                       "hybrid_defense": (None, 0.75)}


def score_parts(category, damage_type, tags, enemy_ad, enemy_ap):
    """[(puncte, motiv)] din care se aduna scorul. Motivul cu cele mai multe
    puncte e ce afisam: "de ce asta, la campionul asta"."""
    parts = [(CATEGORY_BY_DAMAGE.get(category, {}).get(damage_type, 3),
              f"campion {damage_type}")]
    for tag in tags or ():
        bonus = TAG_BONUS.get(tag, {}).get(category, 0)
        if bonus:
            parts.append((bonus, tag.lower()))

    weight = ENEMY_DAMAGE_WEIGHT.get(category)
    if weight:
        dmg_type, factor = weight
        if dmg_type is None:
            parts.append(((enemy_ad + enemy_ap) * factor, "inamici"))
        elif dmg_type == "AD":
            parts.append((enemy_ad * factor, "inamici AD"))
        elif dmg_type == "AP":
            parts.append((enemy_ap * factor, "inamici AP"))
    return parts


def score_shard(category, damage_type, tags, enemy_ad, enemy_ap):
    """Scor euristic (nu absolut, doar comparativ intre cele 3 oferite)."""
    return sum(p for p, _ in score_parts(category, damage_type, tags, enemy_ad, enemy_ap))


PRICE = 750
LEVEL = 9
ITEM = "Stat Bonus"           # numele itemului Stat Anvil in datele de Mayhem
MIN_CORE = 2


def advise(level, gold, own_items, full, core, left_gold, left_items, next_gold):
    """Cand sa cumperi Stat Anvil, in functie de aur si de cat mai ai pana la build complet.

      locked  nivel < 9     wait  prea putine iteme terminate   gold  nu ai 750g
      buy     ia-l acum     use   il ai deja: deschide-l
    `left_gold`/`left_items`: ce mai lipseste din build; `next_gold`: itemul urmator.
    """
    out = {"left_gold": left_gold, "left_items": left_items}
    progress = "Build complet." if not left_items else f"Pana la build complet: {left_items} iteme, ~{left_gold}g."
    if ITEM in (own_items or ()):
        out.update(state="use", when="Ai deja Stat Anvil: deschide-l si alege un shard.")
    elif not isinstance(level, int) or level < LEVEL:
        out.update(state="locked", when=f"Se deschide la nivel {LEVEL}. {progress}")
    elif core < MIN_CORE and not full:
        out.update(state="wait", when=f"Mai intai {MIN_CORE} iteme terminate ({core} acum). {progress}")
    elif not isinstance(gold, (int, float)) or gold < PRICE:
        need = PRICE - int(gold or 0)
        out.update(state="gold", need=need, when=f"Mai ai nevoie de {need}g. {progress}")
    else:
        after = int(gold) - PRICE
        tail = ("" if not next_gold else
                f" Dupa el ai {after}g: itemul urmator costa ~{next_gold}g" + (" (ajunge)." if after >= next_gold else f" (mai lipsesc {next_gold - after}g)."))
        out.update(state="buy", when=f"Ia-l la urmatorul recall (750g). {progress}{tail}")
    return out


def recommend(names, champion_tags, champ, enemies):
    """[{name, category, score, is_best}] in ordinea primita (a cardurilor).

    names: pana la 3 nume de shard, in ordinea de pe ecran (stanga->dreapta).
    champ: campionul jucat. enemies: lista de nume de campioni inamici.
    Fara campion cunoscut, tot dam un scor (damage_type "mixed"), doar ca
    fara bonusurile de tag -- mai bine o recomandare neutra decat nimic.
    """
    meta = (champion_tags or {}).get(champ) or {}
    damage_type = meta.get("damageType", "mixed")
    tags = meta.get("tags", [])

    enemy_ad = enemy_ap = 0
    for e in enemies or ():
        emeta = (champion_tags or {}).get(e)
        if not emeta:
            continue
        if emeta.get("damageType") == "AD":
            enemy_ad += 1
        elif emeta.get("damageType") == "AP":
            enemy_ap += 1
        elif emeta.get("damageType") == "mixed":
            enemy_ad += 0.5
            enemy_ap += 0.5

    entries = []
    for name in names:
        category = SHARD_CATEGORY.get(name, "hp")
        parts = score_parts(category, damage_type, tags, enemy_ad, enemy_ap)
        entries.append({
            "name": name,
            "category": category,
            "score": sum(p for p, _ in parts),
            "why": max(parts)[1],
        })

    if entries:
        best = max(entries, key=lambda e: e["score"])
        for e in entries:
            e["is_best"] = e is best
            # campionul si motivul, ca sa se vada ca recomandarea e pentru
            # EL, nu una generica
            e["champion"] = champ
    return entries
