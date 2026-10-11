"""Beim Aufruf als Paket (python -m unittest tests.test_...) zuerst Testschutz und Datenumleitung laden.

Achtung: Bei "discover -s tests" läuft diese Datei NICHT - dort lädt test_000_isolierung.py beides.
11.10.2026: Ohne diese Zeilen schrieben Einzelaufrufe in den echten Ordner data/.
"""

from . import testschutz, test_000_isolierung  # noqa: F401
