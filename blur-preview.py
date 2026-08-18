#!/usr/bin/env python3
"""Zeichnet die Sperrkaesten aus content/fotos.json ueber das Original.

Warum: `blur` sind relative Kaesten und werden von Hand gepflegt. Am 17.08. lagen
drei von vier Kaesten zu tief und ein ganzer Satz Roller-Kennzeichen war uebersehen —
sichtbar erst mit eingezeichneten Rahmen, nicht im Test. Der Test prueft, DASS
weichgezeichnet wird, nicht WO.

    python3 blur-preview.py 2026-08-18_033254.jpg          # Kaesten aus fotos.json
    python3 blur-preview.py 2026-08-18_033254.jpg --raster # zusaetzlich 10%-Raster

Schreibt nach /tmp/blur-preview-<datei>.jpg. Aendert nichts am Repo.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

WURZEL = Path(__file__).resolve().parent
QUELLE = Path.home() / "repos" / "assistant" / "state" / "attachments"


def main(argv):
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    datei = argv[0]
    raster = "--raster" in argv

    original = QUELLE / datei
    if not original.exists():
        print(f"nicht gefunden: {original}")
        return 2

    fotos = json.loads((WURZEL / "content" / "fotos.json").read_text())
    eintrag = fotos.get(datei, {})
    kaesten = eintrag.get("blur", [])

    bild = Image.open(original).convert("RGB")
    b, h = bild.size
    stift = ImageDraw.Draw(bild)

    if raster:
        for i in range(1, 10):
            stift.line([(b * i / 10, 0), (b * i / 10, h)], fill=(255, 255, 0), width=1)
            stift.line([(0, h * i / 10), (b, h * i / 10)], fill=(255, 255, 0), width=1)
            stift.text((b * i / 10 + 3, 3), f"{i}", fill=(255, 255, 0))
            stift.text((3, h * i / 10 + 3), f"{i}", fill=(255, 255, 0))

    for x, y, breite, hoehe in kaesten:
        stift.rectangle([x * b, y * h, (x + breite) * b, (y + hoehe) * h],
                        outline=(255, 0, 0), width=3)

    ziel = Path("/tmp") / f"blur-preview-{datei}"
    bild.save(ziel, quality=90)
    print(f"{len(kaesten)} Kaesten ueber {b}x{h} -> {ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
