# malaysia.jenslaufer.com

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
python3 tests/test_build.py # 33 Tests
```

Eine Markdown-Bibliothek wäre hier die falsche Wahl: sie macht aus dem Zeichen
fetten Fließtext. Der Renderer in `build.py` kennt genau die Formen, die im
Dokument vorkommen, und macht aus dem Zeichen Auszeichnung.

## Datenschutz ist im Build verdrahtet, nicht im Kopf

`pruefe_privat()` bricht den Build ab, wenn Passnummern, IBANs, E-Mail-Adressen,
Telefonnummern oder ein Token aus `GEHEIME_TOKEN` im Text stehen. Es wird dann
**nichts** geschrieben — lieber ein Fehlalarm als eine Passnummer im Netz.
HTML-Kommentare (der Pflegeblock am Fuß des Quelldokuments) erreichen die Seite nie.

Neue Buchungscodes oder PINs gehören in `GEHEIME_TOKEN` in `build.py`.

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
