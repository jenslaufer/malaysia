# jenslaufer.com/malaysia/

**Live unter `https://jenslaufer.com/malaysia/`** — GitHub Pages, Projektpfad, kein CNAME.
`malaysia.jenslaufer.com` löst nicht auf und ist bewusst aufgeschoben (Begründung unten unter
„Ausliefern"). Wer die Subdomain im Text findet, meint diesen Pfad.

Reisenotizen aus Singapur und Malaysia (August/September 2026), zum Weitergeben.
Statische Seite, gebaut aus einem Markdown-Dokument. Kein Framework, keine
Abhängigkeiten außer Leaflet (CDN) für die Karte.

Auftrag: Jens, 2026-08-17 — „We could create malaysia.jenslaufer.com. there we can
share our trip and details. But private info must hidden there (eg passport numbers
etc). You can maintain the site. You can also share maps there for the people.
It must be styled beautifully. In German. no ai slop."

## Die tragende Idee

Jeder Eintrag trägt ein Zeichen: **✓ selbst erlebt** · **○ nachgeschlagen** ·
**✗ hat nicht funktioniert**. Drei Wochen Recherche stehen gegen eine Handvoll
gemeldeter Erlebnisse — ohne die Trennung liest sich das Dokument nach einer Woche
als lauter Erfahrung, und **ein ✓ ohne Erlebnis entwertet jeden anderen Haken darin**.
Deshalb ist das Zeichen auch gestalterisch die Hauptsache: eigene Randspalte,
eigene Farbe, keine Bildflächen, keine Kacheln.

## Die Reihenfolge ist der Umbau, nicht das Layout

Jens am 18.08. 09:44: „Sollten wir den Reiseblog nicht spannender gestalten?"
Die Antwort war keine Design-Frage. **Kein Satz wurde umgeschrieben, gekürzt
oder gelöscht** — es wurde nur sortiert, und das an drei Stellen:

| Block | Was er zeigt | Warum |
|---|---|---|
| `#zuletzt` (`_zuletzt`) | die 5 jüngsten **✓** mit Bild, Datum, Sprungmarke | die frischen Einträge liegen in ihrem Themenabschnitt; wer nach zwei Tagen wiederkommt, findet nicht, was neu ist |
| `#fehlschlaege` (`_fehlschlaege`) | **alle ✗**, ungedeckelt | 2 gegen 69: wer überfliegt, sieht lauter Haken und keinen Reinfall — das liest sich glatter, als es war |
| `<details>` (`falte_recherche`) | ≥2 aufeinanderfolgende **○** in einem Kasten | die Seite verspricht „was wirklich funktioniert hat" und bestand mehrheitlich aus Vorher-Gelesenem |

Sprungmarken: **✓** hängt am Telegram-Zeitstempel (siehe unten), **✗** am
eigenen Titel (`fehl-…`, an der Wortkante gekürzt) — ein ✗ hat keine Messung,
weil gerade nichts von Telegram bis zur Seite gelaufen ist. Beide Marken
entstehen im selben Build wie der Link darauf, können also nicht ins Leere
zeigen; ein Test hält das gegen die **ausgelieferte** Datei fest, nicht gegen
den Renderer.

## Die Verbindung zu /otto/ ist eine Messung, kein Link

Die Seite ist zugleich Reisebericht und Arbeitsprobe: sie entsteht drei Wochen
lang ausschließlich aus Telegram-Nachrichten, während Jens ohne Rechner
unterwegs ist. Ein Link auf [jenslaufer.com/otto](https://jenslaufer.com/otto/)
würde das behaupten. Belegt wird es durch die Zeit, die unter jedem selbst
erlebten Eintrag steht:

    Telegram 17.08. 04:41  →  auf dieser Seite 17.08. 05:46   66 Min

Herkunft steht im Quelldokument, direkt unter dem Eintrag und ohne Leerzeile:

    <!-- werkstatt: telegram=2026-08-17T06:21 -->

Gemessen wird nicht hier, sondern in `~/repos/assistant/tools/reise-werkstatt.py`:
Telegram-Zeitstempel gegen den **ersten Commit dieses Repos**, der den Eintrag
in `content/erfahrungen.md` gebracht hat. Der Build holt nur das Ergebnis nach
`content/werkstatt.json`. Beide Seiten lesen dieselbe Datei — zwei Seiten mit
zwei eigenen Zahlen wären nach einer Woche zwei verschiedene Zahlen.

Der Marker gehört **nur** an Einträge, die Jens selbst gemeldet hat. Ein aus
zwei Zeitstempeln abgeleiteter Wert (die 33 MRT-Minuten) bekommt keinen, sonst
misst die Zahl die eigene Rechenzeit statt der Reaktionszeit. Fehlt die Messung,
fällt die Zeile weg und das Band verschwindet — eine 0 wäre die schnellste Zahl
der Seite und hieße „nicht gemessen".

## Quelle und Build

Die Inhalte werden **nicht hier** gepflegt, sondern in

    ~/repos/assistant/state/reise-erfahrungen-malaysia-2026.md

Dort trägt die Sitzung ein, was Jens aus dem Urlaub meldet (Routine in
`state/routines.md`). `build.py` holt sich eine Kopie nach `content/erfahrungen.md`
und rendert `index.html`.

```bash
python3 build.py            # Quelle holen + index.html bauen
python3 build.py --no-sync  # nur aus content/erfahrungen.md bauen
python3 build.py --check    # nichts schreiben, nur Datenschutz prüfen
python3 tests/test_build.py # Tests (Zahl im Lauf, nicht hier — sie altert)
```

Eine Markdown-Bibliothek wäre hier die falsche Wahl: sie macht aus dem Zeichen
fetten Fließtext. Der Renderer in `build.py` kennt genau die Formen, die im
Dokument vorkommen, und macht aus dem Zeichen Auszeichnung.

## Benachrichtigungen: ein Feed, kein Push

Auftrag Jens 2026-08-17 10:43: „Können wir Website Notifications einstellen, so
dass Leute über Neuerungen informiert werden?"

Browser-Push scheidet aus. Auf dem iPhone geht es nur, wenn der Leser die Seite
vorher auf den Startbildschirm legt, und es braucht einen Server, der Pushes
verschickt — diese Seite hat keinen. Atom braucht beides nicht: `feed.xml` liegt
neben `index.html`, `en/feed.xml` neben der englischen Fassung.

    python3 build.py       # baut beide Seiten und beide Feeds

**Im Feed steht nur, was gemessen ist.** Ein Eintrag ohne Messung hätte kein
Datum, und ein erfundenes wäre schlimmer als sein Fehlen — der Leser bekäme eine
Meldung über etwas, das nicht passiert ist. Recherche (`○`) steht deshalb auf der
Seite und nicht im Feed; gemeldet wird, was Jens erlebt hat. Gibt es **gar keine**
Messung, wird nichts geschrieben und die alte Datei bleibt stehen: ein leerer Feed
sieht bei jedem Leser aus wie eine ruhige Woche.

**Die `id` hängt am Zeitstempel der Nachricht und am Abschnitt, nie am Text.**
Ein Schlüssel aus dem Inhalt bricht, sobald der Inhalt sich ändert — dann meldet
ein korrigierter Tippfehler denselben Eintrag ein zweites Mal. Der Abschnitt muss
mit hinein, weil eine Nachricht mehrere Einträge auslösen kann: Jens schickte am
17.08. um 10:21 drei Fotos, zwei Einträge trugen denselben Zeitstempel, und **zwei
gleiche ids lassen den zweiten Eintrag bei jedem Leser verschwinden**. Gefunden im
ausgelieferten Feed, nicht im Test. Doppelt zugestellt ist laut und heilbar, gar
nicht zugestellt ist keins von beidem.

`baue_feed` ruft `pruefe_privat` selbst auf, vorne auf der Quelle und hinten auf
dem fertigen XML. Ein zweiter Ausgabeweg, der die Sperre nicht kennt, hätte die
Datenschutzprüfung nicht umgangen, sondern verdoppelt — einmal mit, einmal ohne.

E-Mail-Anmeldung ist der zweite Teil des Auftrags und noch nicht gebaut; sie
braucht einen Mandanten auf launch-kit und läuft über dessen Lead-Capture.

## Fotos

Im Quelldokument steht eine Bildzeile als eigener Absatz:

    ![Eine schwarze Katze liegt im Schatten unter einem Marktwagen.](foto:2026-08-17_085957.jpg)

Mehrere Zeilen direkt untereinander werden **eine Gruppe** (Bilderreihe), eine
einzelne Zeile ein Bild in Satzbreite. Der Dateiname ist der aus
`state/attachments/` im Assistenz-Repo — also der, unter dem Telegram das Bild
abgelegt hat. Was daraus veröffentlicht wird, steht in `content/fotos.json`:
Zielname, Sperrkästen, Bildausschnitt.

**Kopiert wird nie, es wird neu geschrieben.** Das ist der ganze Punkt:
`pruefe_privat()` liest Text, und die Standortdaten eines Fotos stehen in
keinem Satz. Ein Bild mit GPS-Koordinaten läuft an jeder Textprüfung vorbei,
ist auf der gerenderten Seite unsichtbar und sagt Fremden, vor welchem Haus die
Familie gerade steht. Telegram wirft das EXIF beim Komprimieren zwar selbst weg
(am 17.08. an allen zwölf Bildern nachgemessen) — aber das ist Telegrams
Eigenschaft, nicht unsere: dasselbe Foto **als Datei** geschickt behält alles.
Also schreibt der Build jedes Bild neu, ohne EXIF, ohne Farbprofil, begrenzt auf
1280 px.

`blur` sind **relative** Kästen `[x, y, breite, höhe]` von 0 bis 1 — sie
überleben das Verkleinern; absolute Pixel zeigen nach dem Skalieren woanders
hin, und zwar lautlos. Darin liegen die Kfz-Kennzeichen Fremder und erkennbare
Gesichter. Die Liste ist **von Hand gepflegt, und das ist Absicht**: ein
Erkenner, der drei von vier Kennzeichen findet, liest sich wie Schutz und ist
keiner. Nach jeder Änderung das Bild ansehen, nicht nur den Test — am 17.08.
lagen drei von vier Kästen zu tief und ein ganzer Satz Roller-Kennzeichen war
übersehen, sichtbar erst mit eingezeichneten Rahmen über dem Original.

`position: "top"` steuert den Bildausschnitt in der Gruppe. Beim hochkanten Foto
des Geldautomaten steht die Aussage — die laufende Abfrage auf dem Schirm —
oben; mittig zugeschnitten war das Bild noch da und sein Inhalt weg.

## Datenschutz ist im Build verdrahtet, nicht im Kopf

`pruefe_privat()` bricht den Build ab, wenn Passnummern, IBANs, E-Mail-Adressen,
Telefonnummern oder ein gesperrtes Wort im Text stehen. Es wird dann **nichts**
geschrieben — lieber ein Fehlalarm als eine Passnummer im Netz. HTML-Kommentare
(der Pflegeblock am Fuß des Quelldokuments) erreichen die Seite nie.

**Die Sperrliste liegt bewusst nicht in diesem Repo**, sondern in
`~/repos/assistant/state/oeffentlich-gesperrt.txt`. Dieses Repo ist public, und
eine Sperrliste ist per Definition die Liste genau der Wörter, die niemand sehen
soll — sie neben die Seite zu legen, veröffentlicht sie. Genau so stand hier am
17.08. einen Tag lang die MDAC-PIN im Klartext, im Schutzcode selbst. Fehlt oder
leer → Abbruch. Neue Buchungscodes und PINs gehören in diese Datei.

Daneben `state/oeffentlich-warnung.txt`: **nur Meldung, kein Abbruch**. Sie
enthält die Familiennamen. Ein Abbruch hätte die Seite stillgelegt, für die eine
laufende Routine schreibt, und wer auf einer Familienseite vorkommt, entscheidet
Jens (offen als `#204`). Ein Wächter, dessen einzige Antwort „Abbruch" ist, wird
umgangen.

## Ausliefern

GitHub Pages aus `main`, Wurzel des Repos. `.nojekyll` verhindert die
Jekyll-Verarbeitung.

**Die eigene Domain ist bewusst noch nicht eingetragen.** `jenslaufer.com` hat
lebende MX-Einträge (mxa/mxb.mailgun.org); die Namecheap-Schnittstelle schreibt
beim Ändern den ganzen Record-Satz neu und hat dabei schon einmal `EmailType`
verloren — das killt die Mail. Während einer laufenden Reise, an der Bahn- und
Buchungsbestätigungen hängen, kauft dieses Risiko nichts: die Seite ist unter der
`github.io`-Adresse sofort sichtbar. DNS kommt zuletzt und auf Jens' Wort.

Dann: CNAME-Record `malaysia` → `jenslaufer.github.io` (wie `cv` und `concepts`),
Datei `CNAME` mit `malaysia.jenslaufer.com` ins Repo, Pages-Einstellung nachziehen.
