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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent

# Wo die Seite ausgeliefert wird. Eine Zeile, damit og:image und canonical nicht
# auseinanderlaufen — eine Vorschau, die ins Leere zeigt, ist schlimmer als keine.
BASIS = "https://jenslaufer.com/malaysia/"
HARNESS_SEITE = "https://jenslaufer.com/harry/"
LINKEDIN = "https://www.linkedin.com/in/jenslaufer"
QUELLE = Path.home() / "repos" / "assistant" / "state" / "reise-erfahrungen-malaysia-2026.md"
KOPIE = WURZEL / "content" / "erfahrungen.md"
ZIEL = WURZEL / "index.html"

# Zwei Sprachen, zwei Quelldateien, EINE Messung (Jens 17.08. 07:59: "Dann
# deutsch und englisch"). Die englische Fassung ist die, die Jens nicht liest —
# ihr Rueckstand faellt also niemandem auf. Dagegen hilft kein Vorsatz, sondern
# `pruefe_deckung()`: der Build zaehlt beide Dateien und meldet die Luecke.
SPRACHEN = ("de", "en")
QUELLEN = {"de": QUELLE, "en": QUELLE.with_name(QUELLE.stem + ".en.md")}
KOPIEN = {"de": KOPIE, "en": WURZEL / "content" / "erfahrungen.en.md"}
ZIELE = {"de": ZIEL, "en": WURZEL / "en" / "index.html"}

# Welche Fassung gerade gebaut wird. Ein Modul-Global wie WERKSTATT und
# GEHEIME_TOKEN daneben: der Rendercode reicht sonst durch ein Dutzend
# Funktionen einen Parameter, den nur drei davon lesen.
SPRACHE = "de"


def _t(de: str, en: str) -> str:
    """Der Satz in der Sprache, die gerade gebaut wird."""
    return en if SPRACHE == "en" else de

# Herkunftsspur: wie lange von Jens' Telegram-Nachricht bis zu diesem Eintrag.
# Gemessen wird sie nicht hier, sondern in tools/reise-werkstatt.py im
# Assistenz-Repo — aus der git-Historie von content/erfahrungen.md. Der Build
# holt nur das Ergebnis, damit dieses Repo fuer sich allein baut.
WERKSTATT_QUELLE = Path.home() / "repos" / "assistant" / "state" / "reise-werkstatt.json"
WERKSTATT_KOPIE = WURZEL / "content" / "werkstatt.json"

# anker -> {telegram, veroeffentlicht, minuten}. Wird in main() gefuellt.
WERKSTATT: dict[str, dict] = {}
WERKSTATT_SUMME: dict = {}

# ---------------------------------------------------------------------- Fotos
#
# Die Bilder kommen ueber Telegram und liegen im PRIVATEN Assistenz-Repo. Von
# dort werden sie nie kopiert, sondern neu geschrieben — der Unterschied ist der
# ganze Punkt: `pruefe_privat` liest Text, und die Standortdaten eines Fotos
# stehen in keinem Satz. Ein Bild mit GPS-Koordinaten laeuft an jeder
# Textpruefung vorbei, ist auf der gerenderten Seite unsichtbar und sagt
# Fremden, vor welchem Haus die Familie gerade steht. Telegram wirft das EXIF
# beim Komprimieren zwar selbst weg (am 17.08. an allen zwoelf Bildern
# gemessen) — aber das ist Telegrams Eigenschaft, nicht unsere: dasselbe Foto
# als *Datei* geschickt behaelt alles. Also schreibt der Build jedes Bild neu.
FOTO_QUELLE = Path.home() / "repos" / "assistant" / "state" / "attachments"
FOTO_ZIEL = WURZEL / "fotos"
FOTO_DATEN_DATEI = WURZEL / "content" / "fotos.json"
FOTO_MAX_BREITE = 1280  # was Telegram liefert; hochrechnen kostet Bytes ohne Bildpunkte
FOTO_QUALITAET = 82

# dateiname -> {"name": slug, "blur": [[x, y, b, h], ...]}. Die Kaesten sind
# RELATIV (0..1), damit sie das Verkleinern ueberleben; absolute Pixel zeigen
# nach dem Skalieren woanders hin, und zwar lautlos.
#
# Von Hand gepflegt, und das ist Absicht: ein Erkenner, der ein Kennzeichen von
# vier findet, liest sich wie Schutz und ist keiner. Eine Liste, die ich gegen
# das gerenderte Bild pruefen kann, ist ehrlicher.
FOTO_DATEN: dict[str, dict] = {}

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

