"""Genereaza data/item-stats.json: nume de item -> ce aparare/sustain da.

De ce: pana acum regulile ghiceau apararea inamica din tipul campionului
("3+ campioni AP -> ia MR"). Dar Live Client Data ne da itemii reali ai
tuturor jucatorilor, deci putem reactiona la ce au CUMPARAT, nu la ce ar
putea cumpara. Fisierul asta traduce numele itemului in cifrele care ne
intereseaza cand decidem ce contra-item sa recomandam.

Ruleaza-l la patch nou, ca pe celelalte build_*.py:
    python build_item_stats.py
"""

import json
import pathlib
import urllib.request

OUT = pathlib.Path(__file__).with_name("data") / "item-stats.json"
AUG_OUT = pathlib.Path(__file__).with_name("data") / "augment-items.json"
DESC_OUT = pathlib.Path(__file__).with_name("data") / "item-desc.json"
DDRAGON = "https://ddragon.leagueoflegends.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# praguri sub care itemul nu conteaza ca "item de aparare": componentele mici
# (Cloth Armor, Null-Magic Mantle) nu inseamna ca inamicul chiar se apara
MIN_ARMOR = 30
MIN_MR = 30
MIN_HP = 200


def fetch_json(url):
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def build_augment_items(item_names):
    """Augmentele care iti cer un item anume -> numele itemului.

    Doar tiparul "Upgrade <Item>", si doar cand itemul chiar exista in joc.
    Alte augmente au nume care seamana cu itemi ("Goredrink" vs Goredrinker,
    "Rejuvenation" vs Rejuvenation Bead) dar nu inseamna ca trebuie sa-i
    cumperi -- pe alea le lasam afara, o recomandare gresita e mai rea decat
    una lipsa.
    """
    import augment_tier
    global_augments = json.loads(
        (pathlib.Path(__file__).with_name("data") / "augments-global.json")
        .read_text(encoding="utf-8"))

    by_lower = {n.lower(): n for n in item_names}
    out = {}
    for aug in augment_tier.flatten_names(global_augments):
        if not aug.startswith("Upgrade "):
            continue
        base = aug[len("Upgrade "):].strip()
        item = by_lower.get(base.lower())
        if item is None:
            # "Upgrade Zhonya's" -> "Zhonya's Hourglass": prefix unic
            matches = [n for low, n in by_lower.items() if low.startswith(base.lower())]
            item = matches[0] if len(matches) == 1 else None
        if item:
            out[aug] = item
    return out


def item_text(item):
    """Descrierea itemului asa cum o vezi in joc, ca text simplu.

    Data Dragon o da ca HTML (<stats>, <attention>, <passive>, <br>). Pastram
    structura pe randuri, ca sa fie citibila intr-un tooltip, si scoatem
    restul etichetelor.
    """
    import re

    html = item.get("description") or ""
    html = re.sub(r"</?(mainText|stats|attention|scale\w*)>", "", html)
    html = html.replace("<br>", "\n")
    html = re.sub(r"<(passive|active|rules|rarity\w*)>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return "\n".join(line.strip() for line in html.split("\n")).strip()


def main():
    version = fetch_json(f"{DDRAGON}/api/versions.json")[0]
    items = fetch_json(f"{DDRAGON}/cdn/{version}/data/en_US/item.json")["data"]

    out = {}
    for it in items.values():
        name = it.get("name")
        if not name:
            continue
        stats = it.get("stats") or {}
        tags = it.get("tags") or []

        armor = stats.get("FlatArmorMod", 0)
        mr = stats.get("FlatSpellBlockMod", 0)
        hp = stats.get("FlatHPPoolMod", 0)
        # vindecarea vine si din itemi fara stat direct (Bloodthirster,
        # Sterak's), deci ne bazam pe tag-uri, nu doar pe cifre
        heals = bool({"LifeSteal", "SpellVamp", "Health Regen", "HealthRegen"} & set(tags))

        entry = {}
        if armor >= MIN_ARMOR:
            entry["armor"] = armor
        if mr >= MIN_MR:
            entry["mr"] = mr
        if hp >= MIN_HP:
            entry["hp"] = hp
        if heals:
            entry["heal"] = True

        # Tag-ul "Boots" prinde si obiecte de eveniment fara nicio legatura
        # (Healthbar Splash, Party Favor), deci cerem si viteza de deplasare.
        if "Boots" in tags and stats.get("FlatMovementSpeedMod", 0) > 0:
            entry["boots"] = True
        # Consumabilele nu ocupa un slot de build: fara ele n-am sti cand
        # inventarul e "plin". Poro-Snax n-are niciun tag, dar are consumed,
        # deci ne uitam la ambele semnale.
        if "Consumable" in tags or "Trinket" in tags or it.get("consumed"):
            entry["consumable"] = True
        # componentele ("into" = in ce se construiesc) nu sunt un item de
        # sine statator: n-are rost sa vinzi cizmele ca sa iei un Pickaxe
        if it.get("into"):
            entry["component"] = True

        if entry:
            # Data Dragon are duplicate per harta; pastram prima intrare
            out.setdefault(name, entry)

    OUT.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False),
                   encoding="utf-8")

    counts = {k: sum(1 for v in out.values() if k in v)
              for k in ("armor", "mr", "hp", "heal")}
    print(f"patch {version}: {len(out)} itemi cu stat defensiv {counts}")

    # descrierile pentru tooltip la hover: le vrem pentru orice item care
    # poate aparea in overlay, nu doar pentru cele cu stat defensiv
    desc = {}
    for it in items.values():
        name = it.get("name")
        if name:
            text = item_text(it)
            if text:
                desc.setdefault(name, text)
    DESC_OUT.write_text(json.dumps(desc, indent=1, sort_keys=True, ensure_ascii=False),
                        encoding="utf-8")
    print(f"descrieri de item: {len(desc)}")

    augs = build_augment_items({it["name"] for it in items.values() if it.get("name")})
    AUG_OUT.write_text(json.dumps(augs, indent=1, sort_keys=True, ensure_ascii=False),
                       encoding="utf-8")
    print(f"augmente care cer un item anume: {len(augs)}")
    for aug, item in sorted(augs.items()):
        print(f"  {aug} -> {item}")


if __name__ == "__main__":
    main()
