"""Citeste shardurile oferite la cumpararea unui Stat Anvil, prin OCR.

Acelasi motiv ca la ocr_augments.py: Stat Anvil n-are niciun API, se cumpara
manual din shop (750g, nivel 9+) si deschide 3 carduri de ales, la fel ca la
augmente -- doar ca fara nivele fixe (3/7/11/15), cumperi cate vrei, cand
vrei. De asta zona centrala se citeste separat de oferta de augment, mai rar
(la 3.6s, nu 1.2s): alegerea nu are countdown care te forteaza, deci nu are
rost sa cheltuim OCR la fel de des ca la augmente.

Zona reutilizeaza OFFER_REGION din ocr_augments -- pe o captura reala de
Stat Anvil, cardurile cad in aceeasi zona centrala ca la oferta de augment.
"""

import asyncio

import win32gui

import ocr_augments

# tag-ul de pe fiecare card ("Stat Anvil") e un semnal aproape sigur ca
# suntem pe ecranul asta si nu pe altceva -- il cerem separat de numele de
# shard, ca sa nu confundam "n-am recunoscut numele" cu "nu e ecranul asta"
_STAT_ANVIL_TAG = "stat anvil"

MAX_SHARDS = 3


def detect_offered_shards(shard_names, min_matches=2):
    """(nume_gasite, status), la fel ca detect_offered_augments."""
    hwnd = ocr_augments.find_game_window()
    if hwnd is None:
        return [], "n-am gasit fereastra League"
    if win32gui.GetForegroundWindow() != hwnd:
        return [], "jocul nu e in fata (nu citesc alte ferestre)"

    img = ocr_augments.capture_region(
        ocr_augments.offer_region(win32gui.GetWindowRect(hwnd)))
    text = asyncio.run(ocr_augments._ocr_bytes(img))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [], "nimic pe ecran"

    haystack = ocr_augments._norm(" ".join(lines))
    if _STAT_ANVIL_TAG not in haystack:
        return [], "nu e ecran de Stat Anvil"

    matches = ocr_augments.match_augments(lines, shard_names)
    if len(matches) < min_matches:
        return [], f"stat anvil pe ecran, dar shard-uri necitite ({len(lines)} linii)"

    return matches[:MAX_SHARDS], f"{len(matches)} shard-uri recunoscute"
