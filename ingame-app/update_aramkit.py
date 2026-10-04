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
  ingame-app/data/augment-effects.json, champion-range.json  ce schimba un augment
                                 (ex. Draw Your Sword = melee) si raza de atac de baza
  ingame-app/data/item-ids.json, item-desc.json, item-stats.json  itemii de Mayhem (text, armura/MR/viata,
                                 cizme, componente, evolutii), nu cei de ARAM clasic
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

# Itemi pe care jucatorul nu ii poate cumpara desi datele ii listeaza (raportat
# din joc). Se scot din orice recomandare; adauga aici ce se mai gaseste.
BLOCKED_ITEMS = {"Gluttonous Greaves"}

# praguri sub care itemul nu conteaza ca "item de aparare" (componente mici)
MIN_ARMOR, MIN_MR, MIN_HP = 30, 30, 200


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
    """Numele itemului DOAR daca il poti cumpara din shop.

    Itemii "conditional" (dati de augmente: Ultra Hydra, Wooglet's Witchcap) si
    cei "transform" (Muramana apare singur din Manamune) apar in statisticile
    de meciuri, dar a-i recomanda e o recomandare imposibila de urmat.
    """
    it = items.get(str(item_id)) or {}
    if it.get("acquisition") != "shop" or not it.get("purchasable"):
        return None
    if it.get("name") in BLOCKED_ITEMS:
        return None
    return it.get("name")


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


def tooltip_text(item):
    """Tooltip-ul de Mayhem ca text simplu, cate un paragraf pe rand."""
    lines = []
    for block in (item.get("tooltip") or {}).get("blocks", []):
        text = "".join(sp.get("text") or "" for sp in block.get("spans", []))
        if text.strip():
            lines.append(text.strip())
    # Riot scrie intervalele cu linie lunga (U+2013, ex. 150-200); in aplicatie le vrem cu cratima
    return "\n".join(lines).replace("\u2013", "-").replace("\u2014", "-")


_STAT_LABELS = {"Armor": "armor", "Magic Resist": "mr", "Health": "hp"}
_MINIMUM = {"armor": MIN_ARMOR, "mr": MIN_MR, "hp": MIN_HP}


def item_files(items):
    """(item-desc, item-stats) din itemele de Mayhem ale ARAMKit."""
    names = {k: v["name"] for k, v in items.items()}
    desc, stats = {}, {}
    for item in items.values():
        name = item["name"]
        text = tooltip_text(item)
        if text:
            desc.setdefault(name, text)

        cats = item.get("categories") or []
        entry = {}
        for block in (item.get("tooltip") or {}).get("blocks", []):
            spans = block.get("spans", [])
            label = next((sp.get("label") for sp in spans if sp.get("type") == "icon"), None)
            key = _STAT_LABELS.get(label)
            value = next((sp.get("text") for sp in spans if sp.get("semantic") == "stat"), None)
            if key and value and key not in entry:
                try:
                    number = float(re.sub(r"[^0-9.]", "", value))
                except ValueError:
                    continue
                if number >= _MINIMUM[key]:
                    entry[key] = int(number)
        if {"LifeSteal", "SpellVamp", "HealthRegen"} & set(cats):
            entry["heal"] = True
        if "Boots" in cats:
            entry["boots"] = True
        if "Consumable" in cats:
            entry["consumable"] = True
        # "Must be Ranged" (Runaan's Hurricane): indisponibil daca esti melee,
        # inclusiv cand un augment te face melee (Draw Your Sword)
        m = re.search(r"Must be\s*(Ranged|Melee)", text)
        if m:
            entry["needs"] = m.group(1).lower()
        if item.get("isFinal") is False:
            entry["component"] = True
        # pe ce merg augmentele de tip "aplica efectele On-Hit" / "crit"
        if re.search(r"On-?Hit", text):
            entry["onhit"] = True
        if "Critical Strike Chance" in text:
            entry["crit"] = True

        # evolutii: "Transforms into X at ..." (Manamune -> Muramana) si lantul
        # de upgrade al cizmelor (Mercury's Treads -> Chainlaced Crushers)
        evolves = {re.sub(r"\s+", " ", m).strip()
                   for m in re.findall(r"Transforms into\s+(.+?)\s+(?:at|after|when)", text)}
        if "Boots" in cats:
            evolves |= {names[i] for i in item.get("to") or [] if i in names}
        if evolves:
            entry["evolves_into"] = sorted(evolves)
        if entry:
            stats.setdefault(name, entry)
    return desc, stats


def names_in(text, item_names):
    """Itemii numiti in text, in ordinea aparitiei; cel mai lung nume castiga
    ("Hollow Radiance" nu e si "Radiance")."""
    found, taken = [], []
    for name in sorted(item_names, key=len, reverse=True):
        for m in re.finditer(re.escape(name), text):
            if not any(a < m.end() and m.start() < b for a, b in taken):
                taken.append((m.start(), m.end()))
                found.append((m.start(), name))
    return [n for _, n in sorted(found)]


