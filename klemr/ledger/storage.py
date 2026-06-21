"""SQLite evidence ledger — append-only system of record for human/agent decisions.

Findings and detection stay recomputable from inputs; this ledger holds the
irreducible facts the data cannot give you: *what* was decided about each finding's
decisive Gate-3 signal, *by whom*, *when*, and *citing which rule version* — plus the
state transitions those decisions caused.

Append-only is enforced structurally: BEFORE UPDATE / BEFORE DELETE triggers RAISE
on the resolution, transition, and coverage tables. A corrected decision is a NEW
resolution row; nothing is ever mutated in place. Timestamps are caller-supplied
(a real action time) — the ledger never fabricates one.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resolutions (
    resolution_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id        TEXT NOT NULL,
    gate              TEXT NOT NULL,
    resolved_value    TEXT NOT NULL,
    source            TEXT NOT NULL,
    reviewer          TEXT NOT NULL,
    resolved_at       TEXT NOT NULL,
    evidence_ref      TEXT,
    rule_id           TEXT NOT NULL,
    rule_content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id    TEXT NOT NULL,
    from_state    TEXT NOT NULL,
    to_state      TEXT NOT NULL,
    reason        TEXT,
    actor         TEXT NOT NULL,
    at            TEXT NOT NULL,
    resolution_id INTEGER REFERENCES resolutions(resolution_id)
);
CREATE TABLE IF NOT EXISTS coverage_carryforward (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_fingerprint TEXT NOT NULL,
    order_id        TEXT NOT NULL,
    cancelled_at    TEXT,
    reason          TEXT NOT NULL
);
"""

# Append-only guards: mutating any ledger row is structurally impossible.
_APPEND_ONLY = """
CREATE TRIGGER IF NOT EXISTS {t}_no_update BEFORE UPDATE ON {t}
BEGIN SELECT RAISE(ABORT, 'evidence ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS {t}_no_delete BEFORE DELETE ON {t}
BEGIN SELECT RAISE(ABORT, 'evidence ledger is append-only'); END;
"""


@dataclass(frozen=True)
class ResolutionRecord:
    resolution_id: int
    finding_id: str
    gate: str
    resolved_value: str
    source: str
    reviewer: str
    resolved_at: str
    evidence_ref: str | None
    rule_id: str
    rule_content_hash: str


@dataclass(frozen=True)
class TransitionRecord:
    transition_id: int
    finding_id: str
    from_state: str
    to_state: str
    reason: str | None
    actor: str
    at: str
    resolution_id: int | None


@dataclass(frozen=True)
class CoverageNote:
    id: int
    run_fingerprint: str
    order_id: str
    cancelled_at: str | None
    reason: str


class EvidenceLedger:
    """Append-only SQLite ledger. ``path=':memory:'`` for tests; a file otherwise."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        for table in ("resolutions", "transitions", "coverage_carryforward"):
            self._conn.executescript(_APPEND_ONLY.format(t=table))
        self._conn.commit()

    # ---- writes (INSERT only) ----
    def record_resolution(
        self,
        *,
        finding_id: str,
        gate: str,
        resolved_value: str,
        source: str,
        reviewer: str,
        resolved_at: datetime,
        rule_id: str,
        rule_content_hash: str,
        evidence_ref: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO resolutions (finding_id, gate, resolved_value, source, reviewer, "
            "resolved_at, evidence_ref, rule_id, rule_content_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (finding_id, gate, resolved_value, source, reviewer,
             resolved_at.isoformat(), evidence_ref, rule_id, rule_content_hash),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record_transition(
        self,
        *,
        finding_id: str,
        from_state: str,
        to_state: str,
        actor: str,
        at: datetime,
        resolution_id: int | None,
        reason: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO transitions (finding_id, from_state, to_state, reason, actor, at, "
            "resolution_id) VALUES (?,?,?,?,?,?,?)",
            (finding_id, from_state, to_state, reason, actor, at.isoformat(), resolution_id),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record_coverage_carryforward(self, run_fingerprint: str, notes) -> None:
        self._conn.executemany(
            "INSERT INTO coverage_carryforward (run_fingerprint, order_id, cancelled_at, reason) "
            "VALUES (?,?,?,?)",
            [(run_fingerprint, n.order_id,
              n.cancelled_at.isoformat() if n.cancelled_at else None, n.reason)
             for n in notes],
        )
        self._conn.commit()

    # ---- reads ----
    def resolutions_for(self, finding_id: str) -> list[ResolutionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM resolutions WHERE finding_id=? ORDER BY resolution_id", (finding_id,)
        ).fetchall()
        return [ResolutionRecord(**dict(r)) for r in rows]

    def latest_resolution(self, finding_id: str) -> ResolutionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM resolutions WHERE finding_id=? ORDER BY resolution_id DESC LIMIT 1",
            (finding_id,),
        ).fetchone()
        return ResolutionRecord(**dict(row)) if row else None

    def transitions_for(self, finding_id: str) -> list[TransitionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM transitions WHERE finding_id=? ORDER BY transition_id", (finding_id,)
        ).fetchall()
        return [TransitionRecord(**dict(r)) for r in rows]

    def coverage_carryforward(self, run_fingerprint: str) -> list[CoverageNote]:
        rows = self._conn.execute(
            "SELECT * FROM coverage_carryforward WHERE run_fingerprint=? ORDER BY order_id",
            (run_fingerprint,),
        ).fetchall()
        return [CoverageNote(**dict(r)) for r in rows]

    def count(self, table: str) -> int:
        if table not in ("resolutions", "transitions", "coverage_carryforward"):
            raise ValueError(table)
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def triggers_intact(self) -> bool:
        """Integrity check: confirm the append-only guard triggers still exist.

        The write-capable connection is intentionally NOT exposed, so production code
        cannot drop a trigger and then mutate. A long-running service can call this at
        open time to fail fast if a DB file was tampered with out-of-band.
        """
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        names = {r["name"] for r in rows}
        expected = {
            f"{t}_no_{op}"
            for t in ("resolutions", "transitions", "coverage_carryforward")
            for op in ("update", "delete")
        }
        return expected <= names

    def __enter__(self) -> "EvidenceLedger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()
