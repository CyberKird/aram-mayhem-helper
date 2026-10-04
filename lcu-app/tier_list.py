"""Tier list ARAM Mayhem (u.gg), citit din tier_data.json.

Datele nu mai sunt scrise de mana aici: `update_tier_list.py` le aduce de pe
https://u.gg/lol/aram-mayhem-tier-list si pastreaza patch-ul anterior in
"previous", ca sa vedem cum s-a schimbat fiecare campion. In plus, aplicatia
descarca la pornire cel mai nou tier_data.json din repo (vezi data_sync.py),
deci tier-urile se actualizeaza fara un exe nou.
"""

import json
import os
import pathlib

BUNDLED = pathlib.Path(__file__).with_name("tier_data.json")


def _vkey(version):
    return tuple(int(x) if x.isdigit() else 0 for x in str(version or "").split("."))


def newest(bundled, key):
    """Fisierul cu versiunea mai mare dintre cel din pachet si cel adus de
    data_sync in ARAM_DATA_DIR. La egalitate, cel din pachet."""
    folder = os.environ.get("ARAM_DATA_DIR")
    synced = pathlib.Path(folder) / bundled.name if folder else None
    if synced and synced.exists():
        try:
            mine = json.loads(bundled.read_text(encoding="utf-8")).get(key)
            theirs = json.loads(synced.read_text(encoding="utf-8")).get(key)
            if _vkey(theirs) > _vkey(mine):
                return synced
        except (OSError, ValueError):
            pass
    return bundled


# fisierul in care scrie update_tier_list.py (mereu cel din pachet)
DATA_FILE = BUNDLED

# nume din Data Dragon care nu se potrivesc pe cheile din u.gg.
# Reconcilierea a iesit curata (173/173 campioni acoperiti), deci e gol.
# Daca selfcheck-ul incepe sa raporteze campioni fara tier, aici se mapeaza.
NAME_OVERRIDES = {}

TIER_ORDER = ["S+", "S", "A", "B", "C", "D"]


def flatten(tiers):
    """{tier: [nume]} -> {nume: tier}"""
    return {name: tier for tier, names in tiers.items() for name in names}


def load(path=DATA_FILE):
    """(patch, {nume: tier}, patch_anterior, {nume: tier anterior})."""
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    prev = raw.get("previous") or {}
    return (raw["patch"], flatten(raw["tiers"]),
            prev.get("patch"), flatten(prev.get("tiers") or {}))


def change(name, current, previous):
    """Cate trepte a urcat (+) sau coborat (-) campionul fata de patch-ul
    anterior. None daca nu avem date pentru unul din patch-uri."""
    now, before = current.get(name), previous.get(name)
    if now not in TIER_ORDER or before not in TIER_ORDER:
        return None
    return TIER_ORDER.index(before) - TIER_ORDER.index(now)


PATCH, TIER_DATA, PREVIOUS_PATCH, PREVIOUS_TIERS = load(newest(BUNDLED, "patch"))
