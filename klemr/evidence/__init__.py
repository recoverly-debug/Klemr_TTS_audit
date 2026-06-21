"""Evidence assembly — Tier-1 evidence packet PDF (Step 5).

A faithful display layer over verified findings: renders what replay() + the ledger +
the rule store provide, and nothing else. Requires the ``packet`` optional extra
(reportlab + pillow).
"""
from klemr.evidence.packet import PacketResult, build_packet

__all__ = ["build_packet", "PacketResult"]
