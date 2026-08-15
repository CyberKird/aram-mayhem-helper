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
from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

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
            found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else None


def find_game_window_rect():
    """(left, top, right, bottom) al ferestrei jocului, sau None."""
    hwnd = find_game_window()
    return win32gui.GetWindowRect(hwnd) if hwnd else None


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


# Sub inaltimea asta nu mai micsoram: pe rezolutii mici textul augmentelor
# ar deveni prea marunt pentru OCR. Peste ea, micsorarea e castig curat.
MIN_OCR_HEIGHT = 600


def capture_region(rect):
    """Bytes de imagine ai unei zone (left, top, right, bottom), pe orice monitor.

    BMP, nu PNG: compresia PNG lua ~390ms per ciclu doar ca sa micsoreze un
    fisier pe care il trimitem oricum in RAM. BMP e tot fara pierderi si se
    scrie in cateva zeci de ms.

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
    if k > 1:
        img = img.reduce(k)

    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


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


def detect_offered_augments(augment_names, min_matches=2):
    """(nume_gasite, status) -- status explica de ce lista poate fi goala,
    ca UI-ul sa nu ramana tacut cand OCR-ul nu prinde nimic.

    min_matches=2 nu e capriciu: HUD-ul afiseaza permanent augmentele deja
    alese, deci un singur nume gasit pe ecran inseamna aproape sigur HUD, nu
    o oferta noua. Cu pragul la 1 lista se umplea si nu se mai golea, iar
    build-ul era impins in afara ferestrei.
    """
    hwnd = find_game_window()
    if hwnd is None:
        return [], "n-am gasit fereastra League"
    if win32gui.GetForegroundWindow() != hwnd:
        return [], "jocul nu e in fata (nu citesc alte ferestre)"

    img = capture_region(offer_region(win32gui.GetWindowRect(hwnd)))
    text = asyncio.run(_ocr_bytes(img))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [], "nicio oferta pe ecran"

    matches = match_augments(lines, augment_names)
    if len(matches) < min_matches:
        return [], f"nicio oferta ({len(lines)} linii in zona centrala)"

    if DEBUG_OFFER:
        # Scrierea asta e cateva MB pe disc la FIECARE oferta detectata, adica
        # exact in timpul jocului. Zona e deja confirmata pe o captura reala,
        # deci ramane oprita; se aprinde cu ARAM_DEBUG_OFFER=1 daca vreodata
        # trebuie recalibrata.
        try:
            LAST_OFFER.write_bytes(img)
        except OSError:
            pass
    # taiem la 3: mai multe inseamna ca am prins si altceva pe langa oferta,
    # iar o lista lunga impinge build-ul in afara ferestrei
    return matches[:MAX_OFFER], f"{len(matches)} augmente recunoscute"
