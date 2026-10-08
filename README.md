# ARAM Mayhem Helper

Un overlay local pentru League of Legends, mod ARAM Mayhem. Arata tier-ul campionilor la champ select, plus build si augmente in timpul meciului. Fara Overwolf, fara cont, fara instalare de client separat.

## Ce face

- **Champ select**: tier-ul campionului tau si al celor de pe bench (reroll), cu cel mai bun marcat. Citeste din LCU, API-ul local al clientului League.
- **In joc**: roster complet (coechipieri + inamici), build recomandat cu un singur item per slot (nu meniu de alternative), si augmentele oferite, citite prin OCR nativ Windows.
- **Build-ul reactioneaza la itemii reali ai inamicilor** (armura, magic resist, viata, vindecare), nu doar la tipul de campion.
- **Sfat de vandut cizmele** la build complet, daca nu contreaza compozitia inamica.
- **Tier de augment per campion**, nu doar global: acelasi augment poate fi S+ pe un campion si B pe altul.
- **Stat Anvil**: cand cumperi unul, o banda deasupra cardurilor arata care shard e cel mai bun pe campionul tau si contra compozitiei inamice.
- **Augmentele care cer un item anume** ("Upgrade Zhonya's") il urca in capul listei de cumparat. Click pe insigna augmentului ales ca sa-l confirmi -- Riot nu expune nicaieri ce ai ales.
- **Statistici per campion**: win rate, pick rate si cum s-au schimbat fata de patch-ul anterior (sageti verzi/rosii, plus schimbarea de tier u.gg), la champ select si in joc.
- **Raport de bug** direct din aplicatie (butonul `BUG`), trimis la contact@joltarise.com, cu un diagnostic pe care il vezi inainte sa pleace.
- **Stat Anvil** arata in panou si motivul recomandarii pentru campionul tau.
- **Itemele care evolueaza** (Manamune -> Muramana, Archangel's -> Seraph's etc.) conteaza ca detinute dupa transformare.
- **Se actualizeaza singur**: exe-ul din Releases, iar tier-urile si statisticile de patch se iau din repo la pornire, fara exe nou.

## Cum functioneaza

Doua surse de date, fara API oficial pentru ele:

- **LCU** (`127.0.0.1` + port random, gasit din lockfile) pentru champ select.
- **Live Client Data API** (`127.0.0.1:2999`), oficial de la Riot, pentru roster si itemii jucatorilor in timpul meciului.

Augmentele oferite nu au niciun API. Se citesc prin OCR nativ Windows (`Windows.Media.Ocr`), pe o zona centrala a ferestrei jocului.

Aplicatia are doua bucati: **motorul** (Python, `app.py`), care face toata logica si OCR-ul, si **interfata** (Electron, `ui/`), care il porneste ca proces copil si deseneaza panoul. Vorbesc prin JSON pe stdin/stdout. In meci panoul e o piesa a HUD-ului: rama e taiata din atlasul de texturi al jocului (`ui/assets/make_frame.py`), iar fonturile sunt cele ale jocului (Beaufort, Spiegel), luate o data de pe CommunityDragon la prima pornire. Pozitionarea lucreaza per monitor, deci arata la fel pe 1080p, 1440p si 4K, si cu monitoare cu scalari diferite.

