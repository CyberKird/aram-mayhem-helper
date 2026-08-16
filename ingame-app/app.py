"""ARAM Mayhem helper: roster + build adaptat la comp, in timpul meciului.

Nu foloseste Overwolf: rosterul (coechipieri + inamici) vine de la Riot local
(Live Client Data API). Overlay-ul asta NU porneste niciodata un browser --
un Chromium lansat in timpul unui meci taie framerate-ul (confirmat: ~40fps
pe un setup cu 3 monitoare). Build-urile se citesc STRICT din cache; daca un
campion nu e in cache, overlay-ul arata "date indisponibile", nu scrapuieste
pe loc. Ruleaza `prefetch_builds.py` separat, INAINTE sa joci, ca sa umpli
cache-ul.

Augment-urile oferite nu se pot citi fara Overwolf sau OCR (Riot nu le expune
pe API-ul asta) -- ramane limitarea cunoscuta, vezi README.

    python app.py              # porneste overlay-ul
    python app.py --selfcheck  # verifica logica pura, fara joc pornit
"""

import json
import pathlib
import sys
import threading
import time

import augment_tier
import live_client
import ocr_augments
import ocr_stat_anvil
import rules_engine
import stat_anvil
from build_scraper import load_cached

DATA = pathlib.Path(__file__).with_name("data")

# Cat timp lasam o oferta pe ecran. Alegerea unui augment dureaza cateva
# secunde, deci daca aceleasi nume se citesc si dupa atat, a ramas ceva
# afisat degeaba -- iar panoul de augmente acoperea build-ul pana dadeai
# alt-tab (unfocus-ul golea lista, si asa se "repara" singur).
OFFER_TTL = 25.0

BG = "#0a0e14"
CARD = "#0f1720"
BORDER = "#1e2a38"
TEXT = "#e6e6e6"
MUTED = "#7a8899"
HOT = "#ff4655"

TIER_COLORS = {"S+": "#ff4655", "S": "#ff9a3c", "A": "#ffd166",
               "B": "#8ac926", "C": "#4a9de0", "D": "#6b7280", "?": "#3f4650"}
TIER_FG = {"S+": "#ffffff", "S": "#2b1400", "A": "#3a2c00",
           "B": "#182b00", "C": "#04203a", "D": "#ffffff", "?": "#c3cbd6"}


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def normalize_roster(raw, champ_id_map):
    """championName (id intern Riot) -> nume afisat, pentru allies/enemies."""
    def fix(name):
        return champ_id_map.get(name, name)

    return {
        "allies": [fix(n) for n in raw.get("allies", [])],
        "enemies": [fix(n) for n in raw.get("enemies", [])],
        # numele de itemi vin deja afisabile, nu au nevoie de normalizare
        "enemy_items": list(raw.get("enemy_items") or []),
        "ally_items": list(raw.get("ally_items") or []),
        "own_items": list(raw.get("own_items") or []),
        "local_champion": fix(raw["local_champion"]) if raw.get("local_champion") else None,
    }


