"""Pozitiile panourilor, pastrate intre sesiuni.

Fiecare panou se muta cu mouse-ul si isi tine minte locul. Nu ancoram la
HUD-ul jocului: pozitia lui depinde de rezolutie si de scala HUD din setari,
iar unii jucatori il tin ascuns cu totul -- o ancorare "automata" ar fi de
fapt o ghicire care se strica pe alt sistem.

Fisierul sta langa exe/script, nu in %APPDATA%: aplicatia e portabila, o
copiezi si merge cu tot cu asezarea ta.
"""

import json
import pathlib


class Settings:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.data = {}
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass   # prima pornire, sau fisier stricat: pornim de la zero

    def pos(self, name, default):
        """(x, y) pentru panoul `name`, sau `default` daca n-a fost mutat inca."""
        got = self.data.get(name)
        if isinstance(got, list) and len(got) == 2:
            return tuple(got)
        return default

    def set_pos(self, name, x, y):
        self.data[name] = [int(x), int(y)]
        self.save()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        except OSError:
            pass   # disc plin / drepturi: pierdem doar memorarea pozitiei
