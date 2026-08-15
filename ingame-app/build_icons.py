"""Descarca iconitele oficiale in data/icons/{items,champions,augments,summoners}/.

Patru surse, fiecare cea autoritara pentru felul ei:

  itemi      Data Dragon (img/item) -- aceeasi sursa ca build_item_sprites.py
  campioni   Data Dragon (img/champion), numele intern != cel afisat
             ("MonkeyKing" -> Wukong), deci mapam prin champion.json
  augmente   CommunityDragon, cherry-augments.json. NU folosi
             cdragon/arena/en_us.json: acopera doar Arena si ii lipsesc
             peste 100 din augmentele de Mayhem (vezi build_augment_map.py).
  summoners  Data Dragon (img/spell), numele afisat de u.gg ("Ghost") difera
             de id-ul intern Riot ("SummonerHaste"), mapam prin summoner.json.

Fisierele sunt numite dupa numele AFISAT trecut prin slug(), pentru ca asta
e singurul lucru pe care UI-ul il are la indemana (OCR-ul si tier list-ul de
pe u.gg lucreaza tot pe nume afisate, nu pe id-uri).

Ruleaza-l o data, si din nou la patch nou / dupa prefetch_builds.py:
    python build_icons.py
"""

import json
import pathlib
import re
import urllib.request

HERE = pathlib.Path(__file__).parent
BUILDS = HERE / "data" / "builds"
ICONS = HERE / "data" / "icons"

DDRAGON = "https://ddragon.leagueoflegends.com"
VERSIONS = f"{DDRAGON}/api/versions.json"
CDRAGON = ("https://raw.communitydragon.org/latest/plugins/"
           "rcp-be-lol-game-data/global/default")
AUGMENTS = f"{CDRAGON}/v1/cherry-augments.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}   # CommunityDragon respinge default-ul


def slug(name):
    """Nume afisat -> nume de fisier sigur ('Luden's Echo' -> 'luden-s-echo')."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch(url):
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        return r.read()


def fetch_json(url):
    return json.loads(fetch(url).decode("utf-8"))


def save_all(kind, sources):
    """sources: {nume afisat: url}. Sare peste ce exista deja pe disc."""
    folder = ICONS / kind
    folder.mkdir(parents=True, exist_ok=True)

    saved = skipped = failed = 0
    for name, url in sorted(sources.items()):
        out = folder / f"{slug(name)}.png"
        if out.exists():
            skipped += 1
            continue
        try:
            out.write_bytes(fetch(url))
            saved += 1
        except Exception as e:
            failed += 1
            print(f"  {kind}: {name} -- {type(e).__name__}")
    print(f"{kind:10s} {saved:4d} noi, {skipped:4d} aveam, {failed:3d} esuate "
          f"({len(sources)} in total)")


def item_sources(version):
    """Doar itemii care apar in build-urile aduse in cache, nu toti din joc."""
    wanted = set()
    for path in BUILDS.glob("*.json"):
        build = json.loads(path.read_text(encoding="utf-8"))
        for key in ("starting", "core", "fourth", "fifth", "sixth", "pool"):
            wanted.update(build.get(key) or [])

    catalog = fetch_json(f"{DDRAGON}/cdn/{version}/data/en_US/item.json")["data"]
    by_name = {}
    for item in catalog.values():
        name, img = item.get("name"), (item.get("image") or {}).get("full")
        if name and img:
            # Data Dragon are intrari duplicate per harta; imaginea e aceeasi
            by_name.setdefault(name, f"{DDRAGON}/cdn/{version}/img/item/{img}")
    return {n: u for n, u in by_name.items() if n in wanted}


def champion_sources(version):
    """Toti campionii: oricare poate aparea pe bench sau in echipa inamica."""
    catalog = fetch_json(f"{DDRAGON}/cdn/{version}/data/en_US/champion.json")["data"]
    return {c["name"]: f"{DDRAGON}/cdn/{version}/img/champion/{c['image']['full']}"
            for c in catalog.values() if c.get("name") and c.get("image")}


def summoner_sources(version):
    """Doar spell-urile care apar in build-urile aduse in cache."""
    wanted = set()
    for path in BUILDS.glob("*.json"):
        build = json.loads(path.read_text(encoding="utf-8"))
        wanted.update(build.get("summoners") or [])

    catalog = fetch_json(f"{DDRAGON}/cdn/{version}/data/en_US/summoner.json")["data"]
    by_name = {}
    for spell in catalog.values():
        name, img = spell.get("name"), (spell.get("image") or {}).get("full")
        if name and img:
            # id-uri "_Jade" sunt varianta de eveniment, aceeasi iconita
            by_name.setdefault(name, f"{DDRAGON}/cdn/{version}/img/spell/{img}")
    return {n: u for n, u in by_name.items() if n in wanted}


def augment_sources():
    augments = fetch_json(AUGMENTS)
    out = {}
    for row in augments:
        name, path = row.get("nameTRA"), row.get("augmentSmallIconPath")
        if not (name and path):
            continue
        # "/lol-game-data/assets/ASSETS/UX/..." -> ".../assets/ux/..."
        rel = path.replace("/lol-game-data/assets", "").lower()
        out.setdefault(name, CDRAGON + rel)
    return out


def main():
    version = fetch_json(VERSIONS)[0]
    print(f"patch {version}")
    save_all("items", item_sources(version))
    save_all("champions", champion_sources(version))
    save_all("summoners", summoner_sources(version))
    save_all("augments", augment_sources())


if __name__ == "__main__":
    main()
