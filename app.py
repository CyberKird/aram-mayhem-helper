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
import os
import importlib.util
import pathlib
import sys
import threading
import time
import tkinter as tk

import augment_bar
import bug_report
import champ_ocr
import data_sync
import hotkey
import hud_settings
import settings as settings_mod
import updater



def enable_dpi_awareness():
    """Coordonate in pixeli reali peste tot (Tk, mss, ferestrele jocului).

    Fara asta, pe un monitor 4K cu scalare 150% Tk lucra in coordonate logice
    iar mss in cele fizice; ele se amestecau abia cand mss isi activa singur
    awareness-ul, la prima captura. Rezultatul: banda de tier si panoul
    cadeau in alt loc decat zona citita. Apelat O DATA, INAINTE de tk.Tk().
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_window_icon(user32, hwnd):
    """Iconita ferestrei la rezolutia potrivita DPI-ului, direct din icon.ico.

    iconbitmap() din Tk alege o singura dimensiune si Windows o intinde
    (de-aia iesea neclara in taskbar). Aici cerem mare (256, redusa curat de
    shell) si mica (16 scalat cu DPI-ul), iar LoadImage ia cea mai buna
    intrare din fisier pentru fiecare.
    """
    path = ROOT / "icon.ico"
    if not path.exists():
        return
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                    ctypes.c_size_t, ctypes.c_void_p]
    for kind, size in ((1, 256), (0, max(16, round(16 * UI_SCALE)))):   # BIG, SMALL
        icon_handle = user32.LoadImageW(None, str(path), 1, size, size, 0x10)  # LR_LOADFROMFILE
        if icon_handle:
            user32.SendMessageW(hwnd, 0x0080, kind, icon_handle)       # WM_SETICON


def show_in_taskbar(root):
    """Buton in taskbar (si deci posibilitatea de pin) pentru o fereastra fara chenar.

    Cu overrideredirect Windows nu da niciun buton in taskbar. Stilul
    WS_EX_APPWINDOW il cere explicit, iar scoaterea lui WS_EX_TOOLWINDOW il
    face sa nu mai fie tratata ca paleta. Stilul se aplica doar la urmatoarea
    afisare, de-asta ascundem si reafisam fereastra.
    """
    try:
        user32 = ctypes.windll.user32
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id())
        GWL_EXSTYLE, APPWINDOW, TOOLWINDOW = -20, 0x00040000, 0x00000080
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~TOOLWINDOW) | APPWINDOW)
        set_window_icon(user32, hwnd)
        root.withdraw()
        root.after(30, root.deiconify)
    except Exception:
        pass        # fara buton in taskbar, dar aplicatia merge


# 1.0 la 96 DPI (100%); 1.5 la 150% etc. Setat in build_ui dupa ce exista Tk.
# Fonturile (in puncte) se scaleaza singure; pixelii fixi de mai jos nu.
UI_SCALE = 1.0

# Factor de potrivire cand panoul sta lipit de HUD: marimea lui urmeaza inaltimea
# jocului, ca sa incapa intre HUD si minimap la orice rezolutie. 1.0 in rest.
FIT = 1.0

# Locul liber dintre HUD-ul de jos si minimap, in fractiuni din inaltimea jocului
# (masurat pe o captura 16:9). Se potriveste cu minimap-ul tau; daca il schimbi,
# muti panoul o data cu mouse-ul si isi tine minte diferenta.
IDLE_SIZE = 1.25      # cat de mare e panoul in afara meciului, fata de marimea de baza
DOCK_MAXH = 0.31      # inaltimea maxima a panoului, ca fractie din inaltimea jocului
MIN_HFIT = 0.55       # cat de mult poate fi micsorat continutul inainte de scroll


def px(n):
    return int(round(n * UI_SCALE * FIT))


def be_lightweight():
    """Prioritate sub normal: cand jocul are nevoie de procesor, noi cedam.

    Nu folosim EcoQoS (nuclee eficiente): ar incetini OCR-ul si interfata,
    adica exact lipsa de "instant" pe care o vrem. Sub normal costa nimic cand
    procesorul e liber si ne scoate din drumul jocului cand nu e.
    """
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass(ctypes.c_void_p(k.GetCurrentProcess()), 0x00004000)
    except Exception:
        pass


# Ridica-l INAINTE de a publica un Release nou, altfel exe-ul deja instalat
# la useri nu vede ca a aparut ceva mai nou.
VERSION = "1.3.9"

HOTKEY_LABEL = "CTRL+ALT+Z"

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

# Paleta HUD-ului din joc: teal aproape negru, auriu-bronz, crem, turcoaz.
BG = "#081517"
LINE = "#785a28"          # auriu inchis: linii si chenare
GOLD = "#c8aa6e"          # auriu deschis: chenarul ferestrei, titluri
ACCENT = "#0ac8b9"        # turcoazul hextech: starea activa / "urmeaza"
DIM = "#a09b8c"
TEXT = "#f0e6d2"
CARD = "#0f2428"          # interiorul panourilor din HUD (abilitati, shop)
EDGE = "#1e3a3a"          # linii de sectiune, teal stins ca separatorii din HUD
# chenarul hartii si al HUD-ului, din captura jocului: margine aproape neagra,
# fir auriu-bronz, banda teal inchis si o linie teal mai deschisa spre interior
FRAME = ("#010a0c", "#a3874f", "#0f2b2c", "#1f4644")
UP, DOWN = "#0ac8b9", "#e84057"
ORNAMENT = "#f0d68c"      # auriul aprins al colturilor si rombului din HUD

# In joc panoul imita HUD-ul (teal); in client imita clientul League (bleumarin
# hextech, auriu). Se schimba singur dupa ecranul pe care esti (apply_theme).
THEMES = {
    "hud": {"BG": BG, "CARD": CARD, "EDGE": EDGE, "FRAME": FRAME},
    "client": {"BG": "#010a13", "CARD": "#0a1428", "EDGE": "#1e2328",
               "FRAME": ("#000000", "#785a28", "#091428", "#c8aa6e")},
}

TIER_COLORS = {"S+": "#ff4655", "S": "#ff9a3c", "A": "#ffd166",
               "B": "#8ac926", "C": "#4a9de0", "D": "#6b7280"}
TIER_FG = {"S+": "#ffffff", "S": "#2b1400", "A": "#3a2c00",
           "B": "#182b00", "C": "#04203a", "D": "#ffffff"}
UNKNOWN_TIER = ("#1e2328", "#a09b8c")

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


def pick_fonts():
    """(familie titluri, familie text), primele disponibile din fiecare lista.

    Beaufort (fontul League) e licentiat si nu-l putem livra, deci cerem
    primul serif cu aer similar care exista pe orice Windows. Trebuie apelat
    DUPA tk.Tk(): families() are nevoie de o radacina Tk.
    """
    import tkinter.font as tkfont
    have = set(tkfont.families())
    heading = next((f for f in ("Beaufort for LOL", "Constantia", "Palatino Linotype",
                                "Georgia") if f in have), "Times New Roman")
    body = next((f for f in ("Spiegel", "Segoe UI") if f in have), "Arial")
    return heading, body


def icon(kind, name, size=30):
    """Iconita oficiala, scalata cu NEAREST ca sa ramana pixelata.

    kind: "items" | "champions" | "augments". None daca n-avem fisierul
    (patch nou, nume diferit intre u.gg si datele Riot) -- apelantul cade
    atunci pe un placeholder, nu crapa.
    """
    from build_icons import slug   # aceeasi regula de nume ca la descarcare

    key = (kind, name, px(size))
    if key in _icon_cache:
        return _icon_cache[key]

    path = ICONS / kind / f"{slug(name)}.png"
    if not path.exists():
        _icon_cache[key] = None
        return None

    from PIL import Image, ImageTk
    img = Image.open(path).convert("RGBA").resize((px(size), px(size)), Image.NEAREST)
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

    root = tk.Tk()
    global UI_SCALE
    UI_SCALE = root.winfo_fpixels("1i") / 96
    augment_bar.SCALE = UI_SCALE
    heading, body_family = pick_fonts()
    # titlurile mici (fosta pixel 7) devin serif aldin putin mai mare; textul
    # (fost Consolas 13) devine Segoe UI cu doua puncte mai jos, ca latimea
    # randurilor sa ramana cea de dinainte
    pix = lambda size, weight="normal": (heading, max(6, round((size + 2) * FIT)), "bold")
    mono = lambda size, weight="normal": (body_family, max(7, round((size - 2) * FIT)), weight)

    root.title("ARAM Mayhem Helper")
    ico = ROOT / "icon.ico"
    if ico.exists():
        try:
            root.iconbitmap(default=str(ico))      # iconita din taskbar, nu pana Tk
        except tk.TclError:
            pass
    root.overrideredirect(True)      # desenam noi chenarul, ca in macheta
    root.attributes("-topmost", True)
    root.configure(bg=FRAME[0])
    root.withdraw()

    x, y = settings.pos("panel", (root.winfo_screenwidth() - px(372) - 28, 64))
    root.geometry(f"{px(372)}x{px(260)}+{int(x)}+{int(y)}")

    # --- lipirea de HUD ---------------------------------------------------
    # La pornirea meciului panoul se aseaza singur in golul dintre HUD si
    # minimap. Daca il muti (in joc sau pe alt monitor), ramane unde l-ai pus
    # pana porneste meciul urmator; butonul de langa titlu il pune inapoi.
    # manual: (x, y) ales de tine, sau None. hfit: cat am micsorat continutul
    # ca sa incapa pe inaltime (1.0 = deloc).
    settings.data.pop("dock_offset", None)       # offset-ul permanent de dinainte
    dock = {"last": None, "drag": False, "hfit": 1.0, "manual": None}

    def game_box():
        """(l, t, r, b) al jocului sau None. Fara joc, panoul ramane unde l-ai pus."""
        try:
            import ocr_augments as o
            hwnd = o.find_game_window()
            if hwnd:
                box = o.game_rect(hwnd)
                if box[3] - box[1] >= 300:
                    return box
        except Exception:
            pass
        return None

    def dock_area(box):
        """(x, y, w, h) de ecran al spatiului dintre HUD si minimap, din setarile
        jocului (marimea hartii si a HUD-ului difera de la jucator la jucator)."""
        l, t, r, b = box
        x0, y0, x1, y1 = hud_settings.area(r - l, b - t)
        return int(l + x0), int(t + y0), int(x1 - x0), int(y1 - y0)

    def dock_base(box, h):
        """(x, y, w) al panoului lipit: umple latimea golului, jos lipit de margine."""
        x, y, w, ah = dock_area(box)
        return x, y + ah - h, w

    def client_target(h):
        """(x, y, H) pentru panou langa clientul League, in champ select, sau None.

        Preferam in afara ferestrei clientului (dreapta, apoi stanga) cand monitorul
        are loc, ca sa nu acopere cartile; altfel in coltul din dreapta-jos al
        clientului. Ca la joc, diferenta ta (cand muti panoul) se tine in fractiuni.
        """
        if lcu_mon.phase != "in_mayhem_select":
            return None
        try:
            import ocr_augments as o
            import win32api
            hwnd = o.find_client_window()
            if not hwnd:
                return None
            l, t, r, b = o.game_rect(hwnd)
            ml, mt, mr, mb = win32api.GetMonitorInfo(
                win32api.MonitorFromWindow(hwnd, 2))["Monitor"]
        except Exception:
            return None
        w, H = px(372), b - t
        if mr - r >= w + 8:
            x, y = r + 8, t
        elif l - ml >= w + 8:
            x, y = l - w - 8, t
        else:
            x, y = r - w - 12, b - h - 12
        return x, y, H

    def place(h):
        """Aseaza panoul: lipit de HUD cand jocul e deschis, langa client in champ
        select, altfel pe loc."""
        box = game_box()
        # meci nou (dupa API-ul jocului, nu dupa fereastra: alt-tab din
        # fullscreen o minimizeaza): inapoi in gol
        if ingame_mon.phase == "in_game" and dock.get("phase") != "in_game":
            away = settings.get("away")
            dock["manual"] = tuple(away) if away else None
        dock["phase"] = ingame_mon.phase
        dock["mode"] = "game" if box else None
        if dock["manual"] is not None:
            w = dock_base(box, h)[2] if box else px(372)
            x, y = dock["manual"]
            # panoul creste in jos cand apare un sfat nou: il ridicam cat trebuie
            # ca sa nu iasa din ecranul pe care l-ai pus (jocul sau alt monitor),
            # fara sa-ti uitam pozitia
            try:
                import win32api
                ml, mt, mr, mb = win32api.GetMonitorInfo(
                    win32api.MonitorFromPoint((x + w // 2, y), 2))["Work"]
                x = max(ml, min(x, mr - w))
                y = max(mt, min(y, mb - h))
            except Exception:
                pass
            geo = f"{w}x{h}+{x}+{y}"
        elif box is None:
            tgt = client_target(h)
            if tgt:
                dock["mode"] = "client"
                x, y, H = tgt
                ox, oy = settings.get("client_offset", [0, 0])
                geo = f"{px(372)}x{h}+{int(x + ox * H)}+{int(y + oy * H)}"
            else:
                geo = f"{px(372)}x{h}"
        else:
            H = box[3] - box[1]
            bx, by, w = dock_base(box, h)
            geo = f"{w}x{h}+{bx}+{by}"
        if geo != dock["last"]:
            root.geometry(geo)
            dock["last"] = geo

    def draw_bug():
        """Iconita de bug desenata la marimea curenta: supraesantionata 4x si
        redusa, ca liniile subtiri sa ramana curate la orice DPI."""
        from PIL import Image, ImageDraw, ImageTk
        size = max(10, round(px(13) * FIT))
        big = Image.new("RGBA", (64, 64))
        d = ImageDraw.Draw(big)
        line = dict(fill=GOLD, width=4)
        d.ellipse((19, 22, 45, 60), outline=GOLD, width=4)          # corpul
        d.ellipse((25, 9, 39, 23), fill=GOLD)                       # capul
        d.line((32, 26, 32, 58), **line)                            # aripile
        for y0, y1 in ((32, 26), (42, 42), (52, 58)):               # picioarele
            d.line((19, y0, 7, y1), **line)
            d.line((45, y0, 57, y1), **line)
        d.line((28, 12, 21, 2), **line)                             # antenele
        d.line((36, 12, 43, 2), **line)
        photo = ImageTk.PhotoImage(big.resize((size, size), Image.LANCZOS))
        bug.configure(image=photo)
        bug.image = photo        # referinta vie, altfel Tk o pierde

    def update_fit():
        """Potriveste marimea panoului pe jocul curent. True daca s-a schimbat."""
        global FIT
        box = game_box()
        if box is None:
            # in afara meciului panoul nu e strans intr-un gol: pe 1080p arata
            # ingust si cu iconite marunte la marimea de baza
            new = IDLE_SIZE
        else:
            _, gap_w = hud_settings.gap(box[2] - box[0], box[3] - box[1])
            new = max(0.55, min(1.3, gap_w / (372 * UI_SCALE))) * dock["hfit"]
        if abs(new - FIT) < 0.01:
            return False
        FIT = new
        # antetul si subsolul nu se redeseneaza la fiecare randare: fontul lor
        # trebuie sa urmeze si el marimea, altfel raman mari pe un panou micsorat
        for widget, size in ((title, 8), (close, 8), (minimize, 8), (snap, 8),
                             (context, 7), (status_label, 7), (version, 6), (aug_btn, 6)):
            widget.configure(font=pix(size))
        draw_bug()
        return True

    # chenarul de 1px: un frame exterior alb cu padding, peste care sta continutul
    # chenarul, ca la minimap si HUD: margine intunecata, bronz, fir auriu
    # fiecare inel lasa sa se vada culoarea parintelui pe grosimea data:
    # 1 margine, 2 auriu, 3 banda teal, 1 linie teal
    outer = root
    for color, width in zip(FRAME[1:] + (BG,), (1, 2, 3, 1)):
        ring = tk.Frame(outer, bg=color)
        ring.pack(fill="both", expand=True, padx=max(1, px(width)), pady=max(1, px(width)))
        outer = ring
    shell = outer

    # --- bara de titlu ---------------------------------------------------
    titlebar = tk.Frame(shell, bg=BG)
    titlebar.pack(fill="x", padx=8, pady=(7, 6))

    title = tk.Label(titlebar, text="ARAM MAYHEM", bg=BG, fg=GOLD, font=pix(8))
    title.pack(side="left")
    # versiune noua deja instalata in fundal: se vede, dar nu intrerupe nimic
    update_note = tk.Label(titlebar, text="", bg=BG, fg=ACCENT, font=pix(6))
    # augmentele alese, langa numele campionului: nu mai iau un rand din panou
    title_augs = tk.Frame(titlebar, bg=BG)
    title_augs.pack(side="left", padx=(8, 0))

    close = tk.Label(titlebar, text="X", bg=BG, fg=GOLD, font=pix(8),
                     cursor="hand2", padx=4)
    close.pack(side="right")
    minimize = tk.Label(titlebar, text="_", bg=BG, fg=GOLD, font=pix(8), padx=4)
    minimize.pack(side="right")
    # gandacul de raportat bug-uri, ca in clientul League: contur auriu
    bug = tk.Label(titlebar, bg=BG, bd=0, padx=6, cursor="hand2")
    bug.pack(side="right")
    # inapoi in golul dintre HUD si minimap, dupa ce l-ai mutat
    snap = tk.Label(titlebar, text="\u25c7", bg=BG, fg=GOLD, font=pix(8), padx=4,
                    cursor="hand2")
    snap.pack(side="right")
    # versiunea pe care rulezi; click = cauta update acum, nu peste 30 de minute
    version = tk.Label(titlebar, text=f"v{VERSION}", bg=BG, fg=DIM, font=pix(6),
                       padx=4, cursor="hand2")
    version.pack(side="right")
    # rezerva cand OCR-ul nu vede oferta: augmentele bune ale campionului (doar in joc)
    aug_btn = tk.Label(titlebar, text="AUG", bg=BG, fg=GOLD, font=pix(6), padx=4,
                       cursor="hand2")
    aug_view = {"on": False}

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
    # Corpul sta intr-un canvas ca sa se poata da scroll cand nu incape (rotita
    # de mouse). Inaltimea canvasului o fixeaza fit_height(): urmeaza continutul
    # pana la limita, apoi scroll.
    body_wrap = tk.Canvas(shell, bg=BG, highlightthickness=0, bd=0, yscrollincrement=24)
    body_wrap.pack(fill="both", expand=True, padx=10, pady=8)
    body = tk.Frame(body_wrap, bg=BG)
    body_win = body_wrap.create_window((0, 0), window=body, anchor="nw")
    body_wrap.bind("<Configure>", lambda e: body_wrap.itemconfigure(body_win, width=e.width))
    body.bind("<Configure>",
              lambda _e: body_wrap.configure(scrollregion=body_wrap.bbox("all")))

    def on_wheel(e):
        # doar cand cursorul e deasupra panoului; fara asta am fura rotita altor ferestre
        x, y = root.winfo_pointerxy()
        if root.winfo_rootx() <= x <= root.winfo_rootx() + root.winfo_width() \
                and root.winfo_rooty() <= y <= root.winfo_rooty() + root.winfo_height():
            if body.winfo_reqheight() > body_wrap.winfo_height():
                body_wrap.yview_scroll(-1 if e.delta > 0 else 1, "units")
                body_wrap.yview_scroll(-1 if e.delta > 0 else 1, "units")

    root.bind_all("<MouseWheel>", on_wheel)

    # --- subsolul --------------------------------------------------------
    divider3 = tk.Frame(shell, bg=LINE, height=1)
    divider3.pack(fill="x")
    footer = tk.Frame(shell, bg=BG)
    footer.pack(fill="x", padx=8, pady=6)
    status_label = tk.Label(footer, text="", bg=BG, fg=DIM, font=pix(7),
                            anchor="w", justify="left", wraplength=px(340))
    status_label.pack(side="left")

    # Ornamentele HUD-ului: colturi aurii in L peste chenar (ca bucla din coltul
    # hartii) si un romb in mijlocul separatoarelor. ORNAMENT nu e in nicio
    # tema, deci apply_theme nu le recoloreaza.
    for relx, rely in ((0, 0), (1, 0), (0, 1), (1, 1)):
        anchor = ("n" if rely == 0 else "s") + ("w" if relx == 0 else "e")
        for w, h in ((14, 3), (3, 14)):
            tk.Frame(root, bg=ORNAMENT, width=px(w), height=px(h)).place(
                relx=relx, rely=rely, anchor=anchor)
    for divider in (divider1, divider2, divider3):
        d = px(7)
        gem = tk.Canvas(shell, width=d, height=d, bg=BG, highlightthickness=0, bd=0)
        gem.create_polygon(d / 2, 0, d, d / 2, d / 2, d, 0, d / 2, fill=ORNAMENT, outline="")
        # asezat pe separator: dispare singur cand separatorul e ascuns
        gem.place(in_=divider, relx=0.5, rely=0.5, anchor="center")

    # piesele astea se ascund cand fereastra e "stransa" la bara de titlu.
    # NU folosim withdraw() pentru asta -- daca hotkey-ul nu ajunge (de ex.
    # blocat de un anticheat cand jocul e in prim-plan), o fereastra complet
    # ascunsa n-are cum sa mai fie adusa inapoi. Bara de titlu ramane mereu
    # pe ecran si mereu clickabila, indiferent ce se intampla cu hotkey-ul.
    collapsible = (divider1, subbar, divider2, body_wrap, divider3, footer)

    # mutarea ferestrei cu mouse-ul: fara bara nativa, o facem noi
    drag = {"x": 0, "y": 0}

    def press(e):
        dock["drag"] = True
        dock["moved"] = False
        drag["x"], drag["y"] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def move(e):
        dock["moved"] = True
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

    def show_tip(widget, name, text=None):
        hide_tip()
        text = text or item_desc.get(name)
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
                     wraplength=px(300)).pack(fill="x", padx=8, pady=(4, 6))

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

    def attach_tip(widget, name, text=None):
        widget.bind("<Enter>", lambda _e, w=widget, n=name, t=text: show_tip(w, n, t))
        widget.bind("<Leave>", hide_tip)

    def section(text):
        # pady strans: cinci antete luau 85px din 499px de continut, adica
        # 17% din fereastra doar pentru etichete
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(6, 3))
        tk.Label(row, text=text, bg=BG, fg=ACCENT, font=pix(7),
                 anchor="w").pack(side="left")
        tk.Frame(row, bg=EDGE, height=1).pack(side="left", fill="x",
                                                   expand=True, padx=(6, 0))

    def tier_badge(parent, tier):
        bg, fg = TIER_COLORS.get(tier), TIER_FG.get(tier)
        if bg is None:
            bg, fg = UNKNOWN_TIER
        return tk.Label(parent, text=tier, bg=bg, fg=fg, font=pix(8),
                        width=3, height=2)

    def stat_line(parent, info, tip_text=None):
        """Win rate / pick rate si cum s-au schimbat fata de patch-ul anterior.

        Sageata verde = mai bun, rosie = mai slab; lipsa datelor nu desenează nimic.
        """
        if "wr" not in info and "tier_change" not in info:
            return
        if info.get("balance"):
            # modificatorii Mayhem ai campionului, ex. "DMG DAT -5%"; ii aratam
            # sub cifre ca sa vezi imediat cum e "taiat" sau "umflat" in mod
            tk.Label(parent, text="MAYHEM  " + "  ".join(info["balance"]),
                     bg=parent["bg"], fg=DIM, font=mono(9), anchor="w",
                     justify="left", wraplength=px(300)).pack(fill="x")
        line = tk.Frame(parent, bg=parent["bg"])
        line.pack(fill="x", pady=(2, 0))

        def part(text, color):
            tk.Label(line, text=text, bg=parent["bg"], fg=color,
                     font=mono(10, "bold")).pack(side="left", padx=(0, 7))

        def arrow(value, unit=""):
            if not value:
                return "=", DIM
            return (f"▲{abs(value):g}{unit}", UP) if value > 0                 else (f"▼{abs(value):g}{unit}", DOWN)

        if "wr" in info:
            part(f"WR {info['wr']:.1f}%", TEXT)
            if "wr_delta" in info:
                part(*arrow(info["wr_delta"], "%"))
            part(f"PR {info['pr']:.1f}%", DIM)
        if "tier_change" in info:
            text, color = arrow(info["tier_change"])
            part(f"TIER {text}", color)
        if tip_text:
            attach_tip(line, "Schimbari Mayhem", tip_text)
            for child in line.winfo_children():
                attach_tip(child, "Schimbari Mayhem", tip_text)

    def tier_row(kind, entry, best_label=None, tag=None):
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
        if kind == "champions":
            stat_line(texts, entry)
        # unele augmente ("Upgrade Zhonya's") n-au sens decat daca chiar
        # cumperi itemul din spate -- se vede la momentul alegerii, nu dupa
        needs = augment_items.get(entry["name"])
        if needs:
            tk.Label(texts, text=f"CERE {needs.upper()}", bg=CARD, fg=ACCENT,
                     font=pix(7), anchor="w").pack(fill="x", pady=(3, 0))

        # Fara tier (u.gg nu-l claseaza) aratam ce face, ca sa poti decide tu.
        # Nu inventam un rank: ar arata identic cu unul calculat din meciuri
        # reale, dar ar fi doar o parere.
        if entry["tier"] not in TIER_COLORS:
            what = augment_desc.get(entry["name"])
            tk.Label(texts, text=(what or "neclasat de u.gg")[:110], bg=CARD,
                     fg=DIM, font=mono(10), anchor="w", justify="left",
                     wraplength=px(250)).pack(fill="x", pady=(2, 0))

        if is_best and best_label:
            tk.Label(row, text=best_label + (f"  ·  {tag}" if tag else ""), bg=CARD, fg=color,
                     font=pix(7)).pack(side="right", padx=6)
        elif tag:
            tk.Label(row, text=tag, bg=CARD, fg=DIM, font=pix(6)).pack(side="right", padx=6)

    def icon_strip(entries):
        """Iconite una langa alta. Accepta si nume simple, si {item, owned}."""
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=2)
        for e in entries:
            name = e["item"] if isinstance(e, dict) else e
            owned = isinstance(e, dict) and e.get("owned")
            is_next = isinstance(e, dict) and e.get("next")
            # verde = urmatorul de cumparat, gri stins = deja al tau
            border = ACCENT if is_next else ("#1e2328" if owned else EDGE)
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

    def item_row(entry, icon_kind="items"):
        """Un item de cumparat: iconita + nume + motivul (daca exista).

        Accepta si intrari de core, care n-au cheia "reason" -- de aceea .get.
        """
        hot = bool(entry.get("reason"))
        owned = entry.get("owned")
        is_next = entry.get("next")
        outer = tk.Frame(body, bg=ACCENT if (hot or is_next) else CARD)
        outer.pack(fill="x", pady=2)
        row = tk.Frame(outer, bg=CARD)
        row.pack(fill="both", expand=True, padx=1, pady=1)

        photo = icon(icon_kind, entry["item"], 30) if icon_kind else None
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
            tk.Label(texts, text=entry["reason"].upper(), bg=CARD, fg=ACCENT,
                     font=pix(7), anchor="w", justify="left",
                     wraplength=px(REASON_WRAP)).pack(fill="x", pady=(3, 0))

        if owned:
            tk.Label(row, text="AI", bg=CARD, fg=DIM,
                     font=pix(7)).pack(side="right", padx=8)
        elif is_next:
            tk.Label(row, text="URMEAZA" if icon_kind else "BEST", bg=CARD, fg=ACCENT,
                     font=pix(7)).pack(side="right", padx=8)

    def boots_row(advice):
        """Vinde X -> ia Y (rules_engine.sell_advice)."""
        outer = tk.Frame(body, bg=ACCENT)
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
        tk.Label(texts, text=f"VINDE {advice['sell']}", bg=CARD, fg=DOWN,
                 font=pix(7), anchor="w", justify="left",
                 wraplength=px(BOOTS_WRAP)).pack(fill="x")
        tk.Label(texts, text=f"IA {advice['buy']}", bg=CARD, fg=TEXT,
                 font=mono(12, "bold"), anchor="w", justify="left",
                 wraplength=px(BOOTS_WRAP)).pack(fill="x", pady=(1, 0))
        if advice["reason"]:
            tk.Label(texts, text=advice["reason"].upper(), bg=CARD, fg=ACCENT,
                     font=pix(6), anchor="w", justify="left",
                     wraplength=px(BOOTS_WRAP)).pack(fill="x", pady=(1, 0))

    def note(text, color=DIM):
        tk.Label(body, text=text, bg=BG, fg=color, font=mono(11), anchor="w",
                 justify="left", wraplength=px(330)).pack(fill="x", pady=6)

    def summoner_row(names):
        """Cele doua spell-uri recomandate de u.gg, iconita + nume, unul langa altul."""
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=2)
        for name in names:
            cell = tk.Frame(row, bg=EDGE)
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
        tk.Label(row, text=value, bg=BG, fg=ACCENT if ok else "#9a6b6b",
                 font=mono(10, "bold"), anchor="e").pack(side="right")

    def waiting_bar():
        """Bara segmentata din macheta, ca semn ca aplicatia chiar traieste.

        Celulele sunt animate de animate(), care ruleaza continuu si le
        gaseste prin anim["cells"] -- nu redesenam tot corpul la fiecare
        cadru, ar fi risipa pentru o animatie de asteptare.
        """
        wrap = tk.Frame(body, bg=EDGE)
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
                cell.configure(bg=ACCENT if lit else BG)
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

    def champ_offer_entries():
        """Cartile personale citite prin OCR, cu tier si statistici.

        BEST se recalculeaza peste TOT ce vezi (campionul tau, bench si cartile
        citite), ca sa existe un singur BEST pe ecran.
        """
        import mayhem_logic as logic
        import tier_list
        # lista de carti se reimprospateaza mai rar decat LCU-ul: un campion
        # tocmai ales sau trecut pe bench ar aparea de doua ori
        known = set(champ_known())
        names = [n for n in champ_reader.offers if n not in known]
        if not names:
            return []
        import champ_stats
        entries = [dict(name=n, tier=tier_list.TIER_DATA.get(n, logic.UNRANKED),
                        is_best=False, **champ_stats.info(n)) for n in names]
        # cat timp cartile sunt pe ecran alegi dintre ele; bench-ul vine dupa
        pool = ([lcu_mon.assigned] if lcu_mon.assigned else []) + entries
        best = min(pool, key=lambda e: logic.tier_rank(e["tier"]))
        for e in lcu_mon.bench + ([lcu_mon.assigned] if lcu_mon.assigned else []):
            e["is_best"] = e is best
        for e in entries:
            e["is_best"] = e is best
        return entries

    def render_champ_select():
        title.configure(text="ARAM MAYHEM")
        context.configure(text="CHAMP SELECT  ·  REROLL")
        # Toti campionii pe care ii poti avea, intr-o singura lista ordonata dupa
        # tier: al tau, apoi cartile tale sau bench-ul. De unde vine fiecare scrie in
        # dreapta; la tier egal, al tau ramane primul (n-are rost reroll).
        import mayhem_logic as logic
        offers = champ_offer_entries()
        # Cat timp cartile tale sunt pe ecran alegi dintre ele: bench-ul apare
        # abia dupa ce au disparut.
        pool = ([(lcu_mon.assigned, "AL TAU")] if lcu_mon.assigned else []) \
            + ([(e, "CARTE") for e in offers] if offers else [(e, "BENCH") for e in lcu_mon.bench])
        if not pool:
            note("se incarca...")
            return
        ranked = sorted(pool, key=lambda p: logic.tier_rank(p[0]["tier"]))
        # Sus, fixate: cel mai bun campion si spell-urile lui. Lista de dedesubt
        # poate fi lunga, dar decizia se vede fara scroll.
        best, origin = ranked[0]
        section("CEL MAI BUN")
        tier_row("champions", best, "BEST", tag=origin)
        build = ingame.load_cached(best["name"])
        summoners = build.get("summoners") if build else None
        if summoners:
            section(f"SUMMONER SPELLS  ·  {best['name'].upper()}")
            summoner_row(summoners)
        if ranked[1:]:
            section("RESTUL  ·  DUPA TIER")
            for entry, origin in ranked[1:]:
                tier_row("champions", entry, "BEST", tag=origin)

    def augment_strip(names):
        """Augmentele luate, iconite mici in bara de titlu; click pe una o scoate
        (alegere gresita)."""
        row = title_augs
        for name in names:
            photo = icon("augments", name, 16)
            cell = tk.Label(row, image=photo, bg=BG, bd=0, cursor="hand2") if photo else \
                tk.Label(row, text=name[:10], bg=CARD, fg=TEXT, font=mono(9), cursor="hand2")
            cell.pack(side="left", padx=(0, 4))
            attach_tip(cell, name, "Click: scoate din lista (ai ales gresit)")

            def drop(_e, n=name):
                if n in ingame_mon.taken_augments:
                    ingame_mon.taken_augments.remove(n)
                    ingame_mon._recompute_build()
                    shown["fingerprint"] = None
            cell.bind("<Button-1>", drop)

    def next_strip(entries):
        """Itemul de cumparat ACUM, mare si incadrat auriu ca sa sara in ochi
        dintr-o privire; dupa el, restul ordinii ca sloturi mici si stinse.
        Motivele celorlalti apar la hover pe iconita."""
        def tip_for(e):
            return "\n\n".join(t for t in (e.get("reason") and e["reason"].capitalize(),
                                           item_desc.get(e["item"])) if t) or None

        def slot(parent, e, size, bg):
            photo = icon("items", e["item"], size)
            lbl = tk.Label(parent, image=photo, bg=bg, bd=0) if photo else \
                tk.Label(parent, text=e["item"][:3].upper(), bg=CARD, fg=DIM, font=pix(7),
                         width=4, height=2)
            attach_tip(lbl, e["item"], tip_for(e))
            return lbl

        head, rest = entries[0], entries[1:]
        # chenar auriu dublu cu linie hextech inauntru, ca alegerea buna din joc
        gold = tk.Frame(body, bg=GOLD)
        gold.pack(fill="x", pady=(2, 0))
        glow = tk.Frame(gold, bg=ACCENT)
        glow.pack(fill="x", padx=2, pady=2)
        hero = tk.Frame(glow, bg=CARD)
        hero.pack(fill="x", padx=1, pady=1)
        slot(hero, head, 56, CARD).pack(side="left", padx=(5, 8), pady=5)
        texts = tk.Frame(hero, bg=CARD)
        texts.pack(side="left", fill="x", expand=True, pady=4)
        tk.Label(texts, text="CUMPARA ACUM", bg=CARD, fg=ACCENT, font=pix(6),
                 anchor="w").pack(fill="x")
        tk.Label(texts, text=head["item"], bg=CARD, fg=TEXT, font=mono(16, "bold"),
                 anchor="w", justify="left", wraplength=px(230)).pack(fill="x")
        if head.get("reason"):
            tk.Label(texts, text=head["reason"].upper(), bg=CARD, fg=GOLD, font=pix(6),
                     anchor="w", justify="left", wraplength=px(230)).pack(fill="x", pady=(1, 0))

        if rest:
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=(5, 0))
            tk.Label(row, text="APOI", bg=BG, fg=DIM, font=pix(6)).pack(side="left", padx=(0, 6))
            for e in rest:
                # linie turcoaz pe itemii ceruti de meci (contra-item, augment)
                cell = tk.Frame(row, bg=ACCENT if e.get("reason") else LINE)
                cell.pack(side="left", padx=(0, 4))
                slot(cell, e, 30, BG).pack(padx=1, pady=1)

    def top_augments():
        """Rezerva cand OCR-ul nu vede oferta: cele mai bune augmente ale
        campionului pe fiecare raritate. Le cauti pe carduri dupa nume."""
        import augment_tier
        champ = (ingame_mon.roster or {}).get("local_champion")
        section("TOP AUGMENTE" + (f"  \u00b7  {champ.upper()}" if champ else ""))
        if ingame_mon.ocr_status:
            note("OCR: " + ingame_mon.ocr_status.split(" (")[0], DIM)
        top = augment_tier.top_by_rarity(ingame_mon.global_augments, champ)
        for rarity, label in (("prismatic", "PRISM"), ("gold", "AUR"), ("silver", "ARGINT")):
            if not top.get(rarity):
                continue
            row = tk.Frame(body, bg=CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=CARD, fg=DIM, font=pix(6), width=7,
                     anchor="w").pack(side="left", padx=(6, 4), pady=4)
            tk.Label(row, text="  \u00b7  ".join(f"{a['name']} ({a['tier']})" for a in top[rarity]),
                     bg=CARD, fg=TEXT, font=mono(10, "bold"), anchor="w", justify="left",
                     wraplength=px(260)).pack(side="left", fill="x", pady=4)

    def render_in_game():
        champ = (ingame_mon.roster or {}).get("local_champion") or "?"
        enemies = (ingame_mon.roster or {}).get("enemies") or []
        # in joc antetul e numele campionului: randul de context si subsolul
        # sunt ascunse (vezi set_chrome), fiecare pixel din gol conteaza
        title.configure(text=champ.upper() if champ != "?" else "ARAM MAYHEM")
        context.configure(text=f"IN JOC  \u00b7  {champ.upper()}"
                               + (f"  \u00b7  VS {len(enemies)}" if enemies else ""))
        # Doar ce te ajuta sa castigi meciul: ce cumperi, ce vinzi, ce shard
        # iei. Cifrele de patch si schimbarile de balans raman in champ select.
        if ingame_mon.status:
            note(ingame_mon.status, DIM)

        if ingame_mon.taken_augments:
            augment_strip(ingame_mon.taken_augments)

        if ingame_mon.augments:
            # numele citite, in ordinea cardurilor: daca o insigna a cazut pe
            # alt card, aici vezi oricum ce tier are fiecare augment
            section("OFERTA")
            for a in ingame_mon.augments:
                tier_row("augments", a, "BEST")
        elif aug_view["on"]:
            top_augments()

        if ingame_mon.stat_anvil:
            section("STAT ANVIL")
            for s in ingame_mon.stat_anvil:
                label = ANVIL_LABEL.get(s["category"], s["category"].upper())
                item_row({"item": f"{s['name'].replace(' Shard', '')} ({label})",
                          "reason": s["why"].upper() if s["is_best"] else None,
                          "next": s["is_best"]}, icon_kind=None)

        rb = ingame_mon.resolved_build
        if rb:
            # startul doar cat inca nu l-ai cumparat (rules_engine.starting_left)
            if rb.get("starting"):
                section("START")
                icon_strip(rb["starting"])

            # Vanzarea e cel mai urgent lucru de pe ecran: sta prima, ca sa nu
            # ramana niciodata sub marginea panoului.
            if rb.get("sell"):
                boots_row(rb["sell"])

            # Doar ce URMEAZA sa cumperi, in ordine. Cele deja cumparate nu mai
            # sunt o decizie.
            # Cu 6 sloturi pline nu mai ai unde pune un item: ce urmeaza vine
            # doar prin sfatul de vanzare de mai sus (VINDE X, IA Y).
            full = rb.get("full")
            ramase = [] if full else [e for e in rb["core"] + rb["picks"] if not e["owned"]]
            if ramase:
                next_strip(ramase[:6])      # are propria eticheta: CUMPARA ACUM
            elif rb["picks"]:
                section("BUILD COMPLET")
                icon_strip([e for e in rb["core"] + rb["picks"] if e["owned"] or not full])

            if rb.get("unavailable"):
                # de ce lipseste un item pe care l-ai astepta: nu-l poti cumpara
                note("Indisponibil: " + ", ".join(rb["unavailable"])
                     + (f" (esti {rb['range']})" if rb.get("range") else ""), DIM)

        if not ingame_mon.roster:
            note("se incarca...")

    # --- bucla de improspatare -------------------------------------------

    shown = {"view": None, "fingerprint": None}

    def took_augment(name):
        """Click pe o insigna: augmentul asta e al meu, reasaza build-ul."""
        if name not in ingame_mon.taken_augments:
            ingame_mon.taken_augments.append(name)
            ingame_mon._recompute_build()
            shown["fingerprint"] = None      # forteaza redesenarea panoului

    bar = augment_bar.AugmentBar(root, TIER_COLORS, UNKNOWN_TIER[1],
                                 (heading, body_family), on_pick=took_augment,
                                 names=True)

    # Stat Anvil: acelasi fel de banda, deasupra acelorasi carduri, doar ca
    # "tier"-ul e statul oferit si culoarea spune doar daca e alegerea buna --
    # nu exista tier list public pentru shard-uri, deci n-avem ce rank sa aratam.
    anvil_bar = augment_bar.AugmentBar(root, {}, DIM, (heading, body_family))

    # nume lung de card -> eticheta scurta care incape in insigna
    ANVIL_LABEL = {
        "haste": "HASTE", "ap": "AP", "ad": "AD", "as": "AS", "crit": "CRIT",
        "hp": "HP", "armor": "ARMOR", "mr": "MR", "pen_ad": "PEN AD",
        "pen_ap": "PEN AP", "hybrid_dmg": "AD+AP", "hybrid_utility": "AS+AH",
        "hybrid_defense": "AR+MR", "mobility": "MS", "sustain": "OMNIVAMP",
        "heal_power": "HEAL", "cc_resist": "TENACITY",
    }

    def anvil_entries(shards):
        """Shard-uri -> forma pe care o stie AugmentBar, plus culorile lor."""
        entries, colors = [], {}
        for s in shards:
            label = ANVIL_LABEL.get(s["category"], s["category"].upper())
            colors[label] = GOLD if s["is_best"] else DIM
            entries.append({"name": s["name"].replace(" Shard", ""),
                            "tier": label, "is_best": s["is_best"], "slot": s.get("slot"),
                            "note": (f"{s['champion']} \u00b7 {s['why']}"
                                     if s["is_best"] and s.get("champion") else None)})
        return entries, colors

    def champ_known():
        # tu, bench-ul si coechipierii: toti apar pe ecran, dar nu sunt cartile tale
        return [e["name"] for e in ([lcu_mon.assigned] if lcu_mon.assigned else [])
                + list(lcu_mon.bench)] + list(lcu_mon.team)

    champ_reader = champ_ocr.ChampSelectReader(
        lcu.load_champion_data().values(),
        lambda: lcu_mon.phase == "in_mayhem_select" and ingame_mon.phase != "in_game",
        champ_known)
    champ_reader.run()

    pin_bar = augment_bar.PinBar(root, TIER_COLORS, UNKNOWN_TIER[1], (heading, body_family))

    def update_bars():
        """Benzile de tier de deasupra cardurilor. Separate de panou si rulate
        des (150 ms): o oferta noua dupa un reroll trebuie sa apara pe loc, nu
        la urmatorul ciclu al panoului. Merg si cand panoul e strans."""
        try:
            import ocr_augments as _ocr
            import win32gui as _w32
            hwnd = _ocr.find_game_window()
            focused = bool(hwnd) and _ocr.in_front(hwnd)
            region = _ocr.augment_region(_ocr.game_rect(hwnd)) if focused else None

            if ingame_mon.augments and focused:
                bar.show(ingame_mon.augments, region)
            else:
                bar.hide()

            # Stat Anvil si oferta de augment nu apar niciodata deodata, deci
            # a doua banda foloseste aceeasi zona fara sa se suprapuna.
            if ingame_mon.stat_anvil and focused and not ingame_mon.augments:
                entries, anvil_bar.colors = anvil_entries(ingame_mon.stat_anvil)
                anvil_bar.show(entries, region)
            else:
                anvil_bar.hide()

            # champ select: insigna de tier deasupra fiecarei carti personale
            client = _ocr.find_client_window()
            if (champ_reader.pins and client
                    and _w32.GetForegroundWindow() == client
                    and active_view() == "champ_select"):
                pins = [dict(e, cx=champ_reader.pins[e["name"]][0],
                             y=champ_reader.pins[e["name"]][1])
                        for e in champ_offer_entries() if e["name"] in champ_reader.pins]
                pin_bar.show(pins)
            else:
                pin_bar.hide()
        except Exception:
            bar.hide()   # benzile sunt un plus; daca dau gres, nu opresc aplicatia
            anvil_bar.hide()
            pin_bar.hide()
        root.after(150, update_bars)

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
                    tuple((e["name"], e["is_best"]) for e in lcu_mon.bench),
                    tuple(champ_reader.offers))
        if view == "in_game":
            picks = ingame_mon.resolved_build["picks"] if ingame_mon.resolved_build else []
            core = ingame_mon.resolved_build["core"] if ingame_mon.resolved_build else []
            return (view,
                    ingame_mon.roster and ingame_mon.roster.get("local_champion"),
                    ingame_mon.roster and tuple(ingame_mon.roster.get("enemies", [])),
                    tuple((c["item"], c["owned"], c["next"]) for c in core),
                    tuple((p["item"], p["reason"], p["owned"], p["next"]) for p in picks),
                    (ingame_mon.resolved_build or {}).get("sell") and
                    tuple((ingame_mon.resolved_build["sell"] or {}).values()),
                    tuple((a["name"], a["tier"]) for a in ingame_mon.augments),
                    tuple(ingame_mon.taken_augments),
                    tuple((ingame_mon.resolved_build or {}).get("unavailable") or ()),
                    tuple((s["name"], s["is_best"]) for s in ingame_mon.stat_anvil),
                    ingame_mon.status,
                    (ingame_mon.resolved_build or {}).get("full"),
                    aug_view["on"] and (ingame_mon.ocr_status or "").split(" (")[0])
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
        (body_wrap, {"fill": "both", "expand": True, "padx": 10, "pady": 8}),
        (divider3, {"fill": "x"}),
        (footer, {"fill": "x", "padx": 8, "pady": 6}),
    ]

    collapsed = {"want": False, "applied": False}
    chrome = {"lean": False}

    theme = {"name": "hud"}

    def apply_theme(view):
        """Culorile ecranului curent; recoloreaza si piesele fixe ale ferestrei."""
        global BG, CARD, EDGE, FRAME
        name = "hud" if view == "in_game" else "client"
        if name == theme["name"]:
            return
        old, new = THEMES[theme["name"]], THEMES[name]
        swap = {}
        for key in ("BG", "CARD", "EDGE"):
            swap[old[key]] = new[key]
        swap.update(zip(old["FRAME"], new["FRAME"]))
        BG, CARD, EDGE, FRAME = new["BG"], new["CARD"], new["EDGE"], new["FRAME"]
        theme["name"] = name
        stack = [root]
        while stack:
            w = stack.pop()
            try:
                if w.cget("bg") in swap:
                    w.configure(bg=swap[w.cget("bg")])
            except tk.TclError:
                pass
            stack.extend(w.winfo_children())

    def set_chrome(view):
        """In joc fara randul de context si fara subsol: panoul sta in golul
        dintre HUD si minimap, iar acolo conteaza doar continutul."""
        lean = view == "in_game"
        if lean == chrome["lean"] or collapsed["applied"]:
            return
        chrome["lean"] = lean
        if lean:
            for w in (subbar, divider2, divider3, footer):
                w.pack_forget()
            aug_btn.pack(side="right", after=version)
        else:
            aug_btn.pack_forget()
            subbar.pack(fill="x", padx=8, pady=5, before=body_wrap)
            divider2.pack(fill="x", before=body_wrap)
            divider3.pack(fill="x", after=body_wrap)
            footer.pack(fill="x", padx=8, pady=6, after=divider3)

    def toggle_collapsed():
        # ruleaza pe firul hotkey-ului, nu pe cel al Tk-ului -- doar o
        # atribuire simpla de bool, restul se rezolva la urmatorul refresh()
        collapsed["want"] = not collapsed["want"]

    def refresh():
        if version.cget("text") == "..." and not UPDATE["busy"]:
            # raspunsul scurt ("ESTI LA ZI"), apoi inapoi la numarul versiunii
            version.configure(text=(UPDATE["why"] or "").split(":")[0].upper() or f"v{VERSION}")
            root.after(4000, lambda: version.configure(text=f"v{VERSION}"))
        if UPDATE["tag"] and not update_note.winfo_ismapped():
            update_note.configure(text=f"UPDATE {UPDATE['tag']}")
            update_note.pack(side="left", padx=(8, 0))
        # versiunea noua e pe disc: in afara meciului si a champ select-ului
        # repornim singuri pe ea, in meci doar la click (nu dispare panoul in lupta)
        # o singura data pe versiune: un exe publicat cu numar gresit ar
        # reporni la nesfarsit
        if (UPDATE["tag"] and ingame_mon.phase != "in_game"
                and lcu_mon.phase != "in_mayhem_select"
                and settings.get("restarted_for") != UPDATE["tag"]):
            settings.set("restarted_for", UPDATE["tag"])
            restart_into_update()
            return
        if not dock["drag"]:
            if update_fit():
                shown["fingerprint"] = None      # marimea s-a schimbat: redesenam
            elif collapsed["applied"] or shown["fingerprint"] is not None:
                place(root.winfo_height())       # jocul s-a mutat/redimensionat
        if collapsed["want"] != collapsed["applied"]:
            for w, kw in COLLAPSIBLE_PACK:
                if collapsed["want"]:
                    w.pack_forget()
                elif not (chrome["lean"] and w in (subbar, divider2, divider3, footer)):
                    w.pack(**kw)
            collapsed["applied"] = collapsed["want"]
            # update_idletasks() INAINTE de a citi inaltimea: fara el, Tk
            # raporteaza dimensiunea "naturala" pe layout-ul vechi (dinaintea
            # pack_forget), iar fereastra ramane cu un dreptunghi gol dedesubt.
            # Latimea ramane fixa (width) -- doar geometry("") ar lasa-o sa se
            # ingusteze si ar muta "_"/"X" in alta parte la fiecare apasare
            root.update_idletasks()
            place(root.winfo_reqheight())

        if collapsed["want"]:
            root.after(500, refresh)
            return

        view = active_view()
        apply_theme(view)
        set_chrome(view)
        fp = fingerprint(view)
        if view != shown["view"] or fp != shown["fingerprint"]:
            shown["view"] = view
            shown["fingerprint"] = fp
            # tooltip-ul e ancorat de un widget care tocmai dispare: fara
            # asta ar ramane agatat pe ecran dupa redesenare
            hide_tip()
            if view != dock.get("view"):
                dock["view"], dock["hfit"] = view, 1.0     # alt continut: refacem potrivirea
                update_fit()
            for _n in range(5):
                if os.environ.get("ARAM_DEBUG_FIT"):
                    print("pass", _n, "hfit", round(dock["hfit"], 3), "FIT", round(FIT, 3))
                for w in body.winfo_children() + title_augs.winfo_children():
                    w.destroy()
                anim["cells"] = []    # celulele tocmai au fost distruse
                render[view]()
                status_label.configure(text=(ingame_mon.status or "").upper())
                if not fit_height(final=(_n == 4)):
                    break
            body_wrap.yview_moveto(0)

        root.after(500, refresh)

    def fit_height(final=False):
        """Inaltimea urmeaza continutul, dar nu iese din golul dintre HUD si minimap.

        Daca nu incape, micsoram tot panoul (hfit) pana la MIN_HFIT si cerem o
        noua randare -- True. Sub MIN_HFIT ramane scroll. Apelata si dupa
        mesajele care apar mai tarziu (avertismentul de hotkey).
        """
        root.update_idletasks()
        content = body.winfo_reqheight()
        chrome = root.winfo_reqheight() - body_wrap.winfo_reqheight()
        box = game_box()
        docked = box is not None and dock["manual"] is None
        limit = dock_area(box)[3] if docked else (
            int(DOCK_MAXH * (box[3] - box[1])) if box else px(MAX_HEIGHT))
        total = chrome + content
        if os.environ.get("ARAM_DEBUG_FIT"):
            print("  fit: content", content, "chrome", chrome, "limit", limit)
        if box and total > limit and not final and dock["hfit"] > MIN_HFIT + 0.01:
            # antetul (chrome) nu se scaleaza, deci raportul se face pe continut
            dock["hfit"] = max(MIN_HFIT, dock["hfit"] * max(1, limit - chrome) / content * 0.97)
            update_fit()
            return True
        # inaltimea urmeaza continutul (cat mai putin loc), plafonata la inaltimea
        # hartii; latimea umple golul (dock_base)
        shown_h = max(1, min(content, limit - chrome))
        body_wrap.configure(height=shown_h)
        root.update_idletasks()
        place(chrome + shown_h)
        return False

    def close_app():
        champ_reader.stop.set()
        pin_bar.hide()
        lcu_mon.stop.set()
        ingame_mon.stop.set()
        bar.hide()          # banda e alta fereastra; altfel ramane pe ecran
        anvil_bar.hide()
        root.destroy()

    def restart_into_update(_=None):
        """Porneste exe-ul nou (deja pe disc) si inchide procesul vechi.

        Il lanseaza explorer.exe, nu noi: procesul nou nu e copilul unuia care
        dispare (de asta se plangea Vanguard). Portul-santinela se elibereaza
        inainte, altfel instanta noua ar crede ca ruleaza deja una.
        """
        if not UPDATE["tag"] or not updater.is_frozen():
            return
        _lock_socket.close()
        import subprocess
        subprocess.Popen(["explorer.exe", sys.executable])
        close_app()

    report = {"win": None}

    def open_report(_=None):
        # o singura fereastra de raport deschisa odata
        if report["win"] is not None and report["win"].winfo_exists():
            report["win"].lift()
            return
        report["win"] = bug_report.open_dialog(
            root, {"bg": BG, "gold": GOLD, "line": LINE, "edge": EDGE, "card": CARD,
                   "text": TEXT, "dim": DIM, "accent": ACCENT, "down": DOWN,
                   "heading": pix, "body": mono, "px": px},
            VERSION, LOG_DIR, lcu_mon, ingame_mon)

    bug.bind("<Button-1>", open_report)

    def check_update(_=None):
        if UPDATE["tag"]:
            restart_into_update()     # deja instalat: click = treci pe el acum
            return
        if UPDATE["busy"]:
            return
        UPDATE["busy"] = True
        version.configure(text="...")

        def work():
            try:
                _, UPDATE["why"] = install_update()
            except Exception as e:
                UPDATE["why"] = f"eroare: {type(e).__name__}"
            UPDATE["busy"] = False
        threading.Thread(target=work, daemon=True).start()

    version.bind("<Button-1>", check_update)
    attach_tip(version, f"Versiunea {VERSION}", "Click: cauta si instaleaza acum o versiune noua.")

    def toggle_aug(_=None):
        aug_view["on"] = not aug_view["on"]
        aug_btn.configure(fg=ACCENT if aug_view["on"] else GOLD)
        shown["fingerprint"] = None

    aug_btn.bind("<Button-1>", toggle_aug)
    attach_tip(aug_btn, "Top augmente",
               "Cele mai bune augmente pentru campionul tau, cand insignele nu apar pe carduri.")
    draw_bug()
    attach_tip(bug, "Raporteaza un bug", "Trimite ce vede aplicatia acum, ca sa pot repara.")

    def snap_back(_=None):
        dock["manual"], dock["last"] = None, None
        settings.set("away", None)
        place(root.winfo_height())
    snap.bind("<Button-1>", snap_back)
    attach_tip(snap, "Aseaza in gol",
               "Pune panoul inapoi intre HUD si minimap. Il poti trage si pe alt ecran: ramane acolo.")
    update_note.bind("<Button-1>", restart_into_update)
    attach_tip(update_note, "Versiune noua instalata",
               "Click: reporneste pe ea acum. In afara meciului se reporneste singura.")
    close.bind("<Button-1>", lambda _: close_app())
    minimize.bind("<Button-1>", lambda _: toggle_collapsed())
    root.bind("<Escape>", lambda _: close_app())
    root.protocol("WM_DELETE_WINDOW", close_app)

    # pozitia ferestrei se retine intre sesiuni: o asezi o data unde vrei
    def remember_pos(_=None):
        dock["drag"] = False
        if not dock.get("moved"):
            return              # doar un click pe titlu: nu schimbam nimic
        dock["moved"] = False
        box = game_box()
        if box is not None or dock["manual"] is not None:
            # in meci (sau mutat in timpul lui): ramane exact unde l-ai lasat,
            # pana porneste meciul urmator
            dock["manual"] = (root.winfo_x(), root.winfo_y())
            dock["last"] = None
            if box is not None:
                # mijlocul panoului in afara jocului = l-ai scos pe alt ecran:
                # il tinem acolo si la meciurile urmatoare, pana apesi pe "\u25c7"
                cx = root.winfo_x() + root.winfo_width() // 2
                cy = root.winfo_y() + root.winfo_height() // 2
                outside = not (box[0] <= cx < box[2] and box[1] <= cy < box[3])
                settings.set("away", list(dock["manual"]) if outside else None)
            return
        tgt = client_target(root.winfo_height())
        if tgt:
            x, y, H = tgt
            settings.set("client_offset", [round((root.winfo_x() - x) / H, 4),
                                           round((root.winfo_y() - y) / H, 4)])
            dock["last"] = None
            return
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
    show_in_taskbar(root)
    refresh()
    update_bars()
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

    # champ select: numele de campioni se cauta pe cuvinte intregi
    assert champ_ocr.find_names("Pick Sett or Jinx, Vi too", ["Sett", "Jinx", "Vi", "Jax"])         == ["Sett", "Jinx"]

    # OCR-ul real functioneaza si in exe (winrt e incarcat dinamic): desenam un
    # nume cu un font de sistem, il citim si il recunoastem
    import ocr_augments
    from PIL import Image, ImageDraw, ImageFont
    pic = Image.new("RGB", (520, 120), (20, 26, 40))
    ImageDraw.Draw(pic).text((20, 30), "Goliath  Eureka", fill=(240, 230, 210),
                             font=ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 44))
    read = ocr_augments.read_offer(pic, names)[0]
    assert "Goliath" in read or "Eureka" in read, f"OCR nu citeste nimic: {read}"

    updater.selfcheck()


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


UPDATE_EVERY = 30 * 60      # secunde intre verificari cat timp aplicatia ruleaza
UPDATE = {"tag": None, "busy": False, "why": None}   # tag = versiunea instalata, asteapta repornirea
UPDATE_LOCK = threading.Lock()


def install_update():
    """(tag, motiv). Serializat: butonul de update si verificarea periodica nu
    descarca de doua ori, si nimic nu se reinstaleaza dupa ce s-a instalat."""
    with UPDATE_LOCK:
        if UPDATE["tag"]:
            return UPDATE["tag"], None
        tag, why = updater.update_if_available(VERSION)
        UPDATE["tag"] = tag
        return tag, why


def maintenance():
    """Date noi si update de exe, in fundal: la pornire si apoi la fiecare
    UPDATE_EVERY, chiar daca aplicatia sta deschisa toata ziua.

    Exe-ul nou se pune pe disc pe loc (Windows lasa redenumirea celui care
    ruleaza); panoul arata "UPDATE" in bara de titlu si il folosesti de la
    urmatoarea deschidere. Nu repornim singuri: un proces lansat de altul care
    apoi dispare il face pe Vanguard sa se planga, si nici nu vrei asta in meci.
    Orice esec inseamna doar ca mergem mai departe: fara internet trebuie sa mearga.
    """
    while UPDATE["tag"] is None:
        try:
            data_sync.sync(LOG_DIR / "data-sync")
        except Exception:
            pass
        try:
            install_update()
        except Exception:
            pass
        if UPDATE["tag"] is None:
            time.sleep(UPDATE_EVERY)


def main():
    if "--selfcheck" in sys.argv:
        selfcheck()
        return

    enable_dpi_awareness()
    be_lightweight()
    try:
        # identitate proprie in taskbar: se grupeaza si se fixeaza (pin) separat
        # de python.exe, cu iconita exe-ului
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Joltarise.AramMayhemHelper")
    except Exception:
        pass
    if already_running():
        return

    # tier-uri si statistici mai noi din repo: copia sincronizata sta langa exe
    # si e citita la importul modulelor, deci o noua copie se vede la pornirea
    # urmatoare. Sincronizarea ruleaza in fundal (vezi maintenance mai jos).
    import os
    os.environ["ARAM_DATA_DIR"] = str(LOG_DIR / "data-sync")

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

    root = build_ui(lcu, lcu_mon, ingame, ingame_mon)
    if "--no-update" not in sys.argv:
        threading.Thread(target=maintenance, daemon=True).start()
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
