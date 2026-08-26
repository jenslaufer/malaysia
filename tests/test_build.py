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
import xml.etree.ElementTree as ET
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

    def test_nummerierte_liste_wird_liste(self):
        # Gefunden am 17.08. am gerenderten Bild: der Renderer kannte "- ", aber
        # nicht "1. ". Eine nummerierte Liste erreichte die Seite als EIN Absatz,
        # mit den Ziffern als Fliesstext. Im Markdown sieht das richtig aus.
        html = build.render_markdown("1. erster Schritt\n2. zweiter Schritt\n3. dritter")
        self.assertIn("<ol", html)
        self.assertEqual(html.count("<li"), 3)
        self.assertNotIn("<p>1. erster Schritt", html)
        # Die Ziffer setzt der Browser. Bleibt sie zusaetzlich im Text stehen, zeigt
        # die Seite "1. 1. erster Schritt" — am 17.08. genau so passiert, und der
        # Test darueber war dabei gruen.
        self.assertIn("<li>erster Schritt</li>", html)
        self.assertNotIn("<li>1.", html)

    def test_nummerierte_liste_traegt_fortsetzungszeilen(self):
        md = "1. erster Schritt,\n   in zwei Zeilen geschrieben.\n2. zweiter Schritt"
        html = build.render_markdown(md)
        self.assertEqual(html.count("<li"), 2)
        self.assertIn("in zwei Zeilen geschrieben.", html)

    def test_datum_am_satzanfang_ist_keine_liste(self):
        # Gegenprobe, und sie ist der Grund fuer die enge Regel: auf Deutsch faengt
        # ein Absatz oft mit einem Datum an. "18. August 2026 war ..." sieht fuer
        # ein naives ^\d+\. wie ein Listenpunkt aus. Eine Liste beginnt deshalb bei
        # 1. und braucht eine zweite Zeile mit 2.
        html = build.render_markdown("18. August 2026 war der Tag der Ueberfahrt.")
        self.assertNotIn("<ol", html)
        html = build.render_markdown("1. Klasse faehrt nicht auf dieser Strecke.")
        self.assertNotIn("<ol", html)

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

    def test_malaiisches_wort_in_versalien_ist_keine_passnummer(self):
        """Der Waechter darf ein zitiertes Behoerdenschild nicht fuer einen Pass halten.

        Am 20.08. brach der Build an `KEBENARAN` ab — neun Grossbuchstaben, K am
        Anfang, also formal `[CFGHJK][0-9A-Z]{8}`. Eine deutsche Passnummer kann
        die Buchstaben A, B, D, E, I, O, Q, S, U aber gar nicht enthalten; sie
        sind aus dem Zeichenvorrat ausgenommen, damit man 0/O und 1/I nicht
        verwechselt. Ein Muster, das jedes malaiische Wort in Versalien fangen
        kann, kostet nicht eine Minute, sondern verleitet dazu, das Zitat zu
        verbiegen — und dann ist der naechste echte Treffer auch nur Laerm.
        """
        build.pruefe_privat("Auf dem Schild steht DILARANG MASUK TANPA KEBENARAN.")

    def test_echte_passnummer_faellt_weiter_auf(self):
        """Gegenprobe zum Muster darueber: die Verschaerfung darf nichts durchlassen."""
        for nummer in ("C01X00T47", "CZ6311T47", "K12345678"):
            with self.subTest(nummer=nummer):
                try:
                    build.pruefe_privat(f"Reisepass {nummer} vorlegen.")
                except build.PrivatException:
                    pass
                else:
                    self.fail(f"{nummer} nicht erkannt")

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
    """Die Herkunftsspur ist die Verbindung zu /otto/.

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
    """Das Band erklaert dem Leser, wie die Seite entsteht, und verlinkt /otto/."""

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
        self.assertIn("/otto/", html)

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
        self.assertIn("/otto/", seite)


class TestAutorblock(unittest.TestCase):
    """Der Block am Fuss sagt, wer die Seite schreibt und was er beruflich macht.

    Zwei Leser, ein Block. Wer die Reise liest, will wissen, wem er die Haken
    glaubt. Wer wissen will, wie die Seite entsteht, findet hier den Beruf, der
    dahintersteckt — und der ist der Grund, warum es diese Seite gibt.

    Was hier NICHT hingehoert: Preise. Diese Seite geht an Freunde und an Leute,
    die nach dem Weg zur Larkin-Busstation suchen. Ein Tagessatz zwischen
    Faehrzeiten wuerde den Rest der Seite entwerten. Er steht auf /otto/.
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
        self.assertIn("/otto/", build._autor_block())

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


class TestKartenadresse(unittest.TestCase):
    """Die Adresse auf der Vorschaukarte findet kein grep — sie steht im PNG.

    Gefunden am 17.08.: die Karte warb fuer malaysia.jenslaufer.com, eine
    Adresse ohne DNS-Eintrag. Jede Pruefung ueber HTML, Feed und sitemap war
    gruen, weil dort ueberall die richtige Adresse steht; gelesen wird beim
    Teilen aber das Bild. Wer sie abtippt, landet nirgends.
    """

    ERWARTET = build.BASIS.split("://", 1)[1].rstrip("/")

    @contextlib.contextmanager
    def sprache(self, wert):
        alt, build.SPRACHE = build.SPRACHE, wert
        try:
            yield
        finally:
            build.SPRACHE = alt

    def test_karte_zeigt_die_adresse_unter_der_die_seite_steht(self):
        for wert in build.SPRACHEN:
            with self.subTest(sprache=wert), self.sprache(wert):
                self.assertIn(self.ERWARTET, build._og_karte({}))

    def test_karte_nennt_keine_zweite_adresse_auf_dieser_domain(self):
        muster = re.compile(r"[\w.-]*jenslaufer\.com[\w/.-]*")
        for wert in build.SPRACHEN:
            with self.subTest(sprache=wert), self.sprache(wert):
                for gefunden in muster.findall(build._og_karte({})):
                    self.assertEqual(
                        self.ERWARTET, gefunden.rstrip("/"),
                        f"Vorschaukarte nennt {gefunden!r}, erreichbar ist "
                        f"{self.ERWARTET!r}")


class TestKarteSpricht(unittest.TestCase):
    """Die englische Vorschaukarte war zur Haelfte deutsch.

    Belegt am 17.08. an der gerenderten Karte: `lang="en"`, Titel uebersetzt,
    Unterzeile und Legende weiter deutsch. Sichtbar wird das genau dort, wo es
    am meisten kostet — unter dem englischen LinkedIn-Post, den Fremde sehen.
    """

    DEUTSCH = ("selbst erlebt", "nachgeschlagen", "hat nicht funktioniert",
               "Reisenotizen", "veröffentlicht")

    def test_englische_karte_traegt_kein_deutsches_wort(self):
        alt, build.SPRACHE = build.SPRACHE, "en"
        try:
            karte = build._og_karte({})
        finally:
            build.SPRACHE = alt
        sichtbar = re.sub(r"<(style|script)\b.*?</\1>", " ", karte, flags=re.S | re.I)
        for wort in self.DEUTSCH:
            self.assertNotIn(wort, sichtbar)

    def test_deutsche_karte_bleibt_deutsch(self):
        alt, build.SPRACHE = build.SPRACHE, "de"
        try:
            karte = build._og_karte({})
        finally:
            build.SPRACHE = alt
        self.assertIn("selbst erlebt", karte)
        self.assertIn("Reisenotizen", karte)


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
        "gepruef", "haelt", "faehrt", "gehoert", "eintraege",
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

    def test_feed_hat_keine_ascii_umschrift(self):
        """Der Feed-Titel steht in jedem Leseprogramm — und stand am 17.08. falsch.

        Geprueft werden nur die Felder, die ein Leser sieht. Die ids tragen den
        Abschnitts-Slug, und der ist per Bauart ASCII-umgeschrieben — sie
        mitzupruefen hiesse, den Test an einer Stelle rot zu machen, an der die
        Umschrift richtig ist. Ein Test, der am falschen Ort misst, wird
        abgeschaltet statt befolgt.
        """
        A = "{http://www.w3.org/2005/Atom}"
        for pfad in (build.WURZEL / "feed.xml", build.WURZEL / "en" / "feed.xml"):
            if not pfad.exists():
                continue
            wurzel = ET.fromstring(pfad.read_text(encoding="utf-8"))
            sichtbar = [wurzel.findtext(A + "title"), wurzel.findtext(A + "subtitle")]
            for e in wurzel.findall(A + "entry"):
                sichtbar += [e.findtext(A + "title"), e.findtext(A + "content")]
            klein = " ".join(t for t in sichtbar if t).lower()
            for wort in self.UMSCHRIFT:
                self.assertNotIn(wort, klein,
                                 f"ASCII-Umschrift im Feed {pfad.name}: {wort!r}")



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


