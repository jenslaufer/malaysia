#!/usr/bin/env python3
"""Erzeugt `karte-land.json` — die Kuestenlinie, die die Karte zeichnet.

Warum es diese Datei gibt: bis zum 20.08. holte die Karte ihre Bilder bei
tile.openstreetmap.org. Das traegt die IP jedes Lesers zu einem Dritten,
also stand ein Knopf davor ("Karte laden") und der Leser musste einwilligen.
Der Knopf war die Folge einer Annahme, die im Code stand — "eine Weltkarte
laesst sich nicht mitliefern". Die Reise braucht aber keine Weltkarte,
sondern einen Ausschnitt: Singapur bis Nordborneo. Der wiegt 52 KB.

Warum nicht einfach die Kacheln mitliefern: verboten. Die Tile Usage Policy
der OSM Foundation nennt "Pre-seeding large areas or multiple zoom levels in
advance" und "Building tile archives for later distribution" ausdruecklich
als Missbrauch (operations.osmfoundation.org/policies/tiles, gelesen
20.08.2026). Also keine Kacheln, sondern Vektoren aus einer Quelle, die das
erlaubt.

Quelle: Natural Earth 1:10m (ne_10m_land, ne_10m_minor_islands),
gemeinfrei — "no permission needed" (naturalearthdata.com/about/terms-of-use).
Deshalb faellt mit den Kacheln auch die Pflicht zur Namensnennung weg; die
Seite nennt die Quelle trotzdem.

Lauf: python3 karte-land.py   (laedt ~11 MB von GitHub, schreibt karte-land.json)
"""
import json
import math
import sys
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
ZIEL = WURZEL / "karte-land.json"

# Zwei Rechtecke, und der Unterschied ist der Grund fuer beide.
#
# KERN ist, was der Leser wirklich anschaut: Singapur bis Nordborneo. Hier
# zaehlt Genauigkeit — Tioman ist 15 km lang und eine der acht Stationen.
#
# WEIT ist der Hintergrund. Ohne ihn schneidet der Schnitt genau dort, wo die
# Karte hinschaut, und die Schnittkante steht als schnurgerade Linie quer
# durchs Bild (gemessen am 20.08. am gerenderten Bild, nicht am Test). Weit
# genug hinaus, und die Kante liegt ausserhalb der ersten Ansicht — weiter
# heraus kann der Leser nicht, `setMinZoom` haelt ihn.
KERN = (99.0, -2.0, 121.0, 9.5)
BBOX = (93.0, -8.0, 127.0, 17.0)

# Toleranz fuer grosse Landmassen (Grad, ~1,1 km). Kleine Inseln bekommen
# weniger, siehe unten.
TOLERANZ = 0.01
# Kleiner als das faellt weg (Quadratgrad, ~12 km²).
MIN_FLAECHE = 0.001

# Hintergrund darf grob sein. Mit denselben Werten wie im Kern waere die Datei
# 191 KB statt 58 — bezahlt fast nur mit Inseln der Philippinen und Indonesiens,
# die im Bild vier Pixel gross sind.
TOLERANZ_WEIT = 0.08
MIN_FLAECHE_WEIT = 0.02

QUELLEN = ("ne_10m_land", "ne_10m_minor_islands")
BASIS = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
         "master/geojson/")


def lade(name: str) -> dict:
    zwischen = Path("/tmp") / f"{name}.geojson"
    if not zwischen.exists():
        print(f"lade {name} …", file=sys.stderr)
        urllib.request.urlretrieve(BASIS + name + ".geojson", zwischen)
    return json.loads(zwischen.read_text())


def kreuz(a, b, i, grenze):
    t = (grenze - a[i]) / (b[i] - a[i])
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def schneide(pts, bbox):
    """Sutherland-Hodgman gegen das Rechteck.

    Ohne den Schnitt traegt die Datei ganz Afro-Eurasien mit: der Ring
    beruehrt das Fenster, also waere er drin. Gemessen am 20.08.: 6.433 von
    7.949 Punkten fuer Land, das nie im Bild ist — Faktor 5 auf die Datei.
    """
    lo0, la0, lo1, la1 = bbox
    for achse, grenze, richtung in (("x", lo0, 1), ("x", lo1, -1),
                                    ("y", la0, 1), ("y", la1, -1)):
        i = 0 if achse == "x" else 1
        if not pts:
            return []
        neu = []
        for k in range(len(pts)):
            a, b = pts[k - 1], pts[k]
            a_drin = (a[i] - grenze) * richtung >= 0
            b_drin = (b[i] - grenze) * richtung >= 0
            if b_drin:
                if not a_drin:
                    neu.append(kreuz(a, b, i, grenze))
                neu.append(b)
            elif a_drin:
                neu.append(kreuz(a, b, i, grenze))
        pts = neu
    return pts


