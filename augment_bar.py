"""Banda de tier care apare deasupra cardurilor de augment, doar in oferta.

Separata de panoul principal pentru ca are alt rost: aici te uiti doua
secunde, cat alegi, apoi dispare. N-are sens sa ocupe permanent loc in
panoul care sta mereu pe ecran.

Pozitia se calculeaza din zona in care apar cardurile (ocr_augments.
OFFER_REGION), deci se muta singura la alta rezolutie. Cele trei carduri
sunt centrate la 1/6, 3/6 si 5/6 din latimea zonei -- verificat pe o captura
reala de oferta.
"""

import tkinter as tk

ABOVE_CARDS = 64          # cat de sus fata de marginea de sus a cardurilor
BG = "#010a13"
SCALE = 1.0               # setat de app.py din DPI-ul ecranului


class PinBar:
    """Insigne de tier agatate deasupra unor puncte de pe ecran (cardurile de
    campion din champ select). Cate o fereastra mica per insigna, la pozitia
    exacta a textului citit prin OCR."""

    def __init__(self, root, colors, fg_colors, unknown, pix_font, mono_font):
        self.root, self.colors, self.fg_colors, self.unknown = root, colors, fg_colors, unknown
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
            bg = self.colors.get(p["tier"], self.unknown[0])
            fg = self.fg_colors.get(p["tier"], self.unknown[1])
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=BG)
            box = tk.Frame(win, bg=bg)
            box.pack()
            if p.get("is_best"):
                tk.Label(box, text="BEST", bg=bg, fg=fg, font=self.pix(7)).pack(padx=8, pady=(4, 0))
            tk.Label(box, text=p["tier"], bg=bg, fg=fg, font=self.pix(11)).pack(
                padx=10, pady=(0 if p.get("is_best") else 4, 0))
            tk.Label(box, text=p["name"][:20], bg=bg, fg=fg,
                     font=self.mono(9, "bold")).pack(padx=8, pady=(0, 4))
            win.update_idletasks()
            x = int(p["cx"] - win.winfo_width() / 2)
            y = max(0, int(p["y"] - win.winfo_height() - 8 * SCALE))
            win.geometry(f"+{x}+{y}")
            win.attributes("-alpha", 0.9)
            self.wins.append(win)
        self._key = key


class PinBar:
    """Insigne de tier agatate deasupra unor puncte de pe ecran (cardurile de
    campion din champ select). Cate o fereastra mica per insigna, la pozitia
    exacta a textului citit prin OCR."""

    def __init__(self, root, colors, fg_colors, unknown, pix_font, mono_font):
        self.root, self.colors, self.fg_colors, self.unknown = root, colors, fg_colors, unknown
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
            bg = self.colors.get(p["tier"], self.unknown[0])
            fg = self.fg_colors.get(p["tier"], self.unknown[1])
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=BG)
            box = tk.Frame(win, bg=bg)
            box.pack()
            if p.get("is_best"):
                tk.Label(box, text="BEST", bg=bg, fg=fg, font=self.pix(7)).pack(padx=8, pady=(4, 0))
            tk.Label(box, text=p["tier"], bg=bg, fg=fg, font=self.pix(11)).pack(
                padx=10, pady=(0 if p.get("is_best") else 4, 0))
            tk.Label(box, text=p["name"][:20], bg=bg, fg=fg,
                     font=self.mono(9, "bold")).pack(padx=8, pady=(0, 4))
            win.update_idletasks()
            x = int(p["cx"] - win.winfo_width() / 2)
            y = max(0, int(p["y"] - win.winfo_height() - 8 * SCALE))
            win.geometry(f"+{x}+{y}")
            win.attributes("-alpha", 0.9)
            self.wins.append(win)
        self._key = key


