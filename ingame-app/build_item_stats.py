"""Genereaza data/augment-items.json: augmentele "Upgrade X" -> itemul X.

Itemii (descrieri, statistici defensive, evolutii) NU se mai iau de aici din
Data Dragon: acolo cifrele sunt de ARAM clasic / Arena, iar Mayhem are alt
text (ex. Manamune: 35 AD / 500 mana, nu 40 / 600). Le scrie update_aramkit.py
din itemele de Mayhem. Ruleaza-l DUPA el, la patch nou:

    python update_aramkit.py
    python build_item_stats.py
"""

import json
import pathlib

DATA = pathlib.Path(__file__).with_name("data")
AUG_OUT = DATA / "augment-items.json"


def build_augment_items(item_names):
    """Augmentele care iti cer un item anume -> numele itemului.

    Doar tiparul "Upgrade <Item>", si doar cand itemul chiar exista in joc.
    Alte augmente au nume care seamana cu itemi ("Goredrink" vs Goredrinker,
    "Rejuvenation" vs Rejuvenation Bead) dar nu inseamna ca trebuie sa-i
    cumperi -- pe alea le lasam afara, o recomandare gresita e mai rea decat
    una lipsa.
    """
    import augment_tier
    global_augments = json.loads((DATA / "augments-global.json").read_text(encoding="utf-8"))

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


GROUPS_OUT = DATA / "item-groups.json"
GAME_ITEMS = "https://raw.communitydragon.org/latest/game/items.cdtb.bin.json"


def build_item_groups():
    """{item: [grupuri]}: grupurile din care poti avea un singur item.

    Jocul refuza al doilea item din acelasi grup ("ITEM UNAVAILABLE"): Terminus
    si Lord Dominik's Regards sunt amandoua LastWhisper. Data Dragon nu are
    grupurile, deci le citim din fisierele jocului, prin CommunityDragon.
    """
    import urllib.request
    # fara User-Agent CommunityDragon raspunde 403
    req = urllib.request.Request(GAME_ITEMS, headers={"User-Agent": "aram-mayhem-helper"})
    with urllib.request.urlopen(req, timeout=120) as r:
        game = json.load(r)
    names = json.loads((DATA / "item-ids.json").read_text(encoding="utf-8"))
    single = {k for k, v in game.items()
              if isinstance(v, dict) and v.get("mMaxGroupOwnable") == 1}
    out = {}
    for v in game.values():
        if not isinstance(v, dict) or str(v.get("itemID")) not in names:
            continue
        groups = sorted(g for g in v.get("mItemGroups") or () if g in single)
        if groups:
            out[names[str(v["itemID"])]] = groups
    return out


def main():
    groups = build_item_groups()
    GROUPS_OUT.write_text(json.dumps(groups, indent=1, sort_keys=True), encoding="utf-8")
    print(f"itemi cu grup exclusiv: {len(groups)}")
    names = set(json.loads((DATA / "item-desc.json").read_text(encoding="utf-8")))
    augs = build_augment_items(names)
    AUG_OUT.write_text(json.dumps(augs, indent=1, sort_keys=True, ensure_ascii=False),
                       encoding="utf-8")
    print(f"augmente care cer un item anume: {len(augs)}")
    for aug, item in sorted(augs.items()):
        print(f"  {aug} -> {item}")


if __name__ == "__main__":
    main()
