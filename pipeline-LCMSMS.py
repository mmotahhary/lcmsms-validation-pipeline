"""
generate_batch.py
Generates a realistic synthetic LC-MS/MS batch dataset for 25-OH Vitamin D3.
Simulates peak area variability, IS fluctuation, RT drift, and outliers.
Output: data/raw/<batch_id>_raw.csv  (immutable)
Run this first before any other script.
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
ASSAY = config["assay"]
CAL   = config["calibration"]
QC    = config["qc"]
SIM   = config["simulation"]
BATCH = config["batch"]

np.random.seed(SIM["random_seed"])

RESPONSE_FACTOR  = 12000.0
IS_BASELINE_AREA = 850000.0

def simulate_peak_area(conc_ngml, noise_cv=SIM["peak_area_noise_cv"], is_outlier=False):
    if conc_ngml <= 0:
        return 0.0
    base_area = conc_ngml * RESPONSE_FACTOR
    noise     = np.random.normal(1.0, noise_cv)
    area      = base_area * noise
    if is_outlier:
        area *= np.random.choice([0.4, 2.5])
    return max(round(area, 1), 0.0)

def simulate_is_area(fluctuation_cv=SIM["is_fluctuation_cv"]):
    noise = np.random.normal(1.0, fluctuation_cv)
    return max(round(IS_BASELINE_AREA * noise, 1), 1.0)

def simulate_rt(base_rt=ASSAY["retention_time_min"], drift_sd=SIM["rt_drift_sd"]):
    return round(base_rt + np.random.normal(0, drift_sd), 3)

batch_id  = f"{BATCH['id_prefix']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
records   = []
run_order = 1

def add_injection(sample_id, sample_type, nominal_conc):
    global run_order
    is_outlier  = np.random.random() < SIM["outlier_probability"]
    peak_area   = simulate_peak_area(nominal_conc, is_outlier=is_outlier)
    is_area     = simulate_is_area()
    area_ratio  = round(peak_area / is_area, 6) if is_area > 0 else 0.0
    rt          = simulate_rt()

    records.append({
        "batch_id"          : batch_id,
        "sample_id"         : sample_id,
        "sample_type"       : sample_type,
        "analyte"           : ASSAY["analyte"],
        "internal_standard" : ASSAY["internal_standard"],
        "nominal_conc_ngml" : nominal_conc,
        "measured_peak_area": peak_area,
        "IS_peak_area"      : is_area,
        "area_ratio"        : area_ratio,
        "retention_time"    : rt,
        "run_order"         : run_order,
        "is_outlier_flag"   : is_outlier,
        "generated_at"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    run_order += 1

# Blank and double blank
add_injection("BLANK_01",  "Blank",        0.0)
add_injection("DBLANK_01", "Double_Blank", 0.0)

# Calibrators
for i, conc in enumerate(CAL["levels_ngml"], start=1):
    add_injection(f"CAL_{i:02d}", "Calibrator", conc)

# QC replicates
for rep in range(1, QC["replicates_per_level"] + 1):
    for level_name, conc in QC["levels"].items():
        add_injection(f"{level_name}_R{rep}", "QC", conc)

# Unknowns
unknown_concs = np.random.uniform(8, 65, SIM["n_unknowns"])
for i, conc in enumerate(unknown_concs, start=1):
    add_injection(f"UNK_{i:02d}", "Unknown", round(conc, 2))

# Bracket calibrators
add_injection("CAL_01_END", "Calibrator", CAL["levels_ngml"][0])
add_injection("CAL_07_END", "Calibrator", CAL["levels_ngml"][-1])

df = pd.DataFrame(records)

# Ensure clean column names and numeric types
df.columns               = df.columns.str.strip()
df["IS_peak_area"]       = pd.to_numeric(df["IS_peak_area"],        errors="coerce")
df["measured_peak_area"] = pd.to_numeric(df["measured_peak_area"],  errors="coerce")
df["area_ratio"]         = (df["measured_peak_area"] / df["IS_peak_area"]).round(6)

print(f"Batch ID         : {batch_id}")
print(f"Total injections : {len(df)}")
print(f"\nInjection breakdown:")
for stype, group in df.groupby("sample_type"):
    print(f"  {stype:<15}: {len(group)}")
print(f"\nOutliers flagged : {df['is_outlier_flag'].sum()}")
print(f"RT range         : {df['retention_time'].min():.3f} — {df['retention_time'].max():.3f} min")

raw_dir  = os.path.join(ROOT, PATHS["raw"])
os.makedirs(raw_dir, exist_ok=True)

out_path = os.path.join(raw_dir, f"{batch_id}_raw.csv")
df.to_csv(out_path, index=False)

print(f"\nRaw dataset saved : {out_path}")
print("Do not modify this file after saving.")
print("Next: preprocessing.py")
---
"""
preprocessing.py
IS normalization, area ratio verification, IS and RT flag checks.
Input : data/raw/<batch_id>_raw.csv
Output: data/processed/<batch_id>_preprocessed.csv
Run after generate_batch.py.
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

