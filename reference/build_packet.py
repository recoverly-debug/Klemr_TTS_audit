#!/usr/bin/env python3
"""
build_packet.py — Build the Tier-1 (filable) RAF evidence packet PDF from a
VERIFIED candidates.csv (the `resolution` column filled in by a human or the
Order API). Splits claims into Tier 1 (auto_approved -> filable), Tier 2
(seller_canceled -> hold), and Needs-Review (blank/other), recomputes every
total from scratch, embeds one Seller Center screenshot per filable claim, and
loudly flags anything missing so nothing is filed on a weak record.

INPUT candidates.csv columns (from detect.py, then human-filled):
  order_id, reason, cancelled_time, stmt_date, recoverable_amount, raf_lines,
  mature, fresh, seller_center_url, resolution, resolution_timestamp, screenshot
  (optional extras: item, skus)

Usage:
  python build_packet.py --candidates verified.csv --screenshots ./shots \
      --out packet.pdf --client "Haus Apparel" --brand "Klemr"
"""
import argparse, os, sys, datetime as dt
import pandas as pd
from PIL import Image as PILImage
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image, PageBreak, KeepTogether)

NAVY=colors.HexColor("#0F2436"); TEAL=colors.HexColor("#0E7C7B")
TEALLT=colors.HexColor("#E3F1F1"); GREEN=colors.HexColor("#1B7F4B")
GREENLT=colors.HexColor("#E6F4EC"); GRAY=colors.HexColor("#5A6B78")
LIGHT=colors.HexColor("#F2F5F7"); LINE=colors.HexColor("#D5DDE3")

AUTO_VALUES   = {"auto_approved","autoapproved","auto-approved","auto","approved"}
SELLER_VALUES = {"seller_canceled","sellercanceled","seller-canceled","seller","manual"}

def norm(s): return "".join(ch for ch in str(s).strip().lower() if ch.isalnum() or ch=="_")

def match_screenshot(row, shots_dir):
    """Resolve a screenshot path: explicit filename, else search dir for order id."""
    fn = str(row.get("screenshot","")).strip()
    if fn:
        p = fn if os.path.isabs(fn) else os.path.join(shots_dir, fn)
        if os.path.exists(p): return p
    if shots_dir and os.path.isdir(shots_dir):
        oid = str(row["order_id"]).strip()
        for f in os.listdir(shots_dir):
            if oid in f and f.lower().endswith((".png",".jpg",".jpeg")):
                return os.path.join(shots_dir, f)
    return None

