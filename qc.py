"""
qc.py
Back-calculates QC samples, computes accuracy and precision per level.
Applies ICH M10 acceptance rules.
Input : data/processed/<batch_id>_preprocessed.csv
        data/output/<batch_id>_calibration_summary.json
Output: data/output/<batch_id>_qc_results.csv
        data/output/<batch_id>_qc_summary.json
Run after calibration.py.
"""

import pandas as pd
import numpy as np
import os
import json
from datetime import datetime

ROOT        = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS = config["paths"]
QC    = config["qc"]
ACC   = QC["accuracy_pct"]
PREC  = QC["precision_cv_pct"]
LLOQ  = config["calibration"]["lloq_ngml"]

# --- Load data ---
proc_dir   = os.path.join(ROOT, PATHS["processed"])
out_dir    = os.path.join(ROOT, PATHS["output"])
proc_files = sorted([f for f in os.listdir(proc_dir) if f.endswith("_preprocessed.csv")])

if not proc_files:
    raise FileNotFoundError("No preprocessed CSV found. Run preprocessing.py first.")

df       = pd.read_csv(os.path.join(proc_dir, proc_files[-1]))
batch_id = df["batch_id"].iloc[0]

cal_path = os.path.join(out_dir, f"{batch_id}_calibration_summary.json")
if not os.path.exists(cal_path):
    raise FileNotFoundError("Calibration summary not found. Run calibration.py first.")

with open(cal_path) as f:
    cal = json.load(f)

if not cal["cal_accepted"]:
    raise RuntimeError("Calibration was not accepted. QC evaluation cannot proceed.")

slope     = cal["slope"]
intercept = cal["intercept"]

qc_df = df[
    (df["sample_type"] == "QC") &
    (~df["IS_flag"]) &
    (~df["RT_flag"])
].copy()

print(f"Batch ID            : {batch_id}")
print(f"Slope / Intercept   : {slope} / {intercept}")
print(f"QC injections loaded: {len(qc_df)}")

# --- Back-calculate QC samples ---
qc_results = []

for _, row in qc_df.iterrows():
    back_calc  = (row["area_ratio"] - intercept) / slope
    nominal    = row["nominal_conc_ngml"]
    bias_pct   = (back_calc - nominal) / nominal * 100
    is_lloq    = nominal == LLOQ
    threshold  = ACC["lloq"] if is_lloq else ACC["standard"]
    passed     = abs(bias_pct) <= threshold
    level_name = "_".join(row["sample_id"].split("_")[:-1])

    qc_results.append({
        "batch_id"      : batch_id,
        "sample_id"     : row["sample_id"],
        "qc_level"      : level_name,
        "nominal_conc"  : nominal,
        "area_ratio"    : round(row["area_ratio"], 6),
        "back_calc_conc": round(back_calc, 3),
        "bias_pct"      : round(bias_pct, 2),
        "threshold_pct" : threshold,
        "passed"        : passed,
        "is_lloq"       : is_lloq,
    })

qc_results_df = pd.DataFrame(qc_results)

print(f"\n=== QC Back-Calculation ===")
print(f"{'Sample':<18} {'Level':<12} {'Nominal':>8} {'Back-calc':>10} {'Bias%':>7} {'Pass':>6}")
print("-" * 68)
for _, row in qc_results_df.iterrows():
    print(f"{row['sample_id']:<18} {row['qc_level']:<12} "
          f"{row['nominal_conc']:>8.2f} {row['back_calc_conc']:>10.3f} "
          f"{row['bias_pct']:>7.2f} {'YES' if row['passed'] else 'NO':>6}")

# --- Precision per level ---
precision_results = []

for level, group in qc_results_df.groupby("qc_level"):
    nominal   = group["nominal_conc"].iloc[0]
    is_lloq   = nominal == LLOQ
    cv_limit  = PREC["lloq"] if is_lloq else PREC["standard"]
    mean_conc = group["back_calc_conc"].mean()
    sd_conc   = group["back_calc_conc"].std(ddof=1) if len(group) > 1 else 0.0
    cv_pct    = sd_conc / mean_conc * 100 if mean_conc > 0 else 0.0
    prec_pass = cv_pct <= cv_limit

    precision_results.append({
        "qc_level"   : level,
        "nominal"    : nominal,
        "n"          : len(group),
        "mean_conc"  : round(mean_conc, 3),
        "sd_conc"    : round(sd_conc, 3),
        "cv_pct"     : round(cv_pct, 2),
        "cv_limit"   : cv_limit,
        "prec_passed": prec_pass,
    })

prec_df = pd.DataFrame(precision_results)

print(f"\n=== Precision Summary ===")
print(f"{'Level':<12} {'Nominal':>8} {'Mean':>8} {'CV%':>7} {'Limit':>7} {'Pass':>6}")
print("-" * 52)
for _, row in prec_df.iterrows():
    print(f"{row['qc_level']:<12} {row['nominal']:>8.2f} {row['mean_conc']:>8.3f} "
          f"{row['cv_pct']:>7.2f} {row['cv_limit']:>7.1f} "
          f"{'YES' if row['prec_passed'] else 'NO':>6}")

# --- ICH M10 batch QC decision ---
level_decisions = []

for level, group in qc_results_df.groupby("qc_level"):
    n_pass     = group["passed"].sum()
    n_total    = len(group)
    acc_pass   = n_pass >= QC["min_qc_pass_per_level"]
    prec_row   = prec_df[prec_df["qc_level"] == level].iloc[0]
    prec_pass  = prec_row["prec_passed"]
    level_pass = acc_pass and prec_pass

    level_decisions.append({
        "qc_level"    : level,
        "nominal"     : group["nominal_conc"].iloc[0],
        "n_pass_acc"  : int(n_pass),
        "n_total"     : int(n_total),
        "acc_passed"  : bool(acc_pass),
        "cv_pct"      : float(prec_row["cv_pct"]),
        "prec_passed" : bool(prec_pass),
        "level_passed": bool(level_pass),
    })

level_dec_df    = pd.DataFrame(level_decisions)
n_levels_passed = level_dec_df["level_passed"].sum()
qc_batch_passed = n_levels_passed >= QC["min_qc_levels_pass"]

print(f"\n=== QC Batch Decision ===")
for _, row in level_dec_df.iterrows():
    print(f"  {row['qc_level']:<12}: Acc {row['n_pass_acc']}/{row['n_total']} "
          f"| CV% {row['cv_pct']:.2f} "
          f"| {'PASS' if row['level_passed'] else 'FAIL'}")

print(f"\n  Levels passed    : {n_levels_passed} of {len(level_dec_df)}")
print(f"  Batch QC         : {'PASSED' if qc_batch_passed else 'FAILED'}")

# --- Export ---
os.makedirs(out_dir, exist_ok=True)

qc_results_df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
csv_path = os.path.join(out_dir, f"{batch_id}_qc_results.csv")
qc_results_df.to_csv(csv_path, index=False)

qc_summary = {
    "batch_id"        : batch_id,
    "qc_batch_passed" : bool(qc_batch_passed),
    "n_levels_passed" : int(n_levels_passed),
    "n_levels_total"  : len(level_dec_df),
    "level_decisions" : level_decisions,
    "evaluated_at"    : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

json_path = os.path.join(out_dir, f"{batch_id}_qc_summary.json")
with open(json_path, "w") as f:
    json.dump(qc_summary, f, indent=2)

print(f"\nQC results  -> {csv_path}")
print(f"QC summary  -> {json_path}")
print("Next: decision.py")
