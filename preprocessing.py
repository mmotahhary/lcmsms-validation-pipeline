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