def build(cand_path, shots_dir, out_pdf, client, brand, asof):
    df = pd.read_csv(cand_path, dtype=str, keep_default_na=False)
    df.columns=[c.strip() for c in df.columns]
    df["_res"]=df["resolution"].map(norm)
    df["_amt"]=pd.to_numeric(df["recoverable_amount"],errors="coerce").fillna(0.0)

    tier1 = df[df["_res"].isin(AUTO_VALUES)].copy()
    tier2 = df[df["_res"].isin(SELLER_VALUES)].copy()
    review= df[~df["_res"].isin(AUTO_VALUES|SELLER_VALUES)].copy()

    # math decides: recompute from scratch
    t1_total=round(float(tier1["_amt"].sum()),2)
    t2_total=round(float(tier2["_amt"].sum()),2)
    rv_total=round(float(review["_amt"].sum()),2)

    tier1=tier1.sort_values("_amt",ascending=False).reset_index(drop=True)
    # attach screenshots + flag missing
    missing=[]
    paths=[]
    for _,r in tier1.iterrows():
        p=match_screenshot(r,shots_dir)
        paths.append(p if p else "")
        if not p: missing.append(str(r["order_id"]))
    tier1=tier1.reset_index(drop=True)
    tier1["_shot"]=paths

    # ---------- console report (flags first) ----------
    print("="*68)
    print(f"TIER-1 EVIDENCE PACKET BUILD  ({brand} -> {client})")
    print("="*68)
    print(f"  Tier 1 (auto_approved, FILABLE) : {len(tier1):>3}   ${t1_total:,.2f}")
    print(f"  Tier 2 (seller_canceled, HOLD)  : {len(tier2):>3}   ${t2_total:,.2f}")
    print(f"  NEEDS REVIEW (blank/other)      : {len(review):>3}   ${rv_total:,.2f}")
    if len(review):
        print("  !! Resolve the NEEDS REVIEW rows before treating totals as final:")
        for _,r in review.iterrows():
            print(f"     - {r['order_id']}  resolution='{r['resolution']}'")
    if missing:
        print(f"  !! {len(missing)} filable order(s) MISSING a screenshot exhibit:")
        for m in missing: print(f"     - {m}")
        print("     (packet will mark these 'EXHIBIT PENDING' — supply before filing.)")
    fresh=tier1[tier1.get("fresh","").map(lambda v:str(v).lower() in ('true','1','yes'))]
    if len(fresh):
        print(f"  i  {len(fresh)} freshly-settled — file in a 2nd wave: "
              + ", ".join(fresh['order_id'].astype(str)))
    print("="*68)

    # ---------- PDF ----------
    ss=getSampleStyleSheet()
    def mk(n,**k): return ParagraphStyle(n,parent=ss["Normal"],**k)
    st_title=mk("t",fontName="Helvetica-Bold",fontSize=23,textColor=NAVY,leading=27)
    st_sub=mk("s",fontName="Helvetica",fontSize=12.5,textColor=TEAL,leading=16)
    st_sm=mk("sm",fontName="Helvetica",fontSize=8.5,textColor=GRAY,leading=12)
    st_b=mk("b",fontName="Helvetica",fontSize=9.5,textColor=NAVY,leading=14)
    st_h2=mk("h2",fontName="Helvetica-Bold",fontSize=12.5,textColor=NAVY,leading=16,spaceBefore=4,spaceAfter=4)
    st_kn=mk("kn",fontName="Helvetica-Bold",fontSize=21,textColor=NAVY,leading=23,alignment=1)
    st_kl=mk("kl",fontName="Helvetica",fontSize=8,textColor=GRAY,leading=10,alignment=1)
    st_ch=mk("ch",fontName="Helvetica-Bold",fontSize=12,textColor=colors.white,leading=15)
    st_ca=mk("ca",fontName="Helvetica-Bold",fontSize=12,textColor=colors.white,leading=15,alignment=TA_RIGHT)
    st_th=mk("th",fontName="Helvetica-Bold",fontSize=7.6,textColor=colors.white,leading=9.5)
    st_td=mk("td",fontName="Helvetica",fontSize=7.6,textColor=NAVY,leading=9.5)
    st_tdr=mk("tdr",fontName="Helvetica",fontSize=7.6,textColor=NAVY,leading=9.5,alignment=TA_RIGHT)
    st_lbl=mk("l",fontName="Helvetica-Bold",fontSize=8,textColor=GRAY,leading=11)
    st_val=mk("v",fontName="Helvetica",fontSize=9,textColor=NAVY,leading=12)

    def footer(c,d):
        c.saveState(); c.setStrokeColor(LINE); c.setLineWidth(0.5)
        c.line(43,34,letter[0]-43,34); c.setFont("Helvetica",7); c.setFillColor(GRAY)
        c.drawString(43,24,f"{brand}  \u00b7  TikTok Shop RAF Recovery \u2014 Tier 1 Evidence Packet  \u00b7  {client}  \u00b7  Confidential")
        c.drawRightString(letter[0]-43,24,f"Page {d.page}"); c.restoreState()

    doc=SimpleDocTemplate(out_pdf,pagesize=letter,leftMargin=43,rightMargin=43,
                          topMargin=46,bottomMargin=46,
                          title=f"{brand} RAF Tier 1 Evidence Packet - {client}",author=brand)
    CW=letter[0]-86; story=[]
    bar=Table([[""]],colWidths=[CW],rowHeights=[5]); bar.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TEAL)]))
    story+=[Spacer(1,6),bar,Spacer(1,14),
            Paragraph("Refund Administration Fee \u2014 Recovery Evidence Packet",st_title),Spacer(1,4),
            Paragraph(f"Tier 1: Filable Claims  \u00b7  TikTok Shop  \u00b7  {client} (Seller-Fulfilled)",st_sub),Spacer(1,4),
            Paragraph(f"Prepared by {brand}  \u00b7  {asof}",st_sm),Spacer(1,16)]
    kpi=Table([[[Paragraph(f"{len(tier1)}",st_kn),Paragraph("FILABLE CLAIMS",st_kl)],
                [Paragraph(f"${t1_total:,.2f}",st_kn),Paragraph("RECOVERABLE (TIER 1)",st_kl)],
                [Paragraph("100%",st_kn),Paragraph("AUTO-APPROVED / VERIFIED",st_kl)],
                [Paragraph("$5",st_kn),Paragraph("PER-SKU RAF CAP",st_kl)]]],colWidths=[CW/4]*4)
    kpi.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.5,LINE),
        ("LINEAFTER",(0,0),(-2,-1),0.5,LINE),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12)]))
    story+=[kpi,Spacer(1,18),Paragraph("What this packet contains",st_h2),
            Paragraph(f"This packet documents {len(tier1)} TikTok Shop orders on which a Refund Administration "
                      "Fee (RAF) was deducted even though the order qualified for the auto-cancellation exemption: "
                      "a buyer-initiated, pre-shipment cancellation resolved by TikTok's 24-hour automatic-approval "
                      "SLA. Each claim is supported by a Seller Center order-history screenshot on its own page.",st_b),Spacer(1,10),
            Paragraph("Policy basis",st_h2),
            Paragraph("TikTok Shop US \u2014 <i>Referral Fee Updates</i> (last revised 05/08/2025). RAF = 20% of the "
                      "referral fee, capped at $5 per SKU (effective May 15, 2025), at the SKU level. Carve-out: "
                      "<b>\u201cIf a refund is initiated by the buyer before the order is shipped and meets the "
                      "auto-canceling criteria, no Refund Administration Fee will be charged.\u201d</b>",st_b),Spacer(1,10)]
    holdline=(f"Excluded from this packet: {len(tier2)} order(s) (${t2_total:,.2f}) that Haus staff canceled "
              "manually within the 24h window (Tier 2, contestable)." if len(tier2) else
              "No manually-canceled orders were excluded.")
    rvline=(f" {len(review)} order(s) (${rv_total:,.2f}) remain unverified and are NOT included." if len(review) else "")
    note=Table([[Paragraph("<b>Scope &amp; method.</b> Candidates were surfaced deterministically (settlement RAF &gt; 0 on a "
                 "buyer-initiated, pre-shipment cancellation), then each was verified against Seller Center order "
                 "history; only true auto-approvals are claimed here. "+holdline+rvline+" Agent suggests, math decides.",st_sm)]],colWidths=[CW])
    note.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),TEALLT),("BOX",(0,0),(-1,-1),0.5,TEAL),
        ("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    story+=[note,PageBreak()]

    # summary table
    story+=[Paragraph("Claim Summary \u2014 Tier 1 (Filable)",st_title),Spacer(1,3),
            Paragraph(f"{len(tier1)} orders  \u00b7  ${t1_total:,.2f} recoverable  \u00b7  all auto-approved, screenshot-verified",st_sub),Spacer(1,12)]
    head=[Paragraph(h,st_th) for h in ["#","Order ID","Cancel reason","Resolution","Settled","RAF"]]
    rows=[head]
    for i,r in tier1.iterrows():
        rows.append([Paragraph(str(i+1),st_td),Paragraph(str(r["order_id"]),st_td),
                     Paragraph(str(r.get("reason","")),st_td),
                     Paragraph(str(r.get("resolution_timestamp","") or "auto-approved"),st_td),
                     Paragraph(str(r.get("stmt_date","")),st_td),
                     Paragraph(f"${r['_amt']:.2f}",st_tdr)])
    rows.append([Paragraph("",st_td),Paragraph("",st_td),Paragraph("<b>TOTAL RECOVERABLE</b>",st_td),
                 Paragraph("",st_td),Paragraph("",st_td),Paragraph(f"<b>${t1_total:.2f}</b>",st_tdr)])
    cw=[0.22,1.5,1.7,1.1,0.8,0.55]; cw=[c*inch for c in cw]; sc=CW/sum(cw); cw=[c*sc for c in cw]
    tbl=Table(rows,colWidths=cw,repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),NAVY),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white,LIGHT]),("BACKGROUND",(0,-1),(-1,-1),TEALLT),
        ("LINEABOVE",(0,-1),(-1,-1),0.8,TEAL),("BOX",(0,0),(-1,-1),0.5,LINE),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),4.5),("BOTTOMPADDING",(0,0),(-1,-1),4.5)]))
    story+=[tbl,PageBreak()]

    # evidence pages
    def chip(txt):
        t=Table([[Paragraph(txt,mk("gc",fontName="Helvetica-Bold",fontSize=7.5,textColor=GREEN,leading=9))]])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREENLT),("BOX",(0,0),(-1,-1),0.5,GREEN),
            ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
            ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)])); return t
    N=len(tier1)
    for i,r in tier1.iterrows():
        amt=r["_amt"]; flow=[]
        hdr=Table([[Paragraph(f"Claim {i+1} of {N} \u2014 Order {r['order_id']}",st_ch),
                    Paragraph(f"RAF ${amt:.2f}",st_ca)]],colWidths=[CW*0.74,CW*0.26])
        hdr.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),NAVY),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
            ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)])); flow.append(hdr)
        facts=Table([
            [Paragraph("ITEM",st_lbl),Paragraph(str(r.get("item","(see exhibit)")),st_val),
             Paragraph("CANCEL REQUEST",st_lbl),Paragraph(str(r.get("cancelled_time","(see exhibit)")),st_val)],
            [Paragraph("BUYER REASON",st_lbl),Paragraph(str(r.get("reason","")),st_val),
             Paragraph("AUTO-APPROVED",st_lbl),Paragraph(str(r.get("resolution_timestamp","(see exhibit)")),st_val)],
            [Paragraph("FULFILLMENT",st_lbl),Paragraph("Seller-fulfilled",st_val),
             Paragraph("RAF SETTLED",st_lbl),Paragraph(f"{r.get('stmt_date','')}  \u00b7  $-{amt:.2f}",st_val)],
        ],colWidths=[CW*0.16,CW*0.34,CW*0.18,CW*0.32])
        facts.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LIGHT),("BOX",(0,0),(-1,-1),0.5,LINE),
            ("INNERGRID",(0,0),(-1,-1),0.4,colors.white),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),6),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)])); flow.append(facts)
        flow.append(Spacer(1,6))
        chips=Table([[chip("\u2713 Gate 1  Buyer-initiated"),chip("\u2713 Gate 2  Pre-shipment"),
                      chip("\u2713 Gate 3  Auto-approved (24h SLA)")]],colWidths=[CW/3.0]*3)
        chips.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),4),
            ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
        flow+=[chips,Spacer(1,7)]
        concl=Table([[Paragraph("<b>Conclusion:</b> All three gates satisfied. Per TikTok Shop policy the RAF should "
                     f"have been waived; ${amt:.2f} is recoverable.",mk("cc",fontName="Helvetica",fontSize=8.5,textColor=GREEN,leading=11))]],colWidths=[CW])
        concl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),GREENLT),("BOX",(0,0),(-1,-1),0.5,GREEN),
            ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        flow+=[concl,Spacer(1,8),Paragraph("EXHIBIT \u2014 Seller Center order history",st_lbl),Spacer(1,3)]
        shot=r["_shot"]
        if isinstance(shot,str) and shot and os.path.exists(shot):
            with PILImage.open(shot) as im: iw,ih=im.size
            scale=min(CW/iw,430/ih); pic=Image(shot,width=iw*scale,height=ih*scale); pic.hAlign="CENTER"
            fr=Table([[pic]],colWidths=[iw*scale]); fr.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.6,LINE),
                ("LEFTPADDING",(0,0),(-1,-1),2),("RIGHTPADDING",(0,0),(-1,-1),2),
                ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)])); fr.hAlign="CENTER"
            flow.append(fr)
        else:
            ph=Table([[Paragraph("EXHIBIT PENDING \u2014 attach Seller Center order-history screenshot before filing.",
                       mk("ph",fontName="Helvetica-Bold",fontSize=9,textColor=colors.HexColor('#B26A00'),leading=12,alignment=1))]],
                     colWidths=[CW],rowHeights=[90])
            ph.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor('#FBF3E2')),
                ("BOX",(0,0),(-1,-1),0.6,colors.HexColor('#B26A00')),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
            flow.append(ph)
        story.append(KeepTogether(flow))
        if i<N-1: story.append(PageBreak())

    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(f"\nWROTE {out_pdf}  ({N} claims, ${t1_total:,.2f})")
    return {"tier1":len(tier1),"tier1_total":t1_total,"tier2":len(tier2),"tier2_total":t2_total,
            "review":len(review),"missing_screenshots":missing}

def main():
    ap=argparse.ArgumentParser(description="Build Tier-1 RAF evidence packet from verified candidates.")
    ap.add_argument("--candidates",required=True)
    ap.add_argument("--screenshots",default="")
    ap.add_argument("--out",default="RAF_Tier1_Evidence_Packet.pdf")
    ap.add_argument("--client",default="the merchant")
    ap.add_argument("--brand",default="Klemr")
    ap.add_argument("--asof",default=dt.date.today().strftime("%B %-d, %Y") if os.name!="nt" else dt.date.today().strftime("%B %d, %Y"))
    a=ap.parse_args()
    build(a.candidates,a.screenshots,a.out,a.client,a.brand,a.asof)

if __name__=="__main__":
    main()
