"""
Stichwort-Aufbereitung für die Hybrid-Suche (Keyword-Anteil im Retriever).

Warum eigenes Modul?
Bis 19.09.2026 zählte jedes Wort ab 3 Buchstaben als Stichwort - also auch
"wie", "ich", "eine", "mit". Diese Füllwörter stehen in fast jedem Abschnitt
und verwässern den Keyword-Anteil: Bei "Wie prüfe ich eine Handelsstrategie mit
alten Kursdaten?" waren 4 von 8 Stichwörtern reine Füllwörter, die passende
Backtesting-Notiz landete nicht in den Top 3 (siehe Entwicklungslog).

Jetzt:
1. Füllwörter (Stoppwörter) werden ignoriert.
2. Wörter werden auf ihren Wortstamm gekürzt, damit Beugungsformen
   zusammenpassen: "prüfe"/"prüft"/"prüfen" -> "pruf", "Gefahren"/"Gefahr".
   Umgesetzt ist der Snowball-Stemmer für Deutsch (snowballstem.org),
   ohne zusätzliches Paket.
3. Zweibuchstabige Abkürzungen in Großschrift ("KI", "AI", "UI") zählen mit -
   "KI" ist im Vault ein zentrales Thema und fiel vorher durch das Raster.
"""

from __future__ import annotations

import re

WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß0-9]+")

# Häufige deutsche Funktionswörter (Artikel, Pronomen, Präpositionen,
# Konjunktionen, Hilfsverben, Frage- und Füllwörter) plus die häufigsten
# englischen, weil einige Vault-Notizen englische Abschnitte enthalten.
# Bewusst NICHT enthalten: Wörter mit Inhalt wie "gut", "neu", "Frage",
# "Unterschied", "Beispiel" - die können für die Suche relevant sein.
STOPWORDS: frozenset[str] = frozenset(
    """
    aber alle allem allen aller alles als also am an ander andere anderem anderen
    anderer anderes anders auch auf aus bei beim bin bis bist da dabei dadurch
    dafür dagegen daher dahin damals damit dann dar daran darauf daraus darf
    darfst darin darüber darum darunter das dass dasselbe davon davor dazu dein
    deine deinem deinen deiner deines dem demselben den denen denn dennoch
    denselben der derer derselbe derselben des deshalb desselben dessen dich die
    dies diese dieselbe dieselben diesem diesen dieser dieses dir doch dort du
    durch eben ebenso ein eine einem einen einer eines einige einigem einigen
    einiger einiges einmal er es etwa etwas euch euer eure eurem euren eurer
    eures für gab gegen geht gibt gewesen hab habe haben hast hat hatte hatten
    hattest her hier hin hinter ich ihm ihn ihnen ihr ihre ihrem ihren ihrer
    ihres im immer in ins ist ja je jede jedem jeden jeder jedes jedoch jene
    jenem jenen jener jenes jetzt kann kannst kein keine keinem keinen keiner
    keines können könnte könnten machen macht man manche manchem manchen
    mancher manches mehr mein meine meinem meinen meiner meines mich mir mit
    muss musst müssen musste nach nachdem nein nicht nichts noch nun nur ob oder
    ohne sehr sein seine seinem seinen seiner seines seit selbst sich sie sind
    so sogar solche solchem solchen solcher solches soll sollen sollte sollten
    sondern sonst über um und uns unse unser unsere unserem unseren unserer
    unseres unter viel viele vom von vor wann war waren warst warum was weg
    weil weiter welche welchem welchen welcher welches wem wen wenn wer werde
    werden werdet weshalb wessen wie wieder wieso will willst wir wird wirst
    wo woher wohin wollen wollte worden wurde wurden während zu zum zur zwar
    zwischen bzw usw etc ca eigentlich eher ganz genau gerade gern gerne halt
    irgendwie mal oft schon wohl
    about and are but can did does for from had has have how into its not
    that the their them then there these they this was were what when where
    which who why will with would you your
    """.split()
)

_VOWELS = "aeiouyäöü"
_S_ENDING = "bdfghklmnrt"
_ST_ENDING = "bdfghklmnt"


def _region_start(word: str, start: int = 0) -> int:
    """Position nach dem ersten Nicht-Vokal, der auf einen Vokal folgt
    (Snowball-Definition von R1/R2)."""
    for i in range(start + 1, len(word)):
        if word[i] not in _VOWELS and word[i - 1] in _VOWELS:
            return i + 1
    return len(word)


def stem_german(word: str) -> str:
    """Snowball-Stemmer für Deutsch. Erwartet ein kleingeschriebenes Wort.

    Beispiele: "prüfe"/"prüft"/"prüfen" -> "pruf", "Gefahren" -> "gefahr",
    "historischer"/"historische" -> "histor", "Bedürfnissen" -> "bedurfnis".
    """
    word = word.replace("ß", "ss")
    # u und y zwischen zwei Vokalen gelten als Konsonant (Großbuchstabe markiert das)
    chars = list(word)
    for i in range(1, len(chars) - 1):
        if chars[i] in "uy" and chars[i - 1] in _VOWELS and chars[i + 1] in _VOWELS:
            chars[i] = chars[i].upper()
    word = "".join(chars)

    r1 = max(_region_start(word), 3)
    r2 = _region_start(word, _region_start(word))

    # Schritt 1
    for suffix in ("ern", "em", "er", "en", "es", "e", "s"):
        if not word.endswith(suffix):
            continue
        pos = len(word) - len(suffix)
        if suffix == "s" and (pos < 1 or word[pos - 1] not in _S_ENDING):
            continue
        if pos >= r1:
            word = word[:pos]
            if suffix in ("en", "es", "e") and word.endswith("niss"):
                word = word[:-1]
        break

    # Schritt 2
    for suffix in ("est", "en", "er", "st"):
        if not word.endswith(suffix):
            continue
        pos = len(word) - len(suffix)
        if suffix == "st" and (pos < 4 or word[pos - 1] not in _ST_ENDING):
            continue
        if pos >= r1:
            word = word[:pos]
        break

    # Schritt 3 (Ableitungs-Endungen)
    for suffix in ("isch", "lich", "heit", "keit", "end", "ung", "ig", "ik"):
        if not word.endswith(suffix):
            continue
        pos = len(word) - len(suffix)
        if suffix in ("end", "ung"):
            if pos >= r2:
                word = word[:pos]
                if word.endswith("ig") and not word.endswith("eig") and len(word) - 2 >= r2:
                    word = word[:-2]
        elif suffix in ("ig", "ik", "isch"):
            if pos >= r2 and (pos < 1 or word[pos - 1] != "e"):
                word = word[:pos]
        elif suffix in ("lich", "heit"):
            if pos >= r2:
                word = word[:pos]
                for pre in ("er", "en"):
                    if word.endswith(pre) and len(word) - 2 >= r1:
                        word = word[:-2]
                        break
        elif suffix == "keit":
            if pos >= r2:
                word = word[:pos]
                for pre in ("lich", "ig"):
                    if word.endswith(pre) and len(word) - len(pre) >= r2:
                        word = word[: -len(pre)]
                        break
        break

    return word.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u")


def keywords(text: str) -> set[str]:
    """Wortstämme der inhaltstragenden Wörter eines Textes."""
    result: set[str] = set()
    for raw in WORD_RE.findall(text):
        word = raw.lower()
        if len(raw) < 2 or (len(raw) == 2 and not raw.isupper()):
            continue
        if word in STOPWORDS or word.isdigit() and len(word) < 3:
            continue
        result.add(stem_german(word) if not word.isdigit() else word)
    return result
