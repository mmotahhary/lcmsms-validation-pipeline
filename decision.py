"""
decision.py
Combines calibration and QC results into a batch verdict: PASS, FAIL, or REVIEW.
Back-calculates unknown sample concentrations.
Input : data/processed/<batch_id>_preprocessed.csv
        data/output/<batch_id>_calibration_summary.json
        data/output/<batch_id>_qc_summary.json
Output: data/output/<batch_id>_unknown_results.csv
        data/output/<batch_id>_batch_decision.json
Run after qc.py.
"""

import pandas as pd
import os
import json
from datetime import datetime

ROOT        = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS = config["paths"]
CAL   = config["calibration"]

# --- Load data ---
proc_dir   = os.path.join(ROOT, PATHS["processed"])
out_dir    = os.path.join(ROOT, PATHS["output"])
proc_files = sorted([f for f in os.listdir(proc_dir) if f.endswith("_preprocessed.csv")])

if not proc_files:
    raise FileNotFoundError("No preprocessed CSV found. Run preprocessing.py first.")

df       = pd.read_csv(os.path.join(proc_dir, proc_files[-1]))
batch_id = df["batch_id"].iloc[0]

cal_path = os.path.join(out_dir, f"{batch_id}_calibration_summary.json")
qc_path  = os.path.join(out_dir, f"{batch_id}_qc_summary.json")

if not os.path.exists(cal_path):
    raise FileNotFoundError("Calibration summary not found. Run calibration.py first.")
if not os.path.exists(qc_path):
    raise FileNotFoundError("QC summary not found. Run qc.py first.")

with open(cal_path) as f:
    cal = json.load(f)
with open(qc_path) as f:
    qc = json.load(f)

slope     = cal["slope"]
intercept = cal["intercept"]
lloq      = CAL["lloq_ngml"]
uloq      = CAL["uloq_ngml"]

print(f"Batch ID    : {batch_id}")
print(f"Calibration : {'ACCEPTED' if cal['cal_accepted'] else 'REJECTED'}")
print(f"QC batch    : {'PASSED' if qc['qc_batch_passed'] else 'FAILED'}")

# --- Batch verdict ---
n_levels_passed = qc["n_levels_passed"]
n_levels_total  = qc["n_levels_total"]
min_pass        = config["qc"]["min_qc_levels_pass"]

if not cal["cal_accepted"]:
    verdict = "FAIL"
    reason  = "Calibration rejected"
elif qc["qc_batch_passed"]:
    verdict = "PASS"
    reason  = f"Calibration accepted. QC passed ({n_levels_passed}/{n_levels_total} levels)"
elif n_levels_passed == min_pass - 1:
    verdict = "REVIEW"
    reason  = (f"Calibration accepted. QC borderline — "
               f"{n_levels_passed}/{n_levels_total} levels passed "
               f"(minimum {min_pass}). Reinjection recommended.")
else:
    verdict = "FAIL"
    reason  = (f"QC failed — {n_levels_passed}/{n_levels_total} levels passed "
               f"(minimum {min_pass})")

print(f"\n=== BATCH VERDICT ===")
print(f"  Verdict : {verdict}")
print(f"  Reason  : {reason}")

# --- Back-calculate unknowns ---
unknowns_df = df[
    (df["sample_type"] == "Unknown") &
    (~df["IS_flag"]) &
    (~df["RT_flag"])
].copy()

unk_results = []

for _, row in unknowns_df.iterrows():
    back_calc = (row["area_ratio"] - intercept) / slope

    if verdict == "FAIL":
        status, reportable = "NOT_REPORTABLE", False
    elif back_calc < lloq:
        status, reportable = "BELOW_LLOQ", False
    elif back_calc > uloq:
        status, reportable = "ABOVE_ULOQ", False
    else:
        status, reportable = "REPORTABLE", True

    unk_results.append({
        "batch_id"       : batch_id,
        "sample_id"      : row["sample_id"],
        "area_ratio"     : round(row["area_ratio"], 6),
        "calculated_conc": round(back_calc, 3),
        "lloq_ngml"      : lloq,
        "uloq_ngml"      : uloq,
        "status"         : status,
        "reportable"     : reportable,
        "IS_flag"        : row["IS_flag"],
        "RT_flag"        : row["RT_flag"],
        "batch_verdict"  : verdict,
        "quantified_at"  : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

unk_df = pd.DataFrame(unk_results)

print(f"\n=== Unknown Sample Results ===")
print(f"{'Sample':<12} {'Conc (ng/mL)':>14} {'Status':<16} {'Reportable':>10}")
print("-" * 58)
for _, row in unk_df.iterrows():
    print(f"{row['sample_id']:<12} {row['calculated_conc']:>14.3f} "
          f"{row['status']:<16} {'YES' if row['reportable'] else 'NO':>10}")

print(f"\n  Reportable     : {unk_df['reportable'].sum()}")
print(f"  Not reportable : {(~unk_df['reportable']).sum()}")

# --- Traceability ---
print(f"\n=== Traceability ===")
for _, row in unk_df[unk_df["reportable"]].iterrows():
    raw_row = df[df["sample_id"] == row["sample_id"]].iloc[0]
    print(f"  {row['sample_id']}: "
          f"PeakArea={raw_row['measured_peak_area']:.0f} / "
          f"IS={raw_row['IS_peak_area']:.0f} "
          f"-> Ratio={raw_row['area_ratio']:.4f} "
          f"-> {row['calculated_conc']:.3f} ng/mL [{row['status']}]")

# --- Export ---
os.makedirs(out_dir, exist_ok=True)

unk_csv_path = os.path.join(out_dir, f"{batch_id}_unknown_results.csv")
unk_df.to_csv(unk_csv_path, index=False)

batch_decision = {
    "batch_id"       : batch_id,
    "verdict"        : verdict,
    "reason"         : reason,
    "cal_accepted"   : cal["cal_accepted"],
    "qc_passed"      : qc["qc_batch_passed"],
    "n_unknowns"     : len(unk_df),
    "n_reportable"   : int(unk_df["reportable"].sum()),
    "n_below_lloq"   : int((unk_df["status"] == "BELOW_LLOQ").sum()),
    "n_above_uloq"   : int((unk_df["status"] == "ABOVE_ULOQ").sum()),
    "unknown_results": unk_csv_path,
    "decided_at"     : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

decision_path = os.path.join(out_dir, f"{batch_id}_batch_decision.json")
with open(decision_path, "w") as f:
    json.dump(batch_decision, f, indent=2)

print(f"\nUnknown results  -> {unk_csv_path}")
print(f"Batch decision   -> {decision_path}")
print(f"\nVerdict: {verdict}")
print("Next: audit.py")
