"""Tier list ARAM Mayhem, u.gg patch 26.15.

Sursa unica e u.gg. METAsrc publica si el un tier list de Mayhem, dar il
deriva din date de ARAM + Arena (Riot blocheaza cu 403 datele reale de
Mayhem in match-v5), deci clasamentele difera masiv si nu se pot amesteca.

Cand se schimba patch-ul: rescrie TIER_DATA de pe
https://u.gg/lol/aram-mayhem-tier-list si ruleaza `python app.py --selfcheck`.
"""

_TIERS = {
    "S+": """
        Sett, Jinx, Yunara, Vayne, Dr. Mundo, Kayle
    """,
    "S": """
        Caitlyn, Brand, Sion, Lillia, Graves, Seraphine, Aurelion Sol,
        Aphelios, Ashe, Morgana, Ahri, Viktor, Rell, Leona, Tristana,
        Alistar, Aurora, Shen, Hwei, Sivir, Illaoi
    """,
    "A": """
        Master Yi, Sona, Zaahen, Akshan, Gwen, Singed, Syndra, Bel'Veth,
        Xayah, Heimerdinger, Teemo, Tahm Kench, Briar, Ryze, Jax, Swain,
        Miss Fortune, Xin Zhao, Shyvana, Vel'Koz, Veigar, Yone, Renata Glasc,
        Yuumi, Twisted Fate, Galio, Nautilus, Ekko, Yasuo, Twitch, Milio,
        Sejuani, Vex, Karthus, Volibear, Amumu, Malzahar, Zyra, Janna,
        Samira, Tryndamere, Taric, Maokai, Rammus, Kassadin, Rumble, Nasus,
        Zeri, Soraka, Annie, Wukong, Poppy, Ambessa, Fiora, Kayn, Kalista
    """,
    "B": """
        Kog'Maw, Draven, Trundle, Ornn, Varus, Mordekaiser, Olaf, Kled,
        Smolder, Fizz, Rek'Sai, Gnar, Azir, Fiddlesticks, Vi, Nocturne,
        Nami, Orianna, Vladimir, Quinn, Cassiopeia, Skarner, Viego, Ivern,
        Nilah, Hecarim, Lux, Taliyah, Corki, Riven, Warwick, Urgot, Talon,
        Renekton, Zac, Evelynn, Rakan, Gangplank, Jhin, Ziggs, Lucian,
        Diana, Braum, Jarvan IV
    """,
    "C": """
        Yorick, Elise, Rengar, Lissandra, Udyr, Zilean, Gragas, Sylas,
        Camille, Kennen, Karma, Katarina, Irelia, Pantheon, Cho'Gath, Zed,
        Lulu, Kindred
    """,
    "D": """
        Aatrox, Darius, Kha'Zix, Xerath, Garen, Malphite, K'Sante, Qiyana,
        Nunu & Willump, Anivia, Mel, Zoe, Naafiri, LeBlanc, Neeko, Senna,
        Bard, Akali, Nidalee, Shaco, Jayce, Lee Sin, Kai'Sa, Pyke, Ezreal,
        Thresh, Blitzcrank, Locke
    """,
}

TIER_DATA = {
    name.strip(): tier
    for tier, block in _TIERS.items()
    for name in block.replace("\n", " ").split(",")
    if name.strip()
}

# nume din Data Dragon care nu se potrivesc pe cheile de mai sus.
# Reconcilierea a iesit curata pe 26.15 (173/173 campioni acoperiti), deci e gol.
# Daca selfcheck-ul incepe sa raporteze campioni fara tier, aici se mapeaza.
NAME_OVERRIDES = {}