ZEICHEN_EN = {
    "✓": ("erlebt", "we did it ourselves"),
    "○": ("recherche", "looked up, not checked ourselves"),
    "✗": ("gescheitert", "did not work"),
}

UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


MARKER = re.compile(r"^[ \t]*<!--\s*werkstatt:.*?-->[ \t]*\n?", flags=re.M)
# Derselbe Marker, aber mit der Uhrzeit als Gruppe. Er wird vor dem Entfernen
# aller Kommentare in ein Token umgeschrieben, damit die Herkunft den Weg durch
# den Renderer ueberlebt: die englische Fassung hat einen anderen Text und
# damit einen anderen Anker — ueber den Anker gefunden wuerde sie nichts
# finden, und zwar still.
MARKER_ZEIT = re.compile(r"[ \t]*<!--\s*werkstatt:\s*telegram=([0-9TZ:+\-]+)\s*-->[ \t]*")
TOKEN = re.compile(r"@@WERKSTATT:([0-9TZ:+\-]+)@@")
ANKER_LAENGE = 60


def _tg_schluessel(iso: str) -> str:
    """Ein Zeitstempel, zwei Schreibweisen — daraus einen Schluessel.

    Im Dokument steht `2026-08-17T04:41`, in der Messung
    `2026-08-17T04:41:00+00:00`. Ohne Normalisierung findet die englische Seite
    ihre eigene Messung nicht und laesst die Herkunftszeile weg.
    """
    zeit = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.isoformat()


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
    """Escapen, dann `code`, **fett**, *kursiv*. Die Reihenfolge ist die Sache.

    Fett besteht aus zwei Sternchen: wird kursiv zuerst aufgeloest, frisst es
    die Haelfte jedes fetten Absatzanfangs — und jeder Eintrag dieser Seite
    faengt mit einem an. Kursiv verlangt darum ein Zeichen, das kein Sternchen
    und kein Leerraum ist, direkt hinter dem oeffnenden Stern; sonst wird aus
    "3 * 4 Ringgit" eine Auszeichnung.
    """
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\*([^\s*][^*]*?)\*", r"<em>\1</em>", t)
    return t


def _eintrag(block: str, telegram: str = None) -> str | None:
    """Absatz mit Zeichen → eigener Eintrag mit Zeichen in der Randspalte."""
    treffer = re.match(r"^\*\*([✓○✗])\s+(.*)$", block, flags=re.S)
    if treffer:
        zeichen = treffer.group(1)
        klasse, label = (ZEICHEN_EN if SPRACHE == "en" else ZEICHEN)[zeichen]
        rest = "**" + treffer.group(2)
        glyph = html.escape(zeichen)
    elif block.startswith(("**Offen, kommt noch:**", "**Open, still to come:**")):
        zeichen, klasse = "…", "offen"
        label = _t("noch offen", "still open")
        rest, glyph = block, "…"
    else:
        return None
    return (
        f'<div class="entry entry--{klasse}">'
        f'<span class="mark" aria-hidden="true">{glyph}</span>'
        f'<span class="mark-label">{label}</span>'
        f"<p>{inline(rest)}</p>"
        f"{_spur(block, telegram)}"
        f"</div>"
    )


def _uhr(iso: str) -> str:
    z = datetime.fromisoformat(iso)
    return z.strftime("%d %b, %H:%M") if SPRACHE == "en" else z.strftime("%d.%m. %H:%M")