def augment_effects(augments, item_names, extra_desc=None):
    """Ce schimba un augment la build, din textul lui (ARAMKit + augment-desc):

      range    "melee"/"ranged"   ("You are now melee": Draw Your Sword)
      needs    [itemi]            questul cere sa-i ai ("Possess A and B")
      combine  item               questul ii uneste intr-unul ("combine into X"):
                                  se elibereaza un slot, iar A si B nu se mai cumpara
      stack    item               se poate cumpara de mai multe ori ("purchase unlimited")
      likes    "onhit"/"crit"     augmentul se foloseste de itemii cu efectul asta
      any      [itemi]            "Upgrade" care merge cu oricare din ei (Immolate)
    """
    texts = {}
    for aug in augments.values():
        texts.setdefault(aug["name"], []).append(tooltip_text(aug))
    for name, text in (extra_desc or {}).items():
        texts.setdefault(name, []).append(text)
    out = {}
    for name, parts in texts.items():
        text = re.sub(r"\s+", " ", " ".join(parts))
        low = text.lower()
        eff = {}
        m = re.search(r"you are now (melee|ranged)", low)
        if m:
            eff["range"] = m.group(1)
        m = re.search(r"Possess (.+?)(?:\.| with |REWARD|Reward|$)", text)
        if m:
            need = names_in(m.group(1), item_names)
            if need:
                eff["needs"] = need
        # "Upgrade Immolate: Hollow Radiance and Sunfire Aegis grant...": augmentul
        # merge cu oricare din itemii din prima propozitie
        if name.startswith("Upgrade"):
            first = names_in(text.split(".")[0], item_names)
            if len(first) >= 2:
                eff["any"] = first
        m = re.search(r"combine into (.+?)(?:\.|$)", text, re.I)
        if m and names_in(m.group(1), item_names):
            eff["combine"] = names_in(m.group(1), item_names)[0]
        m = re.search(r"purchase unlimited (?:amounts of )?(.+?)(?:\.|$)", text, re.I)
        if m and names_in(m.group(1), item_names):
            eff["stack"] = names_in(m.group(1), item_names)[0]
        if re.search(r"On-?Hit|Item_Keyword_OnHit", text):
            eff["likes"] = "onhit"
        elif "critical strike" in low and "crit" not in name.lower()                 and "can critically strike" not in low:
            eff["likes"] = "crit"
        elif re.search(r"crit", name, re.I) and "can critically strike" not in low:
            eff["likes"] = "crit"
        if eff:
            out[name] = eff
    return out


def champion_ranges():
    """{campion: raza de atac de baza} din Data Dragon (>= 300 = ranged)."""
    version = get_json("https://ddragon.leagueoflegends.com/api/versions.json")[0]
    data = get_json(f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json")["data"]
    return {c["name"]: c["stats"]["attackrange"] for c in data.values()}


MIN_AUG_PICK, MIN_AUG_GAMES, AUG_TOP = 0.03, 300, 6


def augment_item_stats(champ_id, data_token, res):
    """{nume augment: [[id item, win rate x1000, pick rate x1000], ...]}.

    Itemii care merg cel mai bine CU augmentul respectiv pe campionul asta (din
    "single augments" ARAMKit, ~1.8 MB per campion, de aceea doar rezumatul).
    Doar itemi cumparabili, cu destule meciuri ca sa nu fie zgomot.
    """
    raw = get_json(f"{CDN}/data/{data_token}/stats/all/champion-details/{champ_id}-single-augments.json")
    out = {}
    for row in raw.get("items") or []:
        name = (res["augments"].get(str(row["augmentId"])) or {}).get("name")
        if not name:
            continue
        rows = [r for r in row.get("all") or []
                if r.get("pickRate", 0) >= MIN_AUG_PICK and r.get("sampleCount", 0) >= MIN_AUG_GAMES
                and item_name(res["items"], r["id"])]
        rows.sort(key=lambda r: -r["winRate"])
        if rows:
            out[name] = [[r["id"], round(r["winRate"] * 1000), round(r["pickRate"] * 1000)]
                         for r in rows[:AUG_TOP]]
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

    desc, istats = item_files(res["items"])
    (DATA / "item-desc.json").write_text(
        json.dumps(desc, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    (DATA / "item-stats.json").write_text(
        json.dumps(istats, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    (DATA / "item-ids.json").write_text(
        json.dumps({k: v["name"] for k, v in res["items"].items()}, sort_keys=True,
                   ensure_ascii=False), encoding="utf-8")
    effects = augment_effects(res["augments"], set(desc), json.loads(
        (DATA / "augment-desc.json").read_text(encoding="utf-8")))
    (DATA / "augment-effects.json").write_text(
        json.dumps(effects, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    (DATA / "champion-range.json").write_text(
        json.dumps(champion_ranges(), indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(f"itemi de Mayhem: {len(desc)} descrieri, {len(istats)} cu statistici")

    (DATA / "builds").mkdir(parents=True, exist_ok=True)
    (DATA / "augments").mkdir(parents=True, exist_ok=True)

    stats, global_tier, built, failed = {}, {}, 0, []
    # data ARAMKit se reface si in cursul aceluiasi patch: "revision" (data) e
    # ce decide ce copie e mai noua, "version" ramane patch-ul pentru afisare
    revision = data_token.split("-")[1]
    bundle = {"version": patch, "revision": revision, "builds": {}, "augments": {}, "global": {},
              "augment_builds": {}}
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

        try:
            ab = augment_item_stats(cid, data_token, res)
            if ab:
                bundle["augment_builds"][slug(name)] = ab
        except Exception as e:
            print(f"  {name}: fara itemi per augment ({type(e).__name__})")
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
