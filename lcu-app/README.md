# ARAM Mayhem helper - champ select

Overlay care arata tier-ul campionilor de pe bench in champ select de ARAM Mayhem.
Se afiseaza singur cand intri in champ select si dispare cand se termina.

```bash
pip install -r requirements.txt
python app.py
```

`Escape` sau X inchide overlay-ul.

## Verificare

```bash
python app.py --selfcheck
```

Verifica logica pura (parsare bench, tier, best pick) fara League pornit. Include
si o reconciliere: daca u.gg ramane in urma cu campioni noi, selfcheck-ul pica si
arata exact care campioni n-au tier.

Ce **nu** poate verifica selfcheck-ul, trebuie confirmat manual intr-un joc real:
numele exacte ale campurilor din LCU (`localPlayerCellId`, `benchChampions` vs
`benchChampionIds`) si ca overlay-ul apare la momentul potrivit.

## Actualizare la patch nou

1. `python build_champion_data.py` - reface maparea id -> nume din Data Dragon.
2. Rescrie `TIER_DATA` din `tier_list.py` de pe
   <https://u.gg/lol/aram-mayhem-tier-list>.
3. `python app.py --selfcheck`.

## Note

- Portul si tokenul LCU se schimba la fiecare pornire a clientului, deci se
  citesc de fiecare data din argumentele procesului `LeagueClientUx.exe`.
- Data Dragon are si id-uri de varianta (`60000 + id`) pentru modurile speciale.
  Maparea le acopera pe amandoua, deci tier-ul iese corect indiferent ce id
  trimite clientul.
- Riot blocheaza cu 403 datele reale de Mayhem in match-v5, deci **niciun** tier
  list de Mayhem nu e bazat pe meciuri reale de Mayhem. u.gg e sursa aleasa aici;
  METAsrc deriva explicit din ARAM + Arena si da un clasament complet diferit.
  Trateaza tier-urile ca aproximare, nu ca adevar.
