"""Logica pura pentru ARAM Mayhem: parsare bench, rezolvare campion, tier, best pick.

Fara retea, fara UI, fara stare globala. Tot ce e aici e testabil offline
cu dict-uri simple (vezi selfcheck() din app.py).
"""

# queue id-ul pentru ARAM: Mayhem. Riot a mai schimbat id-ul modului asta
# (e mod rotativ), deci daca detectia nu mai porneste, aici se schimba.
MAYHEM_QUEUE_ID = 2400

TIER_ORDER = ["S+", "S", "A", "B", "C", "D"]
UNRANKED = "Unranked"

# campionii lipsa din tier list (campioni noi, drift de la patch la patch) nu
# trebuie sa arunce; ii tratam ca pe cel mai prost pick posibil
_UNRANKED_RANK = len(TIER_ORDER)

# numele posibile pentru cell id-ul jucatorului local. Campul nu e documentat
# si s-a mai redenumit intre versiuni de client, deci incercam mai multe.
_LOCAL_CELL_KEYS = ("localPlayerCellId", "localPlayerCellID", "cellId")


def is_mayhem_gameflow(gameflow_session):
    """True daca sesiunea curenta de gameflow e un joc de ARAM Mayhem."""
    if not isinstance(gameflow_session, dict):
        return False
    queue = gameflow_session.get("gameData", {}).get("queue", {})
    return queue.get("id") == MAYHEM_QUEUE_ID


def parse_bench(champ_select_session):
    """Id-urile campionilor de pe bench (optiunile de reroll).

    Clientul expune campul asta sub doua forme, in functie de versiune:
    `benchChampions` (lista de dict-uri) sau `benchChampionIds` (lista de int).
    """
    if not isinstance(champ_select_session, dict):
        return []

    raw = champ_select_session.get("benchChampions")
    if isinstance(raw, list):
        ids = []
        for entry in raw:
            if isinstance(entry, dict):
                cid = entry.get("championId")
                if isinstance(cid, int) and cid > 0:
                    ids.append(cid)
        return ids

    raw = champ_select_session.get("benchChampionIds")
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, int) and c > 0]

    return []


def get_local_player_champion_id(champ_select_session):
    """Id-ul campionului atribuit jucatorului local, sau None."""
    if not isinstance(champ_select_session, dict):
        return None

    cell_id = None
    for key in _LOCAL_CELL_KEYS:
        value = champ_select_session.get(key)
        if isinstance(value, int):
            cell_id = value
            break
    if cell_id is None:
        return None

    for player in champ_select_session.get("myTeam", []) or []:
        if not isinstance(player, dict):
            continue
        if player.get("cellId") == cell_id:
            cid = player.get("championId")
            return cid if isinstance(cid, int) and cid > 0 else None
    return None


def resolve_champion_name(champion_id, champion_data):
    """Numele campionului dupa id (cheile din champion_data.json sunt string)."""
    return champion_data.get(str(champion_id))


def get_tier(champion_name, tier_data, overrides):
    """Tier-ul unui campion. Necunoscut -> UNRANKED, niciodata exceptie."""
    if not champion_name:
        return UNRANKED
    resolved = overrides.get(champion_name, champion_name)
    return tier_data.get(resolved, UNRANKED)


def tier_rank(tier):
    """Pozitia in clasament; mai mic = mai bun."""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return _UNRANKED_RANK


def best_pick(champion_ids, champion_data, tier_data, overrides):
    """Id-ul campionului cu cel mai bun tier din lista. La egalitate, primul."""
    best_id = None
    best_rank = None
    for cid in champion_ids:
        name = resolve_champion_name(cid, champion_data)
        rank = tier_rank(get_tier(name, tier_data, overrides))
        if best_rank is None or rank < best_rank:
            best_id, best_rank = cid, rank
    return best_id


def describe(champion_id, champion_data, tier_data, overrides):
    """{id, name, tier} pentru afisare. Numele necunoscut ramane vizibil ca id."""
    name = resolve_champion_name(champion_id, champion_data)
    return {
        "id": champion_id,
        "name": name or f"#{champion_id}",
        "tier": get_tier(name, tier_data, overrides),
    }
