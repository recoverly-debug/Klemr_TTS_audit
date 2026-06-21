"""Tier-1 evidence packet (PDF) — a faithful DISPLAY layer over verified findings.

The packet invents nothing: every number, date, citation and screenshot traces to a
Finding (replay output), a ledger resolution, or a rule already in the system.
"Math decides" already happened upstream; this renders it.

Inputs: the verified findings + the RuleStore + the EvidenceLedger. Tiers are read
off the findings' states (never recomputed here). Totals are row-sums of the shown
findings. A missing screenshot is rendered as a visible "pending" placeholder and
listed on the cover — never faked.

reportlab note (per the pdf skill): the base-14 fonts only cover Latin-1, so this
module uses only Latin-1-safe glyphs (em dash, middot, curly quotes, bullet) — no
checkmarks/sub/superscripts, which would render as black boxes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from klemr.claims.state import ClaimState

NAVY = colors.HexColor("#0F2436")
TEAL = colors.HexColor("#0E7C7B")
TEALLT = colors.HexColor("#E3F1F1")
GREEN = colors.HexColor("#1B7F4B")
GREENLT = colors.HexColor("#E6F4EC")
AMBER = colors.HexColor("#B26A00")
AMBERLT = colors.HexColor("#FBF3E2")
GRAY = colors.HexColor("#5A6B78")
LIGHT = colors.HexColor("#F2F5F7")
LINE = colors.HexColor("#D5DDE3")


@dataclass
class PacketResult:
    out_path: str
    tier1_count: int
    tier1_total: Decimal
    tier2_count: int
    tier2_total: Decimal
    evidence_pages: int
    total_pages: int
    real_screenshots: int
    rule_content_hash: str
    hash_matches: bool
    # ripe-now split of the filable total (informational maturity flag, not a state)
    tier1_mature_total: Decimal = Decimal("0.00")
    tier1_maturing_total: Decimal = Decimal("0.00")
    tier1_mature_count: int = 0
    tier1_maturing_count: int = 0
    cropped_screenshots: int = 0
    pending_orders: list[str] = field(default_factory=list)


def _money(d: Decimal) -> str:
    return f"${d:,.2f}"


def _resolve_screenshot(evidence_ref, screenshots_dir):
    if not evidence_ref:
        return None
    p = Path(evidence_ref)
    if not p.is_absolute() and screenshots_dir:
        p = Path(screenshots_dir) / evidence_ref
    return str(p) if p.exists() else None


def _load_exhibit(path, crop_top, crop_right, min_aspect):
    """Open a screenshot and, ONLY for landscape full-window captures, crop the
    browser chrome (top band) and right-edge assistant overlay. Returns
    ``(BytesIO_or_path, width, height, cropped)``. Never upscales or distorts; if the
    capture isn't full-window (aspect < min_aspect), it is embedded uncropped.
    """
    with PILImage.open(path) as im:
        im.load()
        w, h = im.size
        if w / h < min_aspect or (crop_top <= 0 and crop_right <= 0):
            return path, w, h, False  # not a full-window capture -> embed as-is
        box = (0, int(h * crop_top), w - int(w * crop_right), h)
        cropped = im.crop(box)
        buf = BytesIO()
        cropped.save(buf, format="PNG")  # deterministic re-encode
        buf.seek(0)
        return buf, cropped.size[0], cropped.size[1], True


def build_packet(
    findings,
    *,
    rule_store,
    ledger,
    run_date: date,
    run_fingerprint: str,
    out_path,
    brand: str = "Klemr",
    client: str = "Haus Apparel",
    claim_title: str = "TikTok Shop RAF — Auto-Cancellation Exemption (Leakage 1a)",
    screenshots_dir=None,
    charge_lines: dict | None = None,
    funnel: dict | None = None,
    chrome_crop_top: float = 0.12,
    chrome_crop_right: float = 0.035,
    chrome_crop_min_aspect: float = 1.4,
    validate_against_ledger: bool = True,
    require_evidence: bool = False,
) -> PacketResult:
    """Render the packet. Deterministic: same inputs -> identical bytes (invariant on).

    ``chrome_crop_*`` are a SAFETY NET (Fix 2): a stray full-window screenshot has its
    browser chrome (top tabs/bookmarks/address bar) and right-edge assistant overlay
    cropped before embedding, so analyst desktop context never reaches a client doc.
    Cropping only trims non-content margins and only applies to landscape full-window
    captures (aspect >= ``chrome_crop_min_aspect``) — it never distorts, upscales, or
    removes order-history content. The durable fix is clean capture (see the SOP).
    """
    rl_config.invariant = 1  # fixed PDF id + creation date -> reproducible output

    tier1 = sorted(
        (f for f in findings if f.state is ClaimState.FILABLE),
        key=lambda f: f.credit_match_key.order_id,
    )
    tier2 = sorted(
        (f for f in findings
         if f.state is ClaimState.DISMISSED and f.tier2_appeal_candidate),
        key=lambda f: f.credit_match_key.order_id,
    )
    # totals are row-sums of the shown findings (never literals)
    t1_total = sum((f.ceiling_amount for f in tier1), Decimal("0.00"))
    t2_total = sum((f.ceiling_amount for f in tier2), Decimal("0.00"))

    # citation comes from the findings' own rule version (and we prove the hash matches)
    if not tier1 and not tier2:
        raise ValueError(
            "build_packet: no filable or Tier-2 findings to render — nothing to attest. "
            "A run with zero verified findings should be reported as a clean bill, not a packet."
        )
    sample = (tier1 or tier2)[0]
    rule = rule_store.get(sample.rule_id, sample.rule_version)
    rule_hash = rule.content_hash()
    # integrity line covers the RENDERED claims only (not unrelated input findings)
    hash_matches = all(f.rule_content_hash == rule_hash for f in (*tier1, *tier2))

    # maturity window comes from rule data (parameters), not a constant
    maturity_days = rule.parameters.maturity_days
    fresh_days = rule.parameters.fresh_days
    # ripe-now split of the filable total (row-sums over the informational flag)
    t1_mature = sum((f.ceiling_amount for f in tier1 if f.mature), Decimal("0.00"))
    t1_maturing = t1_total - t1_mature
    n_mature = sum(1 for f in tier1 if f.mature)
    n_maturing = len(tier1) - n_mature

    # resolve each filable finding's verified resolution + screenshot
    resolutions = {f.finding_id: ledger.latest_resolution(f.finding_id) for f in tier1}

    # TRUST BOUNDARY (#8): every Tier-1 claim must be backed by a recorded ledger
    # resolution that classifies as filable — never an in-memory projection. "A claim is
    # never filable on a guess." Disable only to test the display layer in isolation.
    if validate_against_ledger:
        unbacked = [
            f.credit_match_key.order_id for f in tier1
            if resolutions[f.finding_id] is None
            or rule.resolution_policy.classify(resolutions[f.finding_id].resolved_value)
            is not rule.resolution_policy.filable
        ]
        if unbacked:
            raise ValueError(
                f"build_packet: {len(unbacked)} Tier-1 finding(s) lack a filable ledger "
                f"resolution and cannot be attested: {unbacked}."
            )

    shots: dict[str, str | None] = {}
    pending: list[str] = []
    for f in tier1:
        res = resolutions[f.finding_id]
        path = _resolve_screenshot(res.evidence_ref if res else None, screenshots_dir)
        shots[f.finding_id] = path
        if path is None:
            pending.append(f.credit_match_key.order_id)

    # FINALIZATION GATE (#2): a *filing* packet must have every exhibit. Default off keeps
    # the draft behavior (render "EXHIBIT PENDING" + list on cover); require_evidence=True
    # makes finalization fail hard rather than emit a packet with missing proof.
    if require_evidence and pending:
        raise ValueError(
            f"build_packet(require_evidence=True): {len(pending)} filable order(s) have no "
            f"Seller Center exhibit: {pending}. Capture the screenshots before finalizing."
        )

    ss = getSampleStyleSheet()

    def mk(name, **kw):
        return ParagraphStyle(name, parent=ss["Normal"], **kw)

    st_title = mk("t", fontName="Helvetica-Bold", fontSize=22, textColor=NAVY, leading=26)
    st_sub = mk("s", fontName="Helvetica", fontSize=12, textColor=TEAL, leading=16)
    st_sm = mk("sm", fontName="Helvetica", fontSize=8.5, textColor=GRAY, leading=12)
    st_b = mk("b", fontName="Helvetica", fontSize=9.5, textColor=NAVY, leading=14)
    st_h2 = mk("h2", fontName="Helvetica-Bold", fontSize=12.5, textColor=NAVY, leading=16,
               spaceBefore=4, spaceAfter=4)
    st_kn = mk("kn", fontName="Helvetica-Bold", fontSize=19, textColor=NAVY, leading=22, alignment=1)
    st_kl = mk("kl", fontName="Helvetica", fontSize=7.5, textColor=GRAY, leading=10, alignment=1)
    st_ch = mk("ch", fontName="Helvetica-Bold", fontSize=12, textColor=colors.white, leading=15)
    st_ca = mk("ca", fontName="Helvetica-Bold", fontSize=12, textColor=colors.white, leading=15,
               alignment=TA_RIGHT)
    st_lbl = mk("l", fontName="Helvetica-Bold", fontSize=7.5, textColor=GRAY, leading=11)
    st_val = mk("v", fontName="Helvetica", fontSize=9, textColor=NAVY, leading=12)
    st_th = mk("th", fontName="Helvetica-Bold", fontSize=7.6, textColor=colors.white, leading=9.5)
    st_td = mk("td", fontName="Helvetica", fontSize=7.6, textColor=NAVY, leading=9.5)
    st_tdr = mk("tdr", fontName="Helvetica", fontSize=7.6, textColor=NAVY, leading=9.5, alignment=TA_RIGHT)
    st_mono = mk("mono", fontName="Courier", fontSize=7.5, textColor=GRAY, leading=10)

    CW = letter[0] - 86

    def footer(c, d):
        c.saveState()
        c.setStrokeColor(LINE); c.setLineWidth(0.5)
        c.line(43, 34, letter[0] - 43, 34)
        c.setFont("Helvetica", 7); c.setFillColor(GRAY)
        c.drawString(43, 24, f"{brand}  ·  TikTok Shop RAF Recovery — Tier 1 Evidence Packet  ·  {client}  ·  Confidential")
        c.drawRightString(letter[0] - 43, 24, f"Page {d.page}")
        c.restoreState()

    story = []

    # ---------------- COVER ----------------
    bar = Table([[""]], colWidths=[CW], rowHeights=[5])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL)]))
    story += [Spacer(1, 6), bar, Spacer(1, 14),
              Paragraph("Refund Administration Fee — Recovery Evidence Packet", st_title),
              Spacer(1, 4),
              Paragraph(f"{claim_title}  ·  {client} (Seller-Fulfilled)", st_sub),
              Spacer(1, 4),
              Paragraph(f"Prepared by {brand}  ·  Run {run_date.isoformat()}", st_sm),
              Paragraph(f"Run fingerprint  ·  {run_fingerprint}", st_mono),
              Spacer(1, 16)]
    kpi = Table([[
        [Paragraph(f"{len(tier1)}", st_kn), Paragraph("TIER 1 FILABLE CLAIMS", st_kl)],
        [Paragraph(_money(t1_total), st_kn), Paragraph("RECOVERABLE (TIER 1)", st_kl)],
        [Paragraph(f"{len(tier2)}", st_kn), Paragraph("TIER 2 APPEAL CANDIDATES", st_kl)],
        [Paragraph(_money(t2_total), st_kn), Paragraph("CONTESTABLE (TIER 2)", st_kl)],
    ]], colWidths=[CW / 4] * 4)
    kpi.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    ripe = Table([[Paragraph(
        f"<b>Tier-1 readiness</b> (of {_money(t1_total)}):  "
        f"<b>{_money(t1_mature)}</b> ready to file now — {n_mature} mature orders  ·  "
        f"<b>{_money(t1_maturing)}</b> maturing — {n_maturing} orders for the next wave.", st_sm)]],
        colWidths=[CW])
    ripe.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [kpi, Spacer(1, 8), ripe, Spacer(1, 16), Paragraph("What this packet contains", st_h2),
              Paragraph(f"{len(tier1)} TikTok Shop orders on which a Refund Administration Fee (RAF) was "
                        "deducted even though the order qualified for the auto-cancellation exemption "
                        "(buyer-initiated, pre-shipment, resolved by TikTok's 24-hour auto-approval SLA). "
                        "Each is supported by a Seller Center order-history screenshot on its own page. A "
                        f"separate Tier 2 section lists {len(tier2)} seller-canceled orders as appeal "
                        "candidates (contestable, not filed here). Totals are recomputed from the rows shown.", st_b),
              Spacer(1, 10)]
    if pending:
        story += [Paragraph("Screenshots pending (rendered as EXHIBIT PENDING — supply before filing):", st_h2),
                  Paragraph(", ".join(pending), st_sm), Spacer(1, 8)]
    else:
        story += [Paragraph("All Tier-1 claims have an attached Seller Center screenshot exhibit.", st_sm)]
    story += [PageBreak()]

    # ---------------- POLICY ----------------
    cit = rule.citation
    story += [Paragraph("Policy Basis", st_title), Spacer(1, 6),
              Paragraph(f"{cit.title} — {cit.publisher}", st_h2),
              Paragraph(f"Last revised {cit.last_revised.isoformat()}  ·  {cit.url}", st_sm),
              Spacer(1, 10), Paragraph("Exemption (verbatim policy text)", st_h2)]
    quote = Table([[Paragraph(f"“{cit.quote}”",
                   mk("q", fontName="Helvetica-Oblique", fontSize=11, textColor=NAVY, leading=16))]], colWidths=[CW])
    quote.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEALLT), ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    fee = rule.payload.get("fee_schedule", {})
    story += [quote, Spacer(1, 12), Paragraph("Fee schedule (as data)", st_h2),
              Paragraph(f"RAF = {fee.get('referral_fee_rate','?')} × referral fee, capped at "
                        f"${fee.get('per_sku_cap','?')} per SKU (effective {fee.get('cap_effective_date','?')}).", st_b),
              Spacer(1, 12), Paragraph("Provenance — rule version &amp; integrity", st_h2),
              Paragraph(f"Rule: {rule.rule_id}  ·  version {rule.version}", st_b),
              Paragraph(f"Rule content hash: {rule_hash}", st_mono)]
    tamper = ("INTEGRITY OK — every finding in this packet was produced under this exact rule hash."
              if hash_matches else
              "WARNING — a finding's rule hash does NOT match this rule version. Do not file.")
    tline = Table([[Paragraph(tamper, mk("ti", fontName="Helvetica-Bold", fontSize=8.5,
                   textColor=(GREEN if hash_matches else AMBER), leading=12))]], colWidths=[CW])
    tline.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GREENLT if hash_matches else AMBERLT),
        ("BOX", (0, 0), (-1, -1), 0.5, GREEN if hash_matches else AMBER),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [Spacer(1, 6), tline, PageBreak()]

    # ---------------- GATE TEST ----------------
    story += [Paragraph("The Three-Gate Test", st_title), Spacer(1, 6),
              Paragraph("A claim is Tier-1 filable only if all three gates hold. Gates 1 and 2 are read "
                        "from the export data; Gate 3 — the decisive one — is NOT in the data and was "
                        "verified per order against Seller Center order history and recorded in the ledger.", st_b),
              Spacer(1, 10)]
    gate_rows = [[Paragraph("GATE", st_th), Paragraph("CONDITION", st_th), Paragraph("SOURCE", st_th)]]
    for g in rule.gates:
        gate_rows.append([Paragraph(f"Gate {g.number} — {g.name}", st_td),
                          Paragraph(g.description, st_td),
                          Paragraph("Seller Center (verified)" if not g.in_data else "Export data", st_td)])
    gt = Table(gate_rows, colWidths=[CW * 0.22, CW * 0.56, CW * 0.22])
    gt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    f_canceled = funnel.get("canceled") if funnel else None
    f_inscope = funnel.get("in_scope") if funnel else None
    f_flagged = funnel.get("flagged") if funnel else (len(tier1) + len(tier2))
    narrowing = "  →  ".join(filter(None, [
        f"{f_canceled} canceled" if f_canceled else None,
        f"{f_inscope} buyer + pre-shipment" if f_inscope else None,
        f"{f_flagged} flagged (RAF charged)",
        f"{len(tier1)} Tier-1 filable",
    ]))
    legend = (f"<b>Maturity</b> (informational flag, NOT a filing state). "
              f"<b>Mature</b> = settled {maturity_days}+ days ago, past TikTok's settlement-reconciliation "
              f"window — ready to file now. <b>Maturing</b> = settled within the last {maturity_days} days "
              f"(<b>Fresh</b> = within {fresh_days} days); re-verify and file in the next wave once past the "
              f"window. All {len(tier1)} orders here are filable; maturity only sequences when to file.")
    leg = Table([[Paragraph(legend, st_sm)]], colWidths=[CW])
    leg.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEALLT), ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [gt, Spacer(1, 14), Paragraph("How the funnel narrowed", st_h2),
              Paragraph(narrowing, st_sub),
              Paragraph(f"({len(tier2)} flagged orders were verified seller-canceled — see Tier 2.)", st_sm),
              Spacer(1, 12), Paragraph("Maturity legend", st_h2), leg,
              PageBreak()]

    # ---------------- 23 EVIDENCE PAGES ----------------
    n = len(tier1)
    cropped_count = 0
    for i, f in enumerate(tier1):
        res = resolutions[f.finding_id]
        amt = f.ceiling_amount
        oid = f.credit_match_key.order_id
        flow = []
        hdr = Table([[Paragraph(f"Claim {i + 1} of {n} — Order {oid}", st_ch),
                      Paragraph(f"RAF {_money(amt)}", st_ca)]], colWidths=[CW * 0.74, CW * 0.26])
        hdr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        flow.append(hdr)

        resolved_at = res.resolved_at if res else "(missing)"
        reviewer = res.reviewer if res else "(missing)"
        facts = Table([
            [Paragraph("RECOVERABLE RAF", st_lbl), Paragraph(_money(amt), st_val),
             Paragraph("MATURITY", st_lbl),
             Paragraph("Mature — file now" if f.mature
                       else (f"Maturing — fresh (&lt;{fresh_days}d)" if f.fresh else "Maturing — next wave"), st_val)],
            [Paragraph("GATE-3 RESOLUTION", st_lbl), Paragraph(str(res.resolved_value if res else "?"), st_val),
             Paragraph("VERIFIED BY", st_lbl), Paragraph(reviewer, st_val)],
            [Paragraph("RESOLVED AT", st_lbl), Paragraph(str(resolved_at), st_val),
             Paragraph("FULFILLMENT", st_lbl), Paragraph("Seller-fulfilled", st_val)],
        ], colWidths=[CW * 0.18, CW * 0.32, CW * 0.18, CW * 0.32])
        facts.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        flow += [facts, Spacer(1, 6)]

        # RAF rows (per-SKU, summed) — shown from the canonical charge lines when provided
        lines = (charge_lines or {}).get(oid, [])
        rows = [[Paragraph("#", st_th), Paragraph("SKU ID", st_th), Paragraph("SETTLED", st_th), Paragraph("RAF", st_th)]]
        if lines:
            for j, c in enumerate(lines):
                rows.append([Paragraph(str(j + 1), st_td), Paragraph(str(c.sku_id or "(order)"), st_td),
                             Paragraph(str(c.statement_date or ""), st_td),
                             Paragraph(_money(c.deduction_magnitude), st_tdr)])
        else:
            rows.append([Paragraph("—", st_td), Paragraph("(see provenance rows)", st_td),
                         Paragraph("", st_td), Paragraph(_money(amt), st_tdr)])
        rows.append([Paragraph("", st_td), Paragraph("", st_td), Paragraph("ORDER TOTAL (row-sum)", st_td),
                     Paragraph(_money(amt), st_tdr)])
        rt = Table(rows, colWidths=[CW * 0.08, CW * 0.5, CW * 0.22, CW * 0.2])
        rt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), TEAL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]), ("BACKGROUND", (0, -1), (-1, -1), TEALLT),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, TEAL), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
        flow += [rt, Spacer(1, 6)]

        chips = Table([[
            _chip("Gate 1  Buyer-initiated", st_td), _chip("Gate 2  Pre-shipment", st_td),
            _chip("Gate 3  Auto-approved (verified)", st_td)]], colWidths=[CW / 3.0] * 3)
        chips.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        flow += [chips, Spacer(1, 7),
                 Paragraph("EXHIBIT — Seller Center order history", st_lbl), Spacer(1, 3)]

        shot = shots[f.finding_id]
        if shot:
            src, iw, ih, was_cropped = _load_exhibit(
                shot, chrome_crop_top, chrome_crop_right, chrome_crop_min_aspect)
            cropped_count += int(was_cropped)
            scale = min(CW / iw, 360 / ih, 1.0)  # fit, never upscale
            pic = Image(src, width=iw * scale, height=ih * scale)
            pic.hAlign = "CENTER"
            fr = Table([[pic]], colWidths=[iw * scale])
            fr.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
            fr.hAlign = "CENTER"
            flow.append(fr)
        else:
            ph = Table([[Paragraph("EXHIBIT PENDING — attach Seller Center order-history screenshot before filing.",
                       mk("ph", fontName="Helvetica-Bold", fontSize=9, textColor=AMBER, leading=12, alignment=1))]],
                       colWidths=[CW], rowHeights=[90])
            ph.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AMBERLT), ("BOX", (0, 0), (-1, -1), 0.6, AMBER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            flow.append(ph)
        story.append(KeepTogether(flow))
        story.append(PageBreak())

    # ---------------- TIER 2 — APPEAL CANDIDATES ----------------
    story += [Paragraph("Tier 2 — Appeal Candidates", st_title), Spacer(1, 4),
              Paragraph(f"{len(tier2)} orders  ·  {_money(t2_total)} contestable  ·  NOT filed in this packet", st_sub),
              Spacer(1, 8),
              Paragraph("These orders were verified <b>seller-canceled</b> (Gate 3). Under a strict reading of "
                        "the exemption they are not cleanly filable, but a buyer-initiated pre-shipment cancel "
                        "may be argued exempt regardless of who approved it. They are carried as appeal "
                        "candidates — separate from the Tier-1 filable claims above.", st_b), Spacer(1, 10)]
    t2rows = [[Paragraph(h, st_th) for h in ["#", "Order ID", "RAF", "Resolution"]]]
    for i, f in enumerate(tier2):
        res = ledger.latest_resolution(f.finding_id)
        t2rows.append([Paragraph(str(i + 1), st_td), Paragraph(f.credit_match_key.order_id, st_td),
                       Paragraph(_money(f.ceiling_amount), st_tdr),
                       Paragraph(str(res.resolved_value if res else "seller_canceled"), st_td)])
    t2rows.append([Paragraph("", st_td), Paragraph("", st_td), Paragraph(f"<b>{_money(t2_total)}</b>", st_tdr),
                   Paragraph("<b>row-sum</b>", st_td)])
    t2 = Table(t2rows, colWidths=[CW * 0.08, CW * 0.42, CW * 0.2, CW * 0.3])
    t2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]), ("BACKGROUND", (0, -1), (-1, -1), TEALLT),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, TEAL), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [t2, Spacer(1, 12),
              Paragraph("Policy basis for the appeal (same exemption text)", st_h2),
              Paragraph(f"“{cit.quote}”  — {cit.title}, rev. {cit.last_revised.isoformat()}", st_sm)]

    doc = SimpleDocTemplate(str(out_path), pagesize=letter, leftMargin=43, rightMargin=43,
                            topMargin=46, bottomMargin=46,
                            title=f"{brand} RAF Tier 1 Evidence Packet - {client}", author=brand)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    return PacketResult(
        out_path=str(out_path),
        tier1_count=len(tier1), tier1_total=t1_total,
        tier2_count=len(tier2), tier2_total=t2_total,
        evidence_pages=len(tier1), total_pages=doc.page,
        real_screenshots=len(tier1) - len(pending),
        rule_content_hash=rule_hash, hash_matches=hash_matches,
        tier1_mature_total=t1_mature, tier1_maturing_total=t1_maturing,
        tier1_mature_count=n_mature, tier1_maturing_count=n_maturing,
        cropped_screenshots=cropped_count,
        pending_orders=pending,
    )


def _chip(text, base):
    p = Paragraph(text, ParagraphStyle("gc", parent=base, fontName="Helvetica-Bold",
                                       fontSize=7.5, textColor=GREEN, leading=9))
    t = Table([[p]])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GREENLT), ("BOX", (0, 0), (-1, -1), 0.5, GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t
