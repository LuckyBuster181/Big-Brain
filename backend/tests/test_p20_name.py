"""P20 (13.10.2026): Der Name "Jarvis" ist für Sir nirgends mehr sichtbar oder hörbar. Auron sagt ihn nie.

Erlaubt bleiben Dateinamen, Ordner, Umgebungsvariablen, Vault-Dateinamen, Browser-Kennungen und
Themennamen, die in bestehenden Notizen als Verweis stehen (siehe ERLAUBT). Alte Befehle mit "Jarvis"
funktionieren weiter (stilles Synonym, siehe test_name_auron.py).
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]

ERLAUBT = re.compile("|".join([
    r"JARVIS[ _]STARTEN(?:\.bat)?", r"JARVIS_[A-Z0-9_<>ÄÖÜ]+", r"[\\/]Jarvis\b", r"\bJarvis[\\/]",
    r"\bJarvis\.(?:py|bat|ps1|vbs|json|md)", r"\bJarvis-(?:Ordner|Nachtarbeit)\b", r"Jarvis/1\.0", r"JarvisBigBrain",
    r"Gemerkt von Jarvis", r"projekt: Jarvis", r"06 - Jarvis fragt", r"Jarvis (?:Projekt Anweisung|Entwicklungslog|Big Brain Dashboard|Gesamtidee)",
    r"Jarvis und KI-Agenten", r"alten Namen „Jarvis“",
]))


def _sichtbar(text: str) -> list[str]:
    return re.findall(r"\b(?:Jarvis|JARVIS)\b", ERLAUBT.sub("", text))


class KeinJarvisSichtbar(unittest.TestCase):
    def test_python_texte(self):
        funde = []
        dateien = [*WURZEL.glob("backend/app/*.py"), WURZEL / "backend/main.py", *WURZEL.glob("backend/tools/*.py"),
                   *WURZEL.glob("backend/llm/*.py")]
        for datei in dateien:
            baum = ast.parse(datei.read_text(encoding="utf-8"))
            doc = {id(k.body[0].value) for k in ast.walk(baum)
                   if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and k.body
                   and isinstance(k.body[0], ast.Expr) and isinstance(getattr(k.body[0], "value", None), ast.Constant)
                   and isinstance(k.body[0].value.value, str)}
            for k in ast.walk(baum):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and id(k) not in doc and _sichtbar(k.value):
                    funde.append(f"{datei.name}:{k.lineno}: {k.value[:80]!r}")
        self.assertEqual(funde, [])

    def test_hud_und_handy(self):
        funde = []
        for name in ("dashboard/index.html", "dashboard/handy.html"):
            for nr, zeile in enumerate((WURZEL / name).read_text(encoding="utf-8").splitlines(), 1):
                if _sichtbar(zeile):
                    funde.append(f"{name}:{nr}: {zeile.strip()[:80]}")
        self.assertEqual(funde, [])

    def test_system_prompt_nennt_den_alten_namen_nur_als_hinweis(self):
        from app import chat_service

        self.assertIn("du sagst und schreibst ihn selbst nie", chat_service.SYSTEM_PROMPT)
        self.assertEqual(_sichtbar(chat_service.SYSTEM_PROMPT), [])

    def test_gespeicherter_alter_name_wird_im_hud_umgestellt(self):
        html = (WURZEL / "dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn('assistent: "Auron"', html)
        self.assertRegex(html, r'S\.assistent = "Auron"')


if __name__ == "__main__":
    unittest.main()
