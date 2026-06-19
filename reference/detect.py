#!/usr/bin/env python3
"""
detect.py — Deterministic candidate detection for the TikTok Shop
Refund Administration Fee (RAF) auto-cancellation exemption (Leakage 1a).

WHAT THIS DOES (and does NOT do):
  It flags CANDIDATE orders that *might* be owed a RAF refund: buyer-initiated,
  pre-shipment cancellations that nonetheless had a RAF deducted in settlement.
  It CANNOT confirm the exemption on its own. The decisive condition — whether the
  cancellation was AUTO-APPROVED (24h SLA) or MANUALLY canceled by the seller — is
  NOT in these files. That lives in Seller Center order history and must be verified
  by a human (or the Order API) before anything is filed. This script therefore emits
  a review queue, not a final claim list.

INPUTS
  --settlement   one or more TikTok "income" .xlsx exports (sheet "Order details")
  --cancellations  the TikTok "Canceled_order" .csv export
OUTPUTS (written to --out dir)
  candidates.csv        flagged orders + blank `resolution` column for human verify
  anomalies.csv         anything amiss (cap breach, non-buyer cancels, etc.)
  not_in_settlement.csv canceled buyer-pre orders with no settled RAF (not a recovery)
  summary.txt / .json   human-readable + machine-readable run summary

Usage:
  python detect.py --settlement a.xlsx b.xlsx --cancellations c.csv --out ./out
"""
import argparse, json, os, sys, datetime as dt
import pandas as pd
import numpy as np

# ----------------------------- column resolution -----------------------------
def _norm(s): return "".join(ch for ch in str(s).lower() if ch.isalnum())

def find_col(cols, *aliases, required=True, label=None):
    """Find a column by fuzzy alias match (case/space/punct-insensitive)."""
    norm = {_norm(c): c for c in cols}
    for a in aliases:
        na = _norm(a)
        if na in norm:
            return norm[na]
        for k, orig in norm.items():
            if na and na in k:
                return orig
    if required:
        raise SystemExit(f"[detect] Could not find required column for "
                         f"{label or aliases[0]!r}. Available: {list(cols)}")
    return None

def clean_id(x):
    return str(x).replace("\t", "").replace("\u200b", "").strip()

# ----------------------------- loaders -----------------------------
def load_settlement(paths):
    frames = []
    for p in paths:
        xl = pd.ExcelFile(p)
        sheet = next((s for s in xl.sheet_names if _norm(s) == _norm("Order details")), None)
        if sheet is None:
            sheet = next((s for s in xl.sheet_names if "order" in _norm(s)), xl.sheet_names[0])
        df = xl.parse(sheet)
        df["__src__"] = os.path.basename(p)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)

