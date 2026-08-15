"""Jurnal de diagnostic: ce citeste OCR-ul, la fiecare ciclu, in timp real.

Nu face parte din aplicatie. E pentru cazul in care un augment nu apare in
overlay si vrem sa stim DE CE: textul brut citit de pe ecran, ce s-a potrivit
si ce nu. Fara asta ne uitam pe ecran dupa ce oferta a trecut deja.

    python watch_offers.py            # scrie in data/_offers.log
"""

import asyncio
import json
import pathlib
import time

import augment_tier
import ocr_augments
import win32gui

LOG = pathlib.Path(__file__).with_name("data") / "_offers.log"


def main():
    names = augment_tier.flatten_names(
        json.loads((pathlib.Path(__file__).with_name("data") /
                    "augments-global.json").read_text(encoding="utf-8")))
    keys = ocr_augments._augment_keys(names)

    LOG.write_text(f"start {time.strftime('%H:%M:%S')}\n", encoding="utf-8")
    last = None

    while True:
        hwnd = ocr_augments.find_game_window()
        if hwnd and win32gui.GetForegroundWindow() == hwnd:
            try:
                img = ocr_augments.capture_region(
                    ocr_augments.offer_region(win32gui.GetWindowRect(hwnd)))
                txt = asyncio.run(ocr_augments._ocr_bytes(img))
            except Exception as e:
                txt = f"<EROARE {type(e).__name__}: {e}>"

            hay = ocr_augments._norm(txt)
            # notam doar cand ecranul contine ceva ce SEAMANA cu o oferta:
            # un card de augment are mereu si eticheta de categorie
            interesting = any(w in hay for w in ("damage", "utility", "speed", "tank"))
            if interesting and hay != last:
                last = hay
                matches = ocr_augments.match_augments([txt], names)
                exact = [n for n, k in keys.items() if k in hay]
                with LOG.open("a", encoding="utf-8") as f:
                    f.write(f"\n--- {time.strftime('%H:%M:%S')} ---\n")
                    f.write(f"TEXT : {txt[:500]}\n")
                    f.write(f"EXACT: {exact}\n")
                    f.write(f"FINAL: {matches}\n")
        time.sleep(1.2)


if __name__ == "__main__":
    main()
