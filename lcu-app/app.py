"""ARAM Mayhem helper: arata tier-ul campionilor de pe bench in champ select.

Ruleaza in fundal, se arata singur cand intri in champ select de Mayhem si
dispare cand se termina. Nu are nevoie de niciun click.

    python app.py              # porneste overlay-ul
    python app.py --selfcheck  # verifica logica pura, fara League pornit
"""

import json
import pathlib
import sys
import threading

import mayhem_logic as logic
import tier_list
from lcu_client import connect, find_lcu_process

DATA = pathlib.Path(__file__).with_name("champion_data.json")

GAMEFLOW = "/lol-gameflow/v1/session"
CHAMP_SELECT = "/lol-champ-select/v1/session"

BG = "#0a0e14"
CARD = "#0f1720"
BORDER = "#1e2a38"
TEXT = "#e6e6e6"
MUTED = "#7a8899"

# rampa cald -> rece, conventia de tier list pe care jucatorii o recunosc deja
TIER_COLORS = {
    "S+": "#ff4655", "S": "#ff9a3c", "A": "#ffd166",
    "B": "#8ac926", "C": "#4a9de0", "D": "#6b7280",
    logic.UNRANKED: "#3f4650",
}
# text inchis pe insignele deschise, alb pe cele inchise
TIER_FG = {"S+": "#ffffff", "S": "#2b1400", "A": "#3a2c00",
           "B": "#182b00", "C": "#04203a", "D": "#ffffff",
           logic.UNRANKED: "#c3cbd6"}


def load_champion_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


class Monitor:
    """Interogheaza LCU-ul intr-un fir separat si tine ultima stare cunoscuta.

    Firul de UI citeste direct atributele. E sigur fara lock pentru ca aici
    se atribuie mereu obiecte noi, nu se modifica cele existente.
    """

    def __init__(self, champion_data):
        self.champion_data = champion_data
        self.stop = threading.Event()
        self.phase = "waiting_for_client"
        self.assigned = None
        self.bench = []
        self.error = None
        self._client = None
        self._dumped = False

    def _interval(self):
        return {"waiting_for_client": 3.0, "idle": 2.0}.get(self.phase, 1.0)

    def run(self):
        while not self.stop.is_set():
            try:
                self.cycle()
            except Exception as e:
                # un monitor care moare in tacere e mai rau decat niciun
                # monitor: notam si mergem mai departe
                self.error = f"{type(e).__name__}: {e}"
            self.stop.wait(self._interval())

    def _reset(self, phase):
        self.phase = phase
        self.assigned = None
        self.bench = []

    def cycle(self):
        if self._client is None:
            if find_lcu_process() is None:
                self._reset("waiting_for_client")
                return
            self._client = connect()
            if self._client is None:
                self._reset("waiting_for_client")
                return
            self.phase = "idle"

        gameflow = self._client.get(GAMEFLOW)
        if gameflow is None:
            # clientul s-a inchis sau nu mai raspunde: reluam descoperirea
            self._client = None
            self._reset("waiting_for_client")
            return

        if not logic.is_mayhem_gameflow(gameflow):
            self._reset("idle")
            return

        session = self._client.get(CHAMP_SELECT)
        if session is None:
            self._reset("idle")
            return

        self.error = None
        self.phase = "in_mayhem_select"
        self._dump_session_once(session)
        self._read_session(session)

    def _dump_session_once(self, session):
        """Salveaza sesiunea bruta de champ select, pentru diagnostic.

        Mayhem ofera 2-3 "carti" de campion (fara bench, fara reroll) si nu
        stim inca in ce camp le tine clientul. Prima captura a prins doar
        momentul zero (nimeni nu alesese, benchChampions gol), deci scriem la
        FIECARE ciclu, nu o singura data: cartile apar dupa cateva secunde.

        Salvam si /pickable-champion-ids: `allowSubsetChampionPicks` era
        true in sesiune, deci lista restransa e cel mai probabil acolo.
        """
        try:
            snap = {"session": session}
            if self._client is not None:
                for ep in ("/lol-champ-select/v1/pickable-champion-ids",
                           "/lol-champ-select/v1/bannable-champion-ids"):
                    got = self._client.get(ep)
                    if got is not None:
                        snap[ep.rsplit("/", 1)[-1]] = got
            path = pathlib.Path(__file__).with_name("_champselect.json")
            path.write_text(json.dumps(snap, indent=1, ensure_ascii=False),
                            encoding="utf-8")
        except OSError:
            pass

    def _read_session(self, session):
        data, tiers, over = self.champion_data, tier_list.TIER_DATA, tier_list.NAME_OVERRIDES

        mine = logic.get_local_player_champion_id(session)
        ids = logic.parse_bench(session)

        # campionul propriu intra in comparatie, si stă PRIMUL in lista:
        # best_pick da primul la egalitate, iar la tier egal nu are rost sa
        # dai reroll. Fara el, BEST arata mereu spre bench chiar daca ai deja
        # ceva mai bun in mana.
        best = logic.best_pick(([mine] if mine else []) + ids, data, tiers, over)

        self.assigned = (dict(logic.describe(mine, data, tiers, over),
                              is_best=(mine == best)) if mine else None)
        self.bench = [
            dict(logic.describe(cid, data, tiers, over), is_best=(cid == best))
            for cid in ids
        ]


