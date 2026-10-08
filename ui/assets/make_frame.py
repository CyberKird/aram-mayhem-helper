"""Rama panoului, taiata din atlasul HUD-ului din joc (clarity_hudatlas.png).

Sursa: https://raw.communitydragon.org/latest/game/assets/ux/lol/clarity_hudatlas.png
Rama minimap-ului e cea mai curata piesa din atlas (interiorul e gol): luam
coltul cu ornament (stanga-sus) si il oglindim in dreapta-sus, iar coltul de
jos cu flare-ul il oglindim in dreapta-jos. Interiorul, pana la linia teal,
devine transparent: acolo panoul isi pune singur fundalul (vezi style.css).

    python make_frame.py <clarity_hudatlas.png>   # scrie hud-frame.png langa el
"""

import pathlib
import sys

from PIL import Image, ImageOps

S = 40                       # latura unui colt in pixeli de atlas = border-image-slice
MAP = (35, 90, 345, 401)     # rama minimap-ului in atlas (doar firul auriu, fara vecini)
FILL = (16, 28, 27)          # umplutura dintre linia teal si gaura hartii


def build(atlas):
    a = Image.open(atlas).convert("RGBA")
    l, t, r, b = MAP
    tl = a.crop((l, t, l + S, t + S))
    bl = a.crop((l, b - S, l + S, b))
    top = a.crop((l + 150, t, l + 154, t + S))
    bottom = a.crop((l + 150, b - S, l + 154, b))
    left = a.crop((l, t + 160, l + S, t + 164))

    out = Image.new("RGBA", (2 * S + 4, 2 * S + 4))
    out.paste(tl, (0, 0))
    out.paste(ImageOps.mirror(tl), (S + 4, 0))
    out.paste(bl, (0, S + 4))
    out.paste(ImageOps.mirror(bl), (S + 4, S + 4))
    out.paste(top, (S, 0))
    out.paste(bottom, (S, S + 4))
    out.paste(left, (0, S))
    out.paste(ImageOps.mirror(left), (S + 4, S))

    # interiorul: umplere din centru peste golul hartii si umplutura plata,
    # pana la linia teal. Exteriorul (coltul de dupa ornament) ramane transparent.
    px = out.load()
    w, h = out.size
    seen, stack = set(), [(w // 2, h // 2)]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
            continue
        seen.add((x, y))
        c = px[x, y]
        if c[3] > 20 and c[:3] != FILL:
            continue
        px[x, y] = (0, 0, 0, 0)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return out


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1])
    frame = build(src)
    dest = pathlib.Path(__file__).with_name("hud-frame.png")
    frame.save(dest)
    # verificare: centrul gol, colturile exterioare goale, firul auriu opac
    assert frame.getpixel((S + 2, S + 2))[3] == 0
    assert frame.getpixel((0, 0))[3] == 0 and frame.getpixel((2 * S + 3, 0))[3] == 0
    assert frame.getpixel((S + 2, 5))[3] == 255, "firul auriu de sus trebuie sa ramana"
    print(dest, frame.size)
