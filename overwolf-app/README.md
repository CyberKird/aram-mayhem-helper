# ARAM Mayhem helper - in joc (Overwolf)

Overlay care, in timpul meciului de ARAM Mayhem, arata:

- **tier-ul augmentelor oferite** (S+ ... D), cu cel mai bun marcat `BEST`;
- **build-ul campionului tau** de pe u.gg, cu itemii relevanti pentru
  compozitia inamica evidentiati.

E aplicatie Overwolf pentru ca augmentele **nu** se pot citi altfel: Live Client
Data API-ul lui Riot (`127.0.0.1:2999`) nu expune deloc optiunile oferite, iar
singura sursa structurata fara OCR e Game Events Provider-ul de la Overwolf.

## Instalare

1. Instaleaza clientul Overwolf.
2. Overwolf → Settings → About → Development options → **Load unpacked extension**
   → alege folderul `overwolf-app`.

Nu trebuie publicata in store. Riot cere aprobare pentru aplicatii care se
distribuie public; pentru un tool personal, nedistribuit, nu se aplica.

## Verificare

```bash
node scripts/selfcheck.js
```

Verifica logica pura: parsarea rosterului (mai multe forme de payload),
traducerea id intern → nume de augment (toate cele 206 clasate pe u.gg),
cautarea de tier cu rezerva pe raritate si **invariantul critic** - motorul de
reguli nu propune niciodata un item din afara pool-ului campionului.

Aspectul overlay-ului se poate verifica intr-un browser obisnuit:

```
overlay/overlay.html?mock=1
```

Ce **nu** se poate verifica automat, trebuie confirmat intr-un meci real:
ca GEP chiar trimite `arena_teams` / `me.augments` / `me.picked_augment` la
momentul potrivit si in forma asteptata (documentatia Overwolf nu fixeaza
structura exacta, de aceea parserul accepta mai multe forme), si ca scrape-ul
de build apuca sa termine pana la finalul loading screen-ului.

## Date

| Fisier | Ce e | Cum se reface |
|---|---|---|
| `data/augments-global.json` | tier de augmente pe raritate | manual, de pe [u.gg](https://u.gg/lol/aram-mayhem-augment-tier-list) |
| `data/augment-map.json` | id intern → nume + raritate | `python scripts/build_augment_map.py` |
| `data/champion-tags.json` | clasa + tip de damage | `python scripts/build_champion_tags.py` |
| `data/item-sprites.json` | coordonata sprite → nume item | `python scripts/build_item_sprites.py` |
| `data/builds/*.json` | build pe campion | automat, la prima intalnire a campionului |

Build-urile pe campion **nu** se descarca toate dinainte. Se aduc la prima
intalnire a campionului si raman in cache.

## Note tehnice

- **Sursa augmentelor**: `cherry-augments.json` din datele de joc, nu
  `cdragon/arena/en_us.json`. Al doilea acopera doar modul Arena si ii lipsesc
  peste 100 din augmentele de Mayhem.
- **Itemii de pe u.gg**: pagina nu contine id-uri de itemi, deseneaza fiecare
  item dintr-un sprite sheet prin `background-position`. Coordonatele sunt exact
  cele publicate de Data Dragon, deci maparea inversa e exacta, nu ghicita.
- **Regulile de build sunt euristici, nu date de matchup.** Nu exista nicaieri
  build-uri de ARAM conditionate de compozitie. Regulile din `rules/item-rules.json`
  doar *evidentiaza* itemi care exista deja in build-ul campionului de pe u.gg;
  prin constructie nu pot propune un item din afara lui.
