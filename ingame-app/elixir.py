"""Indicator pentru potiunea de 500g: care Elixir si cand.

In Mayhem "potiunea de 500" sunt cele trei Elixiruri (priceTotal 500 in datele
ARAMKit): Iron, Sorcery, Wrath. Cer nivel 9, tin 3 minute si se beau o data.
Corrupting Potion nu exista in Mayhem.

Doua intrebari, separate:
  CARE  - scor euristic pe campionul tau, compozitia inamica si a echipei tale
          (aceeasi idee ca stat_anvil.py: nu inventam date, punctam optiunile).
  CAND  - stare din nivel, aur, iteme terminate si timpul de joc.

Fara date publice despre elixiruri in Mayhem, ponderile de mai jos sunt scrise
de mana si ajustabile; selfcheck-ul fixeaza comportamentul, nu cifrele.
"""

ELIXIRS = ("Elixir of Iron", "Elixir of Sorcery", "Elixir of Wrath")
PRICE = 500
LEVEL = 9
DURATION = 180          # secunde de efect
MIN_CORE = 2            # iteme terminate inainte ca elixirul sa merite banii
LATE = 20 * 60          # de aici lupta e lunga si aurul sta degeaba

_DEF_MIN = {"armor": 30, "mr": 30, "hp": 200}     # ca in update_aramkit.py


def _meta(tags, name):
    return (tags or {}).get(name) or {}


def _count(tags, names, *want):
    return sum(1 for n in names if set(_meta(tags, n).get("tags") or ()) & set(want))


def _damage(tags, name):
    return _meta(tags, name).get("damageType", "mixed")


def defensive_items(items, item_stats):
    """Cati itemi de aparare (armura/MR/viata mare) au inamicii."""
    stats = item_stats or {}
    return sum(1 for n in items or ()
               if any((stats.get(n) or {}).get(k, 0) >= v for k, v in _DEF_MIN.items()))


def score(tags, champ, allies, enemies, enemy_items=(), item_stats=None):
    """{elixir: [(puncte, motiv)]}. Motivul cu cele mai multe puncte se afiseaza."""
    me = _meta(tags, champ)
    dmg, mine = me.get("damageType", "mixed"), set(me.get("tags") or ())
    mates = list(allies or ())
    if champ in mates:
        mates.remove(champ)          # rosterul include campionul tau

    tanks = _count(tags, enemies, "Tank")
    cc = tanks + _count(tags, enemies, "Support") + 0.5 * _count(tags, enemies, "Mage")
    burst = _count(tags, enemies, "Assassin", "Mage")
    poke = _count(tags, enemies, "Mage", "Marksman")
    armored = min(3, defensive_items(enemy_items, item_stats))
    front = _count(tags, mates, "Tank", "Fighter")
    melee = _count(tags, mates, "Tank", "Fighter", "Assassin")
    healers = min(2, _count(tags, mates, "Support"))

    wrath = [({"AD": 10, "mixed": 5, "AP": 0}.get(dmg, 5), f"campion {dmg}")]
    sorcery = [({"AP": 10, "mixed": 5, "AD": 0}.get(dmg, 5), f"campion {dmg}")]
    iron = [(4, "se potriveste oricui")]

    for tag, w, s, i in (("Marksman", 3, 0, -2), ("Fighter", 2, 0, 3), ("Assassin", 2, 1, 0),
                         ("Mage", 0, 3, 0), ("Tank", 0, 0, 8), ("Support", 0, 0, 3)):
        if tag in mine:
            for lst, pts in ((wrath, w), (sorcery, s), (iron, i)):
                if pts:
                    lst.append((pts, tag.lower()))

    # inamici: CC si burst cer rezistenta; tancurile si itemele de aparare cer damage curat
    iron += [(0.8 * cc, "inamici cu CC"), (0.6 * burst, "inamici cu burst")]
    sorcery += [(1.0 * tanks + 0.5 * armored, "inamici tancosi (damage curat)")]
    wrath += [(0.5 * poke, "inamici cu poke (physical vamp)")]
    # echipa ta: fara linie intai cineva trebuie sa reziste; aliatii in melee profita de urma de viteza
    if front <= 1:
        iron.append((3, "echipa fara linie intai"))
    if melee >= 3:
        iron.append((2, "aliati in melee (urma de viteza)"))
    if healers:
        wrath.append((-1.0 * healers, "echipa are heal deja"))

    return {"Elixir of Wrath": wrath, "Elixir of Sorcery": sorcery, "Elixir of Iron": iron}


