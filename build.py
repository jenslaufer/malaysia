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
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent

# Wo die Seite ausgeliefert wird. Eine Zeile, damit og:image und canonical nicht
# auseinanderlaufen — eine Vorschau, die ins Leere zeigt, ist schlimmer als keine.
BASIS = "https://jenslaufer.com/malaysia/"
HARNESS_SEITE = "https://jenslaufer.com/otto/"
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

KONTAKT = "jens.laufer@solytics.de"

RECHT_VORLAGE = WURZEL / "template" / "recht.html"
RECHTSARTEN = ("impressum", "datenschutz")
# EINE Tabelle, aus der Bauen, Verlinken und Pruefen lesen. Zwei Stellen waeren
# zwei Wahrheiten, und ein Impressumslink ins Leere ist schlimmer als keiner:
# er sieht aus wie ein erfuellter Paragraf.
RECHTSSEITEN = {
    ("impressum", "de"): "impressum.html",
    ("datenschutz", "de"): "datenschutz.html",
    ("impressum", "en"): "en/imprint.html",
    ("datenschutz", "en"): "en/privacy.html",
}

# Pflichtangaben nach § 5 DDG — dieselben wie auf der Angebotsseite, aus dem
# Handelsregister und den eigenen Belegen. Diese Seite ist kein reiner
# Familienblog: Jens' Wort vom 17.08. 06:59 ist "eine Art Marketingprojekt
# fuer meine Taetigkeit als HarnessEngineer/FDE", und sie verlinkt die
# Angebotsseite. Ein Impressum, das ein privater Blog nicht braucht, schadet
# nie; sein Fehlen auf einer geschaeftsnahen Seite ist abmahnbar.
IMPRESSUM = {
    "firma": "Solytics GmbH",
    "strasse": "Hörsteiner Str. 20a",
    "ort": "63791 Karlstein a. Main",
    "land": "Deutschland",
    "vertreten": "Jens Laufer",
    "registergericht": "Amtsgericht Aschaffenburg",
    "registernummer": "HRB 16879",
    "ustid": "DE357501843",
}

# Hosts, von denen diese Seite laden darf. Schriften und Leaflet liegen seit
# dem 17.08. hier im Repo; die Kartenkacheln bleiben fremd, weil man eine
# Weltkarte nicht mitliefert — deshalb laedt die Karte erst auf Klick.
# Was hier steht, muss in der Datenschutzerklaerung stehen; ein Test haelt
# beide zusammen.
EXTERN_ERLAUBT: tuple[str, ...] = ("tile.openstreetmap.org", "www.openstreetmap.org")

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

# Zwei Breiten, drei Formate. Der Grund ist gemessen, nicht Geschmack: in der
# Dreiergruppe ist ein Bild rund 200 px breit, in Satzbreite rund 640 — ein
# 1280er JPEG fuer den Gruppenplatz sind Faktor sechs an Bildpunkten, die
# niemand sieht. Am 17.08. wogen zwoelf Fotos so 1,75 MB.
# Reihenfolge im <picture> = Rangfolge: der Browser nimmt die erste Quelle,
# die er lesen kann, also muss die kleinste zuerst stehen.
FOTO_BREITEN = (640, 1280)
FOTO_FORMATE = (
    ("avif", "AVIF", {"quality": 55}),
    ("webp", "WEBP", {"quality": 80, "method": 6}),
    ("jpg", "JPEG", {"quality": FOTO_QUALITAET, "optimize": True, "progressive": True}),
)
# Was der Browser fuer die Auswahl braucht: wie breit das Bild am Ende steht.
# Ein gemeinsamer Wert waere fuer eines von beiden falsch, und zwar immer fuer
# das kleinere — der Browser laedt dann die grosse Fassung in den Gruppenplatz.
FOTO_SIZES_EINZELN = "(max-width: 46rem) 92vw, 640px"
FOTO_SIZES_GRUPPE = "(max-width: 560px) 92vw, 220px"

# dateiname -> {"name": slug, "zuschnitt": [x, y, b, h], "blur": [[x, y, b, h], ...],
# "position": "top"}. Kaesten und Zuschnitt sind RELATIV (0..1), damit sie das
# Verkleinern ueberleben; absolute Pixel zeigen nach dem Skalieren woanders hin,
# und zwar lautlos.
#
# Von Hand gepflegt, und das ist Absicht: ein Erkenner, der ein Kennzeichen von
# vier findet, liest sich wie Schutz und ist keiner. Eine Liste, die ich gegen
# das gerenderte Bild pruefen kann, ist ehrlicher.
#
# `zuschnitt` ist der staerkere der beiden Wege und laeuft ZUERST: er nimmt die
# Bildpunkte weg, statt sie zu verwischen. Was nicht mehr da ist, kann kein
# vergessener Kasten freilassen. Auf einer Strassenaufnahme mit zwanzig fremden
# Gesichtern ist er darum nicht die bequemere, sondern die ehrlichere Loesung.
# `blur` zaehlt danach im ZUGESCHNITTENEN Bild — sonst muesste man beim Setzen
# eines Kastens im Kopf zurueckrechnen, und ein falsch sitzender Kasten sieht
# auf der Seite aus wie Schutz.
#
# Schluessel mit `_` davor sind Notizen (`_zuschnitt`, `_blur`, `_position`) und
# stehen bewusst neben dem Wert: die Begruendung altert sonst getrennt von ihm.
FOTO_SCHLUESSEL = frozenset({"name", "blur", "zuschnitt", "position"})

FOTO_DATEN: dict[str, dict] = {}

# ---------------------------------------------------------------- Datenschutz

class PrivatException(Exception):
    """Etwas Privates haette die Seite erreicht. Es wird nichts geschrieben."""


# Muster, die niemals oeffentlich werden duerfen. Lieber ein Fehlalarm als eine
# Passnummer im Netz — ein Fehlalarm kostet eine Minute, der andere Fall ist
# nicht ruecknehmbar.
MUSTER = [
    # Der Zeichenvorrat der deutschen Passnummer laesst A, B, D, E, I, O, Q, S
    # und U aus (0/O und 1/I sollen nicht verwechselbar sein). `[0-9A-Z]{8}` fing
    # deshalb jedes neunstellige Wort in Versalien mit — am 20.08. brach der Build
    # an KEBENARAN ab, einem Zitat vom Behoerdenschild am Weg nach Juara. Der
    # Fehlalarm kostete nicht eine Minute, sondern haette das Zitat gekostet.
    (r"\b[CFGHJK][0-9CFGHJKLMNPRTVWXYZ]{8}\b", "Passnummer (deutsches Format)"),
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
        "OTTO_SPERRLISTE",
        Path.home() / "repos" / "assistant" / "state" / "oeffentlich-gesperrt.txt",
    )
)

