"""Acces la Live Client Data API al jocului (127.0.0.1:2999).

Spre deosebire de LCU (champ select), API-ul asta ruleaza doar cat timp e un
meci efectiv pornit (nu in champ select). Expune tot rosterul (ambele echipe),
nu doar echipa proprie -- exact ce ne trebuie pentru build adaptat la comp.
"""

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://127.0.0.1:2999/liveclientdata"


def get(path):
    """JSON-ul de la endpoint, sau None daca jocul nu e pornit / nu raspunde."""
    try:
        r = requests.get(BASE + path, timeout=2, verify=False)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def get_roster():
    """{allies, enemies, local_champion} sau None daca jocul nu ruleaza.

    'allies'/'enemies' sunt liste de nume de campioni (numele Riot intern,
    ex. 'MonkeyKing' pentru Wukong -- normalizat separat la afisare).
    """
    players = get("/playerlist")
    active = get("/activeplayername")
    if not players:
        return None

    local_name = active if isinstance(active, str) else None
    local_team = None
    for p in players:
        if p.get("summonerName") == local_name or p.get("riotIdGameName") == local_name:
            local_team = p.get("team")
            break

    if local_team is None:
        # activeplayername poate lipsi in unele moduri; fallback simplu:
        # jucatorul local e cel al carui items/abilities sunt disponibile
        active_full = get("/activeplayer")
        if isinstance(active_full, dict):
            local_name = active_full.get("summonerName") or local_name

    allies, enemies, local_champ = [], [], None
    enemy_items, ally_items, own_items = [], [], []
    for p in players:
        champ = p.get("championName")
        if not champ:
            continue
        is_local = p.get("summonerName") == local_name or p.get("riotIdGameName") == local_name
        if is_local:
            local_champ = champ
        if local_team is None:
            continue

        names = [i.get("displayName") for i in (p.get("items") or [])
                 if i.get("displayName")]
        if p.get("team") == local_team:
            allies.append(champ)
            if is_local:
                own_items.extend(names)     # ce ai deja cumparat
            else:
                # itemii coechipierilor conteaza pentru golurile de echipa:
                # daca nimeni n-a luat anti-heal, trebuie sa-l iei tu
                ally_items.extend(names)
        else:
            enemies.append(champ)
            # itemii chiar cumparati de inamici: semnal mult mai bun
            # decat tipul campionului cand alegem contra-itemi
            enemy_items.extend(names)

    if local_team is None:
        # nu am putut determina echipa: mai bine gol decat gresit
        return {"allies": [], "enemies": [], "enemy_items": [], "ally_items": [],
                "own_items": own_items, "local_champion": local_champ}

    return {"allies": allies, "enemies": enemies, "enemy_items": enemy_items,
            "ally_items": ally_items, "own_items": own_items,
            "local_champion": local_champ}