def build_ui(mon):
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("ARAM Mayhem")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(fg_color=BG)
    root.withdraw()

    width = 270
    root.geometry(f"{width}x400+{root.winfo_screenwidth() - width - 24}+80")

    frame = ctk.CTkFrame(root, fg_color=BG, border_color=BORDER, border_width=1)
    frame.pack(fill="both", expand=True)

    head = ctk.CTkFrame(frame, fg_color="transparent")
    head.pack(fill="x", padx=10, pady=(9, 6))
    ctk.CTkLabel(head, text="ARAM MAYHEM", text_color=MUTED,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
    ctk.CTkButton(head, text="X", width=18, height=18, fg_color="transparent",
                  hover_color=CARD, text_color=MUTED, font=("Segoe UI", 10),
                  command=lambda: (mon.stop.set(), root.destroy())).pack(side="right")

    body = ctk.CTkFrame(frame, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def card(parent, entry, label=None):
        color = TIER_COLORS.get(entry["tier"], TIER_COLORS[logic.UNRANKED])
        row = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8,
                           border_width=2 if entry.get("is_best") else 0,
                           border_color=color)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=entry["tier"], width=34, height=24, corner_radius=6,
                     fg_color=color, text_color=TIER_FG.get(entry["tier"], "#fff"),
                     font=("Segoe UI", 12, "bold")).pack(side="left", padx=8, pady=7)
        ctk.CTkLabel(row, text=entry["name"], text_color=TEXT, anchor="w",
                     font=("Segoe UI", 13)).pack(side="left", padx=(2, 6))
        if label:
            ctk.CTkLabel(row, text=label, text_color=color, anchor="e",
                         font=("Segoe UI", 9, "bold")).pack(side="right", padx=8)

    def section(text):
        ctk.CTkLabel(body, text=text, text_color=MUTED, anchor="w",
                     font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(8, 1))

    shown = {"visible": False}

    def refresh():
        active = mon.phase == "in_mayhem_select"
        if active != shown["visible"]:
            root.deiconify() if active else root.withdraw()
            shown["visible"] = active

        if active:
            for w in body.winfo_children():
                w.destroy()
            if mon.assigned:
                section("CAMPIONUL TAU")
                card(body, mon.assigned)
            if mon.bench:
                section("BENCH")
                for entry in mon.bench:
                    card(body, entry, "BEST" if entry["is_best"] else None)
            if not mon.assigned and not mon.bench:
                ctk.CTkLabel(body, text="se incarca...", text_color=MUTED,
                             font=("Segoe UI", 11)).pack(pady=12)

        root.after(500, refresh)

    root.bind("<Escape>", lambda _: (mon.stop.set(), root.destroy()))
    refresh()
    return root