# Warnliste: KEIN Abbruch, nur eine Meldung. Die Reise-Seite geht bewusst an
# Freunde, also entscheidet Jens, wer dort vorkommt — aber unbemerkt soll es
# nicht passieren.
WARNLISTE = Path(
    os.environ.get(
        "OTTO_WARNLISTE",
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


# Genau eine Adresse ist erlaubt (Impressum/Datenschutz brauchen sie), und sie
# wird VOR der Mustersuche aus dem Text entfernt statt im Muster ausgenommen.
# Die Grenze muss auf BEIDEN Seiten stehen: ohne die Vorschau nach links
# entfernt `xjens.laufer@solytics.de` seinen eigenen Rumpf und laesst ein
# nacktes `x` zurueck, das kein Muster mehr trifft — dieselbe Falle wie bei
# otto am 17.08.
_ERLAUBTE_ADRESSE = re.compile(
    r"(?<![\w.+-])" + re.escape(KONTAKT) + r"(?![\w-]|\.\w)", re.I
)

# Dieselbe Tuer fuer die USt-IdNr: "DE357501843" faellt in die Vorgangsnummer-
# Falle (zwei Buchstaben, 7-9 Ziffern) — dieselbe Form wie eine MDAC- oder
# Buchungsnummer, die die Reise-Seite zurecht sperrt. Auf dem Impressum ist
# sie Pflichtangabe (§ 27a UStG), keine private Nummer.
_ERLAUBTE_USTID = re.compile(r"\b" + re.escape(IMPRESSUM["ustid"]) + r"\b")


def pruefe_privat(text: str) -> None:
    """Wirft PrivatException, wenn etwas Personenbezogenes im Text steht."""
    klein = text.lower()
    for token in GEHEIME_TOKEN:
        if token in klein:
            raise PrivatException("gesperrtes Wort im Text (Liste ausserhalb des Repos)")
    pruefbar = _ERLAUBTE_USTID.sub("", _ERLAUBTE_ADRESSE.sub("", text))
    for muster, name in MUSTER:
        treffer = re.search(muster, pruefbar)
        if treffer:
            raise PrivatException(f"{name} im Text: {treffer.group(0)}")


# --------------------------------------------------------- Fremde Ressourcen

class FotoDatenException(Exception):
    """`content/fotos.json` sagt etwas anderes, als das Bild zeigen wird.

    Bis zum 24.08. gab `lade_foto_daten` bei einem Syntaxfehler stillschweigend
    `{}` zurueck: ein Komma zu viel, und JEDES Foto erschien ohne seine
    Sperrkaesten — mit gruenem Build und ohne eine Zeile Ausgabe. Ein Schutz,
    der bei einem Tippfehler lautlos abschaltet, ist keiner. Dasselbe gilt fuer
    einen unbekannten Schluessel: `zuschneiden` statt `zuschnitt` waere ein
    ungeschnittenes Bild, das laut Datei geschnitten ist.
    """


class ExternException(Exception):
    """Die Seite wuerde beim Leser etwas von fremden Servern laden."""


# Attribute, die beim ANZEIGEN laden. Ein `<a href>` steht bewusst nicht dabei:
# er laedt nichts, solange niemand klickt, und eine Reiseseite MUSS nach
# draussen zeigen duerfen. `canonical` und `alternate` laden ebenfalls nichts.
_LADEND = re.compile(
    r"<(?:script|img|iframe|video|audio|source|embed|track)\b[^>]*?\s"
    r"src\s*=\s*[\"']([^\"']+)[\"']", re.I)
_LINK = re.compile(r"<link\b([^>]*)>", re.I)
_CSS_URL = re.compile(r"url\(\s*[\"']?([^\"')]+)[\"')]", re.I)
_SKRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)
_ADRESSE_IM_TEXT = re.compile(r"https?://[^\s\"'<>{)]+", re.I)
_LINK_LAEDT_NICHT = ("canonical", "alternate", "me", "author", "license", "next", "prev")


def externe_ressourcen(html: str, erlaubt: tuple[str, ...] = None) -> list[str]:
    """Adressen, die der Browser beim Anzeigen von fremden Hosts holen wuerde."""
    erlaubt = EXTERN_ERLAUBT if erlaubt is None else erlaubt
    gefunden = list(_LADEND.findall(html))

    for attribute in _LINK.findall(html):
        rel = re.search(r"rel\s*=\s*[\"']?([\w -]+)", attribute, re.I)
        if rel and rel.group(1).strip().lower() in _LINK_LAEDT_NICHT:
            continue
        ziel = re.search(r"href\s*=\s*[\"']([^\"']+)[\"']", attribute, re.I)
        if ziel:
            gefunden.append(ziel.group(1))

    gefunden += _CSS_URL.findall(html)

    # Und das Javascript. Die Kartenkacheln laedt kein Attribut, sondern eine
    # Zeile Code — ein Waechter, der nur Attribute liest, meldet die Seite
    # sauber, waehrend der Browser bei einem Dritten holt.
    for rumpf in _SKRIPT.findall(html):
        gefunden += _ADRESSE_IM_TEXT.findall(rumpf)

    fremd = []
    for adresse in gefunden:
        treffer = re.match(r"(?:https?:)?//([^/]+)", adresse.strip())
        if treffer and treffer.group(1).lower() not in erlaubt:
            fremd.append(adresse.strip())
    return fremd


def pruefe_extern(html: str, erlaubt: tuple[str, ...] = None) -> None:
    """Wirft ExternException, wenn die Seite bei fremden Hosts laden wuerde.

    Warum ein Abbruch und kein Hinweis: ein `<link>` auf fonts.googleapis.com
    traegt die IP jedes Lesers zu Google, bevor der Leser etwas anklicken
    konnte, und das heilt keine Datenschutzzeile (LG Muenchen I, 20.01.2022 —
    3 O 17493/20). Ein Hinweis auf stderr wird beim naechsten Build ueberlesen.
    """
    fremd = externe_ressourcen(html, erlaubt)
    if fremd:
        raise ExternException(
            "fremde Ressource auf der Seite: " + ", ".join(sorted(set(fremd)))
            + " — erlaubt: " + (", ".join(erlaubt if erlaubt is not None
                                          else EXTERN_ERLAUBT) or "nichts"))


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


MARKER = re.compile(r"^[ \t]*<!--\s*(?:werkstatt|ort):.*?-->[ \t]*\n?", flags=re.M)
# Derselbe Marker, aber mit der Uhrzeit als Gruppe. Er wird vor dem Entfernen
# aller Kommentare in ein Token umgeschrieben, damit die Herkunft den Weg durch
# den Renderer ueberlebt: die englische Fassung hat einen anderen Text und
# damit einen anderen Anker — ueber den Anker gefunden wuerde sie nichts
# finden, und zwar still.
MARKER_ZEIT = re.compile(r"[ \t]*<!--\s*werkstatt:\s*telegram=([0-9TZ:+\-]+)\s*-->[ \t]*")
TOKEN = re.compile(r"@@WERKSTATT:([0-9TZ:+\-]+)@@")
# Der Ort eines Eintrags. Er geht denselben Weg wie die Herkunft und aus
# demselben Grund: die englische Fassung hat einen anderen Text, ueber den
# Text gefunden faende sie nichts — und zwar still.
ORT_WERT = re.compile(r"[ \t]*<!--\s*ort:\s*([a-z0-9-]+)\s*-->[ \t]*")
ORT_TOKEN = re.compile(r"@@ORT:([a-z0-9-]+)@@")


class OrtException(Exception):
    """Ein Eintrag nennt einen Ort, den die Karte nicht kennt."""

# Die Zaehlziffer eines Listenpunkts. Sie muss raus, bevor der Punkt ein <li>
# wird — die Nummer setzt der Browser, sonst steht "1. 1." auf der Seite.
ZIFFER = re.compile(r"^\d+\.[ \t]+")
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

    Fett darf Kursives ENTHALTEN. Das Muster verbot vorher jedes Sternchen im
    Inneren und fand sein Paar deshalb nie, wenn ein Werktitel darin stand:
    `**✓ *Garden Rhapsody* im Supertree Grove.**` stand am 17.08. mit zwei
    sichtbaren Sternchen auf der Seite — kein Fehler, keine leere Zeile, nur
    die Auszeichnung weg. Gefunden im gerenderten Bild, nicht im Test.
    Nicht-gierig (`.+?`) ist dabei die tragende Stelle: gierig wuerde
    "**eins** dazwischen **zwei**" zu einem einzigen fetten Block. Und
    `re.S` ist die zweite: die Quelle ist auf 95 Zeichen umbrochen, fast
    jeder Eintragstitel laeuft also ueber den Zeilenumbruch. Das alte
    `[^*]+` traf ihn beilaeufig mit — eine negierte Klasse schliesst den
    Umbruch ein, ein blankes `.` nicht. Die erste Fassung der Reparatur hat
    genau daran den haeufigsten Fall zerbrochen, um den seltenen zu heilen.
    """
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t, flags=re.S)
    t = re.sub(r"\*([^\s*][^*]*?)\*", r"<em>\1</em>", t)
    return t


def _eintrag(block: str, telegram: str = None, ort: str = None) -> str | None:
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
    # Die Marke haengt am Zeitstempel der Nachricht, nie am Text: ein Schluessel
    # aus dem Inhalt bricht, sobald ein Tippfehler behoben wird, und dann zeigt
    # der Block "Zuletzt" ins Leere. Eine Nachricht kann mehrere Eintraege
    # ausloesen (17.08., drei Fotos), deshalb der Zaehler.
    daten = _messung(block, telegram)
    marke = ""
    if daten:
        schluessel = slug(daten["telegram"][:16])
        MARKEN[schluessel] = MARKEN.get(schluessel, 0) + 1
        marke = (f' id="eintrag-{schluessel}-{MARKEN[schluessel]}"'
                 f' data-telegram="{html.escape(daten["telegram"], quote=True)}"')
    elif zeichen in "✗✓":
        # Keine Messung, aber verlinkbar sein muss der Block trotzdem. Bei ✗ ist
        # das die Regel — es ist ja gerade nichts passiert, das man von Telegram
        # bis zur Seite haette stoppen koennen. Bei ✓ die Ausnahme: die 33
        # MRT-Minuten sind aus zwei Zeitstempeln gerechnet und bekommen deshalb
        # bewusst keinen Herkunftsmarker. Die Marke kommt dann aus dem TITEL —
        # der Fliesstext darunter wird nachgebessert, die fette Zeile nicht;
        # ein geteilter Link ueberlebt damit eine Korrektur am Absatz.
        marke = f' id="{_fehl_marke(rest, "fehl" if zeichen == "✗" else "erlebt")}"'
    # Der Ort steht hinter der Herkunft, weil `EINTRAG_ZEILE` die Attribute in
    # dieser Reihenfolge liest. Ein unbekannter Schluessel bricht ab statt still
    # zu verschwinden: ein Tippfehler waere sonst ein Eintrag, der nie auf der
    # Karte auftaucht, und niemand erfuehre warum.
    if ort:
        if ort not in ORTE:
            raise OrtException(
                f"Unbekannter Ort '{ort}'. Bekannt sind: {', '.join(sorted(ORTE))}"
            )
        marke += f' data-ort="{ort}"'
    return (
        f'<div class="entry entry--{klasse}"{marke}>'
        f'<span class="mark" aria-hidden="true">{glyph}</span>'
        f'<span class="mark-label">{label}</span>'
        f"<p>{inline(rest)}</p>"
        f"{_spur(block, telegram)}"
        f"</div>"
    )


FEHL_MARKEN: dict[str, int] = {}
FEHL_TITEL = re.compile(r"^\*\*(.*?)\*\*", flags=re.S)


def _fehl_marke(rest: str, praefix: str = "fehl") -> str:
    """Sprungmarke aus den ersten Woertern des Titels.

    Zwei Aufrufer, ein Verfahren: ein ✗ hat nie eine Messung (es ist ja gerade
    nichts passiert), und ein paar ✓ haben ebenfalls keine — die 33 MRT-Minuten
    sind aus zwei Zeitstempeln gerechnet, nicht gemeldet. Ohne Marke ist so ein
    Eintrag von der Karte aus nicht erreichbar, und die Zahl unter der Karte
    waere kleiner als die Zahl der Haken auf der Seite.

    Gekuerzt auf eine Kante, nicht mitten im Wort: eine Marke ist eine Adresse,
    die jemand weitergibt. Der Zaehler dahinter faengt den Fall ab, dass zwei
    ✗ mit denselben sechs Woertern anfangen — zwei gleiche id auf einer Seite
    lassen den Browser immer die erste anspringen, und das faellt niemandem auf.
    """
    titel = FEHL_TITEL.match(rest)
    basis = slug(titel.group(1)) if titel else "eintrag"
    if len(basis) > 48:
        # An der Wortkante schneiden, nicht bei Zeichen 48: `…-bei-u` liest
        # sich wie ein Uebertragungsfehler, und die Marke steht in der
        # Adresszeile, sobald jemand den Punkt weitergibt.
        basis = basis[:48].rsplit("-", 1)[0]
    basis = f"{praefix}-{basis}"
    FEHL_MARKEN[basis] = FEHL_MARKEN.get(basis, 0) + 1
    nr = FEHL_MARKEN[basis]
    return basis + (f"-{nr}" if nr > 1 else "")


def _uhr(iso: str) -> str:
    z = datetime.fromisoformat(iso)
    return z.strftime("%d %b, %H:%M") if SPRACHE == "en" else z.strftime("%d.%m. %H:%M")


MARKEN: dict[str, int] = {}


def _messung(block: str, telegram: str = None) -> dict | None:
    """Die Messung zu einem Block — ueber den Textanker, sonst ueber die Uhrzeit.

    Eine Stelle, weil zwei Leser: die Herkunftszeile unter dem Eintrag und die
    Sprungmarke, an der der Block "Zuletzt" ihn wiederfindet. Getrennt aufgeloest
    bekaeme ein Eintrag eine Marke ohne Herkunft oder umgekehrt — und zwar still.
    """
    anker = block.splitlines()[0].strip()[:ANKER_LAENGE]
    daten = WERKSTATT.get(anker)
    if daten is None and telegram:
        daten = WERKSTATT.get(_tg_schluessel(telegram))
    if not daten or daten.get("minuten") is None:
        return None
    return daten


def _spur(block: str, telegram: str = None) -> str:
    """Herkunftszeile unter einem Eintrag: Nachricht → veroeffentlicht → Dauer.

    Das ist die eigentliche Verbindung zwischen dieser Seite und /otto/. Ein
    Reisebericht mit einem Link auf eine Seite ueber Agenten behauptet etwas;
    ein Eintrag, der seine eigene Entstehungszeit mitfuehrt, belegt es.

    Ohne Messung wird gar nichts gerendert — eine leere oder auf 0 gesetzte
    Dauer waere die schnellste Zahl der Seite und hiesse "nicht gemessen".
    """
    daten = _messung(block, telegram)
    if not daten:
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
    """Liest content/fotos.json.

    **Fehlt die Datei, ist das kein Fehler** — das Repo muss bauen, bevor das
    erste Foto eingetragen ist. **Ist sie da und unlesbar, bricht der Build ab.**
    Der Unterschied ist der ganze Punkt: unlesbar hiess frueher `{}`, und `{}`
    heisst „keine Sperrkaesten", nicht „keine Datei".
    """
    pfad = Path(pfad) if pfad else FOTO_DATEN_DATEI
    if not pfad.exists():
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FotoDatenException(f"{pfad} ist nicht lesbar: {e}") from e
    if not isinstance(daten, dict):
        raise FotoDatenException(f"{pfad} enthaelt kein Objekt.")
    return daten


def pruefe_foto_daten(datei: str, daten: dict) -> None:
    """Ein Eintrag muss halten, was er behauptet — sonst Abbruch, nie Zurechtbiegen.

    Ein stillschweigend gekappter Zuschnitt schneidet woanders als beabsichtigt,
    und niemand sieht es dem fertigen Bild an.
    """
    fremd = sorted(k for k in daten if not k.startswith("_") and k not in FOTO_SCHLUESSEL)
    if fremd:
        raise FotoDatenException(
            f"{datei}: unbekannte(r) Schluessel {', '.join(fremd)} "
            f"(erlaubt: {', '.join(sorted(FOTO_SCHLUESSEL))}, Notizen mit `_` davor)")

    kaesten = [("zuschnitt", daten["zuschnitt"])] if "zuschnitt" in daten else []
    kaesten += [("blur", k) for k in daten.get("blur", [])]
    for feld, kasten in kaesten:
        if len(kasten) != 4 or not all(isinstance(w, (int, float)) for w in kasten):
            raise FotoDatenException(f"{datei}: {feld} braucht vier Zahlen [x, y, b, h].")
        x, y, b, h = kasten
        if b <= 0 or h <= 0:
            raise FotoDatenException(f"{datei}: {feld} hat Breite oder Hoehe 0.")
        if x < 0 or y < 0 or x + b > 1 or y + h > 1:
            raise FotoDatenException(
                f"{datei}: {feld} {kasten} liegt ausserhalb des Bildes (0..1).")


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
    pruefe_foto_daten(datei, daten)
    name = daten.get("name") or Path(datei).stem
    ziel = FOTO_ZIEL / f"{name}.jpg"

    if not quelle.exists():
        if ziel.exists():
            return ziel  # schon veroeffentlicht; das Repo baut auch ohne Assistenz-Repo
        print(f"ACHTUNG: Foto fehlt, Bild faellt weg: {datei}", file=sys.stderr)
        return None

    stempel = _foto_stempel(quelle, daten)
    if _fassungen_aktuell(name, stempel):
        return ziel

    with Image.open(quelle) as bild:
        bild = bild.convert("RGB")
        if "zuschnitt" in daten:
            x, y, b, h = daten["zuschnitt"]
            breite, hoehe = bild.size
            bild = bild.crop((int(x * breite), int(y * hoehe),
                              int((x + b) * breite), int((y + h) * hoehe)))
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
        basis = bild.size[0]
        for b in foto_breiten(basis):
            fassung = bild if b == basis else bild.resize(
                (b, round(bild.size[1] * b / basis)), Image.LANCZOS)
            for endung, format_, optionen in FOTO_FORMATE:
                pfad = fassungs_pfad(name, b, endung, basis)
                # Ohne exif=/icc_profile= schreibt Pillow vorhandene Bloecke
                # wieder mit — in jedes Format, nicht nur ins JPEG.
                fassung.save(pfad, format_, exif=b"", icc_profile=None, **optionen)
    _stempel_schreiben(name, stempel)
    return ziel


def foto_breiten(basis: int) -> list[int]:
    """Welche Breiten geschrieben werden. Nie ueber die Vorlage hinaus —
    ein hochkantes Telegram-Bild ist 720 px breit, eine 1280er-Fassung davon
    kostet Bytes ohne einen einzigen zusaetzlichen Bildpunkt."""
    return sorted({b for b in FOTO_BREITEN if b < basis} | {basis})


def fassungs_pfad(name: str, breite: int, endung: str, basis: int) -> Path:
    """Die groesste JPEG-Fassung behaelt den Namen ohne Breite: sie ist die
    Rueckfalldatei im `src`, und ein Browser ohne srcset-Verstaendnis kennt
    nur sie."""
    if endung == "jpg" and breite == basis:
        return FOTO_ZIEL / f"{name}.jpg"
    return FOTO_ZIEL / f"{name}-{breite}.{endung}"


def _foto_stempel(quelle: Path, daten: dict) -> str:
    """Alles, was das Ergebnis aendern darf, in einer Zeile. Der Zwischen-
    speicher darf keinen Sperrkasten und keinen Zuschnitt verschlucken: beide
    stehen deshalb im Stempel, nicht nur die Datei. Sonst bliebe genau die
    Fassung mit den Gesichtern liegen, waehrend die fotos.json sagt, sie seien
    weggeschnitten."""
    inhalt = quelle.read_bytes()
    beschreibung = json.dumps(
        [daten.get("blur", []), daten.get("zuschnitt"), list(FOTO_BREITEN),
         [(e, o) for e, _, o in FOTO_FORMATE]], sort_keys=True)
    return hashlib.sha256(inhalt + beschreibung.encode()).hexdigest()


def _stempel_datei() -> Path:
    """Als Funktion, nicht als Konstante: FOTO_ZIEL wird im Test umgebogen,
    und eine beim Import berechnete Konstante zeigte dann weiter in das echte
    Repo — der Test haette den Zwischenspeicher der Seite beschrieben."""
    return FOTO_ZIEL / ".fassungen.json"


def _stempel_lesen() -> dict:
    try:
        return json.loads(_stempel_datei().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fassungen_aktuell(name: str, stempel: str) -> bool:
    """Nur dann ueberspringen, wenn der Stempel stimmt UND jede Datei da ist.
    AVIF kostet eine Viertelsekunde je Bild und Breite; ohne diese Pruefung
    waechst jeder Build um eine Zeit, die niemand misst — mit einer Pruefung,
    die nur den Stempel liest, faellt dafuer eine geloeschte Fassung nicht auf."""
    if _stempel_lesen().get(name) != stempel:
        return False
    basis_datei = FOTO_ZIEL / f"{name}.jpg"
    if not basis_datei.exists():
        return False
    from PIL import Image

    with Image.open(basis_datei) as bild:
        basis = bild.size[0]
    return all(fassungs_pfad(name, b, e, basis).exists()
               for b in foto_breiten(basis) for e, _, _ in FOTO_FORMATE)


def _stempel_schreiben(name: str, stempel: str) -> None:
    alle = _stempel_lesen()
    alle[name] = stempel
    FOTO_ZIEL.mkdir(parents=True, exist_ok=True)
    _stempel_datei().write_text(
        json.dumps(alle, indent=1, sort_keys=True), encoding="utf-8")


def _fotopfad(datei: str) -> str:
    """Bildadresse relativ zur Seite, die sie laedt.

    Die Bilder liegen EINMAL unter `/malaysia/fotos/`. Die deutsche Seite liegt
    daneben, die englische eine Ebene tiefer unter `/malaysia/en/`. Ein
    relatives `fotos/…` zeigt von dort auf `/malaysia/en/fotos/…` und damit ins
    Leere — 144 Adressen, jede live ein 404, gefunden erst am 18.08.

    Warum es so lange unsichtbar war: die Tests verglichen erzeugte Zeichenketten
    miteinander, und eine Zeichenkette kann nicht 404 sein. Geprueft wird deshalb
    jetzt gegen die Platte (`TestBildpfadeEnglisch`), nicht gegen das Muster.
    """
    return ("../" if SPRACHE == "en" else "") + f"fotos/{datei}"


def _srcset(name: str, endung: str, basis: int) -> str:
    return ", ".join(
        f"{_fotopfad(fassungs_pfad(name, b, endung, basis).name)} {b}w"
        for b in foto_breiten(basis))


def _figure(text: str, datei: str, gruppe: bool = False) -> str | None:
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
    name = ziel.stem
    sizes = FOTO_SIZES_GRUPPE if gruppe else FOTO_SIZES_EINZELN
    quellen = "".join(
        f'<source type="image/{endung}" srcset="{_srcset(name, endung, breite)}" '
        f'sizes="{sizes}">'
        for endung, _, _ in FOTO_FORMATE if endung != "jpg")
    return (
        f'<figure class="foto"{stil}>'
        f"<picture>{quellen}"
        f'<img src="{html.escape(_fotopfad(ziel.name))}" ' 
        f'srcset="{_srcset(name, "jpg", breite)}" sizes="{sizes}" '
        f'width="{breite}" height="{hoehe}" '
        f'alt="{html.escape(text, quote=True)}" loading="lazy" decoding="async">'
        "</picture>"
        f"<figcaption>{inline(text)}</figcaption>"
        "</figure>"
    )


def _fotos(block: str) -> str | None:
    """Ein Absatz aus lauter Bildzeilen → ein Bild oder eine Gruppe."""
    zeilen = [z.strip() for z in block.splitlines() if z.strip()]
    treffer = [FOTO.match(z) for z in zeilen]
    if not zeilen or not all(treffer):
        return None
    gruppe = len(zeilen) > 1
    stuecke = [_figure(t.group("text"), t.group("datei"), gruppe) for t in treffer]
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
    md = ORT_WERT.sub(r"@@ORT:\1@@", md)
    md = strip_kommentare(strip_marker(md))
    MARKEN.clear()  # sonst zaehlt die englische Fassung auf der deutschen weiter
    FEHL_MARKEN.clear()  # dito: sonst heisst das erste ✗ der en-Fassung fehl-…-2
    teile = []
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        zeit = TOKEN.search(block)
        telegram = zeit.group(1) if zeit else None
        block = TOKEN.sub("", block).strip()
        wo = ORT_TOKEN.search(block)
        ort = wo.group(1) if wo else None
        block = ORT_TOKEN.sub("", block).strip()
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
        elif block.startswith("1. ") and re.search(r"^2\. ", block, re.M):
            # Die Regel ist absichtlich eng: auf Deutsch beginnt ein Absatz oft mit
            # einem Datum ("18. August 2026 war ..."), und ein naives ^\d+\. macht
            # daraus eine Liste. Eine Aufzaehlung faengt bei 1. an und hat eine 2.
            punkte = re.split(r"\n(?=\d+\. )", block)
            li = "".join(
                f"<li>{inline(ZIFFER.sub('', p).strip())}</li>" for p in punkte
            )
            teile.append(f'<ol class="schritte">{li}</ol>')
        else:
            teile.append(_eintrag(block, telegram, ort) or f"<p>{inline(block)}</p>")
    return "\n".join(teile)


# ------------------------------------------------- Zuletzt + Recherche falten
#
# Beides geht auf eine Frage von Jens zurueck (18.08. 09:44): "Sollten wir den
# Reiseblog nicht spannender gestalten?" Die Antwort war keine Design-Frage,
# sondern eine Sortier-Frage — der Text bleibt in beiden Umbauten unveraendert.

EINTRAG_ZEILE = re.compile(
    r'^<div class="entry entry--(?P<art>[a-z]+)"'
    r'(?: id="(?P<id>[^"]+)")?(?: data-telegram="(?P<zeit>[^"]+)")?'
    r'(?: data-ort="(?P<ort>[^"]+)")?>'
)

# Ein Block ist NICHT eine Zeile. Die Absaetze im Quelldokument sind umbrochen,
# und `inline()` laesst den Umbruch stehen — ein Eintrag ist im Rumpf im Schnitt
# sechs Zeilen lang. Eine zeilenweise Faltung fand deshalb auf der echten Seite
# null zusammenhaengende Laeufe, waehrend sie an einzeiligen Testdaten gruen war
# (18.08., gefunden vom Test gegen die ausgelieferte Datei, nicht vom Renderer).
#
# Die Liste ist eine Positivliste und darf es sein: `render_markdown` ist der
# einzige Erzeuger dieses Rumpfs. Eine Regel "Zeile beginnt mit <" waere falsch —
# gemessen beginnen Fortsetzungszeilen unter anderem mit <em> und <code>.
BLOCK_START = re.compile(
    r'\n(?=<(?:h1>|h2 id=|p>|div class="(?:entry |fotos |table-wrap")'
    r'|figure class="foto"|ul class="legende"|ol class="schritte"))'
)


def _bloecke(rumpf: str) -> list[str]:
    """Den gerenderten Rumpf wieder in die Bloecke zerlegen, aus denen er entstand."""
    return BLOCK_START.split(rumpf)
STARK = re.compile(r"<strong>(.*?)</strong>", flags=re.S)
# Im Eintrag gehoert das Datum in den Satz. Im Block "Zuletzt" steht es in
# einer eigenen Spalte daneben — zweimal dasselbe Datum in einer Zeile liest
# sich wie ein Fehler.
TITEL_DATUM = re.compile(r"\s*\((?:\d{1,2}\.\d{1,2}\.|\d{1,2} \w{3})\)\.?\s*$")
MINIATUR = re.compile(r'fotos/([a-z0-9-]+)-640\.jpg')


def _zuletzt(rumpf: str, anzahl: int = 5) -> str:
    """Die juengsten selbst erlebten Meldungen, ganz oben.

    Der Grund ist gemessen, nicht geraten: die frischen Eintraege liegen in
    ihren Themenabschnitten (Essen, Bezahlen, Strom), und wer nach zwei Tagen
    wiederkommt, findet nicht, was neu ist — er muesste die ganze Seite lesen.

    Aufgenommen wird nur, was Jens selbst gemeldet hat (`✓` MIT Messung).
    Recherche hat kein Datum, an dem sie "neu" waere; ein erfundenes waere
    schlimmer als ihr Fehlen — dieselbe Regel wie im Feed.
    """
    bloecke = _bloecke(rumpf)
    treffer = []
    for i, block in enumerate(bloecke):
        m = EINTRAG_ZEILE.match(block)
        if not m or m.group("art") != "erlebt" or not m.group("id"):
            continue
        # Seit ✓ ohne Messung eine Titelmarke bekommt, reicht die id als Filter
        # nicht mehr: ohne Zeitstempel gibt es kein Datum, nach dem sich
        # sortieren liesse, und `sort` faellt ueber das None.
        if not m.group("zeit"):
            continue
        titel = STARK.search(block)
        if not titel:
            continue
        # Das Bild zum Eintrag steht im FOLGENDEN Block, nie im Eintrag selbst.
        naechster = bloecke[i + 1] if i + 1 < len(bloecke) else ""
        bild = MINIATUR.search(naechster) if naechster.startswith(
            ('<figure class="foto"', '<div class="fotos ')) else None
        treffer.append({
            "id": m.group("id"), "zeit": m.group("zeit"),
            "titel": TITEL_DATUM.sub("", titel.group(1).strip()).rstrip(" .") + ".",
            "bild": bild.group(1) if bild else None,
        })
    if not treffer:
        return ""
    treffer.sort(key=lambda e: e["zeit"], reverse=True)

    posten = []
    for e in treffer[:anzahl]:
        datum = _uhr(e["zeit"]).split(",")[0].strip() if SPRACHE == "en" else \
            _uhr(e["zeit"]).split(" ")[0].strip()
        vorschau = (
            f'<img class="zuletzt-bild" src="{_fotopfad(e["bild"] + "-640.jpg")}" alt="" ' 
            f'loading="lazy" decoding="async" width="640" height="360">'
            if e["bild"] else ""
        )
        posten.append(
            f'<li class="zuletzt-posten"><a href="#{e["id"]}">{vorschau}'
            f'<span class="zuletzt-datum">{html.escape(datum)}</span>'
            f'<span class="zuletzt-titel">{e["titel"]}</span></a></li>'
        )
    return (
        f'<section id="zuletzt" class="zuletzt" aria-label="'
        f'{_t("Zuletzt erlebt", "Latest from the road")}">'
        f'<h2 class="zuletzt-kopf">{_t("Zuletzt", "Latest")}</h2>'
        f'<ol class="zuletzt-liste">{"".join(posten)}</ol></section>'
    )


def _fehlschlaege(rumpf: str) -> str:
    """Was nicht funktioniert hat — ganz oben, obwohl es das Seltenste ist.

    Umbau 2 (Jens 18.08. 09:44). Die Seite traegt 2 ✗ gegen 29 ✓ und 40 ○, und
    beide lagen in ihrem Themenabschnitt: der Automaten-Irrtum unter „Bezahlen",
    die gescheiterte SIM-Bestellung unter „Mobilfunk". Wer die Seite ueberfliegt,
    sieht 71 Haken und keinen einzigen Reinfall — das liest sich glatter, als es
    war. Der Block ist die Gegenprobe zum Versprechen der Seite und macht die
    anderen Zeichen erst glaubwuerdig.

    Gedeckelt wird nichts: ✗ ist die knappste Kategorie der Seite, ein Deckel
    haette hier nur eine Zahl versteckt.
    """
    posten = []
    for block in _bloecke(rumpf):
        m = EINTRAG_ZEILE.match(block)
        if not m or m.group("art") != "gescheitert" or not m.group("id"):
            continue
        titel = STARK.search(block)
        if not titel:
            continue
        posten.append(
            f'<li class="fehl-posten"><a href="#{m.group("id")}">'
            f'<span class="fehl-zeichen" aria-hidden="true">✗</span>'
            f'<span class="fehl-titel">'
            f'{TITEL_DATUM.sub("", titel.group(1).strip()).rstrip(" .")}.'
            f'</span></a></li>'
        )
    if not posten:
        return ""
    kopf = _t("Was nicht funktioniert hat", "What did not work")
    return (
        f'<section id="fehlschlaege" class="fehl" aria-label="{kopf}">'
        f'<h2 class="fehl-kopf">{kopf} <span class="fehl-zahl">{len(posten)}</span></h2>'
        f'<ol class="fehl-liste">{"".join(posten)}</ol></section>'
    )


def falte_recherche(rumpf: str, ab: int = 2) -> str:
    """Zusammenhaengende `○`-Eintraege in einen aufklappbaren Kasten.

    Die Seite verspricht "was funktioniert hat und was nicht" und bestand am
    18.08. aus 37 nachgeschlagenen gegen 28 erlebten Eintraegen — die
    Recherche trug die Seite, nicht das Erlebte. Eingeklappt kehrt sich das
    um, ohne dass ein Satz verschwindet: der Text steht im `<details>` und
    ist einen Klick entfernt, ohne JavaScript.

    Ein einzelner `○` bekommt KEINEN Kasten (`ab=2`): ein Kasten um einen
    Eintrag kostet einen Klick und spart keine Zeile.
    """
    aus, lauf = [], []

    def schliessen():
        if not lauf:
            return
        if len(lauf) < ab:
            aus.extend(lauf)
        else:
            wort = _t(
                f"{len(lauf)} nachgeschlagene Notizen — nicht selbst geprüft",
                f"{len(lauf)} looked-up notes — not checked ourselves",
            )
            aus.append(
                f'<details class="recherche-box"><summary>{html.escape(wort)}'
                f"</summary>" + "".join(lauf) + "</details>"
            )
        lauf.clear()

    for block in _bloecke(rumpf):
        m = EINTRAG_ZEILE.match(block)
        if m and m.group("art") == "recherche":
            lauf.append(block)
        else:
            schliessen()
            aus.append(block)
    schliessen()
    return "\n".join(aus)


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
    ("Sandakan", 5.8402, 118.1179, "25.–26.08. · Sabah", "25–26 Aug · Sabah"),
    # Sepilok: Jens' eigene Standortmeldung (Telegram 26.08. 09:57), nicht der
    # Ortsmittelpunkt eines Kartendienstes. Kinabatangan: Kampung Bilit, die
    # Schlafadresse laut Buchung AB26084033, ueber Nominatim aufgeloest — dort
    # ist niemand mit einem Geraet gewesen, das eine Koordinate meldet.
    ("Sepilok", 5.8728, 117.9432, "26.–27.08. · Sabah", "26–27 Aug · Sabah"),
    ("Kinabatangan", 5.4999, 118.2080, "27.–29.08. · Sabah",
     "27–29 Aug · Sabah"),
    ("Kota Kinabalu", 5.9804, 116.0735, "29.08.–03.09.", "29 Aug – 3 Sep"),
    ("Kudat", 6.8837, 116.8378, "04.–05.09. · Tip of Borneo",
     "4–5 Sep · Tip of Borneo"),
]

# Der Schluessel, den ein `<!-- ort: … -->` nennen darf. Aus STATIONEN erzeugt,
# nicht danebengeschrieben: zwei Listen waeren nach einer Woche zwei Listen.
ORTE = {slug(name): name for name, *_ in STATIONEN}


# Was die Karte aus dem Dokument geholt hat. Gemeldet wird eine Zahl, keine
# Warnung: dass eine Etappe ("gut vier Stunden von der Grenze nach Mersing")
# keinen Ort traegt, ist die Regel und kein Versaeumnis — aber wenn die Zahl
# eines Tages faellt, waehrend die Seite waechst, sieht man es hier.
KARTE_SUMME: dict[str, int] = {}


def _erlebnisse(rumpf: str) -> dict[str, list[tuple[str, str]]]:
    """Je Ort die selbst erlebten Eintraege, in Dokumentreihenfolge.

    Nur `✓` MIT Sprungmarke. Recherche hat keinen Ort, an dem jemand gewesen
    waere — ein Punkt dafuer waere eine Ortsangabe fuer etwas Gelesenes.
    """
    gefunden: dict[str, list[tuple[str, str]]] = {}
    erlebt_gesamt = 0
    for block in _bloecke(rumpf):
        m = EINTRAG_ZEILE.match(block)
        if not m or m.group("art") != "erlebt":
            continue
        erlebt_gesamt += 1
        if not m.group("ort") or not m.group("id"):
            continue
        titel = STARK.search(block)
        if not titel:
            continue
        gefunden.setdefault(m.group("ort"), []).append((
            m.group("id"),
            TITEL_DATUM.sub("", titel.group(1).strip()).rstrip(" .") + ".",
        ))
    KARTE_SUMME.clear()
    KARTE_SUMME.update(
        erlebt=erlebt_gesamt,
        verortet=sum(len(v) for v in gefunden.values()),
        stationen=len(gefunden),
    )
    return gefunden


def _karte(rumpf: str = "") -> str:
    """Die Route — und seit Jens' vierter Idee (18.08. 09:44) der zweite Weg
    in den Text.

    "Ein Punkt je ✓ mit Sprung zum Eintrag gibt einen zweiten Weg hinein, ueber
    den Ort statt ueber das Thema." Gebuendelt wird pro Station, nicht pro
    Eintrag: sieben Erlebnisse in Tekek liegen auf derselben Koordinate und
    haetten sich gegenseitig verdeckt.

    Neue Koordinaten kommen dabei keine dazu, und das ist Absicht. Die acht
    Stationen stehen seit dem 17.08. hier und sind geprueft; ein Punkt, den
    diese Sitzung fuer "Mamak-Stand in Mersing" erfunden haette, waere eine
    Genauigkeit, die niemand gemessen hat.
    """
    erlebt = _erlebnisse(rumpf)
    stationen = [
        (name, lat, lon, _t(de, en), erlebt.get(slug(name), []))
        for name, lat, lon, de, en in STATIONEN
    ]
    gesamt = sum(len(e) for *_, e in stationen)

    # Das JS bekommt die Daten als JSON, nicht handgeschrieben: in den Titeln
    # stehen Anfuehrungszeichen, Apostrophe und Umlaute. `</` wird zerlegt,
    # weil sonst ein Titel das <script> schliessen koennte.
    daten = json.dumps(
        [[name, lat, lon, note, [[i, t] for i, t in eintraege]]
         for name, lat, lon, note, eintraege in stationen],
        ensure_ascii=False,
    ).replace("</", "<\\/")

    posten = []
    for name, _, _, note, eintraege in stationen:
        zahl = (f'<span class="stationen-zahl">{len(eintraege)}</span>'
                if eintraege else "")
        sprung = "".join(
            f'<li><a href="#{i}">{t}</a></li>' for i, t in eintraege
        )
        liste = f'<ul class="stationen-erlebt">{sprung}</ul>' if sprung else ""
        posten.append(
            f"<li><b>{html.escape(name)}</b>{zahl}"
            f'<span class="stationen-zeit">{html.escape(note)}</span>{liste}</li>'
        )
    liste = "".join(posten)

    # Seitentext, nicht Kommentar: hier stehen echte Umlaute. Ein Test haelt
    # die ganze Seite dagegen — die ASCII-Umschrift dieser Datei gilt fuer den
    # Quelltext, nicht fuer das, was der Leser sieht.
    grund = _t(
        "Acht Stationen zwischen Singapur und dem Norden Borneos. Die Anreise "
        "über Frankfurt und Bahrain liegt außerhalb des Ausschnitts.",
        "Eight stops between Singapore and the north of Borneo. The journey out "
        "via Frankfurt and Bahrain lies outside the frame.",
    )
    if gesamt:
        grund += _t(
            f" An den Stationen hängen die {gesamt} selbst erlebten Einträge — "
            "ein zweiter Weg in den Text, über den Ort statt über das Thema.",
            f" The {gesamt} first-hand entries hang off the stops — a second way "
            "into the text, by place instead of by topic.",
        )

    return f"""
<section class="karte-block" aria-labelledby="karte-titel">
  <h2 id="karte-titel">{_t("Die Route", "The route")}</h2>
  <p class="karte-intro">{grund}</p>
  <div id="karte" role="img" aria-label="{_t(
       'Karte der Reiseroute von Singapur über die Halbinsel bis nach Sabah auf Borneo',
       'Map of the route from Singapore across the peninsula to Sabah on Borneo')}">
    <div class="karte-tuer">
      <p>{_t(
         "Die Kartenbilder kommen von OpenStreetMap. Beim Laden erfährt "
         "openstreetmap.org Ihre IP-Adresse — deshalb erst auf Ihren Klick.",
         "The map tiles come from OpenStreetMap. Loading them tells "
         "openstreetmap.org your IP address — so it happens on your click, not before.")}</p>
      <button type="button" id="karte-laden">{_t("Karte laden", "Load map")}</button>
    </div>
  </div>
  <noscript><p class="hinweis">{_t(
     "Die Karte braucht JavaScript. Die Stationen stehen als Liste darunter.",
     "The map needs JavaScript. The stops are listed below it.")}</p></noscript>
  <ol class="stationen">{liste}</ol>
