import math, random
random.seed(7)
W, H = 1500, 1060
CX, CY = 640, 492
SX = 1.22  # Insel ist breiter als hoch

def r_insel(t):
    r = 300 * (1 + 0.09*math.sin(2*t+0.6) + 0.06*math.sin(3*t+2.1) + 0.05*math.sin(5*t+0.3) + 0.025*math.sin(9*t+1.7))
    def beule(mitte, breite, hoehe):
        d = math.atan2(math.sin(t-mitte), math.cos(t-mitte))
        return hoehe*math.exp(-(d/breite)**2)
    r *= 1 + beule(math.radians(38), 0.16, 0.30)      # Neon-Kap (NO)
    r *= 1 + beule(math.radians(-90), 0.10, -0.13)    # Hafenbucht (S)
    r *= 1 + beule(math.radians(185), 0.22, 0.14)     # Westhalbinsel
    r *= 1 + beule(math.radians(-20), 0.08, -0.08)    # kleine Bucht SO
    r *= 1 + beule(math.radians(118), 0.07, -0.07)    # Fjord N
    return r

PH = [(random.uniform(0, 6.28), k) for k in (13, 17, 23, 31, 41, 53)]
def zack(t, f=1.0):
    return 1 + f*sum((0.018/(i+1)**0.6)*math.sin(k*t+p) for i, (p, k) in enumerate(PH))

def pt(t, r, cx=CX, cy=CY, sx=SX):
    return (cx + r*math.cos(t)*sx, cy - r*math.sin(t))

def poly(fn, n=900):
    pts = [fn(2*math.pi*i/n) for i in range(n)]
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"

kueste = poly(lambda t: pt(t, r_insel(t)*zack(t)))
flach = poly(lambda t: pt(t, r_insel(t)*zack(t)*1.07 + 6))
huegel = poly(lambda t: pt(t, r_insel(t)*zack(t, 1.6)*0.66))
hoch = poly(lambda t: pt(t, r_insel(t)*zack(t, 2.2)*0.40))
plateau = poly(lambda t: pt(t, 128*(1+0.05*math.sin(5*t+.7)+0.03*math.sin(8*t+2)), sx=1.0))

def bogen(von, bis):
    pts = []
    a, b = math.radians(von), math.radians(bis)
    for i in range(121):
        t = a + (b-a)*i/120
        pts.append(pt(t, r_insel(t)*zack(t)))
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)

klippen = [bogen(70, 215), bogen(-8, 22)]
straende = [bogen(-140, -100), bogen(-80, -40), bogen(220, 250)]

def ort(winkel, anteil):
    t = math.radians(winkel)
    return pt(t, r_insel(t)*anteil)

# Nebeninseln
g_t = math.radians(142); g_c = pt(g_t, r_insel(g_t)*1.0 + 215)
gehirn = poly(lambda t: pt(t, 92*(1+0.12*math.sin(3*t+1)+0.06*math.sin(5*t))*zack(t, 1.3), g_c[0], g_c[1], 1.15))
gehirn_flach = poly(lambda t: pt(t, 92*(1+0.12*math.sin(3*t+1)+0.06*math.sin(5*t))*zack(t, 1.3)*1.12+5, g_c[0], g_c[1], 1.15))
tr_t = math.radians(-33); tr_c = pt(tr_t, r_insel(tr_t) + 300)
trading = poly(lambda t: pt(t, 36*(1+0.2*math.sin(4*t+.4))*zack(t, 2), tr_c[0], tr_c[1], 1.0))
trading_flach = poly(lambda t: pt(t, 36*(1+0.2*math.sin(4*t+.4))*zack(t, 2)*1.2+4, tr_c[0], tr_c[1], 1.0))
klein = []
for (w, d, rr) in [(100, 120, 14), (205, 95, 18), (-120, 90, 11), (60, 60, 9), (250, 140, 12)]:
    t = math.radians(w); c = pt(t, r_insel(t)+d)
    klein.append(poly(lambda tt, c=c, rr=rr: pt(tt, rr*(1+0.25*math.sin(3*tt))*zack(tt, 3), c[0], c[1], 1.1), 120))

STATUS = {"laeuft": "#3fbf6a", "wartet": "#e2b33c", "aus": "#8a8f98"}
TUERME = [  # Winkel, Name, Status, Bauform
    (90, "Haupt-PC", "laeuft", "Glasturm"),
    (30, "Mini-PC", "laeuft", "Funkturm"),
    (150, "Nachtarbeit", "wartet", "Sternwarte"),
    (210, "Test-PC", "laeuft", "Werkstattturm"),
    (270, "Sicherheit", "wartet", "Torturm"),
    (330, "Kosten", "laeuft", "Münzturm"),
]
REGIONEN = [  # Winkel, Anteil, Name, Ortsname, Status, Symbol
    (-90, 0.80, "Briefing &amp; Gmail", "Hafenstadt", "laeuft"),
    (2, 0.70, "Kalender", "Sonnenuhr-Tal", "laeuft"),
    (184, 0.70, "Aufgaben-Loop", "Mühlenebene", "wartet"),
    (38, 0.86, "TikTok", "Neon-Kap", "wartet"),
]

