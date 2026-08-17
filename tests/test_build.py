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

import re
import sys
import unittest
from pathlib import Path

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



if __name__ == "__main__":
    unittest.main(verbosity=2)