def selfcheck():
    data = load_champion_data()
    tiers, over = tier_list.TIER_DATA, tier_list.NAME_OVERRIDES

    # gate-ul de mod: doar Mayhem porneste aplicatia
    assert logic.is_mayhem_gameflow({"gameData": {"queue": {"id": 2400}}})
    assert not logic.is_mayhem_gameflow({"gameData": {"queue": {"id": 450}}})
    assert not logic.is_mayhem_gameflow({})
    assert not logic.is_mayhem_gameflow(None)

    # bench-ul vine sub doua forme, in functie de versiunea de client
    assert logic.parse_bench({"benchChampions": [{"championId": 22},
                                                 {"championId": 51}]}) == [22, 51]
    assert logic.parse_bench({"benchChampionIds": [22, 51]}) == [22, 51]
    assert logic.parse_bench({"benchChampions": [{"championId": 0}, {}]}) == []
    assert logic.parse_bench({}) == []

    # campionul propriu se afla incrucisand cell id-ul local cu myTeam
    session = {"localPlayerCellId": 2,
               "myTeam": [{"cellId": 1, "championId": 22},
                          {"cellId": 2, "championId": 875}]}
    assert logic.get_local_player_champion_id(session) == 875
    assert logic.get_local_player_champion_id({"myTeam": []}) is None
    assert logic.get_local_player_champion_id({"localPlayerCellId": 9,
                                               "myTeam": [{"cellId": 1}]}) is None

    # tier: nume exact, nume prin override, nume necunoscut
    assert logic.get_tier("Sett", tiers, over) == "S+"
    assert logic.get_tier("Poro", tiers, over) == logic.UNRANKED
    assert logic.get_tier(None, tiers, over) == logic.UNRANKED
    assert logic.get_tier("X", {"Y": "S"}, {"X": "Y"}) == "S"

    # best pick: cel mai bun tier castiga, la egalitate primul din lista
    ids = {n: int(k) for k, n in data.items()}
    picks = [ids["Yorick"], ids["Sett"], ids["Aatrox"]]      # C, S+, D
    assert logic.best_pick(picks, data, tiers, over) == ids["Sett"]
    assert logic.best_pick([], data, tiers, over) is None
    tie = [ids["Jinx"], ids["Vayne"]]                        # ambii S+
    assert logic.best_pick(tie, data, tiers, over) == ids["Jinx"]
    # un campion fara tier nu trebuie sa castige in fata unuia clasat
    assert logic.best_pick([999999, ids["Aatrox"]], data, tiers, over) == ids["Aatrox"]

    # id-urile de varianta (60000 + id de baza) trebuie sa dea acelasi nume
    assert logic.resolve_champion_name(60001, data) == logic.resolve_champion_name(1, data)

    # BEST se compara si cu campionul propriu, nu doar intre cei de pe bench:
    # altfel te trimite la reroll chiar cand ai deja cel mai bun pick
    mon = Monitor(data)
    mon._read_session({"localPlayerCellId": 1,
                       "myTeam": [{"cellId": 1, "championId": ids["Sett"]}],
                       "benchChampionIds": [ids["Yorick"], ids["Aatrox"]]})
    assert mon.assigned["is_best"], mon.assigned          # Sett S+ bate C si D
    assert not any(e["is_best"] for e in mon.bench), mon.bench

    mon._read_session({"localPlayerCellId": 1,
                       "myTeam": [{"cellId": 1, "championId": ids["Aatrox"]}],
                       "benchChampionIds": [ids["Sett"], ids["Yorick"]]})
    assert not mon.assigned["is_best"]                    # Aatrox D pierde
    assert [e["name"] for e in mon.bench if e["is_best"]] == ["Sett"]

    # la tier egal ramane pe al tau: un reroll lateral nu castiga nimic
    mon._read_session({"localPlayerCellId": 1,
                       "myTeam": [{"cellId": 1, "championId": ids["Jinx"]}],
                       "benchChampionIds": [ids["Vayne"]]})   # ambii S+
    assert mon.assigned["is_best"] and not mon.bench[0]["is_best"]

    # reconciliere: fiecare campion din Data Dragon trebuie sa aiba tier.
    # daca u.gg ramane in urma cu campioni noi, aici se vede imediat.
    missing = sorted({n for n in data.values()
                      if logic.get_tier(n, tiers, over) == logic.UNRANKED})
    if missing:
        print(f"campioni fara tier ({len(missing)}): {', '.join(missing)}")
    assert len(missing) <= 3, f"prea multi campioni fara tier: {missing}"

    print(f"selfcheck OK ({len(data)} id-uri, {len(tiers)} campioni clasati)")


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    mon = Monitor(load_champion_data())
    threading.Thread(target=mon.run, daemon=True).start()
    build_ui(mon).mainloop()
    mon.stop.set()


if __name__ == "__main__":
    main()
