# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec pentru motorul ARAM Mayhem Helper (fara interfata).

Build:  pyinstaller engine.spec --noconfirm --clean   ->  dist/aram-engine/

Interfata Electron (ui/) il ia din dist/aram-engine si il pune in exe-ul
portabil. Onedir, nu onefile: nu se mai dezarhiveaza la fiecare pornire.
Consola ramane (console=True): vorbim cu interfata pe stdin/stdout; Electron
il porneste cu fereastra ascunsa.

Motorul (app.py) incarca lcu-app/ si ingame-app/ dinamic
(importlib.util), deci fisierele lor .py intra ca DATA, nu ca importuri
normale. Tot ce importa ele la runtime trebuie declarat in hiddenimports.
"""

import pathlib

from PyInstaller.utils.hooks import collect_all

datas = [
    ("icon.ico", "."),
    ("lcu-app/app.py", "lcu-app"),
    ("lcu-app/mayhem_logic.py", "lcu-app"),
    ("lcu-app/tier_list.py", "lcu-app"),
    ("lcu-app/lcu_client.py", "lcu-app"),
    ("lcu-app/champion_data.json", "lcu-app"),
    ("lcu-app/champ_stats.py", "lcu-app"),
    ("lcu-app/tier_data.json", "lcu-app"),
    ("lcu-app/stats_data.json", "lcu-app"),
    ("ingame-app/app.py", "ingame-app"),
    ("ingame-app/augment_tier.py", "ingame-app"),
    ("ingame-app/bundle.py", "ingame-app"),
    ("ingame-app/live_client.py", "ingame-app"),
    ("ingame-app/ocr_augments.py", "ingame-app"),
    ("ingame-app/stat_anvil.py", "ingame-app"),
    ("ingame-app/rules_engine.py", "ingame-app"),
    ("ingame-app/build_scraper.py", "ingame-app"),
    ("ingame-app/build_icons.py", "ingame-app"),
    ("ingame-app/data/icons", "ingame-app/data/icons"),
    ("ingame-app/data/augments", "ingame-app/data/augments"),
    ("ingame-app/data/builds", "ingame-app/data/builds"),
]

# Toate .json-urile din data/ (champion-tags, item-rules, augment-map etc.)
for json_file in sorted(pathlib.Path("ingame-app/data").glob("*.json")):
    datas.append((str(json_file), "ingame-app/data"))

# Pachetele winrt (OCR-ul nativ Windows) sunt incarcate doar dinamic
# (ocr_augments): le colectam complet. Sunt cateva sute de KB, spre deosebire
# de winsdk (varianta veche), care aducea un singur .pyd de 48 MB cu tot WinRT-ul.
winrt_datas, winrt_bins, winrt_hidden = collect_all("winrt")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=winrt_bins,
    datas=datas + winrt_datas,
    hiddenimports=winrt_hidden + [
        "asyncio",
        "difflib",
        "io",
        "requests",
        "urllib3",
        "psutil",
        "mss",
        "PIL.Image",
        "PIL.ImageOps",
        "win32api",
        "win32con",
        "win32gui",
        "win32process",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # plugini de imagine nefolositi (avif singur e 4 MB) si module de test/doc:
    # exe-ul se dezarhiveaza la fiecare pornire, fiecare MB conteaza
    excludes=["PIL._avif", "PIL._webp", "PIL.AvifImagePlugin", "PIL.WebPImagePlugin",
              "unittest", "pydoc", "doctest", "lib2to3", "sqlite3",
              "tkinter", "_tkinter", "PIL.ImageTk"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aram-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="icon.ico",
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="aram-engine")
