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
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
QUELLE = Path.home() / "repos" / "assistant" / "state" / "reise-erfahrungen-malaysia-2026.md"
KOPIE = WURZEL / "content" / "erfahrungen.md"
ZIEL = WURZEL / "index.html"

# Herkunftsspur: wie lange von Jens' Telegram-Nachricht bis zu diesem Eintrag.
# Gemessen wird sie nicht hier, sondern in tools/reise-werkstatt.py im
# Assistenz-Repo — aus der git-Historie von content/erfahrungen.md. Der Build
# holt nur das Ergebnis, damit dieses Repo fuer sich allein baut.
WERKSTATT_QUELLE = Path.home() / "repos" / "assistant" / "state" / "reise-werkstatt.json"
WERKSTATT_KOPIE = WURZEL / "content" / "werkstatt.json"

# anker -> {telegram, veroeffentlicht, minuten}. Wird in main() gefuellt.
WERKSTATT: dict[str, dict] = {}
WERKSTATT_SUMME: dict = {}

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
# Namen, Betraege. Die Liste liegt bewusst NICHT hier, sondern im privaten
# Assistenz-Repo — dieses Repo ist public, und eine Sperrliste ist per
# Definition eine Liste genau der Woerter, die niemand sehen soll. Genau so
# stand die MDAC-PIN einen Tag lang in diesem Build (17.08. gefunden).
# Fehlt oder leer -> Abbruch; ein Schutz, der bei fehlender Datei
# stillschweigend durchlaesst, ist keiner.
SPERRLISTE = Path(
    os.environ.get(
        "HARRY_SPERRLISTE",
        Path.home() / "repos" / "assistant" / "state" / "oeffentlich-gesperrt.txt",
    )
)

# Warnliste: KEIN Abbruch, nur eine Meldung. Die Reise-Seite geht bewusst an
# Freunde, also entscheidet Jens, wer dort vorkommt — aber unbemerkt soll es
# nicht passieren.
WARNLISTE = Path(
    os.environ.get(
        "HARRY_WARNLISTE",
        Path.home() / "repos" / "assistant" / "state" / "oeffentlich-warnung.txt",
    )
)

GEHEIME_TOKEN: list[str] = []


def warne_namen(text: str) -> list[str]:
    """Nennt gefundene Namen aus der Warnliste, bricht aber nicht ab."""
    if not WARNLISTE.exists():
        return []
    klein = text.lower()
    return [w for w in lade_sperrliste(WARNLISTE) if w in klein]


def lade_sperrliste(pfad: Path = None) -> list[str]:
    """Liest die Sperrliste. Fehlt oder leer -> PrivatException."""
    pfad = Path(pfad) if pfad else SPERRLISTE
    try:
        roh = pfad.read_text(encoding="utf-8")
    except OSError as fehler:
        raise PrivatException(
            f"Sperrliste nicht lesbar ({pfad}): ohne sie prueft der Build nur "
            "Muster, keine Namen und keine Codes — das ist zu wenig."
        ) from fehler
    woerter = [
        z.strip().lower() for z in roh.splitlines()
        if z.strip() and not z.lstrip().startswith("#")
    ]
    if not woerter:
        raise PrivatException(f"Sperrliste ist leer ({pfad}).")
    return woerter


def pruefe_privat(text: str) -> None:
    """Wirft PrivatException, wenn etwas Personenbezogenes im Text steht."""
    klein = text.lower()
    for token in GEHEIME_TOKEN:
        if token in klein:
            raise PrivatException("gesperrtes Wort im Text (Liste ausserhalb des Repos)")
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


MARKER = re.compile(r"^[ \t]*<!--\s*werkstatt:.*?-->[ \t]*\n?", flags=re.M)
ANKER_LAENGE = 60


def strip_marker(md: str) -> str:
    """Entfernt die Herkunfts-Marker. Sie sind Daten, kein Text.

    Muss VOR strip_kommentare laufen und getrennt davon: der Pflegeblock am Fuss
    ist ein mehrzeiliger Kommentar, der Marker eine einzelne Zeile mitten in
    einem Absatz. Bliebe der Marker im Block stehen, faende ihn `_eintrag`
    im Fliesstext wieder — und die Uhrzeit stuende ungerahmt auf der Seite.
    """
    return MARKER.sub("", md)


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
        f"{_spur(block)}"
        f"</div>"
    )


def _uhr(iso: str) -> str:
    z = datetime.fromisoformat(iso)
    return z.strftime("%d.%m. %H:%M")