def _spur(block: str, telegram: str = None) -> str:
    """Herkunftszeile unter einem Eintrag: Nachricht → veroeffentlicht → Dauer.

    Das ist die eigentliche Verbindung zwischen dieser Seite und /harry/. Ein
    Reisebericht mit einem Link auf eine Seite ueber Agenten behauptet etwas;
    ein Eintrag, der seine eigene Entstehungszeit mitfuehrt, belegt es.

    Ohne Messung wird gar nichts gerendert — eine leere oder auf 0 gesetzte
    Dauer waere die schnellste Zahl der Seite und hiesse "nicht gemessen".
    """
    anker = block.splitlines()[0].strip()[:ANKER_LAENGE]
    daten = WERKSTATT.get(anker)
    if daten is None and telegram:
        daten = WERKSTATT.get(_tg_schluessel(telegram))
    if not daten or daten.get("minuten") is None:
        return ""
    return (
        '<p class="spur">'
        f'<span class="spur-von">Telegram {html.escape(_uhr(daten["telegram"]))}</span>'
        f'<span class="spur-pfeil" aria-hidden="true">→</span>'
        f'<span class="spur-bis">{_t("auf dieser Seite", "live on this page")} '
        f'{html.escape(_uhr(daten["veroeffentlicht"]))}</span>'
        f'<span class="spur-dauer">{daten["minuten"]} {_t("Min", "min")}</span>'
        "</p>"
    )


FOTO = re.compile(r"^!\[(?P<text>[^\]]*)\]\(foto:(?P<datei>[^)\s]+)\)$")


def lade_foto_daten(pfad: Path = None) -> dict:
    """Liest content/fotos.json. Fehlt sie, gibt es keine Sperrkaesten."""
    pfad = Path(pfad) if pfad else FOTO_DATEN_DATEI
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def verarbeite_foto(datei: str) -> Path | None:
    """Ein Telegram-Bild → ein veroeffentlichungsfaehiges JPEG. Oder None.

    Drei Dinge passieren hier, und jedes hat einen Grund:

    1. **Neu geschrieben, nie kopiert.** Damit faellt jeder Metadatenblock weg —
       GPS, Geraet, Aufnahmezeit. Ein `shutil.copyfile` haette sie mitgenommen.
    2. **Gesperrte Stellen weichgezeichnet**, bevor irgendetwas skaliert wird.
       Auf der Strasse stehen Autos Fremder mit lesbaren Kennzeichen; die haben
       auf einer Seite, die Jens beruflich verlinkt, nichts zu suchen.
    3. **Auf FOTO_MAX_BREITE begrenzt, nie hochgerechnet.**

    Fehlt die Quelle, kommt None zurueck und der Aufrufer laesst das Bild weg —
    aber laut. Ein kaputtes `<img>` ist auf einer oeffentlichen Seite sichtbarer
    Schaden, ein fehlender Absatz nicht.
    """
    from PIL import Image, ImageFilter

    quelle = FOTO_QUELLE / datei
    daten = FOTO_DATEN.get(datei, {})
    name = daten.get("name") or Path(datei).stem
    ziel = FOTO_ZIEL / f"{name}.jpg"

    if not quelle.exists():
        if ziel.exists():
            return ziel  # schon veroeffentlicht; das Repo baut auch ohne Assistenz-Repo
        print(f"ACHTUNG: Foto fehlt, Bild faellt weg: {datei}", file=sys.stderr)
        return None

    with Image.open(quelle) as bild:
        bild = bild.convert("RGB")
        breite, hoehe = bild.size
        for x, y, b, h in daten.get("blur", []):
            kasten = (int(x * breite), int(y * hoehe),
                      int((x + b) * breite), int((y + h) * hoehe))
            ausschnitt = bild.crop(kasten)
            radius = max(6, int(min(kasten[2] - kasten[0], kasten[3] - kasten[1]) / 2.5))
            bild.paste(ausschnitt.filter(ImageFilter.GaussianBlur(radius)), kasten)
        if breite > FOTO_MAX_BREITE:
            bild = bild.resize(
                (FOTO_MAX_BREITE, round(hoehe * FOTO_MAX_BREITE / breite)),
                Image.LANCZOS,
            )
        FOTO_ZIEL.mkdir(parents=True, exist_ok=True)
        # Ohne exif=/icc_profile= schreibt Pillow vorhandene Bloecke wieder mit.
        bild.save(ziel, "JPEG", quality=FOTO_QUALITAET, optimize=True,
                  progressive=True, exif=b"", icc_profile=None)
    return ziel


