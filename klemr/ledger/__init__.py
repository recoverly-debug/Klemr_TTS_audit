"""Evidence ledger — SQLite provenance store (Step 4).

Every finding records its source rows, rule version + content hash, confidence,
and (post-verify) reviewer + resolution + screenshot. All verification decisions
are written here so a UI refresh never loses work. The recovery / credit ledger is
a stubbed interface only. Not implemented in this slice.
"""
