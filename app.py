"""ARAM Mayhem helper: o singura aplicatie, detecteaza singura faza jocului.

Ruleaza ambele monitoare din spate (champ select prin LCU, roster+build+
augmente in joc prin Live Client Data + OCR) si arata o singura fereastra,
care comuta automat intre cele doua vederi dupa faza in care esti -- fara
niciun switch manual. Nu reimplementeaza logica: importa direct modulele din
lcu-app/ si ingame-app/ (fiecare ramane si utilizabil separat, pentru debug).

UI-ul e tkinter simplu, nu customtkinter: colturile ascutite sunt exact ce
vrea estetica pixel, si scapam de bug-ul din customtkinter 6.0.0 care lasa
ferestrele pornite ascunse blocate ascunse pentru totdeauna.

    python app.py              # porneste aplicatia unificata
    python app.py --selfcheck  # ruleaza selfcheck-ul ambelor module, fara joc
"""

import ctypes
import importlib.util
import pathlib
import sys
import threading
import tkinter as tk

import augment_bar
import hotkey
import settings as settings_mod

HOTKEY_LABEL = "CTRL+ALT+Z"

# Cate itemi din build aratam. Tot build-ul insemna 6 randuri din care 4 erau
# deja cumparate sau prea departe ca sa conteze acum.
NEXT_ITEMS = 3

# Fereastra isi ia inaltimea din continut, nu dintr-o valoare fixa. Plafonul
# exista doar ca sa nu creasca peste ecran daca apare tot deodata.
MAX_HEIGHT = 620

# Latimi de incadrare pentru textul verde de motiv. Fontul pixel e lat: un
# motiv de ~50 de caractere masoara 450px, mult peste cat ramane dupa iconita
# si marginile ferestrei de 372px. Fara ele, textul se taia fara niciun semn.
REASON_WRAP = 250     # rand cu o singura iconita in fata (2 randuri de text)
BOOTS_WRAP = 190      # randul de cizme are doua iconite plus sageata

# In exe-ul distribuit (PyInstaller, onefile), codul si datele se extrag
# intr-un folder temporar la fiecare pornire -- ROOT trebuie sa arate acolo,
# nu la __file__, care in modul "frozen" nu mai indica locul corect. Pentru
# fisiere care trebuie sa supravietuiasca inchiderii (jurnalul de erori),
# folosim in schimb folderul exe-ului propriu-zis.
if getattr(sys, "frozen", False):
    ROOT = pathlib.Path(sys._MEIPASS)
    LOG_DIR = pathlib.Path(sys.executable).parent
else:
    ROOT = pathlib.Path(__file__).parent
    LOG_DIR = ROOT

ICONS = ROOT / "ingame-app" / "data" / "icons"
FONTS = ROOT / "ingame-app" / "data" / "fonts"

BG = "#0b0b0b"
LINE = "#ffffff"
GREEN = "#a4e82c"
DIM = "#6f7d66"
TEXT = "#e8e8e8"
CARD = "#121512"

TIER_COLORS = {"S+": "#ff4655", "S": "#ff9a3c", "A": "#ffd166",
               "B": "#8ac926", "C": "#4a9de0", "D": "#6b7280"}
TIER_FG = {"S+": "#ffffff", "S": "#2b1400", "A": "#3a2c00",
           "B": "#182b00", "C": "#04203a", "D": "#ffffff"}
UNKNOWN_TIER = ("#2a2f28", "#7e8c76")

_icon_cache = {}


