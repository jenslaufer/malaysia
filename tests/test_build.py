#!/usr/bin/env python3
"""Tests fuer build.py — die Seite malaysia.jenslaufer.com.

Zwei Sorten Test, und die zweite ist die wichtigere:

1. Rendert der Generator, was im Markdown steht?
2. Kommt garantiert NICHTS raus, was privat ist? Die Seite geht an Fremde.
   Jens' Auftrag (2026-08-17): "private info must hidden there (eg passport
   numbers etc)". Ein Datenschutz-Versprechen, das nur im Kopf des Autors
   existiert, haelt genau bis zur ersten Sitzung, die es nicht gelesen hat.

Lauf: python3 tests/test_build.py
"""

import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build  # noqa: E402


class TestMarks(unittest.TestCase):
    """Das Zeichen ist das Produkt. Wenn es verrutscht, ist die Seite wertlos."""

    def test_erlebt_wird_zu_eigener_klasse(self):
        html = build.render_markdown("**✓ Im Bus geht kontaktlos (17.08.).** Ohne Vorbereitung.")
        self.assertIn('class="entry entry--erlebt"', html)
        self.assertIn("Im Bus geht kontaktlos", html)

    def test_nachgeschlagen_wird_zu_eigener_klasse(self):
        html = build.render_markdown("**○ Wechselstube schlägt Geldautomat.** Wegen der Gebühr.")
        self.assertIn('class="entry entry--recherche"', html)

    def test_gescheitert_wird_zu_eigener_klasse(self):
        html = build.render_markdown("**✗ CelcomDigi ließ sich online nicht kaufen.** Abbruch.")
        self.assertIn('class="entry entry--gescheitert"', html)

    def test_zeichen_steht_im_rail_nicht_mehr_im_fliesstext(self):
        html = build.render_markdown("**✓ Etwas hat geklappt.** Dazu ein Satz.")
        self.assertIn('<span class="mark" aria-hidden="true">✓</span>', html)
        self.assertNotIn("<strong>✓", html)

    def test_zeichen_bekommt_lesbare_beschriftung_fuer_screenreader(self):
        html = build.render_markdown("**✓ Etwas hat geklappt.** Dazu ein Satz.")
        self.assertIn("selbst erlebt", html)

    def test_absatz_ohne_zeichen_bleibt_normaler_absatz(self):
        html = build.render_markdown("Ein ganz normaler Absatz ohne Zeichen.")
        self.assertIn("<p>Ein ganz normaler Absatz", html)
        self.assertNotIn("entry--", html)

    def test_offene_punkte_werden_als_offen_markiert(self):
        html = build.render_markdown("**Offen, kommt noch:** ob Karte auf der Fähre geht.")
        self.assertIn('class="entry entry--offen"', html)


class TestStruktur(unittest.TestCase):
    def test_h1_und_h2(self):
        html = build.render_markdown("# Titel\n\n## Abschnitt")
        self.assertIn("<h1", html)
        self.assertIn("<h2", html)

    def test_abschnitt_bekommt_id_zum_verlinken(self):
        html = build.render_markdown("## Grenze Singapur → Malaysia")
        self.assertIn('id="grenze-singapur-malaysia"', html)

    def test_tabelle_wird_tabelle(self):
        md = "| Datum | Wo |\n|---|---|\n| 15.08. | Frankfurt |"
        html = build.render_markdown(md)
        self.assertIn("<table", html)
        self.assertIn("<th>Datum</th>", html)
        self.assertIn("<td>15.08.</td>", html)

    def test_liste_wird_liste(self):
        html = build.render_markdown("- erster Punkt\n- zweiter Punkt")
        self.assertIn("<ul", html)
        self.assertEqual(html.count("<li"), 2)

    def test_code_bleibt_code(self):
        html = build.render_markdown("Adresse `imigresen-online.imi.gov.my` eintippen.")
        self.assertIn("<code>imigresen-online.imi.gov.my</code>", html)

    def test_html_kommentar_erreicht_die_seite_nie(self):
        """Der Pflegeblock am Fuss des Quelldokuments ist interne Anweisung."""
        md = "Sichtbar.\n\n<!--\nPFLEGE: interne Notiz, geht niemanden an.\n-->"
        html = build.render_markdown(md)
        self.assertIn("Sichtbar.", html)
        self.assertNotIn("PFLEGE", html)
        self.assertNotIn("interne Notiz", html)

    def test_spitze_klammern_im_text_werden_escaped(self):
        html = build.render_markdown("Ein <script>alert(1)</script> im Text.")
        self.assertNotIn("<script>", html)


