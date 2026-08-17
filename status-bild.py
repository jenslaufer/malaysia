#!/usr/bin/env python3
"""Baut ein Bild fuers Teilen im WhatsApp-Status (1080x1920, 9:16).

Warum eigenes Format: die Vorschaukarte `og.png` ist 1200x630 und damit quer.
Im Status steht sie als Briefmarke in der Bildmitte, der Text darauf ist auf
einem Telefon nicht lesbar, und der einzige Zweck des Bildes — jemanden auf die
Seite holen — faellt weg. Ein Status ist hochkant und wird ohne Ton, ohne
Untertitel und in zwei Sekunden gelesen.

Deshalb traegt das Bild genau drei Dinge: ein Foto von der Reise, den Satz,
der die Seite von jedem anderen Reiseblog unterscheidet, und die Adresse.

Die Zahlen kommen aus `content/werkstatt.json` — derselben Messung, aus der die
Seite ihre Herkunftszeilen baut. Eine getippte Zahl auf einem Bild, das Fremde
sehen, waere genau der Fehler, den die Seite bei sich selbst ausschliesst.

Das Foto ist eine der **ausgelieferten** Dateien aus `fotos/` — dort sind die
Sperrkaesten schon drin. Das Original aus `state/attachments/` traegt sie nicht.

Aufruf:
    python3 status-bild.py                  # baut status.png
    python3 status-bild.py --foto <name>    # anderes Foto aus fotos/
"""

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

from PIL import Image

WURZEL = Path(__file__).resolve().parent
FOTOS = WURZEL / "fotos"
WERKSTATT = WURZEL / "content" / "werkstatt.json"
ZIEL = WURZEL / "status.jpg"
ADRESSE = "jenslaufer.com/malaysia"

# Nacht, viel dunkle Flaeche unten — Text steht darauf ohne Abdunkelung lesbar.
STANDARD_FOTO = "garden-rhapsody-supertrees-mbs.jpg"


def messe() -> tuple[int, int]:
    """(Anzahl Eintraege, Median-Minuten) aus der Messung der Seite."""
    daten = json.loads(WERKSTATT.read_text(encoding="utf-8"))
    minuten = [e["minuten"] for e in daten["eintraege"]]
    if not minuten:
        raise SystemExit("werkstatt.json enthaelt keine Messung — kein Bild gebaut.")
    return len(minuten), int(statistics.median(minuten))


def karte(foto: Path, anzahl: int, median: int) -> str:
    return f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="fonts.css">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ width: 1080px; height: 1920px; overflow: hidden;
          background: #17161a; color: #f7f4ef; font-family: Inter, sans-serif; }}
  .bild {{ position: absolute; inset: 0; }}
  .bild img {{ width: 100%; height: 100%; object-fit: cover; }}
  /* Der Verlauf ist kein Effekt, er ist die Lesbarkeit: ohne ihn steht weisse
     Schrift auf einem Foto, dessen Helligkeit niemand vorher kennt. */
  .schleier {{ position: absolute; inset: 0;
      background: linear-gradient(180deg, rgba(23,22,26,.72) 0%, rgba(23,22,26,.25) 30%,
                  rgba(23,22,26,.72) 62%, rgba(23,22,26,.96) 100%); }}
  .inhalt {{ position: absolute; inset: 0; padding: 110px 92px;
             display: flex; flex-direction: column; }}
  .kicker {{ font-size: 34px; font-weight: 600; letter-spacing: .22em;
             text-transform: uppercase; color: #e08a3c; }}
  .titel {{ margin-top: auto; font-family: Fraunces, Georgia, serif; font-weight: 600;
            font-size: 104px; line-height: 1.06; letter-spacing: -.02em; }}
  .unter {{ margin-top: 42px; font-size: 42px; line-height: 1.45; color: #ddd6cc;
            max-width: 22ch; }}
  .zahlen {{ margin-top: 64px; display: flex; gap: 76px; }}
  .zahl b {{ display: block; font-family: Fraunces, Georgia, serif;
             font-size: 82px; font-weight: 600; line-height: 1; }}
  .zahl span {{ display: block; margin-top: 14px; font-size: 30px; color: #b9b1a6;
                letter-spacing: .04em; }}
  .adresse {{ margin-top: 84px; padding-top: 40px; border-top: 2px solid rgba(247,244,239,.22);
              font-size: 46px; font-weight: 600; letter-spacing: -.01em; }}
</style></head><body>
<div class="bild"><img src="{foto.as_uri()}" alt=""></div>
<div class="schleier"></div>
<div class="inhalt">
  <div class="kicker">Familie unterwegs &middot; Reisebericht</div>
  <h1 class="titel">Singapur &amp; Malaysia&nbsp;2026</h1>
  <p class="unter">Fähren, Geldautomaten und zu viele Katzen in Mersing. Was wir
     selbst erlebt haben, steht mit Haken.</p>
  <div class="zahlen">
    <div class="zahl"><b>{anzahl}</b><span>Einträge</span></div>
    <div class="zahl"><b>{median} Min</b><span>von unterwegs bis online</span></div>
  </div>
  <div class="adresse">{ADRESSE}</div>
</div>
</body></html>"""


def main() -> int:
    z = argparse.ArgumentParser(description=__doc__)
    z.add_argument("--foto", default=STANDARD_FOTO, help="Datei aus fotos/")
    args = z.parse_args()

    foto = FOTOS / args.foto
    if not foto.exists():
        print(f"{foto} fehlt. Vorhanden: "
              f"{', '.join(sorted(p.name for p in FOTOS.glob('*.jpg') if '-' not in p.stem[-5:]))}",
              file=sys.stderr)
        return 2

    anzahl, median = messe()

    # Snap-Chromium darf weder nach /tmp noch in versteckte Ordner schreiben.
    arbeit = Path.home() / "pdf-slim-work" / "malaysia" / "status"
    arbeit.mkdir(parents=True, exist_ok=True)
    quelle = arbeit / "status.html"
    quelle.write_text(karte(foto, anzahl, median), encoding="utf-8")

    for programm in ("chromium", "chromium-browser", "google-chrome"):
        try:
            lauf = subprocess.run(
                [programm, "--headless", "--disable-gpu", "--hide-scrollbars",
                 "--window-size=1080,1920", "--virtual-time-budget=10000",
                 f"--screenshot={arbeit / 'status.png'}", f"file://{quelle}"],
                capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if lauf.returncode == 0 and (arbeit / "status.png").exists():
            # Als JPEG ablegen: das Repo haelt seine Bilder bewusst klein (alle
            # zehn Reisefotos zusammen 528 KB), ein 1,5-MB-PNG daneben waere die
            # Ausnahme ohne Grund. WhatsApp rechnet ohnehin selbst herunter.
            Image.open(arbeit / "status.png").convert("RGB").save(
                ZIEL, "JPEG", quality=88, optimize=True, progressive=True)
            print(f"gebaut: {ZIEL.name} ({ZIEL.stat().st_size:,} B, "
                  f"{anzahl} Eintraege, Median {median} Min)")
            return 0
    print("Kein Chromium gefunden — kein Bild gebaut.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
