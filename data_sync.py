"""Aduce la pornire cele mai noi tier-uri si statistici din repo, fara exe nou.

Fisierele tier_data.json, stats_data.json si mayhem-bundle.json din repo se actualizeaza la fiecare
patch; exe-ul are o copie in el, dar aici luam una mai noua daca exista si o
punem langa exe. Incarcarea alege apoi fisierul cu patch-ul mai mare
(vezi tier_list.newest). Orice esec (fara internet, JSON stricat) lasa copia
veche: aplicatia trebuie sa porneasca si offline.
"""

import json
import pathlib

import requests

RAW = "https://raw.githubusercontent.com/CyberKird/aram-mayhem-helper/master/"
# fisier -> (cale in repo, cheia de versiune, cheia care trebuie sa existe)
FILES = {
    "tier_data.json": ("lcu-app/", "patch", "tiers"),
    "stats_data.json": ("lcu-app/", "revision", "champions"),
    "mayhem-bundle.json": ("ingame-app/data/", "revision", "builds"),
}
TIMEOUT = 8


def sync(dest):
    """Descarca fisierele in `dest`. Intoarce lista celor actualizate."""
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    updated = []
    for name, (folder, version_key, required) in FILES.items():
        try:
            r = requests.get(RAW + folder + name, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            data = r.json()
            if not data.get(version_key) or not data.get(required):
                continue            # raspuns ciudat: nu stricam ce avem
            (dest / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            updated.append(name)
        except Exception:
            continue
    return updated