class TestDatenschutz(unittest.TestCase):
    """Der Generator schreibt lieber gar nichts als etwas Privates."""

    def test_passnummer_stoppt_den_build(self):
        with self.assertRaises(build.PrivatException):
            build.pruefe_privat("Reisepass C01X00T47 vorlegen.")

    def test_iban_stoppt_den_build(self):
        with self.assertRaises(build.PrivatException):
            build.pruefe_privat("Konto DE57 3701 0050 0000 3995 09 nutzen.")

    def test_email_adresse_stoppt_den_build(self):
        with self.assertRaises(build.PrivatException):
            build.pruefe_privat("Schreib an carlotte@amazingborneo.com.")

    def test_telefonnummer_stoppt_den_build(self):
        with self.assertRaises(build.PrivatException):
            build.pruefe_privat("Anruf unter +60 88 448 409 genuegt.")

    def test_gesperrtes_wort_stoppt_den_build(self):
        """Codes und Namen faengt kein Muster — dafuer gibt es die Liste.
        Sie liegt ausserhalb dieses public-Repos, deshalb wird sie hier
        fuer den Test gesetzt statt importiert."""
        vorher = build.GEHEIME_TOKEN
        build.GEHEIME_TOKEN = ["gesperrtesbeispiel"]
        try:
            with self.assertRaises(build.PrivatException):
                build.pruefe_privat("PIN GesperrtesBeispiel vorzeigen.")
        finally:
            build.GEHEIME_TOKEN = vorher

    def test_sperrliste_liegt_nicht_in_diesem_repo(self):
        """Eine Sperrliste im public-Repo veroeffentlicht, was sie schuetzt —
        genau so lag die MDAC-PIN am 17.08. hier im Klartext."""
        self.assertNotIn(str(Path(__file__).resolve().parent.parent), str(build.SPERRLISTE))

    def test_fehlende_sperrliste_bricht_ab(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(build.PrivatException):
                build.lade_sperrliste(Path(tmp) / "weg.txt")

    def test_die_fehlermeldung_nennt_den_fund(self):
        try:
            build.pruefe_privat("Mail an carlotte@amazingborneo.com.")
        except build.PrivatException as e:
            self.assertIn("carlotte@amazingborneo.com", str(e))
        else:
            self.fail("keine Exception")

    def test_harmloser_text_laeuft_durch(self):
        build.pruefe_privat("Der Bus von JB Sentral nach Larkin nimmt Google Pay.")

    def test_uhrzeit_ist_keine_telefonnummer(self):
        build.pruefe_privat("Die Wechselstube hat 10:00–20:00 geöffnet.")

    def test_gebuehr_ist_keine_passnummer(self):
        build.pruefe_privat("RM105 Marine-Park-Gebühr, dazu RM60 Touristensteuer.")

    def test_datum_ist_keine_iban(self):
        build.pruefe_privat("Grab fährt seit dem 04.05.2026 über die Grenze.")

    def test_echtes_dokument_ist_sauber(self):
        """Die Positivkontrolle: das reale Quelldokument muss durchlaufen."""
        quelle = Path(__file__).resolve().parent.parent / "content" / "erfahrungen.md"
        if not quelle.exists():
            self.skipTest("content/erfahrungen.md fehlt")
        build.pruefe_privat(build.strip_kommentare(quelle.read_text(encoding="utf-8")))


class TestSeite(unittest.TestCase):
    def setUp(self):
        self.seite = build.baue_seite("# Titel\n\n## Erstes\n\n**✓ Etwas (17.08.).** Text.")

    def test_deutsch_ausgezeichnet(self):
        self.assertIn('lang="de"', self.seite)

    def test_utf8_und_viewport(self):
        self.assertIn('charset="utf-8"', self.seite)
        self.assertIn("viewport", self.seite)

    def test_css_ist_eingebettet_kein_zweiter_request(self):
        self.assertIn("<style>", self.seite)
        self.assertNotIn('rel="stylesheet" href="assets', self.seite)

    def test_karte_ist_drin(self):
        self.assertIn("id=\"karte\"", self.seite)
        self.assertIn("leaflet", self.seite.lower())

    def test_karte_hat_alle_stationen(self):
        for ort in ("Singapur", "Johor Bahru", "Mersing", "Tioman",
                    "Kuala Lumpur", "Sandakan", "Kota Kinabalu", "Kudat"):
            self.assertIn(ort, self.seite, f"Station fehlt auf der Karte: {ort}")

    def test_keine_karte_ohne_javascript_bleibt_erklaert(self):
        """Ohne JS ist die Karte leer — dann muss dastehen, warum."""
        self.assertIn("<noscript>", self.seite)

    def test_inhaltsverzeichnis_verlinkt_die_abschnitte(self):
        self.assertIn('href="#erstes"', self.seite)

    def test_stand_datum_steht_drauf(self):
        self.assertIn("Stand", self.seite)


class TestWerkstattSpur(unittest.TestCase):
    """Die Herkunftsspur ist die Verbindung zu /harry/.

    Sie behauptet oeffentlich eine Reaktionszeit. Jede Art, sie zu schoenen oder
    stillschweigend zu verlieren, gehoert deshalb unter einen roten Test — und
    die teuerste ist die stille: ein Marker, der nicht gefunden wird, laesst den
    Eintrag einfach ohne Spur stehen und faellt niemandem auf.
    """

    MD = (
        "**✓ Im Fernbus sitzt eine USB-Buchse (17.08.).** Zwei Anschluesse.\n"
        "<!-- werkstatt: telegram=2026-08-17T06:21 -->"
    )
    SPUR = {
        "**✓ Im Fernbus sitzt eine USB-Buchse (17.08.).** Zwei Anschl": {
            "telegram": "2026-08-17T06:21:00+00:00",
            "veroeffentlicht": "2026-08-17T06:38:00+00:00",
            "minuten": 17,
        }
    }

    def setUp(self):
        self._alt = build.WERKSTATT
        build.WERKSTATT = dict(self.SPUR)

    def tearDown(self):
        build.WERKSTATT = self._alt

    def test_spur_wird_unter_den_eintrag_gerendert(self):
        html = build.render_markdown(self.MD)
        self.assertIn('class="spur"', html)
        self.assertIn("17", html)

    def test_marker_erreicht_die_seite_nie_als_text(self):
        # Ein durchgereichter HTML-Kommentar waere im Quelltext der Seite
        # sichtbar und die Zeit dort ungerahmt lesbar.
        html = build.render_markdown(self.MD)
        self.assertNotIn("werkstatt:", html)
        self.assertNotIn("<!--", html)

    def test_eintrag_ohne_spur_bekommt_keine_leere_zeile(self):
        html = build.render_markdown("**✓ Etwas anderes.** Ohne Marker.")
        self.assertNotIn('class="spur"', html)

    def test_zeichen_und_text_bleiben_trotz_marker_intakt(self):
        html = build.render_markdown(self.MD)
        self.assertIn('class="entry entry--erlebt"', html)
        self.assertIn("Zwei Anschluesse", html)
        self.assertIn('<span class="mark" aria-hidden="true">✓</span>', html)

    def test_pflegeblock_wird_weiter_entfernt(self):
        html = build.render_markdown(
            self.MD + "\n\n<!--\nPFLEGE - interner Block.\n-->\n"
        )
        self.assertNotIn("PFLEGE", html)

    def test_ungemessener_eintrag_zeigt_keine_zahl(self):
        # Fehlt die Veroeffentlichung, waere "0 Minuten" die schnellste Zahl der
        # Seite und hiesse in Wahrheit "nicht gemessen".
        build.WERKSTATT = {
            k: {**v, "veroeffentlicht": None, "minuten": None}
            for k, v in self.SPUR.items()
        }
        html = build.render_markdown(self.MD)
        self.assertNotIn('class="spur"', html)


class TestWerkstattBand(unittest.TestCase):
    """Das Band erklaert dem Leser, wie die Seite entsteht, und verlinkt /harry/."""

    def test_band_nennt_zahlen_aus_der_messung(self):
        html = build._werkstatt_band(
            {"gemessen": 5, "median_minuten": 66, "juengste_minuten": 17}
        )
        self.assertIn("5", html)
        self.assertIn("66", html)
        self.assertIn("17", html)

    def test_band_verlinkt_die_harness_seite(self):
        html = build._werkstatt_band(
            {"gemessen": 5, "median_minuten": 66, "juengste_minuten": 17}
        )
        self.assertIn("/harry/", html)

    def test_ohne_messung_kein_band_statt_band_mit_nullen(self):
        # Lieber gar keine Aussage als "Median 0 Minuten".
        self.assertEqual(
            build._werkstatt_band({"gemessen": 0, "median_minuten": None,
                                   "juengste_minuten": None}),
            "",
        )

    def test_band_steht_auf_der_gebauten_seite(self):
        seite = build.baue_seite(
            "# Titel\n\nVorspann.\n\n## Erstes\n\n"
            "**✓ Etwas hat geklappt (17.08.).** Dazu ein Satz.\n"
            "<!-- werkstatt: telegram=2026-08-17T06:21 -->\n"
        )
        self.assertIn("/harry/", seite)


class TestAutorblock(unittest.TestCase):
    """Der Block am Fuss sagt, wer die Seite schreibt und was er beruflich macht.

    Zwei Leser, ein Block. Wer die Reise liest, will wissen, wem er die Haken
    glaubt. Wer wissen will, wie die Seite entsteht, findet hier den Beruf, der
    dahintersteckt — und der ist der Grund, warum es diese Seite gibt.

    Was hier NICHT hingehoert: Preise. Diese Seite geht an Freunde und an Leute,
    die nach dem Weg zur Larkin-Busstation suchen. Ein Tagessatz zwischen
    Faehrzeiten wuerde den Rest der Seite entwerten. Er steht auf /harry/.
    """

    def test_block_nennt_beide_rollen(self):
        html = build._autor_block()
        self.assertIn("Forward Deployed Engineer", html)
        self.assertIn("Harness Engineer", html)

    def test_block_nennt_keinen_preis(self):
        html = build._autor_block()
        self.assertNotIn("€", html)
        self.assertNotIn("Tagessatz", html)

    def test_block_verlinkt_die_harness_seite(self):
        self.assertIn("/harry/", build._autor_block())

    def test_block_steht_auf_der_gebauten_seite(self):
        seite = build.baue_seite("# Titel\n\nVorspann.\n\n## Erstes\n\nEin Satz.\n")
        self.assertIn("Forward Deployed Engineer", seite)

    def test_block_steht_auch_ohne_messung_auf_der_seite(self):
        # Das Werkstatt-Band faellt nach der Reise weg. Wer die Seite geschrieben
        # hat, bleibt trotzdem eine Auskunft, die der Leser braucht.
        vorher = build.WERKSTATT_SUMME
        build.WERKSTATT_SUMME = {}
        try:
            seite = build.baue_seite("# Titel\n\nVorspann.\n\n## Erstes\n\nEin Satz.\n")
        finally:
            build.WERKSTATT_SUMME = vorher
        self.assertIn("Forward Deployed Engineer", seite)


class TestVorschaubild(unittest.TestCase):
    """Geteilt wird die Vorschaukarte, nicht die Seite.

    Ein Link ohne Bild ist in Telegram, WhatsApp und LinkedIn eine graue Zeile.
    Ein og:image-Tag ohne Datei ist schlimmer als keins: die Vorschau bleibt
    leer, und niemand sieht nach, warum.
    """

    def test_seite_verweist_auf_ein_vorschaubild(self):
        seite = build.baue_seite("# Titel\n\nVorspann.\n\n## Erstes\n\nEin Satz.\n")
        self.assertIn('property="og:image"', seite)
        self.assertIn("og.png", seite)

    def test_bild_liegt_wirklich_im_repo(self):
        bild = build.WURZEL / "og.png"
        self.assertTrue(bild.exists(), "og:image ist ausgezeichnet, aber og.png fehlt")
        self.assertGreater(bild.stat().st_size, 5000, "og.png ist verdaechtig klein")

    def test_adresse_ist_absolut(self):
        # Ein relativer Pfad im og:image wird von keinem Vorschau-Dienst geladen.
        seite = build.baue_seite("# Titel\n\nVorspann.\n\n## Erstes\n\nEin Satz.\n")
        treffer = re.search(r'property="og:image" content="([^"]+)"', seite)
        self.assertIsNotNone(treffer)
        self.assertTrue(treffer.group(1).startswith("https://"))

    def test_karte_traegt_keine_erfundene_zahl(self):
        # Ohne Messung darf auf der Karte keine Minutenzahl stehen.
        karte = build._og_karte({})
        self.assertNotIn("Minuten", karte)


class TestEchteUmlaute(unittest.TestCase):
    """Auf der Seite stehen echte Umlaute, nie die ASCII-Umschrift.

    Der Fehler ist ein Werkzeug-Reflex aus dem Python-Quelltext und faellt beim
    Lesen kaum auf — "prueft" liest sich fast wie "prueft". Auf einer deutschen
    Seite, die als Arbeitsprobe dient, ist es der erste sichtbare Schnitzer.
    Gefunden am 17.08. im Werkstatt-Band, nachdem die Seite gerendert wurde.
    """

    UMSCHRIFT = [
        "prueft", "traegt", "laeuft", "veroeffentlich", "geschaetzt",
        "waehrend", "fuer ", "ueber ", "koennen", "muessen", "naechste",
        "gepruef", "haelt", "faehrt", "gehoert",
    ]

    @staticmethod
    def sichtbar(seite: str) -> str:
        """Nur was der Leser sieht. CSS- und JS-Kommentare zaehlen nicht.

        Der erste Entwurf dieses Tests pruefte das ganze Dokument und schlug an
        einem Kommentar im Stylesheet an — also an Text, den niemand liest. Ein
        Test, der am falschen Ort misst, wird abgeschaltet statt befolgt.
        """
        ohne = re.sub(r"<(style|script)\b.*?</\1>", " ", seite, flags=re.S | re.I)
        ohne = re.sub(r"<!--.*?-->", " ", ohne, flags=re.S)
        return re.sub(r"<[^>]+>", " ", ohne).lower()

    def test_gebaute_seite_hat_keine_ascii_umschrift(self):
        seite = build.baue_seite(
            "# Titel\n\nVorspann.\n\n## Erstes\n\n"
            "**✓ Etwas hat geklappt (17.08.).** Dazu ein Satz.\n"
            "<!-- werkstatt: telegram=2026-08-17T06:21 -->\n"
        )
        klein = self.sichtbar(seite)
        for wort in self.UMSCHRIFT:
            self.assertNotIn(wort, klein, f"ASCII-Umschrift auf der Seite: {wort!r}")

    def test_echtes_dokument_hat_keine_ascii_umschrift(self):
        """Positivkontrolle am wirklich ausgelieferten Text, nicht am Beispiel."""
        klein = self.sichtbar(build.ZIEL.read_text(encoding="utf-8"))
        for wort in self.UMSCHRIFT:
            self.assertNotIn(wort, klein, f"ASCII-Umschrift auf der Seite: {wort!r}")

    def test_band_hat_keine_ascii_umschrift(self):
        klein = build._werkstatt_band(
            {"gemessen": 5, "median_minuten": 66, "juengste_minuten": 17}
        ).lower()
        for wort in self.UMSCHRIFT:
            self.assertNotIn(wort, klein, f"ASCII-Umschrift im Band: {wort!r}")



class TestZweisprachig(unittest.TestCase):
    """Der Reisebericht auf Englisch — dieselbe Messung, zweite Quelldatei.

    Die Gefahr ist nicht die Uebersetzung, sondern ihr Altern: die englische
    Fassung ist die, die Jens nicht liest, also faellt ihr Rueckstand niemandem
    auf. Deshalb misst der Build die Deckung und meldet sie laut.
    """

    DE = """# Titel

Vorspann.

## Bezahlen

**✓ Im Bus geht kontaktlos (17.08.).** Ein Satz.
<!-- werkstatt: telegram=2026-08-17T04:41 -->

**○ Bargeld bleibt Pflicht.** Noch ein Satz.

## Grenze

**✗ Ging nicht.** Dritter Satz.
"""

    EN = """# Title

Intro.

## Paying

**✓ Contactless works on the bus (17 Aug).** One sentence.
<!-- werkstatt: telegram=2026-08-17T04:41 -->

**○ Cash is still compulsory.** Another sentence.

## Border

**✗ Did not work.** Third sentence.
"""

    def setUp(self):
        self.vorher = build.SPRACHE
        self.werkstatt = build.WERKSTATT

    def tearDown(self):
        build.SPRACHE = self.vorher
        build.WERKSTATT = self.werkstatt

    def test_sprache_steuert_die_zeichenerklaerung(self):
        build.SPRACHE = "de"
        self.assertIn("selbst erlebt", build.render_markdown(self.DE))
        build.SPRACHE = "en"
        self.assertIn("we did it ourselves", build.render_markdown(self.EN))

    def test_englische_seite_traegt_die_deutsche_messung(self):
        # Die Herkunftszeile haengt an der Uhrzeit der Telegram-Nachricht, nicht
        # am Text: der englische Absatz hat einen anderen Anker, und ueber den
        # Anker gefunden wuerde er nichts finden — still.
        build.WERKSTATT = {
            "2026-08-17T04:41:00+00:00": {
                "minuten": 66,
                "telegram": "2026-08-17T04:41:00+00:00",
                "veroeffentlicht": "2026-08-17T05:46:51+00:00",
            }
        }
        build.SPRACHE = "en"
        rumpf = build.render_markdown(self.EN)
        self.assertIn("66", rumpf)
        self.assertIn("min", rumpf)

    def test_deckung_meldet_fehlende_abschnitte(self):
        fehlt = self.EN.replace("## Border\n\n**✗ Did not work.** Third sentence.\n", "")
        luecken = build.pruefe_deckung(self.DE, fehlt)
        self.assertTrue(luecken, "fehlender Abschnitt wurde nicht gemeldet")

    def test_deckung_schweigt_bei_gleichstand(self):
        self.assertEqual(build.pruefe_deckung(self.DE, self.EN), [])

    def test_englische_seite_hat_keine_deutschen_reste(self):
        build.SPRACHE = "en"
        seite = build.baue_seite(self.EN)
        sichtbar = re.sub(r"<(style|script)\b.*?</\1>", " ", seite, flags=re.S | re.I)
        sichtbar = re.sub(r"<!--.*?-->", " ", sichtbar, flags=re.S)
        sichtbar = re.sub(r"<[^>]+>", " ", sichtbar).lower()
        for muster in (r"\bund\b", r"\bnicht\b", r"\bsind\b", r"\bwir\b",
                       r"selbst erlebt", r"nachgeschlagen", r"reisenotizen",
                       r"die route", r"meldungen"):
            self.assertIsNone(re.search(muster, sichtbar),
                              f"deutscher Rest auf der englischen Seite: {muster}")

    def test_englische_seite_zeigt_auf_die_deutsche(self):
        build.SPRACHE = "en"
        en = build.baue_seite(self.EN)
        self.assertIn('hreflang="de"', en)
        self.assertIn(f'rel="canonical" href="{build.BASIS}en/"', en)
        build.SPRACHE = "de"
        de = build.baue_seite(self.DE)
        self.assertIn('hreflang="en"', de)
        self.assertIn(f'rel="canonical" href="{build.BASIS}"', de)

    def test_privatpruefung_gilt_auch_englisch(self):
        build.SPRACHE = "en"
        with self.assertRaises(build.PrivatException):
            build.baue_seite(self.EN + "\n\nWrite to jens@example.com.\n")


class TestFotos(unittest.TestCase):
    """Ein Foto ist der Beleg hinter einem Haken — und die groesste Leckstelle.

    Der Textwaechter `pruefe_privat` liest Text. Eine JPEG-Datei traegt ihre
    Standortdaten im EXIF-Block, und der steht in keinem Satz: eine Datei mit
    GPS-Koordinaten laeuft an jeder Textpruefung vorbei und ist auf der
    gerenderten Seite unsichtbar. Genau die Sorte Fehler, die erst auffaellt,
    wenn sie nicht mehr ruecknehmbar ist.
    """

    def setUp(self):
        build.SPRACHE = "de"
        self.tmp = tempfile.mkdtemp()
        self.quelle = Path(self.tmp) / "quelle"
        self.ziel = Path(self.tmp) / "fotos"
        self.quelle.mkdir()
        self.ziel.mkdir()
        self._alt = (build.FOTO_QUELLE, build.FOTO_ZIEL, dict(build.FOTO_DATEN))
        build.FOTO_QUELLE, build.FOTO_ZIEL = self.quelle, self.ziel
        build.FOTO_DATEN = {}

    def tearDown(self):
        build.FOTO_QUELLE, build.FOTO_ZIEL, build.FOTO_DATEN = self._alt
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _jpeg(self, name="bild.jpg", groesse=(1600, 900), gps=False):
        """Ein Testfoto, auf Wunsch mit Standortdaten im EXIF."""
        bild = Image.new("RGB", groesse)
        for x in range(groesse[0]):  # Verlauf, damit Weichzeichnen messbar ist
            for y in range(0, groesse[1], 4):
                bild.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, 90))
        exif = Image.Exif()
        if gps:
            # Mersing, ungefaehr — genau der Wert, der nie oeffentlich werden darf.
            exif[0x8825] = {1: "N", 2: (2.0, 25.0, 52.0),
                            3: "E", 4: (103.0, 50.0, 26.0)}
            exif[0x010F] = "TestPhone"
        pfad = self.quelle / name
        bild.save(pfad, "JPEG", exif=exif)
        return pfad

    # ------------------------------------------------------- Der Datenschutz

    def test_standortdaten_erreichen_die_seite_nicht(self):
        """Das eigentliche Versprechen. Faellt der Test, faellt der Rest egal aus."""
        self._jpeg("mit-gps.jpg", gps=True)
        with Image.open(self.quelle / "mit-gps.jpg") as vorher:
            self.assertTrue(vorher.getexif().get_ifd(0x8825),
                            "die Vorlage muss GPS tragen, sonst prueft der Test nichts")
        ziel = build.verarbeite_foto("mit-gps.jpg")
        with Image.open(ziel) as nachher:
            self.assertFalse(nachher.getexif().get_ifd(0x8825), "GPS im Ausgabebild")
            self.assertFalse(dict(nachher.getexif()), "EXIF im Ausgabebild")

    def test_kein_bild_wird_roh_durchgereicht(self):
        """Kopieren wuerde EXIF mitkopieren. Es muss neu geschrieben werden."""
        quelle = self._jpeg("roh.jpg", gps=True)
        ziel = build.verarbeite_foto("roh.jpg")
        self.assertNotEqual(quelle.read_bytes(), ziel.read_bytes())

    def test_gesperrte_stellen_werden_unkenntlich(self):
        """Kfz-Kennzeichen Fremder. Relative Koordinaten, damit sie das
        Verkleinern ueberleben — absolute Pixel zeigen nach dem Skalieren
        woanders hin, und zwar lautlos."""
        self._jpeg("kennzeichen.jpg")
        build.FOTO_DATEN = {"kennzeichen.jpg": {"blur": [[0.25, 0.5, 0.2, 0.1]]}}
        ziel = build.verarbeite_foto("kennzeichen.jpg")
        with Image.open(ziel) as bild:
            b, h = bild.size
            innen = bild.crop((int(0.30 * b), int(0.55 * h), int(0.40 * b), int(0.58 * h)))
            aussen = bild.crop((int(0.70 * b), int(0.55 * h), int(0.80 * b), int(0.58 * h)))
        self.assertLess(self._streuung(innen), self._streuung(aussen) / 2,
                        "der gesperrte Bereich ist nicht weichgezeichnet")

    @staticmethod
    def _streuung(bild) -> float:
        werte = list(bild.convert("L").getdata())
        mittel = sum(werte) / len(werte)
        return (sum((w - mittel) ** 2 for w in werte) / len(werte)) ** 0.5

    def test_ohne_sperrliste_bleibt_das_bild_unveraendert_scharf(self):
        """Gegenprobe: der Weichzeichner darf nicht immer anspringen."""
        self._jpeg("scharf.jpg")
        ziel = build.verarbeite_foto("scharf.jpg")
        with Image.open(ziel) as bild:
            b, h = bild.size
            aus = bild.crop((int(0.30 * b), int(0.55 * h), int(0.40 * b), int(0.58 * h)))
        self.assertGreater(self._streuung(aus), 10)

    def test_quellpfad_steht_nicht_auf_der_seite(self):
        self._jpeg("pfad.jpg")
        html = build.render_markdown("![Eine Katze.](foto:pfad.jpg)")
        self.assertNotIn("attachments", html)
        self.assertNotIn(str(self.quelle), html)

    # ----------------------------------------------------------- Das Rendern

    def test_foto_wird_zu_figure_mit_unterschrift(self):
        self._jpeg("katze.jpg")
        html = build.render_markdown("![Eine schwarze Katze im Schatten.](foto:katze.jpg)")
        self.assertIn("<figure", html)
        self.assertIn("<figcaption>", html)
        self.assertIn("Eine schwarze Katze im Schatten.", html)
        self.assertRegex(html, r'src="fotos/[^"]+\.jpg"')

    def test_bild_traegt_masse_und_alternativtext(self):
        """Ohne width/height springt das Layout beim Laden."""
        self._jpeg("masse.jpg", groesse=(1200, 800))
        html = build.render_markdown("![Ein Geldautomat.](foto:masse.jpg)")
        self.assertRegex(html, r'width="\d+"')
        self.assertRegex(html, r'height="\d+"')
        self.assertIn('alt="Ein Geldautomat."', html)
        self.assertIn('loading="lazy"', html)

    def test_mehrere_fotos_werden_eine_gruppe(self):
        for n in ("a.jpg", "b.jpg", "c.jpg"):
            self._jpeg(n)
        html = build.render_markdown(
            "![Erste.](foto:a.jpg)\n![Zweite.](foto:b.jpg)\n![Dritte.](foto:c.jpg)")
        self.assertIn('class="fotos fotos--3"', html)
        self.assertEqual(html.count("<figure"), 3)

    def test_fehlendes_foto_bricht_nicht_ab_und_zeigt_keine_ruine(self):
        """Ein kaputtes Bild ist auf einer oeffentlichen Seite sichtbarer
        Schaden; ein fehlender Absatz ist es nicht. Also weg damit — aber
        laut, nie stumm."""
        fehler = io.StringIO()
        with contextlib.redirect_stderr(fehler):
            html = build.render_markdown("![Fehlt.](foto:gibtsnicht.jpg)")
        self.assertNotIn("<img", html)
        self.assertIn("gibtsnicht.jpg", fehler.getvalue())

    def test_hochformat_behaelt_seinen_bildausschnitt(self):
        """Im gerenderten Bild gefunden, im Quelltext unsichtbar.

        Die Gruppe schneidet jedes Bild auf 4:3. Das Foto des Geldautomaten ist
        hochkant, und der Satz, um den es geht — die laufende Abfrage auf dem
        Schirm — steht oben. Zugeschnitten auf die Mitte zeigte es Tastatur und
        sonst nichts: das Bild war noch da und sein Inhalt weg.
        """
        self._jpeg("hoch.jpg", groesse=(720, 1280))
        self._jpeg("quer.jpg", groesse=(1280, 720))
        build.FOTO_DATEN = {"hoch.jpg": {"position": "top"}}
        html = build.render_markdown("![Hoch.](foto:hoch.jpg)\n![Quer.](foto:quer.jpg)")
        self.assertIn("--pos: top", html)
        self.assertEqual(html.count("--pos"), 1, "nur das erklaerte Bild bekommt eine Position")

    def test_kursiv_wird_ausgezeichnet_statt_gedruckt(self):
        """Sternchen standen woertlich auf der Seite: *Mee Goreng Panggung
        Wayang* — der Renderer kannte nur **fett** und `code`."""
        html = build.render_markdown("Ein Stand namens *Mee Goreng Panggung Wayang* im Ort.")
        self.assertIn("<em>Mee Goreng Panggung Wayang</em>", html)
        self.assertNotIn("*", html)

    def test_fett_bleibt_fett_neben_kursiv(self):
        """Die Reihenfolge ist die Falle: **fett** besteht aus zwei Sternchen,
        also muss es zuerst aufgeloest werden, sonst frisst kursiv die Haelfte."""
        html = build.render_markdown("**✓ Ein Haken (17.08.).** Dazu *ein Wort* kursiv.")
        self.assertIn("<strong>", html)
        self.assertIn("<em>ein Wort</em>", html)
        self.assertNotIn("*", html)

    def test_einzelner_stern_bleibt_stehen(self):
        """Ein Sternchen ohne Partner ist kein Auszeichnungszeichen."""
        html = build.render_markdown("Preis 3 * 4 Ringgit.")
        self.assertNotIn("<em>", html)

    def test_kursiv_innerhalb_von_fett(self):
        """Gefunden am 17.08. im gerenderten Bild, nicht im Test: der
        Eintragstitel `**✓ *Garden Rhapsody* im Supertree Grove.**` stand mit
        zwei sichtbaren Sternchen auf der Seite. Ursache: das Fett-Muster
        verbot Sternchen im Inneren, also fand es sein Paar nie — und ein
        Muster, das nur Gueltiges trifft, macht aus einem Fehler eine
        Abwesenheit. Genau die Bauform, mit der ein Werktitel geschrieben
        wird, war damit die eine, die nicht ging."""
        html = build.render_markdown("**✓ *Garden Rhapsody* im Supertree Grove (16.08.).** Frei.")
        self.assertIn("<strong>", html)
        self.assertIn("<em>Garden Rhapsody</em>", html)
        self.assertNotIn("*", html)

    def test_fett_ueber_zwei_zeilen(self):
        """Der Eintragstitel laeuft im Quelltext fast immer ueber den
        Zeilenumbruch — die Quelle ist auf 95 Zeichen umbrochen. Das alte
        Muster `[^*]+` traf den Umbruch mit, ein naives `.+?` nicht: die
        Reparatur des kursiv-in-fett-Falls hat diesen Fall zuerst zerbrochen,
        und wieder hat es nur das gerenderte Bild gezeigt."""
        html = build.render_markdown("**✓ Ein Titel, der ueber die Zeile\nlaeuft (17.08.).** Text.")
        self.assertIn("<strong>", html)
        self.assertNotIn("*", html)

    def test_zwei_fette_stellen_bleiben_getrennt(self):
        """Die Reparatur darf nicht ins andere Extrem kippen: ein gieriges
        Fett-Muster wuerde von der ersten bis zur LETZTEN Sternchenfolge
        greifen und den Text dazwischen mitschlucken."""
        html = build.render_markdown("**eins** dazwischen **zwei**")
        self.assertIn("<strong>eins</strong>", html)
        self.assertIn("<strong>zwei</strong>", html)
        self.assertEqual(html.count("<strong>"), 2)

    def test_unterschrift_wird_escaped(self):
        self._jpeg("escape.jpg")
        html = build.render_markdown('![Ein <script>-Test & mehr.](foto:escape.jpg)')
        self.assertNotIn("<script>", html)
        self.assertIn("&amp;", html)

    def test_bild_wird_nicht_hochgerechnet(self):
        """Telegram liefert 1280 px. Auf 1600 aufblasen kostet Bytes ohne
        einen einzigen zusaetzlichen Bildpunkt."""
        self._jpeg("klein.jpg", groesse=(800, 600))
        ziel = build.verarbeite_foto("klein.jpg")
        with Image.open(ziel) as bild:
            self.assertEqual(bild.size, (800, 600))

    def test_grosses_bild_wird_begrenzt(self):
        self._jpeg("gross.jpg", groesse=(4000, 3000))
        ziel = build.verarbeite_foto("gross.jpg")
        with Image.open(ziel) as bild:
            self.assertLessEqual(bild.size[0], build.FOTO_MAX_BREITE)

    # ------------------------------------------------- Rueckstand der Sprache

    def test_deckungspruefung_zaehlt_auch_fotos(self):
        """Die englische Fassung ist die, die Jens nicht liest. Verliert sie
        ein Foto, faellt es niemandem auf."""
        de = "## A\n\n![Eins.](foto:a.jpg)\n\n![Zwei.](foto:b.jpg)\n"
        en = "## A\n\n![One.](foto:a.jpg)\n"
        luecken = build.pruefe_deckung(de, en)
        self.assertTrue(any("Foto" in l for l in luecken), luecken)

    def test_gleichstand_meldet_nichts(self):
        de = "## A\n\n![Eins.](foto:a.jpg)\n"
        en = "## A\n\n![One.](foto:a.jpg)\n"
        self.assertEqual(build.pruefe_deckung(de, en), [])


