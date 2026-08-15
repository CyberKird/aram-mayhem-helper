# ARAM Mayhem helper - in joc (fara Overwolf)

Overlay care, in timpul meciului, arata rosterul (coechipieri + inamici) si
build-ul campionului tau cu itemii relevanti pentru compozitia inamica
evidentiati. Nu are nevoie de Overwolf -- rosterul vine direct de la Riot
local (Live Client Data API).

**Augment-urile oferite nu se pot citi asa** -- Riot nu le expune pe API-ul
asta deloc. Overwolf ramane singura cale non-OCR pentru partea aia (vezi
`../overwolf-app/`); alternativa e OCR pe ecran, nefacuta inca.

## Doua bucati separate, intentionat

| | Cand ruleaza | Ce face |
|---|---|---|
| `app.py` | in timpul jocului | citeste rosterul, arata build-ul din cache. **Niciodata nu porneste un browser.** |
| `prefetch_builds.py` | inainte sa joci | porneste Chromium (Playwright) ca sa ia build-urile de pe u.gg, o data, offline |

Sunt separate pentru ca un Chromium lansat live taie framerate (confirmat:
~40fps pe un setup cu 3 monitoare) - overlay-ul din timpul jocului trebuie sa
fie cat mai usor posibil.

## Instalare

```bash
pip install -r requirements.txt
python -m playwright install chromium   # o singura data, ~300MB
```

## Folosire

```bash
# inainte sa joci (sau oricand, nu conteaza cand):
python prefetch_builds.py                    # cativa campioni comuni
python prefetch_builds.py Ahri Jinx Sett      # campioni specifici
python prefetch_builds.py --all               # toti cei 173 (cateva minute)

# in timpul jocului:
python app.py
```

Overlay-ul apare singur cand incepe un meci de Mayhem (dupa loading screen,
cand Live Client Data API devine disponibil), arata campionul tau si inamicii
detectati. Daca un campion nu e in cache, arata direct ce comanda sa rulezi
ca sa-l aduci (`prefetch_builds.py <nume>`) -- nu incearca sa scrapuiasca pe
loc, niciodata.

## Verificare

```bash
python app.py --selfcheck
```

Verifica logica pura: normalizarea numelor interne Riot ("MonkeyKing" ->
"Wukong"), motorul de reguli, si invariantul critic -- niciun item evidentiat
nu poate fi din afara pool-ului campionului. Scraping-ul live (Playwright) nu
se poate testa offline in acest fel; se verifica separat, manual, cu
`prefetch_builds.py` pe un campion cunoscut.

## Date

Aceleasi surse ca la `overwolf-app/` (u.gg pentru build-uri, Data Dragon
pentru id-uri/tag-uri de campioni). `champion-id-map.json` e specific acestei
aplicatii: face legatura intre numele interne folosite de Live Client Data
API ("FiddleSticks", "Nunu") si numele afisate ("Fiddlesticks", "Nunu & Willump").