o = []
o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Segoe UI, Arial, sans-serif">')
o.append('''<defs>
<radialGradient id="meer" cx="45%" cy="50%" r="75%"><stop offset="0" stop-color="#1d6f86"/><stop offset=".6" stop-color="#124a63"/><stop offset="1" stop-color="#0a2a3d"/></radialGradient>
<radialGradient id="krone" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#fff6c8"/><stop offset=".45" stop-color="#f3c74f" stop-opacity=".95"/><stop offset="1" stop-color="#f3c74f" stop-opacity="0"/></radialGradient>
<pattern id="fels" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="8" stroke="#5c5a4c" stroke-width="1.2" opacity=".35"/></pattern>
<filter id="schatten" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000" flood-opacity=".35"/></filter>
<style>
.t{paint-order:stroke;stroke:#0b1d28;stroke-width:3.5px;stroke-linejoin:round;fill:#fff}
.k{font-size:13px;font-weight:600}.g{font-size:11px;fill:#d7e6ee}
.ort{font-size:15px;font-weight:700}.klein{font-size:11px}
</style></defs>''')
o.append(f'<rect width="{W}" height="{H}" fill="url(#meer)"/>')
# Wellenlinien
for i in range(26):
    y = 30 + i*40
    o.append(f'<path d="M0,{y} q 40,-6 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0 t 80,0" fill="none" stroke="#ffffff" stroke-opacity=".035"/>')
# Flachwasser
for p in [flach, gehirn_flach, trading_flach]:
    o.append(f'<path d="{p}" fill="#2a95a6" opacity=".55"/>')
# Inseln
o.append(f'<path d="{kueste}" fill="#6f9a52" filter="url(#schatten)"/>')
o.append(f'<path d="{huegel}" fill="#5b8644"/>')
o.append(f'<path d="{hoch}" fill="#8c8a72"/><path d="{hoch}" fill="url(#fels)"/>')
for s in straende:
    o.append(f'<path d="{s}" fill="none" stroke="#e9d9a6" stroke-width="7" stroke-linecap="round"/>')
for k in klippen:
    o.append(f'<path d="{k}" fill="none" stroke="#4d483d" stroke-width="9" stroke-linejoin="round"/><path d="{k}" fill="none" stroke="#7d7768" stroke-width="3"/>')
o.append(f'<path d="{gehirn}" fill="#8d7bbd" filter="url(#schatten)"/>')
o.append(f'<path d="{trading}" fill="#7d7a6c" filter="url(#schatten)"/><path d="{trading}" fill="url(#fels)"/>')
for k in klein:
    o.append(f'<path d="{k}" fill="#6a8f4f"/>')

# Wege: Ringstraße auf dem Plateau, Straßen zu den Regionen, Brücke, Bootslinie
o.append(f'<path d="{plateau}" fill="#b9b39a" stroke="#efe6c4" stroke-width="3"/>')
o.append(f'<circle cx="{CX}" cy="{CY}" r="98" fill="none" stroke="#e8dcb0" stroke-width="5" opacity=".9"/>')
def strasse(a, b, krumm=0.18, cls='#e8dcb0', w=4, dash=None):
    mx, my = (a[0]+b[0])/2, (a[1]+b[1])/2
    dx, dy = b[0]-a[0], b[1]-a[1]
    c = (mx - dy*krumm, my + dx*krumm)
    d = f' stroke-dasharray="{dash}"' if dash else ''
    o.append(f'<path d="M{a[0]:.1f},{a[1]:.1f} Q{c[0]:.1f},{c[1]:.1f} {b[0]:.1f},{b[1]:.1f}" fill="none" stroke="{cls}" stroke-width="{w}" stroke-linecap="round"{d}/>')
for w, an, *_ in REGIONEN:
    t = math.radians(w)
    strasse(pt(t, 128, sx=1.0), ort(w, an), 0.12)
