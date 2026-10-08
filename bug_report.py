"""Raport de bug trimis la contact@joltarise.com, direct din aplicatie.

Transport: FormSubmit (formsubmit.co) -- un POST JSON, fara server propriu si
fara credentiale de email in exe. La primul raport, FormSubmit trimite un mail
de activare la contact@joltarise.com; pana e confirmat o data, raportul nu
ajunge. Daca trimiterea pica (fara internet, endpoint blocat), dialogul ofera
un mailto: precompletat ca rezerva.

Ce pleaca: descrierea scrisa de utilizator, emailul lui (optional) si, doar daca
lasa bifat, un bloc de diagnostic pe care il vede inainte sa trimita (versiune,
Windows, faza jocului, ultima citire OCR, ultima eroare). Nicio captura de ecran.
"""

import platform
import sys
import time
import urllib.parse
import webbrowser

import requests

TO = "contact@joltarise.com"
ENDPOINT = f"https://formsubmit.co/ajax/{TO}"
MAX_TEXT = 2000
COOLDOWN = 60          # secunde intre doua trimiteri, impotriva apasarilor repetate
_last_sent = 0.0


def build_diagnostics(version, log_dir, lcu_mon=None, ingame_mon=None):
    """Blocul de diagnostic, ca text. Orice sursa lipsa e sarita, nu crapa."""
    lines = [f"versiune: {version}",
             f"windows: {platform.platform()}",
             f"frozen: {getattr(sys, 'frozen', False)}"]
    if lcu_mon is not None:
        lines.append(f"client league: faza={lcu_mon.phase} eroare={lcu_mon.error or '-'}")
    if ingame_mon is not None:
        lines.append(f"in joc: faza={ingame_mon.phase} status={ingame_mon.status or '-'} "
                     f"ocr={ingame_mon.ocr_status or '-'}")
        try:
            import ocr_augments
            read = ocr_augments.last_read
            lines.append(f"ultima citire OCR: {read['matches']} ({read['status']})")
            for i, t in enumerate(read["texts"], 1):
                lines.append(f"  card {i}: {t.strip()[:160]!r}")
        except Exception:
            pass
    try:
        err = (log_dir / "eroare.log").read_text(encoding="utf-8")
        lines.append("eroare.log (final):\n" + err[-800:])
    except OSError:
        pass
    return "\n".join(lines)


def validate(description, email):
    """Mesaj de eroare pentru utilizator, sau None daca e ok."""
    if len(description.strip()) < 10:
        return "Descrie problema in cateva cuvinte (minim 10 caractere)."
    if len(description) > MAX_TEXT:
        return f"Prea lung (maxim {MAX_TEXT} caractere)."
    email = email.strip()
    if email and not ("@" in email and "." in email.split("@")[-1] and " " not in email):
        return "Adresa de email nu pare valida (las-o goala daca nu vrei raspuns)."
    return None


def send(description, email, diagnostics, version, timeout=10):
    """Trimite raportul. Intoarce (ok, mesaj). Nu ridica niciodata exceptii."""
    global _last_sent
    wait = COOLDOWN - (time.monotonic() - _last_sent)
    if _last_sent and wait > 0:
        return False, f"Asteapta {int(wait)}s inainte de un nou raport."
    payload = {
        "_subject": f"[ARAM Mayhem Helper {version}] bug report",
        "_template": "box",
        "_captcha": "false",
        "_honey": "",
        "message": description.strip()[:MAX_TEXT],
        "diagnostic": diagnostics[:6000],
    }
    if email.strip():
        payload["email"] = email.strip()      # FormSubmit il foloseste ca Reply-To
    try:
        r = requests.post(ENDPOINT, json=payload, timeout=timeout,
                          headers={"Accept": "application/json"})
        data = r.json() if r.content else {}
        if r.status_code == 200 and str(data.get("success")).lower() == "true":
            _last_sent = time.monotonic()
            return True, "Trimis. Multumim!"
        return False, data.get("message") or f"Serverul a raspuns {r.status_code}."
    except Exception as e:
        return False, f"Nu am putut trimite ({type(e).__name__})."


def mailto(description, diagnostics, version):
    """Rezerva: un mailto: precompletat (limitat ca lungime de Windows)."""
    q = urllib.parse.urlencode(
        {"subject": f"[ARAM Mayhem Helper {version}] bug report",
         "body": description.strip()[:900] + "\n\n--\n" + diagnostics[:600]},
        quote_via=urllib.parse.quote)
    webbrowser.open(f"mailto:{TO}?{q}")
