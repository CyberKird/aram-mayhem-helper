"""Insignele de tier de pe carduri: oferta de augment, Stat Anvil si cartile
din champ select.

Separate de panoul principal pentru ca au alt rost: aici te uiti doua
secunde, cat alegi, apoi dispar.

Arata ca o piesa a cardului, nu ca o eticheta lipita peste joc: o insigna mica
in stilul HUD-ului (fond teal inchis, chenar auriu, dublu pe alegerea buna),
asezata pe marginea de sus a cardului, centrata pe el. Doar tier-ul si BEST:
numele e deja scris pe card. Marimea vine din latimea cardului, deci arata la
fel la orice rezolutie.
"""

import tkinter as tk

FILL = "#0f2428"          # interiorul panourilor din HUD
LINE = "#a3874f"          # firul auriu-bronz al chenarelor din HUD
GOLD = "#f0d68c"          # auriul aprins al alegerii bune
HEXTECH = "#0ac8b9"
KEY = "#ff00fe"           # culoarea facuta transparenta: in jurul insignei se vede jocul
SCALE = 1.0               # setat de app.py din DPI-ul ecranului
CARD_SPACING_1080 = 378   # distanta dintre centrele cardurilor la 1080p (0.35 * 1080)


def _badge(parent, tier, color, fonts, k, is_best=False):
    """O insigna: tier-ul colorat, cu BEST deasupra pe alegerea buna."""
    heading = fonts[0]
    edge = tk.Frame(parent, bg=GOLD if is_best else LINE)
    box = tk.Frame(edge, bg=FILL)
    w = max(1, round(2 * k)) if is_best else max(1, round(k))
    box.pack(padx=w, pady=w)
    if is_best:
        tk.Label(box, text="BEST", bg=FILL, fg=HEXTECH,
                 font=(heading, max(6, round(7 * k)), "bold")).pack(
            padx=round(8 * k), pady=(round(3 * k), 0))
    tk.Label(box, text=tier, bg=FILL, fg=color,
             font=(heading, max(8, round(15 * k)), "bold")).pack(
        padx=round(10 * k), pady=(0 if is_best else round(3 * k), round(3 * k)))
    return edge


def _overlay(root):
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=KEY)
    win.attributes("-transparentcolor", KEY)
    return win


class PinBar:
    """Insigne de tier agatate deasupra unor puncte de pe ecran (cardurile de
    campion din champ select). Cate o fereastra mica per insigna, la pozitia
    exacta a textului citit prin OCR."""

    def __init__(self, root, colors, unknown, fonts):
        self.root, self.colors, self.unknown, self.fonts = root, colors, unknown, fonts
        self.wins = []
        self._key = None

    def hide(self):
        for w in self.wins:
            w.destroy()
        self.wins = []
        self._key = None

    def show(self, pins):
        """pins: [{name, tier, is_best, cx, y}] cu coordonate de ecran."""
        key = tuple((p["name"], p["tier"], p.get("is_best"), int(p["cx"]), int(p["y"]))
                    for p in pins)
        if key == self._key:
            return
        self.hide()
        for p in pins:
            win = _overlay(self.root)
            _badge(win, p["tier"], self.colors.get(p["tier"], self.unknown), self.fonts,
                   SCALE, p.get("is_best")).pack()
            win.update_idletasks()
            x = int(p["cx"] - win.winfo_width() / 2)
            y = max(0, int(p["y"] - win.winfo_height() - 8 * SCALE))
            win.geometry(f"+{x}+{y}")
            self.wins.append(win)
        self._key = key


class AugmentBar:
    """Cate o insigna de tier pe fiecare card. Se arata/ascunde singura."""

    def __init__(self, root, colors, unknown, fonts, on_pick=None):
        self.root = root
        self.colors = colors
        self.unknown = unknown        # culoarea tier-ului necunoscut
        self.fonts = fonts            # (familie titluri, familie text)
        # apelat cu numele augmentului cand dai click pe insigna lui: singurul
        # mod sigur de a sti ce ai ales (Riot nu expune alegerea nicaieri)
        self.on_pick = on_pick
        self.wins = []
        self._key = None

    def hide(self):
        for w in self.wins:
            w.destroy()
        self.wins = []
        self._key = None

    def show(self, augments, region):
        """augments: [{name, tier, is_best, slot}]. region: (l, t, r, b), cu t =
        marginea de sus a cardurilor si l..r = cele 3 coloane de carduri."""
        key = (tuple((a["name"], a["tier"], a.get("is_best"), a.get("slot")) for a in augments),
               tuple(region))
        if key == self._key and self.wins:
            return          # deja pe ecran; n-o recream la fiecare ciclu
        self.hide()
        if not augments:
            return

        left, top, right, _ = region
        col = (right - left) / 3
        k = col / CARD_SPACING_1080

        taken = set()
        for i, aug in enumerate(augments[:3]):
            # coloana cardului pe care a fost citit numele (slot), nu ordinea
            # listei: altfel un tier ajungea peste alt card
            slot = aug.get("slot")
            if slot not in (0, 1, 2) or slot in taken:
                slot = next(c for c in (i, 0, 1, 2) if c not in taken)
            taken.add(slot)

            win = _overlay(self.root)
            box = _badge(win, aug["tier"], self.colors.get(aug["tier"], self.unknown),
                         self.fonts, k, aug.get("is_best"))
            box.pack()
            # click pe insigna = "pe asta l-am luat", ca sa putem impinge in
            # build itemul cerut de el ("Upgrade Zhonya's" -> Zhonya's)
            if self.on_pick is not None:
                name = aug["name"]
                stack = [box]
                while stack:
                    w = stack.pop()
                    w.bind("<Button-1>", lambda _e, n=name: self.on_pick(n))
                    w.configure(cursor="hand2")
                    stack.extend(w.winfo_children())
            win.update_idletasks()
            # centrata pe card, calare pe marginea lui de sus
            cx = left + col * (slot + 0.5)
            win.geometry(f"+{int(cx - win.winfo_width() / 2)}+"
                         f"{max(0, int(top - win.winfo_height() / 2))}")
            self.wins.append(win)
        self._key = key