def _load_page(name, folder):
    """Incarca <folder>/app.py sub un nume propriu (ambele se numesc 'app.py',
    deci un import normal ar coliziona). Adauga folderul in sys.path ca
    submodulele lui (ex. mayhem_logic, live_client) sa se gaseasca."""
    folder_path = ROOT / folder
    sys.path.insert(0, str(folder_path))
    spec = importlib.util.spec_from_file_location(name, folder_path / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_pixel_font():
    """Inregistreaza fontul pixel doar pentru procesul asta si da familia lui.

    FR_PRIVATE = nu-l instaleaza in sistem, nu apare in alte programe. Trebuie
    apelat INAINTE de tk.Tk(), altfel Tk nu-l vede -- isi enumera fonturile la
    pornire. Daca fisierul lipseste, cadem pe un mono care exista peste tot.
    """
    ttf = FONTS / "PressStart2P-Regular.ttf"
    if ttf.exists() and sys.platform.startswith("win"):
        FR_PRIVATE = 0x10
        if ctypes.windll.gdi32.AddFontResourceExW(str(ttf), FR_PRIVATE, 0):
            return "Press Start 2P"
    return "Consolas"


def icon(kind, name, size=30):
    """Iconita oficiala, scalata cu NEAREST ca sa ramana pixelata.

    kind: "items" | "champions" | "augments". None daca n-avem fisierul
    (patch nou, nume diferit intre u.gg si datele Riot) -- apelantul cade
    atunci pe un placeholder, nu crapa.
    """
    from build_icons import slug   # aceeasi regula de nume ca la descarcare

    key = (kind, name, size)
    if key in _icon_cache:
        return _icon_cache[key]

    path = ICONS / kind / f"{slug(name)}.png"
    if not path.exists():
        _icon_cache[key] = None
        return None

    from PIL import Image, ImageTk
    img = Image.open(path).convert("RGBA").resize((size, size), Image.NEAREST)
    photo = ImageTk.PhotoImage(img)
    _icon_cache[key] = photo      # referinta vie: Tk nu tine imaginile singur
    return photo


def build_ui(lcu, lcu_mon, ingame, ingame_mon):
    counts = {
        "builds": len(list((ROOT / "ingame-app" / "data" / "builds").glob("*.json"))),
        "champions": len(list((ICONS / "champions").glob("*.png"))),
        "augments": len(list((ICONS / "augments").glob("*.png"))),
    }
    anim = {"cells": [], "step": 0}
    augment_items = ingame.load_json("augment-items.json")
    augment_desc = ingame.load_json("augment-desc.json")
    item_desc = ingame.load_json("item-desc.json")
    settings = settings_mod.Settings(LOG_DIR / "settings.json")

    family = load_pixel_font()
    pix = lambda size, weight="normal": (family, size, weight)
    mono = lambda size, weight="normal": ("Consolas", size, weight)

    root = tk.Tk()
    root.title("ARAM Mayhem Helper")
    root.overrideredirect(True)      # desenam noi chenarul, ca in macheta
    root.attributes("-topmost", True)
    root.configure(bg=LINE)
    root.withdraw()

    width = 372
    x, y = settings.pos("panel", (root.winfo_screenwidth() - width - 28, 64))
    root.geometry(f"{width}x260+{int(x)}+{int(y)}")

    # chenarul de 1px: un frame exterior alb cu padding, peste care sta continutul
    shell = tk.Frame(root, bg=BG)
    shell.pack(fill="both", expand=True, padx=1, pady=1)

    # --- bara de titlu ---------------------------------------------------
    titlebar = tk.Frame(shell, bg=BG)
    titlebar.pack(fill="x", padx=8, pady=(7, 6))

    title = tk.Label(titlebar, text="ARAM MAYHEM", bg=BG, fg=LINE, font=pix(8))
    title.pack(side="left")

    close = tk.Label(titlebar, text="X", bg=BG, fg=LINE, font=pix(8),
                     cursor="hand2", padx=4)
    close.pack(side="right")
    minimize = tk.Label(titlebar, text="_", bg=BG, fg=LINE, font=pix(8), padx=4)
    minimize.pack(side="right")

    divider1 = tk.Frame(shell, bg=LINE, height=1)
    divider1.pack(fill="x")

    # --- randul de context (ce arata acum) -------------------------------
    subbar = tk.Frame(shell, bg=BG)
    subbar.pack(fill="x", padx=8, pady=5)
    context = tk.Label(subbar, text="ASTEPT JOCUL", bg=BG, fg=DIM,
                       font=pix(7), anchor="w")
    context.pack(side="left")

    divider2 = tk.Frame(shell, bg=LINE, height=1)
    divider2.pack(fill="x")

    # --- corpul ----------------------------------------------------------
    body = tk.Frame(shell, bg=BG)
    body.pack(fill="both", expand=True, padx=10, pady=8)

    # --- subsolul --------------------------------------------------------
    divider3 = tk.Frame(shell, bg=LINE, height=1)
    divider3.pack(fill="x")
    footer = tk.Frame(shell, bg=BG)
    footer.pack(fill="x", padx=8, pady=6)
    status_label = tk.Label(footer, text="", bg=BG, fg=DIM, font=pix(7),
                            anchor="w", justify="left", wraplength=340)
    status_label.pack(side="left")

    # piesele astea se ascund cand fereastra e "stransa" la bara de titlu.
    # NU folosim withdraw() pentru asta -- daca hotkey-ul nu ajunge (de ex.
    # blocat de un anticheat cand jocul e in prim-plan), o fereastra complet
    # ascunsa n-are cum sa mai fie adusa inapoi. Bara de titlu ramane mereu
    # pe ecran si mereu clickabila, indiferent ce se intampla cu hotkey-ul.
    collapsible = (divider1, subbar, divider2, body, divider3, footer)

    # mutarea ferestrei cu mouse-ul: fara bara nativa, o facem noi
    drag = {"x": 0, "y": 0}

    def press(e):
        drag["x"], drag["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def move(e):
        root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    for widget in (titlebar, title, subbar, context):
        widget.bind("<Button-1>", press)
        widget.bind("<B1-Motion>", move)

    # --- caramizile de continut ------------------------------------------

    # --- tooltip la hover -------------------------------------------------
    # O singura fereastra refolosita, nu una noua la fiecare hover: altfel
    # Tk ar acumula Toplevel-uri pe toata durata meciului.
    tip = {"win": None}

    def hide_tip(_=None):
        if tip["win"] is not None:
            tip["win"].destroy()
            tip["win"] = None

    def show_tip(widget, name):
        hide_tip()
        text = item_desc.get(name)
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=LINE)
        inner = tk.Frame(win, bg=BG)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=name, bg=BG, fg=TEXT, font=mono(13, "bold"),
                 anchor="w", justify="left").pack(fill="x", padx=8, pady=(6, 0))
        if text:
            tk.Label(inner, text=text, bg=BG, fg=DIM, font=mono(11),
                     anchor="w", justify="left",
                     wraplength=300).pack(fill="x", padx=8, pady=(4, 6))

        # asezat sub cursor, dar tras inapoi daca ar iesi din ecran -- pe
        # marginea din dreapta a monitorului, un tooltip ancorat la cursor
        # ar fi pe jumatate invizibil
        win.update_idletasks()
        x = widget.winfo_rootx() + widget.winfo_width() + 8
        y = widget.winfo_rooty()
        if x + win.winfo_width() > root.winfo_screenwidth():
            x = widget.winfo_rootx() - win.winfo_width() - 8
        if y + win.winfo_height() > root.winfo_screenheight():
            y = root.winfo_screenheight() - win.winfo_height() - 8
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        tip["win"] = win

    def attach_tip(widget, name):
        widget.bind("<Enter>", lambda _e, w=widget, n=name: show_tip(w, n))
        widget.bind("<Leave>", hide_tip)

    def section(text):
        # pady strans: cinci antete luau 85px din 499px de continut, adica
        # 17% din fereastra doar pentru etichete
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(6, 3))
        tk.Label(row, text=text, bg=BG, fg=GREEN, font=pix(7),
                 anchor="w").pack(side="left")
        tk.Frame(row, bg="#1e2a18", height=1).pack(side="left", fill="x",
                                                   expand=True, padx=(6, 0))

    def tier_badge(parent, tier):
        bg, fg = TIER_COLORS.get(tier), TIER_FG.get(tier)
        if bg is None:
            bg, fg = UNKNOWN_TIER
        return tk.Label(parent, text=tier, bg=bg, fg=fg, font=pix(8),
                        width=3, height=2)

    def tier_row(kind, entry, best_label=None):
        """Un campion sau un augment: iconita oficiala + insigna de tier."""
        is_best = entry.get("is_best")
        color = TIER_COLORS.get(entry["tier"], UNKNOWN_TIER[0])
        outer = tk.Frame(body, bg=color if is_best else CARD)
        outer.pack(fill="x", pady=2)
        row = tk.Frame(outer, bg=CARD)
        row.pack(fill="both", expand=True, padx=1, pady=1)

        photo = icon(kind, entry["name"], 28)
        if photo:
            tk.Label(row, image=photo, bg=CARD, bd=0).pack(side="left",
                                                           padx=(4, 0), pady=4)
        tier_badge(row, entry["tier"]).pack(side="left", padx=(6, 7), pady=4)

        texts = tk.Frame(row, bg=CARD)
        texts.pack(side="left", fill="x", expand=True, pady=4)
        tk.Label(texts, text=entry["name"], bg=CARD, fg=TEXT, font=mono(13, "bold"),
                 anchor="w").pack(fill="x")
        # unele augmente ("Upgrade Zhonya's") n-au sens decat daca chiar
        # cumperi itemul din spate -- se vede la momentul alegerii, nu dupa
        needs = augment_items.get(entry["name"])
        if needs:
            tk.Label(texts, text=f"CERE {needs.upper()}", bg=CARD, fg=GREEN,
                     font=pix(7), anchor="w").pack(fill="x", pady=(3, 0))

        # Fara tier (u.gg nu-l claseaza) aratam ce face, ca sa poti decide tu.
        # Nu inventam un rank: ar arata identic cu unul calculat din meciuri
        # reale, dar ar fi doar o parere.
        if entry["tier"] not in TIER_COLORS:
            what = augment_desc.get(entry["name"])
            tk.Label(texts, text=(what or "neclasat de u.gg")[:110], bg=CARD,
                     fg=DIM, font=mono(10), anchor="w", justify="left",
                     wraplength=250).pack(fill="x", pady=(2, 0))

        if is_best and best_label:
            tk.Label(row, text=best_label, bg=CARD, fg=color,
                     font=pix(7)).pack(side="right", padx=6)

    def icon_strip(entries):
        """Iconite una langa alta. Accepta si nume simple, si {item, owned}."""
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=2)
        for e in entries:
            name = e["item"] if isinstance(e, dict) else e
            owned = isinstance(e, dict) and e.get("owned")
            is_next = isinstance(e, dict) and e.get("next")
            # verde = urmatorul de cumparat, gri stins = deja al tau
            border = GREEN if is_next else ("#1b2016" if owned else "#2a3324")
            cell = tk.Frame(row, bg=border)
            cell.pack(side="left", padx=(0, 5))
            photo = icon("items", name, 34)
            if photo:
                lbl = tk.Label(cell, image=photo, bg=CARD, bd=0)
            else:
                lbl = tk.Label(cell, text=name[:3].upper(), bg=CARD, fg=DIM,
                               font=pix(7), width=5, height=3)
            lbl.pack(padx=2 if is_next else 1, pady=2 if is_next else 1)
            attach_tip(lbl, name)

    def item_row(entry):
        """Un item de cumparat: iconita + nume + motivul (daca exista).

        Accepta si intrari de core, care n-au cheia "reason" -- de aceea .get.
        """
        hot = bool(entry.get("reason"))
        owned = entry.get("owned")
        is_next = entry.get("next")
        outer = tk.Frame(body, bg=GREEN if (hot or is_next) else CARD)
        outer.pack(fill="x", pady=2)
        row = tk.Frame(outer, bg=CARD)
        row.pack(fill="both", expand=True, padx=1, pady=1)

        photo = icon("items", entry["item"], 30)
        if photo:
            ilbl = tk.Label(row, image=photo, bg=CARD, bd=0)
            ilbl.pack(side="left", padx=(4, 7), pady=4)
            attach_tip(ilbl, entry["item"])
        texts = tk.Frame(row, bg=CARD)
        texts.pack(side="left", fill="x", expand=True, pady=4)
        # itemul detinut se stinge: nu mai e o decizie, e istorie
        tk.Label(texts, text=entry["item"], bg=CARD, fg=DIM if owned else TEXT,
                 font=mono(13, "bold"), anchor="w").pack(fill="x")
        if hot:
            # wraplength obligatoriu: fontul pixel e lat, iar un motiv lung
            # ("inamicii se vindeca, nimeni la noi n-are anti-heal" = 400px)
            # nu incape pe un rand si se taia tacut la marginea ferestrei
            tk.Label(texts, text=entry["reason"].upper(), bg=CARD, fg=GREEN,
                     font=pix(7), anchor="w", justify="left",
                     wraplength=REASON_WRAP).pack(fill="x", pady=(3, 0))

        if owned:
            tk.Label(row, text="AI", bg=CARD, fg=DIM,
                     font=pix(7)).pack(side="right", padx=8)
        elif is_next:
            tk.Label(row, text="URMEAZA", bg=CARD, fg=GREEN,
                     font=pix(7)).pack(side="right", padx=8)

    def boots_row(advice):
        """Vinde cizmele -> ia asta. Apare doar la 6 itemi, nu mai devreme."""
        outer = tk.Frame(body, bg=GREEN)
        outer.pack(fill="x", pady=2)
        row = tk.Frame(outer, bg=CARD)
        row.pack(fill="both", expand=True, padx=1, pady=1)

        for name, tint in ((advice["sell"], "#3a2020"), (advice["buy"], CARD)):
            cell = tk.Frame(row, bg=tint)
            cell.pack(side="left", padx=(4, 0), pady=4)
            photo = icon("items", name, 28)
            if photo:
                blbl = tk.Label(cell, image=photo, bg=tint, bd=0)
                blbl.pack(padx=1, pady=1)
                attach_tip(blbl, name)
            if name == advice["sell"]:
                tk.Label(row, text="->", bg=CARD, fg=DIM,
                         font=mono(13, "bold")).pack(side="left", padx=5)

        texts = tk.Frame(row, bg=CARD)
        texts.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=4)
        tk.Label(texts, text=f"VINDE {advice['sell']}", bg=CARD, fg=DIM,
                 font=pix(7), anchor="w", justify="left",
                 wraplength=BOOTS_WRAP).pack(fill="x")
        tk.Label(texts, text=advice["buy"], bg=CARD, fg=TEXT,
                 font=mono(13, "bold"), anchor="w").pack(fill="x", pady=(2, 0))
        if advice["reason"]:
            tk.Label(texts, text=advice["reason"].upper(), bg=CARD, fg=GREEN,
                     font=pix(7), anchor="w", justify="left",
                     wraplength=BOOTS_WRAP).pack(fill="x", pady=(3, 0))

    def note(text, color=DIM):
        tk.Label(body, text=text, bg=BG, fg=color, font=mono(11), anchor="w",
                 justify="left", wraplength=330).pack(fill="x", pady=6)

    def summoner_row(names):
        """Cele doua spell-uri recomandate de u.gg, iconita + nume, unul langa altul."""
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=2)
        for name in names:
            cell = tk.Frame(row, bg="#2a3324")
            cell.pack(side="left", padx=(0, 8))
            inner = tk.Frame(cell, bg=CARD)
            inner.pack(padx=1, pady=1)
            photo = icon("summoners", name, 30)
            if photo:
                tk.Label(inner, image=photo, bg=CARD, bd=0).pack(side="left",
                                                                 padx=4, pady=4)
            tk.Label(inner, text=name, bg=CARD, fg=TEXT, font=mono(13, "bold")
                     ).pack(side="left", padx=(0, 8), pady=4)

    def state_row(label, value, ok):
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=BG, fg=DIM, font=mono(11),
                 anchor="w").pack(side="left")
        tk.Label(row, text=value, bg=BG, fg=GREEN if ok else "#9a6b6b",
                 font=mono(10, "bold"), anchor="e").pack(side="right")

    def waiting_bar():
        """Bara segmentata din macheta, ca semn ca aplicatia chiar traieste.

        Celulele sunt animate de animate(), care ruleaza continuu si le
        gaseste prin anim["cells"] -- nu redesenam tot corpul la fiecare
        cadru, ar fi risipa pentru o animatie de asteptare.
        """
        wrap = tk.Frame(body, bg="#1e2a18")
        wrap.pack(fill="x", pady=(2, 4))
        inner = tk.Frame(wrap, bg=BG, height=14)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        inner.pack_propagate(False)
        anim["cells"] = [tk.Frame(inner, bg=BG) for _ in range(16)]
        for cell in anim["cells"]:
            cell.pack(side="left", fill="both", expand=True, padx=1, pady=2)

    def animate():
        cells = [c for c in anim.get("cells", []) if c.winfo_exists()]
        if cells:
            anim["step"] = (anim["step"] + 1) % len(cells)
            for i, cell in enumerate(cells):
                lit = (i - anim["step"]) % len(cells) < 3
                cell.configure(bg=GREEN if lit else BG)
        root.after(110, animate)

    # --- cele trei vederi -------------------------------------------------

    def render_idle():
        title.configure(text="ARAM MAYHEM")
        context.configure(text="IDLE  ·  ASTEPT")

        client_up = lcu_mon.phase != "waiting_for_client"
        section("STARE")
        state_row("CLIENT LEAGUE", "PORNIT" if client_up else "OPRIT", client_up)
        state_row("MECI", "NU", False)

        section("ASTEPT")
        waiting_bar()
        note("Se umple singura cand intri in champ select de Mayhem "
             "sau cand incepe meciul.")

        section("DATE LOCALE")
        note(f"{counts['builds']} build-uri  ·  {counts['champions']} campioni"
             f"  ·  {counts['augments']} augmente")
        if lcu_mon.error:
            note(lcu_mon.error, "#c07a7a")

        section("SCURTATURA")
        note(f"{HOTKEY_LABEL} strange fereastra la bara de titlu. Daca nu "
             f"merge (unele anti-cheat-uri blocheaza taste globale cat "
             f"jocul e activ), click pe \"_\" din colt face acelasi lucru.")

    def render_champ_select():
        title.configure(text="ARAM MAYHEM")
        context.configure(text="CHAMP SELECT  ·  REROLL")
        if lcu_mon.assigned:
            section("CAMPIONUL TAU")
            tier_row("champions", lcu_mon.assigned, "BEST")

            build = ingame.load_cached(lcu_mon.assigned["name"])
            summoners = build.get("summoners") if build else None
            if summoners:
                section("SUMMONER SPELLS")
                summoner_row(summoners)
        if lcu_mon.bench:
            section("BENCH")
            for entry in lcu_mon.bench:
                tier_row("champions", entry, "BEST")
        if not lcu_mon.assigned and not lcu_mon.bench:
            note("se incarca...")

    def render_in_game():
        title.configure(text="ARAM MAYHEM")
        champ = (ingame_mon.roster or {}).get("local_champion") or "?"
        enemies = (ingame_mon.roster or {}).get("enemies") or []
        # inamicii stau in bara de context, nu intr-o sectiune proprie:
        # lista lor lua 38px, iar informatia o vezi oricum cu TAB in joc.
        # Ce conteaza cu adevarat -- cum schimba ei build-ul -- apare oricum
        # ca motiv verde langa itemi.
        context.configure(text=f"IN JOC  ·  {champ.upper()}"
                               + (f"  ·  VS {len(enemies)}" if enemies else ""))

        # Augmentele NU mai apar aici: au banda lor, care se ridica deasupra
        # cardurilor exact cand ai de ales. Aici ar fi fost tot timpul pe
        # ecran degeaba, si tot timpul in alt loc decat te uiti.

        rb = ingame_mon.resolved_build
        if rb:
            # Starting items conteaza doar la inceput. Din clipa in care ai
            # primul item de core, sectiunea e 53px de istorie.
            inceput = not any(c["owned"] for c in rb["core"])
            if inceput and rb.get("starting"):
                section("STARTING ITEMS")
                icon_strip(rb["starting"])

            # Doar ce URMEAZA sa cumperi, in ordine, nu tot build-ul. Cele
            # deja cumparate nu mai sunt o decizie, iar itemul 6 nu conteaza
            # cand esti la al doilea.
            ramase = [e for e in rb["core"] + rb["picks"] if not e["owned"]]
            if ramase:
                section("URMATOARELE" if len(ramase) > 1 else "URMATORUL")
                for entry in ramase[:NEXT_ITEMS]:
                    item_row(entry)
            elif rb["picks"]:
                section("BUILD COMPLET")
                icon_strip(rb["core"] + rb["picks"])

            boots = rb.get("boots")
            if boots:
                section("BUILD PLIN")
                boots_row(boots)

        if not ingame_mon.roster:
            note("se incarca...")

    # --- bucla de improspatare -------------------------------------------

    shown = {"view": None, "fingerprint": None}
    bar = augment_bar.AugmentBar(root, TIER_COLORS, TIER_FG, UNKNOWN_TIER, pix, mono)

    def active_view():
        if lcu_mon.phase == "in_mayhem_select":
            return "champ_select"
        if ingame_mon.phase == "in_game":
            return "in_game"
        return "idle"

    def fingerprint(view):
        if view == "champ_select":
            return (view,
                    lcu_mon.assigned and (lcu_mon.assigned["name"],
                                          lcu_mon.assigned["is_best"]),
                    tuple((e["name"], e["is_best"]) for e in lcu_mon.bench))
        if view == "in_game":
            picks = ingame_mon.resolved_build["picks"] if ingame_mon.resolved_build else []
            core = ingame_mon.resolved_build["core"] if ingame_mon.resolved_build else []
            return (view,
                    ingame_mon.roster and ingame_mon.roster.get("local_champion"),
                    ingame_mon.roster and tuple(ingame_mon.roster.get("enemies", [])),
                    tuple((c["item"], c["owned"], c["next"]) for c in core),
                    tuple((p["item"], p["reason"], p["owned"], p["next"]) for p in picks),
                    (ingame_mon.resolved_build or {}).get("boots") and
                    tuple((ingame_mon.resolved_build["boots"] or {}).values()),
                    tuple((a["name"], a["tier"]) for a in ingame_mon.augments),
                    ingame_mon.status)
        # idle: doar starea monitoarelor. Pasul animatiei NU intra aici --
        # altfel am redesena tot corpul de 9 ori pe secunda.
        return (view, lcu_mon.phase, ingame_mon.phase, lcu_mon.error)

    render = {"idle": render_idle, "champ_select": render_champ_select,
              "in_game": render_in_game}

    # pack kwargs originale, ca sa putem re-atasa exact la fel dupa pack_forget
    COLLAPSIBLE_PACK = [
        (divider1, {"fill": "x"}),
        (subbar, {"fill": "x", "padx": 8, "pady": 5}),
        (divider2, {"fill": "x"}),
        (body, {"fill": "both", "expand": True, "padx": 10, "pady": 8}),
        (divider3, {"fill": "x"}),
        (footer, {"fill": "x", "padx": 8, "pady": 6}),
    ]

    collapsed = {"want": False, "applied": False}

    def toggle_collapsed():
        # ruleaza pe firul hotkey-ului, nu pe cel al Tk-ului -- doar o
        # atribuire simpla de bool, restul se rezolva la urmatorul refresh()
        collapsed["want"] = not collapsed["want"]

    def refresh():
        if collapsed["want"] != collapsed["applied"]:
            for w, kw in COLLAPSIBLE_PACK:
                w.pack_forget() if collapsed["want"] else w.pack(**kw)
            collapsed["applied"] = collapsed["want"]
            # update_idletasks() INAINTE de a citi inaltimea: fara el, Tk
            # raporteaza dimensiunea "naturala" pe layout-ul vechi (dinaintea
            # pack_forget), iar fereastra ramane cu un dreptunghi gol dedesubt.
            # Latimea ramane fixa (width) -- doar geometry("") ar lasa-o sa se
            # ingusteze si ar muta "_"/"X" in alta parte la fiecare apasare
            root.update_idletasks()
            root.geometry(f"{width}x{root.winfo_reqheight()}")

        # Banda de augmente traieste separat de panou: apare deasupra
        # cardurilor cand ai de ales si dispare imediat dupa. O actualizam
        # chiar si cand panoul e strans -- exact atunci ai nevoie de ea.
        try:
            import ocr_augments as _ocr
            import win32gui as _w32
            hwnd = _ocr.find_game_window()
            if (ingame_mon.augments and hwnd
                    and _w32.GetForegroundWindow() == hwnd):
                bar.show(ingame_mon.augments, _ocr.offer_region(_w32.GetWindowRect(hwnd)))
            else:
                bar.hide()
        except Exception:
            bar.hide()   # banda e un plus; daca da gres, nu opreste aplicatia

        if collapsed["want"]:
            root.after(500, refresh)
            return

        view = active_view()
        fp = fingerprint(view)
        if view != shown["view"] or fp != shown["fingerprint"]:
            shown["view"] = view
            shown["fingerprint"] = fp
            # tooltip-ul e ancorat de un widget care tocmai dispare: fara
            # asta ar ramane agatat pe ecran dupa redesenare
            hide_tip()
            for w in body.winfo_children():
                w.destroy()
            anim["cells"] = []    # celulele tocmai au fost distruse
            render[view]()
            status_label.configure(text=(ingame_mon.status or "").upper())

            fit_height()

        root.after(500, refresh)

    def fit_height():
        """Inaltimea urmeaza continutul, nu o valoare fixa.

        Apelata si dupa mesajele care apar mai tarziu (avertismentul de
        hotkey): altfel fereastra ramane dimensionata pe continutul de
        dinainte si taie ultimul rand.
        """
        root.update_idletasks()
        root.geometry(f"{width}x{min(root.winfo_reqheight(), MAX_HEIGHT)}")

    def close_app():
        lcu_mon.stop.set()
        ingame_mon.stop.set()
        bar.hide()          # banda e alta fereastra; altfel ramane pe ecran
        root.destroy()

    close.bind("<Button-1>", lambda _: close_app())
    minimize.bind("<Button-1>", lambda _: toggle_collapsed())
    root.bind("<Escape>", lambda _: close_app())
    root.protocol("WM_DELETE_WINDOW", close_app)

    # pozitia ferestrei se retine intre sesiuni: o asezi o data unde vrei
    def remember_pos(_=None):
        settings.set_pos("panel", root.winfo_x(), root.winfo_y())

    for widget in (titlebar, title, subbar, context):
        widget.bind("<ButtonRelease-1>", remember_pos, add="+")

    listener = hotkey.HotkeyListener(toggle_collapsed, modifiers=hotkey.MOD_CONTROL | hotkey.MOD_ALT,
                                     vk=hotkey.VK["Z"])
    listener.start()
    root._hotkey_listener = listener   # referinta vie, altfel firul poate fi colectat

    def check_hotkey_registered():
        if listener.registered is False:
            status_label.configure(
                text=f"{HOTKEY_LABEL} ocupat -- foloseste \"_\" din titlu")
            fit_height()
        elif listener.registered is None:
            root.after(300, check_hotkey_registered)   # inca n-a apucat sa se inregistreze
    root.after(300, check_hotkey_registered)

    root.deiconify()
    refresh()
    animate()
    return root


