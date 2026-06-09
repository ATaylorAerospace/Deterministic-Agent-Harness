"""Flight Recorder: append-only, hash-chained JSONL audit log.

Author: A Taylor

Every line on disk carries a SHA-256 hash computed over the previous
line's hash plus a canonical serialization of the current entry. Any
edit, deletion, or reordering of a line breaks the chain and is caught
by verify(). The recorder exposes no deletion or rewrite API, flushes
and fsyncs every write, and resumes its chain across process restarts
by re-reading the last line on startup.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

GENESIS_HASH = "0" * 64


def _canonical(payload: Dict[str, Any]) -> str:
    """Canonical JSON: sorted keys, compact separators, no NaN.

    record() and verify() both hash this exact form, so the chain check
    is symmetric with the write path.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    )


def _chain_hash(prev_hash: str, entry: Dict[str, Any]) -> str:
    material = prev_hash + _canonical(entry)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class FlightRecorder:
    """Immutable text-file audit trail with a per-line hash chain."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._prev_hash = self._resume_chain()

    @property
    def path(self) -> Path:
        return self._path

    def _resume_chain(self) -> str:
        """Pick up the chain from the last line of an existing log."""
        if not self._path.exists() or self._path.stat().st_size == 0:
            return GENESIS_HASH
        last_line = ""
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
        if not last_line:
            return GENESIS_HASH
        return json.loads(last_line)["hash"]

    def record(self, entry: Dict[str, Any]) -> str:
        """Append one entry and return its chain hash."""
        if not isinstance(entry, dict):
            raise TypeError("Flight Recorder entries must be dictionaries")
        line_hash = _chain_hash(self._prev_hash, entry)
        line = {"entry": entry, "prev": self._prev_hash, "hash": line_hash}
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(line) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._prev_hash = line_hash
        return line_hash

    def verify(self) -> Tuple[bool, int]:
        """Walk the log and recompute the chain.

        Returns (True, line_count) for a clean log, or
        (False, first_bad_line_number) when the chain is broken.
        Line numbers are 1-based.
        """
        if not self._path.exists():
            return True, 0
        prev_hash = GENESIS_HASH
        count = 0
        with self._path.open("r", encoding="utf-8") as handle:
            for number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    line = json.loads(raw)
                    entry = line["entry"]
                    claimed_prev = line["prev"]
                    claimed_hash = line["hash"]
                except (ValueError, KeyError, TypeError):
                    return False, number
                if claimed_prev != prev_hash:
                    return False, number
                if _chain_hash(prev_hash, entry) != claimed_hash:
                    return False, number
                prev_hash = claimed_hash
                count = number
        return True, count
