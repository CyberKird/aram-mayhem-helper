"""Genereaza data/champion-tags.json din Data Dragon.

Script de dezvoltare. Ruleaza-l manual la patch nou:
    python scripts/build_champion_tags.py
"""

import json
import pathlib
import urllib.request

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "champion-tags.json"
VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMPIONS = "https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/champion.json"


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def damage_type(info):
    """AD / AP / mixed dupa scorurile Data Dragon.

    Aproximativ prin constructie: Data Dragon nu publica un split real de damage,
    doar scorurile astea de la 0 la 10.
    """
    attack, magic = info.get("attack", 0), info.get("magic", 0)
    if magic - attack >= 3:
        return "AP"
    if attack - magic >= 3:
        return "AD"
    return "mixed"


def main():
    version = fetch_json(VERSIONS)[0]
    data = fetch_json(CHAMPIONS.format(v=version))["data"]

    out = {}
    for champ in data.values():
        out[champ["name"]] = {
            "tags": champ.get("tags", []),
            "damageType": damage_type(champ.get("info", {})),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")

    counts = {}
    for v in out.values():
        counts[v["damageType"]] = counts.get(v["damageType"], 0) + 1
    print(f"Data Dragon {version}: {len(out)} campioni -> {OUT.name} {counts}")


if __name__ == "__main__":
    main()
