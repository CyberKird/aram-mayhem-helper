"""Genereaza data/item-sprites.json: coordonata din sprite -> nume de item.

u.gg nu pune id-uri de itemi in DOM, deseneaza itemii din sprite sheet-uri
(`item3.webp` + `background-position: -48px -288px`). Data Dragon publica exact
aceleasi coordonate in item.json, deci maparea inversa e exacta, nu ghicita.

Ruleaza-l manual la patch nou:
    python scripts/build_item_sprites.py
"""

import json
import pathlib
import urllib.request

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "item-sprites.json"
VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
ITEMS = "https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/item.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    version = fetch_json(VERSIONS)[0]
    items = fetch_json(ITEMS.format(v=version))["data"]

    sprites = {}
    for item_id, item in items.items():
        img = item.get("image") or {}
        sprite, x, y = img.get("sprite"), img.get("x"), img.get("y")
        name = item.get("name")
        if not (sprite and name) or x is None or y is None:
            continue
        # cheia foloseste numele fara extensie: u.gg serveste .webp, Data Dragon .png
        key = sprite.rsplit(".", 1)[0]
        sprites.setdefault(key, {})[f"{x},{y}"] = name

    OUT.write_text(json.dumps(sprites, indent=0, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")

    total = sum(len(v) for v in sprites.values())
    print(f"Data Dragon {version}: {total} itemi in {len(sprites)} sprite-uri -> {OUT.name}")

    # verificare pe o coordonata cunoscuta, extrasa manual de pe pagina de Sett
    check = sprites.get("item3", {}).get("48,288")
    print("verificare item3 @ 48,288 =", check)
    assert check, "maparea sprite -> item nu mai corespunde"


if __name__ == "__main__":
    main()
