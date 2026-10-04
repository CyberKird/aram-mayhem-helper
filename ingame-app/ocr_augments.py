"""Citeste augment-urile oferite in joc prin OCR, fara Overwolf.

Nu exista alt API local pentru asta (Live Client Data API nu expune deloc
alegerile de augment). Foloseste OCR-ul nativ din Windows (Windows.Media.Ocr,
acelasi motor ca in Snipping Tool / PowerToys) -- nimic de instalat separat.

Strategie: captam ZONA CENTRALA a ferestrei jocului (vezi OFFER_REGION), o
trecem prin OCR si cautam numele celor 206 augmente cunoscute in text.

Zona, nu tot ecranul: numele augmentelor apar si in HUD dupa ce le alegi, iar
citind tot ecranul nu aveam cum sa deosebim "mi se ofera acum" de "am ales
acum cinci minute" -- lista ramanea afisata permanent si impingea build-ul
afara. Marginile taiate scot HUD-ul, kill feed-ul si bara de scor.

Ca bonus, zona mai mica e si mai rapida. Zona a fost confirmata pe o captura
reala de oferta (toate cele 3 carduri incap cu margini). Daca vreodata trebuie
recalibrata, ARAM_DEBUG_OFFER=1 salveaza in LAST_OFFER exact ce s-a citit.
"""

import asyncio
import difflib
import io
import os
import pathlib
import re

import mss
import win32api
import win32con
import win32gui
from PIL import Image
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

GAME_WINDOW_TITLES = ("League of Legends (TM) Client", "League of Legends")

_engine = None


def find_game_window():
    """hwnd-ul ferestrei jocului, sau None.

    Cu 3 monitoare nu avem cum sa ghicim pe care e League -- cautam fereastra
    dupa titlu si captam exact zona ei, indiferent pe ce ecran e.
    """
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if any(t in title for t in GAME_WINDOW_TITLES):
            found.append((hwnd, title))

    win32gui.EnumWindows(visit, None)
    # "League of Legends" e si titlul clientului: cand sunt deschise amandoua,
    # jocul ("... (TM) Client") trebuie sa castige, altfel panoul se lipeste de
    # fereastra gresita
    found.sort(key=lambda f: "(TM) Client" not in f[1])
    return found[0][0] if found else None


def find_client_window():
    """hwnd-ul clientului League (champ select, lobby), sau None."""
    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == "League of Legends":
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else None


def game_rect(hwnd):
    """(left, top, right, bottom) al ZONEI DE JOC, in coordonate de ecran.

    Zona client, nu fereastra: in modul fereastra, bara de titlu si chenarele
    intra in GetWindowRect si decaleaza toate fractiunile din OFFER_REGION.
    Pe borderless/fullscreen cele doua coincid, deci nu strica nimic acolo.
    """
    try:
        left, top = win32gui.ClientToScreen(hwnd, (0, 0))
        _, _, w, h = win32gui.GetClientRect(hwnd)
        if w > 0 and h > 0:
            return (left, top, left + w, top + h)
    except Exception:
        pass
    return win32gui.GetWindowRect(hwnd)


def find_game_window_rect():
    """(left, top, right, bottom) al zonei de joc, sau None."""
    hwnd = find_game_window()
    return game_rect(hwnd) if hwnd else None


def game_is_focused():
    """True daca League e chiar fereastra din fata.

    Capturam ecranul, nu continutul ferestrei, deci orice fereastra pusa
    peste joc intra in poza. Cand te uiti pe u.gg in browser, OCR-ul citea
    tier list-ul de acolo si il raporta ca "oferta" -- de aici augmentele
    care pareau inventate. Daca jocul nu e in fata, nu are rost sa citim.
    """
    hwnd = find_game_window()
    return bool(hwnd) and win32gui.GetForegroundWindow() == hwnd


def _get_engine():
    global _engine
    if _engine is None:
        _engine = OcrEngine.try_create_from_language(Language("en")) \
            or OcrEngine.try_create_from_user_profile_languages()
    return _engine


