"""ubox_lesen.py (04.10.2026, Claude)

Liest eine Universe-Sandbox-Datei (.ubox = ZIP mit JSON) und schreibt eine kleine
szene.json fuer universum_3d.html. Nur Standardbibliothek, kein Internet.

Aufruf:
    python ubox_lesen.py DATEI.ubox [ZIELORDNER]
    python ubox_lesen.py ORDNER_MIT_UBOX [ZIELORDNER]

Ohne Zielordner landet alles in ./szenen. Zusaetzlich wird szenen/liste.json
neu geschrieben (Liste aller Szenen fuer die Auswahl in der 3D-Ansicht).
Die Oberflaechen-Datei (*-surface.zip, mehrere 100 MB) wird nicht gelesen.
"""
import json
import os
import re
import sys
import zipfile

FORMAT = "auron-universum-1"
_ZAHL = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def vektor(text, n=3):
    """'1;2;3' -> [1.0, 2.0, 3.0]. Leer/kaputt -> Nullen."""
    try:
        teile = [float(x) for x in str(text).split(";")]
    except ValueError:
        return [0.0] * n
    return (teile + [0.0] * n)[:n]


def farbe(text):
    """'RGBA(0.3, 0.4, 0.5, 1.000)' oder '1;1;1;1' -> [r, g, b, a]."""
    werte = [float(x) for x in re.findall(_ZAHL, str(text or ""))]
    if len(werte) < 3:
        return [1.0, 1.0, 1.0, 1.0]
    if len(werte) == 3:
        werte.append(1.0)
    return [round(min(max(w, 0.0), 1.0), 3) for w in werte[:4]]


def _knapp(x, stellen=5):
    return float(f"{x:.{stellen}g}")


def _komponente(eintrag, typ):
    for k in eintrag.get("Components") or []:
        if k.get("$type") == typ:
            return k
    return None


def ausgewaehlt(pfad):
    """Id des im Spiel ausgewaehlten Koerpers (ui-state.json, 'Selector') oder None."""
    try:
        with zipfile.ZipFile(pfad) as z:
            for n in z.namelist():
                if n.endswith("-ui-state.json"):
                    ui = json.loads(z.read(n).decode("utf-8-sig"))
                    werte = list((ui.get("Selector") or {}).values())
                    return int(werte[0]) if werte else None
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return None


def simulation_aus_zip(pfad):
    """Holt die Haupt-JSON aus der .ubox (Name laut manifest.json)."""
    with zipfile.ZipFile(pfad) as z:
        namen = z.namelist()
        ziel = None
        if "manifest.json" in namen:
            man = json.loads(z.read("manifest.json").decode("utf-8-sig"))
            for e in man.get("Entries", []):
                if e.get("BaseType") == "Simulation" and e.get("Path") in namen:
                    ziel = e["Path"]
                    break
        if ziel is None:
            kandidaten = [n for n in namen if n.endswith(".json")
                          and not n.endswith(("-info.json", "-ui-state.json"))
                          and n != "manifest.json"]
            if not kandidaten:
                raise ValueError("Keine Simulations-JSON in der Datei gefunden")
            ziel = max(kandidaten, key=lambda n: z.getinfo(n).file_size)
        return json.loads(z.read(ziel).decode("utf-8-sig"))