def _figure(text: str, datei: str) -> str | None:
    from PIL import Image

    ziel = verarbeite_foto(datei)
    if ziel is None:
        return None
    with Image.open(ziel) as bild:
        breite, hoehe = bild.size
    # In der Gruppe wird jedes Bild auf ein festes Seitenverhaeltnis
    # geschnitten. Bei einem hochkanten Foto liegt der Inhalt dann oft oben —
    # beim Geldautomaten die laufende Abfrage auf dem Schirm. Mittig
    # zugeschnitten war das Bild noch da und seine Aussage weg.
    position = FOTO_DATEN.get(datei, {}).get("position")
    stil = f' style="--pos: {html.escape(position, quote=True)}"' if position else ""
    return (
        f'<figure class="foto"{stil}>'
        f'<img src="fotos/{html.escape(ziel.name)}" width="{breite}" height="{hoehe}" '
        f'alt="{html.escape(text, quote=True)}" loading="lazy" decoding="async">'
        f"<figcaption>{inline(text)}</figcaption>"
        "</figure>"
    )


def _fotos(block: str) -> str | None:
    """Ein Absatz aus lauter Bildzeilen → ein Bild oder eine Gruppe."""
    zeilen = [z.strip() for z in block.splitlines() if z.strip()]
    treffer = [FOTO.match(z) for z in zeilen]
    if not zeilen or not all(treffer):
        return None
    stuecke = [_figure(t.group("text"), t.group("datei")) for t in treffer]
    stuecke = [s for s in stuecke if s]
    if not stuecke:
        return ""
    if len(stuecke) == 1:
        return stuecke[0]
    return f'<div class="fotos fotos--{len(stuecke)}">' + "".join(stuecke) + "</div>"


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
    # Der Herkunftsmarker wird ZUERST in ein Token umgeschrieben und erst danach
    # werden alle Kommentare entfernt. Andersherum verschwindet mit dem
    # Pflegeblock am Dateiende auch die Uhrzeit, an der die englische Fassung
    # ihre Messung wiederfindet.
    md = MARKER_ZEIT.sub(r"@@WERKSTATT:\1@@", md)
    md = strip_kommentare(strip_marker(md))
    teile = []
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        zeit = TOKEN.search(block)
        telegram = zeit.group(1) if zeit else None
        block = TOKEN.sub("", block).strip()
        if not block or set(block) <= {"-"} and len(block) >= 3:
            continue
        bilder = _fotos(block)
        if bilder is not None:
            if bilder:
                teile.append(bilder)
        elif block.startswith("## "):
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
            teile.append(_eintrag(block, telegram) or f"<p>{inline(block)}</p>")
    return "\n".join(teile)


def pruefe_deckung(deutsch: str, englisch: str) -> list[str]:
    """Was in der deutschen Fassung steht und in der englischen fehlt.

    Gezaehlt werden Abschnitte und Eintraege, nicht Woerter: ein Rueckstand
    zeigt sich als fehlender Eintrag, nicht als kuerzerer Satz. Der Build
    veroeffentlicht trotzdem — eine Seite, die zu 90 % uebersetzt ist, ist
    besser als keine, aber sie darf nicht still 90 % sein.
    """
    def zaehle(md: str) -> tuple[int, int, int]:
        ohne = strip_kommentare(strip_marker(md))
        abschnitte = len(re.findall(r"^## ", ohne, flags=re.M))
        eintraege = len(re.findall(r"^\*\*[✓○✗]", ohne, flags=re.M))
        fotos = len(re.findall(r"^!\[[^\]]*\]\(foto:", ohne, flags=re.M))
        return abschnitte, eintraege, fotos

    de_abschnitte, de_eintraege, de_fotos = zaehle(deutsch)
    en_abschnitte, en_eintraege, en_fotos = zaehle(englisch)
    luecken = []
    if en_abschnitte < de_abschnitte:
        luecken.append(f"{de_abschnitte - en_abschnitte} Abschnitt(e) fehlen "
                       f"({en_abschnitte} von {de_abschnitte})")
    if en_eintraege < de_eintraege:
        luecken.append(f"{de_eintraege - en_eintraege} Eintrag/Eintraege fehlen "
                       f"({en_eintraege} von {de_eintraege})")
    # Ein Bild ohne englische Unterschrift faellt aus der englischen Fassung,
    # ohne eine Luecke zu hinterlassen, die jemand sieht.
    if en_fotos < de_fotos:
        luecken.append(f"{de_fotos - en_fotos} Foto(s) fehlen "
                       f"({en_fotos} von {de_fotos})")
    return luecken


# ---------------------------------------------------------------------- Seite

