"""ARAM Mayhem Helper: motorul, fara interfata.

Ruleaza monitoarele (champ select prin LCU, roster + build + augmente in joc
prin Live Client Data + OCR) si scrie starea pe stdout, JSON pe o linie, de
fiecare data cand se schimba. Interfata e aplicatia Electron din ui/: ne
porneste ca proces copil si ne trimite comenzi pe stdin, tot JSON pe o linie.

Nu reimplementeaza logica: importa direct modulele din lcu-app/ si ingame-app/
(fiecare ramane utilizabil separat, pentru debug).

Coordonatele din stare sunt pixeli fizici de ecran (procesul e DPI-aware);
interfata le transforma in unitatile ei, per monitor.

    python app.py              # motorul (il porneste ui/)
    python app.py --selfcheck  # logica pura offline, fara joc
"""

import ctypes
import functools
import importlib.util
import json
import os
import pathlib
import sys
import threading
import time

import bug_report
import champ_ocr
import data_sync
import hud_settings

# versiunea o tine ui/package.json (de acolo vin si update-urile); aici doar o raportam
VERSION = os.environ.get("ARAM_VERSION") or "dev"

# In exe (PyInstaller) codul si datele stau in _MEIPASS. Ce trebuie sa
# supravietuiasca inchiderii (jurnal, date sincronizate) sta in ARAM_HOME,
# folderul de date al aplicatiei (%APPDATA%), dat de interfata.
if getattr(sys, "frozen", False):
    ROOT = pathlib.Path(sys._MEIPASS)
    HOME = pathlib.Path(os.environ.get("ARAM_HOME") or pathlib.Path(sys.executable).parent)
else:
    ROOT = pathlib.Path(__file__).parent
    HOME = pathlib.Path(os.environ.get("ARAM_HOME") or ROOT)

ICONS = ROOT / "ingame-app" / "data" / "icons"
TIERS = ("S+", "S", "A", "B", "C", "D")

# nume lung de card Stat Anvil -> eticheta scurta care incape in insigna
ANVIL_LABEL = {
    "haste": "HASTE", "ap": "AP", "ad": "AD", "as": "AS", "crit": "CRIT",
    "hp": "HP", "armor": "ARMOR", "mr": "MR", "pen_ad": "PEN AD",
    "pen_ap": "PEN AP", "hybrid_dmg": "AD+AP", "hybrid_utility": "AS+AH",
    "hybrid_defense": "AR+MR", "mobility": "MS", "sustain": "OMNIVAMP",
    "heal_power": "HEAL", "cc_resist": "TENACITY",
}

TICK = 0.15     # secunde intre doua citiri de stare: o oferta noua trebuie sa apara pe loc