class TestBildgewicht(TestFotos):
    """Was ausgeliefert wird, ist nicht die Datei, sondern das, was der
    Browser laedt.

    Zwoelf Fotos zu je 1280 px waren am 17.08. 1,75 MB — und zwar auch dort,
    wo das Bild in der Dreiergruppe rund 200 px breit dargestellt wird. Das
    ist Faktor sechs an Bildpunkten, die niemand sieht. Jedes Bild kommt
    deshalb in zwei Breiten und drei Formaten; der Browser nimmt das
    kleinste, das er lesen kann.
    """

    def test_jede_fassung_wird_geschrieben(self):
        self._jpeg("fassungen.jpg", groesse=(1600, 900))
        build.verarbeite_foto("fassungen.jpg")
        for name in ("fassungen.jpg", "fassungen-640.jpg",
                     "fassungen-640.avif", "fassungen-1280.avif",
                     "fassungen-640.webp", "fassungen-1280.webp"):
            self.assertTrue((self.ziel / name).exists(), f"{name} fehlt")

    def test_moderne_formate_sind_kleiner_als_das_jpeg(self):
        """Der ganze Zweck. Ist AVIF nicht kleiner, ist der Aufwand umsonst."""
        self._jpeg("gewicht.jpg", groesse=(1600, 900))
        build.verarbeite_foto("gewicht.jpg")
        jpg = (self.ziel / "gewicht.jpg").stat().st_size
        avif = (self.ziel / "gewicht-1280.avif").stat().st_size
        self.assertLess(avif, jpg, "AVIF ist nicht kleiner als das JPEG")

    def test_keine_fassung_wird_hochgerechnet(self):
        """Ein hochkantes Telegram-Bild ist 720 px breit. Eine
        1280er-Fassung davon kostet Bytes ohne einen Bildpunkt mehr."""
        self._jpeg("hochkant.jpg", groesse=(720, 1280))
        build.verarbeite_foto("hochkant.jpg")
        self.assertFalse((self.ziel / "hochkant-1280.avif").exists(),
                         "720 px breit, und trotzdem eine 1280er-Fassung")
        self.assertTrue((self.ziel / "hochkant-640.avif").exists())

    def test_bild_steht_in_einem_picture_mit_avif_zuerst(self):
        self._jpeg("markup.jpg")
        html = build.render_markdown("![Eine Katze.](foto:markup.jpg)")
        self.assertIn("<picture>", html)
        self.assertLess(html.index('type="image/avif"'), html.index('type="image/webp"'),
                        "AVIF muss vor WebP stehen, sonst gewinnt nie das kleinere")
        self.assertIn('src="fotos/markup.jpg"', html)
        self.assertIn('loading="lazy"', html)

    def test_srcset_nennt_beide_breiten_mit_w(self):
        self._jpeg("srcset.jpg")
        html = build.render_markdown("![Eine Katze.](foto:srcset.jpg)")
        self.assertIn("fotos/srcset-640.avif 640w", html)
        self.assertIn("fotos/srcset-1280.avif 1280w", html)

    def test_gruppe_verlangt_ein_anderes_sizes_als_das_einzelbild(self):
        """In der Dreiergruppe ist das Bild ein Fuenftel so breit wie in
        Satzbreite. Ein gemeinsames `sizes` waere fuer eines von beiden
        falsch — und zwar immer fuer das kleinere."""
        self._jpeg("a.jpg")
        self._jpeg("b.jpg")
        einzeln = build.render_markdown("![Eins.](foto:a.jpg)")
        gruppe = build.render_markdown("![Eins.](foto:a.jpg)\n![Zwei.](foto:b.jpg)")
        self.assertNotEqual(
            re.search(r'sizes="([^"]+)"', einzeln).group(1),
            re.search(r'sizes="([^"]+)"', gruppe).group(1))

    def test_zweiter_lauf_schreibt_nicht_neu(self):
        """AVIF kostet eine Viertelsekunde je Bild und Breite. Ohne diesen
        Test waechst jeder Build um die Zeit, die niemand misst."""
        self._jpeg("cache.jpg")
        build.verarbeite_foto("cache.jpg")
        vorher = {p.name: p.stat().st_mtime_ns for p in self.ziel.iterdir()}
        build.verarbeite_foto("cache.jpg")
        nachher = {p.name: p.stat().st_mtime_ns for p in self.ziel.iterdir()}
        self.assertEqual(vorher, nachher, "die Fassungen wurden neu geschrieben")

    def test_geaenderter_sperrkasten_erzwingt_neubau(self):
        """Die Gegenprobe zum Zwischenspeicher: ein neuer Sperrkasten muss
        durchschlagen, sonst haelt der Cache ein Kennzeichen offen."""
        self._jpeg("neubau.jpg")
        build.verarbeite_foto("neubau.jpg")
        vorher = (self.ziel / "neubau-640.avif").read_bytes()
        build.FOTO_DATEN = {"neubau.jpg": {"blur": [[0.25, 0.5, 0.3, 0.2]]}}
        build.verarbeite_foto("neubau.jpg")
        self.assertNotEqual(vorher, (self.ziel / "neubau-640.avif").read_bytes(),
                            "der Sperrkasten hat die kleine Fassung nicht erreicht")


