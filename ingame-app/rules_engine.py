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

    Raza reala din joc (live_range, din /activeplayer) bate orice deductie:
    vede Draw Your Sword chiar daca aplicatia n-a prins alegerea augmentului.
    """
    live = extra.get("live_range")
    if live:
        return "ranged" if live >= RANGED_FROM else "melee"
    reach = (extra.get("ranges") or {}).get(champion)
    state = None if reach is None else ("ranged" if reach >= RANGED_FROM else "melee")
    for aug in taken_augments or ():
        state = ((extra.get("effects") or {}).get(aug) or {}).get("range", state)
    return state


def implied_augment(champion, taken_augments, extra):
    """Augmentul care explica raza din joc, daca n-a fost prins la alegere.

    Ashe are 600 raza de baza; daca jocul raporteaza 200, ai luat Draw Your
    Sword. Il adaugam ca sa conteze si la itemii cu cel mai bun win rate CU el.
    Doar cand un singur augment poate explica schimbarea.
    """
    base = (extra.get("ranges") or {}).get(champion)
    live = extra.get("live_range")
    if not base or not live:
        return None
    now = "ranged" if live >= RANGED_FROM else "melee"
    if now == ("ranged" if base >= RANGED_FROM else "melee"):
        return None
    effects = extra.get("effects") or {}
    if any((effects.get(a) or {}).get("range") == now for a in taken_augments or ()):
        return None
    cands = [a for a, e in effects.items() if e.get("range") == now]
    return cands[0] if len(cands) == 1 else None


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
    effects = [((extra.get("effects") or {}).get(a) or {}, a) for a in taken_augments or ()]
    likes = {e["likes"] for e, _ in effects if e.get("likes")}

    # Questul care uneste itemi (Icathia's Fall: Sunfire + Hollow Radiance ->
    # Void Immolation): dupa unire sursele nu mai sunt in inventar, dar nici
    # nu trebuie cumparate iar.
    for eff, _ in effects:
        if eff.get("combine") and item_key(eff["combine"]) in owned:
            owned |= {item_key(n) for n in eff.get("needs") or ()}

    needed = [(n, "cerut de augment") for n in required_items(taken_augments, augment_items)]
    for eff, aug in effects:
        why = (f"{aug}: se unesc in {eff['combine']}" if eff.get("combine")
               else f"quest {aug}")
        needed += [(n, why) for n in eff.get("needs") or ()]
        if eff.get("stack"):
            needed.append((eff["stack"], f"{aug}: se cumuleaza"))
    seen = set()
    needed = [(n, why) for n, why in needed
              if item_key(n) not in owned and ok(n)
              and not (item_key(n) in seen or seen.add(item_key(n)))]

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
        if chosen is None and likes:
            # augment on-hit/crit: dintre optiunile slotului, cea care il hraneste
            chosen = next((c for c in free if likes & {k for k in ("onhit", "crit")
                                                       if (stats.get(c) or {}).get(k)}), None)
        if chosen is None and free:
            chosen = free[0]
        if chosen is None:
            return None
        used.add(chosen)
        reason = hot.get(chosen)
        if reason is None and chosen in scores:
            wr, aug = scores[chosen]
            reason = f"{wr:.0f}% WR cu {aug}"
        if reason is None and likes & {k for k in ("onhit", "crit") if (stats.get(chosen) or {}).get(k)}:
            reason = "on-hit pentru augment" if "onhit" in likes else "crit pentru augment"
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
    for name, why in needed:
        key = item_key(name)
        core_entries = [e for e in core_entries if item_key(e["item"]) != key]
        picks = [e for e in picks if item_key(e["item"]) != key]
        forced.append({"item": name, "owned": False, "reason": why})
    core_entries = forced + core_entries
    # itemul care se cumuleaza (Don't Stop Cleavin'): dupa primul, inca unul
    # la coada build-ului, ca sa nu ramana sloturi "terminate" degeaba
    for eff, aug in effects:
        if eff.get("stack") and item_key(eff["stack"]) in owned:
            picks.append({"item": eff["stack"], "owned": False,
                          "reason": f"inca unul: {aug} il cumuleaza"})

    # primul item neluat din ordinea core -> 4 -> 5 -> 6: exact ce urmeaza
    # sa cumperi acum. Nu schimbam build-ul, doar aratam unde ai ramas.
    for entry in core_entries + picks:
        entry.setdefault("next", False)
    for entry in core_entries + picks:
        if not entry["owned"]:
            entry["next"] = True
            break

    return {"starting": starting_left(build.get("starting"), roster.get("own_items"), stats),
            "core": core_entries, "picks": picks,
            "sell": sell_advice(build, roster, hot, item_stats, ok, rng,
                                core_entries + picks),
            "unavailable": unavailable, "range": rng}


def starting_left(starting, own_items, item_stats=None):
    """Itemii de start inca necumparati; nimic dupa ce ai luat altceva.

    Startul se cumpara o data, la fantana. Ce ai deja nu mai e o decizie, iar
    dupa primul item din afara startului sectiunea e doar istorie. Pot-urile
    dispar dupa ce le bei, deci nu le recomandam iar odata ce ai cumparat ceva.
    """
    stats = item_stats or {}
    start = list(starting or [])
    keys = {item_key(n) for n in start}
    own = [n for n in own_items or () if "poro" not in item_key(n)]   # trinket-ul ARAM
    if any(item_key(n) not in keys for n in own):
        return []
    have = {item_key(n) for n in own}
    return [n for n in start if item_key(n) not in have
            and not (own and (stats.get(n) or {}).get("consumable"))]


# itemi de start din ARAM care nu cresc in nimic: primii vanduti la sloturi pline
STARTER_PREFIXES = ("dorans", "guardians", "cull")

# cate sloturi de item are un campion
FULL_BUILD = 6


def slot_items(own_items, item_stats=None):
    """Itemii care ocupa sloturi: fara pot-uri si fara trinket-ul de ARAM."""
    stats = item_stats or {}
    return [n for n in own_items or ()
            if not (stats.get(n) or {}).get("consumable") and "poro" not in item_key(n)]


def sell_advice(build, roster, hot, item_stats=None, ok=None, rng=None, plan=()):
    """{sell, buy, reason}: ce sa vinzi acum si ce iei in loc, sau None.

    In ordinea importantei:
      1. un item pe care nu-l mai poti folosi (Runaan's dupa Draw Your Sword)
         -- oricand, nu doar la build plin: e aur blocat degeaba
      2. sloturi pline, dar unul e item de start (Doran's): face loc
      3. build plin: cizmele (boots_advice), apoi un item din afara planului
         cand inamicii cer un contra-item pe care nu-l ai
    """
    stats = item_stats or {}
    own = slot_items(roster.get("own_items"), stats)
    have = owned_keys(own, stats)
    upcoming = [e["item"] for e in plan if not e.get("owned")
                and item_key(e["item"]) not in have]
    nxt = upcoming[0] if upcoming else None

    if ok is not None:
        dead = next((n for n in own if not ok(n)), None)
        if dead and nxt:
            return {"sell": dead, "buy": nxt,
                    "reason": f"nu merge pe {rng}" if rng else "nu-l mai poti folosi"}

    if len(own) >= FULL_BUILD:
        # Itemul de start (Doran's, Guardian's, Cull) tine un slot intreg pentru
        # statistici de inceput de meci. Cand sloturile sunt pline e primul
        # care pleaca: il vinzi cand ai aur de urmatorul item. Tear si Dark Seal
        # nu intra aici, ele cresc in itemi finali.
        starters = {item_key(n) for n in build.get("starting") or ()}
        filler = next((n for n in own
                       if (item_key(n) in starters or item_key(n).startswith(STARTER_PREFIXES))
                       and not (stats.get(n) or {}).get("evolves_into")), None)
        buy = nxt or next((n for n in hot if item_key(n) not in have), None) or next(
            (n for n in build.get("pool") or [] if item_key(n) not in have
             and not (stats.get(n) or {}).get("component")
             and not (stats.get(n) or {}).get("boots")), None)
        if filler and buy:
            return {"sell": filler, "buy": buy,
                    "reason": f"item de start: vinde-l cand ai aur de {buy}"}

    advice = boots_advice(build, roster, hot, item_stats)
    if advice or len(own) < FULL_BUILD:
        return advice
    if any((stats.get(n) or {}).get("component") for n in own):
        return None          # inca o componenta de terminat: cumperi, nu vinzi

    # Build plin si fara cizme de vandut: daca inamicii cer un contra-item pe
    # care nu-l ai, schimbi itemul din inventar care nu e nici in plan, nici
    # contra-item. Itemii din build-ul campionului nu se ating.
    wanted = next((n for n in hot if item_key(n) not in have
                   and not (stats.get(n) or {}).get("component")), None)
    planned = {item_key(n) for n in (build.get("core") or [])
               + [x for k in ("fourth", "fifth", "sixth") for x in build.get(k) or []]}
    spare = next((n for n in own if item_key(n) not in planned and n not in hot
                  and not (stats.get(n) or {}).get("boots")), None)
    if wanted and spare:
        return {"sell": spare, "buy": wanted, "reason": hot[wanted]}
    return None


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
    owned = slot_items(roster.get("own_items"), stats)
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