def pick(parts):
    """(elixirul cu cel mai mare scor, scorurile lui, motivul principal, restul)."""
    totals = {n: sum(p for p, _ in ps) for n, ps in parts.items()}
    best = max(ELIXIRS, key=lambda n: totals[n])        # la egalitate: ordinea din ELIXIRS
    why = [m for p, m in sorted(parts[best], reverse=True) if p > 0][:2]
    return best, totals, why


def owned(own_items):
    return next((n for n in own_items or () if n in ELIXIRS), None)


class Tracker:
    """Cat mai tine efectul. Jocul nu expune buff-urile, dar un elixir care
    dispare din inventar fara sa fi crescut aurul cu ~pretul lui a fost baut."""

    def __init__(self):
        self.had, self.until = None, 0.0

    def update(self, own_items, game_time):
        now = owned(own_items)
        if self.had and not now and isinstance(game_time, (int, float)):
            self.until = game_time + DURATION
        self.had = now
        return self.until

    def reset(self):
        self.had, self.until = None, 0.0


def advise(tags, champ, allies, enemies, enemy_items, own_items, item_stats,
           level, gold, game_time, active_until=0.0, full=False, core=0):
    """Starea pentru panou:
      locked  nivel < 9           wait  prea putine iteme terminate
      gold    nu ai 500g          buy   ia-l acum (la recall)
      use     il ai in inventar   active  efectul inca tine
    Plus elixirul recomandat, motivul si clasamentul complet."""
    best, totals, why = pick(score(tags, champ, allies, enemies, enemy_items, item_stats))
    out = {"pick": best, "why": ", ".join(why), "scores": {n: round(totals[n], 1) for n in ELIXIRS}}
    held = owned(own_items)
    t = game_time if isinstance(game_time, (int, float)) else 0
    left = int(active_until - t)

    if held:
        out.update(state="use", pick=held, when="Ai deja elixirul: bea-l cand pornesti spre lupta, tine 3 min.")
    elif left > 0:
        out.update(state="active", left=left, when=f"Efectul tine inca ~{left}s: nu cumpara altul.")
    elif not isinstance(level, int) or level < LEVEL:
        out.update(state="locked", when=f"Se deschide la nivel {LEVEL}" + (f" (acum {level})." if isinstance(level, int) else "."))
    elif core < MIN_CORE and not full:
        out.update(state="wait", when=f"Mai intai {MIN_CORE} iteme terminate ({core} acum): itemele dau mai mult decat 3 min de buff.")
    elif not isinstance(gold, (int, float)) or gold < PRICE:
        out.update(state="gold", need=max(0, PRICE - int(gold or 0)),
                   when=f"Mai ai nevoie de {max(0, PRICE - int(gold or 0))}g.")
    else:
        late = t >= LATE
        out.update(state="buy", when=("Build plin: e cea mai buna cheltuiala de aur, ia-l la fiecare recall." if full
                                      else "Lupte lungi, aur de sobra: ia-l la fiecare recall." if late
                                      else "Ia-l la urmatorul recall, inainte de lupta mare (tine 3 min)."))
    return out


