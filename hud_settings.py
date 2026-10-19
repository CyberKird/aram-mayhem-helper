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
from PIL import Image, ImageChops, ImageOps

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
# inaltime), unde nu ne acopera propriul panou. Banda e subtire (pana la 0.30) ca sa fie
# toata in interiorul hartii, iar marginea trebuie sa fie o linie continua pe toata banda:
# bare de viata, efecte, chenarele cartilor de augment au muchii tari, dar nu drepte si lungi.

BAND_TOP, BAND_BOTTOM = 0.30, 0.255     # din inaltimea jocului, masurat de jos
EDGE_MIN, COHERENCE = 20, 0.9           # diferenta de luminozitate, partea din banda
_mm = {"key": None, "px": None, "next": 0.0, "last": None, "n": 0, "left": None}


def estimate_minimap(H, s=None):
    """Latimea hartii dupa setari (estimare), sau valoarea implicita."""
    s = read() if s is None else s
    return (MINIMAP_PER_SCALE * s["MinimapScale"] if "MinimapScale" in s else 0.259) * H


def detect_minimap(img, H, est=None):
    """Latimea hartii in pixeli din banda `img` (de la W-0.8H pana la marginea dreapta), sau None.

    Cautam doar aproape de estimare (0.75-1.35x): harta nu e niciodata de doua ori mai mare.
    """
    w = img.width
    est = est or 0.334 * H
    diff = ImageChops.difference(img, ImageChops.offset(img, 2, 0)).convert("L")
    mask = diff.point(lambda v: 255 if v > EDGE_MIN else 0)
    cols = list(mask.resize((w, 1), Image.BOX).getdata())
    lo, hi = max(2, int(w - 1.35 * est)), min(w - 2, int(w - 0.75 * est))
    # cea mai continua linie (la egalitate, cea mai din stanga = marginea exterioara a ramei)
    best = max(range(lo, hi), key=lambda x: (cols[x] // 13, -x), default=None)
    if best is None or cols[best] < 255 * COHERENCE:
        return None                     # nicio margine clara: nu ghicim
    return w - best + 1


def measured_minimap(box, grab, front, est=None, hint=None):
    """(latime px, harta_in_stanga) masurate pe ecran, pastrate pana se schimba rezolutia.

    Cautam rama hartii in banda din dreapta si in cea din stanga (oglindita): jucatorul poate
    avea harta pe oricare parte, iar setarile jocului nu se gasesc mereu. `hint` (din setari)
    decide doar daca ambele benzi par sa aiba o rama. Doua masuratori la fel la rand (+-3 px)
    ca s-o credem; o valoare noua, diferita de cea pastrata cu peste 0.03 din inaltime, are
    nevoie de patru la rand. Reverificare pe minut.
    """
    l, t, r, b = box
    W, H = r - l, b - t
    key = (W, H)
    if _mm["key"] != key:
        _mm.update(key=key, px=None, next=0.0, last=None, n=0, left=None)
    now = time.monotonic()
    if not front or now < _mm["next"]:
        return _mm["px"], _mm["left"]
    _mm["next"] = now + (60 if _mm["px"] else 1.0)
    try:
        # banda urca doar cat e harta (estimarea poate fi mica: nu iesim din rama), dar cel putin 0.015 H
        top = min(BAND_TOP, max(BAND_BOTTOM + 0.015, 0.97 * est / H)) if est else BAND_TOP
        y0, y1 = int(b - top * H), int(b - BAND_BOTTOM * H)
        found = {}
        for left, band in ((False, (int(r - 0.8 * H), y0, r, y1)), (True, (l, y0, int(l + 0.8 * H), y1))):
            img = grab(band)
            k = img.info.get("reduce", 1)
            px = detect_minimap(ImageOps.mirror(img) if left else img, H / k, est and est / k)
            if px:
                found[left] = px * k
    except Exception:
        return _mm["px"], _mm["left"]
    if not found:
        _mm["last"], _mm["n"] = None, 0
        return _mm["px"], _mm["left"]
    side = next((c for c in (hint, _mm["left"], False, True) if c in found))   # indiciu, apoi ce stiam, apoi dreapta
    px = found[side]
    if _mm["left"] is not None and side != _mm["left"]:
        _mm.update(px=None, last=None, n=0)          # alta parte: masuratorile vechi nu mai conteaza
    same = _mm["last"] and abs(_mm["last"] - px) <= 3
    _mm["n"] = _mm["n"] + 1 if same else 1
    _mm["last"] = px
    far = _mm["px"] and abs(_mm["px"] - px) > 0.03 * H
    if _mm["n"] >= (4 if far else 2):
        _mm.update(px=px, left=side)
    return _mm["px"], _mm["left"]


def area(box_w, box_h, settings=None, minimap_px=None, flipped=None):
    """(x0, y0, x1, y1) al spatiului dintre HUD si minimap, relativ la joc.

    Lipit de HUD, de harta (pe oricare parte ar fi) si de jos; in sus cel mult
    PANEL_TALL x inaltimea HUD-ului. HUD-ul creste cu GlobalScale in aceeasi proportie pe latime si pe inaltime (masurat pe o
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
    flipped = s.get("FlipMiniMap") == 1 if flipped is None else flipped
    if flipped:                              # harta in stanga: golul dintre harta si HUD
        x0, x1 = minimap + edge, box_w / 2 - hud_half - edge
        x1 = max(x1, x0 + 0.18 * H)
    else:                                    # harta in dreapta: golul dintre HUD si harta
        x0, x1 = box_w / 2 + hud_half + edge, box_w - minimap - edge
        x0 = min(x0, x1 - 0.18 * H)          # oricat de mare e HUD-ul, panoul ramane lizibil
    return x0, box_h - min(hud_tall * PANEL_TALL, minimap), x1, box_h


def gap(box_w, box_h, settings=None):
    """(x_dreapta, latime) a golului dintre HUD si minimap, relativ la stanga jocului."""
    x0, _, x1, _ = area(box_w, box_h, settings)
    return x1, x1 - x0
