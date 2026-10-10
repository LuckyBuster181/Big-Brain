"""
Systemwerte für das HUD: CPU, Arbeitsspeicher, Festplatte, Laufzeit.

Ohne Zusatzpakete: unter Windows über ctypes (GetSystemTimes,
GlobalMemoryStatusEx), unter Linux über /proc. Fehlt ein Wert, steht dort None -
das HUD zeigt dann einen Strich statt einer erfundenen Zahl.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import time
from pathlib import Path
from typing import Any

START_TIME = time.time()

# Für die CPU-Auslastung wird zwischen zwei Abfragen verglichen.
_last: dict[str, float] = {}


def _windows_cpu_times() -> tuple[float, float] | None:
    class FILETIME(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
    except Exception:
        return None
    if not ok:
        return None
    to_float = lambda f: (f.high << 32) + f.low  # noqa: E731
    idle_t = to_float(idle)
    total = to_float(kernel) + to_float(user)
    return idle_t, total


def _linux_cpu_times() -> tuple[float, float] | None:
    try:
        parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    except OSError:
        return None
    values = [float(v) for v in parts]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


def cpu_percent() -> float | None:
    """Auslastung seit dem letzten Aufruf. Der erste Aufruf liefert None."""
    times = _windows_cpu_times() if os.name == "nt" else _linux_cpu_times()
    if times is None:
        return None
    idle, total = times
    prev_idle, prev_total = _last.get("idle"), _last.get("total")
    _last["idle"], _last["total"] = idle, total
    if prev_idle is None or prev_total is None or total <= prev_total:
        return None
    busy = (total - prev_total) - (idle - prev_idle)
    return max(0.0, min(100.0, busy / (total - prev_total) * 100))


def memory() -> dict[str, float] | None:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        try:
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return None
        except Exception:
            return None
        total = status.ullTotalPhys / 1024**3
        frei = status.ullAvailPhys / 1024**3
        return {"gesamt_gb": round(total, 1), "benutzt_gb": round(total - frei, 1), "prozent": float(status.dwMemoryLoad)}

    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = float(rest.strip().split()[0]) / 1024**2  # kB -> GB
    except OSError:
        return None
    total = info.get("MemTotal")
    frei = info.get("MemAvailable", info.get("MemFree"))
    if not total or frei is None:
        return None
    return {"gesamt_gb": round(total, 1), "benutzt_gb": round(total - frei, 1), "prozent": round((total - frei) / total * 100)}


def disk(path: str | Path | None = None) -> dict[str, float] | None:
    ziel = Path(path or os.getenv("VAULT_PATH") or Path.home())
    while not ziel.exists() and ziel != ziel.parent:
        ziel = ziel.parent
    try:
        usage = shutil.disk_usage(ziel)
    except OSError:
        return None
    return {
        "gesamt_gb": round(usage.total / 1024**3),
        "benutzt_gb": round(usage.used / 1024**3),
        "prozent": round(usage.used / usage.total * 100),
        "laufwerk": str(ziel.anchor or ziel),
    }


def snapshot() -> dict[str, Any]:
    return {
        "cpu_prozent": cpu_percent(),
        "speicher": memory(),
        "festplatte": disk(),
        "laufzeit_s": round(time.time() - START_TIME),
        "system": os.name,
    }


if __name__ == "__main__":  # pragma: no cover
    cpu_percent()
    time.sleep(0.5)
    print(snapshot())
