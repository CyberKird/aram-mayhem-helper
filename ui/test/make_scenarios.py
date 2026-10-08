"""Scenarii pentru motorul de test, construite de logica reala a motorului
(app.Engine) pe monitoare false. Scrie <nume>.json langa el.

    python make_scenarios.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import app          # noqa: E402
import hud_settings  # noqa: E402

lcu = app._load_page("lcu_page", "lcu-app")
ingame = app._load_page("ingame_page", "ingame-app")
OUT = pathlib.Path(__file__).parent
# monitoarele de pe PC-ul de test: 4K 150% principal, 1080p 100% in dreapta
MON_4K = (0, 0, 3840, 2160)
MON_1080 = (3840, 209, 5760, 1289)


class Lcu:
    phase, error, team = "idle", None, []
    assigned = dict(name="Jinx", tier="A", is_best=False, wr=51.2, wr_delta=0.8, pr=6.1, tier_change=1)
    bench = [dict(name="Sett", tier="S", is_best=True, wr=53.4, wr_delta=-0.4, pr=4.2,
                  balance=["DMG DAT -5%", "DMG PRIMIT +5%"]),
             dict(name="Lux", tier="B", is_best=False, wr=49.9, pr=8.8, tier_change=-1)]


class Mon:
    phase, status, ocr_status = "in_game", "", ""
    roster = {"local_champion": "Ahri", "enemies": ["Jinx", "Sett", "Lux", "Garen", "Ezreal"], "own_items": []}
    augments, stat_anvil, taken_augments = [], [], []
    global_augments = None
    resolved_build = {
        "starting": [], "full": False, "range": "ranged", "unavailable": [],
        "sell": {"sell": "Sorcerer's Shoes", "buy": "Banshee's Veil", "reason": "inamicii au mult control"},
        "core": [{"item": "Luden's Echo", "owned": True, "next": False},
                 {"item": "Shadowflame", "owned": False, "next": True}],
        "picks": [{"item": "Morellonomicon", "reason": "inamicii se vindeca", "owned": False, "next": False},
                  {"item": "Zhonya's Hourglass", "reason": None, "owned": False, "next": False},
                  {"item": "Rabadon's Deathcap", "reason": None, "owned": False, "next": False}]}


Mon.global_augments = ingame.load_json("augments-global.json")
eng = app.Engine(lcu, Lcu(), ingame, Mon())
eng.reader.offers, eng.reader.pins = [], {}


def game_geo(mon, front=True):
    l, t, r, b = mon
    x0, y0, x1, y1 = hud_settings.area(r - l, b - t, {"MinimapScale": 2.31, "GlobalScale": 0.0})
    return {"box": list(mon), "dock": [int(l + x0), int(t + y0), int(l + x1), int(t + y1)], "front": front}


def write(name, view, data, geo=None, update=None):
    state = {"view": view, "data": data, "update": update or {"tag": None, "busy": False, "why": None},
             "geo": dict({"game": None, "client": None, "bars": None, "pins": None}, **(geo or {}))}
    (OUT / f"{name}.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(name)


write("idle", "idle", {"client_up": True, "error": None})
write("champ", "champ_select", eng.champ_select(),
      {"client": {"box": [4000, 300, 5280, 1020]}})

game = eng.in_game()
write("game1080", "in_game", game, {"game": game_geo(MON_1080)})
write("game4k", "in_game", game, {"game": game_geo(MON_4K)})

names = [n for n in eng.top_augments("Ahri").get("gold", [])][:3]
Mon.augments = [dict(name=a["name"], tier=a["tier"], is_best=i == 0, slot=i) for i, a in enumerate(names)]
Mon.taken_augments = []
offer = eng.in_game()
import ocr_augments  # noqa: E402
for label, mon in (("offer1080", MON_1080), ("offer4k", MON_4K)):
    g = game_geo(mon)
    bars = {"kind": "augment", "region": list(ocr_augments.augment_region(mon)), "items": offer["offer"]}
    write(label, "in_game", offer, {"game": g, "bars": bars})