class TestAusgelieferteFotos(unittest.TestCase):
    """Gemessen wird am Artefakt auf der Platte, nicht am Generator.

    Am 17.08. war jeder i18n-Test gruen, waehrend cv.jenslaufer.com drei Tage
    lang jedem englischen Leser Deutsch ausgeliefert hat: die Tests prueften
    die Faehigkeit zu rendern, nicht die ausgelieferte Datei.
    """

    def test_kein_ausgeliefertes_foto_traegt_exif(self):
        fotos = sorted(build.FOTO_ZIEL.glob("*.jpg")) if build.FOTO_ZIEL.exists() else []
        if not fotos:
            self.skipTest("noch keine Fotos veroeffentlicht")
        for pfad in fotos:
            with Image.open(pfad) as bild:
                self.assertFalse(dict(bild.getexif()), f"EXIF in {pfad.name}")
                self.assertFalse(bild.getexif().get_ifd(0x8825), f"GPS in {pfad.name}")

    def test_jedes_verlinkte_foto_liegt_auch_da(self):
        for pfad in (build.ZIELE["de"], build.ZIELE["en"]):
            if not pfad.exists():
                continue
            for treffer in re.findall(r'src="(fotos/[^"]+)"', pfad.read_text(encoding="utf-8")):
                self.assertTrue((build.WURZEL / treffer).exists(),
                                f"{treffer} ist verlinkt, liegt aber nicht im Repo")