class TestZuschnitt(unittest.TestCase):
    """Wegschneiden ist der staerkere Schutz, und manchmal der einzig ehrliche.

    Am 24.08. lagen 5 von 16 Bildern aus Kuala Lumpur ungenutzt herum, weil auf
    jedem ueber zwanzig fremde Gesichter aus der Naehe zu sehen sind. Zwanzig
    von Hand gepflegte Sperrkaesten sind genau der Schutz, der wie Schutz
    aussieht und keiner ist — es genuegt, einen zu vergessen. Auf dem Bild vom
    Fahrenheit 88 steht die Aussage ueber den Koepfen: Fassade, Anzeigetafel,
    Springbrunnen, Flaggen. Ein Zuschnitt nimmt die Bildpunkte weg, statt sie
    zu verwischen — was nicht mehr da ist, kann kein Kasten verfehlen.
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

    def _jpeg(self, name="bild.jpg", groesse=(1200, 800)):
        """Oben eine ruhige Flaeche, unten Rauschen. So laesst sich messen,
        ob wirklich der obere Teil uebrig geblieben ist."""
        bild = Image.new("RGB", groesse, (200, 200, 200))
        for x in range(groesse[0]):
            for y in range(groesse[1] // 2, groesse[1]):
                bild.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, 90))
        pfad = self.quelle / name
        bild.save(pfad, "JPEG", quality=95)
        return pfad

    @staticmethod
    def _streuung(bild) -> float:
        werte = list(bild.convert("L").getdata())
        mittel = sum(werte) / len(werte)
        return (sum((w - mittel) ** 2 for w in werte) / len(werte)) ** 0.5

    def test_zuschnitt_nimmt_den_rest_weg(self):
        """Der Kern: die weggeschnittenen Bildpunkte sind weg, nicht verwischt."""
        self._jpeg("platz.jpg", groesse=(1200, 800))
        build.FOTO_DATEN = {"platz.jpg": {"zuschnitt": [0.0, 0.0, 1.0, 0.5]}}
        ziel = build.verarbeite_foto("platz.jpg")
        with Image.open(ziel) as bild:
            self.assertEqual(bild.size, (1200, 400), "der Zuschnitt hat nicht gegriffen")
            self.assertLess(self._streuung(bild), 5,
                            "die untere, verrauschte Haelfte steht noch im Bild")

    def test_zuschnitt_ist_relativ_und_ueberlebt_das_verkleinern(self):
        """Dieselbe Begruendung wie beim Sperrkasten: absolute Bildpunkte
        zeigen nach dem Skalieren woanders hin, und zwar lautlos."""
        self._jpeg("gross.jpg", groesse=(2000, 1000))
        build.FOTO_DATEN = {"gross.jpg": {"zuschnitt": [0.25, 0.0, 0.5, 0.4]}}
        ziel = build.verarbeite_foto("gross.jpg")
        with Image.open(ziel) as bild:
            # 2000x1000 -> Ausschnitt 1000x400 -> unter FOTO_MAX_BREITE, bleibt
            self.assertEqual(bild.size, (1000, 400))

    def test_sperrkasten_zaehlt_im_zugeschnittenen_bild(self):
        """Sonst muesste ich beim Setzen eines Kastens im Kopf zurueckrechnen —
        und ein Kasten, der falsch sitzt, sieht auf der Seite aus wie Schutz."""
        self._jpeg("beides.jpg", groesse=(1200, 800))
        build.FOTO_DATEN = {"beides.jpg": {
            "zuschnitt": [0.0, 0.5, 1.0, 0.5],       # die verrauschte Haelfte
            "blur": [[0.0, 0.0, 0.5, 1.0]],          # deren linke Haelfte
        }}
        ziel = build.verarbeite_foto("beides.jpg")
        with Image.open(ziel) as bild:
            b, h = bild.size
            links = bild.crop((int(0.10 * b), int(0.3 * h), int(0.35 * b), int(0.7 * h)))
            rechts = bild.crop((int(0.65 * b), int(0.3 * h), int(0.90 * b), int(0.7 * h)))
        self.assertLess(self._streuung(links), self._streuung(rechts) / 2,
                        "der Kasten wurde auf die Vorlage statt auf den Ausschnitt gelegt")

    def test_geaenderter_zuschnitt_erzwingt_neubau(self):
        """Der Zwischenspeicher darf keinen Zuschnitt verschlucken. Sonst
        bleibt genau die Fassung mit den Gesichtern liegen, waehrend die
        fotos.json sagt, sie waeren weggeschnitten."""
        self._jpeg("cache.jpg", groesse=(1200, 800))
        build.verarbeite_foto("cache.jpg")
        vorher = (self.ziel / "cache.jpg").read_bytes()
        build.FOTO_DATEN = {"cache.jpg": {"zuschnitt": [0.0, 0.0, 1.0, 0.5]}}
        build.verarbeite_foto("cache.jpg")
        self.assertNotEqual(vorher, (self.ziel / "cache.jpg").read_bytes(),
                            "der Zuschnitt hat die ausgelieferte Datei nicht erreicht")

    def test_zuschnitt_ausserhalb_des_bildes_bricht_ab(self):
        """Nicht zurechtbiegen. Ein stillschweigend gekappter Kasten schneidet
        woanders als beabsichtigt — und niemand sieht es dem Bild an."""
        self._jpeg("daneben.jpg")
        for kasten in ([0.5, 0.0, 0.8, 0.5], [-0.1, 0.0, 0.5, 0.5], [0.0, 0.0, 0.0, 0.5]):
            with self.subTest(kasten=kasten):
                build.FOTO_DATEN = {"daneben.jpg": {"zuschnitt": kasten}}
                with self.assertRaises(build.FotoDatenException):
                    build.verarbeite_foto("daneben.jpg")

    def test_unbekannter_schluessel_bricht_ab(self):
        """Ein Tippfehler in fotos.json (`zuschneiden` statt `zuschnitt`) waere
        sonst still: das Bild erscheint ungeschnitten, der Build ist gruen, und
        die Datei behauptet das Gegenteil. Genau die Bauform, gegen die dieses
        Repo seine Sperrkaesten von Hand pflegt."""
        self._jpeg("tippfehler.jpg")
        build.FOTO_DATEN = {"tippfehler.jpg": {"zuschneiden": [0.0, 0.0, 1.0, 0.5]}}
        with self.assertRaises(build.FotoDatenException):
            build.verarbeite_foto("tippfehler.jpg")

    def test_unterstrich_schluessel_bleiben_erlaubt(self):
        """`_zuschnitt` und `_blur` tragen die Begruendung neben dem Wert.
        Gegenprobe zum Test darueber, sonst verbietet die Pruefung die Notizen."""
        self._jpeg("notiz.jpg")
        build.FOTO_DATEN = {"notiz.jpg": {
            "name": "notiz", "_zuschnitt": "warum hier geschnitten wird",
            "zuschnitt": [0.0, 0.0, 1.0, 0.5]}}
        self.assertIsNotNone(build.verarbeite_foto("notiz.jpg"))

    def test_kaputte_fotos_json_bricht_ab_statt_ohne_sperrkaesten_zu_bauen(self):
        """Der teuerste Fall in dieser Datei: ein Komma zu viel, und
        `lade_foto_daten` gab {} zurueck — jedes Foto erschien dann OHNE seine
        Sperrkaesten, mit gruenem Build. Ein Schutz, der bei einem Syntaxfehler
        lautlos abschaltet, ist keiner."""
        pfad = Path(self.tmp) / "kaputt.json"
        pfad.write_text('{"a.jpg": {"blur": [[0.1, 0.1, 0.2, 0.2]],}}', encoding="utf-8")
        with self.assertRaises(build.FotoDatenException):
            build.lade_foto_daten(pfad)

    def test_fehlende_fotos_json_bleibt_erlaubt(self):
        """Gegenprobe: keine Datei ist keine kaputte Datei — sonst baut das
        Repo nicht mehr, bevor das erste Foto eingetragen ist."""
        self.assertEqual(build.lade_foto_daten(Path(self.tmp) / "gibtsnicht.json"), {})


class TestAusgelieferteFotos(unittest.TestCase):
    """Gemessen wird am Artefakt auf der Platte, nicht am Generator.

    Am 17.08. war jeder i18n-Test gruen, waehrend cv.jenslaufer.com drei Tage
    lang jedem englischen Leser Deutsch ausgeliefert hat: die Tests prueften
    die Faehigkeit zu rendern, nicht die ausgelieferte Datei.
    """

    def test_kein_ausgeliefertes_foto_traegt_exif(self):
        """Alle Formate, nicht nur JPEG: AVIF und WebP koennen EXIF genauso
        tragen, und die kleine Fassung ist dieselbe Aufnahme."""
        fotos = sorted(p for e in ("*.jpg", "*.avif", "*.webp")
                       for p in build.FOTO_ZIEL.glob(e)) if build.FOTO_ZIEL.exists() else []
        if not fotos:
            self.skipTest("noch keine Fotos veroeffentlicht")
        for pfad in fotos:
            with Image.open(pfad) as bild:
                self.assertFalse(dict(bild.getexif()), f"EXIF in {pfad.name}")
                self.assertFalse(bild.getexif().get_ifd(0x8825), f"GPS in {pfad.name}")

    def test_jedes_verlinkte_foto_liegt_auch_da(self):
        """`src` UND `srcset`: ein fehlendes srcset-Bild ist der teurere
        Fehler, weil der Browser es dem `src` vorzieht — die Seite zeigt dann
        ein Loch, obwohl die Rueckfalldatei danebenliegt.

        **Aufgeloest wird gegen den Ordner der SEITE, nicht gegen die Wurzel**
        (18.08.). Vorher lief beides gegen `build.WURZEL`: `fotos/x.jpg` aus
        `en/index.html` fand die Datei im Wurzelordner, waehrend der Browser
        sie unter `/malaysia/en/fotos/` suchte und 404 bekam. Der Test bewies
        die Existenz der Datei — nicht, dass der Verweis von dort aus traegt.
        Ein relativer Pfad hat ohne seinen Ausgangspunkt keine Bedeutung.
        """
        gemessen = 0
        for pfad in (build.ZIELE["de"], build.ZIELE["en"]):
            if not pfad.exists():
                continue
            text = pfad.read_text(encoding="utf-8")
            verlinkt = set(re.findall(r'src="([^"]*fotos/[^"]+)"', text))
            for satz in re.findall(r'srcset="([^"]+)"', text):
                verlinkt.update(t.strip().split()[0] for t in satz.split(",")
                                if "fotos/" in t)
            for treffer in sorted(verlinkt):
                gemessen += 1
                self.assertTrue((pfad.parent / treffer).resolve().exists(),
                                f"{treffer} ist aus {pfad.name} verlinkt, "
                                f"liegt von dort aus aber nicht da")
        self.assertGreater(gemessen, 0, "keine Bildadresse geprueft — Test misst nichts")


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


class TestFeed(unittest.TestCase):
    """Der Feed ist ein ZWEITER Ausgabeweg — und damit ein zweites Leck.

    Jens 2026-08-17 10:43: "Können wir Website Notifications einstellen, so dass
    Leute über Neuerungen informiert werden?" Browser-Push scheidet aus (auf dem
    iPhone nur mit Seite-auf-Startbildschirm und mit Server), also Atom.

    Die teure Stelle ist nicht das XML, sondern dass `pruefe_privat` bisher nur
    im Weg nach `index.html` haengt. Ein zweiter Schreiber, der daran vorbeilaeuft,
    haette die Datenschutzpruefung der Seite nicht umgangen, sondern verdoppelt —
    einmal mit Pruefung, einmal ohne.
    """

    QUELLE = (
        "# Titel\n\n"
        "## Bezahlen\n\n"
        "**✓ Im Bus geht kontaktlos.** Ohne Vorbereitung, Karte drauf.\n"
        "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n\n"
        "**✓ Am Automaten kam Geld heraus.** BSN, keine Gebuehr.\n"
        "<!-- werkstatt: telegram=2026-08-17T09:25 -->\n\n"
        "**○ Wechselstuben sollen guenstiger sein.** Nicht selbst geprueft.\n"
    )

    SPUREN = {
        "2026-08-17T04:41:00+00:00": {
            "telegram": "2026-08-17T04:41:00+00:00",
            "veroeffentlicht": "2026-08-17T05:46:51+00:00",
            "minuten": 66,
        },
        "2026-08-17T09:25:00+00:00": {
            "telegram": "2026-08-17T09:25:00+00:00",
            "veroeffentlicht": "2026-08-17T10:05:00+00:00",
            "minuten": 40,
        },
    }

    @contextlib.contextmanager
    def messung(self, spuren):
        alt = build.WERKSTATT
        build.WERKSTATT = spuren
        try:
            yield
        finally:
            build.WERKSTATT = alt

    def feed(self, md=None, spuren=None, sprache="de"):
        with self.messung(self.SPUREN if spuren is None else spuren):
            alt, build.SPRACHE = build.SPRACHE, sprache
            try:
                return build.baue_feed(self.QUELLE if md is None else md)
            finally:
                build.SPRACHE = alt

    def test_feed_ist_wohlgeformtes_atom(self):
        wurzel = ET.fromstring(self.feed())
        self.assertTrue(wurzel.tag.endswith("}feed"), wurzel.tag)

    def test_jede_gemessene_meldung_wird_ein_eintrag(self):
        wurzel = ET.fromstring(self.feed())
        self.assertEqual(2, len(wurzel.findall("{http://www.w3.org/2005/Atom}entry")))

    def test_ohne_messung_kein_eintrag_und_kein_erfundenes_datum(self):
        """Recherche hat kein Datum — also steht sie nicht im Feed.

        Ein Eintrag ohne Messung braeuchte ein Datum, das niemand gemessen hat.
        Ein erfundenes waere die schlechteste der drei Moeglichkeiten: der Leser
        bekaeme eine Meldung ueber etwas, das nicht passiert ist.
        """
        xml = self.feed()
        self.assertIn("Im Bus geht kontaktlos", xml)
        self.assertNotIn("Wechselstuben", xml)

    def test_ganz_ohne_messung_wird_gar_kein_feed_geschrieben(self):
        """Ein leerer Feed liest sich wie ein ruhiger Tag, ist aber ein Ausfall.

        Dieselbe Bauform wie eine Pruefung, die gar nicht laeuft und als
        bestanden gilt. Ohne Messung gibt es kein Ergebnis, also auch keine
        Datei — die alte bleibt stehen und luegt wenigstens nicht neu.
        """
        self.assertIsNone(self.feed(spuren={}))

    def test_id_haengt_am_zeitstempel_nicht_am_text(self):
        """Ein Schluessel aus dem Inhalt bricht, sobald der Inhalt sich aendert.

        Genau dieser Fehler hat am 17.08. die Herkunftszeile der englischen
        Seite gekostet (Anker = erste 60 Zeichen). Im Feed waere er teurer: eine
        neue id heisst fuer jeden Leser "neuer Beitrag", also meldet ein
        korrigierter Tippfehler denselben Eintrag ein zweites Mal.
        """
        vorher = ET.fromstring(self.feed())
        geaendert = self.QUELLE.replace("Im Bus geht kontaktlos.",
                                        "Im Bus geht kontaktlos bezahlen.")
        nachher = ET.fromstring(self.feed(md=geaendert))
        ids = lambda w: [e.findtext("{http://www.w3.org/2005/Atom}id")  # noqa: E731
                         for e in w.findall("{http://www.w3.org/2005/Atom}entry")]
        self.assertEqual(ids(vorher), ids(nachher))

    def test_zwei_eintraege_aus_EINER_nachricht_bekommen_verschiedene_ids(self):
        """Gefunden am 17.08. im ausgelieferten Feed, nicht im Test.

        Jens schickte um 10:21 drei Fotos; zwei Eintraege tragen deshalb
        denselben Telegram-Zeitstempel. Mit der Zeit allein als id waren beide
        derselbe Beitrag — und ein Leseprogramm zeigt von zwei gleichen ids
        genau einen an. Der zweite Eintrag erreicht dann **niemanden**, still
        und dauerhaft.

        Doppelt zugestellt ist laut und heilbar, gar nicht zugestellt ist keins
        von beidem: die id darf sich lieber einmal zu oft aendern.
        """
        md = ("# Titel\n\n## Bezahlen\n\n"
              "**✓ Erstes Bild.** Dazu ein Satz.\n"
              "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n\n"
              "**✓ Zweites Bild aus derselben Nachricht.** Noch ein Satz.\n"
              "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n")
        wurzel = ET.fromstring(self.feed(md=md))
        ids = [e.findtext("{http://www.w3.org/2005/Atom}id")
               for e in wurzel.findall("{http://www.w3.org/2005/Atom}entry")]
        self.assertEqual(2, len(ids))
        self.assertEqual(len(ids), len(set(ids)), f"doppelte id: {ids}")

    def test_ausgelieferter_feed_hat_keine_doppelte_id(self):
        """Gemessen an der Datei im Netz — die Faehigkeit sagt nichts ueber sie."""
        for pfad in (build.WURZEL / "feed.xml", build.WURZEL / "en" / "feed.xml"):
            if not pfad.exists():
                continue
            wurzel = ET.fromstring(pfad.read_text(encoding="utf-8"))
            ids = [e.findtext("{http://www.w3.org/2005/Atom}id")
                   for e in wurzel.findall("{http://www.w3.org/2005/Atom}entry")]
            doppelt = {i for i in ids if ids.count(i) > 1}
            self.assertFalse(doppelt, f"{pfad.name}: doppelte ids {doppelt}")

    def test_neueste_meldung_steht_oben(self):
        wurzel = ET.fromstring(self.feed())
        daten = [e.findtext("{http://www.w3.org/2005/Atom}updated")
                 for e in wurzel.findall("{http://www.w3.org/2005/Atom}entry")]
        self.assertEqual(sorted(daten, reverse=True), daten)

    def test_link_zeigt_auf_den_abschnitt_nicht_nur_auf_die_seite(self):
        wurzel = ET.fromstring(self.feed())
        erster = wurzel.find("{http://www.w3.org/2005/Atom}entry")
        ziel = erster.find("{http://www.w3.org/2005/Atom}link").get("href")
        self.assertTrue(ziel.endswith("#bezahlen"), ziel)

    def test_englischer_feed_zeigt_auf_die_englische_seite(self):
        wurzel = ET.fromstring(self.feed(sprache="en"))
        erster = wurzel.find("{http://www.w3.org/2005/Atom}entry")
        ziel = erster.find("{http://www.w3.org/2005/Atom}link").get("href")
        self.assertIn("/en/", ziel)

    def test_sonderzeichen_zerreissen_das_xml_nicht(self):
        md = ("# Titel\n\n## Bezahlen\n\n"
              "**✓ Karte & Bargeld <beides> geht.** Ein \"Satz\" dazu.\n"
              "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n")
        wurzel = ET.fromstring(self.feed(md=md))
        titel = wurzel.find(".//{http://www.w3.org/2005/Atom}entry/"
                            "{http://www.w3.org/2005/Atom}title").text
        self.assertIn("Karte & Bargeld <beides> geht", titel)

    def test_feed_bricht_bei_privaten_daten_genauso_ab_wie_die_seite(self):
        """Der zweite Ausgabeweg darf die Sperre nicht umgehen."""
        md = ("# Titel\n\n## Bezahlen\n\n"
              "**✓ Reisepass C01X00T47 gescannt.** Ging schnell.\n"
              "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n")
        with self.assertRaises(build.PrivatException):
            self.feed(md=md)

    def test_gesperrtes_wort_erreicht_den_feed_nicht(self):
        md = ("# Titel\n\n## Bezahlen\n\n"
              "**✓ Die PIN lautet GEHEIMTOKEN4711.** Steht auf dem Zettel.\n"
              "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n")
        # klein geschrieben, weil `lade_sperrliste` jedes Wort klein ablegt und
        # `pruefe_privat` gegen den kleingeschriebenen Text vergleicht. Ein
        # grosses Token im Test prueft eine Liste, die es so nie gibt.
        alt = build.GEHEIME_TOKEN
        build.GEHEIME_TOKEN = ["geheimtoken4711"]
        try:
            with self.assertRaises(build.PrivatException):
                self.feed(md=md)
        finally:
            build.GEHEIME_TOKEN = alt

    def test_seite_meldet_den_feed_an_leseprogramme(self):
        """Ohne diese Zeile findet kein Reader den Feed — er ist dann nur eine Datei."""
        for sprache, ziel in build.ZIELE.items():
            if not ziel.exists():
                continue
            seite = ziel.read_text(encoding="utf-8")
            self.assertIn('type="application/atom+xml"', seite,
                          f"{ziel.name} meldet keinen Feed")

    def test_ausgelieferter_feed_ist_wohlgeformt(self):
        """Gemessen wird die Datei, die im Netz liegt, nicht die Faehigkeit."""
        for pfad in (build.WURZEL / "feed.xml", build.WURZEL / "en" / "feed.xml"):
            if not pfad.exists():
                continue
            ET.fromstring(pfad.read_text(encoding="utf-8"))


class TestSitemap(unittest.TestCase):
    """Die Search Console meldete am 17.08. fuer beide Fassungen `URL is unknown
    to Google` — die Seite stand in keiner sitemap der Domain. Geprueft wird
    deshalb die ausgelieferte Datei, nicht die Faehigkeit, eine zu schreiben."""

    def test_sitemap_nennt_beide_sprachfassungen(self):
        pfad = build.WURZEL / "sitemap.xml"
        self.assertTrue(pfad.exists(), "sitemap.xml fehlt — Google findet die Seite nicht")
        wurzel = ET.fromstring(pfad.read_text(encoding="utf-8"))
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        adressen = {e.text for e in wurzel.iter(f"{ns}loc")}
        self.assertIn(build.BASIS, adressen)
        self.assertIn(build.BASIS + "en/", adressen)

    def test_sitemap_nennt_keine_relative_adresse(self):
        """Eine relative Adresse ist in einer sitemap ungueltig und wird still
        verworfen — der Fehler sieht dann wie ein langsamer Crawler aus."""
        wurzel = ET.fromstring((build.WURZEL / "sitemap.xml").read_text(encoding="utf-8"))
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        for e in wurzel.iter(f"{ns}loc"):
            self.assertTrue(e.text.startswith("https://"), e.text)


class TestFremdeRessourcen(unittest.TestCase):
    """Was die Seite laedt, laedt sie beim Leser — vor jedem Klick.

    Diese Seite lud bis zum 17.08. Schriften bei Google und Leaflet bei unpkg;
    beides traegt die IP jedes Lesers zu einem Dritten, bevor er etwas
    angeklickt hat, und keine Datenschutzzeile heilt das (LG Muenchen I,
    20.01.2022 — 3 O 17493/20). Beides liegt jetzt hier.

    Die Kartenkacheln bleiben fremd — die kann man nicht mitliefern. Deshalb
    laedt die Karte erst auf Klick, und `EXTERN_ERLAUBT` ist die Tuer im
    Waechter: ohne sie waere er derselbe Fehler wie die Adress-Sperre auf der
    Schwester-Seite, die jeden Kontaktweg zugesperrt hat. Was durch die Tuer
    geht, muss in der Datenschutzerklaerung stehen — der letzte Test hier haelt
    beide zusammen.
    """

    def test_erkennt_eine_fremde_schrift(self):
        # Positivkontrolle: ohne sie misst der Test unten nur, dass die Suche
        # nichts findet — auch wenn sie gar nicht sucht.
        fund = build.externe_ressourcen(
            '<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">')
        self.assertEqual(len(fund), 1, fund)

    def test_erkennt_skript_bild_und_css_adresse(self):
        for schnipsel in ('<script src="https://unpkg.com/leaflet.js"></script>',
                          '<img src="https://example.com/a.png">',
                          '<style>body{background:url(https://example.com/b.png)}</style>',
                          '<link rel="preconnect" href="https://fonts.gstatic.com">'):
            with self.subTest(schnipsel=schnipsel):
                self.assertTrue(build.externe_ressourcen(schnipsel), schnipsel)

    def test_erkennt_eine_adresse_im_javascript(self):
        # Die Kacheln laedt kein HTML-Attribut, sondern eine Zeile Javascript.
        # Ein Waechter, der nur Attribute liest, meldet die Seite sauber und
        # der Browser holt trotzdem bei einem Dritten.
        self.assertTrue(build.externe_ressourcen(
            '<script>L.tileLayer("https://tile.example.com/{z}/{x}.png")</script>'))

    def test_anker_ist_keine_ressource(self):
        self.assertEqual([], build.externe_ressourcen(
            '<a href="https://jenslaufer.com/otto/">Harness</a>'))

    def test_eigene_und_data_adressen_sind_keine_fremden(self):
        self.assertEqual([], build.externe_ressourcen(
            '<link rel="stylesheet" href="fonts/fonts.css">'
            '<script src="vendor/leaflet/leaflet.js"></script>'
            '<link rel="icon" href="data:image/svg+xml,%3Csvg%3E">'))

    def test_beide_sprachfassungen_laden_nichts_ausser_der_karte(self):
        for sprache in build.SPRACHEN:
            pfad = build.ZIELE[sprache]
            if not pfad.exists():
                self.skipTest(f"{pfad} noch nicht gebaut")
            with self.subTest(sprache=sprache):
                self.assertEqual([], build.externe_ressourcen(
                    pfad.read_text(encoding="utf-8")))

    def test_pruefung_bricht_ab_statt_zu_melden(self):
        with self.assertRaises(build.ExternException):
            build.pruefe_extern('<script src="https://example.com/x.js"></script>')

    def test_erlaubte_quelle_steht_in_der_datenschutzerklaerung(self):
        self.assertTrue(build.EXTERN_ERLAUBT, "die Karte braucht eine Ausnahme")
        for host in build.EXTERN_ERLAUBT:
            for sprache in build.SPRACHEN:
                with self.subTest(host=host, sprache=sprache):
                    self.assertIn(host, build.rendere_recht("datenschutz", sprache),
                                  f"{host} ist erlaubt, steht aber nicht in der "
                                  f"Datenschutzerklaerung ({sprache})")


class TestKarteLaedtErstAufKlick(unittest.TestCase):
    """Die Kacheln kommen von OpenStreetMap — der einzige Dritte, der bleibt.

    Er bleibt, weil man eine Weltkarte nicht mitliefert. Also entscheidet der
    Leser: die Karte zeigt zuerst einen Knopf, und erst der Klick holt die
    Kacheln. Vorher erfaehrt openstreetmap.org nichts von ihm.
    """

    def setUp(self):
        build.SPRACHE = "de"
        self.html = build._karte()

    def tearDown(self):
        build.SPRACHE = "de"

    def test_die_kachel_adresse_steht_nicht_im_automatischen_teil(self):
        # Der Aufruf muss HINTER dem Knopf liegen. Steht er im Startlauf,
        # laedt die Karte trotz Knopf — und der Knopf ist dann Dekoration.
        start = self.html.split("function karteLaden")[0]
        self.assertNotIn("tile.openstreetmap.org", start)

    def test_knopf_und_begruendung_stehen_da(self):
        self.assertIn("karte-laden", self.html)
        self.assertIn("openstreetmap.org", self.html)
        self.assertIn("IP-Adresse", self.html)

    def test_stationen_stehen_auch_ohne_karte_da(self):
        # Der Knopf darf die Auskunft nicht wegsperren: wer nicht klickt, soll
        # die Route trotzdem lesen koennen.
        self.assertIn('<ol class="stationen">', self.html)
        self.assertIn("Kota Kinabalu", self.html)

    def test_englische_fassung_hat_den_englischen_knopftext(self):
        build.SPRACHE = "en"
        html = build._karte()
        self.assertIn("Load map", html)
        self.assertNotIn("Karte laden", html)


class TestRechtsseiten(unittest.TestCase):
    """Impressum und Datenschutzerklaerung, von Jens am 17.08. 12:32 bestellt.

    Die Seite ist ein Marketing-Projekt fuer Jens' Arbeit als FDE (sein Wort,
    06:59) und verlinkt die Angebotsseite — also kein rein privates Angebot.
    Ein Impressum, das ein privater Blog nicht braucht, schadet nie; sein
    Fehlen auf einer geschaeftsnahen Seite ist abmahnbar.
    """

    def test_impressum_traegt_alle_pflichtangaben(self):
        for sprache in build.SPRACHEN:
            html = build.rendere_recht("impressum", sprache)
            sichtbar = re.sub(r"<[^>]+>", " ", html)
            with self.subTest(sprache=sprache):
                for feld in ("firma", "strasse", "ort", "vertreten",
                             "registergericht", "registernummer", "ustid"):
                    self.assertIn(build.IMPRESSUM[feld], sichtbar, feld)
                self.assertIn(f"mailto:{build.KONTAKT}", html)

    def test_impressum_nennt_das_geltende_gesetz(self):
        html = build.rendere_recht("impressum", "de")
        self.assertIn("DDG", html)
        self.assertNotIn("TMG", html)
        self.assertNotIn("RStV", html)

    def test_datenschutz_traegt_die_pflichtinhalte(self):
        for sprache in build.SPRACHEN:
            html = build.rendere_recht("datenschutz", sprache)
            with self.subTest(sprache=sprache):
                for anker in ("Art. 13", "Art. 6", "Art. 15", "Art. 77",
                              "GitHub", "Data Privacy Framework"):
                    self.assertIn(anker, html, anker)

    def test_datenschutz_nennt_die_fotos(self):
        # Auf dieser Seite stehen Bilder von Menschen. Eine Erklaerung, die
        # davon schweigt, beschreibt eine andere Seite.
        for sprache in build.SPRACHEN:
            html = build.rendere_recht("datenschutz", sprache).lower()
            with self.subTest(sprache=sprache):
                self.assertTrue("foto" in html or "photo" in html)

    def test_rechtsseiten_laden_selbst_nichts_fremdes(self):
        for art in build.RECHTSARTEN:
            for sprache in build.SPRACHEN:
                with self.subTest(art=art, sprache=sprache):
                    self.assertEqual([], build.externe_ressourcen(
                        build.rendere_recht(art, sprache), erlaubt=()))

    def test_jede_seite_verlinkt_impressum_und_datenschutz(self):
        for sprache in build.SPRACHEN:
            pfad = build.ZIELE[sprache]
            if not pfad.exists():
                self.skipTest(f"{pfad} noch nicht gebaut")
            html = pfad.read_text(encoding="utf-8")
            for art in build.RECHTSARTEN:
                ziel = Path(build.RECHTSSEITEN[(art, sprache)]).name
                with self.subTest(sprache=sprache, art=art):
                    self.assertIn(ziel, html)

    def test_englische_fassung_ist_englisch(self):
        for art in build.RECHTSARTEN:
            klein = re.sub(r"<[^>]+>", " ",
                           re.sub(r"<(style|script)\b.*?</\1>", " ",
                                  build.rendere_recht(art, "en"), flags=re.S)).lower()
            with self.subTest(art=art):
                for wort in (r"\bund\b", r"\bnicht\b", r"\bwerden\b", r"\bkeine\b"):
                    self.assertIsNone(re.search(wort, klein), f"{art}/en: {wort}")

    def test_alle_vier_seiten_liegen_gebaut_auf_der_platte(self):
        # Der Test misst das ARTEFAKT, nicht die Faehigkeit es zu rendern.
        # Genau diese Unterscheidung hat am 14.08. drei Tage lang eine
        # englische Seite verschwinden lassen, waehrend alle Tests gruen waren.
        for pfad in build.RECHTSSEITEN.values():
            datei = build.WURZEL / pfad
            with self.subTest(pfad=pfad):
                self.assertTrue(datei.exists(), f"{pfad} fehlt")
                self.assertGreater(datei.stat().st_size, 1500, pfad)




class TestBildpfadeEnglisch(unittest.TestCase):
    """Gefunden am 18.08.: JEDES Foto der englischen Seite war live ein 404.

    Die englische Fassung liegt unter `/malaysia/en/`, die Bilder unter
    `/malaysia/fotos/`. Ein relatives `fotos/…` zeigt von dort auf
    `/malaysia/en/fotos/…` — das gibt es nicht. Der Fehler war unsichtbar:
    die Tests bauten Strings, der Browser lud nichts nach, und Jens liest die
    englische Fassung nicht. Gemessen mit curl gegen die ausgelieferte Seite:
    144 verschiedene Bildadressen, alle 404.
    """

    def setUp(self):
        self.sprache = build.SPRACHE
        build.FOTO_DATEN = build.lade_foto_daten()

    def tearDown(self):
        build.SPRACHE = self.sprache

    def test_deutsche_fassung_bleibt_relativ(self):
        build.SPRACHE = "de"
        self.assertEqual(build._fotopfad("a-640.jpg"), "fotos/a-640.jpg")

    def test_englische_fassung_geht_eine_ebene_hoch(self):
        build.SPRACHE = "en"
        self.assertEqual(build._fotopfad("a-640.jpg"), "../fotos/a-640.jpg")

    def test_kein_bild_der_ausgelieferten_englischen_seite_zeigt_ins_leere(self):
        en = (build.WURZEL / "en" / "index.html").read_text(encoding="utf-8")
        adressen = set(re.findall(r'(?:src|srcset)="([^"]+)"', en))
        einzeln = set()
        for a in adressen:
            for teil in a.split(","):
                pfad = teil.strip().split(" ")[0]
                if "fotos/" in pfad:
                    einzeln.add(pfad)
        self.assertTrue(einzeln, "keine Bilder gefunden — Test misst nichts")
        for pfad in sorted(einzeln):
            self.assertTrue(pfad.startswith("../fotos/"), f"zeigt ins Leere: {pfad}")
            ziel = build.WURZEL / "en" / pfad
            self.assertTrue(ziel.resolve().exists(), f"Datei fehlt: {pfad}")


class TestZuletzt(unittest.TestCase):
    """Umbau 1 (Jens 2026-08-18 09:44, „spannender gestalten").

    Die frischen Eintraege liegen in ihren Themenabschnitten begraben. Wer nach
    zwei Tagen wiederkommt, findet nicht, was neu ist. Der Block steht ganz
    oben und nennt die letzten selbst erlebten Meldungen.
    """

    QUELLE = (
        "# Titel\n\nEinleitung.\n\n"
        "## Alt\n\n"
        "**✓ Erster Eintrag (16.08.).** Text eins.\n"
        "<!-- werkstatt: telegram=2026-08-16T08:00 -->\n\n"
        "**○ Nachgeschlagen.** Nur Recherche, gehoert nie in den Block.\n\n"
        "## Neu\n\n"
        "**✓ Zweiter Eintrag (17.08.).** Text zwei.\n"
        "<!-- werkstatt: telegram=2026-08-17T09:00 -->\n\n"
        "**✓ Dritter Eintrag (18.08.).** Text drei.\n"
        "<!-- werkstatt: telegram=2026-08-18T10:30 -->\n"
    )

    def setUp(self):
        self.alt = dict(build.WERKSTATT)
        build.WERKSTATT.update({
            "2026-08-16T08:00:00+00:00": {
                "telegram": "2026-08-16T08:00:00+00:00",
                "veroeffentlicht": "2026-08-16T08:10:00+00:00", "minuten": 10},
            "2026-08-17T09:00:00+00:00": {
                "telegram": "2026-08-17T09:00:00+00:00",
                "veroeffentlicht": "2026-08-17T09:07:00+00:00", "minuten": 7},
            "2026-08-18T10:30:00+00:00": {
                "telegram": "2026-08-18T10:30:00+00:00",
                "veroeffentlicht": "2026-08-18T10:37:00+00:00", "minuten": 7},
        })

    def tearDown(self):
        build.WERKSTATT.clear()
        build.WERKSTATT.update(self.alt)

    def test_gemessener_eintrag_bekommt_eine_sprungmarke(self):
        html = build.render_markdown(self.QUELLE)
        self.assertRegex(html, r'<div class="entry entry--erlebt" id="[^"]+"')

    def test_die_sprungmarke_haengt_am_zeitstempel_nicht_am_text(self):
        """Ein Schluessel aus dem Text bricht, sobald ein Tippfehler behoben wird."""
        a = build.render_markdown(self.QUELLE)
        b = build.render_markdown(self.QUELLE.replace("Text drei.", "Text drei, korrigiert."))
        marken = re.findall(r'id="(eintrag-[^"]+)"', a)
        self.assertEqual(len(marken), 3, "ohne Marken vergleicht der Test zwei leere Listen")
        self.assertEqual(marken, re.findall(r'id="(eintrag-[^"]+)"', b))

    def test_neueste_meldung_steht_im_block_ganz_oben(self):
        block = build._zuletzt(build.render_markdown(self.QUELLE))
        reihenfolge = re.findall(r"(Erster|Zweiter|Dritter) Eintrag", block)
        self.assertEqual(reihenfolge, ["Dritter", "Zweiter", "Erster"])

    def test_datum_steht_einmal_nicht_zweimal(self):
        """Das Datum hat im Block eine eigene Spalte — im Satz waere es doppelt."""
        block = build._zuletzt(build.render_markdown(self.QUELLE))
        self.assertIn("Dritter Eintrag.", block)
        self.assertNotIn("Dritter Eintrag (18.08.).", block)

    def test_recherche_kommt_nicht_in_den_block(self):
        block = build._zuletzt(build.render_markdown(self.QUELLE))
        self.assertNotIn("Nachgeschlagen", block)

    def test_block_verlinkt_auf_den_eintrag_selbst(self):
        rumpf = build.render_markdown(self.QUELLE)
        block = build._zuletzt(rumpf)
        for ziel in re.findall(r'href="#(eintrag-[^"]+)"', block):
            self.assertIn(f'id="{ziel}"', rumpf)
        self.assertTrue(re.findall(r'href="#(eintrag-[^"]+)"', block))

    def test_ohne_messung_gar_kein_block(self):
        """Eine Seite ohne gemessene Meldung bekommt keine leere Ueberschrift."""
        self.assertEqual(build._zuletzt(build.render_markdown(
            "## Nur Recherche\n\n**○ Nachgeschlagen.** Text.\n")), "")

    def test_block_deckelt_die_zahl(self):
        viele = "# T\n\n## A\n\n" + "\n\n".join(
            f"**✓ Meldung {i} (18.08.).** Text.\n<!-- werkstatt: telegram=2026-08-18T{i:02d}:00 -->"
            for i in range(1, 9))
        for i in range(1, 9):
            build.WERKSTATT[f"2026-08-18T{i:02d}:00:00+00:00"] = {
                "telegram": f"2026-08-18T{i:02d}:00:00+00:00",
                "veroeffentlicht": f"2026-08-18T{i:02d}:10:00+00:00", "minuten": 10}
        block = build._zuletzt(build.render_markdown(viele))
        self.assertEqual(len(re.findall(r'href="#eintrag-', block)), 5)


class TestRechercheFaltung(unittest.TestCase):
    """Umbau 3 (Jens 2026-08-18 09:44).

    37 ○ gegen 28 ✓: die Seite verspricht „was funktioniert hat und was nicht" und
    besteht mehrheitlich aus Vorher-Gelesenem. Eingeklappt traegt das Erlebte
    die Seite — der Text bleibt, er ist einen Klick entfernt.
    """

    def test_mehrere_recherchen_hintereinander_werden_ein_kasten(self):
        html = build.falte_recherche(build.render_markdown(
            "## A\n\n**○ Eins.** Text.\n\n**○ Zwei.** Text.\n\n**○ Drei.** Text.\n"))
        self.assertEqual(html.count("<details"), 1)
        self.assertEqual(html.count('entry--recherche'), 3)

    def test_der_kasten_nennt_die_anzahl(self):
        html = build.falte_recherche(build.render_markdown(
            "## A\n\n**○ Eins.** Text.\n\n**○ Zwei.** Text.\n"))
        self.assertRegex(html, r"<summary[^>]*>[^<]*2[^<]*</summary>")

    def test_ein_erlebter_eintrag_trennt_zwei_kaesten(self):
        html = build.falte_recherche(build.render_markdown(
            "## A\n\n**○ Eins.** Text.\n\n**○ Zwei.** Text.\n\n"
            "**✓ Erlebt.** Text.\n\n**○ Drei.** Text.\n\n**○ Vier.** Text.\n"))
        self.assertEqual(html.count("<details"), 2)

    def test_eine_ueberschrift_trennt_zwei_kaesten(self):
        html = build.falte_recherche(build.render_markdown(
            "## A\n\n**○ Eins.** Text.\n\n**○ Zwei.** Text.\n\n"
            "## B\n\n**○ Drei.** Text.\n\n**○ Vier.** Text.\n"))
        self.assertEqual(html.count("<details"), 2)

    def test_eine_einzelne_recherche_bekommt_keinen_kasten(self):
        """Ein Kasten um einen Eintrag kostet einen Klick und spart nichts."""
        html = build.falte_recherche(build.render_markdown(
            "## A\n\n**✓ Erlebt.** Text.\n\n**○ Allein.** Text.\n\n**✓ Wieder.** Text.\n"))
        self.assertNotIn("<details", html)

    def test_erlebtes_wird_nie_eingeklappt(self):
        roh = build.render_markdown(
            "## A\n\n**✓ Eins.** Text.\n\n**✓ Zwei.** Text.\n\n**✗ Drei.** Text.\n")
        self.assertNotIn("<details", build.falte_recherche(roh))

    def test_kein_zeichen_geht_verloren(self):
        roh = build.render_markdown(
            "## A\n\n**○ Eins.** Text.\n\n**○ Zwei.** Text.\n\n**✓ Drei.** Text.\n")
        gefaltet = build.falte_recherche(roh)
        for wort in ("Eins", "Zwei", "Drei"):
            self.assertIn(wort, gefaltet)

    def test_umbrochene_absaetze_werden_trotzdem_gefaltet(self):
        """Der Fehler vom 18.08.: ein Block ist NICHT eine Zeile.

        Die Absaetze im Quelldokument sind umbrochen und `inline()` laesst den
        Umbruch stehen. Die erste Fassung faltete zeilenweise — an einzeiligen
        Testdaten gruen, auf der echten Seite null Kaesten. Dieser Test haelt
        die Faltung an mehrzeiligen Eintraegen fest.
        """
        md = ("## A\n\n"
              "**○ Erste Notiz.** Ein Satz, der im Quelldokument\n"
              "ueber drei Zeilen laeuft, weil das Dokument umbrochen\n"
              "geschrieben ist.\n\n"
              "**○ Zweite Notiz.** Auch diese hier laeuft\n"
              "ueber mehrere Zeilen.\n")
        roh = build.render_markdown(md)
        self.assertGreater(roh.count("\n"), 3, "Testdaten sind nicht mehrzeilig")
        html = build.falte_recherche(roh)
        self.assertEqual(html.count("<details"), 1)
        self.assertIn("Erste Notiz", html)
        self.assertIn("Zweite Notiz", html)

    def test_die_ausgelieferte_seite_klappt_die_recherche_ein(self):
        seite = (build.WURZEL / "index.html").read_text(encoding="utf-8")
        self.assertIn("<details", seite)
        self.assertIn('id="zuletzt"', seite)

    def test_beide_sprachfassungen_haben_beides(self):
        en = (build.WURZEL / "en" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<details", en)
        self.assertIn('id="zuletzt"', en)



class TestFehlschlaege(unittest.TestCase):
    """Umbau 2 (Jens 2026-08-18 09:44): „Sollten wir den Reiseblog nicht spannender gestalten?"

    Die Seite verspricht „was funktioniert hat und was nicht" und traegt am 18.08.
    genau **2 ✗** gegen 29 ✓ und 40 ○ — beide in ihrem Themenabschnitt vergraben.
    Das ist der Teil, den kein Reisefuehrer schreibt, und der einzige, der die
    anderen Haken glaubwuerdig macht. Deshalb steht er oben, nicht weil er
    haeufig waere.
    """

    QUELLE = ("# T\n\n## A\n\n"
              "**✓ Hat geklappt.** Text.\n\n"
              "**✗ Wechselstube schlaegt Automat — galt bei uns nicht.** Begruendung.\n\n"
              "## B\n\n"
              "**○ Nachgeschlagen.** Text.\n\n"
              "**✗ CelcomDigi liess sich online nicht kaufen.** Begruendung.\n")

    def test_jeder_gescheiterte_eintrag_bekommt_eine_sprungmarke(self):
        """Ohne id ist der Block nicht verlinkbar, und ✗ traegt keine Messung."""
        rumpf = build.render_markdown(self.QUELLE)
        self.assertEqual(rumpf.count('class="entry entry--gescheitert" id="'), 2)

    def test_der_block_nennt_beide_und_verlinkt_in_den_rumpf(self):
        rumpf = build.render_markdown(self.QUELLE)
        block = build._fehlschlaege(rumpf)
        ziele = re.findall(r'href="#([^"]+)"', block)
        self.assertEqual(len(ziele), 2)
        for ziel in ziele:
            self.assertIn(f'id="{ziel}"', rumpf)

    def test_nur_gescheitertes_kommt_hinein(self):
        block = build._fehlschlaege(build.render_markdown(self.QUELLE))
        self.assertNotIn("Hat geklappt", block)
        self.assertNotIn("Nachgeschlagen", block)

    def test_ohne_fehlschlag_gar_kein_block(self):
        """Eine leere Ueberschrift „Was nicht funktioniert hat" waere eine Luege."""
        self.assertEqual(build._fehlschlaege(build.render_markdown(
            "## A\n\n**✓ Alles gut.** Text.\n")), "")

    def test_die_marke_haengt_am_titel_nicht_am_fliesstext(self):
        """Ein geteilter Link darf nicht brechen, weil der Absatz nachgebessert wird."""
        a = build.render_markdown(self.QUELLE)
        b = build.render_markdown(self.QUELLE.replace("Begruendung.", "Begruendung, laenger."))
        marken = re.findall(r'class="entry entry--gescheitert" id="([^"]+)"', a)
        self.assertEqual(len(marken), 2, "ohne Marken vergleicht der Test zwei leere Listen")
        self.assertEqual(
            marken, re.findall(r'class="entry entry--gescheitert" id="([^"]+)"', b))

    def test_die_marke_bricht_kein_wort_ab(self):
        """`…-bei-u` liest sich wie ein Uebertragungsfehler, und die Marke
        landet in der Adresszeile, sobald jemand den Punkt weitergibt."""
        rumpf = build.render_markdown(
            "## A\n\n**✗ Ein sehr langer Titel mit vielen Woertern, der die "
            "Grenze von achtundvierzig Zeichen deutlich ueberschreitet.** Text.\n")
        marke = re.search(r'id="(fehl-[^"]+)"', rumpf).group(1)
        self.assertLessEqual(len(marke), 53)
        for wort in marke[len("fehl-"):].split("-"):
            self.assertIn(wort, build.slug(
                "Ein sehr langer Titel mit vielen Woertern, der die Grenze von "
                "achtundvierzig Zeichen deutlich ueberschreitet.").split("-"))

    def test_der_block_nennt_die_anzahl(self):
        block = build._fehlschlaege(build.render_markdown(self.QUELLE))
        # Die Zahl steht in einem eigenen <span> (sie traegt die Farbe des
        # Zeichens), also darf das Muster Verschachtelung zulassen.
        self.assertRegex(block, r"(?s)<h2[^>]*>.*?\b2\b.*?</h2>")

    def test_die_ausgelieferte_seite_traegt_den_block(self):
        for datei in (build.WURZEL / "index.html", build.WURZEL / "en" / "index.html"):
            with self.subTest(datei=f"{datei.parent.name}/{datei.name}"):
                seite = datei.read_text(encoding="utf-8")
                self.assertIn('id="fehlschlaege"', seite)
                for ziel in re.findall(r'href="#(fehl-[^"]+)"', seite):
                    self.assertIn(f'id="{ziel}"', seite)



class TestOrtsmarker(unittest.TestCase):
    """Ein Eintrag weiss, WO er passiert ist — aber nur, wenn es dasteht.

    Der Ort wird nicht aus dem Abschnitt geraten. "Essen", "Bezahlen" und
    "Strom" sind Themen, keine Orte, und die Eintraege darin stammen aus vier
    verschiedenen Staedten. Ein geratener Punkt auf einer Karte ist derselbe
    Fehler wie ein ✓ ohne Erlebnis: er sieht aus wie eine Messung.
    """

    def test_marker_wird_zu_data_ort(self):
        html = build.render_markdown(
            "**✓ Der Ort ist voller Katzen (17.08.).** Ueberall.\n"
            "<!-- ort: mersing -->")
        self.assertIn('data-ort="mersing"', html)

    def test_marker_steht_nicht_im_text(self):
        """Er ist Angabe, kein Satz — wie der Herkunftsmarker."""
        html = build.render_markdown(
            "**✓ Der Ort ist voller Katzen (17.08.).** Ueberall.\n"
            "<!-- ort: mersing -->")
        self.assertNotIn("ort:", html)
        self.assertNotIn("@@ORT", html)

    def test_eintrag_ohne_marker_traegt_kein_data_ort(self):
        html = build.render_markdown("**✓ Etwas hat geklappt.** Dazu ein Satz.")
        self.assertNotIn("data-ort", html)

    def test_marker_ueberlebt_neben_dem_herkunftsmarker(self):
        """Beide haengen am selben Eintrag und duerfen sich nicht fressen."""
        html = build.render_markdown(
            "**✓ Etwas hat geklappt (17.08.).** Dazu ein Satz.\n"
            "<!-- werkstatt: telegram=2026-08-17T06:21 -->\n"
            "<!-- ort: tioman -->")
        self.assertIn('data-ort="tioman"', html)
        self.assertNotIn("telegram=", html)

    def test_unbekannter_ort_bricht_den_build_ab(self):
        """Still verschluckt waere er ein Eintrag, der nie auf der Karte auftaucht,
        ohne dass jemand erfaehrt warum. Ein Tippfehler muss schreien."""
        with self.assertRaises(build.OrtException):
            build.render_markdown(
                "**✓ Etwas hat geklappt.** Dazu ein Satz.\n"
                "<!-- ort: tiomann -->")


class TestVerworfeneBearbeitung(unittest.TestCase):
    """Wer die Kopie bearbeitet, verliert die Arbeit — dann muss es dastehen.

    `content/erfahrungen*.md` ist eine Kopie. Jeder Lauf ohne `--no-sync`
    ueberschreibt sie aus `assistant/state/reise-erfahrungen-malaysia-2026*.md`.
    Eine Bearbeitung der Kopie verschwindet damit **ohne Fehlermeldung**, und
    `git status` zeigt die Datei danach als unveraendert — die Aenderung nimmt
    sich selbst zurueck.

    Am 26.08. ist das an einem Tag **zweimal** passiert. Der Vormittag fing es
    nur am Byte-Vergleich der `index.html`, der Nachmittag nur daran, dass die
    Stationszahl im Buildbericht nicht sprang, obwohl eine Station dazukam.
    Beide Male lag der Hinweis schon in `MEMORY.md`. Eine Notiz, die zweimal
    gegen die Absicht verliert, gehoert in den Code.

    Gemeldet, nicht verhindert: die Kopie darf abweichen, sobald die Quelle
    weitergeschrieben wurde — das ist der Normalfall vor jedem Sync. Gesucht
    wird nur, was **allein in der Kopie** steht.
    """

    def test_nur_in_der_kopie_stehende_zeile_wird_genannt(self):
        verloren = build.verworfene_zeilen(
            "**✓ Etwas hat geklappt (17.08.).** Dazu ein Satz.\n",
            "**✓ Etwas hat geklappt (17.08.).** Dazu ein Satz.\n"
            "<!-- ort: sepilok -->\n")
        self.assertEqual(["<!-- ort: sepilok -->"], verloren)

    def test_neue_zeile_in_der_quelle_ist_kein_verlust(self):
        """Der Normalfall vor jedem Sync — darf nicht melden."""
        self.assertEqual([], build.verworfene_zeilen(
            "alt\nneu aus der Quelle\n", "alt\n"))

    def test_gleichstand_meldet_nichts(self):
        self.assertEqual([], build.verworfene_zeilen("a\nb\n", "a\nb\n"))

    def test_leerzeilen_zaehlen_nicht_als_verlust(self):
        self.assertEqual([], build.verworfene_zeilen("a\nb\n", "a\n\n  \nb\n"))


class TestStationenGegenChronik(unittest.TestCase):
    """Steht in STATIONEN dieselbe Reise wie in der Chronik?

    Die Chronik ist die gepflegte Liste — Jens meldet einen Ortswechsel, die
    Tabelle wird nachgezogen. `STATIONEN` ist die zweite Kopie derselben
    Tatsache, und sie wird von Hand gefuehrt. Zwei Listen sind nach einer Woche
    zwei Listen.

    Gemessen am 26.08., beide Faelle echt: die Chronik trug seit dem 25.08.
    `26.-27.08. Sepilok` und `27.-29.08. Kinabatangan`, `STATIONEN` kannte
    beide nicht — neun ✓-Eintraege aus Sepilok konnten deshalb keinen
    `<!-- ort: … -->` tragen und fehlten auf der Karte, denn `ORTE` wird aus
    `STATIONEN` erzeugt und ein unbekannter Schluessel bricht den Build ab. Und
    `Sandakan` stand weiter auf `25.-28.08.`, obwohl die Buchung (AB26084033)
    eine einzige Nacht ausweist und die Chronik am 25.08. auf `25.-26.08.`
    korrigiert wurde. Die Korrektur erreichte die Chronik und `ortszeit.py`,
    nicht aber diese Liste.

    Gelesen wird die ausgelieferte Chronik, nicht eine Attrappe: ein
    Datenfehler ist in synthetischen Testdaten nicht sichtbar.

    Nur Zeilen mit **einem** Ort zaehlen. `→` und `·` trennen mehrere Orte in
    einer Zeile ("Frankfurt → Bahrain → Singapur", "Grenze nach Johor Bahru ·
    Larkin Sentral · Bus nach Mersing") — das sind Reisetage, keine Stationen,
    und aus ihnen eine Station abzuleiten hiesse Bahrain auf die Karte zu
    setzen.
    """

    QUELLE = Path(__file__).resolve().parent.parent / "content" / "erfahrungen.md"

    @classmethod
    def setUpClass(cls):
        cls.zeilen = cls._chronik(cls.QUELLE.read_text(encoding="utf-8"))
        if not cls.zeilen:
            raise AssertionError(
                f"Keine Chronik-Zeile in {cls.QUELLE} gefunden — der Test misst "
                "dann nichts und waere still gruen.")

    @staticmethod
    def _chronik(text: str) -> list[tuple[str, str]]:
        """(Datum, Ort) je Chronik-Zeile mit genau einem Ort.

        Gelesen wird **nur** die Tabelle unter `## Chronik`. Das Dokument
        enthaelt weitere Tabellen (Faehrzeiten, Packliste); ueber alle Zeilen
        mit `|` zu laufen holte beim ersten Lauf zehn angebliche Stationen wie
        "Geld holen" und "Ablegen" herein. Ein Test, der routinemaessig Unsinn
        meldet, wird nach drei Tagen nicht mehr gelesen.
        """
        rumpf = text.split("\n## Chronik", 1)
        if len(rumpf) != 2:
            return []
        rumpf = rumpf[1].split("\n## ", 1)[0]
        raus = []
        for zeile in rumpf.splitlines():
            if not zeile.startswith("|"):
                continue
            spalten = [s.strip() for s in zeile.strip("|").split("|")]
            if len(spalten) < 2:
                continue
            datum, wo = spalten[0], spalten[1]
            if datum in ("Datum", "") or set(datum) <= set("-: "):
                continue
            if "→" in wo or "·" in wo:
                continue
            raus.append((datum, wo.split(",")[0].strip()))
        return raus

    def test_jede_chronik_station_steht_in_stationen(self):
        bekannt = {name for name, *_ in build.STATIONEN}
        fehlend = sorted({wo for _, wo in self.zeilen if wo not in bekannt})
        self.assertEqual(
            [], fehlend,
            f"Die Chronik nennt {fehlend}, STATIONEN kennt sie nicht. Eintraege "
            "von dort koennen keinen <!-- ort: … --> tragen und fehlen auf der "
            "Karte.")

    def test_datumsspanne_der_station_stimmt_mit_der_chronik(self):
        """Die Notiz an der Station faengt mit der Spanne an, die die Chronik nennt."""
        nach_ort = {}
        for datum, wo in self.zeilen:
            nach_ort.setdefault(wo, []).append(datum)
        falsch = []
        for name, _lat, _lon, de, _en in build.STATIONEN:
            if name not in nach_ort or len(nach_ort[name]) != 1:
                continue                      # mehrfach besucht -> keine eine Spanne
            chronik = nach_ort[name][0]
            if not de.startswith(chronik):
                falsch.append(f"{name}: Karte {de!r}, Chronik {chronik!r}")
        self.assertEqual([], falsch, "Station und Chronik widersprechen sich: "
                                     + "; ".join(falsch))


class TestKarteErlebnisse(unittest.TestCase):
    """Die Karte war eine Route. Jetzt ist sie ein zweiter Weg in den Text.

    Jens' vierte Idee vom 18.08. 09:44: "Ein Punkt je ✓ mit Sprung zum
    Eintrag gibt einen zweiten Weg hinein, ueber den Ort statt ueber das
    Thema." Gebuendelt wird pro Station, nicht pro Eintrag: sieben Erlebnisse
    in Tekek haetten sonst sieben Punkte auf derselben Koordinate.
    """

    QUELLE = (
        "## Unterwegs\n\n"
        "**✓ In der Grenzhalle haengt die Wegweisung schon (17.08.).** Text dazu.\n"
        "<!-- werkstatt: telegram=2026-08-17T06:21 -->\n"
        "<!-- ort: johor-bahru -->\n\n"
        "**✓ Der Ort ist voller Katzen (17.08.).** Text dazu.\n"
        "<!-- werkstatt: telegram=2026-08-17T07:21 -->\n"
        "<!-- ort: mersing -->\n\n"
        "**○ Wechselstube schlaegt Geldautomat.** Nachgeschlagen.\n"
        "<!-- ort: mersing -->\n"
    )

    def rumpf(self):
        return build.render_markdown(self.QUELLE)

    def test_station_listet_ihre_erlebnisse(self):
        karte = build._karte(self.rumpf())
        self.assertIn("Der Ort ist voller Katzen", karte)
        self.assertIn("In der Grenzhalle", karte)

    def test_jeder_posten_springt_in_den_text(self):
        rumpf = self.rumpf()
        karte = build._karte(rumpf)
        ziele = re.findall(r'href="#([^"]+)"', karte)
        self.assertTrue(ziele, "kein einziger Sprung in den Text")
        for ziel in ziele:
            self.assertIn(f'id="{ziel}"', rumpf)

    def test_nur_selbst_erlebtes_kommt_auf_die_karte(self):
        """Recherche hat keinen Ort, an dem jemand gewesen waere."""
        karte = build._karte(self.rumpf())
        self.assertNotIn("Wechselstube", karte)

    def test_station_ohne_erlebnis_bleibt_stehen(self):
        """Die Linie ist die Reise. Ein Loch darin waere eine andere Reise."""
        karte = build._karte(self.rumpf())
        for name, *_ in build.STATIONEN:
            self.assertIn(name, karte)

    def test_die_zahl_steht_neben_der_station(self):
        karte = build._karte(self.rumpf())
        self.assertRegex(karte, r'(?s)Mersing.*?stationen-zahl[^>]*>\s*1\s*<')

    def test_javascript_kennt_die_erlebnisse(self):
        """Sonst zeigt das Popup einen Ort ohne einen Weg hinein."""
        karte = build._karte(self.rumpf())
        js = karte.split("var orte = ", 1)[1].split("\n", 1)[0]
        self.assertIn("Der Ort ist voller Katzen", js)

    def test_ohne_javascript_bleibt_die_liste(self):
        """Die Kartenkacheln laden erst auf Klick — ohne die Liste waere die
        Verbindung Ort → Eintrag fuer jeden weg, der nicht klickt."""
        karte = build._karte(self.rumpf())
        liste = karte.split('<ol class="stationen">', 1)[1]
        self.assertIn('href="#', liste)
        self.assertIn("Der Ort ist voller Katzen", liste)

    def test_die_ausgelieferte_seite_traegt_die_erlebnispunkte(self):
        """Gegen die Datei, nicht gegen den Renderer."""
        for datei in (build.WURZEL / "index.html", build.WURZEL / "en" / "index.html"):
            with self.subTest(datei=f"{datei.parent.name}/{datei.name}"):
                seite = datei.read_text(encoding="utf-8")
                block = seite.split('<ol class="stationen">', 1)[1].split("</ol>", 1)[0]
                ziele = re.findall(r'href="#([^"]+)"', block)
                self.assertTrue(ziele, "die Karte fuehrt in keinen einzigen Eintrag")
                for ziel in ziele:
                    self.assertIn(f'id="{ziel}"', seite)

    def test_beide_sprachen_tragen_gleich_viele_punkte(self):
        """Die englische Fassung findet ihre Orte ueber den Marker, nicht ueber
        den Text — waere es der Text, faende sie nichts, und zwar still."""
        zahlen = []
        for datei in (build.WURZEL / "index.html", build.WURZEL / "en" / "index.html"):
            seite = datei.read_text(encoding="utf-8")
            block = seite.split('<ol class="stationen">', 1)[1].split("</ol>", 1)[0]
            zahlen.append(len(re.findall(r'href="#', block)))
        self.assertEqual(zahlen[0], zahlen[1])

class TestFlugzeugwrack(unittest.TestCase):
    """Ein Foto von einem Wrack ist eine Beobachtung, keine Unfallgeschichte.

    Jens schickte am 19.08. ein zerlegtes Kleinflugzeug ohne ein Wort dazu.
    Zum Kennzeichen 9M-ZWP findet sich in Unfalldatenbanken, Registern und
    malaysischen Nachrichten nichts. Genau da entsteht der Fehler: die
    naechste Sitzung liest den Absatz, findet ein Kennzeichen und einen
    Flugplatz im selben Abschnitt und schreibt daraus einen Absturz.

    Der Test haelt deshalb BEIDE Haelften fest — das Kennzeichen und den
    Satz, dass es dazu keinen oeffentlichen Eintrag gibt. Faellt die zweite
    weg, sieht der Abschnitt vollstaendig aus und behauptet mehr, als
    gemessen ist.
    """

    def _seiten(self):
        return {
            "de": (build.WURZEL / "index.html").read_text(encoding="utf-8"),
            "en": (build.WURZEL / "en" / "index.html").read_text(encoding="utf-8"),
        }

    def test_das_kennzeichen_steht_auf_beiden_seiten(self):
        for sprache, seite in self._seiten().items():
            with self.subTest(sprache=sprache):
                self.assertIn("9M-ZWP", seite)

    def test_die_leere_suche_steht_daneben(self):
        """Ohne diesen Satz ist das Kennzeichen eine Identifikation."""
        marker = {"de": "keinen öffentlichen Eintrag", "en": "no public record"}
        for sprache, seite in self._seiten().items():
            with self.subTest(sprache=sprache):
                self.assertIn(marker[sprache], seite)

    def test_kein_absturz_behauptet(self):
        """Was mit der Maschine geschah, ist nicht gemessen — also steht es nicht da."""
        verboten = {"de": ("abgestuerzt", "Absturz", "verunglueckt"),
                    "en": ("crashed", "crash landing", "the accident")}
        for sprache, seite in self._seiten().items():
            abschnitt = seite.split("9M-ZWP", 1)[1][:1500]
            for wort in verboten[sprache]:
                with self.subTest(sprache=sprache, wort=wort):
                    self.assertNotIn(wort, abschnitt)


class TestKeinFlugAufDieInsel(unittest.TestCase):
    """Die praktische Halbhaelfte des Flugplatzes: es faehrt nur die Faehre.

    Der Flugplatz liegt mitten im Dorf, also liest sich „992 m Bahn" wie eine
    Ausweichmoeglichkeit. Es gibt keine — der letzte Anbieter hat am
    16.01.2025 eingestellt. Beide Zahlen gehoeren zusammen auf die Seite;
    steht nur die Bahnlaenge da, ist die Auskunft schlimmer als keine.
    """

    def test_bahn_und_einstellung_stehen_zusammen(self):
        for datei in (build.WURZEL / "index.html", build.WURZEL / "en" / "index.html"):
            seite = datei.read_text(encoding="utf-8")
            with self.subTest(datei=f"{datei.parent.name}/{datei.name}"):
                self.assertIn("992", seite)
                self.assertIn("2025", seite)
                self.assertIn("SKS Airways", seite)


class TestEinTitelFuerAlleFlaechen(unittest.TestCase):
    """Der Titel stand sechsmal im Repo — geaendert wird er an einer Stelle.

    Gefunden am 22.08., als Jens „Wir brauchen eine bessere Headline" schrieb.
    Die Ueberschrift lebte im Quelldokument, im `<title>`, im `og:title`, auf
    der Vorschaukarte und im Feed — je Sprache, also zehn Stellen fuer zwei
    Titel. Neun davon sind Kopien, die niemand mitzieht: wer die Ueberschrift
    im Quelldokument aendert, bekommt eine Seite mit dem neuen Titel, einen
    Browser-Reiter mit dem alten, eine WhatsApp-Vorschau mit dem alten und
    einen Feed mit dem alten.

    Sichtbar wird das genau beim Weitergeben, und das ist der einzige Zweck
    der Seite. Dieselbe Bauform hat die Adresse auf der Vorschaukarte schon
    einmal erwischt (17.08.): jede Pruefung ueber HTML war gruen, geteilt wird
    aber das Bild.
    """

    MD = "# Testtitel Alpha\n\nVorspann.\n\n## Erstes\n\n**✓ Etwas (17.08.).** Text.\n"

    def test_seitentitel_kommt_aus_der_ueberschrift(self):
        self.assertEqual("Testtitel Alpha", build.seiten_titel(self.MD))

    def test_quelle_ohne_ueberschrift_bricht_ab(self):
        # Kein stiller Ersatztitel: eine Seite, die „Titel" heisst, faellt
        # niemandem auf, bis sie geteilt wird.
        with self.assertRaises(ValueError):
            build.seiten_titel("Nur Text, keine Ueberschrift.\n")

    def test_browserreiter_folgt_der_quelle(self):
        self.assertIn("<title>Testtitel Alpha</title>", build.baue_seite(self.MD))

    def test_vorschau_folgt_der_quelle(self):
        self.assertIn('property="og:title" content="Testtitel Alpha"',
                      build.baue_seite(self.MD))

    def test_ueberschrift_im_text_folgt_der_quelle(self):
        self.assertIn("<h1>Testtitel Alpha</h1>", build.baue_seite(self.MD))

    def test_vorschaukarte_folgt_der_quelle(self):
        self.assertIn("Testtitel Alpha", build._og_karte({}, "Testtitel Alpha"))

    def test_feed_folgt_der_quelle(self):
        md = ("# Testtitel Alpha\n\n## Bezahlen\n\n"
              "**✓ Im Bus geht kontaktlos.** Ohne Vorbereitung.\n"
              "<!-- werkstatt: telegram=2026-08-17T04:41 -->\n")
        alt_w, build.WERKSTATT = build.WERKSTATT, {
            "2026-08-17T04:41:00+00:00": {
                "telegram": "2026-08-17T04:41:00+00:00",
                "veroeffentlicht": "2026-08-17T05:46:51+00:00",
                "minuten": 66,
            }
        }
        try:
            xml = build.baue_feed(md)
        finally:
            build.WERKSTATT = alt_w
        wurzel = ET.fromstring(xml)
        self.assertEqual("Testtitel Alpha",
                         wurzel.find("{http://www.w3.org/2005/Atom}title").text)

    def test_kein_titel_liegt_hartkodiert_neben_der_quelle(self):
        """Die eigentliche Sperre — sonst wandert der naechste Titel zurueck.

        Die Tests darueber pruefen, dass die Kopien der Quelle folgen. Sie
        bleiben aber gruen, wenn jemand den echten Titel zusaetzlich in eine
        Vorlage schreibt: solange beide gleich lauten, faellt nichts auf. Also
        wird hier gezaehlt, wo der ausgelieferte Titel ueberhaupt stehen darf.
        """
        titel = {s: build.seiten_titel(build.KOPIEN[s].read_text(encoding="utf-8"))
                 for s in build.SPRACHEN}
        dateien = [build.WURZEL / "build.py"]
        dateien += sorted((build.WURZEL / "template").glob("*.html"))
        for datei in dateien:
            inhalt = datei.read_text(encoding="utf-8")
            for sprache, wert in titel.items():
                with self.subTest(datei=datei.name, sprache=sprache):
                    self.assertNotIn(
                        wert, inhalt,
                        f"{datei.name} traegt den Titel ({sprache}) als Kopie. "
                        f"Er gehoert nur in {build.QUELLEN[sprache].name}.")

    def test_ausgelieferte_flaechen_tragen_denselben_titel(self):
        """Gegen die Dateien, die wirklich im Netz stehen, nicht gegen den Renderer.

        Ein Build, der die Seite neu schreibt und den Feed auslaesst, faellt
        sonst durch jede Pruefung: beide Wege sind fuer sich gruen.
        """
        for sprache in build.SPRACHEN:
            titel = build.seiten_titel(build.KOPIEN[sprache].read_text(encoding="utf-8"))
            seite = build.ZIELE[sprache].read_text(encoding="utf-8")
            with self.subTest(sprache=sprache):
                self.assertIn(f"<title>{titel}</title>", seite)
                self.assertIn(f'property="og:title" content="{titel}"', seite)
                self.assertIn(f"<h1>{titel}</h1>", seite)
                feed = build.FEED_DATEIEN[sprache]
                if feed.exists():
                    wurzel = ET.fromstring(feed.read_text(encoding="utf-8"))
                    self.assertEqual(
                        titel,
                        wurzel.find("{http://www.w3.org/2005/Atom}title").text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