def umwandeln(sim, quelle="", ziel_id=None):
    einst = sim.get("Settings") or {}
    ansicht = einst.get("View") or {}
    gruppen = {g.get("Id"): g for g in sim.get("Groups") or []}

    koerper, teilchen = [], {}
    for e in sim.get("Entities") or []:
        if e.get("Name") == "CameraDummy":
            continue
        mitglied = _komponente(e, "GalaxyMemberComponent")
        if mitglied is not None:
            gid = e.get("Group", 0)
            t = teilchen.setdefault(gid, {"galaxie": gid, "pos": [], "temp": [], "hell": [],
                                          "groesse": 0.0, "farbe": farbe(e.get("Color"))})
            t["pos"].append(vektor(e.get("Position")))
            t["temp"].append(int(mitglied.get("AverageStarTemperature") or 6000))
            t["hell"].append(_knapp(float(mitglied.get("Brightness") or 0.1), 3))
            pk = _komponente(e, "ParticleComponent") or {}
            t["groesse"] = max(t["groesse"], float(pk.get("Size") or mitglied.get("Radius") or 0))
            continue
        name = str(e.get("Name") or "")
        if name.startswith("UI_STRING:"):
            name = ""
        koerper.append({
            "id": e.get("Id"),
            "name": name or f"Objekt {e.get('Id')}",
            "art": e.get("Category") or "objekt",
            "pos": vektor(e.get("Position")),
            "v": vektor(e.get("Velocity")),
            "r": float(e.get("Radius") or 0),
            "masse": float(e.get("Mass") or 0),
            "farbe": farbe(e.get("Color")),
            "galaxie": e.get("Group", 0),
        })

    galaxien = []
    for gid, g in gruppen.items():
        if g.get("$type") != "Galaxy":
            continue
        loch = next((k for k in koerper if k["id"] == g.get("BlackHoleId")), None)
        t = teilchen.get(gid)
        if loch:
            mitte = list(loch["pos"])
        elif t and t["pos"]:
            mitte = [sum(p[i] for p in t["pos"]) / len(t["pos"]) for i in range(3)]
        else:
            mitte = [0.0, 0.0, 0.0]
        galaxien.append({
            "id": gid, "name": g.get("Name") or f"Galaxie {gid}", "mitte": mitte,
            "r": float(g.get("Radius") or 0), "arme": g.get("NumberOfArms", 0),
            "typ": g.get("Type", 0), "farbe": farbe(g.get("Color")),
        })

    # Teilchen relativ zur Galaxienmitte, knapp gerundet (spart Platz, Genauigkeit reicht)
    teilchen_liste = []
    for gid, t in teilchen.items():
        mitte = next((g["mitte"] for g in galaxien if g["id"] == gid), [0.0, 0.0, 0.0])
        flach = []
        for p in t["pos"]:
            flach.extend(_knapp(p[i] - mitte[i], 4) for i in range(3))
        teilchen_liste.append({"galaxie": gid, "mitte": mitte, "groesse": t["groesse"],
                               "farbe": t["farbe"], "pos": flach, "temp": t["temp"], "hell": t["hell"]})

    return {
        "format": FORMAT,
        "name": re.sub(r"\.ubox$", "", str(sim.get("Name") or "")) or os.path.splitext(os.path.basename(quelle))[0],
        "achsen": "unity",
        "quelle": os.path.basename(quelle),
        "build": (sim.get("Header") or {}).get("BuildRevision"),
        "kamera": {
            "ziel": ziel_id if ziel_id is not None else einst.get("CameraTargetId"),
            "abstand": float(einst.get("CameraTargetDistance") or 0),
            "fov": float(einst.get("CameraFOV") or 45),
        },
        "koerper_skala": float(ansicht.get("BodyScaleMultiplier") or 1),
        "koerper": koerper,
        "galaxien": galaxien,
        "teilchen": teilchen_liste,
    }


def datei_umwandeln(pfad, zielordner):
    szene = umwandeln(simulation_aus_zip(pfad), pfad, ausgewaehlt(pfad))
    os.makedirs(zielordner, exist_ok=True)
    stamm = os.path.splitext(os.path.basename(pfad))[0]
    stamm = re.sub(r"[^A-Za-z0-9_.-]+", "_", stamm).strip("_") or "szene"
    ziel = os.path.join(zielordner, stamm + ".json")
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(szene, f, ensure_ascii=False, separators=(",", ":"))
    return ziel, szene


def liste_schreiben(zielordner):
    eintraege = []
    for n in sorted(os.listdir(zielordner)):
        if not n.endswith(".json") or n == "liste.json":
            continue
        try:
            with open(os.path.join(zielordner, n), encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        if s.get("format") == FORMAT:
            eintraege.append({"datei": n, "name": s.get("name") or n,
                              "koerper": len(s.get("koerper", [])), "galaxien": len(s.get("galaxien", []))})
    with open(os.path.join(zielordner, "liste.json"), "w", encoding="utf-8") as f:
        json.dump(eintraege, f, ensure_ascii=False, indent=1)
    return eintraege


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    quelle = argv[1]
    ziel = argv[2] if len(argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "szenen")
    dateien = ([os.path.join(quelle, n) for n in sorted(os.listdir(quelle)) if n.lower().endswith(".ubox")]
               if os.path.isdir(quelle) else [quelle])
    fehler = 0
    for d in dateien:
        try:
            pfad, s = datei_umwandeln(d, ziel)
            print(f"OK {os.path.basename(d)} -> {os.path.basename(pfad)}: {len(s['koerper'])} Koerper, "
                  f"{len(s['galaxien'])} Galaxien, {sum(len(t['temp']) for t in s['teilchen'])} Galaxie-Teilchen")
        except Exception as ex:  # eine kaputte Datei soll die anderen nicht aufhalten
            fehler += 1
            print(f"FEHLER {os.path.basename(d)}: {ex}")
    liste_schreiben(ziel)
    print(f"ERGEBNIS={'OK' if not fehler else 'FEHLER'} ({len(dateien)} Dateien, {fehler} Fehler)")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
