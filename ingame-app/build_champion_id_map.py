"""Genereaza data/champion-id-map.json: id intern Riot -> nume afisat.

Live Client Data API foloseste id-uri interne (championName: "MonkeyKing",
"FiddleSticks", "Nunu"), diferite de numele afisate din tier list si din
champion-tags.json ("Wukong", "Fiddlesticks", "Nunu & Willump"). Fisierul asta
face legatura, folosind champul `id` din Data Dragon (nu numeric).

Ruleaza-l manual la patch nou:
    python build_champion_id_map.py
"""

import json
import pathlib
import urllib.request

OUT = pathlib.Path(__file__).with_name("data") / "champion-id-map.json"
VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMPIONS = "https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/champion.json"


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    version = fetch_json(VERSIONS)[0]
    data = fetch_json(CHAMPIONS.format(v=version))["data"]
    mapping = {c["id"]: c["name"] for c in data.values()}
    OUT.write_text(json.dumps(mapping, indent=1, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")
    print(f"Data Dragon {version}: {len(mapping)} campioni -> {OUT.name}")


if __name__ == "__main__":
    main()
