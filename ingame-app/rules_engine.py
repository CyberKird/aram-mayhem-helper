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


def owned_keys(own_items, item_stats=None):
    """Chei de item pe care le ai, inclusiv cele din care au evoluat itemele tale.

    Manamune devine Muramana dupa 360 mana si dispare din inventar: fara asta
    build-ul cerea iar Manamune. "evolves_into" vine din build_item_stats.py
    (descrierea "Transforms into X" si lantul de upgrade al cizmelor). Repetam
    pana nu se mai schimba nimic, ca sa prindem si lanturile de doua trepte.
    """
    keys = {item_key(n) for n in own_items or ()}
    stats = item_stats or {}
    changed = True
    while changed:
        changed = False
        for name, st in stats.items():
            key = item_key(name)
            if key not in keys and any(item_key(e) in keys
                                       for e in st.get("evolves_into") or ()):
                keys.add(key)
                changed = True
    return keys


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


def required_items(taken_augments, augment_items):
    """Itemi ceruti de augmentele luate, in ordinea in care au fost luate.

    "Upgrade Zhonya's" fara Zhonya's Hourglass in inventar e augment irosit,
    deci itemul din spate nu mai e o optiune printre altele: trece inaintea
    build-ului normal. Mapare din augment-items.json, nu ghicita din text.
    """
    out = []
    for name in taken_augments or ():
        item = (augment_items or {}).get(name)
        if item and item not in out:
            out.append(item)
    return out


RANGED_FROM = 300      # raza de atac de la care un campion e ranged


def current_range(champion, taken_augments, extra):
    """"melee" sau "ranged": raza de baza a campionului, schimbata de augmentele luate.

    Draw Your Sword te face melee, iar apoi Runaan's Hurricane ("Must be
    Ranged") nu se mai poate cumpara -- recomandarea lui devine o capcana.
    Ultimul augment care schimba raza castiga.
    """
    reach = (extra.get("ranges") or {}).get(champion)
    state = None if reach is None else ("ranged" if reach >= RANGED_FROM else "melee")
    for aug in taken_augments or ():
        state = ((extra.get("effects") or {}).get(aug) or {}).get("range", state)
    return state


def augment_scores(taken_augments, extra):
    """{item: (win rate %, augment)}: cat de bine merge itemul CU augmentele luate.

    Din statisticile de Mayhem "item | augment" pe campionul asta. Cu mai multe
    augmente luate, se face media peste cele care au date pentru item.
    """
    table, names = extra.get("aug_table") or {}, extra.get("item_names") or {}
    per_item = {}
    for aug in taken_augments or ():
        for item_id, wr, _pr in table.get(aug, []):
            name = names.get(str(item_id))
            if name:
                per_item.setdefault(name, []).append((wr / 10.0, aug))
    return {n: (sum(w for w, _ in v) / len(v), v[-1][1]) for n, v in per_item.items()}