def selfcheck():
    lcu = _load_page("lcu_page", "lcu-app")
    ingame = _load_page("ingame_page", "ingame-app")
    lcu.selfcheck()
    ingame.selfcheck()

    # iconitele: ce afiseaza UI-ul trebuie sa aiba fisier pe disc, altfel
    # cade tacut pe placeholder. Verificam toate cele trei feluri.
    import json
    from build_icons import slug

    def have(kind, name):
        return (ICONS / kind / f"{slug(name)}.png").exists()

    builds = [json.loads(p.read_text(encoding="utf-8"))
              for p in (ROOT / "ingame-app" / "data" / "builds").glob("*.json")]

    missing = set()
    for build in builds:
        # "starting" e inclus: de cand il afisam, o iconita lipsa acolo se
        # vede la fel de urat ca una lipsa din core
        for key in ("starting", "core", "fourth", "fifth", "sixth"):
            for name in build.get(key) or []:
                if not have("items", name):
                    missing.add(f"item: {name}")

    champions = json.loads((ROOT / "ingame-app" / "data" / "champion-tags.json")
                           .read_text(encoding="utf-8"))
    missing |= {f"campion: {n}" for n in champions if not have("champions", n)}

    assert not missing, f"iconite lipsa (ruleaza build_icons.py): {sorted(missing)}"

    # summoner spells: fiecare build ar trebui sa aiba exact 2, cu iconita.
    # Nu ridicam asta la assert dur pentru campion: build_icons.py ruleaza
    # DUPA un rescrape, deci pe termen scurt (rescrape in curs, cache vechi)
    # e normal sa lipseasca -- raportam procentul, nu blocam pe el.
    with_summoners = sum(1 for b in builds if len(b.get("summoners") or []) == 2)
    summoner_names = {n for b in builds for n in (b.get("summoners") or [])}
    summoner_icons = sum(1 for n in summoner_names if have("summoners", n))

    # augmentele vin de la Riot, tier list-ul de la u.gg: numele pot diferi,
    # deci aici raportam acoperirea in loc sa cerem 100%
    import augment_tier
    tiers = json.loads((ROOT / "ingame-app" / "data" / "augments-global.json")
                       .read_text(encoding="utf-8"))
    names = augment_tier.flatten_names(tiers)   # aceeasi sursa ca OCR-ul
    covered = sum(1 for n in names if have("augments", n))
    assert covered >= len(names) * 0.9, \
        f"prea putine iconite de augment: {covered}/{len(names)}"

    counts = {k: len(list((ICONS / k).glob("*.png")))
              for k in ("items", "champions", "augments", "summoners")}
    print(f"selfcheck OK: iconite {counts}, "
          f"augmente acoperite {covered}/{len(names)}, "
          f"summoners {with_summoners}/{len(builds)} campioni "
          f"({summoner_icons}/{len(summoner_names)} iconite unice)")


