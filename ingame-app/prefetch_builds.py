"""Aduce build-urile pentru mai multi campioni DINAINTE sa joci.

Scraping-ul foloseste un browser Chromium real (Playwright) ca sa treaca de
Cloudflare -- e greu (CPU/GPU), de-asta nu ruleaza niciodata in timpul unui
meci. Ruleaza asta o data, cand nu joci, si overlay-ul din app.py devine
strict citire din cache (usor, fara browser deloc).

    python prefetch_builds.py                  # cei mai jucati/comuni (vezi POPULAR)
    python prefetch_builds.py Ahri Jinx Sett    # campioni specifici
    python prefetch_builds.py --all             # toti cei 173 (dureaza cateva minute)
    python prefetch_builds.py --force Ahri       # rescrie chiar daca exista in cache
    python prefetch_builds.py --headed Ahri      # browser vizibil, nu ascuns

--headed: daca Cloudflare incepe sa raspunda cu "Just a moment..." (403) la
toti campionii deodata, inclusiv unii deja in cache la --force, inseamna ca
a devenit mai stricta cu Chromium headless -- un browser vizibil trece de
regula testul, cu pretul unei ferestre care pocneste pe ecran cat scraper-ul
ruleaza.
"""

import json
import pathlib
import sys
import time

from build_scraper import cache_path, scrape

DATA = pathlib.Path(__file__).with_name("data")

# un set rezonabil ca sa nu astepti scraping-ul tuturor celor 173 daca nu vrei
POPULAR = [
    "Sett", "Jinx", "Ahri", "Yasuo", "Lux", "Vayne", "Miss Fortune", "Caitlyn",
    "Zed", "Ezreal", "Thresh", "Leona", "Garen", "Darius", "Katarina",
]


def main():
    args = sys.argv[1:]
    force = "--force" in args
    headed = "--headed" in args
    args = [a for a in args if a not in ("--force", "--headed")]

    if "--all" in args:
        champs = list(json.loads((DATA / "champion-tags.json").read_text(encoding="utf-8")).keys())
    elif args:
        champs = args
    else:
        champs = POPULAR

    print(f"aduc build-uri pentru {len(champs)} campioni...")
    ok, skipped, failed = 0, 0, []

    for i, champ in enumerate(champs, 1):
        if not force and cache_path(champ).exists():
            skipped += 1
            print(f"  [{i}/{len(champs)}] {champ}: deja in cache")
            continue
        try:
            build = scrape(champ, headless=not headed)
        except Exception as e:
            build = None
            print(f"  [{i}/{len(champs)}] {champ}: eroare {type(e).__name__}: {e}")
        if build:
            ok += 1
            print(f"  [{i}/{len(champs)}] {champ}: OK ({len(build['pool'])} itemi)")
        else:
            failed.append(champ)
            print(f"  [{i}/{len(champs)}] {champ}: gol, nu am scris cache")
        time.sleep(0.5)  # curtoazie fata de u.gg, nu bombardam serverul

    print(f"\nGata: {ok} noi, {skipped} deja in cache, {len(failed)} esuati")
    if failed:
        print("esuati:", ", ".join(failed))


if __name__ == "__main__":
    main()
