"""standard_szene.py (04.10.2026, Claude)

Schreibt szenen/Milchstrasse.json: Sonnensystem (echte Groessen und mittlere Abstaende,
Kreisbahnen, Winkel frei gewaehlt) in einer per Rechnung erzeugten Milchstrasse,
dazu Andromeda, M33 und die Magellanschen Wolken (Richtung und Entfernung gerundet).
Die Galaxien selbst erzeugt universum_3d.html aus den Kennwerten ("prozedural").

Werte aus allgemeinem Wissen, gerundet - keine Messdaten-Datei.
"""
import json
import math
import os

AE = 1.495978707e11
KPC = 3.0857e19
LJ = 9.4607e15
G = 6.674e-11
MSONNE = 1.989e30

# Name, Art, Radius km, mittlerer Abstand AE, Masse kg, Farbe, Startwinkel Grad
PLANETEN = [
    ("Merkur", "planet", 2439.7, 0.387, 3.30e23, (0.62, 0.60, 0.58), 40),
    ("Venus", "planet", 6051.8, 0.723, 4.87e24, (0.92, 0.82, 0.62), 160),
    ("Erde", "planet", 6371.0, 1.000, 5.97e24, (0.30, 0.45, 0.75), 250),
    ("Mars", "planet", 3389.5, 1.524, 6.42e23, (0.80, 0.42, 0.25), 300),
    ("Jupiter", "planet", 69911, 5.203, 1.90e27, (0.85, 0.75, 0.62), 20),
    ("Saturn", "planet", 58232, 9.537, 5.68e26, (0.90, 0.82, 0.60), 110),
    ("Uranus", "planet", 25362, 19.19, 8.68e25, (0.62, 0.85, 0.90), 200),
    ("Neptun", "planet", 24622, 30.07, 1.02e26, (0.35, 0.50, 0.95), 330),
]

# Name, Typ, Radius Lichtjahre, Entfernung Lichtjahre, galakt. Laenge l, Breite b, Arme, Sterne-Anteil
NACHBARN = [
    ("Andromeda (M31)", "spirale", 110000, 2.5e6, 121.2, -21.6, 2, 1.0),
    ("Dreiecksnebel (M33)", "spirale", 30000, 2.73e6, 133.6, -31.3, 2, 0.35),
    ("Grosse Magellansche Wolke", "unregel", 7000, 1.6e5, 280.5, -32.9, 1, 0.25),
    ("Kleine Magellansche Wolke", "unregel", 3500, 2.0e5, 302.8, -44.3, 0, 0.15),
]


def galaktisch(l_grad, b_grad):
    """Richtung (l, b) -> Szenen-Achsen (Y nach oben, Milchstrasse in der X-Z-Ebene)."""
    l, b = math.radians(l_grad), math.radians(b_grad)
    gx, gy, gz = math.cos(b) * math.cos(l), math.cos(b) * math.sin(l), math.sin(b)
    return [gx, gz, -gy]


def drehe_x(v, grad):
    w = math.radians(grad)
    return [v[0], v[1] * math.cos(w) - v[2] * math.sin(w), v[1] * math.sin(w) + v[2] * math.cos(w)]


def erzeugen():
    sonne_pos = [-8.2 * KPC, 0.02 * KPC, 0.0]  # Mitte der Milchstrasse = Ursprung
    plus = lambda a, b: [a[i] + b[i] for i in range(3)]
    koerper = [{"id": 1, "name": "Sonne", "art": "star", "pos": sonne_pos, "v": [0, 0, 0],
                "r": 696340e3, "masse": MSONNE, "farbe": [1.0, 0.93, 0.80, 1], "galaxie": 1}]
    erde = None
    for i, (name, art, r_km, a_ae, m, f, wink) in enumerate(PLANETEN):
        w = math.radians(wink)
        rel = drehe_x([math.cos(w) * a_ae * AE, 0.0, math.sin(w) * a_ae * AE], 60)  # Ekliptik ~60 Grad geneigt
        vb = math.sqrt(G * MSONNE / (a_ae * AE))
        vel = drehe_x([-math.sin(w) * vb, 0.0, math.cos(w) * vb], 60)
        k = {"id": 10 + i, "name": name, "art": art, "pos": plus(sonne_pos, rel), "v": vel,
             "r": r_km * 1e3, "masse": m, "farbe": list(f) + [1], "galaxie": 1}
        koerper.append(k)
        if name == "Erde":
            erde = k
    mond_rel = drehe_x([384400e3, 0.0, 0.0], 65)
    mond_v = plus(erde["v"], drehe_x([0.0, 0.0, 1022.0], 65))  # 1,022 km/s um die Erde
    koerper.append({"id": 30, "name": "Mond", "art": "moon", "pos": plus(erde["pos"], mond_rel), "v": mond_v,
                    "r": 1737.4e3, "masse": 7.35e22, "farbe": [0.68, 0.68, 0.68, 1], "galaxie": 1})
    koerper.append({"id": 40, "name": "Sagittarius A*", "art": "blackhole", "pos": [0.0, 0.0, 0.0], "v": [0, 0, 0],
                    "r": 1.2e10, "masse": 8.5e36, "farbe": [0, 0, 0, 1], "galaxie": 1})

    galaxien = [{"id": 1, "name": "Milchstrasse", "mitte": [0.0, 0.0, 0.0], "r": 15 * KPC, "arme": 4,
                 "typ": "balken", "farbe": [1, 1, 1, 1], "prozedural": True, "normale": [0, 1, 0],
                 "sterne": 1.0, "samen": 7}]
    for j, (name, typ, r_lj, d_lj, l, b, arme, anteil) in enumerate(NACHBARN):
        richt = galaktisch(l, b)
        # Abstand von der Sonne aus, Mitte relativ zum Ursprung
        mitte = [sonne_pos[i] + richt[i] * d_lj * LJ for i in range(3)]
        neig = drehe_x([0.0, 1.0, 0.0], 35 + 25 * j)  # Scheibenlage frei gewaehlt
        galaxien.append({"id": 2 + j, "name": name, "mitte": mitte, "r": r_lj * LJ, "arme": arme, "typ": typ,
                         "farbe": [1, 1, 1, 1], "prozedural": True, "normale": neig, "sterne": anteil,
                         "samen": 11 + j})
    return {
        "format": "auron-universum-1",
        "name": "Milchstrasse",
        "quelle": "standard_szene.py",
        "achsen": "rechts",
        "kamera": {"ziel": 12, "abstand": 4.0e7, "fov": 45},
        "koerper_skala": 1.0,
        "koerper": koerper,
        "galaxien": galaxien,
        "teilchen": [],
    }


if __name__ == "__main__":
    ziel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "szenen")
    os.makedirs(ziel, exist_ok=True)
    with open(os.path.join(ziel, "Milchstrasse.json"), "w", encoding="utf-8") as f:
        json.dump(erzeugen(), f, ensure_ascii=False, indent=0)
    print("OK szenen/Milchstrasse.json")