def _spur(block: str) -> str:
    """Herkunftszeile unter einem Eintrag: Nachricht → veroeffentlicht → Dauer.

    Das ist die eigentliche Verbindung zwischen dieser Seite und /harry/. Ein
    Reisebericht mit einem Link auf eine Seite ueber Agenten behauptet etwas;
    ein Eintrag, der seine eigene Entstehungszeit mitfuehrt, belegt es.

    Ohne Messung wird gar nichts gerendert — eine leere oder auf 0 gesetzte
    Dauer waere die schnellste Zahl der Seite und hiesse "nicht gemessen".
    """
    anker = block.splitlines()[0].strip()[:ANKER_LAENGE]
    daten = WERKSTATT.get(anker)
    if not daten or daten.get("minuten") is None:
        return ""
    return (
        '<p class="spur">'
        f'<span class="spur-von">Telegram {html.escape(_uhr(daten["telegram"]))}</span>'
        f'<span class="spur-pfeil" aria-hidden="true">→</span>'
        f'<span class="spur-bis">auf dieser Seite {html.escape(_uhr(daten["veroeffentlicht"]))}</span>'
        f'<span class="spur-dauer">{daten["minuten"]} Min</span>'
        "</p>"
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
    md = strip_kommentare(strip_marker(md))
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


def _werkstatt_band(summe: dict) -> str:
    """Erklaert dem Leser, wie diese Seite entsteht, und verlinkt die Maschine.

    Zwei Adressaten in einem Absatz: wer die Reise lesen will, erfaehrt, warum
    die Seite waehrend der Reise aktuell ist; wer Harness-Arbeit einkauft, sieht
    die Zahl, um die es dabei geht. Ohne Messung steht hier nichts — ein Band
    mit Nullen waere schlechter als keins.
    """
    if not summe.get("gemessen"):
        return ""
    return f"""
<aside class="werkstatt" aria-labelledby="werkstatt-titel">
  <h2 id="werkstatt-titel">Diese Seite pflegt kein Mensch</h2>
  <p>Wir sind unterwegs, mit Telefon und ohne Rechner. Was hier steht, schickt
     Jens als Telegram-Nachricht; ein Assistent auf einem Mini-PC in Deutschland
     trägt es ein, prüft es auf private Daten und baut die Seite neu. Niemand
     sitzt dazwischen — in Deutschland ist es drei Uhr nachts, wenn hier ein Bus
     fährt.</p>
  <p class="werkstatt-zahlen">
    <span><b>{summe['gemessen']}</b> Meldungen bisher so entstanden</span>
    <span>zuletzt <b>{summe['juengste_minuten']} Minuten</b> von der Nachricht bis hierher</span>
    <span>Median <b>{summe['median_minuten']} Minuten</b></span>
  </p>
  <p class="werkstatt-fuss">Die Zeit unter jedem selbst erlebten Eintrag ist
     gemessen, nicht geschätzt: von Jens' Nachricht bis zu dem Commit, der den
     Eintrag veröffentlicht hat. <a href="https://jenslaufer.com/harry/">Wie das
     gebaut ist und was sonst noch darauf läuft →</a></p>
</aside>
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
    rest = _werkstatt_band(WERKSTATT_SUMME) + _karte() + rest

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

def lade_werkstatt() -> tuple[dict, dict]:
    """Liest die Messung aus content/werkstatt.json. Fehlt sie, gibt es sie nicht.

    Kein Abbruch: die Herkunftsspur ist eine Zugabe, der Reisebericht steht auch
    ohne sie. Ein fehlender Wert darf aber nie zu einer 0 werden — deshalb leere
    Strukturen, die `_spur` und `_werkstatt_band` beide stumm schalten.
    """
    try:
        daten = json.loads(WERKSTATT_KOPIE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    spuren = {e["anker"]: e for e in daten.get("eintraege", []) if e.get("anker")}
    summe = {k: daten.get(k) for k in
             ("gemessen", "markiert", "median_minuten", "juengste_minuten")}
    return spuren, summe


def main() -> int:
    global GEHEIME_TOKEN, WERKSTATT, WERKSTATT_SUMME
    GEHEIME_TOKEN = lade_sperrliste()

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-sync", action="store_true", help="Quelle nicht neu holen")
    p.add_argument("--check", action="store_true", help="nur Datenschutz pruefen")
    args = p.parse_args()

    if not args.no_sync and QUELLE.exists():
        KOPIE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(QUELLE, KOPIE)
        print(f"Quelle geholt: {QUELLE}")
        if WERKSTATT_QUELLE.exists():
            shutil.copyfile(WERKSTATT_QUELLE, WERKSTATT_KOPIE)
    elif not KOPIE.exists():
        print(f"FEHLER: weder {QUELLE} noch {KOPIE} vorhanden", file=sys.stderr)
        return 2

    WERKSTATT, WERKSTATT_SUMME = lade_werkstatt()
    if WERKSTATT_SUMME.get("gemessen"):
        print(
            f"Herkunft: {WERKSTATT_SUMME['gemessen']} Meldungen gemessen, "
            f"Median {WERKSTATT_SUMME['median_minuten']} min"
        )
    else:
        print("Herkunft: keine Messung (tools/reise-werkstatt.py laeuft im Assistenz-Repo)")

    md = KOPIE.read_text(encoding="utf-8")
    try:
        seite = baue_seite(md)
    except PrivatException as e:
        print(f"ABBRUCH — {e}", file=sys.stderr)
        print("Nichts geschrieben. Den Satz im Quelldokument entfernen.", file=sys.stderr)
        return 1

    namen = warne_namen(seite)
    if namen:
        print(
            "ACHTUNG: Namen aus der Warnliste stehen auf der oeffentlichen Seite: "
            + ", ".join(namen)
            + ". Kein Abbruch — wer hier vorkommt, entscheidet Jens.",
            file=sys.stderr,
        )

    if args.check:
        print("Datenschutz: keine harte Sperre getroffen. (--check schreibt nichts)")
        return 0

    ZIEL.write_text(seite, encoding="utf-8")
    print(f"gebaut: {ZIEL} ({len(seite):,} Bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
