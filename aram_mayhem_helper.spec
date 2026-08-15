# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec pentru ARAM Mayhem Helper.

Build:  pyinstaller aram_mayhem_helper.spec --noconfirm --clean

Aplicatia unificata (app.py) incarca lcu-app/ si ingame-app/ dinamic
(importlib.util), deci fisierele lor .py intra ca DATA, nu ca importuri
normale. Tot ce importa ele la runtime trebuie declarat in hiddenimports.
"""

import pathlib

from PyInstaller.utils.hooks import collect_all

datas = [
    ("lcu-app/app.py", "lcu-app"),
    ("lcu-app/mayhem_logic.py", "lcu-app"),
    ("lcu-app/tier_list.py", "lcu-app"),
    ("lcu-app/lcu_client.py", "lcu-app"),
    ("lcu-app/champion_data.json", "lcu-app"),
    ("ingame-app/app.py", "ingame-app"),
    ("ingame-app/augment_tier.py", "ingame-app"),
    ("ingame-app/live_client.py", "ingame-app"),
    ("ingame-app/ocr_augments.py", "ingame-app"),
    ("ingame-app/rules_engine.py", "ingame-app"),
    ("ingame-app/build_scraper.py", "ingame-app"),
    ("ingame-app/build_icons.py", "ingame-app"),
    ("ingame-app/data/icons", "ingame-app/data/icons"),
    ("ingame-app/data/fonts", "ingame-app/data/fonts"),
    ("ingame-app/data/augments", "ingame-app/data/augments"),
    ("ingame-app/data/builds", "ingame-app/data/builds"),
]

# Toate .json-urile din data/ (champion-tags, item-rules, augment-map etc.)
for json_file in sorted(pathlib.Path("ingame-app/data").glob("*.json")):
    datas.append((str(json_file), "ingame-app/data"))

# winsdk e incarcat doar dinamic (ocr_augments) - il colectam complet.
winsdk_datas, winsdk_bins, winsdk_hidden = collect_all("winsdk")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=winsdk_bins,
    datas=datas + winsdk_datas,
    hiddenimports=winsdk_hidden + [
        "asyncio",
        "difflib",
        "io",
        "requests",
        "urllib3",
        "psutil",
        "mss",
        "PIL.Image",
        "win32api",
        "win32con",
        "win32gui",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ARAM-Mayhem-Helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="icon.ico",
)
