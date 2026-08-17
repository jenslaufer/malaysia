#!/usr/bin/env python3
"""Baut malaysia.jenslaufer.com aus dem Erfahrungs-Dokument.

Quelle ist `~/repos/assistant/state/reise-erfahrungen-malaysia-2026.md` — dort
traegt die Sitzung ein, was Jens aus dem Urlaub meldet. Der Build holt sich eine
Kopie nach `content/erfahrungen.md` (damit das Repo fuer sich allein baut) und
rendert daraus `index.html`.

Warum ein eigener Renderer statt einer Markdown-Bibliothek: das Zeichen vor
jedem Eintrag (✓ selbst erlebt / ○ nachgeschlagen / ✗ hat nicht funktioniert)
ist der Kern des Dokuments. Eine allgemeine Bibliothek macht daraus fettes
Fliesstext-Zeichen; hier wird es zu eigener Auszeichnung mit eigener Farbe.

Aufruf:
    python3 build.py                 # holt die Quelle, baut index.html
    python3 build.py --no-sync       # baut aus content/erfahrungen.md
    python3 build.py --check         # baut nichts, prueft nur den Datenschutz

Tests: python3 tests/test_build.py
"""

import argparse
import html
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
QUELLE = Path.home() / "repos" / "assistant" / "state" / "reise-erfahrungen-malaysia-2026.md"
KOPIE = WURZEL / "content" / "erfahrungen.md"
ZIEL = WURZEL / "index.html"

# ---------------------------------------------------------------- Datenschutz

class PrivatException(Exception):
    """Etwas Privates haette die Seite erreicht. Es wird nichts geschrieben."""


# Muster, die niemals oeffentlich werden duerfen. Lieber ein Fehlalarm als eine
# Passnummer im Netz — ein Fehlalarm kostet eine Minute, der andere Fall ist
# nicht ruecknehmbar.
MUSTER = [
    (r"\b[CFGHJK][0-9A-Z]{8}\b", "Passnummer (deutsches Format)"),
    (r"\b[A-Z]{1,2}\d{7,9}\b", "Ausweis- oder Vorgangsnummer"),
    (r"\b[A-Z]{2}\d{2}[ ]?(?:[0-9A-Z]{4}[ ]?){3,}[0-9A-Z]{1,4}\b", "IBAN"),
    (r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}", "E-Mail-Adresse"),
    (r"\+\d[\d /()-]{7,}\d", "Telefonnummer"),
]

# Woertliche Zeichenketten, die kein Muster fangen kann: Buchungscodes, PINs,
# Zugangsdaten. Hier eintragen, sobald eine neue dazukommt.
GEHEIME_TOKEN = [
    "yV7P7RyK",          # MDAC-PIN
]


def pruefe_privat(text: str) -> None:
    """Wirft PrivatException, wenn etwas Personenbezogenes im Text steht."""
    for token in GEHEIME_TOKEN:
        if token in text:
            raise PrivatException(f"privates Token im Text: {token}")
    for muster, name in MUSTER:
        treffer = re.search(muster, text)
        if treffer:
            raise PrivatException(f"{name} im Text: {treffer.group(0)}")


# ------------------------------------------------------------------- Renderer

ZEICHEN = {
    "✓": ("erlebt", "selbst erlebt"),
    "○": ("recherche", "nachgeschlagen, nicht selbst geprüft"),
    "✗": ("gescheitert", "hat nicht funktioniert"),
}

UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def strip_kommentare(md: str) -> str:
    """Entfernt HTML-Kommentare. Der Pflegeblock ist interne Anweisung."""
    return re.sub(r"<!--.*?-->", "", md, flags=re.S)


def slug(text: str) -> str:
    s = text.lower().translate(UMLAUTE)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def inline(text: str) -> str:
    """Escapen, dann **fett** und `code` aufloesen. Reihenfolge ist wichtig."""
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    return t


