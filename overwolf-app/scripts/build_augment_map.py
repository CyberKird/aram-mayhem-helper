"""Genereaza data/augment-map.json: id intern -> {name, rarity}.

GEP trimite id-urile interne ale augmentelor (ex. "ARAM_ADAPt"), iar tier
list-ul de pe u.gg e indexat pe numele afisate. Fisierul asta face legatura.

Sursa e cherry-augments.json din datele de joc (via CommunityDragon), care
contine si augmentele de Mayhem (prefix ARAM_). Atentie: cdragon/arena/en_us.json
NU e bun aici, acela acopera doar modul Arena si ii lipsesc peste 100 din
augmentele de Mayhem.

Ruleaza-l manual la patch nou:
    python scripts/build_augment_map.py
"""

import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "augment-map.json"
GLOBAL = ROOT / "data" / "augments-global.json"

URL = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data"
       "/global/default/v1/cherry-augments.json")
# CommunityDragon respinge user-agent-ul default al lui urllib
HEADERS = {"User-Agent": "Mozilla/5.0"}

RARITY = {"kSilver": "silver", "kGold": "gold", "kPrismatic": "prismatic"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    augments = fetch_json(URL)

    mapping = {}
    for entry in augments:
        key = entry.get("augmentNameId")
        name = entry.get("nameTRA")
        if not key or not name:
            continue
        mapping[key] = {
            "name": name,
            "rarity": RARITY.get(entry.get("rarity"), "unknown"),
        }

    OUT.write_text(json.dumps(mapping, indent=1, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")

    # verificare: fiecare augment clasat pe u.gg trebuie sa aiba un id intern,
    # altfel nu-l putem recunoaste cand GEP il trimite in joc
    tiers = json.loads(GLOBAL.read_text(encoding="utf-8"))
    ranked = {n: rarity
              for rarity, block in tiers.items() if isinstance(block, dict)
              for names in block.values() for n in names}

    live = {}
    for key, val in mapping.items():
        live.setdefault(val["name"], []).append((key, val["rarity"]))

    missing = sorted(n for n in ranked if n not in live)
    mismatch = [(n, r, live[n][0][1]) for n, r in ranked.items()
                if n in live and live[n][0][1] != r]

    aram = sum(1 for k in mapping if k.startswith("ARAM_"))
    print(f"{len(mapping)} augmente ({aram} de Mayhem) -> {OUT.name}")
    print(f"clasate pe u.gg: {len(ranked)}, fara id intern: {len(missing)}")
    if missing:
        print("  lipsa:", ", ".join(missing))
    if mismatch:
        print(f"raritate diferita fata de datele de joc ({len(mismatch)}):", mismatch[:10])


if __name__ == "__main__":
    main()