def already_running():
    """True daca o alta instanta a legat deja portul-santinela.

    Cu o scurtatura in taskbar, dublu-click-ul devine usor de facut din
    greseala, iar doua instante inseamna doua fire de OCR care fotografiaza
    ecranul in acelasi timp -- exact ce nu vrem in timpul unui meci.
    """
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

    if already_running():
        return

    lcu = _load_page("lcu_page", "lcu-app")
    ingame = _load_page("ingame_page", "ingame-app")

    lcu_mon = lcu.Monitor(lcu.load_champion_data())
    threading.Thread(target=lcu_mon.run, daemon=True).start()

    ingame_mon = ingame.Monitor(
        ingame.load_json("champion-id-map.json"),
        ingame.load_json("champion-tags.json"),
        ingame.load_json("item-rules.json"),
        ingame.load_json("augments-global.json"),
        ingame.load_json("item-stats.json"),
    )
    ingame_mon.run()

    root = build_ui(lcu, lcu_mon, ingame, ingame_mon)
    root.mainloop()
    lcu_mon.stop.set()
    ingame_mon.stop.set()


if __name__ == "__main__":
    # exe-ul distribuit ruleaza fara consola (--windowed): fara asta, o
    # eroare neasteptata inseamna doar ca fereastra dispare, fara niciun
    # indiciu pentru cineva care nu are de unde sa stie ce s-a intamplat.
    try:
        main()
    except Exception:
        import traceback
        log = LOG_DIR / "eroare.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"ARAM Mayhem Helper a intampinat o eroare.\n\n"
                f"Detaliile sunt salvate in:\n{log}",
                "ARAM Mayhem Helper", 0x10)
        except Exception:
            pass
        raise