def _eintrag(block: str) -> str | None:
    """Absatz mit Zeichen → eigener Eintrag mit Zeichen in der Randspalte."""
    treffer = re.match(r"^\*\*([✓○✗])\s+(.*)$", block, flags=re.S)
    if treffer:
        zeichen = treffer.group(1)
        klasse, label = ZEICHEN[zeichen]
        rest = "**" + treffer.group(2)
        glyph = html.escape(zeichen)
    elif block.startswith("**Offen, kommt noch:**"):
        zeichen, klasse, label = "…", "offen", "noch offen"
        rest, glyph = block, "…"
    else:
        return None
    return (
        f'<div class="entry entry--{klasse}">'
        f'<span class="mark" aria-hidden="true">{glyph}</span>'
        f'<span class="mark-label">{label}</span>'
        f"<p>{inline(rest)}</p>"
        f"</div>"
    )


def _tabelle(block: str) -> str:
    zeilen = [z.strip() for z in block.splitlines() if z.strip()]
    zellen = [[c.strip() for c in z.strip("|").split("|")] for z in zeilen]
    kopf, koerper = zellen[0], zellen[2:]  # Zeile 1 ist der ---|---Trenner
    kopf_html = "".join(f"<th>{inline(c)}</th>" for c in kopf)
    koerper_html = "".join(
        "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in zeile) + "</tr>"
        for zeile in koerper
    )
    return (
        f'<div class="table-wrap"><table><thead><tr>{kopf_html}</tr></thead>'
        f"<tbody>{koerper_html}</tbody></table></div>"
    )


def render_markdown(md: str) -> str:
    """Markdown → HTML-Rumpf. Kennt genau die Formen, die im Dokument vorkommen."""
    md = strip_kommentare(md)
    teile = []
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        if not block or set(block) <= {"-"} and len(block) >= 3:
            continue
        if block.startswith("## "):
            titel = block[3:].strip()
            teile.append(f'<h2 id="{slug(titel)}">{inline(titel)}</h2>')
        elif block.startswith("# "):
            titel = block[2:].strip()
            teile.append(f"<h1>{inline(titel)}</h1>")
        elif block.startswith("|"):
            teile.append(_tabelle(block))
        elif block.startswith("- "):
            punkte = re.split(r"\n(?=- )", block)
            li = "".join(f"<li>{inline(p[2:].strip())}</li>" for p in punkte)
            teile.append(f'<ul class="legende">{li}</ul>')
        else:
            teile.append(_eintrag(block) or f"<p>{inline(block)}</p>")
    return "\n".join(teile)


# ---------------------------------------------------------------------- Seite

STATIONEN = [
    ("Singapur", 1.3521, 103.8198, "15.–17.08. · 05.–07.09."),
    ("Johor Bahru", 1.4655, 103.7578, "17.08. · Grenze und Larkin Sentral"),
    ("Mersing", 2.4312, 103.8405, "17.–18.08. · Fährhafen nach Tioman"),
    ("Tioman", 2.8167, 104.1667, "18.–21.08."),
    ("Kuala Lumpur", 3.1390, 101.6869, "22.–24.08."),
    ("Sandakan", 5.8402, 118.1179, "25.–28.08. · Sabah"),
    ("Kota Kinabalu", 5.9804, 116.0735, "29.08.–03.09."),
    ("Kudat", 6.8837, 116.8378, "04.–05.09. · Tip of Borneo"),
]