class Monitor:
    """Interogheaza Live Client Data API si (separat) ecranul, in fire proprii.

    Firul de UI citeste direct atributele; sunt sigure fara lock pentru ca
    aici se atribuie mereu obiecte noi, nu se modifica cele existente.
    """

    def __init__(self, champ_id_map, champion_tags, rules, global_augments,
                 item_stats=None, augment_items=None):
        self.champ_id_map = champ_id_map
        self.champion_tags = champion_tags
        self.rules = rules
        self.item_stats = item_stats or {}
        self.global_augments = global_augments
        self.augment_items = augment_items or {}
        self.augment_names = augment_tier.flatten_names(global_augments)
        # augmentele confirmate de tine (click pe banda). Nu se pot citi de
        # nicaieri: Riot nu expune alegerea, iar din oferta nu se poate deduce
        # care din cele 3 ai luat. Un click e mai sigur decat orice ghicit.
        self.taken_augments = []

        self.stop = threading.Event()
        self.phase = "waiting_for_game"   # waiting_for_game | in_game
        self.roster = None
        self.build = None
        self.resolved_build = None   # {core, picks} -- build final, nu meniu
        self.augments = []           # ultimele augmente detectate pe ecran
        self.ocr_status = ""         # de ce e goala lista de mai sus, daca e
        self.status = ""
        self.stat_anvil = []         # shard-urile oferite acum, cu recomandare

        self._known_champion = None
        self._last_augments = ()
        self._empty_reads = 0
        self._offer_since = 0.0
        self._expired_names = set()
        self._offer_pool = {}
        self._stat_anvil_tick = 0
        self._last_stat_anvil = ()

    def run(self):
        threading.Thread(target=self._run_roster, daemon=True).start()
        threading.Thread(target=self._run_ocr, daemon=True).start()

    def _run_roster(self):
        # 4s: nu are rost sa cerem mai des, jocul nu se schimba atat de repede
        # si vrem cat mai putina activitate de fundal in timp ce joci
        while not self.stop.is_set():
            try:
                self._roster_cycle()
            except Exception as e:
                self.status = f"{type(e).__name__}: {e}"
            self.stop.wait(6.0 if self.phase == "waiting_for_game" else 4.0)

    def _run_ocr(self):
        # 1.2s: fereastra de alegere a augmentului sta pe ecran cateva secunde,
        # iar un ciclu costa acum ~0.3s (BMP in loc de PNG + chei normalizate
        # o singura data). La 3s cum era inainte, puteai astepta pana la 3.8s
        # ca sa vezi ceva, ceea ce se simtea ca si cum n-ar functiona.
        while not self.stop.is_set():
            if self.phase == "in_game":
                try:
                    self._ocr_cycle()
                except Exception as e:
                    # inainte disparea tacut; acum macar UI-ul poate arata
                    # ca OCR-ul chiar a picat, in loc sa para ca nu face nimic
                    self.ocr_status = f"OCR: {type(e).__name__}: {e}"
                try:
                    self._stat_anvil_cycle()
                except Exception:
                    # ecranul de anvil e un plus; daca pica, oferta de augment
                    # (care are countdown) trebuie sa mearga mai departe
                    self.stat_anvil = []
            self.stop.wait(1.2)

    def _roster_cycle(self):
        raw = live_client.get_roster()
        if raw is None:
            if self.phase != "waiting_for_game":
                self._reset()
            return

        self.phase = "in_game"
        roster = normalize_roster(raw, self.champ_id_map)
        self.roster = roster

        champ = roster["local_champion"]
        if champ and champ != self._known_champion:
            self._known_champion = champ
            # niciodata scraping live: doar citim ce exista deja in cache
            self.build = load_cached(champ)
            self.status = "" if self.build else (
                f"{champ}: nu e in cache -- ruleaza prefetch_builds.py {champ}")

        self._recompute_build()

    def _ocr_cycle(self):
        found, self.ocr_status = ocr_augments.detect_offered_augments(self.augment_names)

        # o oferta dispare de pe ecran dupa ce alegi; fara asta lista ramanea
        # afisata la nesfarsit si impingea build-ul in afara ferestrei
        if not found:
            self._empty_reads += 1
            if self._empty_reads >= 2 and (self.augments or self._offer_pool):
                self.augments = []
                self._offer_pool = {}
                self._last_augments = ()
                # oferta a disparut de pe ecran: de aici incolo, aceleasi
                # nume inseamna o oferta noua, nu una expirata
                self._expired_names = set()
            return
        self._empty_reads = 0

        # Numele dintr-o oferta deja expirata raman ignorate pana cand ecranul
        # chiar se goleste. Tinem minte NUMELE, nu cheia ofertei: cheia se
        # schimba pe masura ce se aduna carduri, iar cele vechi s-ar fi
        # strecurat inapoi in oferta urmatoare.
        fresh = [n for n in found if n not in self._expired_names]
        if not fresh:
            return

        now = time.monotonic()

        # O oferta are exact 3 carduri. Daca apare un al PATRULEA nume nou,
        # inseamna ca oferta s-a schimbat (reroll), nu ca am citit mai bine
        # aceleasi carduri -- si atunci pornim un bazin nou. Fara asta,
        # augmentele vechi ramaneau primele si le taiau pe cele noi.
        noi = [n for n in fresh if n not in self._offer_pool]
        if noi and len(self._offer_pool) >= ocr_augments.MAX_OFFER:
            self._offer_pool = {}

        if not self._offer_pool:
            self._offer_since = now      # abia acum incepe o oferta noua

        # OCR-ul citeste de fiecare data alt subset din aceleasi 3 carduri:
        # fontul e decorativ, cardurile au animatie de aparitie, iar unele
        # nume ies mai greu. Le ADUNAM, nu le inlocuim -- altfel lista sarea
        # de la o citire la alta si nu vedeai niciodata toate trei deodata.
        for name in fresh:
            self._offer_pool.setdefault(name, now)

        champ = (self.roster or {}).get("local_champion")
        names = sorted(self._offer_pool, key=self._offer_pool.get)[:ocr_augments.MAX_OFFER]
        key = (tuple(sorted(names)), champ)

        if key == self._last_augments:
            # Aceleasi nume, de prea mult timp: o oferta se rezolva in cateva
            # secunde (jocul alege singur daca nu apuci tu), deci daca inca le
            # citim dupa OFFER_TTL inseamna ca a ramas ceva pe ecran, nu ca
            # mai ai de ales. Le ascundem ca sa nu acopere build-ul.
            if now - self._offer_since > OFFER_TTL:
                self._expired_names = set(self._offer_pool)
                self.augments = []
                self._offer_pool = {}
                self._last_augments = ()
                self.ocr_status = "oferta veche, ascunsa"
            return

        self._last_augments = key
        # campionul conteaza: acelasi augment poate fi S+ pe unul si B pe altul
        self.augments = augment_tier.rate(names, self.global_augments, champ)

    def _stat_anvil_cycle(self):
        # Stat Anvil nu are countdown care te forteaza sa alegi repede (spre
        # deosebire de augment), deci nu are rost sa cheltuim OCR la fel de
        # des -- verificam o data la 3 cicluri (~3.6s) si doar cand nu e deja
        # o oferta de augment pe ecran (nu pot fi amandoua deodata).
        self._stat_anvil_tick += 1
        if self.augments or self._stat_anvil_tick % 3 != 0:
            return

        found, status = ocr_stat_anvil.detect_offered_shards(stat_anvil.SHARD_NAMES)
        if not found:
            if self.stat_anvil:
                self.stat_anvil = []
                self._last_stat_anvil = ()
            return

        key = tuple(found)
        if key == self._last_stat_anvil:
            return
        self._last_stat_anvil = key

        champ = (self.roster or {}).get("local_champion")
        enemies = (self.roster or {}).get("enemies") or []
        self.stat_anvil = stat_anvil.recommend(found, self.champion_tags, champ, enemies)

    def _recompute_build(self):
        if not self.roster or not self.build or not self.build.get("pool"):
            self.resolved_build = None
            return
        self.resolved_build = rules_engine.resolve_build(
            self.build, self.roster, self.champion_tags, self.rules,
            self.item_stats, self.taken_augments, self.augment_items)

    def _reset(self):
        self.phase = "waiting_for_game"
        self.roster = None
        self.build = None
        self.resolved_build = None
        self.augments = []
        self.ocr_status = ""
        self.stat_anvil = []
        self._last_augments = ()
        self._empty_reads = 0
        self._offer_since = 0.0
        self._expired_names = set()
        self._offer_pool = {}
        self._stat_anvil_tick = 0
        self._last_stat_anvil = ()
        self.taken_augments = []   # meci nou, augmente noi
        self._known_champion = None
        self.status = ""


