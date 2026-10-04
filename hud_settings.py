"""Setarile de HUD ale jocului: cat de mare e minimap-ul si cat de mare e HUD-ul.

Jucatorii isi schimba marimea hartii, deci golul dintre HUD-ul de jos si minimap
nu e fix. Jocul isi tine setarile in Config/PersistedSettings.json (langa
folderul Game), le citim de acolo si calculam golul. Formulele sunt calibrate pe
doua capturi reale (MinimapScale 2.31 -> harta de 0.334 din inaltimea jocului;
GlobalScale 0 -> HUD de 0.228 din inaltime fata de centru), deci sunt estimari,
nu cifre oficiale: de aceea panoul tot poate fi mutat cu mouse-ul si isi tine minte
diferenta.
"""

import json
import pathlib
import time

import psutil

MINIMAP_PER_SCALE = 0.1446     # latimea hartii / (inaltimea jocului * MinimapScale)
HUD_HALF_BASE = 0.228          # jumatatea HUD-ului (pana la aurul din dreapta), la GlobalScale 0
HUD_HALF_PER_SCALE = 0.20      # estimare prudenta: HUD-ul creste cu GlobalScale

_FALLBACKS = (r"C:\Riot Games\League of Legends", r"D:\Riot Games\League of Legends",
              r"E:\Riot Games\League of Legends")

_cache = {"path": None, "mtime": None, "values": {}, "retry_at": 0.0}


def _find_config():
    """Calea PersistedSettings.json: din procesul jocului/clientului, apoi din locurile uzuale."""
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            if proc.info["name"] in ("League of Legends.exe", "LeagueClient.exe") and proc.info["exe"]:
                exe = pathlib.Path(proc.info["exe"])
                for root in (exe.parent.parent, exe.parent):
                    cfg = root / "Config" / "PersistedSettings.json"
                    if cfg.exists():
                        return cfg
    except Exception:
        pass
    for root in _FALLBACKS:
        cfg = pathlib.Path(root) / "Config" / "PersistedSettings.json"
        if cfg.exists():
            return cfg
    return None


def _walk(obj, out):
    if isinstance(obj, dict):
        if "name" in obj and "value" in obj:
            out[obj["name"]] = obj["value"]
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)


def read():
    """{MinimapScale, GlobalScale, FlipMiniMap} ca float-uri; gol daca nu gasim fisierul.

    Recitit doar cand se schimba fisierul (mtime), deci apelul e ieftin.
    """
    path = _cache["path"] if _cache["path"] and _cache["path"].exists() else None
    if path is None:
        # cautarea scaneaza procesele: daca n-am gasit fisierul, nu reincercam la
        # fiecare apel (gap() se cheama de doua ori pe secunda)
        if time.monotonic() < _cache["retry_at"]:
            return {}
        path = _find_config()
        if path is None:
            _cache["retry_at"] = time.monotonic() + 30
            return {}
    try:
        mtime = path.stat().st_mtime
        if path == _cache["path"] and mtime == _cache["mtime"]:
            return _cache["values"]
        found = {}
        _walk(json.loads(path.read_text(encoding="utf-8")), found)
        values = {}
        for key in ("MinimapScale", "GlobalScale", "FlipMiniMap"):
            try:
                values[key] = float(found[key])
            except (KeyError, ValueError):
                pass
        _cache.update(path=path, mtime=mtime, values=values)
        return values
    except (OSError, ValueError):
        return {}


def gap(box_w, box_h, settings=None):
    """(x_dreapta, latime) a golului dintre HUD si minimap, relativ la stanga jocului.

    Fara setari folosim valorile de la capturile de referinta (minimap 0.259*H,
    HUD 0.328*H de la centru), care se potrivesc cu un set tipic de setari.
    """
    s = read() if settings is None else settings
    H = box_h
    if "MinimapScale" in s:
        minimap = MINIMAP_PER_SCALE * s["MinimapScale"] * H
        hud_half = (HUD_HALF_BASE + HUD_HALF_PER_SCALE * s.get("GlobalScale", 0.0)) * H
    else:
        minimap, hud_half = 0.259 * H, 0.328 * H
    margin = 0.012 * H
    if s.get("FlipMiniMap") == 1:           # harta in stanga: golul e pana la marginea din dreapta
        right = box_w - margin
    else:
        right = box_w - minimap - margin
    left = box_w / 2 + hud_half + margin
    return right, max(0.18 * H, right - left)
