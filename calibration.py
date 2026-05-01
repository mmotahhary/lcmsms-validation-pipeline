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