def resolve_build(build, roster, champion_tags, rule_set, item_stats=None,
                  taken_augments=None, augment_items=None, extra=None):
    """Un singur item pe slotul 4/5/6 -- build final, nu meniu de alternative.

    u.gg da 2-3 optiuni per slot situational; alegem una singura per slot,
    prioritizand orice optiune care se potriveste cu o regula de compozitie
    (evaluate_rules) si care nu e deja folosita intr-un slot anterior. Fara
    potrivire, cade pe prima optiune neutilizata din ordinea data de u.gg.

    Itemii ceruti de augmentele luate sar peste tot: build-ul de pe u.gg nu
    stie ce augment ai ales, iar un "Upgrade X" fara X e pur si simplu pierdut.
    """
    extra = extra or {}
    stats = item_stats or {}
    rng = current_range(roster.get("local_champion"), taken_augments, extra)

    def ok(name):
        need = (stats.get(name) or {}).get("needs")
        return need is None or rng is None or need == rng

    # itemele indisponibile (ex. Runaan's dupa Draw Your Sword) nu mai apar nicaieri
    unavailable = [n for n in build.get("pool") or [] if not ok(n)]
    core = [c for c in (build.get("core") or []) if ok(c)]
    lost = len(build.get("core") or []) - len(core)
    scores = augment_scores(taken_augments, extra)
    hot = {h["item"]: h["reason"]
           for h in evaluate_rules(roster, champion_tags, rule_set,
                                   [p for p in build.get("pool") or [] if ok(p)], item_stats)}

    owned = owned_keys(roster.get("own_items"), item_stats)

    needed = [n for n in required_items(taken_augments, augment_items)
              if item_key(n) not in owned]

    def finished(name):
        st = stats.get(name) or {}
        return not (st.get("boots") or st.get("component") or st.get("consumable"))

    used = set(core)
    picks = []

    def pick(candidates):
        """Un item din lista: regula de compozitie, apoi cel mai bun cu augmentele
        tale, apoi ordinea build-ului."""
        free = [c for c in candidates if c not in used]
        chosen = next((c for c in free if c in hot), None)
        if chosen is None and scores:
            # si itemele bune CU augmentul tau, chiar daca nu erau in lista slotului
            extra_items = [n for n in scores if n not in used and ok(n) and finished(n)]
            best = max(set(free) | set(extra_items), key=lambda n: scores.get(n, (0, ""))[0],
                       default=None)
            if best is not None and best in scores:
                chosen = best
        if chosen is None and free:
            chosen = free[0]
        if chosen is None:
            return None
        used.add(chosen)
        reason = hot.get(chosen)
        if reason is None and chosen in scores:
            wr, aug = scores[chosen]
            reason = f"{wr:.0f}% WR cu {aug}"
        return {"item": chosen, "reason": reason, "owned": item_key(chosen) in owned}

    for slot in ("fourth", "fifth", "sixth"):
        candidates = [c for c in (build.get(slot) or []) if ok(c)]
        entry = pick(candidates) if (candidates or scores) else None
        if entry:
            picks.append(entry)
    # un item de core a cazut (indisponibil): il inlocuim, ca build-ul sa ramana plin
    for _ in range(lost):
        entry = pick([p for p in (build.get("pool") or []) if ok(p) and finished(p)])
        if entry:
            picks.append(entry)

    core_entries = [{"item": c, "owned": item_key(c) in owned} for c in core]

    # Itemul cerut de un augment intra primul si scoate din lista o aparitie
    # ulterioara a lui, ca sa nu apara de doua ori.
    forced = []
    for name in needed:
        key = item_key(name)
        core_entries = [e for e in core_entries if item_key(e["item"]) != key]
        picks = [e for e in picks if item_key(e["item"]) != key]
        forced.append({"item": name, "owned": False,
                       "reason": "cerut de augment"})
    core_entries = forced + core_entries

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
            "boots": boots_advice(build, roster, hot, item_stats),
            "unavailable": unavailable, "range": rng}


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
    # Sase sloturi ocupate nu inseamna build plin daca unele sunt doar
    # componente (sau cizmele simple): inca ai de cumparat, nu de optimizat.
    if any((stats.get(n) or {}).get("component") and not (stats.get(n) or {}).get("boots")
           or n == "Boots" for n in owned):
        return None

    boots = next((n for n in owned if (stats.get(n) or {}).get("boots")), None)
    if not boots:
        return None
    if boots in hot:
        return None

    have = owned_keys(owned, stats)
    pool = [n for n in (build.get("pool") or [])
            if item_key(n) not in have
            and not (stats.get(n) or {}).get("boots")
            and not (stats.get(n) or {}).get("consumable")
            and not (stats.get(n) or {}).get("component")]
    if not pool:
        return None

    # daca o regula de compozitie a marcat ceva, ala e inlocuitorul potrivit
    best = next((n for n in pool if n in hot), pool[0])
    return {"sell": boots, "buy": best, "reason": hot.get(best)}
