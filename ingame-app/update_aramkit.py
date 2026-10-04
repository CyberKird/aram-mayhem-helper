"""Toate datele de ARAM MAYHEM, de pe ARAMKit, intr-un singur script.

De ce ARAMKit si nu u.gg: u.gg nu are itemi pentru Mayhem (build-urile erau de
ARAM clasic) si scraping-ul lui de augmente per campion s-a stricat. ARAMKit
publica pe data.aramkit.com fisiere JSON statice, strict de Mayhem (28M+
meciuri pe 16.19): win rate, pick rate, build-uri, augmente, modificatorii de
balans per campion. Nu trebuie browser, doar `urllib`.

Ce scrie:
  lcu-app/stats_data.json        win rate / pick rate / balans, patch curent + anterior
  ingame-app/data/builds/*.json  build de Mayhem per campion (start, core, 4/5/6, spells)
  ingame-app/data/augments/*.json  tier de augment per campion, din win rate real
  ingame-app/data/augments-global.json  tier global per raritate
  ingame-app/data/mayhem-bundle.json  toate cele de mai sus intr-un fisier, pe care
                                 aplicatia il ia din repo la pornire (data_sync.py)

Ruleaza-l la fiecare patch, niciodata in timpul unui meci:
    python update_aramkit.py
"""

import json
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
STATS_OUT = ROOT.parent / "lcu-app" / "stats_data.json"

SITE = "https://aramkit.com/en-US/champions"
CDN = "https://data.aramkit.com"
UA = {"User-Agent": "Mozilla/5.0"}

# Praguri sub care o optiune nu are suficiente meciuri ca sa conteze. Win rate
# pe cateva zeci de meciuri e zgomot, nu recomandare.
MIN_PICK = 0.02          # optiune de item / profil de build
MIN_BOOTS_PICK = 0.03    # cizmele au putine variante, deci prag mai mare
MIN_SPELL_PICK = 0.05    # perechea de summoner spells
SLOT_OPTIONS = 4         # cate optiuni pastram pe slotul 4/5/6