def _karte() -> str:
    punkte = ",\n      ".join(
        f'["{name}", {lat}, {lon}, "{note}"]' for name, lat, lon, note in STATIONEN
    )
    liste = "".join(
        f"<li><b>{html.escape(name)}</b> <span>{html.escape(note)}</span></li>"
        for name, _, _, note in STATIONEN
    )
    return f"""
<section class="karte-block" aria-labelledby="karte-titel">
  <h2 id="karte-titel">Die Route</h2>
  <p class="karte-intro">Acht Stationen zwischen Singapur und dem Norden Borneos.
     Die Anreise über Frankfurt und Bahrain liegt außerhalb des Ausschnitts.</p>
  <div id="karte" role="img" aria-label="Karte der Reiseroute von Singapur über
       die Halbinsel bis nach Sabah auf Borneo"></div>
  <noscript><p class="hinweis">Die Karte braucht JavaScript. Die Stationen stehen
     als Liste darunter.</p></noscript>
  <ol class="stationen">{liste}</ol>
</section>
<script>
  document.addEventListener("DOMContentLoaded", function () {{
    var el = document.getElementById("karte");
    if (!el || typeof L === "undefined") return;
    var orte = [
      {punkte}
    ];
    var karte = L.map("karte", {{ scrollWheelZoom: false }});
    L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 17,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }}).addTo(karte);
    var linie = [];
    orte.forEach(function (o, i) {{
      linie.push([o[1], o[2]]);
      L.circleMarker([o[1], o[2]], {{
        radius: 7, weight: 2, color: "#1c4f3f", fillColor: "#2f6b4f", fillOpacity: 1
      }}).addTo(karte).bindPopup("<b>" + (i + 1) + ". " + o[0] + "</b><br>" + o[3]);
    }});
    L.polyline(linie, {{ color: "#1c4f3f", weight: 2, opacity: .45, dashArray: "5 6" }}).addTo(karte);
    karte.fitBounds(L.latLngBounds(linie).pad(.12));
  }});
</script>
"""


def _inhaltsverzeichnis(rumpf: str) -> str:
    eintraege = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', rumpf, flags=re.S)
    if not eintraege:
        return ""
    links = "".join(
        f'<a href="#{ident}">{re.sub(r"<[^>]+>", "", titel)}</a>'
        for ident, titel in eintraege
    )
    return f'<nav class="toc" aria-label="Abschnitte">{links}</nav>'


def baue_seite(md: str) -> str:
    pruefe_privat(strip_kommentare(md))
    rumpf = render_markdown(md)

    # Kopf ist alles bis zur ersten Ueberschrift zweiter Ordnung.
    schnitt = rumpf.find("<h2")
    kopf, rest = (rumpf[:schnitt], rumpf[schnitt:]) if schnitt > 0 else (rumpf, "")
    rest = _karte() + rest

    vorlage = (WURZEL / "template" / "page.html").read_text(encoding="utf-8")
    css = (WURZEL / "template" / "site.css").read_text(encoding="utf-8")
    stand = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    seite = (
        vorlage.replace("{{CSS}}", css)
        .replace("{{KOPF}}", kopf)
        .replace("{{INHALT}}", rest)
        .replace("{{TOC}}", _inhaltsverzeichnis(rumpf))
        .replace("{{STAND}}", stand)
    )
    pruefe_privat(seite)
    return seite


# ----------------------------------------------------------------------- CLI

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-sync", action="store_true", help="Quelle nicht neu holen")
    p.add_argument("--check", action="store_true", help="nur Datenschutz pruefen")
    args = p.parse_args()

    if not args.no_sync and QUELLE.exists():
        KOPIE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(QUELLE, KOPIE)
        print(f"Quelle geholt: {QUELLE}")
    elif not KOPIE.exists():
        print(f"FEHLER: weder {QUELLE} noch {KOPIE} vorhanden", file=sys.stderr)
        return 2

    md = KOPIE.read_text(encoding="utf-8")
    try:
        seite = baue_seite(md)
    except PrivatException as e:
        print(f"ABBRUCH — {e}", file=sys.stderr)
        print("Nichts geschrieben. Den Satz im Quelldokument entfernen.", file=sys.stderr)
        return 1

    if args.check:
        print("Datenschutz: sauber. (--check schreibt nichts)")
        return 0

    ZIEL.write_text(seite, encoding="utf-8")
    print(f"gebaut: {ZIEL} ({len(seite):,} Bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