PATHS     = config["paths"]
ASSAY     = config["assay"]
IS_CONFIG = config["is_control"]

# --- Load latest raw file ---
raw_dir   = os.path.join(ROOT, PATHS["raw"])
raw_files = sorted([f for f in os.listdir(raw_dir) if f.endswith("_raw.csv")])

if not raw_files:
    raise FileNotFoundError("No raw CSV found. Run generate_batch.py first.")

raw_path = os.path.join(raw_dir, raw_files[-1])
df       = pd.read_csv(raw_path)

# Clean column names and ensure numeric types
df.columns               = df.columns.str.strip()
df["IS_peak_area"]       = pd.to_numeric(df["IS_peak_area"],        errors="coerce")
df["measured_peak_area"] = pd.to_numeric(df["measured_peak_area"],  errors="coerce")
df["area_ratio"]         = pd.to_numeric(df["area_ratio"],          errors="coerce")

batch_id = df["batch_id"].iloc[0]

print(f"Batch ID        : {batch_id}")
print(f"Raw file        : {raw_files[-1]}")
print(f"Rows loaded     : {len(df)}")

# --- Recalculate and verify area ratios ---
df["area_ratio_recalc"] = (df["measured_peak_area"] / df["IS_peak_area"]).round(6)

ratio_diff    = (df["area_ratio_recalc"] - df["area_ratio"]).abs()
discrepancies = df[ratio_diff > 0.0001]

if len(discrepancies) > 0:
    print(f"\nWARNING: {len(discrepancies)} area ratio discrepancies detected")
    print(discrepancies[["sample_id", "area_ratio", "area_ratio_recalc"]])
else:
    print(f"Area ratio verification : PASSED ({len(df)} rows)")

df["area_ratio"] = df["area_ratio_recalc"]
df = df.drop(columns=["area_ratio_recalc"])

# --- IS variability check ---
is_mean = df["IS_peak_area"].mean()
is_sd   = df["IS_peak_area"].std()
is_cv   = is_sd / is_mean * 100

df["IS_flag"] = (
    (df["IS_peak_area"] < is_mean - 2 * is_sd) |
    (df["IS_peak_area"] > is_mean + 2 * is_sd)
)

print(f"\nIS batch mean   : {is_mean:,.1f}")
print(f"IS batch CV%    : {is_cv:.2f}%")
print(f"IS flagged      : {df['IS_flag'].sum()} injections")

if df["IS_flag"].sum() > 0:
    flagged = df[df["IS_flag"]][["sample_id", "sample_type", "IS_peak_area", "run_order"]]
    print(flagged.to_string(index=False))

# --- RT drift check ---
expected_rt = ASSAY["retention_time_min"]
rt_window   = ASSAY["rt_drift_window"]

df["RT_flag"] = (
    (df["retention_time"] < expected_rt - rt_window) |
    (df["retention_time"] > expected_rt + rt_window)
)

print(f"\nExpected RT     : {expected_rt} min (±{rt_window} min)")
print(f"Observed RT     : {df['retention_time'].min():.3f} — {df['retention_time'].max():.3f} min")
print(f"RT flagged      : {df['RT_flag'].sum()} injections")

