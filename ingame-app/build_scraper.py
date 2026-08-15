"""Scrape lenes al build-ului de campion, de pe u.gg, printr-un browser real.

u.gg nu pune id-uri de itemi in DOM -- deseneaza fiecare item dintr-un sprite
sheet prin `background-position`. Coordonatele alea sunt exact cele publicate
de Data Dragon in item.json (vezi build_item_sprites.py), deci maparea
inversa e exacta, nu ghicita.

API-ul intern al u.gg (stats2.u.gg) e in spatele unui Cloudflare challenge si
nu raspunde la cereri simple; un browser real (Playwright headless) il trece
fara probleme, la fel cum ar face orice utilizator normal.
"""

import json
import pathlib
import re

DATA = pathlib.Path(__file__).with_name("data")
SPRITES = json.loads((DATA / "item-sprites.json").read_text(encoding="utf-8"))
BUILDS_DIR = DATA / "builds"

SECTIONS = {
    "starting": "Starting Items",
    "core": "Core Items",
    "fourth": "Fourth Item Options",
    "fifth": "Fifth Item Options",
    "sixth": "Sixth Item Options",
}

EXTRACT_JS = """(sections) => {
  function parse(el){
    const s = el.getAttribute('style') || '';
    const sp = (s.match(/img\\/sprite\\/([a-z0-9]+)\\./i) || [])[1];
    const p = s.match(/background-position:\\s*(-?\\d+)px\\s+(-?\\d+)px/);
    return (sp && p) ? sp + '|' + Math.abs(+p[1]) + ',' + Math.abs(+p[2]) : null;
  }
  const out = {};
  for (const [key, want] of Object.entries(sections)) {
    const label = [...document.querySelectorAll('div')].find(e => e.textContent.trim() === want);
    // ancoram pe containerul sectiunii (.content-section_content starting-items,
    // .core-items, .item-options-N), nu pe nextElementSibling: blocul de
    // win-rate se incarca asincron si uneori ia locul listei de itemi, deci
    // acelasi campion putea da rezultate diferite de la o rulare la alta
    const list = label && label.closest('div[class*="content-section_content"]');
    out[key] = list
      ? [...list.querySelectorAll('div[style*="background-image"]')].map(parse).filter(Boolean)
      : [];
  }

  // summoner spells nu sunt in sprite sheet, sunt <img> normale cu alt text
  // ("Summoner Spell Flash") -- mult mai simplu decat itemii, fara mapare.
  const spellImgs = document.querySelectorAll('.summoner-spells img');
  out.summoners = [...spellImgs]
    .map(img => (img.alt || '').replace('Summoner Spell ', '').trim())
    .filter(Boolean);

  return out;
}"""

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


# slug-ul "strip tot ce nu e alfanumeric" nimereste u.gg pentru 171/173
# campioni. Astia doi sunt exceptiile confirmate manual (u.gg foloseste
# numele scurt Riot, nu numele complet afisat): "nunuwillump-aram" si
# "renataglasc-aram" dau 404 real, nu blocaj Cloudflare.
_SLUG_OVERRIDES = {"nunu & willump": "nunu", "renata glasc": "renata"}


def slug(champion):
    override = _SLUG_OVERRIDES.get(champion.lower())
    if override:
        return override
    return re.sub(r"[^a-z0-9]", "", champion.lower())


def resolve_coords(coords):
    names = []
    for coord in coords:
        sprite, xy = coord.split("|")
        name = SPRITES.get(sprite, {}).get(xy)
        if name:
            names.append(name)
    return names


def cache_path(champion):
    return BUILDS_DIR / f"{slug(champion)}.json"


def load_cached(champion):
    path = cache_path(champion)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def scrape(champion, headless=True):
    """Build-ul unui campion de pe u.gg. Scrie in cache si intoarce dict-ul.

    Playwright se importa aici, nu la nivelul modulului: load_cached() si
    cache_path() sunt folosite de aplicatia normala (fara scraping deloc),
    iar un import la nivel de modul ar cere Playwright instalat si pentru
    cine doar citeste cache-ul deja adus -- inclusiv exe-ul distribuit.
    """
    from playwright.sync_api import sync_playwright

    url = f"https://u.gg/lol/champions/aram/{slug(champion)}-aram"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(user_agent=_UA)
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1500)
            raw = page.evaluate(EXTRACT_JS, SECTIONS)
        finally:
            browser.close()

    build = {"champion": champion, "source": url,
             "summoners": raw.get("summoners") or []}
    pool, seen = [], set()
    for key, coords in raw.items():
        if key == "summoners":
            continue   # nume simple, nu coordonate de sprite -- deja pus mai sus
        names = resolve_coords(coords)
        build[key] = names
        for n in names:
            if n not in seen:
                seen.add(n)
                pool.append(n)
    build["pool"] = pool

    if not pool:
        return None  # nu risipim cache-ul cu un build gol (patch/layout schimbat)

    cache_path(champion).write_text(json.dumps(build, indent=1, ensure_ascii=False),
                                     encoding="utf-8")
    return build


def get_build(champion, headless=True):
    """Build-ul din cache, sau il aduce acum daca lipseste."""
    cached = load_cached(champion)
    if cached:
        return cached
    return scrape(champion, headless=headless)