Statisticile (win rate, pick rate, istoric pe patch-uri) vin de pe [ARAMKit](https://aramkit.com), singura sursa gasita cu cifre reale de Mayhem pe toti campionii (peste 28M meciuri). Riot blocheaza meciurile de Mayhem in match-v5 si Data Dragon nu are win rate. `ingame-app/update_aramkit.py` aduce tot ce e de Mayhem (statistici, modificatorii de balans per campion, build-uri de itemi, tier de augmente), fara browser. `lcu-app/update_tier_list.py` aduce tier list-ul u.gg si pastreaza patch-ul anterior pentru comparatie.

Build-urile de itemi, tier-urile de augment (per campion, din win rate real) si summoner spells vin strict din date de ARAM Mayhem, nu din ARAM clasic.

## Instalare (exe)

1. Deschide [Releases](../../releases) si descarca `ARAM-Mayhem-Helper.exe`.
2. Dublu-click. Se instaleaza singur (fara intrebari, fara drepturi de admin), pune o scurtatura pe desktop si porneste. Dupa asta porneste in sub o secunda.

Windows SmartScreen poate avertiza la prima rulare (exe-ul nu e semnat): `More info` -> `Run anyway`.

Update-urile se descarca singure in fundal (doar diferenta) si se instaleaza cand inchizi aplicatia; in afara meciului si a champ select-ului aplicatia se reporneste singura pe versiunea noua, iar `UPDATE` din bara de titlu face asta pe loc. Repornirea o face installerul prin shell, deci procesul nou are ca parinte `explorer.exe` (Vanguard se plange de procesele ramase fara parinte). Cu `--no-update` sare peste verificare.

Versiunile 1.x (exe-ul Python) se muta singure pe 2.x: updater-ul lor descarca `ARAM-Mayhem-Helper.exe`, care acum e installerul.

## Instalare din sursa (alternativa)

1. Descarca proiectul: butonul verde `Code` -> `Download ZIP`, apoi dezarhiveaza.
2. Dublu-click pe `INSTALL.bat` (sau direct pe `START.bat`, care porneste instalarea singur daca lipseste venv-ul).

Instalatorul face tot: instaleaza Python si Node.js daca lipsesc (via winget), creeaza mediul virtual, pune dependentele (Python si interfata), ruleaza selfcheck-ul de verificare si lasa o scurtatura `ARAM Mayhem Helper` pe desktop. O singura data, dureaza cateva minute. Datele (build-uri, tier-uri, iconite) vin deja in repo, nu trebuie descarcate separat.

## Verificare

```bash
.venv\Scripts\python app.py --selfcheck
```

Ruleaza logica pura offline (fara League pornit), inclusiv acoperirea de iconite si testele de regresie pe reguli.

## Pentru dezvoltatori: regenerarea datelor

Doar daca vrei sa reiei scraping-ul dupa un patch (build-uri, tier-uri de augment):

```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m playwright install chromium
cd ingame-app
..\.venv\Scripts\python update_aramkit.py
..\.venv\Scripts\python build_icons.py
..\.venv\Scripts\python build_item_stats.py
cd ..\lcu-app
..\.venv\Scripts\python update_tier_list.py
```

`--headed` conteaza: Cloudflare blocheaza uneori Chromium headless.

## Pentru dezvoltatori: interfata si build-ul

Interfata, din sursa, cu motorul real sau cu unul de test care reda o stare dintr-un fisier (scenariile se fac cu `ui\test\make_scenarios.py`):

```bash
cd ui
npm install
npx electron .                                   # motorul real (..\app.py)
set ARAM_MOCK=%CD%\test\game1080.json && npx electron .   # stare de test, fara joc
```

Build-ul, in ordinea asta:

```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller engine.spec --noconfirm --clean     # -> dist\aram-engine\
dist\aram-engine\aram-engine.exe --selfcheck
cd ui && npx electron-builder --win nsis --publish never       # -> dist\ARAM-Mayhem-Helper.exe
```

Versiunea e una singura, in `ui/package.json`: ridic-o INAINTE de build, egala cu tag-ul Release-ului. In Release pune trei fisiere din `dist\`: `ARAM-Mayhem-Helper.exe`, `ARAM-Mayhem-Helper.exe.blockmap` si `latest.yml` (din ultimele doua isi iau update-urile aplicatiile deja instalate).

## Ce NU face

- Nu citeste alegerea ta de augment, doar oferta. Riot nu expune asta pe niciun API local.
- Nu garanteaza recunoasterea OCR pe orice rezolutie sau limba a clientului. Testat pe engleza, 4K si 1440p.
- Nu are date de tier pentru toate augmentele. Cateva zeci nu sunt clasate de nicio sursa publica gasita; pentru alea arata descrierea, nu un rank inventat.

## Limitari legale de stiut

Foloseste date scrapuite de pe u.gg (fara API public), iconite de la Riot Data Dragon / CommunityDragon si piese din atlasul HUD-ului jocului (permise pentru continut de fan, necomercial, conform politicilor Riot). Fonturile jocului nu sunt incluse in aplicatie: le descarca fiecare instalare, de pe CommunityDragon. Nu e inregistrat la Riot Developer Portal si nu respecta cerinta de "supported services from Riot Games for data ingestion". Pastreaza-l pentru uz personal.

## Structura

```
aram-mayhem-helper/
  app.py                  # motorul: detecteaza singur faza, trimite starea interfetei
  ui/                     # interfata Electron (panou, insigne, tooltip, raport de bug)
    main.js               # ferestrele, pozitionarea per monitor, update-urile
    renderer/             # ce deseneaza fiecare fereastra
    assets/make_frame.py  # rama HUD taiata din atlasul jocului
  lcu-app/                # champ select (LCU)
  ingame-app/              # in joc (Live Client Data + OCR)
    build_scraper.py       # build-uri de itemi (u.gg ARAM)
    build_champion_augments.py  # tier de augment per campion (u.gg Mayhem)
    build_icons.py         # iconite (Data Dragon, CommunityDragon)
    build_item_stats.py    # stats de item (Data Dragon)
    rules_engine.py         # logica de recomandare, pe date reale de meci
    ocr_augments.py         # citirea augmentelor de pe ecran
```
