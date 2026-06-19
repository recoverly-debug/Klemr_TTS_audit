"""Versioned rule store.

Loads rules from JSON data files (policy lives as data on disk, not in code) and
serves them by id + version, by recency, or by the version effective on a given
date. Registering two different rules under the same (id, version) is an error —
versions are immutable.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from klemr.rules.models import Rule

DATA_DIR = Path(__file__).parent / "data"


class DuplicateRuleVersion(ValueError):
    """Raised when a different rule is registered under an existing (id, version)."""


class RuleNotFound(KeyError):
    """Raised when a requested rule id / version is not in the store."""


class RuleStore:
    """An in-memory index of versioned rules."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], Rule] = {}

    def register(self, rule: Rule) -> None:
        key = (rule.rule_id, rule.version)
        existing = self._by_key.get(key)
        if existing is not None and existing.content_hash() != rule.content_hash():
            raise DuplicateRuleVersion(
                f"Rule {key} already registered with different content "
                f"({existing.content_hash()[:12]} != {rule.content_hash()[:12]})."
            )
        self._by_key[key] = rule

    def get(self, rule_id: str, version: str) -> Rule:
        try:
            return self._by_key[(rule_id, version)]
        except KeyError as exc:
            raise RuleNotFound(f"No rule {rule_id!r} version {version!r}") from exc

    def versions(self, rule_id: str) -> list[Rule]:
        """All versions of a rule, oldest effective_date first."""
        rules = [r for (rid, _), r in self._by_key.items() if rid == rule_id]
        if not rules:
            raise RuleNotFound(f"No rule {rule_id!r}")
        return sorted(rules, key=lambda r: (r.effective_date, r.version))

    def latest(self, rule_id: str) -> Rule:
        """The most recent version by effective_date."""
        return self.versions(rule_id)[-1]

    def effective_on(self, rule_id: str, on: date) -> Rule:
        """The version in force on ``on`` (latest with effective_date <= on)."""
        candidates = [r for r in self.versions(rule_id) if r.effective_date <= on]
        if not candidates:
            raise RuleNotFound(
                f"No version of {rule_id!r} effective on or before {on.isoformat()}"
            )
        return candidates[-1]

    def all(self) -> list[Rule]:
        return list(self._by_key.values())


def load_rule_file(path: Path) -> Rule:
    """Parse one rule JSON file into a validated ``Rule``."""
    with path.open(encoding="utf-8") as f:
        return Rule.model_validate(json.load(f))


def load_rules_from_dir(directory: Path = DATA_DIR) -> list[Rule]:
    return [load_rule_file(p) for p in sorted(directory.glob("*.json"))]


def default_rule_store() -> RuleStore:
    """A fresh store loaded with every bundled policy rule (currently: RAF-1a)."""
    store = RuleStore()
    for rule in load_rules_from_dir():
        store.register(rule)
    return store