STATIONEN = [
    ("Singapur", 1.3521, 103.8198, "15.–17.08. · 05.–07.09.",
     "15–17 Aug · 5–7 Sep"),
    ("Johor Bahru", 1.4655, 103.7578, "17.08. · Grenze und Larkin Sentral",
     "17 Aug · border and Larkin Sentral"),
    ("Mersing", 2.4312, 103.8405, "17.–18.08. · Fährhafen nach Tioman",
     "17–18 Aug · ferry port for Tioman"),
    ("Tioman", 2.8167, 104.1667, "18.–21.08.", "18–21 Aug"),
    ("Kuala Lumpur", 3.1390, 101.6869, "22.–24.08.", "22–24 Aug"),
    ("Sandakan", 5.8402, 118.1179, "25.–28.08. · Sabah", "25–28 Aug · Sabah"),
    ("Kota Kinabalu", 5.9804, 116.0735, "29.08.–03.09.", "29 Aug – 3 Sep"),
    ("Kudat", 6.8837, 116.8378, "04.–05.09. · Tip of Borneo",
     "4–5 Sep · Tip of Borneo"),
]


def _karte() -> str:
    stationen = [(name, lat, lon, _t(de, en)) for name, lat, lon, de, en in STATIONEN]
    punkte = ",\n      ".join(
        f'["{name}", {lat}, {lon}, "{note}"]' for name, lat, lon, note in stationen
    )
    liste = "".join(
        f"<li><b>{html.escape(name)}</b> <span>{html.escape(note)}</span></li>"
        for name, _, _, note in stationen
    )
    return f"""
<section class="karte-block" aria-labelledby="karte-titel">
  <h2 id="karte-titel">{_t("Die Route", "The route")}</h2>
  <p class="karte-intro">{_t(
     "Acht Stationen zwischen Singapur und dem Norden Borneos. "
     "Die Anreise über Frankfurt und Bahrain liegt außerhalb des Ausschnitts.",
     "Eight stops between Singapore and the north of Borneo. The journey out via "
     "Frankfurt and Bahrain lies outside the frame.")}</p>
  <div id="karte" role="img" aria-label="{_t(
       'Karte der Reiseroute von Singapur über die Halbinsel bis nach Sabah auf Borneo',
       'Map of the route from Singapore across the peninsula to Sabah on Borneo')}"></div>
  <noscript><p class="hinweis">{_t(
     "Die Karte braucht JavaScript. Die Stationen stehen als Liste darunter.",
     "The map needs JavaScript. The stops are listed below it.")}</p></noscript>
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
    if SPRACHE == "en":
        return f"""
<aside class="werkstatt" aria-labelledby="werkstatt-titel">
  <h2 id="werkstatt-titel">No human maintains this page</h2>
  <p>We are on the road, with a phone and no computer. What stands here is sent
     by Jens as a Telegram message; an assistant on a mini-PC in Germany writes
     it in, checks it for private data and rebuilds the page. Nobody sits in
     between — it is three in the morning in Germany when a bus leaves here.</p>
  <p class="werkstatt-zahlen">
    <span><b>{summe['gemessen']}</b> entries have come about this way</span>
    <span>most recently <b>{summe['juengste_minuten']} minutes</b> from message to here</span>
    <span>median <b>{summe['median_minuten']} minutes</b></span>
  </p>
  <p class="werkstatt-fuss">The time under each lived-through entry is measured,
     not estimated: from Jens's message to the commit that published the entry.
     <a href="https://jenslaufer.com/harry/en/">How this is built and what else runs
     on it →</a></p>
</aside>
"""
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


def _autor_block() -> str:
    """Wer die Seite schreibt — und der Beruf, aus dem sie entstanden ist.

    Zwei Leser, ein Block: wer die Reise liest, will wissen, wem er die Haken
    glaubt; wer wissen will, wie eine Seite ohne Rechner entsteht, findet hier
    den Weg zur Maschine. Preise stehen bewusst nicht hier — diese Seite geht an
    Freunde und an Leute, die den Weg zur Larkin-Busstation suchen, und ein
    Tagessatz zwischen Faehrzeiten entwertet den Rest der Seite.

    Er steht auch dann, wenn die Reisemessung fehlt: nach dem 07.09. faellt das
    Werkstatt-Band weg, die Auskunft, wer hier schreibt, bleibt noetig.
    """
    if SPRACHE == "en":
        return f"""
