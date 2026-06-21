"""
MediaManager 2026 — Journal de performances SQL

Ring buffer en mémoire des dernières exécutions de requêtes SQL instrumentées.
Thread-safe. Ne persiste pas entre les redémarrages (voulu : données en temps réel).

Usage dans un router :
    from watcher.utils.perf import timed_query

    with timed_query("library_titles", "main") as q:
        rows = conn.execute(...).mappings().fetchall()
        q.row_count = len(rows)
"""

import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

_RING_SIZE      = 500
_lock           = threading.Lock()
_records: deque = deque(maxlen=_RING_SIZE)
_total_recorded = 0


def _record(endpoint: str, name: str, duration_ms: float, row_count: int) -> None:
    global _total_recorded
    entry = {
        "ts":          datetime.now().isoformat(timespec="seconds"),
        "endpoint":    endpoint,
        "name":        name,
        "duration_ms": round(duration_ms, 1),
        "row_count":   row_count,
    }
    with _lock:
        _records.append(entry)
        _total_recorded += 1


@contextmanager
def timed_query(endpoint: str, name: str):
    """Mesure la durée d'une requête SQL et l'enregistre dans le ring buffer.

    Le champ `q.row_count` est optionnel — assigner avant de sortir du bloc.
    """
    t0 = time.perf_counter()
    q  = SimpleNamespace(row_count=0)
    try:
        yield q
    finally:
        _record(endpoint, name, (time.perf_counter() - t0) * 1000, q.row_count)


def get_records(limit: int = 100) -> list:
    """Retourne les N derniers enregistrements (plus récent en premier)."""
    with _lock:
        snapshot = list(_records)
    return list(reversed(snapshot))[:limit]


def get_summary() -> list:
    """Agrège par (endpoint, name) et trie par durée moyenne décroissante."""
    with _lock:
        snapshot = list(_records)

    agg: dict = {}
    for r in snapshot:
        key = (r["endpoint"], r["name"])
        if key not in agg:
            agg[key] = {
                "endpoint":   r["endpoint"],
                "name":       r["name"],
                "calls":      0,
                "total_ms":   0.0,
                "max_ms":     0.0,
                "min_ms":     float("inf"),
                "total_rows": 0,
            }
        e = agg[key]
        e["calls"]      += 1
        e["total_ms"]   += r["duration_ms"]
        e["max_ms"]      = max(e["max_ms"], r["duration_ms"])
        e["min_ms"]      = min(e["min_ms"], r["duration_ms"])
        e["total_rows"] += r["row_count"]

    result = []
    for e in agg.values():
        n = e["calls"]
        result.append({
            "endpoint": e["endpoint"],
            "name":     e["name"],
            "calls":    n,
            "avg_ms":   round(e["total_ms"] / n, 1),
            "max_ms":   round(e["max_ms"], 1),
            "min_ms":   round(e["min_ms"] if e["min_ms"] != float("inf") else 0.0, 1),
            "avg_rows": round(e["total_rows"] / n, 1),
        })

    return sorted(result, key=lambda x: -x["avg_ms"])


def get_stats() -> dict:
    with _lock:
        return {
            "buffered":       len(_records),
            "total_recorded": _total_recorded,
            "ring_size":      _RING_SIZE,
        }


def record(endpoint: str, name: str, duration_ms: float, row_count: int = 0) -> None:
    """API publique pour enregistrer sans context manager (usage : avant/après la requête)."""
    _record(endpoint, name, duration_ms, row_count)


def clear() -> None:
    global _total_recorded
    with _lock:
        _records.clear()
        _total_recorded = 0
