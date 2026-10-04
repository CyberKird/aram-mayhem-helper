"""Insignele de tier care apar deasupra cardurilor: oferta de augment, Stat
Anvil si cartile din champ select.

Separate de panoul principal pentru ca au alt rost: aici te uiti doua
secunde, cat alegi, apoi dispar. N-are sens sa ocupe permanent loc in
panoul care sta mereu pe ecran.

Arata ca interfata jocului, nu ca o eticheta lipita peste ea: fond bleumarin
inchis, chenar auriu (dublu pe alegerea buna), tier-ul colorat ca text si
numele in crem, ca in tooltip-urile din League.
"""

import tkinter as tk

ABOVE_CARDS = 64          # cat de sus fata de marginea de sus a cardurilor
BG = "#010a13"            # fondul HUD-ului League
FILL = "#0a1428"          # interiorul tooltip-urilor din joc
LINE = "#785a28"          # auriu inchis
GOLD = "#c8aa6e"          # auriu deschis, chenarul alegerii bune
CREAM = "#f0e6d2"
DIM = "#a09b8c"
HEXTECH = "#0ac8b9"
SCALE = 1.0               # setat de app.py din DPI-ul ecranului


def _badge(parent, tier, color, name, pix, mono, is_best=False, note=None):
    """O insigna in stilul jocului; intoarce frame-ul exterior."""
    edge = tk.Frame(parent, bg=GOLD if is_best else LINE)
    gap = tk.Frame(edge, bg=BG)
    gap.pack(padx=2 if is_best else 1, pady=2 if is_best else 1)
    box = tk.Frame(gap, bg=FILL)
    box.pack(padx=1 if is_best else 0, pady=1 if is_best else 0)
    if is_best:
        tk.Label(box, text="BEST", bg=FILL, fg=HEXTECH, font=pix(6)).pack(padx=10, pady=(4, 0))
    tk.Label(box, text=tier, bg=FILL, fg=color, font=pix(12)).pack(
        padx=12, pady=(0 if is_best else 4, 0))
    tk.Label(box, text=name[:22], bg=FILL, fg=CREAM, font=mono(9, "bold")).pack(
        padx=10, pady=(0, 0 if note else 5))
    if note:
        # context scurt sub nume ("Katarina . campion AP")
        tk.Label(box, text=note[:30], bg=FILL, fg=DIM, font=mono(8)).pack(padx=10, pady=(0, 5))
    return edge


def _overlay(root):
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=BG)
    return win


class PinBar:
    """Insigne de tier agatate deasupra unor puncte de pe ecran (cardurile de
    campion din champ select). Cate o fereastra mica per insigna, la pozitia
    exacta a textului citit prin OCR."""

    def __init__(self, root, colors, unknown, pix_font, mono_font):
        self.root, self.colors, self.unknown = root, colors, unknown
        self.pix, self.mono = pix_font, mono_font
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
            _badge(win, p["tier"], self.colors.get(p["tier"], self.unknown), p["name"],
                   self.pix, self.mono, p.get("is_best")).pack()
            win.update_idletasks()
            x = int(p["cx"] - win.winfo_width() / 2)
            y = max(0, int(p["y"] - win.winfo_height() - 8 * SCALE))
            win.geometry(f"+{x}+{y}")
            win.attributes("-alpha", 0.94)
            self.wins.append(win)
        self._key = key


class AugmentBar:
    """Cate o insigna de tier deasupra fiecarui card. Se arata/ascunde singura."""

    def __init__(self, root, colors, unknown, pix_font, mono_font, on_pick=None):
        self.root = root
        self.colors = colors
        self.unknown = unknown        # culoarea tier-ului necunoscut
        self.pix = pix_font
        self.mono = mono_font
        # apelat cu numele augmentului cand dai click pe insigna lui: singurul
        # mod sigur de a sti ce ai ales (Riot nu expune alegerea nicaieri)
        self.on_pick = on_pick
        self.win = None
        self._key = None

    def hide(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None
        self._key = None

    def show(self, augments, region):
        """augments: [{name, tier, is_best, note}]. region: (l, t, r, b) al cardurilor."""
        key = tuple((a["name"], a["tier"], a.get("is_best")) for a in augments)
        if key == self._key and self.win is not None:
            return          # deja pe ecran; n-o recream la fiecare ciclu
        self.hide()
        if not augments:
            return

        left, top, right, _ = region
        width = right - left
        col = width // 3

        self.win = _overlay(self.root)
        # fondul ferestrei devine transparent: intre insigne se vede jocul
        self.win.configure(bg="#ff00fe")
        self.win.attributes("-transparentcolor", "#ff00fe")
        row = tk.Frame(self.win, bg="#ff00fe")
        row.pack()

        # trei coloane de latime egala cu cea a cardurilor, ca fiecare insigna
        # sa cada exact deasupra cardului ei
        for i, aug in enumerate(augments[:3]):
            cell = tk.Frame(row, bg="#ff00fe", width=col)
            cell.grid(row=0, column=i, sticky="n")
            cell.grid_propagate(False)

            box = _badge(cell, aug["tier"], self.colors.get(aug["tier"], self.unknown),
                         aug["name"], self.pix, self.mono, aug.get("is_best"), aug.get("note"))
            box.place(relx=0.5, rely=0, anchor="n")

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

            # inaltimea reala a insignei (BEST inclus) -- fara asta cell.height
            # ramane pe valoarea implicita si insigna e taiata
            box.update_idletasks()
            cell.configure(height=box.winfo_reqheight())

        self.win.update_idletasks()
        x = left + width // 2 - self.win.winfo_width() // 2
        y = max(0, top - int(ABOVE_CARDS * SCALE))
        self.win.geometry(f"+{int(x)}+{int(y)}")
        self.win.attributes("-alpha", 0.94)
        self._key = key