def build_ui(mon):
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("ARAM Mayhem - in joc")
    # fereastra normala (bara de titlu Windows), ca sa poata fi mutata si
    # redimensionata cu mana -- pe un setup cu mai multe monitoare, pozitia
    # calculata automat poate iesi in afara ecranului vizibil
    root.attributes("-topmost", True)
    root.resizable(True, True)
    root.minsize(260, 200)
    root.configure(fg_color=BG)
    root.withdraw()
    root.geometry("320x480")

    frame = ctk.CTkFrame(root, fg_color=BG, border_color=BORDER, border_width=1)
    frame.pack(fill="both", expand=True)

    head = ctk.CTkFrame(frame, fg_color="transparent")
    head.pack(fill="x", padx=10, pady=(9, 6))
    ctk.CTkLabel(head, text="ARAM MAYHEM - IN JOC", text_color=MUTED,
                 font=("Segoe UI", 10, "bold")).pack(side="left")

    body = ctk.CTkFrame(frame, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def section(text):
        ctk.CTkLabel(body, text=text, text_color=MUTED, anchor="w",
                     font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(8, 3))

    def augment_row(entry):
        color = TIER_COLORS.get(entry["tier"], TIER_COLORS["?"])
        row = ctk.CTkFrame(body, fg_color=CARD, corner_radius=8,
                           border_width=2 if entry["is_best"] else 0, border_color=color)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=entry["tier"], width=34, height=24, corner_radius=6,
                     fg_color=color, text_color=TIER_FG.get(entry["tier"], "#fff"),
                     font=("Segoe UI", 12, "bold")).pack(side="left", padx=8, pady=7)
        ctk.CTkLabel(row, text=entry["name"], text_color=TEXT, anchor="w",
                     font=("Segoe UI", 12)).pack(side="left", padx=(2, 6))
        if entry["is_best"]:
            ctk.CTkLabel(row, text="BEST", text_color=color, anchor="e",
                         font=("Segoe UI", 9, "bold")).pack(side="right", padx=8)

    def core_row(names):
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        for name in names:
            ctk.CTkLabel(row, text=name, fg_color=CARD, text_color=MUTED,
                         corner_radius=6, font=("Segoe UI", 10),
                         padx=8, pady=4).pack(side="left", padx=(0, 4), pady=2)

    def pick_row(entry):
        hot = bool(entry["reason"])
        row = ctk.CTkFrame(body, fg_color=CARD, corner_radius=8,
                           border_width=2 if hot else 0, border_color=HOT)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=entry["item"], text_color=TEXT, anchor="w",
                     font=("Segoe UI", 12)).pack(side="left", padx=8, pady=6)
        if hot:
            ctk.CTkLabel(row, text=entry["reason"], text_color=HOT, anchor="e",
                         font=("Segoe UI", 9)).pack(side="right", padx=8)

    shown = {"visible": False, "fingerprint": None}

    def fingerprint():
        picks = mon.resolved_build["picks"] if mon.resolved_build else []
        return (
            mon.phase,
            mon.roster and mon.roster.get("local_champion"),
            mon.roster and tuple(mon.roster.get("enemies", [])),
            mon.build and mon.build.get("champion"),
            tuple((p["item"], p["reason"]) for p in picks),
            tuple((a["name"], a["tier"]) for a in mon.augments),
            mon.status,
        )

    def refresh():
        active = mon.phase == "in_game"
        if active != shown["visible"]:
            root.deiconify() if active else root.withdraw()
            shown["visible"] = active

        fp = fingerprint()
        if active and fp != shown["fingerprint"]:
            shown["fingerprint"] = fp
            for w in body.winfo_children():
                w.destroy()

            if mon.augments:
                section("AUGMENTE OFERITE (OCR)")
                for a in mon.augments:
                    augment_row(a)

            if mon.roster and mon.roster.get("local_champion"):
                section("CAMPIONUL TAU")
                ctk.CTkLabel(body, text=mon.roster["local_champion"], text_color=TEXT,
                             font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x")

            if mon.roster and mon.roster.get("enemies"):
                section(f"INAMICI ({len(mon.roster['enemies'])})")
                ctk.CTkLabel(body, text=", ".join(mon.roster["enemies"]), text_color=MUTED,
                             font=("Segoe UI", 10), anchor="w", wraplength=260,
                             justify="left").pack(fill="x")

            if mon.resolved_build:
                if mon.resolved_build["core"]:
                    section("CORE")
                    core_row(mon.resolved_build["core"])
                if mon.resolved_build["picks"]:
                    section("BUILD FINAL")
                    for entry in mon.resolved_build["picks"]:
                        pick_row(entry)

            if mon.status:
                ctk.CTkLabel(body, text=mon.status, text_color=MUTED, anchor="w",
                             justify="left", wraplength=260,
                             font=("Segoe UI", 10)).pack(fill="x", pady=8)
            elif not mon.roster:
                ctk.CTkLabel(body, text="se incarca...", text_color=MUTED, anchor="w",
                             font=("Segoe UI", 11)).pack(fill="x", pady=12)

        root.after(2000, refresh)

    def close():
        mon.stop.set()
        root.destroy()

    root.bind("<Escape>", lambda _: close())
    root.protocol("WM_DELETE_WINDOW", close)  # X-ul din bara de titlu
    refresh()
    return root


def selfcheck():
    champ_id_map = load_json("champion-id-map.json")
    champion_tags = load_json("champion-tags.json")
    rules = load_json("item-rules.json")
    global_augments = load_json("augments-global.json")

    import augment_tier
    import ocr_augments
    from build_scraper import slug

    # "Nunu & Willump" / "Renata Glasc" au 404 real pe u.gg cu slug-ul
    # generic (strip tot ce nu e alfanumeric) -- u.gg foloseste numele scurt
    # Riot pentru astia doi. Confirmat manual, nu ghicit.
    assert slug("Nunu & Willump") == "nunu"
    assert slug("Renata Glasc") == "renata"
    assert slug("Sett") == "sett"          # override-ul nu trebuie sa strice restul

    names = augment_tier.flatten_names(global_augments)
    # u.gg claseaza ~206, dar cautam si numele din datele Riot: un augment
    # nelistat de u.gg (nou la patch) nu era recunoscut deloc si vedeai doua
    # carduri din trei. Nu fixam numarul exact, se schimba la fiecare patch.
    assert len(names) > 400, len(names)
    assert len(names) == len({n.lower() for n in names}), "nume duplicate"

    # cuvintele de interfata nu au voie in vocabular: "Damage" si "Utility"
    # sunt etichete pe cardul de augment, iar ca nume de augment produceau
    # augmente inventate din text perfect normal
    for word in ("Damage", "Utility", "Max Health", "Mythical"):
        assert word not in names, word

    # augmentele reale trebuie sa fie acolo, inclusiv cele neclasate de u.gg
    for real in ("Goliath", "Pinball", "Upgrade Ravenous Hydra"):
        assert real in names, real

    # zero coliziuni de nume intre raritati: cautarea de tier nu are nevoie
    # sa stie raritatea (OCR-ul n-o poate afla din text simplu oricum)
    assert augment_tier.lookup_tier("Goliath", global_augments) == "S+"
    assert augment_tier.lookup_tier("Multishot", global_augments) == "C"
    assert augment_tier.lookup_tier("NuExista", global_augments) == "?"

    rated = augment_tier.rate(["Goliath", "Multishot", "Overloaded"], global_augments)
    assert [r["tier"] for r in rated] == ["S+", "C", "D"]
    assert rated[0]["is_best"] and not rated[1]["is_best"]

    # OCR citeste text cu greseli tipice; potrivirea trebuie sa fie tolerantă
    # dar sa nu forteze potriviri pe text fara sens
    lines = ["GoIiath", "MuItishot", "zgomot random", "Overloacled"]
    matched = ocr_augments.match_augments(lines, names)
    assert set(matched) >= {"Goliath", "Multishot"}, matched
    assert ocr_augments.match_augments(["abc", "xyz"], names) == []

    # Ecrane reale care NU sunt oferte de augmente. Magazinul de itemi era
    # cel mai inselator: "Invulnerability" contine augmentul "Vulnerability",
    # iar itemul "Liandry's Torment" semana fuzzy cu augmentul "Tormentor".
    # Cum oferta se aduna si e taiata la 3, gunoiul asta impingea afara
    # augmentele adevarate.
    magazin = ("Stormsurge Zhonya's Hourglass 2800 Burst Damage Good Against: "
               "3250 Invulnerability SELL UNDO PURCHASE COMPONENTS "
               "Liandry's Torment 3000 60 Ability Power 300 Health Torment "
               "Damaging Abilities burn enemies")
    assert ocr_augments.match_augments([magazin], names) == [], \
        ocr_augments.match_augments([magazin], names)

    scoreboard = "28 66 18 7/5/7 5/7/7 e 1 34 x' 40 Grimoire CyberKird 13 69 19"
    assert ocr_augments.match_augments([scoreboard], names) == []

    # ...dar o oferta adevarata trebuie sa treaca intreaga, inclusiv cand OCR
    # citeste "0k" cu cifra zero in loc de "Ok"
    oferta = ("Phenomenal Evil Damage Permanently gain 1 Ability Power when you "
              "damage enemy champions with Abilities. 0k Boomerang Damage "
              "Autocast throw a boomerang at a nearby enemy every 1 Os.")
    assert ocr_augments.match_augments([oferta], names) == \
        ["Phenomenal Evil", "Ok Boomerang"], ocr_augments.match_augments([oferta], names)

    # normalizare nume interne -> afisate
    raw = {"allies": ["Sett"], "enemies": ["MonkeyKing", "FiddleSticks"],
           "local_champion": "Sett"}
    fixed = normalize_roster(raw, champ_id_map)
    assert fixed["enemies"] == ["Wukong", "FiddleSticks"], fixed
    # FiddleSticks nu are corespondent exact (Data Dragon foloseste
    # "Fiddlesticks", fara majuscula pe S) -- ramane neschimbat, nu arunca
    assert fixed["local_champion"] == "Sett"

    # roster fara jucator local identificat: gol, nu ghicit
    raw2 = {"allies": [], "enemies": [], "local_champion": None}
    assert normalize_roster(raw2, champ_id_map)["local_champion"] is None

    # motorul de reguli: 3+ inamici AP scoate itemi MR din pool
    roster = {"allies": [], "enemies": ["Ahri", "Lux", "Veigar"]}
    pool = ["Force of Nature", "Thornmail", "Boots"]
    hits = rules_engine.evaluate_rules(roster, champion_tags, rules, pool)
    assert any(h["item"] == "Force of Nature" for h in hits), hits

    # invariant critic: niciodata un item din afara pool-ului
    every_enemy = {"allies": [], "enemies": list(champion_tags.keys())[:6]}
    for p in (pool, [], ["Boots"]):
        for h in rules_engine.evaluate_rules(every_enemy, champion_tags, rules, p):
            assert h["item"] in p, f"item din afara pool-ului: {h['item']}"

    # campioni necunoscuti in tags nu arunca si nu se numara
    assert rules_engine.evaluate_rules(
        {"allies": [], "enemies": ["NuExista"]}, champion_tags, rules, pool) == []

    # regulile pe itemii chiar cumparati, si golul de echipa la anti-heal:
    # daca un coechipier l-a luat deja, nu mai insistam sa-l iei si tu
    item_stats = load_json("item-stats.json")
    heal_pool = ["Mortal Reminder", "Boots"]
    vindeca = {"allies": [], "enemies": [], "enemy_items": ["Bloodthirster",
                                                            "Vampiric Scepter"]}

    gol = rules_engine.evaluate_rules(dict(vindeca, ally_items=["Infinity Edge"]),
                                      champion_tags, rules, heal_pool, item_stats)
    assert any(h["rule"] == "enemy_heals_nobody_counters" for h in gol), gol

    acoperit = rules_engine.evaluate_rules(dict(vindeca, ally_items=["Mortal Reminder"]),
                                           champion_tags, rules, heal_pool, item_stats)
    assert not any(h["rule"] == "enemy_heals_nobody_counters" for h in acoperit), acoperit

    # itemii de armura ai inamicilor cer penetrare, nu ghicim din campioni
    armura = {"allies": [], "enemies": [], "ally_items": [],
              "enemy_items": ["Thornmail", "Chain Vest"]}
    pen = rules_engine.evaluate_rules(armura, champion_tags, rules,
                                      ["Lord Dominik's Regards"], item_stats)
    assert [h["rule"] for h in pen] == ["enemy_bought_armor"], pen

    # resolve_build: exact un item per slot situational, niciodata duplicat
    # cu core-ul sau intre sloturi, chiar daca optiunile se suprapun
    build = {
        "starting": ["Doran's Shield", "Health Potion"],
        "core": ["Heartsteel", "Mercury's Treads", "Overlord's Bloodmail"],
        "fourth": ["Warmog's Armor", "Sterak's Gage"],
        "fifth": ["Sterak's Gage", "Warmog's Armor", "Force of Nature"],
        "sixth": ["Sterak's Gage", "Spirit Visage", "Force of Nature"],
        "pool": ["Heartsteel", "Mercury's Treads", "Overlord's Bloodmail",
                 "Warmog's Armor", "Sterak's Gage", "Force of Nature",
                 "Spirit Visage"],
    }
    resolved = rules_engine.resolve_build(
        build, {"allies": [], "enemies": ["Ahri", "Lux", "Veigar"]}, champion_tags, rules)
    assert resolved["starting"] == ["Doran's Shield", "Health Potion"]
    picks = [p["item"] for p in resolved["picks"]]

    # itemii pe care ii ai deja: marcati "owned", si primul neluat e "next".
    # Jocul scrie "Heartsteel" la fel, dar altele difera prin majuscule
    # ("Blade of The Ruined King"), deci potrivirea e case-insensitive.
    have = rules_engine.resolve_build(
        build, {"allies": [], "enemies": [],
                "own_items": ["heartsteel", "MERCURY'S TREADS"]},
        champion_tags, rules)
    core_owned = [(c["item"], c["owned"]) for c in have["core"]]
    assert core_owned[0] == ("Heartsteel", True), core_owned
    assert core_owned[1] == ("Mercury's Treads", True), core_owned
    assert core_owned[2][1] is False, core_owned
    assert have["core"][2]["next"] is True, "urmatorul de cumparat gresit"
    assert not any(c["next"] for c in have["core"][:2])
    assert not any(p["next"] for p in have["picks"])

    # fara niciun item, primul din core e urmatorul
    gol = rules_engine.resolve_build(build, {"allies": [], "enemies": [],
                                             "own_items": []}, champion_tags, rules)
    assert gol["core"][0]["next"] is True and not gol["core"][0]["owned"]

    # sfatul de vandut cizmele: doar la build plin, si niciodata cand chiar
    # cizmele alea contreaza compozitia inamica
    six = ["Heartsteel", "Mercury's Treads", "Overlord's Bloodmail",
           "Warmog's Armor", "Sterak's Gage", "Spirit Visage"]
    sett = {"core": ["Heartsteel", "Mercury's Treads", "Overlord's Bloodmail"],
            "fourth": ["Warmog's Armor"], "fifth": ["Sterak's Gage"],
            "sixth": ["Spirit Visage"],
            "pool": six + ["Thornmail", "Force of Nature"]}

    def boots_for(enemies, own):
        return rules_engine.resolve_build(
            sett, {"allies": [], "enemies": enemies, "enemy_items": [],
                   "ally_items": [], "own_items": own},
            champion_tags, rules, item_stats)["boots"]

    # 3+ inamici AP -> Mercury's Treads isi face treaba, nu o vindem
    assert boots_for(["Ahri", "Lux", "Veigar"], six) is None
    # fara semnal pentru Treads -> sfatul apare
    assert boots_for(["Jinx", "Vayne", "Ashe"], six) is not None
    # build incomplet -> niciodata
    assert boots_for(["Jinx", "Vayne", "Ashe"], six[:4]) is None
    # ce recomanda nu are voie sa fie componenta sau alte cizme
    adv = boots_for(["Jinx", "Vayne", "Ashe"], six)
    assert not (item_stats.get(adv["buy"]) or {}).get("component"), adv
    assert not (item_stats.get(adv["buy"]) or {}).get("boots"), adv

    # ...si NICIODATA ceva ce ai deja, oricum ar fi scris numele. Jocul si
    # u.gg difera prin majuscule si apostrof, iar fara normalizare itemul
    # detinut parea nou si era recomandat inca o data (bug raportat in joc).
    assert rules_engine.item_key("Blade of The Ruined King") == \
        rules_engine.item_key("Blade of the Ruined King")
    assert rules_engine.item_key("Luden's Echo") == rules_engine.item_key("Luden’s Echo")

    variante = ["Heartsteel", "MERCURY'S TREADS", "Overlord's Bloodmail",
                "Warmog's Armor", "Sterak's Gage", "THORNMAIL"]
    adv2 = boots_for(["Jinx", "Vayne", "Ashe"], variante)
    if adv2:
        detinute = {rules_engine.item_key(n) for n in variante}
        assert rules_engine.item_key(adv2["buy"]) not in detinute, adv2

    # --- augment care cere un item anume --------------------------------
    aug_items = load_json("augment-items.json")
    gol_roster = {"allies": [], "enemies": [], "enemy_items": [],
                  "ally_items": [], "own_items": []}

    fara = rules_engine.resolve_build(build, gol_roster, champion_tags, rules,
                                      item_stats)
    cu = rules_engine.resolve_build(build, gol_roster, champion_tags, rules,
                                    item_stats, ["Upgrade Zhonya's"], aug_items)
    assert cu["core"][0]["item"] == "Zhonya's Hourglass", cu["core"][:2]
    assert cu["core"][0]["next"], "itemul cerut de augment trebuie sa fie urmatorul"
    assert fara["core"][0]["item"] != "Zhonya's Hourglass", \
        "fara augment n-avea ce cauta acolo"

    # nu apare de doua ori daca era oricum in build
    cu_dublu = rules_engine.resolve_build(
        build, gol_roster, champion_tags, rules, item_stats,
        ["Upgrade " + build["core"][0]], {"Upgrade " + build["core"][0]: build["core"][0]})
    nume = [e["item"] for e in cu_dublu["core"] + cu_dublu["picks"]]
    assert nume.count(build["core"][0]) == 1, nume

    # un item pe care il ai deja nu se mai cere
    detin = rules_engine.resolve_build(
        build, dict(gol_roster, own_items=["Zhonya's Hourglass"]),
        champion_tags, rules, item_stats, ["Upgrade Zhonya's"], aug_items)
    assert detin["core"][0]["item"] != "Zhonya's Hourglass", detin["core"][:2]

    # augment necunoscut in mapare -> build neschimbat
    neutru = rules_engine.resolve_build(build, gol_roster, champion_tags, rules,
                                        item_stats, ["Ok Boomerang"], aug_items)
    assert [e["item"] for e in neutru["core"]] == \
        [e["item"] for e in fara["core"]], neutru["core"]

    # --- Stat Anvil ------------------------------------------------------
    import stat_anvil

    # fiecare nume de card trebuie sa aiba o categorie, altfel scorul e orb
    assert all(n in stat_anvil.SHARD_CATEGORY for n in stat_anvil.SHARD_NAMES)
    for cat in set(stat_anvil.SHARD_CATEGORY.values()):
        assert cat in stat_anvil.CATEGORY_BY_DAMAGE, cat

    # exact cardurile din captura reala: AP / Haste / Health
    reale = ["Ability Power Shard", "Ability Haste Shard", "Health Shard"]

    # pe un mage, AP-ul bate viata
    rec = stat_anvil.recommend(reale, champion_tags, "Lux", ["Jinx"])
    assert next(e for e in rec if e["is_best"])["name"] == "Ability Power Shard", rec

    # pe un tanc AD, AP-ul e inutil si nu are voie sa iasa primul
    rec2 = stat_anvil.recommend(reale, champion_tags, "Sett", ["Jinx"])
    assert next(e for e in rec2 if e["is_best"])["name"] != "Ability Power Shard", rec2

    # armura urca fata de MR cand inamicii sunt AD, si invers
    aparare = ["Armor Shard", "Magic Resist Shard"]
    ad_comp = stat_anvil.recommend(aparare, champion_tags, "Sett",
                                   ["Jinx", "Vayne", "Ashe"])
    assert next(e for e in ad_comp if e["is_best"])["name"] == "Armor Shard", ad_comp
    ap_comp = stat_anvil.recommend(aparare, champion_tags, "Sett",
                                   ["Ahri", "Lux", "Veigar"])
    assert next(e for e in ap_comp if e["is_best"])["name"] == "Magic Resist Shard", ap_comp

    # campion necunoscut -> tot da o recomandare, nu crapa
    necunoscut = stat_anvil.recommend(reale, champion_tags, "NuExista", [])
    assert len(necunoscut) == 3 and sum(e["is_best"] for e in necunoscut) == 1

    assert stat_anvil.recommend([], champion_tags, "Lux", []) == []

    # o oferta care ramane pe ecran la nesfarsit trebuie sa se stinga singura,
    # altfel acopera build-ul pana dai alt-tab (bug raportat in joc)
    global OFFER_TTL
    real_ttl, real_detect = OFFER_TTL, ocr_augments.detect_offered_augments
    try:
        OFFER_TTL = 0.01
        oferta = ["Goliath", "Multishot"]
        ocr_augments.detect_offered_augments = lambda names, **k: (list(oferta), "test")

        mon = Monitor(champ_id_map, champion_tags, rules, global_augments)
        mon.roster = {"local_champion": None}
        mon._ocr_cycle()
        assert len(mon.augments) == 2, mon.augments
        time.sleep(0.15)   # marja larga: sleep-ul pe Windows sare ~15ms
        mon._ocr_cycle()
        assert mon.augments == [], "oferta veche n-a fost ascunsa"
        mon._ocr_cycle()
        assert mon.augments == [], "oferta expirata a reaparut"
        oferta[:] = ["Dual Wield"]            # oferta noua: trebuie sa reapara
        mon._ocr_cycle()
        assert [a["name"] for a in mon.augments] == ["Dual Wield"], mon.augments

        # OCR-ul vede alt subset la fiecare citire din aceleasi carduri.
        # Trebuie ADUNATE, nu inlocuite: altfel lista sare intre variante si
        # nu vezi niciodata toate trei deodata (bug raportat in joc).
        OFFER_TTL = real_ttl
        mon2 = Monitor(champ_id_map, champion_tags, rules, global_augments)
        mon2.roster = {"local_champion": None}
        citiri = [["Goliath", "Multishot"], ["Goliath", "Overloaded"],
                  ["Multishot"]]
        it = iter(citiri)
        ocr_augments.detect_offered_augments = lambda names, **k: (next(it, []), "t")
        for _ in citiri:
            mon2._ocr_cycle()
        vazute = {a["name"] for a in mon2.augments}
        assert vazute == {"Goliath", "Multishot", "Overloaded"}, vazute

        # ...dar dispar cand oferta chiar se termina
        ocr_augments.detect_offered_augments = lambda names, **k: ([], "gol")
        mon2._ocr_cycle()
        mon2._ocr_cycle()
        assert mon2.augments == [], mon2.augments

        # REROLL: augmente complet noi trebuie sa inlocuiasca bazinul, nu sa
        # se adauge dupa el. Altfel cele vechi ramaneau primele si le taiau
        # pe cele noi la MAX_OFFER (bug raportat in joc).
        mon3 = Monitor(champ_id_map, champion_tags, rules, global_augments)
        mon3.roster = {"local_champion": None}
        secventa = [["Goliath", "Multishot"], ["Goliath", "Overloaded"],
                    ["Dual Wield", "Tap Dancer"]]
        it3 = iter(secventa)
        ocr_augments.detect_offered_augments = lambda names, **k: (next(it3, []), "t")
        mon3._ocr_cycle()
        mon3._ocr_cycle()
        assert len(mon3.augments) == 3, mon3.augments      # s-au adunat
        mon3._ocr_cycle()                                   # reroll
        dupa = [a["name"] for a in mon3.augments]
        assert dupa == ["Dual Wield", "Tap Dancer"], dupa
        assert "Goliath" not in dupa, "augmentele vechi au ramas dupa reroll"
    finally:
        OFFER_TTL = real_ttl
        ocr_augments.detect_offered_augments = real_detect
    assert len(picks) == 3, picks
    assert len(set(picks)) == 3, f"item duplicat intre sloturi: {picks}"
    assert not (set(picks) & {c["item"] for c in resolved["core"]}), \
        "item din core repetat in picks"
    # Force of Nature (MR) trebuie sa apara, e in pool si se potriveste regulii
    assert "Force of Nature" in picks, picks

    print(f"selfcheck OK ({len(champ_id_map)} id-uri, {len(champion_tags)} campioni, "
          f"{len(rules['rules'])} reguli)")


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    champ_id_map = load_json("champion-id-map.json")
    champion_tags = load_json("champion-tags.json")
    rules = load_json("item-rules.json")
    global_augments = load_json("augments-global.json")

    mon = Monitor(champ_id_map, champion_tags, rules, global_augments,
                  load_json("item-stats.json"))
    mon.run()
    build_ui(mon).mainloop()
    mon.stop.set()


if __name__ == "__main__":
    main()
