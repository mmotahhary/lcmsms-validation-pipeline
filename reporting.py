"""
reporting.py
Generates a regulatory-style PDF batch record using ReportLab.
Input : data/output/<batch_id>_*.json and *.csv
        logs/<batch_id>_audit_trail.csv
Output: reports/<batch_id>_batch_report.pdf
Run after audit.py.
"""

import pandas as pd
import os
import json
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable
)

ROOT        = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS    = config["paths"]
ASSAY    = config["assay"]
OPERATOR = config["project"]["author"]

# --- Load pipeline outputs ---
out_dir  = os.path.join(ROOT, PATHS["output"])
logs_dir = os.path.join(ROOT, PATHS["logs"])

decision_files = sorted([f for f in os.listdir(out_dir) if f.endswith("_batch_decision.json")])
if not decision_files:
    raise FileNotFoundError("No batch_decision.json found. Run decision.py first.")

batch_id = decision_files[-1].replace("_batch_decision.json", "")

def load_json(fname):
    path = os.path.join(out_dir, fname)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

cal      = load_json(f"{batch_id}_calibration_summary.json")
qc       = load_json(f"{batch_id}_qc_summary.json")
decision = load_json(f"{batch_id}_batch_decision.json")

qc_results_df  = pd.read_csv(os.path.join(out_dir, f"{batch_id}_qc_results.csv"))
unk_results_df = pd.read_csv(os.path.join(out_dir, f"{batch_id}_unknown_results.csv"))
audit_df       = pd.read_csv(os.path.join(logs_dir, f"{batch_id}_audit_trail.csv"))

print(f"Batch ID   : {batch_id}")
print(f"Verdict    : {decision['verdict']}")
print(f"Unknowns   : {len(unk_results_df)}")
print(f"Audit rows : {len(audit_df)}")

# --- Styles ---
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "title", parent=styles["Normal"],
    fontSize=16, fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1F3864"), spaceAfter=4
)
section_style = ParagraphStyle(
    "section", parent=styles["Normal"],
    fontSize=10, fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1F3864"),
    spaceBefore=12, spaceAfter=4
)
normal_style = ParagraphStyle(
    "normal", parent=styles["Normal"],
    fontSize=8.5, fontName="Helvetica", leading=13
)
small_style = ParagraphStyle(
    "small", parent=styles["Normal"],
    fontSize=7.5, fontName="Helvetica",
    textColor=colors.HexColor("#555555")
)

VERDICT_COLORS = {
    "PASS"  : colors.HexColor("#1A7340"),
    "FAIL"  : colors.HexColor("#C0392B"),
    "REVIEW": colors.HexColor("#D68910"),
}
HDR_COLOR  = colors.HexColor("#1F3864")
ROW_COLOR1 = colors.white
ROW_COLOR2 = colors.HexColor("#F2F4F8")

def base_table_style():
    return TableStyle([
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("BACKGROUND",    (0, 0), (-1, 0),  HDR_COLOR),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [ROW_COLOR1, ROW_COLOR2]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
    ])

# --- Build story ---
story = []

story.append(Paragraph("Bioanalytical Batch Report", title_style))
story.append(Paragraph(
    f"{ASSAY['analyte']} in {ASSAY['matrix']} — LC-MS/MS (MRM)",
    normal_style
))
story.append(HRFlowable(width="100%", thickness=1.5, color=HDR_COLOR, spaceAfter=8))

meta = [
    ["Batch ID",  batch_id,                       "Run Date",    datetime.now().strftime("%Y-%m-%d %H:%M")],
    ["Operator",  OPERATOR,                        "Matrix",      ASSAY["matrix"]],
    ["Analyte",   ASSAY["analyte"],                "IS",          ASSAY["internal_standard"]],
    ["Column",    ASSAY["column"],                 "Ionization",  ASSAY["ionization"]],
    ["Cal range", f"{config['calibration']['lloq_ngml']}–"
                  f"{config['calibration']['uloq_ngml']} ng/mL",
                  "Quantitation", ASSAY["quantitation"]],
]
meta_table = Table(meta, colWidths=[1.1*inch, 2.4*inch, 1.1*inch, 2.4*inch])
meta_ts    = base_table_style()
meta_ts.add("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold")
meta_ts.add("FONTNAME",  (2, 0), (2, -1), "Helvetica-Bold")
meta_ts.add("TEXTCOLOR", (0, 0), (0, -1), HDR_COLOR)
meta_ts.add("TEXTCOLOR", (2, 0), (2, -1), HDR_COLOR)
meta_ts.add("BACKGROUND",(0, 0), (-1, -1), ROW_COLOR2)
meta_table.setStyle(meta_ts)
story.append(meta_table)
story.append(Spacer(1, 8))

story.append(Paragraph("Calibration Curve", section_style))
cal_data = [
    ["Model", "Slope", "Intercept", "R²", "Passed", "Accepted"],
    [cal["model"], f"{cal['slope']:.6f}", f"{cal['intercept']:.6f}",
     f"{cal['r_squared']:.6f}", f"{cal['n_passed']}/{cal['n_total']}",
     "YES" if cal["cal_accepted"] else "NO"]
]
cal_table = Table(cal_data, colWidths=[1.0*inch, 1.2*inch, 1.2*inch, 1.0*inch, 0.9*inch, 0.9*inch])
cal_ts    = base_table_style()
cal_ts.add("TEXTCOLOR", (5, 1), (5, 1),
           VERDICT_COLORS["PASS"] if cal["cal_accepted"] else VERDICT_COLORS["FAIL"])
