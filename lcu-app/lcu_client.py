"""Acces la API-ul local al clientului de League (LCU).

Portul si tokenul se schimba la fiecare pornire a clientului, deci se citesc
de fiecare data din linia de comanda a procesului LeagueClientUx.exe (mai
robust decat lockfile-ul, care depinde de unde e instalat jocul).
"""

import re

import psutil
import requests
import urllib3

# certificatul LCU e self-signed pe 127.0.0.1; verificarea nu are ce sa apere aici
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROCESS_NAME = "LeagueClientUx.exe"
_PORT_RE = re.compile(r"--app-port=(\d+)")
_TOKEN_RE = re.compile(r"--remoting-auth-token=([\w-]+)")


def find_lcu_process():
    """Procesul clientului de League, sau None daca nu ruleaza."""
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == PROCESS_NAME:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def get_lcu_credentials():
    """(port, token) din argumentele procesului, sau None."""
    proc = find_lcu_process()
    if proc is None:
        return None
    try:
        cmdline = " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        # procesul poate disparea intre listare si citirea argumentelor
        return None

    port = _PORT_RE.search(cmdline)
    token = _TOKEN_RE.search(cmdline)
    if not port or not token:
        return None
    return port.group(1), token.group(1)


class LCUClient:
    def __init__(self, port, token):
        self.base = f"https://127.0.0.1:{port}"
        self.session = requests.Session()
        self.session.auth = ("riot", token)
        self.session.verify = False

    def get(self, path):
        """JSON-ul de la endpoint, sau None.

        404 inseamna "nu exista sesiune activa", caz normal, nu eroare.
        """
        try:
            r = self.session.get(self.base + path, timeout=2)
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None


def connect():
    """LCUClient gata de folosit, sau None daca clientul nu ruleaza."""
    creds = get_lcu_credentials()
    return LCUClient(*creds) if creds else None
