"""Versioned rule store — policy as data."""
from klemr.rules.models import (
    Gate,
    PolicyCitation,
    ResolutionOutcome,
    ResolutionPolicy,
    Rule,
    RuleParameters,
)
from klemr.rules.store import (
    DATA_DIR,
    DuplicateRuleVersion,
    RuleNotFound,
    RuleStore,
    default_rule_store,
    load_rules_from_dir,
)

# The canonical rule id for the one claim type in scope (Leakage 1a).
RAF_AUTO_CANCEL_RULE_ID = "raf.auto_cancel_exemption"

__all__ = [
    "Rule",
    "RuleParameters",
    "PolicyCitation",
    "Gate",
    "ResolutionOutcome",
    "ResolutionPolicy",
    "RuleStore",
    "default_rule_store",
    "load_rules_from_dir",
    "DuplicateRuleVersion",
    "RuleNotFound",
    "DATA_DIR",
    "RAF_AUTO_CANCEL_RULE_ID",
]