async def _ocr_bytes(png_bytes):
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = _get_engine()
    if engine is None:
        return ""
    result = await engine.recognize_async(bitmap)
    return result.text


async def _ocr_lines(png_bytes):
    """(text, [(text_linie, x1, y1, x2, y2)]) -- liniile cu chenarul lor, in pixeli
    de imagine. Folosit ca sa aflam UNDE sta fiecare nume pe ecran."""
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = _get_engine()
    if engine is None:
        return "", []
    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        words = [w.bounding_rect for w in line.words]
        if words:
            lines.append((line.text,
                          min(r.x for r in words), min(r.y for r in words),
                          max(r.x + r.width for r in words), max(r.y + r.height for r in words)))
    return result.text, lines


# Sub inaltimea asta nu mai micsoram: pe rezolutii mici textul augmentelor
# ar deveni prea marunt pentru OCR. Peste ea, micsorarea e castig curat.
MIN_OCR_HEIGHT = 600


def grab(rect):
    """Imagine PIL a unei zone (left, top, right, bottom), pe orice monitor,
    deja micsorata cat trebuie pentru OCR.

    reduce(k) inainte de encode: la 4K zona are 1252px inaltime, mult peste
    cat ii trebuie OCR-ului. Injumatatirea scade si encode-ul (64->48ms) si
    OCR-ul (141->37ms), fara nicio pierdere de recunoastere -- verificat pe
    o captura reala de oferta. Factorul se adapteaza la rezolutie, ca sa nu
    stricam citirea pe ecrane mici.
    """
    left, top, right, bottom = rect
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top,
                         "width": right - left, "height": bottom - top})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    k = max(1, img.height // MIN_OCR_HEIGHT)
    img = img.reduce(k) if k > 1 else img
    img.info["reduce"] = k      # pozitiile din OCR se inmultesc cu el ca sa dea pixeli reali
    return img


def encode(img):
    """BMP, nu PNG: compresia PNG lua ~390ms per ciclu doar ca sa micsoreze un
    fisier pe care il trimitem oricum in RAM. BMP e tot fara pierderi si se
    scrie in cateva zeci de ms."""
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def capture_region(rect):
    """Bytes de imagine ai unei zone, pentru OCR pe tot textul zonei."""
    return encode(grab(rect))


def enhance(img):
    """Variant mai usor de citit pentru fonturi decorative: gri, contrast
    intins si marit 1.5x. Folosit doar la a doua trecere, cand prima a citit
    doar o parte din carduri."""
    from PIL import ImageOps
    gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=2)
    return gray.resize((int(gray.width * 1.5), int(gray.height * 1.5)),
                       Image.LANCZOS).convert("RGB")