def enable_dpi_awareness():
    """Pixeli reali peste tot (mss, ferestrele jocului). O data, inainte de orice captura."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def be_lightweight():
    """Prioritate sub normal: cand jocul are nevoie de procesor, noi cedam."""
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00004000)
    except Exception:
        pass


def _load_page(name, folder):
    """Incarca <folder>/app.py sub un nume propriu (ambele se numesc 'app.py')."""
    folder_path = ROOT / folder
    sys.path.insert(0, str(folder_path))
    spec = importlib.util.spec_from_file_location(name, folder_path / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=4096)
def ic(kind, name):
    """Calea iconitei relativ la ICONS ("items/x.png"), sau None daca lipseste."""
    from build_icons import slug   # aceeasi regula de nume ca la descarcare
    path = ICONS / kind / f"{slug(name)}.png"
    return f"{kind}/{path.name}" if path.exists() else None


_out_lock = threading.Lock()


def emit(msg):
    # ASCII pur: ocolim orice problema de codare pe pipe-ul din Windows
    line = json.dumps(msg, separators=(",", ":"))
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


SYNC_EVERY = 30 * 60      # secunde intre doua sincronizari de date cat timp aplicatia ruleaza


def maintenance():
    """Tier-uri si statistici noi din repo, in fundal: la pornire si apoi periodic.
    Fara internet trebuie sa mearga: un esec inseamna doar ca mergem mai departe."""
    while True:
        try:
            data_sync.sync(HOME / "data-sync")
        except Exception:
            pass
        time.sleep(SYNC_EVERY)


class Engine:
    def __init__(self, lcu, lcu_mon, ingame, ingame_mon):
        self.lcu, self.lcu_mon, self.ingame, self.mon = lcu, lcu_mon, ingame, ingame_mon
        self.item_desc = ingame.load_json("item-desc.json")
        self.augment_desc = ingame.load_json("augment-desc.json")
        self.augment_items = ingame.load_json("augment-items.json")
        self._top = (None, {})
        self.reader = champ_ocr.ChampSelectReader(
            lcu.load_champion_data().values(),
            lambda: lcu_mon.phase == "in_mayhem_select" and ingame_mon.phase != "in_game",
            self.champ_known)

    # --- ce arata panoul --------------------------------------------------

    def view(self):
        if self.lcu_mon.phase == "in_mayhem_select":
            return "champ_select"
        if self.mon.phase == "in_game":
            return "in_game"
        return "idle"

    def champ_known(self):
        # tu, bench-ul si coechipierii: toti apar pe ecran, dar nu sunt cartile tale
        lm = self.lcu_mon
        return [e["name"] for e in ([lm.assigned] if lm.assigned else [])
                + list(lm.bench)] + list(lm.team)

    def champ(self, entry, origin):
        keys = ("name", "tier", "wr", "wr_delta", "pr", "tier_change", "balance")
        out = {k: entry[k] for k in keys if k in entry}
        return dict(out, origin=origin, icon=ic("champions", entry["name"]), is_best=False)

    def champ_pool(self):
        """Toti campionii pe care ii poti avea, ordonati dupa tier: al tau, apoi
        cartile tale (cat sunt pe ecran) sau bench-ul. Un singur BEST: primul."""
        import champ_stats
        import mayhem_logic as logic
        import tier_list
        lm = self.lcu_mon
        known = set(self.champ_known())
        offers = [dict(name=n, tier=tier_list.TIER_DATA.get(n, logic.UNRANKED), **champ_stats.info(n))
                  for n in self.reader.offers if n not in known]
        pool = ([self.champ(lm.assigned, "AL TAU")] if lm.assigned else []) + (
            [self.champ(e, "CARTE") for e in offers] or [self.champ(e, "BENCH") for e in lm.bench])
        pool.sort(key=lambda e: logic.tier_rank(e["tier"]))      # stabil: la egalitate ramane al tau
        if pool:
            pool[0]["is_best"] = True
        return pool

    def champ_select(self):
        pool = self.champ_pool()
        build = self.ingame.load_cached(pool[0]["name"]) if pool else None
        summoners = (build or {}).get("summoners") or []
        return {"pool": pool, "summoners": [{"name": n, "icon": ic("summoners", n)} for n in summoners]}

    def item(self, e):
        name = e["item"] if isinstance(e, dict) else e
        e = e if isinstance(e, dict) else {}
        return {"item": name, "icon": ic("items", name), "owned": bool(e.get("owned")),
                "next": bool(e.get("next")), "reason": e.get("reason"),
                "desc": self.item_desc.get(name)}

    def aug(self, a):
        return {"name": a["name"], "tier": a["tier"], "is_best": bool(a.get("is_best")),
                "slot": a.get("slot"), "icon": ic("augments", a["name"]),
                "needs": self.augment_items.get(a["name"]),
                # fara tier aratam ce face, ca sa poti decide tu; nu inventam un rank
                "desc": None if a["tier"] in TIERS else self.augment_desc.get(a["name"])}

    def anvil(self):
        return [{"name": s["name"].replace(" Shard", ""),
                 "tier": ANVIL_LABEL.get(s["category"], s["category"].upper()),
                 "is_best": bool(s["is_best"]), "slot": s.get("slot"), "why": s.get("why"),
                 "champion": s.get("champion")} for s in self.mon.stat_anvil]

    def top_augments(self, champ):
        import augment_tier
        if self._top[0] != champ:
            self._top = (champ, augment_tier.top_by_rarity(self.mon.global_augments, champ))
        return self._top[1]

    def in_game(self):
        m = self.mon
        roster = m.roster or {}
        champ = roster.get("local_champion")
        out = {"champ": champ, "enemies": len(roster.get("enemies") or []),
               "loading": not m.roster, "status": m.status or "",
               "ocr": (m.ocr_status or "").split(" (")[0],
               "taken": [{"name": n, "icon": ic("augments", n)} for n in m.taken_augments],
               "offer": [self.aug(a) for a in m.augments],
               "anvil": self.anvil(),
               "top": self.top_augments(champ),
               "build": None}
        rb = m.resolved_build
        if rb:
            full = rb.get("full")
            items = rb["core"] + rb["picks"]
            left = [] if full else [e for e in items if not e["owned"]]
            sell = rb.get("sell")
            out["build"] = {
                "starting": [self.item(e) for e in rb.get("starting") or []],
                "sell": sell and dict(sell, sell_icon=ic("items", sell["sell"]),
                                      buy_icon=ic("items", sell["buy"])),
                # cu 6 sloturi pline ce urmeaza vine doar prin sfatul de vanzare
                "next": [self.item(e) for e in left[:6]],
                "complete": [] if left or not rb["picks"] else
                [self.item(e) for e in items if e["owned"] or not full],
                "unavailable": rb.get("unavailable") or [], "range": rb.get("range")}
        return out

    # --- unde sunt jocul, clientul si cardurile ----------------------------

    def geometry(self, view):
        import ocr_augments as o
        geo = {"game": None, "client": None, "bars": None, "pins": None}
        hwnd = o.find_game_window()
        box = o.game_rect(hwnd) if hwnd else None
        if box and box[3] - box[1] >= 300:
            l, t, r, b = box
            x0, y0, x1, y1 = hud_settings.area(r - l, b - t)
            front = o.in_front(hwnd)
            geo["game"] = {"box": list(box), "dock": [int(l + x0), int(t + y0), int(l + x1), int(t + y1)],
                           "front": front}
            if front and (self.mon.augments or self.mon.stat_anvil):
                # Stat Anvil si oferta de augment nu apar niciodata deodata
                kind = "augment" if self.mon.augments else "anvil"
                items = [self.aug(a) for a in self.mon.augments] if self.mon.augments else self.anvil()
                geo["bars"] = {"kind": kind, "region": list(o.augment_region(box)), "items": items[:3]}
        if view == "champ_select":
            client = o.find_client_window()
            if client:
                geo["client"] = {"box": list(o.game_rect(client))}
                pins = self.reader.pins
                if pins and o.in_front(client):
                    geo["pins"] = [dict(e, cx=pins[e["name"]][0], y=pins[e["name"]][1])
                                   for e in self.champ_pool() if e["name"] in pins]
        return geo

    def state(self):
        view = self.view()
        lm = self.lcu_mon
        data = {"idle": lambda: {"client_up": lm.phase != "waiting_for_client", "error": lm.error},
                "champ_select": self.champ_select, "in_game": self.in_game}[view]()
        return {"t": "state", "view": view, "data": data, "geo": self.geometry(view)}

    # --- comenzile interfetei ---------------------------------------------

    def command(self, msg):
        cmd, m = msg.get("cmd"), self.mon
        if cmd == "took" and msg.get("name") not in m.taken_augments:
            # singurul mod sigur de a sti ce ai ales: Riot nu expune alegerea
            m.taken_augments.append(msg["name"])
            m._recompute_build()
        elif cmd == "drop" and msg.get("name") in m.taken_augments:
            m.taken_augments.remove(msg["name"])
            m._recompute_build()
        elif cmd == "diag":
            emit({"t": "reply", "id": msg.get("id"),
                  "text": bug_report.build_diagnostics(VERSION, HOME, self.lcu_mon, m)})
        elif cmd == "report":
            def work():
                problem = bug_report.validate(msg.get("desc", ""), msg.get("email", ""))
                ok, text = (False, problem) if problem else bug_report.send(
                    msg["desc"], msg["email"], msg.get("diag", ""), VERSION)
                emit({"t": "reply", "id": msg.get("id"), "ok": ok, "text": text})
            threading.Thread(target=work, daemon=True).start()
        elif cmd == "mailto":
            bug_report.mailto(msg.get("desc", ""), msg.get("diag", ""), VERSION)

    def loop(self, stop):
        last = None
        while not stop.is_set():
            try:
                line = json.dumps(self.state(), separators=(",", ":"), sort_keys=True)
                if line != last:
                    with _out_lock:
                        sys.stdout.write(line + "\n")
                        sys.stdout.flush()
                    last = line
            except (OSError, ValueError):
                stop.set()          # interfata a disparut: n-are rost sa mai rulam
            except Exception as e:
                emit({"t": "error", "text": f"{type(e).__name__}: {e}"})
            stop.wait(TICK)


def selfcheck():
    lcu = _load_page("lcu_page", "lcu-app")
    ingame = _load_page("ingame_page", "ingame-app")
    lcu.selfcheck()
    ingame.selfcheck()

    # iconitele: ce afiseaza UI-ul trebuie sa aiba fisier pe disc, altfel
    # cade tacut pe placeholder. Verificam toate cele trei feluri.
    from build_icons import slug

    def have(kind, name):
        return (ICONS / kind / f"{slug(name)}.png").exists()

    builds = [json.loads(p.read_text(encoding="utf-8"))
              for p in (ROOT / "ingame-app" / "data" / "builds").glob("*.json")]
    missing = set()
    for build in builds:
        for key in ("starting", "core", "fourth", "fifth", "sixth"):
            for name in build.get(key) or []:
                if not have("items", name):
                    missing.add(f"item: {name}")
    champions = json.loads((ROOT / "ingame-app" / "data" / "champion-tags.json")
                           .read_text(encoding="utf-8"))
    missing |= {f"campion: {n}" for n in champions if not have("champions", n)}
    assert not missing, f"iconite lipsa (ruleaza build_icons.py): {sorted(missing)}"

    # summoner spells: raportam procentul, nu blocam (rescrape in curs e normal)
    with_summoners = sum(1 for b in builds if len(b.get("summoners") or []) == 2)
    summoner_names = {n for b in builds for n in (b.get("summoners") or [])}
    summoner_icons = sum(1 for n in summoner_names if have("summoners", n))

    # augmentele vin de la Riot, tier list-ul de la u.gg: numele pot diferi
    import augment_tier
    tiers = json.loads((ROOT / "ingame-app" / "data" / "augments-global.json")
                       .read_text(encoding="utf-8"))
    names = augment_tier.flatten_names(tiers)   # aceeasi sursa ca OCR-ul
    covered = sum(1 for n in names if have("augments", n))
    assert covered >= len(names) * 0.9, f"prea putine iconite de augment: {covered}/{len(names)}"

    counts = {k: len(list((ICONS / k).glob("*.png")))
              for k in ("items", "champions", "augments", "summoners")}
    print(f"selfcheck OK: iconite {counts}, augmente acoperite {covered}/{len(names)}, "
          f"summoners {with_summoners}/{len(builds)} campioni "
          f"({summoner_icons}/{len(summoner_names)} iconite unice)")

    assert champ_ocr.find_names("Pick Sett or Jinx, Vi too", ["Sett", "Jinx", "Vi", "Jax"]) \
        == ["Sett", "Jinx"]

    # starea trimisa interfetei: serializabila si cu forma asteptata, pe monitoare false
    class Stub:
        phase, error, assigned, bench, team = "idle", None, None, [], []
        roster = {"local_champion": "Ahri", "enemies": ["Jinx"], "own_items": []}
        status = ocr_status = ""
        augments = [{"name": names[0], "tier": "S", "is_best": True, "slot": 0}]
        stat_anvil, taken_augments = [], [names[1]]
        global_augments = tiers
        resolved_build = {"starting": ["Doran's Ring"], "sell": None, "full": False,
                          "core": [{"item": "Luden's Echo", "owned": False, "next": True}],
                          "picks": [{"item": "Zhonya's Hourglass", "reason": "x", "owned": False,
                                     "next": False}], "unavailable": [], "range": "ranged"}

    eng = Engine(lcu, Stub(), ingame, Stub())
    eng.reader.offers, eng.reader.pins = [], {}
    game = eng.in_game()
    assert game["build"]["next"][0]["item"] == "Luden's Echo", game["build"]
    assert game["offer"][0]["icon"] and game["taken"][0]["name"] == names[1], game
    json.dumps(eng.state())
    print("selfcheck OK (stare pentru interfata)")

    # OCR-ul real functioneaza si in exe (winrt e incarcat dinamic)
    import ocr_augments
    from PIL import Image, ImageDraw, ImageFont
    pic = Image.new("RGB", (520, 120), (20, 26, 40))
    ImageDraw.Draw(pic).text((20, 30), "Goliath  Eureka", fill=(240, 230, 210),
                             font=ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 44))
    read = ocr_augments.read_offer(pic, names)[0]
    assert "Goliath" in read or "Eureka" in read, f"OCR nu citeste nimic: {read}"


def already_running():
    """True daca o alta instanta a legat deja portul-santinela: doua fire de OCR
    care fotografiaza ecranul in acelasi timp sunt exact ce nu vrem in meci."""
    import socket
    global _lock_socket
    _lock_socket = socket.socket()
    try:
        _lock_socket.bind(("127.0.0.1", 52789))
    except OSError:
        return True
    return False        # socket-ul ramane deschis cat traieste procesul


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return
    enable_dpi_awareness()
    be_lightweight()
    if already_running():
        emit({"t": "error", "text": "already running"})
        return

    # tier-uri si statistici mai noi din repo, citite la importul modulelor
    os.environ["ARAM_DATA_DIR"] = str(HOME / "data-sync")
    lcu = _load_page("lcu_page", "lcu-app")
    ingame = _load_page("ingame_page", "ingame-app")

    lcu_mon = lcu.Monitor(lcu.load_champion_data())
    threading.Thread(target=lcu_mon.run, daemon=True).start()
    ingame_mon = ingame.Monitor(
        ingame.load_json("champion-id-map.json"),
        ingame.load_json("champion-tags.json"),
        ingame.load_json("item-rules.json"),
        __import__("bundle").get().get("global") or ingame.load_json("augments-global.json"),
        ingame.load_json("item-stats.json"),
        ingame.load_json("augment-items.json"),
    )
    ingame_mon.run()

    engine = Engine(lcu, lcu_mon, ingame, ingame_mon)
    engine.reader.run()
    counts = {k: len(list((ICONS / k).glob("*.png"))) for k in ("champions", "augments")}
    counts["builds"] = len(list((ROOT / "ingame-app" / "data" / "builds").glob("*.json")))
    emit({"t": "hello", "version": VERSION, "icons": str(ICONS), "counts": counts})

    stop = threading.Event()
    threading.Thread(target=engine.loop, args=(stop,), daemon=True).start()
    if "--no-update" not in sys.argv:
        threading.Thread(target=maintenance, daemon=True).start()

    # comenzile vin pe stdin; cand se inchide, interfata a murit: iesim si noi,
    # altfel ramanem un proces orfan care face OCR pe ecran
    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg.get("cmd") == "quit":
            break
        try:
            engine.command(msg)
        except Exception as e:
            emit({"t": "error", "text": f"{type(e).__name__}: {e}"})
    stop.set()
    engine.reader.stop.set()
    lcu_mon.stop.set()
    ingame_mon.stop.set()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        (HOME / "eroare.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