# --- Add metadata ---
df["preprocessed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
df["IS_mean_batch"]   = round(is_mean, 1)
df["IS_cv_batch_pct"] = round(is_cv, 2)

print(f"\n=== Preprocessing Summary ===")
print(f"  Total injections : {len(df)}")
print(f"  IS flagged       : {df['IS_flag'].sum()}")
print(f"  RT flagged       : {df['RT_flag'].sum()}")
print(f"  Clean injections : {(~df['IS_flag'] & ~df['RT_flag']).sum()}")

# --- Export ---
proc_dir = os.path.join(ROOT, PATHS["processed"])
os.makedirs(proc_dir, exist_ok=True)

out_path = os.path.join(proc_dir, f"{batch_id}_preprocessed.csv")
df.to_csv(out_path, index=False)

print(f"\nPreprocessed CSV : {out_path}")
print("Next: calibration.py")
---
"""
calibration.py
Weighted linear regression (1/x or 1/x²), back-calculation, acceptance per ICH M10.
Input : data/processed/<batch_id>_preprocessed.csv
Output: data/output/<batch_id>_calibration_results.csv
        data/output/<batch_id>_calibration_summary.json
Run after preprocessing.py.
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
CAL   = config["calibration"]
ACC   = config["qc"]["accuracy_pct"]

# --- Load preprocessed data ---
proc_dir   = os.path.join(ROOT, PATHS["processed"])
proc_files = sorted([f for f in os.listdir(proc_dir) if f.endswith("_preprocessed.csv")])

if not proc_files:
    raise FileNotFoundError("No preprocessed CSV found. Run preprocessing.py first.")

proc_path = os.path.join(proc_dir, proc_files[-1])
df        = pd.read_csv(proc_path)
batch_id  = df["batch_id"].iloc[0]

cals_df = df[
    (df["sample_type"] == "Calibrator") &
    (~df["IS_flag"]) &
    (~df["RT_flag"])
].copy()

print(f"Batch ID             : {batch_id}")
print(f"Calibrators loaded   : {len(cals_df)}")
print(f"Flagged (excluded)   : {len(df[df['sample_type'] == 'Calibrator']) - len(cals_df)}")

# --- Weighted linear regression ---
def weighted_linear_regression(x, y, model="1/x2"):
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)

    if model == "1/x2":
        weights = 1.0 / (x ** 2)
    elif model == "1/x":
        weights = 1.0 / x
    else:
        weights = np.ones_like(x)

    W         = np.diag(weights)
    X_mat     = np.column_stack([x, np.ones_like(x)])
    XtWX      = X_mat.T @ W @ X_mat
    XtWy      = X_mat.T @ W @ y
    coeffs    = np.linalg.solve(XtWX, XtWy)
    slope, intercept = coeffs[0], coeffs[1]

    y_pred  = slope * x + intercept
    y_wmean = np.sum(weights * y) / np.sum(weights)
    ss_res  = np.sum(weights * (y - y_pred) ** 2)
    ss_tot  = np.sum(weights * (y - y_wmean) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return slope, intercept, r_squared

x_data = cals_df["nominal_conc_ngml"].values
y_data = cals_df["area_ratio"].values
model  = CAL["model"]

slope, intercept, r_squared = weighted_linear_regression(x_data, y_data, model)

print(f"\n=== Calibration Curve ===")
print(f"  Model      : Weighted linear ({model})")
print(f"  Slope      : {slope:.6f}")
print(f"  Intercept  : {intercept:.6f}")
print(f"  R²         : {r_squared:.6f}")
print(f"  R² status  : {'PASSED' if r_squared >= CAL['r2_threshold'] else 'FAILED'}")

# --- Back-calculate calibrators ---
lloq    = CAL["lloq_ngml"]
results = []

for _, row in cals_df.iterrows():
    back_calc = (row["area_ratio"] - intercept) / slope
    nominal   = row["nominal_conc_ngml"]
    bias_pct  = (back_calc - nominal) / nominal * 100
    threshold = ACC["lloq"] if nominal == lloq else ACC["standard"]
    passed    = abs(bias_pct) <= threshold

    results.append({
        "sample_id"      : row["sample_id"],
        "nominal_conc"   : nominal,
        "area_ratio"     : round(row["area_ratio"], 6),
        "back_calc_conc" : round(back_calc, 3),
        "bias_pct"       : round(bias_pct, 2),
        "threshold_pct"  : threshold,
        "passed"         : passed,
        "is_lloq"        : nominal == lloq,
    })

cal_results_df = pd.DataFrame(results)

print(f"\n=== Back-Calculation Results ===")
print(f"{'Sample':<15} {'Nominal':>10} {'Back-calc':>10} {'Bias%':>8} {'Pass':>6}")
print("-" * 55)
for _, row in cal_results_df.iterrows():
    print(f"{row['sample_id']:<15} {row['nominal_conc']:>10.3f} "
          f"{row['back_calc_conc']:>10.3f} {row['bias_pct']:>8.2f} "
          f"{'YES' if row['passed'] else 'NO':>6}")

# --- Acceptance decision ---
n_passed    = cal_results_df["passed"].sum()
n_total     = len(cal_results_df)
lloq_passed = cal_results_df[cal_results_df["is_lloq"]]["passed"].all()
cal_accepted = (n_passed >= CAL["min_levels_pass"]) and lloq_passed

print(f"\n=== Calibration Acceptance ===")
print(f"  Passed           : {n_passed} / {n_total}")
print(f"  Minimum required : {CAL['min_levels_pass']}")
print(f"  LLOQ passed      : {lloq_passed}")
print(f"  R² passed        : {r_squared >= CAL['r2_threshold']}")
print(f"  Decision         : {'ACCEPTED' if cal_accepted else 'REJECTED — pipeline halted'}")

if not cal_accepted:
    raise RuntimeError(
        f"Calibration REJECTED — {n_passed}/{n_total} calibrators passed "
        f"(minimum {CAL['min_levels_pass']} required). Pipeline halted."
    )

# --- Export ---
out_dir = os.path.join(ROOT, PATHS["output"])
os.makedirs(out_dir, exist_ok=True)

cal_results_df["batch_id"]     = batch_id
cal_results_df["model"]        = model
cal_results_df["slope"]        = round(slope, 6)
cal_results_df["intercept"]    = round(intercept, 6)
cal_results_df["r_squared"]    = round(r_squared, 6)
cal_results_df["cal_accepted"] = cal_accepted
cal_results_df["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

csv_path = os.path.join(out_dir, f"{batch_id}_calibration_results.csv")
cal_results_df.to_csv(csv_path, index=False)

summary = {
    "batch_id"    : batch_id,
    "model"       : model,
    "slope"       : round(slope, 6),
    "intercept"   : round(intercept, 6),
    "r_squared"   : round(r_squared, 6),
    "n_passed"    : int(n_passed),
    "n_total"     : int(n_total),
    "lloq_passed" : bool(lloq_passed),
    "cal_accepted": bool(cal_accepted),
    "fitted_at"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
}

json_path = os.path.join(out_dir, f"{batch_id}_calibration_summary.json")
with open(json_path, "w") as f:
    json.dump(summary, f, indent=2)

print(f"\nCalibration results -> {csv_path}")
print(f"Calibration summary -> {json_path}")
print("Next: qc.py")
--
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
---
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
---
"""
audit.py
Reconstructs the full ALCOA+ audit trail from pipeline output files.
Verifies raw file integrity via SHA-256 checksum.
Input : data/output/<batch_id>_*.json
        data/raw/<batch_id>_raw.csv
Output: logs/<batch_id>_audit_trail.csv
Run after decision.py.
"""

import pandas as pd
import os
import json
import hashlib
from datetime import datetime

ROOT        = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS    = config["paths"]
OPERATOR = config["project"]["author"]

logs_dir = os.path.join(ROOT, PATHS["logs"])
out_dir  = os.path.join(ROOT, PATHS["output"])
os.makedirs(logs_dir, exist_ok=True)

# --- Find latest batch ---
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

manifest = load_json(f"{batch_id}_ingestion_manifest.json")
cal      = load_json(f"{batch_id}_calibration_summary.json")
qc       = load_json(f"{batch_id}_qc_summary.json")
decision = load_json(f"{batch_id}_batch_decision.json")

print(f"Batch ID : {batch_id}")
print(f"Operator : {OPERATOR}")

# --- Audit entry builder ---
audit_entries = []

def append_entry(module, action, detail, status="OK"):
    audit_entries.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "batch_id" : batch_id,
        "module"   : module,
        "action"   : action,
        "detail"   : str(detail),
        "operator" : OPERATOR,
        "status"   : status,
    })

# --- Reconstruct trail from pipeline outputs ---
if manifest:
    append_entry("ingestion", "FILE_LOADED",
        f"File: {os.path.basename(manifest['raw_file'])} | "
        f"Rows: {manifest['rows_loaded']} | "
        f"SHA-256: {manifest['checksum_sha256'][:16]}...")

    append_entry("ingestion", "SCHEMA_VALIDATED",
        f"Valid: {manifest['schema_valid']}")

    append_entry("ingestion", "IS_VARIABILITY_CHECK",
        f"IS CV%: {manifest['is_cv_pct']}%",
        status=manifest.get("is_status", "OK"))

proc_dir   = os.path.join(ROOT, PATHS["processed"])
proc_files = sorted([f for f in os.listdir(proc_dir) if f.endswith("_preprocessed.csv")])
if proc_files:
    append_entry("preprocessing", "PREPROCESSING_COMPLETE",
        f"Output: {proc_files[-1]}")

if cal:
    append_entry("calibration", "CURVE_FITTED",
        f"Model: {cal['model']} | Slope: {cal['slope']} | "
        f"Intercept: {cal['intercept']} | R²: {cal['r_squared']}")

    append_entry("calibration", "CALIBRATION_DECISION",
        f"Passed: {cal['n_passed']}/{cal['n_total']} | "
        f"LLOQ: {cal['lloq_passed']} | Accepted: {cal['cal_accepted']}",
        status="OK" if cal["cal_accepted"] else "FAIL")

if qc:
    for level in qc["level_decisions"]:
        append_entry("qc", "QC_LEVEL_EVALUATED",
            f"{level['qc_level']}: Acc {level['n_pass_acc']}/{level['n_total']} | "
            f"CV%: {level['cv_pct']:.2f} | Passed: {level['level_passed']}",
            status="OK" if level["level_passed"] else "FAIL")

    append_entry("qc", "QC_BATCH_DECISION",
        f"Levels passed: {qc['n_levels_passed']}/{qc['n_levels_total']} | "
        f"Batch QC: {qc['qc_batch_passed']}",
        status="OK" if qc["qc_batch_passed"] else "FAIL")

if decision:
    append_entry("decision", "BATCH_VERDICT",
        f"Verdict: {decision['verdict']} | "
        f"Reportable: {decision['n_reportable']}/{decision['n_unknowns']} | "
        f"Reason: {decision['reason']}",
        status="OK" if decision["verdict"] == "PASS" else
               "WARNING" if decision["verdict"] == "REVIEW" else "FAIL")

# --- Raw file integrity check ---
raw_dir   = os.path.join(ROOT, PATHS["raw"])
raw_files = sorted([f for f in os.listdir(raw_dir) if f.endswith("_raw.csv")])

if raw_files:
    raw_path = os.path.join(raw_dir, raw_files[-1])
    sha256   = hashlib.sha256()
    with open(raw_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    current_checksum = sha256.hexdigest()

    if manifest:
        original_checksum = manifest.get("checksum_sha256", "")
        integrity_ok      = current_checksum == original_checksum
        append_entry("audit", "RAW_FILE_INTEGRITY_CHECK",
            f"SHA-256 match: {integrity_ok} | "
            f"Current: {current_checksum[:16]}...",
            status="OK" if integrity_ok else "FAIL")
        print(f"Raw file integrity : {'VERIFIED' if integrity_ok else 'FAILED'}")
    else:
        append_entry("audit", "RAW_FILE_CHECKSUM",
            f"SHA-256: {current_checksum[:16]}... (no ingestion manifest to compare)")

# --- Export audit trail ---
audit_df   = pd.DataFrame(audit_entries)
audit_path = os.path.join(logs_dir, f"{batch_id}_audit_trail.csv")
audit_df.to_csv(audit_path, index=False)

print(f"\n=== Audit Trail Summary ===")
print(f"  Total entries : {len(audit_df)}")
for status, group in audit_df.groupby("status"):
    print(f"  {status:<10}: {len(group)} entries")

print(f"\nAudit trail -> {audit_path}")
print("\nAudit trail:")
print(audit_df[["timestamp", "module", "action", "status"]].to_string(index=False))
print("\nNext: reporting.py")
---
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
--