cal_ts.add("FONTNAME", (5, 1), (5, 1), "Helvetica-Bold")
cal_table.setStyle(cal_ts)
story.append(cal_table)
story.append(Spacer(1, 8))

story.append(Paragraph("QC Summary", section_style))
qc_hdr  = [["QC Level", "Nominal (ng/mL)", "Mean (ng/mL)", "Bias%", "CV%", "Acc", "Prec", "Level"]]
qc_rows = []
for level_info in qc["level_decisions"]:
    level  = level_info["qc_level"]
    group  = qc_results_df[qc_results_df["qc_level"] == level]
    mean_c = group["back_calc_conc"].mean()
    bias   = group["bias_pct"].mean()
    cv     = (group["back_calc_conc"].std(ddof=1) / mean_c * 100) if mean_c > 0 else 0
    qc_rows.append([
        level, f"{level_info['nominal']:.2f}", f"{mean_c:.3f}",
        f"{bias:.2f}", f"{cv:.2f}",
        "YES" if level_info["acc_passed"]  else "NO",
        "YES" if level_info["prec_passed"] else "NO",
        "PASS" if level_info["level_passed"] else "FAIL",
    ])

qc_table = Table(qc_hdr + qc_rows,
                 colWidths=[1.0*inch, 1.1*inch, 1.1*inch, 0.7*inch,
                            0.6*inch, 0.65*inch, 0.65*inch, 0.65*inch])
qc_ts = base_table_style()
for i, row in enumerate(qc_rows, start=1):
    c = VERDICT_COLORS["PASS"] if row[7] == "PASS" else VERDICT_COLORS["FAIL"]
    qc_ts.add("TEXTCOLOR", (7, i), (7, i), c)
    qc_ts.add("FONTNAME",  (7, i), (7, i), "Helvetica-Bold")
qc_table.setStyle(qc_ts)
story.append(qc_table)
story.append(Spacer(1, 8))

story.append(Paragraph("Sample Results", section_style))
unk_hdr  = [["Sample ID", "Conc (ng/mL)", "Status", "Reportable"]]
unk_rows = [[row["sample_id"], f"{row['calculated_conc']:.3f}",
             row["status"], "YES" if row["reportable"] else "NO"]
            for _, row in unk_results_df.iterrows()]
unk_table = Table(unk_hdr + unk_rows,
                  colWidths=[1.5*inch, 1.3*inch, 1.8*inch, 1.0*inch])
unk_ts = base_table_style()
for i, row in enumerate(unk_rows, start=1):
    c = VERDICT_COLORS["PASS"] if row[3] == "YES" else VERDICT_COLORS["FAIL"]
    unk_ts.add("TEXTCOLOR", (3, i), (3, i), c)
    unk_ts.add("FONTNAME",  (3, i), (3, i), "Helvetica-Bold")
unk_table.setStyle(unk_ts)
story.append(unk_table)
story.append(Spacer(1, 8))

verdict       = decision["verdict"]
verdict_style = ParagraphStyle(
    "verdict", parent=styles["Normal"],
    fontSize=12, fontName="Helvetica-Bold",
    textColor=VERDICT_COLORS.get(verdict, colors.black)
)
story.append(Paragraph("Batch Verdict", section_style))
story.append(Paragraph(f"Verdict: {verdict}", verdict_style))
story.append(Paragraph(decision["reason"], normal_style))
story.append(Paragraph(
    f"Reportable samples: {decision['n_reportable']} of {decision['n_unknowns']}",
    normal_style
))
story.append(Spacer(1, 8))

story.append(Paragraph("Audit Trail", section_style))
audit_hdr  = [["Timestamp", "Module", "Action", "Status"]]
audit_rows = [[row["timestamp"], row["module"], row["action"], row["status"]]
              for _, row in audit_df.iterrows()]
audit_table = Table(audit_hdr + audit_rows,
                    colWidths=[1.6*inch, 1.0*inch, 2.5*inch, 0.7*inch])
audit_ts = base_table_style()
for i, row in enumerate(audit_rows, start=1):
    if row[3] == "FAIL":
        audit_ts.add("TEXTCOLOR", (3, i), (3, i), VERDICT_COLORS["FAIL"])
    elif row[3] == "WARNING":
        audit_ts.add("TEXTCOLOR", (3, i), (3, i), VERDICT_COLORS["REVIEW"])
audit_table.setStyle(audit_ts)
story.append(audit_table)

story.append(Spacer(1, 12))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC")))
story.append(Paragraph(
    f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  "
    f"Operator: {OPERATOR}  |  Batch: {batch_id}  |  "
    f"Analyte: {ASSAY['analyte']}  |  "
    f"Model: {cal['model']}  |  R²={cal['r_squared']:.4f}",
    small_style
))

# --- Build PDF ---
reports_dir = os.path.join(ROOT, PATHS["reports"])
os.makedirs(reports_dir, exist_ok=True)

pdf_path = os.path.join(reports_dir, f"{batch_id}_batch_report.pdf")
doc = SimpleDocTemplate(
    pdf_path,
    pagesize=letter,
    leftMargin=0.75*inch, rightMargin=0.75*inch,
    topMargin=0.75*inch,  bottomMargin=0.75*inch,
)
doc.build(story)

print(f"\nPDF report saved : {pdf_path}")
print(f"Verdict          : {verdict}")
print(f"Reportable       : {decision['n_reportable']}/{decision['n_unknowns']} samples")
print("\nPipeline complete.")
