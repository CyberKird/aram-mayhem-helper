"""Motorul de reguli pentru evidentierea itemilor pe baza compozitiei.

Euristici scrise de mana, nu date reale de matchup -- nicio sursa nu publica
build-uri de ARAM conditionate de compozitia inamica. Regulile doar
*evidentiaza* itemi deja prezenti in pool-ul campionului, nu inventeaza.
Port direct din overwolf-app/lib/logic.js (evaluateRules), pastrat identic
ca sa nu diveraga cele doua implementari.
"""


def item_key(name):
    """Nume de item -> forma comparabila intre sursele noastre.

    Jocul si u.gg scriu acelasi item diferit: "Blade of The Ruined King" vs
    "...the...", si uneori apostroful e cel tipografic. Fara normalizare,
    un item pe care il ai deja parea nedetinut si ajungea recomandat din nou.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def matches_condition(cond, roster, champion_tags, item_stats=None, categories=None):
    """True daca conditia regulii e indeplinita de compozitia/itemii curenti.

    Doua feluri de conditii:
      itemStat -- numara ITEMII chiar cumparati de inamici care dau statul
                  cerut (armor/mr/hp/heal). Semnal real, nu presupunere.
      restul   -- numara CAMPIONII dupa damageType/tag. Ramane pentru
                  inceputul meciului, cand inca nimeni n-a cumparat nimic.
    """
    stat = cond.get("itemStat")
    if stat:
        items = roster.get("enemy_items") or []
        stats = item_stats or {}
        count = sum(1 for name in items if stat in (stats.get(name) or {}))
        if count < cond.get("countGte", 1):
            return False

        # "nimeni la noi n-a luat asta inca": in ARAM anti-heal-ul e treaba
        # cuiva, si daca toti presupun ca il ia altcineva, nu-l ia nimeni.
        # Regula se stinge singura cand un coechipier chiar il cumpara.
        lacks = cond.get("allyLacksCategory")
        if lacks:
            wanted = {n.lower() for n in (categories or {}).get(lacks, [])}
            if any(name.lower() in wanted
                   for name in (roster.get("ally_items") or [])):
                return False
        return True

    team = roster.get(cond["team"], [])
    count = 0
    for champ in team:
        meta = champion_tags.get(champ)
        if not meta:
            continue
        if cond.get("damageType") and meta.get("damageType") != cond["damageType"]:
            continue
        tag_in = cond.get("tagIn")
        if tag_in and not any(t in tag_in for t in meta.get("tags", [])):
            continue
        count += 1
    return count >= cond.get("countGte", 1)


def evaluate_rules(roster, champion_tags, rule_set, item_pool, item_stats=None):
    """Itemi de evidentiat, cu motivul. Filtreaza pool-ul, nu inventeaza."""
    pool = item_pool or []
    out = []
    seen = set()

    for rule in rule_set.get("rules", []):
        if not matches_condition(rule["condition"], roster, champion_tags,
                                 item_stats, rule_set.get("categories")):
            continue
        keywords = {k.lower() for k in rule_set.get("categories", {}).get(rule["suggestCategory"], [])}
        for item in pool:
            if item.lower() in keywords and item not in seen:
                seen.add(item)
                out.append({"item": item, "reason": rule["reason"], "rule": rule["id"]})

    return out


def resolve_build(build, roster, champion_tags, rule_set, item_stats=None):
    """Un singur item pe slotul 4/5/6 -- build final, nu meniu de alternative.

    u.gg da 2-3 optiuni per slot situational; alegem una singura per slot,
    prioritizand orice optiune care se potriveste cu o regula de compozitie
    (evaluate_rules) si care nu e deja folosita intr-un slot anterior. Fara
    potrivire, cade pe prima optiune neutilizata din ordinea data de u.gg.
    """
    core = list(build.get("core") or [])
    hot = {h["item"]: h["reason"]
           for h in evaluate_rules(roster, champion_tags, rule_set,
                                   build.get("pool") or [], item_stats)}

    owned = {item_key(n) for n in (roster.get("own_items") or [])}

    used = set(core)
    picks = []
    for slot in ("fourth", "fifth", "sixth"):
        candidates = build.get(slot) or []
        if not candidates:
            continue
        chosen = next((c for c in candidates if c in hot and c not in used), None)
        if chosen is None:
            chosen = next((c for c in candidates if c not in used), candidates[0])
        used.add(chosen)
        picks.append({"item": chosen, "reason": hot.get(chosen),
                      "owned": item_key(chosen) in owned})

    core_entries = [{"item": c, "owned": item_key(c) in owned} for c in core]

    # primul item neluat din ordinea core -> 4 -> 5 -> 6: exact ce urmeaza
    # sa cumperi acum. Nu schimbam build-ul, doar aratam unde ai ramas.
    for entry in core_entries + picks:
        entry.setdefault("next", False)
    for entry in core_entries + picks:
        if not entry["owned"]:
            entry["next"] = True
            break

    return {"starting": list(build.get("starting") or []),
            "core": core_entries, "picks": picks,
            "boots": boots_advice(build, roster, hot, item_stats)}


# cate sloturi de item are un campion
FULL_BUILD = 6


def boots_advice(build, roster, hot, item_stats=None):
    """{sell, buy, reason} cand merita vandute cizmele, altfel None.

    Doar la build plin: pana atunci cizmele sunt un slot util. La 6 itemi
    insa ele sunt de obicei cel mai slab slot, iar locul lor valoreaza mai
    mult ca item complet -- optimizarea clasica de ARAM tarziu.

    "De obicei", nu "intotdeauna": Mercury's Treads contra unei compozitii
    cu mult CC, sau Plated Steelcaps contra unei echipe AD, chiar isi fac
    treaba. Daca regulile de compozitie au marcat chiar cizmele pe care le
    porti, tacem -- nu-ti recomandam sa vinzi exact contra-itemul potrivit.
    """
    stats = item_stats or {}
    owned = [n for n in (roster.get("own_items") or [])
             if not (stats.get(n) or {}).get("consumable")]
    if len(owned) < FULL_BUILD:
        return None

    boots = next((n for n in owned if (stats.get(n) or {}).get("boots")), None)
    if not boots:
        return None
    if boots in hot:
        return None

    owned_keys = {item_key(n) for n in owned}
    pool = [n for n in (build.get("pool") or [])
            if item_key(n) not in owned_keys
            and not (stats.get(n) or {}).get("boots")
            and not (stats.get(n) or {}).get("consumable")
            and not (stats.get(n) or {}).get("component")]
    if not pool:
        return None

    # daca o regula de compozitie a marcat ceva, ala e inlocuitorul potrivit
    best = next((n for n in pool if n in hot), pool[0])
    return {"sell": boots, "buy": best, "reason": hot.get(best)}
