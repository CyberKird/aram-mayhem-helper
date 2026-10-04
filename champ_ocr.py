"""Citeste prin OCR campionii din cartile tale personale din champ select.

LCU da campionul atribuit si bench-ul comun, dar nu cartile pe care ti le ofera
personal inainte sa intre in pool-ul comun. Pe ele le citim de pe ecranul
clientului, cu acelasi OCR ca la augmente (ocr_augments).

Zona nu e calibrata pe o captura reala de champ select: citim toata fereastra
clientului si cautam numele campionilor in text. De aceea:
  - ignoram campionul tau si pe cei de pe bench (LCU ii stie deja exact);
  - un nume trebuie sa apara in doua citiri la rand ca sa fie afisat;
  - cautam doar potriviri exacte, pe cuvinte intregi.
Ruleaza doar cat esti in champ select cu clientul in prim-plan.
"""

import asyncio
import re
import threading

import win32gui

MIN_NAME = 3          # "Vi" ar aparea in orice text; sub 3 litere nu cautam
MAX_OFFERS = 6
INTERVAL = 1.5        # secunde intre citiri; champ select dureaza ~1 minut


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def find_names(text, names):
    """Numele de campioni din text, in ordinea in care apar."""
    hay = _norm(text)
    hits = []
    for name in names:
        key = _norm(name)
        if len(key) < MIN_NAME:
            continue
        m = re.search(rf"\b{re.escape(key)}\b", hay)
        if m:
            hits.append((m.start(), name))
    return [n for _, n in sorted(hits)]


class ChampSelectReader:
    def __init__(self, champion_names, active, known):
        """active(): True cat timp e champ select. known(): numele deja afisate din LCU."""
        self.names = sorted(set(champion_names))
        self.active = active
        self.known = known
        self.offers = []
        self.stop = threading.Event()
        self._prev = set()

    def run(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.stop.is_set():
            if self.active():
                try:
                    self._cycle()
                except Exception:
                    pass        # OCR-ul de aici e un plus, nu opreste aplicatia
            elif self.offers:
                self.offers, self._prev = [], set()
            self.stop.wait(INTERVAL)

    def _cycle(self):
        import ocr_augments      # lazy: ingame-app intra in sys.path dupa import-ul asta
        hwnd = ocr_augments.find_game_window()
        if hwnd is None or win32gui.GetForegroundWindow() != hwnd:
            return          # nu citim alte ferestre peste client
        img = ocr_augments.grab(ocr_augments.game_rect(hwnd))
        text = asyncio.run(ocr_augments._ocr_bytes(ocr_augments.encode(img)))
        skip = set(self.known())
        found = [n for n in find_names(text, self.names) if n not in skip][:MAX_OFFERS]
        stable = [n for n in found if n in self._prev]
        self._prev = set(found)
        self.offers = stable
