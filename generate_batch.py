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