# Uferweg zwischen Regionen (Rundweg)
o.append(poly(lambda t: pt(t, r_insel(t)*0.83), 300).join([f'<path d="', f'" fill="none" stroke="#e8dcb0" stroke-width="2" stroke-dasharray="7 6" opacity=".7"/>']))
# Brücke zum Gehirn
b1 = pt(g_t, r_insel(g_t)*zack(g_t)-4); b2 = pt(g_t, r_insel(g_t)*1.0 + 215 - 92*1.05)
o.append(f'<line x1="{b1[0]:.1f}" y1="{b1[1]:.1f}" x2="{b2[0]:.1f}" y2="{b2[1]:.1f}" stroke="#3a3328" stroke-width="11" stroke-linecap="round"/>')
o.append(f'<line x1="{b1[0]:.1f}" y1="{b1[1]:.1f}" x2="{b2[0]:.1f}" y2="{b2[1]:.1f}" stroke="#d9cfae" stroke-width="6" stroke-linecap="round"/>')
strasse(pt(math.radians(150), 128, sx=1.0), b1, -0.1)
# Bootslinie Hafen -> Trading
haf = ort(-90, 0.96)
strasse(haf, (tr_c[0]-30, tr_c[1]+10), -0.25, '#ffffff', 2, '3 7')
# Lichtstrom Nachtarbeit -> Gehirn
nt = pt(math.radians(150), 110, sx=1.0)
strasse(nt, g_c, -0.22, '#c9a7ff', 2.5, '1 6')

# Regionen
def schild(x, y, titel, unter, farbe, dy=0):
    o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="15" fill="#0b1d28" stroke="{farbe}" stroke-width="4"/>')
    o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{farbe}"/>')
    o.append(f'<text x="{x:.1f}" y="{y+34+dy:.1f}" text-anchor="middle" class="t ort">{titel}</text>')
    o.append(f'<text x="{x:.1f}" y="{y+50+dy:.1f}" text-anchor="middle" class="t g">{unter}</text>')
for w, an, name, ortsname, st in REGIONEN:
    x, y = ort(w, an)
    schild(x, y, name, ortsname, STATUS[st])
# Hafenstadt-Andeutung: kleine Blöcke
hx, hy = ort(-90, 0.80)
for i in range(46):
    bx = hx + random.choice([-1, 1])*random.uniform(26, 92); by = hy + random.uniform(-26, 14)
    o.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{random.uniform(5,10):.1f}" height="{random.uniform(5,10):.1f}" fill="#e7ecef" opacity=".85"/>')

# Wälder
for _ in range(260):
    t = random.uniform(0, 2*math.pi); a = random.uniform(0.45, 0.92)
    x, y = pt(t, r_insel(t)*a)
    if math.hypot(x-CX, y-CY) < 175: continue
    if any(math.hypot(x-ort(w, an)[0], y-ort(w, an)[1]) < 62 for w, an, *_ in REGIONEN): continue
    o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{random.uniform(3,6):.1f}" fill="#3f6b33" opacity=".75"/>')

# Weltenbaum
o.append(f'<circle cx="{CX}" cy="{CY}" r="80" fill="url(#krone)"/>')
for i in range(7):
    a = i*2*math.pi/7 + .3
    o.append(f'<path d="M{CX},{CY} Q{CX+30*math.cos(a+.4):.1f},{CY+30*math.sin(a+.4):.1f} {CX+52*math.cos(a):.1f},{CY+52*math.sin(a):.1f}" stroke="#6b4a24" stroke-width="4" fill="none" stroke-linecap="round"/>')
o.append(f'<circle cx="{CX}" cy="{CY}" r="12" fill="#5a3d1c" stroke="#fff3c0" stroke-width="2"/>')
o.append(f'<text x="{CX}" y="{CY+4}" text-anchor="middle" font-size="11" font-weight="700" fill="#fff3c0">J</text>')
o.append(f'<text x="{CX}" y="{CY-88}" text-anchor="middle" class="t ort" style="font-size:18px">Weltenbaum · Auron</text>')

# Türme
for w, name, st, form in TUERME:
    t = math.radians(w)
    x, y = pt(t, 112, sx=1.0)
    o.append(f'<rect x="{x-9:.1f}" y="{y-9:.1f}" width="18" height="18" rx="3" transform="rotate(45 {x:.1f} {y:.1f})" fill="#0b1d28" stroke="{STATUS[st]}" stroke-width="3.5"/>')
    lx, ly = pt(t, 158, sx=1.0)
    anker = "middle" if abs(math.cos(t)) < .3 else ("start" if math.cos(t) > 0 else "end")
    if w == 270: lx, ly, anker = x + 20, y + 2, "start"
    o.append(f'<text x="{lx:.1f}" y="{ly+4:.1f}" text-anchor="{anker}" class="t k">{name}</text>')
    o.append(f'<text x="{lx:.1f}" y="{ly+18:.1f}" text-anchor="{anker}" class="t g">{form}</text>')

# Nebeninseln beschriften
o.append(f'<circle cx="{g_c[0]:.1f}" cy="{g_c[1]:.1f}" r="34" fill="#c9a7ff" opacity=".35"/>')
for _ in range(40):
    a = random.uniform(0, 6.28); d = random.uniform(42, 82)
    x, y = g_c[0] + d*math.cos(a)*1.1, g_c[1] + d*math.sin(a)*0.9
    o.append(f'<path d="M{x:.1f},{y-6:.1f} L{x+3.5:.1f},{y:.1f} L{x:.1f},{y+6:.1f} L{x-3.5:.1f},{y:.1f} Z" fill="#e6dbff" opacity=".8"/>')
