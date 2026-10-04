"""Aduce tier list-ul ARAM Mayhem de pe u.gg in tier_data.json.

Ruleaza-l la fiecare patch nou (niciodata in timpul unui meci, porneste un
Chromium real). Patch-ul vechi devine "previous", de acolo vin sagetile de
schimbare per campion. Daca patch-ul de pe pagina e acelasi cu cel salvat,
nu rotim nimic: doar am rescrie aceleasi date.

    python update_tier_list.py            # headed, Cloudflare blocheaza headless
    python update_tier_list.py --headless
"""

import json
import re
import sys

import tier_list

URL = "https://u.gg/lol/aram-mayhem-tier-list"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def parse_page(text):
    """Textul paginii -> (patch, {tier: [campioni]}).

    Pagina e text simplu: o eticheta de tier (S+, S, A, ...) urmata de
    numele campionilor, una pe linie, pana la subsol.
    """
    m = re.search(r"Patch (\d+\.\d+)", text)
    if not m:
        raise ValueError("nu gasesc patch-ul in pagina")
    lines = [l.strip() for l in text.split("\n")]
    start = lines.index("World") + 1 if "World" in lines else 0
    tiers, current = {}, None
    for line in lines[start:]:
        if line.startswith("©") or line == "Links":
            break
        if line in tier_list.TIER_ORDER:
            current = line
            tiers[current] = []
        elif current and line:
            tiers[current].append(line)
    return m.group(1), tiers


def merge(old, patch, tiers):
    """Fisierul nou: patch-ul vechi trece in "previous" doar daca patch-ul s-a schimbat."""
    if old and old["patch"] == patch:
        return {"patch": patch, "tiers": tiers, "previous": old.get("previous")}
    return {"patch": patch, "tiers": tiers,
            "previous": {"patch": old["patch"], "tiers": old["tiers"]} if old else None}


def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headless" in sys.argv)
        try:
            page = browser.new_page(user_agent=UA)
            page.goto(URL, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(3000)
            patch, tiers = parse_page(page.inner_text("body"))
        finally:
            browser.close()

    total = sum(len(v) for v in tiers.values())
    assert total >= 150, f"prea putini campioni ({total}): layout schimbat?"
    old = json.loads(tier_list.DATA_FILE.read_text(encoding="utf-8"))
    out = merge(old, patch, tiers)
    tier_list.DATA_FILE.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                   encoding="utf-8")
    print(f"patch {patch}: {total} campioni (anterior: "
          f"{(out['previous'] or {}).get('patch')})")


if __name__ == "__main__":
    main()
