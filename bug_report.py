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


def open_dialog(root, theme, version, log_dir, lcu_mon=None, ingame_mon=None):
    """Fereastra de raport, in stilul aplicatiei. theme: dict cu culori/fonturi."""
    import tkinter as tk

    t = theme
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=t["gold"])
    inner = tk.Frame(win, bg=t["bg"])
    inner.pack(padx=1, pady=1, fill="both", expand=True)

    head = tk.Frame(inner, bg=t["bg"])
    head.pack(fill="x", padx=10, pady=(8, 6))
    tk.Label(head, text="RAPORTEAZA UN BUG", bg=t["bg"], fg=t["gold"],
             font=t["heading"](8)).pack(side="left")
    closer = tk.Label(head, text="X", bg=t["bg"], fg=t["gold"], font=t["heading"](8),
                      cursor="hand2", padx=4)
    closer.pack(side="right")
    closer.bind("<Button-1>", lambda _e: win.destroy())
    tk.Frame(inner, bg=t["line"], height=1).pack(fill="x")

    form = tk.Frame(inner, bg=t["bg"])
    form.pack(fill="both", expand=True, padx=12, pady=10)

    def label(text):
        tk.Label(form, text=text, bg=t["bg"], fg=t["dim"], font=t["body"](9),
                 anchor="w").pack(fill="x", pady=(6, 2))

    def border():
        # chenar de 1px in jurul campului
        frame = tk.Frame(form, bg=t["edge"])
        frame.pack(fill="x")
        return frame

    label("CE S-A INTAMPLAT?")
    text = tk.Text(border(), height=6, width=44, wrap="word", bg=t["card"], fg=t["text"],
                   insertbackground=t["text"], relief="flat", font=t["body"](10),
                   padx=6, pady=5)
    text.pack(padx=1, pady=1)

    label("EMAIL (OPTIONAL, DACA VREI RASPUNS)")
    email = tk.Entry(border(), bg=t["card"], fg=t["text"], insertbackground=t["text"],
                     relief="flat", font=t["body"](10))
    email.pack(fill="x", padx=1, pady=1, ipady=4)

    include = tk.BooleanVar(value=True)
    diag = build_diagnostics(version, log_dir, lcu_mon, ingame_mon)
    tk.Checkbutton(form, text="Include diagnostic (vezi ce trimiti mai jos)",
                   variable=include, bg=t["bg"], fg=t["dim"], selectcolor=t["card"],
                   activebackground=t["bg"], activeforeground=t["text"],
                   font=t["body"](9), anchor="w", bd=0, highlightthickness=0
                   ).pack(fill="x", pady=(8, 2))
    tk.Label(form, text=diag[:420] + ("..." if len(diag) > 420 else ""),
             bg=t["bg"], fg=t["dim"], font=("Consolas", 8), anchor="w",
             justify="left", wraplength=t["px"](340)).pack(fill="x")

    result = tk.Label(form, text="", bg=t["bg"], fg=t["dim"], font=t["body"](9),
                      anchor="w", justify="left", wraplength=t["px"](340))
    result.pack(fill="x", pady=(8, 0))

    buttons = tk.Frame(form, bg=t["bg"])
    buttons.pack(fill="x", pady=(8, 0))
    send_btn = tk.Label(buttons, text="TRIMITE", bg=t["gold"], fg=t["bg"],
                        font=t["heading"](8), cursor="hand2", padx=14, pady=5)
    send_btn.pack(side="right")
    mail_btn = tk.Label(buttons, text="DESCHIDE EMAIL", bg=t["bg"], fg=t["gold"],
                        font=t["heading"](7), cursor="hand2", padx=8, pady=5)

    def current_diag():
        return diag if include.get() else "(diagnostic omis de utilizator)"

    def do_send(_e=None):
        desc, addr = text.get("1.0", "end"), email.get()
        problem = validate(desc, addr)
        if problem:
            result.configure(text=problem, fg=t["down"])
            return
        send_btn.configure(text="SE TRIMITE...")
        win.update_idletasks()
        ok, msg = send(desc, addr, current_diag(), version)
        result.configure(text=msg, fg=t["accent"] if ok else t["down"])
        send_btn.configure(text="TRIMITE")
        if ok:
            win.after(1500, win.destroy)
        else:
            mail_btn.pack(side="right")      # rezerva, doar dupa un esec

    send_btn.bind("<Button-1>", do_send)
    mail_btn.bind("<Button-1>",
                  lambda _e: mailto(text.get("1.0", "end"), current_diag(), version))
    win.bind("<Escape>", lambda _e: win.destroy())

    win.update_idletasks()
    x = root.winfo_x() - win.winfo_width() - 8
    if x < 0:
        x = root.winfo_x() + root.winfo_width() + 8
    win.geometry(f"+{max(0, x)}+{root.winfo_y()}")
    win.focus_force()
    text.focus_set()
    return win
