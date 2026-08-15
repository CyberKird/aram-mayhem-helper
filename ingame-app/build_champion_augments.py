"""Aduce tier list-ul de augmente SPECIFIC fiecarui campion, de pe u.gg.

De ce exista fisierul asta: data/augments-global.json e o singura lista
pentru tot modul, deci spunea "Heartsteel = S+" si cand jucai Kalista, pe
care itemul ala nici nu merge. u.gg publica insa un clasament separat pentru
fiecare campion, la /lol/champions/aram-mayhem/<campion>-aram-mayhem.

Pagina aia are DOAR augmente -- build-urile de itemi raman de pe pagina de
ARAM (u.gg nu publica itemi separat pentru Mayhem), vezi build_scraper.py.

Ca si prefetch_builds.py: ruleaza-l INAINTE sa joci, niciodata in timpul
unui meci (porneste un Chromium real).

    python build_champion_augments.py                 # toti campionii
    python build_champion_augments.py Kalista Jinx    # doar unii
    python build_champion_augments.py --headed        # daca Cloudflare blocheaza
"""

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

from build_scraper import slug

DATA = pathlib.Path(__file__).with_name("data")
OUT = DATA / "augments"

TIERS = ["S+", "S", "A", "B", "C", "D"]

# Ancorat pe <section>: cautarea globala dupa eticheta gaseste "B" din
# initiala avatarului de cont inainte sa ajunga la tier-ul B.
EXTRACT_JS = """(tiers) => {
  const res = {};
  for (const sec of document.querySelectorAll('section')) {
    const imgs = [...sec.querySelectorAll('img')]
      .map(i => (i.alt || '').trim()).filter(Boolean);
    if (!imgs.length) continue;
    const label = [...sec.querySelectorAll('*')]
      .find(e => e.children.length === 0 && tiers.includes(e.textContent.trim()));
    if (!label) continue;
    const tier = label.textContent.trim();
    res[tier] = (res[tier] || []).concat(imgs);
  }
  return res;
}"""


def scrape_augments(champion, browser):
    """Fereastra proprie per campion, intentionat.

    Refolosirea aceleiasi file pentru navigari succesive pe u.gg opreste
    randarea dupa prima pagina: paginile urmatoare raman goale si scraper-ul
    se blocheaza. O fila noua de fiecare data costa cateva zecimi de secunda
    si evita complet problema.
    """
    url = f"https://u.gg/lol/champions/aram-mayhem/{slug(champion)}-aram-mayhem"
    page = browser.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        tiers = page.evaluate(EXTRACT_JS, TIERS)
    finally:
        page.close()

    tiers = {t: names for t, names in tiers.items() if names}
    if not tiers:
        return None
    return {"champion": champion, "source": url, "tiers": tiers}


DESC_OUT = DATA / "augment-desc.json"
CDRAGON_ARENA = "https://raw.communitydragon.org/latest/cdragon/arena/en_us.json"
BLITZ = "https://blitz.gg/lol/aram-mayhem-augments"


def build_descriptions(browser):
    """Ce face fiecare augment, din doua surse.

    De ce: u.gg claseaza ~206 augmente, dar exista peste 30 care apar in joc
    si pe care NU le claseaza nimeni -- am cautat pe metasrc, blitz, aramgg,
    arammayhem, niciunul nu le da tier. Pentru alea nu inventam un rank (ar
    arata identic cu unul calculat din milioane de meciuri, dar ar fi doar
    parerea mea). In schimb aratam descrierea, ca sa decizi tu in cele cateva
    secunde cat ai la dispozitie.

    Riot da descrierile structurate; Blitz acopera cateva pe care Riot le
    lasa goale.
    """
    import re
    import urllib.request

    out = {}
    req = urllib.request.Request(CDRAGON_ARENA, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        for a in json.loads(r.read())["augments"]:
            name, desc = a.get("name"), a.get("desc")
            if name and desc:
                clean = re.sub(r"<[^>]+>", "", desc)
                # Datele brute au sabloane nesubstituite (@BonusDamage*100@).
                # Le inlocuim cu "X" in loc sa aruncam descrierea: "Deal X%
                # more damage to enemies below X% health" iti spune tot ce
                # trebuie ca sa alegi, chiar fara cifra exacta.
                clean = re.sub(r"@[^@]+@", "X", clean)
                clean = re.sub(r"\s+", " ", clean).strip()
                if clean:
                    out[name] = clean

    page = browser.new_page()
    try:
        page.goto(BLITZ, wait_until="networkidle", timeout=40000)
        page.wait_for_timeout(4000)
        pairs = page.evaluate("""() => {
          const out = {};
          for (const h of document.querySelectorAll('h3, h4, strong, b')) {
            const name = h.textContent.trim();
            const next = h.nextElementSibling;
            if (name && next && next.textContent.trim().length > 20)
              out[name] = next.textContent.trim();
          }
          return out;
        }""")
        for name, desc in (pairs or {}).items():
            out.setdefault(name, desc)
    except Exception as e:
        print(f"  Blitz: {type(e).__name__} (continui doar cu datele Riot)")
    finally:
        page.close()

    DESC_OUT.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False),
                        encoding="utf-8")
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headed = "--headed" in sys.argv

    champs = args or list(json.loads(
        (DATA / "champion-tags.json").read_text(encoding="utf-8")).keys())
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"aduc augmente pentru {len(champs)} campioni...")
    ok, failed = 0, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        for i, champ in enumerate(champs, 1):
            try:
                data = scrape_augments(champ, browser)
            except Exception as e:
                data = None
                print(f"  [{i}/{len(champs)}] {champ}: {type(e).__name__}")
            if data:
                total = sum(len(v) for v in data["tiers"].values())
                (OUT / f"{slug(champ)}.json").write_text(
                    json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
                ok += 1
                print(f"  [{i}/{len(champs)}] {champ}: {total} augmente "
                      f"({', '.join(data['tiers'])})")
            else:
                failed.append(champ)
                print(f"  [{i}/{len(champs)}] {champ}: gol")
            time.sleep(0.4)   # curtoazie fata de u.gg
        browser.close()

    print(f"\nGata: {ok} scrise, {len(failed)} esuate")
    if failed:
        print("esuati:", ", ".join(failed))


if __name__ == "__main__":
    main()