<section class="autor" aria-labelledby="autor-titel">
  <h2 id="autor-titel">Who writes this</h2>
  <p>There are four of us travelling — three weeks of Singapore, the peninsula and
     Borneo. None of us typed this page. Jens sends a Telegram message when
     something has worked; the rest is done by <a href="{HARNESS_SEITE}en/">Harry</a>,
     an assistant on a mini-PC in a basement in Karlstein am Main, Germany: look it
     up, place it, hold it against the notes so far, check it for private data,
     rebuild the page, publish.</p>
  <p>That is not a party trick on the side, it is the job. Jens Laufer works as a
     <b>Forward Deployed Engineer</b> — he takes models out of the demo and into
     the place where the real data, the real workflows and the real failures are —
     and half of that by now is <b>Harness Engineering</b>: not building the model,
     but building the scaffolding around it in which it works unattended. This trip
     is the stress test. For three weeks, whatever cannot be commissioned from a
     phone does not happen.</p>
  <p class="autor-hinweis"><b>One thing belongs here, because the page would otherwise
     claim more than it delivers.</b> Jens reads every version, and his most frequent
     objection is the language: it still sounds too much like AI to him. Too smooth,
     too many invented words, sentences that read like text rather than like somebody
     telling you something. He is strict about it — stricter than about anything else
     on this page. It says so here because a page meant to show what a setup like this
     can do should also say where it is not good yet.</p>
  <p class="autor-links">
    <a href="{HARNESS_SEITE}en/">How the setup works, with all the numbers →</a>
    <a href="{LINKEDIN}">Jens on LinkedIn</a>
  </p>
</section>
"""
    return f"""
<section class="autor" aria-labelledby="autor-titel">
  <h2 id="autor-titel">Wer das hier schreibt</h2>
  <p>Wir sind zu viert unterwegs — drei Wochen Singapur, Halbinsel, Borneo. Getippt
     hat diese Seite niemand von uns. Jens schickt unterwegs eine Telegram-Nachricht,
     wenn etwas funktioniert hat; den Rest macht <a href="{HARNESS_SEITE}">Harry</a>,
     ein Assistent auf einem Mini-PC in einem Keller in Karlstein am Main: nachsehen,
     einordnen, gegen die bisherigen Notizen halten, auf private Daten prüfen, die
     Seite neu bauen, veröffentlichen.</p>
  <p>Das ist kein Kunststück nebenbei, sondern der Beruf. Jens Laufer arbeitet als
     <b>Forward Deployed Engineer</b> — er bringt Modelle aus der Demo dorthin, wo
     echte Daten, echte Abläufe und echte Ausfälle sind — und die Hälfte davon ist
     inzwischen <b>Harness Engineering</b>: nicht das Modell bauen, sondern den
     Aufbau darum, in dem es unbeaufsichtigt arbeitet. Diese Reise ist der Härtetest.
     Was sich nicht von einem Telefon aus beauftragen lässt, findet drei Wochen lang
     nicht statt.</p>
  <p class="autor-hinweis"><b>Eine Anmerkung gehört hierher, sonst verspricht die Seite
     mehr, als sie hält.</b> Jens liest jede Fassung gegen, und sein häufigster Einwand
     ist die Sprache: sie klingt ihm immer noch zu sehr nach KI. Zu glatt, zu viele
     selbst gebaute Wörter, Sätze, die wie Text klingen und nicht wie jemand, der einem
     etwas erzählt. Er ist da streng — strenger als bei allem anderen auf dieser Seite.
     Das steht hier, weil eine Seite, die zeigen soll, was so ein Aufbau kann, auch
     sagen muss, wo er noch nicht gut ist.</p>
  <p class="autor-links">
    <a href="{HARNESS_SEITE}">Wie der Aufbau funktioniert, mit allen Zahlen →</a>
    <a href="{LINKEDIN}">Jens auf LinkedIn</a>
  </p>