class PinBar:
    """Insigne de tier agatate deasupra unor puncte de pe ecran (cardurile de
    campion din champ select). Cate o fereastra mica per insigna, la pozitia
    exacta a textului citit prin OCR."""

    def __init__(self, root, colors, fg_colors, unknown, pix_font, mono_font):
        self.root, self.colors, self.fg_colors, self.unknown = root, colors, fg_colors, unknown
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
            bg = self.colors.get(p["tier"], self.unknown[0])
            fg = self.fg_colors.get(p["tier"], self.unknown[1])
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=BG)
            box = tk.Frame(win, bg=bg)
            box.pack()
            if p.get("is_best"):
                tk.Label(box, text="BEST", bg=bg, fg=fg, font=self.pix(7)).pack(padx=8, pady=(4, 0))
            tk.Label(box, text=p["tier"], bg=bg, fg=fg, font=self.pix(11)).pack(
                padx=10, pady=(0 if p.get("is_best") else 4, 0))
            tk.Label(box, text=p["name"][:20], bg=bg, fg=fg,
                     font=self.mono(9, "bold")).pack(padx=8, pady=(0, 4))
            win.update_idletasks()
            x = int(p["cx"] - win.winfo_width() / 2)
            y = max(0, int(p["y"] - win.winfo_height() - 8 * SCALE))
            win.geometry(f"+{x}+{y}")
            win.attributes("-alpha", 0.9)
            self.wins.append(win)
        self._key = key


class AugmentBar:
    """Cate o insigna de tier deasupra fiecarui card. Se arata/ascunde singura."""

    def __init__(self, root, colors, fg_colors, unknown, pix_font, mono_font,
                 on_pick=None):
        self.root = root
        self.colors = colors
        self.fg_colors = fg_colors
        self.unknown = unknown
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
        """augments: [{name, tier, is_best}]. region: (l, t, r, b) al cardurilor."""
        key = tuple((a["name"], a["tier"], a.get("is_best")) for a in augments)
        if key == self._key and self.win is not None:
            return          # deja pe ecran; n-o recream la fiecare ciclu
        self.hide()
        if not augments:
            return

        left, top, right, _ = region
        width = right - left
        col = width // 3

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BG)

        row = tk.Frame(self.win, bg=BG)
        row.pack()

        # trei coloane de latime egala cu cea a cardurilor, ca fiecare insigna
        # sa cada exact deasupra cardului ei
        for i, aug in enumerate(augments[:3]):
            tier = aug["tier"]
            bg = self.colors.get(tier, self.unknown[0])
            fg = self.fg_colors.get(tier, self.unknown[1])

            cell = tk.Frame(row, bg=BG, width=col)
            cell.grid(row=0, column=i, sticky="n")
            cell.grid_propagate(False)

            box = tk.Frame(cell, bg=bg)
            box.place(relx=0.5, rely=0, anchor="n")
            if aug.get("is_best"):
                tk.Label(box, text="BEST", bg=bg, fg=fg,
                         font=self.pix(7)).pack(padx=8, pady=(5, 0))
            tk.Label(box, text=tier, bg=bg, fg=fg,
                     font=self.pix(11)).pack(padx=10, pady=(0 if aug.get("is_best") else 5, 2))
            tk.Label(box, text=aug["name"][:22], bg=bg, fg=fg,
                     font=self.mono(9, "bold")).pack(padx=8, pady=(0, 5 if not aug.get("note") else 0))
            if aug.get("note"):
                # context scurt sub nume ("pentru Katarina . campion AP")
                tk.Label(box, text=aug["note"][:30], bg=bg, fg=fg,
                         font=self.mono(8)).pack(padx=8, pady=(0, 5))

            # click pe insigna = "pe asta l-am luat", ca sa putem impinge in
            # build itemul cerut de el ("Upgrade Zhonya's" -> Zhonya's)
            if self.on_pick is not None:
                name = aug["name"]
                for w in (box,) + tuple(box.winfo_children()):
                    w.bind("<Button-1>", lambda _e, n=name: self.on_pick(n))
                    w.configure(cursor="hand2")

            # inaltimea reala a lui box (BEST inclus, daca e cazul) -- fara
            # asta cell.height ramane pe valoarea implicita si box e taiat
            box.update_idletasks()
            cell.configure(height=box.winfo_reqheight())

        self.win.update_idletasks()
        x = left + width // 2 - self.win.winfo_width() // 2
        y = max(0, top - int(ABOVE_CARDS * SCALE))
        self.win.geometry(f"+{int(x)}+{int(y)}")
        self.win.attributes("-alpha", 0.88)
        self._key = key
