"""Versioned rule model — **policy as data, never hardcoded constants**.

A ``Rule`` is an immutable, versioned, claim-agnostic *envelope*: identity + logic
binding, effective date, verbatim citation, the gate test, the resolution -> tier
map, and timing parameters. The claim-specific policy math (e.g. a RAF fee schedule)
lives in an opaque ``payload`` that only the matching plugin interprets — so a second
claim type (carrier overcharge, reserve release, ...) is a new JSON rule + plugin,
NOT a change to this module.

Findings reference a rule by ``rule_id`` + ``version`` + ``content_hash`` so any
result is reproducible and traceable to the exact policy that produced it. This
module is the *data* and the pure envelope-level helpers (maturity math, resolution
classification); it never computes recoverable money.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


def _norm(s: object) -> str:
    """Normalize a token for alias matching: lower, keep alphanumerics and ``_``.

    Mirrors the normalization in the reference ``build_packet.py`` so the engine
    classifies resolutions identically to the oracle.
    """
    return "".join(ch for ch in str(s).strip().lower() if ch.isalnum() or ch == "_")


class PolicyCitation(BaseModel):
    """Verbatim source of the policy, for the packet cover and re-verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    publisher: str
    url: str
    last_revised: date
    quote: str


class RuleParameters(BaseModel):
    """Operational, tunable knobs (not policy text). Drive maturity/freshness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    maturity_days: int = 21
    fresh_days: int = 3

    def mature_cutoff(self, as_of: date) -> date:
        return as_of - timedelta(days=self.maturity_days)

    def fresh_cutoff(self, as_of: date) -> date:
        return as_of - timedelta(days=self.fresh_days)

    def is_mature(self, statement_date: date | None, as_of: date) -> bool:
        """Mature == settled on/before ``as_of - maturity_days`` (boundary is mature)."""
        if statement_date is None:
            return False
        return statement_date <= self.mature_cutoff(as_of)

    def is_fresh(self, statement_date: date | None, as_of: date) -> bool:
        """Fresh == settled strictly after ``as_of - fresh_days`` (file in 2nd wave)."""
        if statement_date is None:
            return False
        return statement_date > self.fresh_cutoff(as_of)


class Gate(BaseModel):
    """One condition in the gate test.

    ``in_data`` encodes the single most important invariant in the audit: a decisive
    gate with ``in_data == False`` (RAF-1a's Gate 3) cannot be read from the export
    files and must never be inferred — it is resolved only by a human or the API.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    key: str
    name: str
    source: Literal["data", "seller_center"]
    in_data: bool
    decisive: bool
    description: str


class ResolutionOutcome(BaseModel):
    """A verified resolution and the claim tier it routes to (+ any metadata flags)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolution: str  # canonical label, e.g. "auto_approved"
    tier: str  # e.g. "filable_tier1"
    aliases: tuple[str, ...] = ()
    # Non-deciding metadata carried alongside the outcome, e.g. "tier2_appeal_candidate"
    # on a dismissed (seller-canceled) finding. A flag is NOT a claim state.
    flags: tuple[str, ...] = ()


class ResolutionPolicy(BaseModel):
    """Maps a verified, human/API-supplied decisive-gate resolution to an outcome.

    The decision split as data: ``filable`` (exempt), ``dismissed`` (decisively not
    exempt — terminal), or ``review`` (anything else). ``classify`` is the only place
    a resolution string becomes a tier; the buyer's cancel *reason* is never an input
    (reason is noise).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    filable: ResolutionOutcome
    dismissed: ResolutionOutcome
    review: ResolutionOutcome

    def classify(self, raw: object) -> ResolutionOutcome:
        n = _norm(raw)
        if n and n in {_norm(a) for a in self.filable.aliases}:
            return self.filable
        if n and n in {_norm(a) for a in self.dismissed.aliases}:
            return self.dismissed
        return self.review


class Rule(BaseModel):
    """An immutable, versioned, claim-agnostic policy envelope. ``extra='forbid'``
    catches schema drift in the JSON data files at load time; ``payload`` is the
    claim-specific blob interpreted only by the matching plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    version: str
    # Binds this rule's DATA to the engine LOGIC allowed to evaluate it. A claim-type
    # plugin asserts a rule's logic_id matches its own before it will touch the rule
    # (or its payload), so a future plugin sharing the store can never mis-apply it.
    logic_id: str
    effective_date: date
    supersedes: str | None = None
    title: str
    description: str
    citation: PolicyCitation
    parameters: RuleParameters
    gates: tuple[Gate, ...]
    resolution_policy: ResolutionPolicy
    # Claim-specific policy payload (e.g. RAF fee schedule). Opaque to the envelope;
    # the owning plugin validates it into a typed model after assert_compatible.
    payload: dict[str, Any] = {}

    def content_hash(self) -> str:
        """Deterministic SHA-256 over the rule's canonical JSON (payload included).

        Stored on findings for reproducibility: same inputs + same rule hash =>
        same result, and any edit to the policy data changes the hash.
        """
        blob = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def decisive_gate(self) -> Gate:
        """The single gate that decides filability and is not in the data (Gate 3)."""
        return next(g for g in self.gates if g.decisive)
