"""Statistici per campion: win rate, pick rate si cum s-au schimbat.

Doua surse, ambele pe patch curent si patch anterior:
  - tier_data.json  (u.gg)     -> schimbarea de tier
  - stats_data.json (ARAMKit)  -> win rate / pick rate reale si diferenta lor
Lipsa unui fisier sau a unui campion nu e eroare: intoarcem ce avem.
"""

import json
import pathlib

import tier_list

STATS_FILE = pathlib.Path(__file__).with_name("stats_data.json")


def _load(path=STATS_FILE):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


STATS = _load(tier_list.newest(STATS_FILE, "revision"))
_now = STATS.get("champions", {})
_before = (STATS.get("previous") or {}).get("champions", {})


# modificatorii de balans pe care Riot ii aplica fiecarui campion in Mayhem
_LABELS = {"damageDealt": "DMG DAT", "damageTaken": "DMG PRIMIT",
           "abilityHaste": "ABILITY HASTE", "tenacity": "TENACITY",
           "healing": "VINDECARE", "shielding": "SCUTURI",
           "attackSpeed": "ATK SPEED", "energyRegen": "REGEN ENERGIE"}


def _fmt(mod):
    v = mod["value"]
    text = f"{v * 100:+g}%" if mod.get("unit") == "percent" else f"{v:+g}"
    return f"{_LABELS.get(mod['key'], mod['key'].upper())} {text}"


def balance(name):
    """(modificatori, schimbari de abilitati) ale campionului in Mayhem.

    modificatori: ["DMG DAT -5%", ...]; schimbari: [("Q", "Boomerang Blade",
    ["Cooldown changed to ..."])]. Liste goale daca nu are nimic.
    """
    b = (_now.get(name) or {}).get("balance") or {}
    mods = [_fmt(m) for m in b.get("modifiers") or []]
    changes = [(a.get("key", ""), a.get("ability", ""), a.get("lines") or [])
               for a in b.get("abilityChanges") or []]
    return mods, changes


def info(name):
    """{tier_change, wr, pr, wr_delta} pentru un campion; chei lipsa = necunoscut.

    tier_change: trepte urcate (+) / coborate (-) intre patch-urile u.gg.
    wr_delta: puncte procentuale de win rate fata de patch-ul anterior ARAMKit.
    """
    out = {}
    change = tier_list.change(name, tier_list.TIER_DATA, tier_list.PREVIOUS_TIERS)
    if change is not None:
        out["tier_change"] = change
    mods, changes = balance(name)
    if mods or changes:
        out["balance"] = mods
        out["ability_changes"] = changes
    cur = _now.get(name)
    if cur:
        out["wr"], out["pr"] = cur["wr"], cur["pr"]
        old = _before.get(name)
        if old:
            out["wr_delta"] = round(cur["wr"] - old["wr"], 1)
    return out


def versions():
    """(patch u.gg, patch u.gg anterior, versiune ARAMKit, anterioara)."""
    return (tier_list.PATCH, tier_list.PREVIOUS_PATCH, STATS.get("version"),
            (STATS.get("previous") or {}).get("version"))