def get(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def get_json(url):
    return json.loads(get(url))


def find_versions():
    """[(patch, data_token, resources_token)], cel mai nou primul.

    Tokenurile sunt in HTML-ul paginii (ex. 16.19-20260929-7ed2deef470c pentru
    date, 16.19-2d56995ce28a pentru resurse). Pagina listeaza si versiunea
    anterioara in selector.
    """
    html = get(SITE)
    data = re.findall(r"(\d+\.\d+)-(\d{8}-[0-9a-f]{12})", html)
    res = re.findall(r"(\d+\.\d+)-([0-9a-f]{12})(?![0-9a-f])", html)
    d, r = {}, {}
    for patch, tok in data:
        d.setdefault(patch, f"{patch}-{tok}")
    for patch, tok in res:
        if not re.fullmatch(r"\d{8}", tok):
            r.setdefault(patch, f"{patch}-{tok}")
    patches = sorted((p for p in d if p in r),
                     key=lambda p: tuple(int(x) for x in p.split(".")), reverse=True)
    return [(p, d[p], r[p]) for p in patches]


def load_resources(res_token):
    base = f"{CDN}/resources/{res_token}/en-US/resources"
    return {name: get_json(f"{base}/{name}.json")
            for name in ("champions", "items", "augments", "summoner-spells")}


def details(data_token, champ_id):
    return get_json(f"{CDN}/data/{data_token}/stats/all/champion-details/{champ_id}.json")


def ranked(rows, min_pick=0.0):
    """Randurile in ordinea data de ARAMKit (rank), fara cele cu prea putine meciuri."""
    return [r for r in sorted(rows, key=lambda r: r.get("rank", 1e9))
            if r.get("pickRate", 0) >= min_pick]


def item_name(items, item_id):
    return (items.get(str(item_id)) or {}).get("name")


def is_boots(items, item_id):
    return "Boots" in ((items.get(str(item_id)) or {}).get("categories") or [])


def build_for(champion, d, res):
    """Build-ul in forma pe care o stie aplicatia, din detaliile ARAMKit."""
    items = res["items"]
    spells = res["summoner-spells"]
    archetypes = (d.get("builds", {}).get("filtered") or {}).get("archetypes") or []
    if not archetypes:
        return None
    profiles = ranked(archetypes[0].get("profiles") or [], MIN_PICK)
    if not profiles:
        return None
    profile = profiles[0]
    routes = profile.get("routes") or []
    route = routes[0] if routes else {}

    core = [item_name(items, i["id"]) for i in
            (route.get("purchaseOrder") or profile.get("itemSet") or [])]
    core = [n for n in core if n]
    if not core:
        return None

    starters = ranked(route.get("starters") or [], MIN_PICK)
    starting = [n for n in (item_name(items, i["id"]) for i in
                            (starters[0]["items"] if starters else [])) if n]

    # cizmele nu sunt in itemSet: le punem dupa primul item, unde le cumperi de
    # obicei in ARAM. "No Boots" (id 0) e o optiune reala, dar nu e un item.
    boots = next((item_name(items, b["item"]["id"]) for b in
                  ranked(route.get("boots") or [], MIN_BOOTS_PICK)
                  if b["item"]["id"] and item_name(items, b["item"]["id"])), None)
    if boots and not any(is_boots_name(items, n) for n in core):
        core.insert(min(1, len(core)), boots)

    owned = set(core)
    slots = {}
    slot_rows = (d.get("items", {}).get("filtered") or {}).get("slots") or {}
    for slot, key in ((4, "fourth"), (5, "fifth"), (6, "sixth")):
        names = []
        for row in ranked(slot_rows.get(str(slot)) or [], MIN_PICK):
            n = item_name(items, row["id"])
            if n and n not in owned and n not in names and not is_boots(items, row["id"]):
                names.append(n)
            if len(names) == SLOT_OPTIONS:
                break
        slots[key] = names

    spell_rows = ranked(d.get("summoners") or [], MIN_SPELL_PICK)
    summoners = []
    if spell_rows:
        summoners = [(spells.get(str(s["id"])) or {}).get("name") for s in spell_rows[0]["spells"]]
        summoners = [s for s in summoners if s]

    pool = []
    for n in starting + core + slots["fourth"] + slots["fifth"] + slots["sixth"]:
        if n not in pool:
            pool.append(n)

    return {"champion": champion, "source": f"{SITE}/{res['champions'][str(d['champion']['id'])]['slug']}",
            "mode": "ARAM Mayhem", "summoners": summoners, "starting": starting,
            "core": core, **slots, "pool": pool}


def is_boots_name(items, name):
    return any(v.get("name") == name and "Boots" in (v.get("categories") or [])
               for v in items.values())


def augment_tiers(d, augments):
    """{tier: [nume]} in ordinea rank, din win rate real al campionului."""
    out = {}
    for row in ranked((d.get("augments") or {}).get("all") or []):
        name = (augments.get(str(row["id"])) or {}).get("name")
        if name and row.get("tier"):
            out.setdefault(row["tier"], []).append(name)
    return out


def main():
    sys.path.insert(0, str(ROOT))
    from build_scraper import slug

    versions = find_versions()
    assert versions, "nu gasesc versiunile in pagina ARAMKit"
    patch, data_token, res_token = versions[0]
    print(f"patch {patch} ({data_token})")
    res = load_resources(res_token)
    champions = res["champions"]

    (DATA / "builds").mkdir(parents=True, exist_ok=True)
    (DATA / "augments").mkdir(parents=True, exist_ok=True)

    stats, global_tier, built, failed = {}, {}, 0, []
    # data ARAMKit se reface si in cursul aceluiasi patch: "revision" (data) e
    # ce decide ce copie e mai noua, "version" ramane patch-ul pentru afisare
    revision = data_token.split("-")[1]
    bundle = {"version": patch, "revision": revision, "builds": {}, "augments": {}, "global": {}}
    for i, (cid, meta) in enumerate(sorted(champions.items(), key=lambda kv: int(kv[0])), 1):
        name = meta["name"]
        try:
            d = details(data_token, cid)
        except Exception as e:
            failed.append(name)
            print(f"  [{i}/{len(champions)}] {name}: {type(e).__name__}")
            continue

        s = d["champion"]["stats"]
        stats[name] = {
            "wr": round(s["winRate"] * 100, 1), "pr": round(s["pickRate"] * 100, 1),
            "tier": d["champion"].get("tier"), "games": s.get("sampleCount"),
            "balance": meta.get("balance") or {},
        }

        build = build_for(name, d, res)
        if build:
            (DATA / "builds" / f"{slug(name)}.json").write_text(
                json.dumps(build, indent=1, ensure_ascii=False), encoding="utf-8")
            bundle["builds"][slug(name)] = build
            built += 1

        tiers = augment_tiers(d, res["augments"])
        if tiers:
            entry = {"champion": name, "source": f"{SITE}/{meta['slug']}", "tiers": tiers}
            (DATA / "augments" / f"{slug(name)}.json").write_text(
                json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
            bundle["augments"][slug(name)] = entry

        for row in (d.get("augments") or {}).get("all") or []:
            global_tier.setdefault(row["id"], row.get("augmentTier"))
        time.sleep(0.15)       # curtoazie fata de CDN, nu bombardam serverul

    assert len(stats) >= 150, f"prea putini campioni ({len(stats)}), nu scriu nimic"

    # tier global pe raritate: acelasi augment are acelasi augmentTier la orice campion
    by_rarity = {}
    for aid, tier in global_tier.items():
        aug = res["augments"].get(str(aid))
        if aug and tier:
            by_rarity.setdefault(aug["rarity"], {}).setdefault(tier, []).append(aug["name"])
    by_rarity["_source"] = f"{SITE} (ARAM Mayhem), patch {patch}"
    (DATA / "augments-global.json").write_text(
        json.dumps(by_rarity, indent=1, ensure_ascii=False), encoding="utf-8")
    bundle["global"] = by_rarity
    (DATA / "mayhem-bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # patch-ul anterior, doar partea de statistici, pentru sagetile de schimbare
    previous = None
    if len(versions) > 1:
        pp, pdata, pres = versions[1]
        print(f"anterior {pp}: aduc statisticile...")
        pchamps = get_json(f"{CDN}/resources/{pres}/en-US/resources/champions.json")
        pstats = {}
        for cid, meta in pchamps.items():
            try:
                ps = details(pdata, cid)["champion"]["stats"]
            except Exception:
                continue
            pstats[meta["name"]] = {"wr": round(ps["winRate"] * 100, 1),
                                    "pr": round(ps["pickRate"] * 100, 1)}
            time.sleep(0.15)
        previous = {"version": pp, "champions": pstats}

    STATS_OUT.write_text(json.dumps(
        {"version": patch, "revision": revision, "source": "aramkit.com (ARAM Mayhem)", "champions": stats,
         "previous": previous}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"gata: {len(stats)} campioni, {built} build-uri, esuati: {failed or 'niciunul'}")


if __name__ == "__main__":
    main()
