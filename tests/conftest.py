"""Shared fixtures. The TikTok exports are read ONCE per test session (openpyxl is the
cost) and reused by every ingestion/reconciliation test. Imports are lazy so this
conftest stays importable without the `ingest` extra (modules that need it
``importorskip`` pandas themselves)."""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETTLEMENTS = sorted(glob.glob(str(ROOT / "fixtures" / "raw" / "income_*.xlsx")))
CANCELLATION = str(ROOT / "fixtures" / "raw" / "Canceled order-2026-06-17-16_14.csv")
RESOLUTIONS = str(ROOT / "fixtures" / "resolutions_haus.csv")


@pytest.fixture(scope="session")
def tiktok_export():
    from klemr.normalization.pipeline import fetch_tiktok

    return fetch_tiktok(SETTLEMENTS, CANCELLATION)


@pytest.fixture(scope="session")
def canonical_dataset(tiktok_export):
    from klemr.normalization.pipeline import normalize_export

    # ingested_at left None -> deterministic, never fabricated.
    return normalize_export(tiktok_export)
