"""Pachetul de date Mayhem (build-uri, augmente per campion, tier global).

Doua copii: cea din pachet (data/mayhem-bundle.json, scrisa de
update_aramkit.py) si cea adusa de data_sync.py in ARAM_DATA_DIR. O folosim pe
cea cu patch-ul mai mare. Fara niciuna, get() intoarce {} si apelantii cad pe
fisierele per campion din data/builds si data/augments.
"""

import json
import os
import pathlib

BUNDLED = pathlib.Path(__file__).with_name("data") / "mayhem-bundle.json"

_cache = None


def _read(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _vkey(version):
    return tuple(int(x) if x.isdigit() else 0 for x in str(version or "").split("."))


def get():
    global _cache
    if _cache is None:
        best = _read(BUNDLED)
        folder = os.environ.get("ARAM_DATA_DIR")
        if folder:
            synced = _read(pathlib.Path(folder) / BUNDLED.name)
            if _vkey(synced.get("revision")) > _vkey(best.get("revision")):
                best = synced
        _cache = best
    return _cache