def dp(pts, tol):
    """Douglas-Peucker in Grad. Genug fuer eine Uebersichtskarte."""
    if len(pts) < 3:
        return pts
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy)
    weit, wi = -1.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = (abs(dy * x - dx * y + x1 * y0 - y1 * x0) / n) if n else \
            math.hypot(x - x0, y - y0)
        if d > weit:
            weit, wi = d, i
    if weit > tol:
        return dp(pts[:wi + 1], tol)[:-1] + dp(pts[wi:], tol)
    return [pts[0], pts[-1]]


def flaeche(ring) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(s) / 2


def aussenringe(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def beruehrt(pts, box) -> bool:
    lo0, la0, lo1, la1 = box
    return any(lo0 <= x <= lo1 and la0 <= y <= la1 for x, y in pts)


def im_kern(p) -> bool:
    lo0, la0, lo1, la1 = KERN
    return lo0 <= p[0] <= lo1 and la0 <= p[1] <= la1


def gestaffelt(pts, tol_nah, tol_weit):
    """Genau im Kern, grob draussen — innerhalb DESSELBEN Rings.

    Eine Toleranz je Ring reicht nicht: die Landmasse Thailand–Malaysia hatte
    1.469 Punkte, davon 340 im Kern (gemessen 20.08.). Der Rest ist Hintergrund
    und wurde in derselben Genauigkeit bezahlt wie das, was der Leser ansieht.
    Also wird der Ring in Laeufe zerlegt und jeder Lauf einzeln vereinfacht.
    """
    laeufe, jetzt = [], None
    for punkt in pts:
        art = im_kern(punkt)
        if art != jetzt:
            laeufe.append([])
            jetzt = art
        laeufe[-1].append(punkt)
    raus = []
    for lauf in laeufe:
        # Ein Lauf startet, wo der vorige endete — sonst reisst die Kueste auf.
        if raus:
            lauf = [raus[-1]] + lauf
        tol = tol_nah if im_kern(lauf[-1]) else tol_weit
        vereinfacht = dp(lauf, tol)
        raus += vereinfacht[1:] if raus else vereinfacht
    return raus


def baue() -> list:
    sys.setrecursionlimit(100000)
    raus = []
    for name in QUELLEN:
        for feat in lade(name)["features"]:
            for ring in aussenringe(feat["geometry"]):
                pts = schneide([(x, y) for x, y in ring], BBOX)
                if len(pts) < 3:
                    continue
                # Im Kern genau, draussen grob. Eine Landmasse, die in den
                # Kern hineinragt, gilt als Kern — Sumatra liegt dem Leser
                # gegenueber und wird mitgelesen.
                nah = beruehrt(pts, KERN)
                if flaeche(pts) < (MIN_FLAECHE if nah else MIN_FLAECHE_WEIT):
                    continue
                xs = [x for x, _ in pts]
                ys = [y for _, y in pts]
                spanne = max(max(xs) - min(xs), max(ys) - min(ys))
                # Eine Insel darf nie grober werden als ein Zwanzigstel ihrer
                # eigenen Ausdehnung. Mit fester Toleranz 0,05 verschwand
                # Tioman — schmaler als die Toleranz, also fiel die Insel auf
                # eine Linie zusammen. Tioman ist Station 4 von 8.
                deckel = max(0.0015, spanne / 20)
                if nah:
                    fein = [[round(x, 3), round(y, 3)] for x, y in gestaffelt(
                        pts, min(TOLERANZ, deckel), min(TOLERANZ_WEIT, deckel))]
                else:
                    fein = [[round(x, 3), round(y, 3)] for x, y in dp(
                        pts, max(0.0015, min(TOLERANZ_WEIT, deckel)))]
                r = fein
                r = [r[0]] + [p for a, p in zip(r, r[1:]) if p != a]
                if len(r) < 4:
                    continue
                if r[0] != r[-1]:
                    r.append(r[0])
                raus.append(r)
    return raus


if __name__ == "__main__":
    flaechen = baue()
    blob = json.dumps(flaechen, separators=(",", ":"))
    ZIEL.write_text(blob)
    print(f"{ZIEL.name}: {len(flaechen)} Flaechen, "
          f"{sum(len(f) for f in flaechen)} Punkte, {len(blob)} B")