def selfcheck():
    tags = {
        "Garen": {"damageType": "AD", "tags": ["Fighter", "Tank"]},
        "Malphite": {"damageType": "AP", "tags": ["Tank", "Fighter"]},
        "Ahri": {"damageType": "AP", "tags": ["Mage", "Assassin"]},
        "Jinx": {"damageType": "AD", "tags": ["Marksman"]},
        "Zed": {"damageType": "AD", "tags": ["Assassin"]},
        "Leona": {"damageType": "mixed", "tags": ["Tank", "Support"]},
        "Soraka": {"damageType": "AP", "tags": ["Support", "Mage"]},
        "Lux": {"damageType": "AP", "tags": ["Mage", "Support"]},
    }
    # campionul decide familia: AD -> Wrath, AP -> Sorcery, tanc -> Iron
    assert pick(score(tags, "Jinx", ["Jinx"], ["Zed", "Ahri"]))[0] == "Elixir of Wrath"
    assert pick(score(tags, "Ahri", ["Ahri"], ["Zed", "Jinx"]))[0] == "Elixir of Sorcery"
    assert pick(score(tags, "Malphite", ["Malphite"], ["Zed", "Jinx"]))[0] == "Elixir of Iron"
    # inamicii conteaza: mult CC + burst muta un luptator AD de la Wrath spre Iron
    base = pick(score(tags, "Garen", ["Garen"], ["Jinx", "Jinx"]))
    heavy = pick(score(tags, "Garen", ["Garen"], ["Leona", "Leona", "Ahri", "Zed", "Lux"]))
    assert base[1]["Elixir of Iron"] < heavy[1]["Elixir of Iron"]
    # tancuri + itemi de aparare ridica Sorcery (damage curat)
    stats = {"Thornmail": {"armor": 70, "hp": 350}, "Force of Nature": {"mr": 70, "hp": 400}}
    few = score(tags, "Ahri", ["Ahri"], ["Zed"], (), stats)["Elixir of Sorcery"]
    many = score(tags, "Ahri", ["Ahri"], ["Malphite", "Leona"], ["Thornmail", "Force of Nature"], stats)["Elixir of Sorcery"]
    assert sum(p for p, _ in many) > sum(p for p, _ in few)
    # echipa ta conteaza: fara linie intai, Iron creste; cu heal in echipa, Wrath scade
    solo = score(tags, "Jinx", ["Jinx", "Ahri", "Lux", "Zed"], ["Zed"])
    wall = score(tags, "Jinx", ["Jinx", "Garen", "Malphite", "Leona"], ["Zed"])
    assert sum(p for p, _ in solo["Elixir of Iron"]) > sum(p for p, _ in wall["Elixir of Iron"])
    heal = score(tags, "Jinx", ["Jinx", "Soraka"], ["Zed"])
    assert sum(p for p, _ in heal["Elixir of Wrath"]) < sum(p for p, _ in score(tags, "Jinx", ["Jinx", "Zed"], ["Zed"])["Elixir of Wrath"])

    def state(**kw):
        a = dict(tags=tags, champ="Jinx", allies=["Jinx"], enemies=["Zed"], enemy_items=[], own_items=[],
                 item_stats={}, level=12, gold=900, game_time=600, core=3)
        a.update(kw)
        return advise(**a)

    assert state(level=8)["state"] == "locked"
    assert state(core=1)["state"] == "wait"
    assert state(core=1, full=True)["state"] == "buy"
    assert state(gold=300)["state"] == "gold" and state(gold=300)["need"] == 200
    assert state()["state"] == "buy" and state()["pick"] == "Elixir of Wrath"
    assert state(own_items=["Elixir of Iron"])["state"] == "use"
    assert state(active_until=700)["state"] == "active"
    assert state(game_time=1500)["state"] == "buy" and "recall" in state(game_time=1500)["when"]
    assert state(level=None)["state"] == "locked"
    # tracker: elixirul dispare din inventar = baut, efectul tine 180s
    tr = Tracker()
    assert tr.update(["Elixir of Wrath"], 100) == 0.0
    assert tr.update([], 130) == 130 + DURATION
    tr.reset()
    assert tr.update([], 200) == 0.0
    print("selfcheck OK (elixir)")