def load_cancellations(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    return df

# ----------------------------- core detection -----------------------------
def run(settlement_paths, cancel_path, outdir, asof, maturity_days, fresh_days, raf_cap):
    os.makedirs(outdir, exist_ok=True)
    asof = pd.to_datetime(asof).normalize()
    mature_cutoff = asof - pd.Timedelta(days=maturity_days)
    fresh_cutoff  = asof - pd.Timedelta(days=fresh_days)

    # ---- cancellations ----
    can = load_cancellations(cancel_path)
    c_id   = find_col(can.columns, "Order ID", "Order/adjustment ID", label="cancellation Order ID")
    c_by   = find_col(can.columns, "Cancel By", "Canceled By", "Cancellation By", label="Cancel By")
    c_rts  = find_col(can.columns, "RTS Time", "Ready to Ship Time", required=False)
    c_when = find_col(can.columns, "Cancelled Time", "Canceled Time", "Cancellation Time", required=False)
    c_rsn  = find_col(can.columns, "Cancel Reason", "Cancellation Reason", "Reason", required=False)

    can["_oid"] = can[c_id].map(clean_id)
    can["_by"]  = can[c_by].astype(str).str.strip()
    can["_rts"] = can[c_rts].astype(str).str.strip() if c_rts else ""
    # collapse SKU-level rows to order level (keep first non-empty signal)
    g = can.groupby("_oid", as_index=False).agg({
        "_by":  lambda s: next((v for v in s if v), ""),
        "_rts": (lambda s: next((v for v in s if v and v.lower() not in ("nan","none","")), "")) if c_rts else (lambda s: ""),
    })
    if c_rsn:
        rsn = can.groupby("_oid")[c_rsn].agg(lambda s: next((v for v in s if v), "")).rename("reason")
        g = g.merge(rsn, left_on="_oid", right_index=True, how="left")
    else:
        g["reason"] = ""
    if c_when:
        whn = can.groupby("_oid")[c_when].agg(lambda s: next((v for v in s if v), "")).rename("cancelled_time")
        g = g.merge(whn, left_on="_oid", right_index=True, how="left")
    else:
        g["cancelled_time"] = ""

    g["buyer_initiated"] = g["_by"].str.lower().eq("user")
    g["pre_shipment"]    = g["_rts"].str.lower().isin(["", "nan", "none"])  # no RTS = not yet shipped
    buyer_pre = g[g["buyer_initiated"] & g["pre_shipment"]].copy()

    # ---- settlement ----
    st = load_settlement(settlement_paths)
    s_id  = find_col(st.columns, "Order/adjustment ID", "Order ID", "Order adjustment ID", label="settlement Order ID")
    s_raf = find_col(st.columns, "Refund administration fee", "Refund admin fee", "RAF", label="Refund administration fee")
    s_ref = find_col(st.columns, "Referral fee", required=False)
    s_dt  = find_col(st.columns, "Statement date", "Order settled time", "Settlement date", required=False)

    st["_oid"] = st[s_id].map(clean_id)
    st["_raf"] = pd.to_numeric(st[s_raf], errors="coerce").fillna(0.0)
    st["_ref"] = pd.to_numeric(st[s_ref], errors="coerce").fillna(0.0) if s_ref else 0.0
    if s_dt:
        st["_stmt"] = pd.to_datetime(st[s_dt], errors="coerce")
    else:
        st["_stmt"] = pd.NaT

    # RAF is stored as a negative deduction; recover magnitude per order
    agg = st.groupby("_oid").agg(
        raf_sum=("_raf", lambda s: float(-s[s < 0].sum())),   # magnitude of deductions
        raf_lines=("_raf", lambda s: int((s < 0).sum())),
        raf_max_line=("_raf", lambda s: float(-s.min()) if (s < 0).any() else 0.0),
        ref_sum=("_ref", "sum"),
        stmt_date=("_stmt", "max"),
    ).reset_index()

    # ---- join: buyer-pre orders that DID get a RAF deducted ----
    j = buyer_pre.merge(agg, on="_oid", how="left", indicator=True)
    flagged = j[(j["_merge"] == "both") & (j["raf_sum"] > 0)].copy()
    not_in  = buyer_pre.merge(agg, on="_oid", how="left").query("raf_sum.isna() or raf_sum == 0", engine="python")

    # ---- maturity / freshness ----
    flagged["mature"] = flagged["stmt_date"].le(mature_cutoff)
    flagged["fresh"]  = flagged["stmt_date"].gt(fresh_cutoff)
    flagged["recoverable_amount"] = flagged["raf_sum"].round(2)

    # ---- anomaly checks (deterministic, from data) ----
    anomalies = []
    for _, r in flagged.iterrows():
        oid = r["_oid"]; raf = r["raf_sum"]; ref = r["ref_sum"]; lines = int(r["raf_lines"])
        # 1) per-line cap breach
        if r["raf_max_line"] > raf_cap + 1e-6:
            anomalies.append((oid, "RAF_LINE_EXCEEDS_CAP",
                f"A RAF line is ${r['raf_max_line']:.2f}, above the ${raf_cap:.2f}/SKU cap — verify SKU split."))
        # 2) RAF vs 20% of referral sanity (only if referral present)
        if ref and ref < 0:  # referral stored negative as a fee
            expected = min(abs(ref) * 0.20, raf_cap * max(lines, 1))
            if raf > expected + 0.05:
                anomalies.append((oid, "RAF_ABOVE_20PCT_REFERRAL",
                    f"RAF ${raf:.2f} exceeds ~20% of referral (${abs(ref)*0.2:.2f}) — verify."))
        # 3) missing settlement date
        if pd.isna(r["stmt_date"]):
            anomalies.append((oid, "MISSING_SETTLEMENT_DATE",
                "No statement date — maturity cannot be assessed; verify manually."))
    # 4) non-buyer / non-pre cancels that still carried a RAF.
    #    This is INFORMATIONAL, not an anomaly: RAF is correctly chargeable on
    #    post-ship or non-buyer cancellations. Routed to its own file so it does
    #    not drown out genuine data issues. May contain other leakage rows
    #    (post-ship returns, creator-sample 1b) handled by separate audits.
    non_eligible = g[~(g["buyer_initiated"] & g["pre_shipment"])].merge(agg, on="_oid", how="inner")
    non_eligible = non_eligible[non_eligible["raf_sum"] > 0].copy()
    def _why(r):
        w = []
        if not r["buyer_initiated"]: w.append(f"Cancel By='{r['_by']}'")
        if not r["pre_shipment"]:    w.append("RTS present (shipped)")
        return "; ".join(w)
    non_eligible["out_of_scope_reason"] = non_eligible.apply(_why, axis=1)

    # ----------------------------- write outputs -----------------------------
    cand_cols = ["_oid", "reason", "cancelled_time", "stmt_date",
                 "recoverable_amount", "raf_lines", "mature", "fresh"]
    cand = flagged[cand_cols].rename(columns={"_oid": "order_id"}).sort_values(
        "recoverable_amount", ascending=False)
    cand["seller_center_url"] = cand["order_id"].map(
        lambda o: f"https://seller-us.tiktok.com/order/detail?order_no={o}&shop_region=US")
    # the two columns a human (or Order API) must fill before anything is filed:
    cand["resolution"] = ""           # auto_approved | seller_canceled | other
    cand["resolution_timestamp"] = "" # the order-history line timestamp
    cand["screenshot"] = ""           # filename of the order-history exhibit
    cand.to_csv(os.path.join(outdir, "candidates.csv"), index=False)

    pd.DataFrame(anomalies, columns=["order_id", "code", "detail"]).to_csv(
        os.path.join(outdir, "anomalies.csv"), index=False)

    ni = not_in[["_oid", "reason", "cancelled_time"]].rename(columns={"_oid": "order_id"})
    ni.to_csv(os.path.join(outdir, "not_in_settlement.csv"), index=False)

    non_eligible[["_oid", "_by", "out_of_scope_reason", "raf_sum"]].rename(
        columns={"_oid": "order_id", "_by": "cancel_by", "raf_sum": "raf_charged"}
    ).to_csv(os.path.join(outdir, "raf_out_of_scope_informational.csv"), index=False)

    # ----------------------------- summary -----------------------------
    n_flag = len(cand); total = round(float(cand["recoverable_amount"].sum()), 2)
    n_mat = int(cand["mature"].sum()); n_fresh = int(cand["fresh"].sum())
    summary = {
        "as_of": str(asof.date()),
        "settlement_files": [os.path.basename(p) for p in settlement_paths],
        "cancellation_file": os.path.basename(cancel_path),
        "canceled_orders_total": int(g["_oid"].nunique()),
        "buyer_initiated_preship": int(len(buyer_pre)),
        "flagged_candidates": n_flag,
        "candidate_ceiling_amount": total,
        "mature_candidates": n_mat,
        "fresh_settled_candidates": n_fresh,
        "canceled_not_in_settlement": int(len(ni)),
        "raf_out_of_scope_rows": int(len(non_eligible)),
        "anomalies": int(len(anomalies)),
        "maturity_days": maturity_days,
        "raf_cap_per_sku": raf_cap,
    }
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    lines = []
    P = lines.append
    P("="*70)
    P("RAF AUTO-CANCELLATION EXEMPTION — CANDIDATE DETECTION (Leakage 1a)")
    P("="*70)
    P(f"As of {asof.date()}  |  maturity {maturity_days}d  |  cap ${raf_cap:.2f}/SKU")
    P("")
    P(f"  Canceled orders (export) .............. {summary['canceled_orders_total']:>6}")
    P(f"  Buyer-initiated AND pre-shipment ...... {summary['buyer_initiated_preship']:>6}")
    P(f"  FLAGGED (had RAF in settlement) ....... {n_flag:>6}   ceiling ${total:,.2f}")
    P(f"     of which mature (>= {maturity_days}d) ......... {n_mat:>6}")
    P(f"     of which freshly settled (< {fresh_days}d) .... {n_fresh:>6}   (file in 2nd wave)")
    P(f"  Canceled but NOT in settlement ........ {summary['canceled_not_in_settlement']:>6}   (no RAF = no recovery)")
    P(f"  RAF on out-of-scope cancels (info) .... {summary['raf_out_of_scope_rows']:>6}   (post-ship / non-buyer; not 1a)")
    P(f"  Genuine anomalies for review .......... {summary['anomalies']:>6}")
    P("")
    P("*** ${:,.2f} is a CEILING, not a claim. Nothing here is filable yet. ***".format(total))
    P("")
    P("NEXT STEP — HUMAN / API VERIFICATION REQUIRED (decisive Gate 3):")
    P("  These files cannot prove the order auto-cancelled vs. was seller-canceled.")
    P("  For each candidate, open the Seller Center URL (in candidates.csv) and read")
    P("  the Order history resolution line, then fill the `resolution` column:")
    P("    'auto_approved'   <- '...awaiting approval too long, now auto-approved'  => FILABLE")
    P("    'seller_canceled' <- 'Seller canceled the order'                         => HOLD (Tier 2)")
    P("    'other'           <- anything else                                       => human review")
    P("  Save an order-history screenshot per filable order and put its filename in")
    P("  the `screenshot` column. Then run build_packet.py.")
    P("="*70)
    txt = "\n".join(lines)
    with open(os.path.join(outdir, "summary.txt"), "w") as f:
        f.write(txt + "\n")
    print(txt)
    return summary

def main():
    ap = argparse.ArgumentParser(description="Detect RAF auto-cancel exemption candidates (1a).")
    ap.add_argument("--settlement", nargs="+", required=True)
    ap.add_argument("--cancellations", required=True)
    ap.add_argument("--out", default="./raf_out")
    ap.add_argument("--asof", default=dt.date.today().isoformat())
    ap.add_argument("--maturity-days", type=int, default=21)
    ap.add_argument("--fresh-days", type=int, default=3)
    ap.add_argument("--raf-cap", type=float, default=5.0)
    a = ap.parse_args()
    run(a.settlement, a.cancellations, a.out, a.asof, a.maturity_days, a.fresh_days, a.raf_cap)

if __name__ == "__main__":
    main()