</section>
"""


def _og_karte(summe: dict) -> str:
    """Die Vorschaukarte als HTML. Ohne Messung ohne Zahl — nie mit einer Null."""
    karte = (WURZEL / "template" / "og.html").read_text(encoding="utf-8")
    if summe.get("gemessen") and summe.get("juengste_minuten") is not None:
        fuss = _t(
            f"{summe['gemessen']} Meldungen von unterwegs &middot; zuletzt "
            f"<em>{summe['juengste_minuten']} Minuten</em> von der Nachricht bis online",
            f"{summe['gemessen']} entries sent from the road &middot; most recently "
            f"<em>{summe['juengste_minuten']} minutes</em> from message to live",
        )
    else:
        fuss = _t("Geschrieben unterwegs, gebaut in Deutschland",
                  "Written on the road, built in Germany")
    if SPRACHE == "en":
        karte = (karte.replace("Singapur und Malaysia", "Singapore and Malaysia")
                      .replace("was wirklich funktioniert hat", "what actually worked")
                      .replace('lang="de"', 'lang="en"'))
    return karte.replace("{{FUSS}}", fuss)


def baue_og_bild(summe: dict, ziel: Path = None) -> Path | None:
    """Rendert die Vorschaukarte (1200x630) mit Chromium.

    Ohne Bild ist der geteilte Link in Telegram, WhatsApp und LinkedIn eine graue
    Zeile — und geteilt wird diese Seite, dafuer ist sie da.
    """
    ziel = ziel or (WURZEL / ("og.png" if SPRACHE == "de" else "en/og.png"))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    karte = _og_karte(summe)
    pruefe_privat(karte)

    # Snap-Chromium darf weder nach /tmp noch in versteckte Ordner schreiben.
    arbeit = Path.home() / "pdf-slim-work" / "malaysia" / SPRACHE
    arbeit.mkdir(parents=True, exist_ok=True)
    quelle = arbeit / "og-karte.html"
    quelle.write_text(karte, encoding="utf-8")

    for programm in ("chromium", "chromium-browser", "google-chrome"):
        try:
            lauf = subprocess.run(
                [programm, "--headless", "--disable-gpu", "--hide-scrollbars",
                 "--window-size=1200,630", "--virtual-time-budget=8000",
                 f"--screenshot={arbeit / 'og.png'}", f"file://{quelle}"],
                capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if lauf.returncode == 0 and (arbeit / "og.png").exists():
            ziel.write_bytes((arbeit / "og.png").read_bytes())
            return ziel
    return None


def _inhaltsverzeichnis(rumpf: str) -> str:
    eintraege = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', rumpf, flags=re.S)
    if not eintraege:
        return ""
    links = "".join(
        f'<a href="#{ident}">{re.sub(r"<[^>]+>", "", titel)}</a>'
        for ident, titel in eintraege
    )
    return f'<nav class="toc" aria-label="{_t("Abschnitte", "Sections")}">{links}</nav>'


def baue_seite(md: str) -> str:
    pruefe_privat(strip_kommentare(md))
    rumpf = render_markdown(md)

    # Kopf ist alles bis zur ersten Ueberschrift zweiter Ordnung.
    schnitt = rumpf.find("<h2")
    kopf, rest = (rumpf[:schnitt], rumpf[schnitt:]) if schnitt > 0 else (rumpf, "")
    rest = _werkstatt_band(WERKSTATT_SUMME) + _karte() + rest + _autor_block()

    vorlage = (WURZEL / "template" / _t("page.html", "page.en.html")).read_text(encoding="utf-8")
    css = (WURZEL / "template" / "site.css").read_text(encoding="utf-8")
    heute = datetime.now(timezone.utc)
    stand = heute.strftime("%d %B %Y") if SPRACHE == "en" else heute.strftime("%d.%m.%Y")
    seite = (
        vorlage.replace("{{CSS}}", css)
        .replace("{{KOPF}}", kopf)
        .replace("{{INHALT}}", rest)
        .replace("{{TOC}}", _inhaltsverzeichnis(rumpf))
        .replace("{{STAND}}", stand)
        .replace("{{BASIS}}", BASIS)
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
    # Zwei Schluessel je Eintrag: der Textanker fuer die deutsche Fassung, die
    # Uhrzeit der Telegram-Nachricht fuer jede andere. Ein uebersetzter Absatz
    # hat einen anderen Anker und faende sonst seine eigene Messung nicht.
    spuren = {}
    for e in daten.get("eintraege", []):
        if e.get("anker"):
            spuren[e["anker"]] = e
        if e.get("telegram"):
            spuren[_tg_schluessel(e["telegram"])] = e
    summe = {k: daten.get(k) for k in
             ("gemessen", "markiert", "median_minuten", "juengste_minuten")}
    return spuren, summe


def main() -> int:
    global GEHEIME_TOKEN, WERKSTATT, WERKSTATT_SUMME, SPRACHE, FOTO_DATEN
    GEHEIME_TOKEN = lade_sperrliste()
    FOTO_DATEN = lade_foto_daten()

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-sync", action="store_true", help="Quelle nicht neu holen")
    p.add_argument("--check", action="store_true", help="nur Datenschutz pruefen")
    p.add_argument("--og", action="store_true",
                   help="auch die Vorschaukarte og.png neu rendern (braucht Chromium)")
    args = p.parse_args()

    for sprache in SPRACHEN:
        quelle, kopie = QUELLEN[sprache], KOPIEN[sprache]
        if not args.no_sync and quelle.exists():
            kopie.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(quelle, kopie)
            print(f"Quelle geholt ({sprache}): {quelle}")
        elif not kopie.exists():
            print(f"FEHLER: weder {quelle} noch {kopie} vorhanden", file=sys.stderr)
            return 2
    if not args.no_sync and WERKSTATT_QUELLE.exists():
        shutil.copyfile(WERKSTATT_QUELLE, WERKSTATT_KOPIE)

    WERKSTATT, WERKSTATT_SUMME = lade_werkstatt()
    if WERKSTATT_SUMME.get("gemessen"):
        print(
            f"Herkunft: {WERKSTATT_SUMME['gemessen']} Meldungen gemessen, "
            f"Median {WERKSTATT_SUMME['median_minuten']} min"
        )
    else:
        print("Herkunft: keine Messung (tools/reise-werkstatt.py laeuft im Assistenz-Repo)")

    quellen = {s: KOPIEN[s].read_text(encoding="utf-8") for s in SPRACHEN}

    # Die englische Fassung altert unbemerkt, weil Jens sie nicht liest. Also
    # zaehlt der Build sie gegen die deutsche und sagt es laut. Kein Abbruch:
    # eine Seite, der ein Eintrag fehlt, ist besser als keine — sie darf nur
    # nicht still unvollstaendig sein.
    luecken = pruefe_deckung(quellen["de"], quellen["en"])
    if luecken:
        print("ACHTUNG: die englische Fassung haengt zurueck — " + "; ".join(luecken)
              + f". Nachtragen in {QUELLEN['en']}", file=sys.stderr)

    seiten = {}
    for sprache in SPRACHEN:
        SPRACHE = sprache
        try:
            seiten[sprache] = baue_seite(quellen[sprache])
        except PrivatException as e:
            print(f"ABBRUCH ({sprache}) — {e}", file=sys.stderr)
            print("Nichts geschrieben. Den Satz im Quelldokument entfernen.", file=sys.stderr)
            return 1
        namen = warne_namen(seiten[sprache])
        if namen:
            print(
                f"ACHTUNG ({sprache}): Namen aus der Warnliste stehen auf der "
                "oeffentlichen Seite: " + ", ".join(namen)
                + ". Kein Abbruch — wer hier vorkommt, entscheidet Jens.",
                file=sys.stderr,
            )

    if args.check:
        print("Datenschutz (de + en): keine harte Sperre getroffen. "
              "(--check schreibt nichts)")
        return 1 if luecken else 0

    for sprache in SPRACHEN:
        ziel = ZIELE[sprache]
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(seiten[sprache], encoding="utf-8")
        # ziel.stat(), nicht len(): len() zaehlt Zeichen. Auf einer deutschen
        # Seite voller Umlaute, Pfeile und Haken liegen zwischen beiden ueber
        # 500 Bytes — und eine Groessenangabe, die man gegen die ausgelieferte
        # Datei haelt, muss dieselbe Einheit haben wie die Datei.
        print(f"gebaut: {ziel} ({ziel.stat().st_size:,} Bytes)")

    if args.og:
        for sprache in SPRACHEN:
            SPRACHE = sprache
            bild = baue_og_bild(WERKSTATT_SUMME)
            if bild:
                print(f"{bild.relative_to(WURZEL)}: {bild.stat().st_size:,} B")
            else:
                print(f"og.png ({sprache}) NICHT gebaut (kein Chromium?) — "
                      "Vorschau bleibt alt.", file=sys.stderr)
    SPRACHE = "de"
    return 1 if luecken else 0


if __name__ == "__main__":
    sys.exit(main())