</section>
<script>
  // Die Kacheln sind der einzige Dritte, der auf dieser Seite bleibt — eine
  // Weltkarte laesst sich nicht mitliefern. Also entscheidet der Leser: vor
  // dem Klick geht keine Anfrage nach openstreetmap.org. Der Aufruf steht
  // deshalb IN dieser Funktion und nirgends sonst.
  function karteLaden() {{
    var el = document.getElementById("karte");
    if (!el || typeof L === "undefined") return;
    el.innerHTML = "";
    el.removeAttribute("role");
    var orte = {daten};
    var karte = L.map("karte", {{ scrollWheelZoom: false }});
    L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 17,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }}).addTo(karte);
    var linie = [];
    orte.forEach(function (o, i) {{
      linie.push([o[1], o[2]]);
      var eintraege = o[4] || [];
      // Der Radius traegt die Zahl der Erlebnisse. Eine Station ohne Erlebnis
      // bleibt sichtbar — ein Loch in der Linie waere eine andere Reise.
      var punkt = L.circleMarker([o[1], o[2]], {{
        radius: eintraege.length ? 7 + Math.min(eintraege.length, 8) : 5,
        weight: 2, color: "#1c4f3f",
        fillColor: eintraege.length ? "#2f6b4f" : "#8aa79b",
        fillOpacity: eintraege.length ? 1 : .6
      }}).addTo(karte);
      var text = "<b>" + (i + 1) + ". " + o[0] + "</b><br>" + o[3];
      if (eintraege.length) {{
        text += "<ul class=\\"karte-liste\\">";
        eintraege.forEach(function (e) {{
          text += "<li><a href=\\"#" + e[0] + "\\">" + e[1] + "</a></li>";
        }});
        text += "</ul>";
      }}
      punkt.bindPopup(text, {{ maxWidth: 320 }});
    }});
    L.polyline(linie, {{ color: "#1c4f3f", weight: 2, opacity: .45, dashArray: "5 6" }}).addTo(karte);
    karte.fitBounds(L.latLngBounds(linie).pad(.12));
  }}
  document.addEventListener("DOMContentLoaded", function () {{
    var knopf = document.getElementById("karte-laden");
    if (knopf) knopf.addEventListener("click", karteLaden);
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
     <a href="https://jenslaufer.com/otto/en/">How this is built and what else runs
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
     Eintrag veröffentlicht hat. <a href="https://jenslaufer.com/otto/">Wie das
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
     something has worked; the rest is done by <a href="{HARNESS_SEITE}en/">Otto</a>,
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
     wenn etwas funktioniert hat; den Rest macht <a href="{HARNESS_SEITE}">Otto</a>,
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


def _og_karte(summe: dict, titel: str = None) -> str:
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
    # Der Titel kam hier bis zum 22.08. aus einer Suchen-und-Ersetzen-Zeile:
    # die deutsche Vorlage trug ihn im Klartext, die englische Karte entstand
    # daraus. Eine geaenderte Ueberschrift traf das Muster nicht mehr und die
    # Karte blieb still auf dem alten Titel.
    if titel is None:
        titel = seiten_titel(KOPIEN[SPRACHE].read_text(encoding="utf-8"))
    if SPRACHE == "en":
        karte = karte.replace('lang="de"', 'lang="en"')
    # Die Adresse kommt aus BASIS, nicht aus der Vorlage. Sie stand dort als
    # malaysia.jenslaufer.com — eine Subdomain, die nie angelegt wurde. Im HTML
    # war ueberall die richtige Adresse, geteilt wird aber das Bild, und dort
    # findet sie kein grep. Wer sie abtippt, landet nirgends (17.08. gemessen).
    ersatz = {
        "SEITENTITEL": _titel_fuer_html(titel),
        "ADRESSE": BASIS.split("://", 1)[1].rstrip("/"),
        "UNTERZEILE": _t(
            "Reisenotizen, unterwegs per Telegram geschrieben und von einer "
            "Maschine in Deutschland veröffentlicht.",
            "Travel notes, written by phone on the road and published by a "
            "machine back in Germany."),
        "ERLEBT": _t("selbst erlebt", "seen ourselves"),
        "RECHERCHE": _t("nachgeschlagen", "looked up"),
        "GESCHEITERT": _t("hat nicht funktioniert", "did not work"),
        "FUSS": fuss,
    }
    for name, wert in ersatz.items():
        karte = karte.replace("{{" + name + "}}", wert)
    return karte


def baue_og_bild(summe: dict, titel: str = None, ziel: Path = None) -> Path | None:
    """Rendert die Vorschaukarte (1200x630) mit Chromium.

    Ohne Bild ist der geteilte Link in Telegram, WhatsApp und LinkedIn eine graue
    Zeile — und geteilt wird diese Seite, dafuer ist sie da.
    """
    ziel = ziel or (WURZEL / ("og.png" if SPRACHE == "de" else "en/og.png"))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    karte = _og_karte(summe, titel)
    pruefe_privat(karte)

    # Snap-Chromium darf weder nach /tmp noch in versteckte Ordner schreiben.
    arbeit = Path.home() / "pdf-slim-work" / "malaysia" / SPRACHE
    arbeit.mkdir(parents=True, exist_ok=True)
    quelle = arbeit / "og-karte.html"
    quelle.write_text(karte, encoding="utf-8")
    # Die Schriften liegen seit dem 17.08. im Repo statt bei Google — also
    # muessen sie mit in den Arbeitsordner, sonst rendert Chromium in der
    # Systemschrift. An einem Bild faellt das niemandem auf, bis es auf
    # LinkedIn oder im WhatsApp-Status steht.
    for datei in sorted((WURZEL / "fonts").glob("*")):
        (arbeit / datei.name).write_bytes(datei.read_bytes())

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


H1 = re.compile(r"^#[ \t]+(.+?)[ \t]*$", flags=re.M)


def _titel_fuer_html(titel: str) -> str:
    """Sicher als Textknoten UND in einem Attribut mit doppelten Anfuehrungszeichen.

    `html.escape(quote=True)` waere zu scharf: es macht aus dem Apostroph in
    „what didn't" ein `&#x27;`, das im Browser-Reiter und in der WhatsApp-
    Vorschau als solches dasteht. Gefaehrlich sind hier `&<>` und das doppelte
    Anfuehrungszeichen, nicht der Apostroph.
    """
    return html.escape(titel, quote=False).replace('"', "&quot;")


def seiten_titel(md: str) -> str:
    """Der Seitentitel ist die erste Ueberschrift des Quelldokuments — nur die.

    Bis zum 22.08. stand er zusaetzlich im `<title>`, im `og:title`, auf der
    Vorschaukarte und im Feed, je Sprache: zehn Stellen fuer zwei Titel, neun
    davon Kopien. Wer die Ueberschrift aendert, aendert dann die Seite und
    laesst Browser-Reiter, WhatsApp-Vorschau und Feed auf dem alten Stand
    stehen — sichtbar genau beim Weitergeben, dem einzigen Zweck der Seite.

    Kein Ersatztitel bei fehlender Ueberschrift: eine Seite, die still
    „Titel" heisst, faellt erst auf, wenn jemand den Link teilt.
    """
    treffer = H1.search(md)
    if not treffer:
        raise ValueError("Quelldokument ohne Ueberschrift erster Ordnung")
    return treffer.group(1).strip()


def baue_seite(md: str) -> str:
    pruefe_privat(strip_kommentare(md))
    rumpf = render_markdown(md)

    # Kopf ist alles bis zur ersten Ueberschrift zweiter Ordnung.
    schnitt = rumpf.find("<h2")
    kopf, rest = (rumpf[:schnitt], rumpf[schnitt:]) if schnitt > 0 else (rumpf, "")
    rest = (_zuletzt(rumpf) + _fehlschlaege(rumpf) + _werkstatt_band(WERKSTATT_SUMME)
            + _karte(rumpf) + falte_recherche(rest) + _autor_block())

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
        .replace("{{SEITENTITEL}}", _titel_fuer_html(seiten_titel(md)))
    )
    pruefe_privat(seite)
    pruefe_extern(seite)
    return seite


# ------------------------------------------------------------- Rechtsseiten

# Von Jens am 17.08. 12:32 bestellt: „Nein Impressum und Datenschutzerklaerung
# muss rein." Die Texte stehen in `template/`, weil Prosa in Vorlagen gehoert;
# die Stammdaten stehen oben in EINER Tabelle, damit die vier Fassungen nicht
# auseinanderlaufen koennen.
RECHT_WORTE = {
    "de": {
        "impressum": ("Impressum", "Anbieterkennzeichnung",
                      "Impressum — Reisenotizen Malaysia",
                      "Pflichtangaben nach § 5 DDG."),
        "datenschutz": ("Datenschutzerklärung", "Art. 13 DSGVO",
                        "Datenschutzerklärung — Reisenotizen Malaysia",
                        "Was beim Aufruf dieser Seite mit Daten geschieht."),
        "sprache_label": "Sprache",
        "diese": "Deutsch",
        "fuss": "Stand {stand}. · <a href=\"{start}\">Zu den Reisenotizen</a> · "
                "<a href=\"{impressum}\">Impressum</a> · "
                "<a href=\"{datenschutz}\">Datenschutzerklärung</a>",
    },
    "en": {
        "impressum": ("Legal notice", "Provider identification",
                      "Legal notice — travel notes Malaysia",
                      "Mandatory details under § 5 DDG."),
        "datenschutz": ("Privacy notice", "Art. 13 GDPR",
                        "Privacy notice — travel notes Malaysia",
                        "What happens to data when you open this page."),
        "sprache_label": "Language",
        "diese": "English",
        "fuss": "Last updated {stand}. · <a href=\"{start}\">To the travel notes</a> · "
                "<a href=\"{impressum}\">Legal notice</a> · "
                "<a href=\"{datenschutz}\">Privacy notice</a>",
    },
}


def _rechtspfad(art: str, sprache: str, von: str) -> str:
    """Adresse der Rechtsseite `art`/`sprache`, relativ zur Seite `von`."""
    ziel = RECHTSSEITEN[(art, sprache)]
    if von == "en":
        return ziel[3:] if ziel.startswith("en/") else "../" + ziel
    return ziel


def rendere_recht(art: str, sprache: str = "de", stand: str = None) -> str:
    if art not in RECHTSARTEN:
        raise ValueError(art)
    heute = datetime.now(timezone.utc)
    stand = stand or (heute.strftime("%d %B %Y") if sprache == "en"
                      else heute.strftime("%d.%m.%Y"))
    andere = "en" if sprache == "de" else "de"
    worte = RECHT_WORTE[sprache]
    ueberschrift, kicker, titel, beschreibung = worte[art]

    werte = {
        "SPRACHE": sprache,
        "SPRACHE_LABEL": worte["sprache_label"],
        "TITEL": titel,
        "BESCHREIBUNG": beschreibung,
        "KICKER": kicker,
        "UEBERSCHRIFT": ueberschrift,
        "BASIS": BASIS if sprache == "de" else BASIS + "en/",
        "PFAD": Path(RECHTSSEITEN[(art, sprache)]).name,
        "FONTS": "fonts/fonts.css" if sprache == "de" else "../fonts/fonts.css",
        "CSS": (WURZEL / "template" / "site.css").read_text(encoding="utf-8"),
        "SPRACHWECHSEL": (
            f'<span aria-current="true">{worte["diese"]}</span>'
            f'<a href="{_rechtspfad(art, andere, sprache)}" hreflang="{andere}" '
            f'lang="{andere}">{RECHT_WORTE[andere]["diese"]}</a>'),
        "INHALT": (WURZEL / "template" / f"{art}.{sprache}.html").read_text(encoding="utf-8"),
        "FUSSTEXT": worte["fuss"].format(
            stand=stand,
            start="index.html",
            impressum=_rechtspfad("impressum", sprache, sprache),
            datenschutz=_rechtspfad("datenschutz", sprache, sprache)),
        "FIRMA": IMPRESSUM["firma"],
        "STRASSE": IMPRESSUM["strasse"],
        "ORT": IMPRESSUM["ort"],
        "LAND": IMPRESSUM["land"],
        "VERTRETEN": IMPRESSUM["vertreten"],
        "REGISTERGERICHT": IMPRESSUM["registergericht"],
        "REGISTERNUMMER": IMPRESSUM["registernummer"],
        "USTID": IMPRESSUM["ustid"],
        "KONTAKT": KONTAKT,
    }

    seite = RECHT_VORLAGE.read_text(encoding="utf-8")
    for platzhalter, wert in werte.items():
        seite = seite.replace("{{" + platzhalter + "}}", str(wert))
    return re.sub(r"<!--.*?-->", "", seite, flags=re.S)


# ---------------------------------------------------------------------- Feed

FEED_DATEIEN = {"de": WURZEL / "feed.xml", "en": WURZEL / "en" / "feed.xml"}
ATOM = "http://www.w3.org/2005/Atom"
# Eine urn, kein http-Link: die id eines Atom-Eintrags ist ein Name, keine
# Adresse. Zoege sie auf BASIS, muesste jeder Umzug der Seite jeden Eintrag bei
# jedem Leser neu melden.
FEED_ID_PRAEFIX = "urn:jenslaufer:malaysia:"


def _feed_meldungen(md: str) -> list[tuple[str, str, str]]:
    """(Abschnitts-Anker, Block, Telegram-Zeit) fuer jeden gemeldeten Eintrag.

    Laeuft absichtlich denselben Weg wie `render_markdown` — Marker in Token,
    dann Kommentare weg, dann an Leerzeilen trennen. Eine zweite, eigene
    Zerlegung waere nach drei Eintraegen eine zweite Wahrheit darueber, was
    ueberhaupt ein Eintrag ist.
    """
    md = MARKER_ZEIT.sub(r"@@WERKSTATT:\1@@", md)
    md = strip_kommentare(strip_marker(md))
    abschnitt, treffer = "", []
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        zeit = TOKEN.search(block)
        telegram = zeit.group(1) if zeit else None
        block = TOKEN.sub("", block).strip()
        if block.startswith("## "):
            abschnitt = slug(block[3:].strip())
        elif re.match(r"^\*\*[✓○✗]\s", block):
            treffer.append((abschnitt, block, telegram))
    return treffer


def _feed_messung(block: str, telegram: str | None) -> dict | None:
    """Dieselbe Suche wie `_spur`: erst Textanker, dann Zeitstempel."""
    daten = WERKSTATT.get(block.splitlines()[0].strip()[:ANKER_LAENGE])
    if daten is None and telegram:
        daten = WERKSTATT.get(_tg_schluessel(telegram))
    if not daten or not daten.get("veroeffentlicht") or not daten.get("telegram"):
        return None
    return daten


def _feed_titel(block: str) -> str:
    """Der fette Vorspann eines Eintrags ist seine Ueberschrift."""
    treffer = re.match(r"^\*\*[✓○✗]\s+(.*?)\*\*", block, flags=re.S)
    rohtext = treffer.group(1) if treffer else block
    return re.sub(r"\s+", " ", rohtext.replace("*", "").replace("`", "")).strip()


def baue_feed(md: str) -> str | None:
    """Atom-Feed der gemeldeten Eintraege — oder None, wenn nichts gemessen ist.

    Auftrag Jens 2026-08-17 10:43: "Können wir Website Notifications einstellen,
    so dass Leute über Neuerungen informiert werden?" Browser-Push scheidet aus
    (auf dem iPhone nur ueber Seite-auf-Startbildschirm, und es braucht einen
    Server, den diese Seite nicht hat). Atom braucht beides nicht.

    **Nur gemessene Eintraege.** Ein Eintrag ohne Messung haette kein Datum, und
    ein erfundenes waere schlimmer als sein Fehlen: der Leser bekaeme eine
    Meldung ueber etwas, das nicht passiert ist. Recherche steht deshalb auf der
    Seite und nicht im Feed — was gemeldet wird, ist, was Jens erlebt hat.

    **Ohne jede Messung wird nichts geschrieben** (None). Ein leerer Feed sieht
    aus wie eine ruhige Woche und ist ein Ausfall; die alte Datei bleibt dann
    stehen und luegt wenigstens nicht neu.

    Gebaut wird ueber ElementTree, nicht aus Zeichenketten: ein `&` im Text
    zerreisst handgeschriebenes XML, und ein zerrissener Feed faellt bei jedem
    Leser gleichzeitig aus, ohne dass hier etwas rot wird.
    """
    pruefe_privat(strip_kommentare(md))

    eintraege, belegt = [], {}
    for abschnitt, block, telegram in _feed_meldungen(md):
        daten = _feed_messung(block, telegram)
        if not daten:
            continue
        # Eine Nachricht kann mehrere Eintraege ausgeloest haben (drei Fotos um
        # 10:21 am 17.08.). Der Zaehler laeuft deshalb je Paar aus Zeit und
        # Abschnitt, nicht ueber das ganze Dokument: sonst verschiebt jede
        # Umsortierung an einer anderen Stelle die ids hier mit.
        schluessel = (_tg_schluessel(daten["telegram"]), abschnitt)
        belegt[schluessel] = belegt.get(schluessel, 0) + 1
        kennung = FEED_ID_PRAEFIX + f"{schluessel[0]}:{abschnitt}"
        if belegt[schluessel] > 1:
            kennung += f":{belegt[schluessel]}"
        eintraege.append((daten, abschnitt, block, kennung))
    if not eintraege:
        return None
    eintraege.sort(key=lambda e: e[0]["veroeffentlicht"], reverse=True)

    seite = BASIS + ("en/" if SPRACHE == "en" else "")
    ET.register_namespace("", ATOM)
    feed = ET.Element(f"{{{ATOM}}}feed")
    feed.set("{http://www.w3.org/XML/1998/namespace}lang", SPRACHE)
    ET.SubElement(feed, f"{{{ATOM}}}title").text = seiten_titel(md)
    ET.SubElement(feed, f"{{{ATOM}}}subtitle").text = _t(
        # Echte Umlaute: dieser Satz steht in jedem Leseprogramm sichtbar da.
        # Die ASCII-Schreibweise ist ein Reflex aus dem Quelltext und war am
        # 17.08. schon einmal der erste sichtbare Schnitzer auf der Seite.
        "Neue Einträge, sobald sie auf der Seite stehen.",
        "New entries, the moment they go live.",
    )
    ET.SubElement(feed, f"{{{ATOM}}}id").text = f"{FEED_ID_PRAEFIX}feed:{SPRACHE}"
    ET.SubElement(feed, f"{{{ATOM}}}link", rel="alternate", type="text/html", href=seite)
    ET.SubElement(feed, f"{{{ATOM}}}link", rel="self",
                  type="application/atom+xml", href=seite + "feed.xml")
    ET.SubElement(feed, f"{{{ATOM}}}updated").text = eintraege[0][0]["veroeffentlicht"]
    ET.SubElement(ET.SubElement(feed, f"{{{ATOM}}}author"),
                  f"{{{ATOM}}}name").text = "Jens Laufer"

    for daten, abschnitt, block, kennung in eintraege:
        eintrag = ET.SubElement(feed, f"{{{ATOM}}}entry")
        ET.SubElement(eintrag, f"{{{ATOM}}}title").text = _feed_titel(block)
        ET.SubElement(eintrag, f"{{{ATOM}}}link", rel="alternate", type="text/html",
                      href=seite + (f"#{abschnitt}" if abschnitt else ""))
        # Die id haengt am Zeitstempel der Nachricht und am Abschnitt, nie am
        # Text. Ein Schluessel aus dem Inhalt bricht, sobald der Inhalt sich
        # aendert — auf der Seite kostete das am 17.08. die Herkunftszeile der
        # englischen Fassung, im Feed waere es teurer: neue id heisst fuer jeden
        # Leser "neuer Beitrag", ein korrigierter Tippfehler meldete denselben
        # Eintrag ein zweites Mal. Der Abschnitt muss mit hinein, weil eine
        # Nachricht mehrere Eintraege ausloesen kann und zwei gleiche ids den
        # zweiten Eintrag bei JEDEM Leser verschwinden lassen.
        ET.SubElement(eintrag, f"{{{ATOM}}}id").text = kennung
        ET.SubElement(eintrag, f"{{{ATOM}}}updated").text = daten["veroeffentlicht"]
        ET.SubElement(eintrag, f"{{{ATOM}}}published").text = daten["telegram"]
        inhalt = ET.SubElement(eintrag, f"{{{ATOM}}}content", type="html")
        inhalt.text = f"<p>{inline(block)}</p>"

    xml = ET.tostring(feed, encoding="unicode", xml_declaration=True)
    pruefe_privat(xml)
    return xml


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
        except (PrivatException, ExternException) as e:
            print(f"ABBRUCH ({sprache}) — {e}", file=sys.stderr)
            print("Nichts geschrieben. Den Satz im Quelldokument entfernen.", file=sys.stderr)
            return 1
        if KARTE_SUMME:
            print(
                f"Karte ({sprache}): {KARTE_SUMME['verortet']} von "
                f"{KARTE_SUMME['erlebt']} Erlebnissen an "
                f"{KARTE_SUMME['stationen']} Stationen"
            )
        namen = warne_namen(seiten[sprache])
        if namen:
            print(
                f"ACHTUNG ({sprache}): Namen aus der Warnliste stehen auf der "
                "oeffentlichen Seite: " + ", ".join(namen)
                + ". Kein Abbruch — wer hier vorkommt, entscheidet Jens.",
                file=sys.stderr,
            )

    # Impressum und Datenschutzerklaerung laufen durch dieselben zwei
    # Waechter wie die Hauptseiten. Ein zweiter Ausgang ohne eigene Pruefung
    # halbiert sie — genau der Fehler, der beim Feed auf dieser Seite schon
    # einmal aufgetreten ist.
    stand = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recht = {}
    for art in RECHTSARTEN:
        for sprache in SPRACHEN:
            try:
                html = rendere_recht(art, sprache, stand)
                pruefe_privat(html)
                pruefe_extern(html)
            except (PrivatException, ExternException) as e:
                print(f"ABBRUCH ({art}/{sprache}) — {e}", file=sys.stderr)
                print("Nichts geschrieben.", file=sys.stderr)
                return 1
            recht[(art, sprache)] = html

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

    for (art, sprache), html in recht.items():
        pfad = WURZEL / RECHTSSEITEN[(art, sprache)]
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(html, encoding="utf-8")
        print(f"gebaut: {pfad} ({pfad.stat().st_size:,} Bytes)")

    # Der Feed wird NACH der Seite geschrieben und nur, wenn es etwas zu
    # melden gibt. Ohne Messung bleibt die alte Datei stehen: ein leerer
    # Feed sieht bei jedem Leser aus wie eine ruhige Woche.
    #
    # Eigene Schleife, seit dem 22.08.: der Block hing eine Ebene tiefer in
    # der Schleife ueber die Rechtsseiten und lief deshalb viermal statt
    # zweimal — sichtbar nur als doppelte Zeile in der Bauausgabe, weil
    # zweimal dieselben Bytes geschrieben wurden. Der Preis waere erst beim
    # naechsten Umbau faellig geworden: haengt der Feed an RECHTSARTEN, wird
    # er gar nicht mehr geschrieben, sobald dort etwas anderes steht — und
    # eine nicht geschriebene Datei bleibt als alte Datei erreichbar.
    for sprache in SPRACHEN:
        SPRACHE = sprache
        xml = baue_feed(quellen[sprache])
        feed_datei = FEED_DATEIEN[sprache]
        if xml:
            feed_datei.parent.mkdir(parents=True, exist_ok=True)
            feed_datei.write_text(xml, encoding="utf-8")
            anzahl = xml.count("<entry>")
            print(f"gebaut: {feed_datei} ({anzahl} Meldungen, "
                  f"{feed_datei.stat().st_size:,} Bytes)")
        else:
            print(f"feed.xml ({sprache}) NICHT geschrieben — keine Messung. "
                  "Die alte Datei bleibt stehen.", file=sys.stderr)

    # Sitemap. Grund, am 17.08. bei Google selbst gemessen: die Search-Console
    # meldet fuer beide Sprachfassungen `URL is unknown to Google` — die Seite
    # liegt in einem eigenen Repo und stand deshalb in keiner sitemap der Domain.
    # Ohne einen Weg dorthin holt Google sie nicht ab, wie gut der Text auch ist.
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for adresse in (BASIS, BASIS + "en/"):
        sm.append(f"  <url><loc>{adresse}</loc>"
                  f"<lastmod>{datetime.now(timezone.utc):%Y-%m-%d}</lastmod></url>")
    sm.append("</urlset>")
    (WURZEL / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    print(f"gebaut: sitemap.xml ({len(sm) - 3} Adressen)")

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
