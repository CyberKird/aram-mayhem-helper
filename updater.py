"""Verifica pe GitHub daca exista o versiune noua si o instaleaza singur.

Merge doar pe exe (build PyInstaller). Din sursa n-are ce inlocui -- acolo
actualizarea inseamna `git pull`, si o spunem in loc s-o facem.

Windows nu lasa un .exe care ruleaza sa fie suprascris, dar lasa sa fie
REDENUMIT. De aici apply(): mutam exe-ul curent in .old, punem noul exe pe
locul lui, si iesim. Daca ceva pica la jumatate, .old e inca acolo si se
poate reveni manual; .old-ul ramas se sterge la pornirea urmatoare.

NU repornim singuri aplicatia. Prima versiune facea asta cu un .cmd care
astepta, stergea .old si redeschidea exe-ul -- iar Vanguard (anti-cheat-ul
Riot) se plangea cu "failed to obtain executable path for parent process",
pentru ca procesul nou ramanea cu un parinte disparut. Nu ocolim asta si nu
ne ascundem de el: pur si simplu nu mai pornim procese in lant. Descarcarea
si inlocuirea raman automate, repornirea o face utilizatorul cu un dublu-click.
"""

import pathlib
import sys
import tempfile

import requests

REPO = "CyberKird/aram-mayhem-helper"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "ARAM-Mayhem-Helper.exe"
TIMEOUT = 10


def is_frozen():
    return getattr(sys, "frozen", False)


def parse(tag):
    """'v1.2.3' -> (1, 2, 3). Ce nu e numar devine 0, ca sa nu crape."""
    nums = []
    for part in str(tag).lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple(nums[:3] or [0])


def check(current):
    """(tag, url_asset) daca exista ceva mai nou, altfel None.

    Orice eroare de retea inseamna doar "nu verificam acum": aplicatia
    trebuie sa porneasca si fara internet, verificarea nu e esentiala.
    """
    try:
        r = requests.get(LATEST, timeout=TIMEOUT,
                         headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    tag = data.get("tag_name") or ""
    if parse(tag) <= parse(current):
        return None

    for asset in data.get("assets") or ():
        if asset.get("name") == ASSET and asset.get("browser_download_url"):
            return tag, asset["browser_download_url"]
    return None


def download(url):
    """Descarca noul exe intr-un fisier temporar si da calea lui."""
    fd, tmp = tempfile.mkstemp(suffix=".exe", prefix="aram-update-")
    os.close(fd)
    tmp = pathlib.Path(tmp)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    if tmp.stat().st_size < 1 << 20:      # un exe real are zeci de MB
        tmp.unlink(missing_ok=True)
        raise OSError("fisier descarcat prea mic, probabil eroare")
    return tmp


def cleanup(exe=None):
    """Sterge .old-ul ramas de la actualizarea precedenta, daca exista.

    Se apeleaza la pornire: atunci sigur nu mai ruleaza nimic din el.
    """
    current = pathlib.Path(exe or sys.executable)
    try:
        current.with_suffix(".old.exe").unlink(missing_ok=True)
    except OSError:
        pass          # ramane pe disc, incercam data viitoare


def apply(new_exe, exe=None):
    """Pune noul exe pe locul celui curent. Aplicatia trebuie repornita apoi."""
    current = pathlib.Path(exe or sys.executable)
    old = current.with_suffix(".old.exe")

    old.unlink(missing_ok=True)
    current.rename(old)                   # permis chiar daca ruleaza
    try:
        pathlib.Path(new_exe).replace(current)
    except OSError:
        old.rename(current)               # punem la loc daca n-a mers
        raise
    return current


def update_if_available(current_version):
    """(tag_nou, None) daca s-a instalat ceva nou, altfel (None, motiv).

    Cu un tag intors, exe-ul de pe disc e deja cel nou, dar procesul curent
    ruleaza tot codul vechi -- apelantul trebuie sa spuna omului sa reporneasca.
    """
    if not is_frozen():
        return None, "din sursa: foloseste git pull"
    cleanup()
    found = check(current_version)
    if not found:
        return None, "esti la zi"
    tag, url = found
    try:
        new_exe = download(url)
    except Exception as e:
        return None, f"descarcare esuata: {type(e).__name__}"
    try:
        apply(new_exe)
    except OSError as e:
        return None, f"instalare esuata: {type(e).__name__}"
    return tag, None


def selfcheck():
    assert parse("v1.2.3") == (1, 2, 3)
    assert parse("1.0.0") == (1, 0, 0)
    assert parse("v2.0") == (2, 0)
    assert parse("brambura") == (0,)
    assert parse("v1.0.1") > parse("v1.0.0")
    assert parse("v1.10.0") > parse("v1.9.0"), "comparatie numerica, nu de text"
    assert not parse("v1.0.0") > parse("v1.0.0")
    # din sursa nu incearca niciodata sa inlocuiasca ceva
    if not is_frozen():
        assert update_if_available("1.0.0") == (None, "din sursa: foloseste git pull")

    # schimbul de fisiere, pe fisiere de mucava: partea care chiar poate
    # strica instalarea cuiva, deci merita verificata fara sa reconstruim exe
    import tempfile as _tf
    with _tf.TemporaryDirectory() as d:
        fake = pathlib.Path(d) / "app.exe"
        fake.write_bytes(b"vechi")
        nou = pathlib.Path(d) / "descarcat.exe"
        nou.write_bytes(b"nou")

        apply(nou, exe=fake)
        assert fake.read_bytes() == b"nou", "exe-ul n-a fost inlocuit"
        assert fake.with_suffix(".old.exe").read_bytes() == b"vechi", \
            "versiunea veche trebuie pastrata pana la pornirea urmatoare"
        assert not nou.exists(), "fisierul descarcat trebuia mutat, nu copiat"

        cleanup(exe=fake)
        assert not fake.with_suffix(".old.exe").exists(), ".old n-a fost curatat"
        cleanup(exe=fake)          # a doua oara nu are voie sa crape

    print("selfcheck OK (updater)")
