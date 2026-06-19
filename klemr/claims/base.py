"""ClaimType plugin interface + registry.

A ``ClaimType`` is one auditable leakage pattern (RAF-1a is the first). It binds an
identity to a versioned rule and exposes the policy surface the rest of the engine
needs. Detection, candidate building, and evidence assembly are added in later
steps as methods on this interface; Step 1 establishes the seam and the metadata.

The UI and CLI discover claim types through ``ClaimRegistry`` — they never import a
concrete claim module directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from klemr.rules.models import Gate, ResolutionPolicy, Rule
from klemr.rules.store import RuleStore


class IncompatibleRule(ValueError):
    """A claim type was asked to evaluate a rule bound to different engine logic."""


class ClaimType(ABC):
    """Interface every claim-type plugin implements."""

    #: Stable short key used in the UI/CLI and registry, e.g. ``"raf-1a"``.
    key: str
    #: Human-readable title.
    title: str
    #: The rule id this claim type is governed by (resolved against a RuleStore).
    rule_id: str
    #: The engine logic this plugin implements; it will only evaluate rules whose
    #: ``logic_id`` matches (FIX 3 — explicit rule->logic binding).
    logic_id: str

    @abstractmethod
    def rule(self, store: RuleStore) -> Rule:
        """Return the governing rule version from the store (after asserting it is
        bound to this plugin's ``logic_id`` via :meth:`assert_compatible`)."""

    def assert_compatible(self, rule: Rule) -> None:
        """Guard: refuse to evaluate a rule whose logic_id is not ours."""
        if rule.logic_id != self.logic_id:
            raise IncompatibleRule(
                f"Claim {self.key!r} (logic_id={self.logic_id!r}) cannot evaluate rule "
                f"{rule.rule_id!r}@{rule.version} (logic_id={rule.logic_id!r})."
            )

    def gates(self, store: RuleStore) -> tuple[Gate, ...]:
        """The three-gate test for this claim type (sourced from the rule data)."""
        return self.rule(store).gates

    def resolution_policy(self, store: RuleStore) -> ResolutionPolicy:
        """The verified-resolution -> tier mapping (sourced from the rule data)."""
        return self.rule(store).resolution_policy


class ClaimRegistry:
    """A lookup of claim-type plugins by key."""

    def __init__(self) -> None:
        self._by_key: dict[str, ClaimType] = {}

    def register(self, claim: ClaimType) -> None:
        if claim.key in self._by_key:
            raise ValueError(f"Claim type {claim.key!r} already registered")
        self._by_key[claim.key] = claim

    def get(self, key: str) -> ClaimType:
        return self._by_key[key]

    def all(self) -> list[ClaimType]:
        return list(self._by_key.values())
