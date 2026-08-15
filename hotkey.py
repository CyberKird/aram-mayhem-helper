"""Hotkey global (arata/ascunde fereastra), fara sa deranjeze jocul.

RegisterHotKey, nu un keyboard hook (SetWindowsHookEx / librarii ca
`keyboard`): un hook global citeste tastele TUTUROR aplicatiilor, ceea ce
anti-cheat-urile moderne il pot trata cu suspiciune. RegisterHotKey doar
inregistreaza o combinatie la Windows si primesti un mesaj cand se apasa,
fara sa citesti nimic din alte procese -- e API-ul standard, folosit de orice
launcher normal (Discord, OBS etc).

Rulam pe fir propriu, cu fereastra proprie invizibila: Tkinter isi are
propria bucla de evenimente (Tcl), separata de PumpMessages de la Win32, deci
nu le putem amesteca in acelasi fir.
"""

import ctypes
import threading

import win32con
import win32gui

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK = {chr(c): c for c in range(0x41, 0x5B)}   # 'A'..'Z' -> cod virtual


class HotkeyListener:
    """Cheama `callback` (din firul propriu) la fiecare apasare a combinatiei.

    `callback` trebuie sa fie sigur de apelat dintr-un fir oarecare -- in
    app.py trece printr-o coada, nu atinge direct widget-uri Tk.
    """

    def __init__(self, callback, modifiers=MOD_CONTROL | MOD_ALT, vk=VK["A"]):
        self.callback = callback
        self.modifiers = modifiers
        self.vk = vk
        self.registered = None   # None = inca nu stim, True/False dupa incercare
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_HOTKEY:
            try:
                self.callback()
            except Exception:
                pass   # un callback picat nu are voie sa opreasca ascultatorul
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _run(self):
        class_name = "AramMayhemHotkeyWindow"
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.lpszClassName = class_name
        wc.hInstance = win32gui.GetModuleHandle(None)
        try:
            atom = win32gui.RegisterClass(wc)
        except win32gui.error:
            atom = class_name   # deja inregistrata (a doua pornire in acelasi proces)

        hwnd = win32gui.CreateWindow(atom, class_name, 0, 0, 0, 0, 0,
                                     0, 0, wc.hInstance, None)

        self.registered = bool(ctypes.windll.user32.RegisterHotKey(
            hwnd, 1, self.modifiers, self.vk))
        if not self.registered:
            return   # combinatia e deja folosita de alt program, nu insistam

        win32gui.PumpMessages()