class TestPflegeblockLeaktNicht(unittest.TestCase):
    """Ein Kommentar kann vorzeitig enden — und legt den Rest offen.

    Gefunden am 17.08. an der englischen Quelle: im Pflegeblock stand die
    Zeichenfolge, die einen HTML-Kommentar schliesst, als Beispiel im Fliesstext.
    Alles danach — interne Regeln, Dateipfade — stand sichtbar auf der
    oeffentlichen Seite. `strip_kommentare` hatte recht: der Kommentar WAR dort
    zu Ende. Der Fehler ist im Quelltext, sichtbar wird er nur im Rendern.
    """

    INTERN = ["pflege", "state/memory/", "fuer die sitzung", "für die sitzung"]

    @staticmethod
    def sichtbar(seite: str) -> str:
        ohne = re.sub(r"<(style|script)\b.*?</\1>", " ", seite, flags=re.S | re.I)
        ohne = re.sub(r"<!--.*?-->", " ", ohne, flags=re.S)
        return re.sub(r"<[^>]+>", " ", ohne).lower()

    def test_frueh_geschlossener_kommentar_faellt_auf(self):
        md = ("# Titel\n\nText.\n\n<!--\nPFLEGE — fuer die Sitzung.\n"
              "Beispiel: ein Kommentar endet mit -->\nDanach: state/memory/geheim.md\n-->\n")
        klein = self.sichtbar(build.render_markdown(md))
        gefunden = [w for w in self.INTERN if w in klein]
        self.assertTrue(gefunden, "der Leak muss auffallen, sonst prueft der Test nichts")

    def test_beide_ausgelieferten_seiten_sind_sauber(self):
        for pfad in (build.ZIELE["de"], build.ZIELE["en"]):
            if not pfad.exists():
                continue
            klein = self.sichtbar(pfad.read_text(encoding="utf-8"))
            for wort in self.INTERN:
                self.assertNotIn(wort, klein, f"interner Pflegetext auf {pfad.name}: {wort!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