schild(g_c[0], g_c[1], "Vault", "Insel Gehirn", STATUS["laeuft"])
schild(tr_c[0], tr_c[1], "Trading", "Fernklippe (aus)", STATUS["aus"], 4)

# Titel, Legende, Kompass, Maßstab
o.append('<text x="40" y="58" class="t" style="font-size:30px;font-weight:800">Auron-Welt · Kartenplan</text>')
o.append('<text x="40" y="82" class="t g" style="font-size:14px">Entwurf 04.10.2026 · eigene Gestaltung · Draufsicht, nicht maßstabsgenau</text>')
lx, ly = 1180, 210
o.append(f'<rect x="{lx-18}" y="{ly-30}" width="318" height="340" rx="12" fill="#0b1d28" opacity=".78"/>')
o.append(f'<text x="{lx}" y="{ly}" class="t k" style="font-size:15px">Legende</text>')
eintraege = [("circ", "#f3c74f", "Weltenbaum = Auron (Mitte)"), ("rauten", "#3fbf6a", "6 Türme: Geräte &amp; Systeme"),
             ("circ2", "#3fbf6a", "Regionen und Inseln"), ("farbe", "#3fbf6a", "läuft"), ("farbe", "#e2b33c", "wartet"),
             ("farbe", "#8a8f98", "aus"), ("linie", "#e8dcb0", "Straße / Ringstraße"), ("strich", "#ffffff", "Bootslinie"),
             ("strich", "#c9a7ff", "Lichtstrom: Nachtarbeit schreibt Notizen"), ("klippe", "#3b3a33", "Steilküste (Ecken und Kanten)"),
             ("strand", "#e9d9a6", "Strand")]
for i, (art, f, txt) in enumerate(eintraege):
    y = ly + 26 + i*26; x = lx + 10
    if art == "circ": o.append(f'<circle cx="{x}" cy="{y-4}" r="8" fill="{f}"/>')
    elif art == "rauten": o.append(f'<rect x="{x-6}" y="{y-10}" width="12" height="12" transform="rotate(45 {x} {y-4})" fill="#0b1d28" stroke="{f}" stroke-width="3"/>')
    elif art == "circ2": o.append(f'<circle cx="{x}" cy="{y-4}" r="8" fill="#0b1d28" stroke="{f}" stroke-width="3"/>')
    elif art == "farbe": o.append(f'<rect x="{x-8}" y="{y-11}" width="16" height="12" rx="3" fill="{f}"/>')
    elif art == "linie": o.append(f'<line x1="{x-10}" y1="{y-4}" x2="{x+10}" y2="{y-4}" stroke="{f}" stroke-width="4"/>')
    elif art == "strich": o.append(f'<line x1="{x-10}" y1="{y-4}" x2="{x+10}" y2="{y-4}" stroke="{f}" stroke-width="2.5" stroke-dasharray="3 4"/>')
    elif art == "klippe": o.append(f'<line x1="{x-10}" y1="{y-4}" x2="{x+10}" y2="{y-4}" stroke="{f}" stroke-width="5"/>')
    elif art == "strand": o.append(f'<line x1="{x-10}" y1="{y-4}" x2="{x+10}" y2="{y-4}" stroke="{f}" stroke-width="6"/>')
    o.append(f'<text x="{x+20}" y="{y}" class="t g" style="font-size:12.5px">{txt}</text>')
# Kompass
kx, ky = 1420, 92
o.append(f'<circle cx="{kx}" cy="{ky}" r="34" fill="#0b1d28" opacity=".7"/><path d="M{kx},{ky-28} L{kx+8},{ky} L{kx},{ky-6} L{kx-8},{ky} Z" fill="#f3c74f"/><path d="M{kx},{ky+28} L{kx+8},{ky} L{kx},{ky+6} L{kx-8},{ky} Z" fill="#9fb3bf"/><text x="{kx}" y="{ky-38}" text-anchor="middle" class="t k">N</text>')
# Maßstab: 100 px = 1 km
o.append(f'<g transform="translate(40,{H-48})"><rect x="0" y="0" width="100" height="8" fill="#fff"/><rect x="100" y="0" width="100" height="8" fill="#0b1d28" stroke="#fff"/><text x="0" y="26" class="t g">0</text><text x="92" y="26" class="t g">1 km</text><text x="190" y="26" class="t g">2 km</text></g>')
o.append('</svg>')
open('/home/claude/karte/Jarvis-Welt Karte.svg', 'w', encoding='utf-8').write("\n".join(o))
print("ok", len("\n".join(o)))