def _norm(text):
    """Text -> litere/cifre si spatii simple, ca sa comparam mere cu mere."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


_key_cache = (None, None)


def _augment_keys(augment_names):
    """{nume: nume normalizat}, calculat o singura data pentru aceeasi lista.

    Normalizarea celor 206 nume la fiecare ciclu de OCR lua ~150ms degeaba --
    lista nu se schimba niciodata in timpul unui meci.
    """
    global _key_cache
    if _key_cache[0] is not augment_names:
        keys = {}
        for name in augment_names:
            key = _norm(name)
            if len(key) >= 4:   # numele foarte scurte dau prea multe fals-pozitive
                keys[name] = key
        _key_cache = (augment_names, keys)
    return _key_cache[1]


def match_augments(lines, augment_names, cutoff=0.82):
    """Text de OCR -> nume de augment cunoscute.

    Cautam numele INAUNTRUL textului, nu comparam linie cu linie: Windows OCR
    intoarce des tot ecranul de augmente ca o singura linie de sute de
    caractere (nume + descriere lipite), iar o astfel de linie nu semana
    niciodata cu un nume de 2 cuvinte -- de aceea nu gasea nimic.

    Doua treceri: intai subsir exact (cazul normal), apoi fuzzy pe ferestre
    de cuvinte de aceeasi lungime, pentru literele pe care OCR-ul le greseste.
    """
    haystack = _norm(" ".join(lines))
    if not haystack:
        return []
    words = haystack.split()

    keys = _augment_keys(augment_names)

    hits = {}   # nume -> pozitia in text, ca sa le dam in ordinea de pe ecran

    for name, key in keys.items():
        # \b obligatoriu: fara el, "Invulnerability" din magazinul de itemi
        # continea augmentul "Vulnerability" si il raporta ca oferit
        m = re.search(rf"\b{re.escape(key)}\b", haystack)
        if m:
            hits[name] = m.start()

    # Trecerea fuzzy e si scumpa (~130ms) si singura sursa de fals-pozitive,
    # deci o sarim cand potrivirea exacta a gasit deja o oferta plauzibila.
    # Pragul ramane 0.82: mai strict (0.86) pierde greseala tipica de OCR --
    # "GoIiath" cu I mare in loc de l da exact 0.857.
    if len(hits) < 2:
        for name, key in keys.items():
            if name in hits:
                continue
            n = len(key.split())
            for i in range(len(words) - n + 1):
                window = " ".join(words[i:i + n])
                # Diferenta de lungime max 1 caracter. Greselile de OCR sunt
                # substitutii ("0k" in loc de "ok", "GoIiath" in loc de
                # "Goliath"), deci pastreaza lungimea. Fara pragul asta,
                # "Torment" (item din magazin) trecea drept augmentul
                # "Tormentor" cu scor 0.875, peste cutoff.
                if abs(len(window) - len(key)) > 1:
                    continue
                if difflib.SequenceMatcher(None, window, key).ratio() >= cutoff:
                    hits[name] = haystack.find(window)
                    break

    return [n for n, _ in sorted(hits.items(), key=lambda kv: kv[1])]


MAX_OFFER = 3      # o oferta are exact 3 carduri

# Fractiuni din fereastra jocului in care apare fereastra de alegere.
# Numele augmentelor apar si in HUD dupa ce alegi (sus/jos, langa portret),
# iar cu tot ecranul citit nu aveam cum sa deosebim "oferta acum" de "ce am
# ales acum 5 minute" -- lista ramanea afisata permanent. Marginile taiate
# scot HUD-ul, kill feed-ul de jos-stanga si bara de scor de sus.
OFFER_REGION = (0.10, 0.20, 0.90, 0.78)   # left, top, right, bottom

# ultima captura din care chiar am recunoscut augmente, pentru calibrare:
# daca zona de mai sus se dovedeste gresita, aici se vede exact ce s-a citit
LAST_OFFER = pathlib.Path(__file__).with_name("data") / "_last_offer.bmp"
DEBUG_OFFER = os.environ.get("ARAM_DEBUG_OFFER") == "1"


_scale = None


def dpi_scale():
    """Pixeli reali / coordonate raportate de Windows.

    Procesul nu e DPI-aware, deci pe un ecran cu scalare peste 100% Windows
    da coordonate "logice" mai mici decat pixelii pe care ii vede mss, si
    zona capturata ar fi decalata. La scalare 100% iese 1.0 si nu schimba
    nimic. Calculat o singura data: nu se schimba in timpul unui meci.
    """
    global _scale
    if _scale is None:
        with mss.mss() as sct:
            physical = sct.monitors[0]["width"]
        logical = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        _scale = (physical / logical) if logical else 1.0
    return _scale


def offer_region(rect):
    """Zona centrala a ferestrei jocului, in pixeli reali de ecran.

    Fractiuni, nu pixeli ficsi: merge la orice rezolutie si orice raport
    de aspect, pentru ca se raporteaza mereu la fereastra jocului.
    """
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    fl, ft, fr, fb = OFFER_REGION
    s = dpi_scale()
    return (int((left + w * fl) * s), int((top + h * ft) * s),
            int((left + w * fr) * s), int((top + h * fb) * s))


CARDS = 3


def match_card(text, augment_names, cutoff=0.82):
    """Textul unui singur card -> numele augmentului lui, sau None.

    Un card are exact un augment, deci aici alegem unul, nu o lista. Daca
    descrierea pomeneste alt augment, castiga cel mai de sus (numele sta
    deasupra descrierii); la egalitate, cel mai lung. Fuzzy doar cand nu
    exista potrivire exacta, cu aceleasi garduri ca in match_augments.
    """
    haystack = _norm(text)
    if not haystack:
        return None
    keys = _augment_keys(augment_names)

    best = None   # (pozitie, -lungime, nume)
    for name, key in keys.items():
        m = re.search(r"\b" + re.escape(key) + r"\b", haystack)
        if m:
            cand = (m.start(), -len(key), name)
            if best is None or cand < best:
                best = cand
    if best:
        return best[2]

    words = haystack.split()
    fuzzy = None  # (-scor, pozitie, nume)
    for name, key in keys.items():
        n = len(key.split())
        for i in range(len(words) - n + 1):
            window = " ".join(words[i:i + n])
            if abs(len(window) - len(key)) > 1:
                continue
            score = difflib.SequenceMatcher(None, window, key).ratio()
            if score >= cutoff:
                cand = (-score, i, name)
                if fuzzy is None or cand < fuzzy:
                    fuzzy = cand
    return fuzzy[2] if fuzzy else None


# Un titlu de card e un rand scurt, aproape doar numele, centrat pe card. Textul
# din shop sau din tooltip-ul unui item (hover) pomeneste si el nume de augmente,
# dar in mijlocul unor propozitii lungi, aliniate la stanga. Fara filtrul asta,
# un hover peste iteme parea o oferta de augmente.
TITLE_EXTRA = 8        # cate caractere in plus fata de nume tolereaza randul
CENTER_TOL = 0.18      # cat de departe de centrul benzii poate sta titlul (din latime)
ALIGN_TOL = 0.04       # cat pot diferi pe verticala titlurile celor 3 carduri (din inaltime)


def match_title(lines, augment_names, width=None, cutoff=0.82):
    """(nume, linie) din randurile OCR ale unui card, doar daca numele e titlul
    lui: rand scurt (sau doua randuri consecutive, numele lungi se rup) si,
    cand stim latimea benzii, centrat pe ea. Altfel (None, None)."""
    rows = [l for l in lines
            if width is None or abs((l[1] + l[3]) / 2 - width / 2) <= CENTER_TOL * width]
    cands = [(l[0], l) for l in rows]
    cands += [(a[0] + " " + b[0], a) for a, b in zip(rows, rows[1:])]
    for text, line in cands:
        name = match_card(text, augment_names, cutoff)
        if name and len(_norm(text)) <= len(_norm(name)) + TITLE_EXTRA:
            return name, line
    return None, None


def aligned(found, centers, height):
    """Titlurile adevarate stau pe acelasi rand; daca nu, nu e o oferta."""
    ys = [c[1] for f, c in zip(found, centers) if f and c]
    return len(ys) < 2 or max(ys) - min(ys) <= ALIGN_TOL * height


def split_cards(img):
    """Imaginea zonei de oferta -> cele 3 coloane de carduri, de la stanga."""
    w = img.width
    return [img.crop((w * i // CARDS, 0, w * (i + 1) // CARDS, img.height))
            for i in range(CARDS)]


async def _ocr_many_lines(images):
    return [await _ocr_lines(encode(i)) for i in images]


# Ultima citire, pentru bug report: ce a vazut OCR-ul si de ce a ales ce a ales.
# Un dict nou la fiecare ciclu (nu se modifica pe loc), deci e sigur de citit
# din alt fir fara lock.
last_read = {"status": "", "texts": [], "matches": []}


def read_offer(img, augment_names):
    """Imaginea zonei -> ([nume sau None pe card], [text brut], [centrul numelui sau None]).

    A doua trecere (contrast crescut) ruleaza doar cand prima a gasit macar un
    card dar nu pe toate: atunci e aproape sigur o oferta cu un nume prost
    citit. Pe un ecran fara oferta n-o rulam, ar dubla costul degeaba.
    Centrele (in pixeli de imagine) servesc la invatarea asezarii cardurilor.
    """
    cards = split_cards(img)
    read = asyncio.run(_ocr_many_lines(cards))
    texts = [t for t, _ in read]
    hits = [match_title(lines, augment_names) for _, lines in read]
    found = [n for n, _ in hits]
    offsets = [img.width * i // CARDS for i in range(CARDS)]
    centers = [((l[1] + l[3]) / 2 + offsets[i], (l[2] + l[4]) / 2) if l else None
               for i, (_, l) in enumerate(hits)]

    if 0 < sum(f is not None for f in found) < CARDS:
        retry = asyncio.run(_ocr_many_lines([enhance(c) for c in cards]))
        for i, (t, lines) in enumerate(retry):
            if found[i] is None:
                found[i] = match_title(lines, augment_names)[0]
                texts[i] = (texts[i] + " | " + t).strip(" |")
    if not aligned(found, centers, img.height):
        found = [None] * CARDS
    return found, texts, centers


# ---------------------------------------------------------------------------
# Asezarea cardurilor, invatata din prima oferta citita.
#
# Prima citire OCR-izeaza toata zona (~350 ms) si afla unde sta numele fiecarui
# card. De acolo incolo citim doar trei benzi inguste, fix la acele locuri: de
# ~6 ori mai putine pixeli, deci o citire dureaza cateva zeci de ms. Asezarea se
# tine ca fractiuni din fereastra jocului, deci ramane valabila pana se schimba
# rezolutia. Daca citirea rapida nu mai gaseste cardurile (alt layout), cade
# singura pe citirea completa si reinvata.
# ---------------------------------------------------------------------------

_idle_fast = 0
IDLE_FULL_EVERY = 8    # la cate citiri rapide goale facem una completa

_layout = None      # {"size": (W, H), "fx": [3 x fractie din W], "fy": fractie din H}

BAND_HALF_W = 0.17     # jumatate din latimea benzii, ca fractie din inaltimea jocului
BAND_HALF_H = 0.05     # jumatate din inaltimea ei
CARD_TOP = 0.229       # de la numele augmentului pana la varful cardului, din inaltimea jocului
# Asezarea implicita, masurata pe o captura reala de oferta (in fractii din
# inaltimea jocului, deci la fel pe orice rezolutie 16:9 sau ultrawide): titlurile
# stau la 0.407 din inaltime, iar centrele cardurilor la 0.35 una de alta.
# Prima citire completa o inlocuieste cu cea invatata.
DEFAULT_FY, DEFAULT_STEP = 0.407, 0.35


def layout_for(W, H):
    """Asezarea invatata daca e pentru marimea asta de fereastra, altfel cea implicita."""
    lay = _layout
    if lay and lay["size"] == (W, H):
        return lay
    d = DEFAULT_STEP * H / W
    return {"size": (W, H), "fx": [0.5 - d, 0.5, 0.5 + d], "fy": DEFAULT_FY}


def learn_layout(rect, region_left, region_top, k, centers):
    """Retine unde sunt cardurile, din centrele numelor citite (>= 2 carduri)."""
    global _layout
    known = [(i, c) for i, c in enumerate(centers) if c]
    if len(known) < 2:
        return
    left, top, right, bottom = rect
    W, H = right - left, bottom - top
    fx = {i: (region_left + c[0] * k - left) / W for i, c in known}
    fy = sum((region_top + c[1] * k - top) / H for _, c in known) / len(known)
    (i, xi), (j, xj) = list(fx.items())[0], list(fx.items())[-1]
    step = (xj - xi) / (j - i)
    _layout = {"size": (W, H), "fx": [xi + step * (n - i) for n in range(CARDS)], "fy": fy}


def read_fast(rect, augment_names):
    """Citire doar pe benzile cardurilor (asezarea invatata sau cea implicita). ([nume|None], [text])."""
    left, top, right, bottom = rect
    W, H = right - left, bottom - top
    lay = layout_for(W, H)
    hw, hh = int(BAND_HALF_W * H), int(BAND_HALF_H * H)
    cy = top + lay["fy"] * H
    x0 = int(left + lay["fx"][0] * W - hw)
    x1 = int(left + lay["fx"][-1] * W + hw)
    strip = grab((x0, int(cy - hh), x1, int(cy + hh)))
    bands = []
    for fx in lay["fx"]:
        cx = int(left + fx * W) - x0
        bands.append(strip.crop((max(0, cx - hw), 0, min(strip.width, cx + hw), strip.height)))
    read = asyncio.run(_ocr_many_lines(bands))
    found = [match_title(lines, augment_names, band.width)[0]
             for (_, lines), band in zip(read, bands)]
    return found, [t for t, _ in read]


def augment_region(rect):
    """(l, t, r, b) in care sta oferta, pentru banda de tier. Din asezarea invatata
    cand o avem (cardurile reale), altfel zona implicita."""
    left, top, right, bottom = rect
    W, H = right - left, bottom - top
    lay = layout_for(W, H)
    step = (lay["fx"][-1] - lay["fx"][0]) / (CARDS - 1) * W
    l = left + lay["fx"][0] * W - step / 2
    return (int(l), int(top + (lay["fy"] - CARD_TOP) * H), int(l + step * CARDS), bottom)


def detect_offered_augments(augment_names, min_matches=2):
    """(nume_gasite, status) -- status explica de ce lista poate fi goala,
    ca UI-ul sa nu ramana tacut cand OCR-ul nu prinde nimic.

    min_matches=2 nu e capriciu: HUD-ul afiseaza permanent augmentele deja
    alese, deci un singur nume gasit pe ecran inseamna aproape sigur HUD, nu
    o oferta noua. Cu pragul la 1 lista se umplea si nu se mai golea, iar
    build-ul era impins in afara ferestrei.
    """
    global last_read
    hwnd = find_game_window()
    if hwnd is None:
        return [], "n-am gasit fereastra League"
    if win32gui.GetForegroundWindow() != hwnd:
        return [], "jocul nu e in fata (nu citesc alte ferestre)"
    if _get_engine() is None:
        return [], "OCR indisponibil: instaleaza pachetul de limba engleza in Windows"

    rect = game_rect(hwnd)
    img = None
    global _idle_fast
    fast = read_fast(rect, augment_names)
    hits = sum(f is not None for f in fast[0]) if fast else -1
    if hits >= min_matches:
        found, texts = fast
        _idle_fast = 0
    elif hits == 0 and _idle_fast < IDLE_FULL_EVERY:
        # benzile sunt goale: nu e nicio oferta, nu are rost citirea completa
        # (~4x mai scumpa). O facem totusi din cand in cand, in caz ca s-a
        # schimbat asezarea si benzile nu mai cad pe carduri.
        found, texts = fast
        _idle_fast += 1
    else:
        _idle_fast = 0
        region = offer_region(rect)
        img = grab(region)
        found, texts, centers = read_offer(img, augment_names)
        if sum(f is not None for f in found) >= min_matches:
            learn_layout(rect, region[0], region[1], img.info.get("reduce", 1), centers)
    names = [n for n in found if n]
    last_read = {"status": f"{len(names)}/{CARDS}", "texts": texts, "matches": found}

    if not any(t.strip() for t in texts):
        return [], "nicio oferta pe ecran"
    if len(names) < min_matches:
        return [], f"nicio oferta ({sum(len(t.split()) for t in texts)} cuvinte in zona centrala)"

    if DEBUG_OFFER:
        # Scrierea asta e cateva MB pe disc la FIECARE oferta detectata, adica
        # exact in timpul jocului. Zona e deja confirmata pe o captura reala,
        # deci ramane oprita; se aprinde cu ARAM_DEBUG_OFFER=1 daca vreodata
        # trebuie recalibrata.
        try:
            LAST_OFFER.write_bytes(encode(img or grab(offer_region(rect))))
        except OSError:
            pass
    # in ordinea de pe ecran, de la stanga la dreapta
    return names, f"{len(names)} augmente recunoscute"
