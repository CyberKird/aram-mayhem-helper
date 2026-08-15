# ARAM Mayhem Helper

Un overlay local pentru League of Legends, mod ARAM Mayhem. Arata tier-ul campionilor la champ select, plus build si augmente in timpul meciului. Fara Overwolf, fara cont, fara instalare de client separat.

## Ce face

- **Champ select**: tier-ul campionului tau si al celor de pe bench (reroll), cu cel mai bun marcat. Citeste din LCU, API-ul local al clientului League.
- **In joc**: roster complet (coechipieri + inamici), build recomandat cu un singur item per slot (nu meniu de alternative), si augmentele oferite, citite prin OCR nativ Windows.
- **Build-ul reactioneaza la itemii reali ai inamicilor** (armura, magic resist, viata, vindecare), nu doar la tipul de campion.
- **Sfat de vandut cizmele** la build complet, daca nu contreaza compozitia inamica.
- **Tier de augment per campion**, nu doar global: acelasi augment poate fi S+ pe un campion si B pe altul.

## Cum functioneaza

Doua surse de date, fara API oficial pentru ele:

- **LCU** (`127.0.0.1` + port random, gasit din lockfile) pentru champ select.
- **Live Client Data API** (`127.0.0.1:2999`), oficial de la Riot, pentru roster si itemii jucatorilor in timpul meciului.

Augmentele oferite nu au niciun API. Se citesc prin OCR nativ Windows (`Windows.Media.Ocr`), pe o zona centrala a ferestrei jocului.

Build-urile de itemi vin din scraping pe u.gg (ARAM, nu exista date separate de Mayhem pentru itemi). Tier-urile de augment vin tot de pe u.gg, per campion cand exista, altfel din lista globala a modului.

## Instalare (exe)

1. Deschide [Releases](../../releases) si descarca `ARAM-Mayhem-Helper.exe`.
2. Dublu-click. Gata. Fara Python, fara instalare, totul e inclus in exe.

Windows SmartScreen poate avertiza la prima rulare (exe-ul nu e semnat): `More info` -> `Run anyway`.

## Instalare din sursa (alternativa)

1. Descarca proiectul: butonul verde `Code` -> `Download ZIP`, apoi dezarhiveaza.
2. Dublu-click pe `INSTALL.bat` (sau direct pe `START.bat`, care porneste instalarea singur daca lipseste venv-ul).

Instalatorul face tot: instaleaza Python daca lipseste (via winget), creeaza mediul virtual, pune dependentele, ruleaza selfcheck-ul de verificare si lasa o scurtatura `ARAM Mayhem Helper` pe desktop. O singura data, dureaza ~2 minute. Datele (build-uri, tier-uri, iconite) vin deja in repo, nu trebuie descarcate separat.

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
..\.venv\Scripts\python prefetch_builds.py --all --headed
..\.venv\Scripts\python build_champion_augments.py --headed
..\.venv\Scripts\python build_icons.py
..\.venv\Scripts\python build_item_stats.py
```

`--headed` conteaza: Cloudflare blocheaza uneori Chromium headless.

## Pentru dezvoltatori: construirea exe-ului

```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller aram_mayhem_helper.spec --noconfirm --clean
```

Rezultatul e `dist\ARAM-Mayhem-Helper.exe`. Dupa build, verifica-l cu `dist\ARAM-Mayhem-Helper.exe --selfcheck` si publica-l ca asset intr-un Release.

## Ce NU face

- Nu citeste alegerea ta de augment, doar oferta. Riot nu expune asta pe niciun API local.
- Nu garanteaza recunoasterea OCR pe orice rezolutie sau limba a clientului. Testat pe engleza, 4K si 1440p.
- Nu are date de tier pentru toate augmentele. Cateva zeci nu sunt clasate de nicio sursa publica gasita; pentru alea arata descrierea, nu un rank inventat.

## Limitari legale de stiut

Foloseste date scrapuite de pe u.gg (fara API public) si iconite de la Riot Data Dragon / CommunityDragon (permise pentru continut de fan, necomercial, conform politicilor Riot). Nu e inregistrat la Riot Developer Portal si nu respecta cerinta de "supported services from Riot Games for data ingestion". Pastreaza-l pentru uz personal.

## Structura

```
aram-mayhem-helper/
  app.py                  # aplicatia unificata, detecteaza singura faza
  lcu-app/                # champ select (LCU)
  ingame-app/              # in joc (Live Client Data + OCR)
    build_scraper.py       # build-uri de itemi (u.gg ARAM)
    build_champion_augments.py  # tier de augment per campion (u.gg Mayhem)
    build_icons.py         # iconite (Data Dragon, CommunityDragon)
    build_item_stats.py    # stats de item (Data Dragon)
    rules_engine.py         # logica de recomandare, pe date reale de meci
    ocr_augments.py         # citirea augmentelor de pe ecran
```
