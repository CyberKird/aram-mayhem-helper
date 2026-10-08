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
from PIL import Image, ImageChops

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


HUD_TALL_BASE = 0.092  # inaltimea HUD-ului cu itemele (chenar inclus), la GlobalScale 0
PANEL_TALL = 2.6       # destul cat sa incapa itemul urmator si sfatul de vanzare, tot sub inaltimea hartii
EDGE = 0.002           # cat lasam intre panou si chenarele vecine, din inaltime


# --- harta masurata de pe ecran --------------------------------------------------------
# Formula din setari e doar o estimare (alti jucatori, alta rezolutie, alte valori). Marginea
# stanga a minimap-ului e o linie verticala dreapta, lunga cat harta, deci iese clar din
# imagine: o cautam pe banda de deasupra panoului (panoul nu urca niciodata peste 0.255 din
# inaltime), unde nu ne acopera propriul panou.

BAND_TOP, BAND_BOTTOM = 0.40, 0.255     # din inaltimea jocului, masurat de jos
_mm = {"key": None, "px": None, "next": 0.0, "last": None}


def detect_minimap(img, H):
    """Latimea hartii in pixeli din banda `img` (de la W-0.8H pana la marginea dreapta), sau None."""
    w = img.width
    diff = ImageChops.difference(img, ImageChops.offset(img, 2, 0)).convert("L")
    cols = list(diff.resize((w, 1), Image.BOX).getdata())
    lo, hi = int(w - 0.6 * H), int(w - 0.2 * H)
    window = sorted(cols[lo:hi])
    peak = max(range(lo, hi), key=cols.__getitem__)
    if cols[peak] < 15 or cols[peak] < 5 * max(window[len(window) // 2], 1):
        return None                     # nicio margine clara: nu ghicim
    return w - peak + 1


def measured_minimap(box, grab, front):
    """Latimea hartii masurata pe ecran (px), pastrata pana se schimba rezolutia.

    Doua masuratori la fel la rand (+-3 px) ca s-o credem; apoi o reverificam o data pe minut.
    """
    l, t, r, b = box
    W, H = r - l, b - t
    key = (W, H)
    if _mm["key"] != key:
        _mm.update(key=key, px=None, next=0.0, last=None)
    now = time.monotonic()
    if not front or now < _mm["next"]:
        return _mm["px"]
    _mm["next"] = now + (60 if _mm["px"] else 1.5)
    try:
        img = grab((int(r - 0.8 * H), int(b - BAND_TOP * H), r, int(b - BAND_BOTTOM * H)))
        k = img.info.get("reduce", 1)
        px = detect_minimap(img, H / k)
    except Exception:
        return _mm["px"]
    px = px and px * k
    if px and 0.2 * H <= px <= 0.6 * H:
        if _mm["last"] and abs(_mm["last"] - px) <= 3:
            _mm["px"] = px
        _mm["last"] = px
    return _mm["px"]


def area(box_w, box_h, settings=None, minimap_px=None):
    """(x0, y0, x1, y1) al spatiului dintre HUD si minimap, relativ la joc.

    Lipit de marginea din dreapta a HUD-ului, de marginea din stanga a hartii
    si de jos; in sus cel mult PANEL_TALL x inaltimea HUD-ului. HUD-ul creste
    cu GlobalScale in aceeasi proportie pe latime si pe inaltime (masurat pe o
    captura reala: 0.227 jumatate de latime, 0.092 inaltime, la GlobalScale 0).

    Fara setari folosim valorile de la capturile de referinta.
    """
    s = read() if settings is None else settings
    H = box_h
    if "MinimapScale" in s:
        minimap = minimap_px or MINIMAP_PER_SCALE * s["MinimapScale"] * H
        hud_half = (HUD_HALF_BASE + HUD_HALF_PER_SCALE * s.get("GlobalScale", 0.0)) * H
    else:
        minimap, hud_half = minimap_px or 0.259 * H, 0.328 * H
    hud_tall = HUD_TALL_BASE * H * hud_half / (HUD_HALF_BASE * H)
    edge = EDGE * H
    x0 = box_w / 2 + hud_half + edge
    # harta in stanga: golul din dreapta HUD-ului merge pana la marginea ecranului
    x1 = box_w if s.get("FlipMiniMap") == 1 else box_w - minimap - edge
    x0 = min(x0, x1 - 0.18 * H)              # oricat de mare e HUD-ul, panoul ramane lizibil
    return x0, box_h - min(hud_tall * PANEL_TALL, minimap), x1, box_h


def gap(box_w, box_h, settings=None):
    """(x_dreapta, latime) a golului dintre HUD si minimap, relativ la stanga jocului."""
    x0, _, x1, _ = area(box_w, box_h, settings)
    return x1, x1 - x0
