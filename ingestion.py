"""
ingestion.py
Validates raw LC-MS/MS batch CSV before preprocessing.
Creates ingestion manifest with SHA-256 checksum and schema validation.

Input : data/raw/<batch_id>_raw.csv
Output: data/output/<batch_id>_ingestion_manifest.json

Run after generate_batch.py.
"""

import pandas as pd
import os
import json
import hashlib
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(ROOT, "config", "settings.json")

with open(config_path) as f:
    config = json.load(f)

PATHS = config["paths"]

required_columns = [
    "batch_id",
    "sample_id",
    "sample_type",
    "analyte",
    "internal_standard",
    "nominal_conc_ngml",
    "measured_peak_area",
    "IS_peak_area",
    "area_ratio",
    "retention_time",
    "run_order"
]

raw_dir = os.path.join(ROOT, PATHS["raw"])
out_dir = os.path.join(ROOT, PATHS["output"])

os.makedirs(out_dir, exist_ok=True)

raw_files = sorted([
    f for f in os.listdir(raw_dir)
    if f.endswith("_raw.csv")
])

if not raw_files:
    raise FileNotFoundError(
        "No raw batch found. Run generate_batch.py first."
    )

raw_path = os.path.join(raw_dir, raw_files[-1])

print(f"Loading: {raw_files[-1]}")

df = pd.read_csv(raw_path)

batch_id = df["batch_id"].iloc[0]

missing_cols = [
    c for c in required_columns
    if c not in df.columns
]

schema_valid = len(missing_cols) == 0

if schema_valid:
    print("Schema validation: PASSED")
else:
    print("Schema validation: FAILED")
    print(f"Missing columns: {missing_cols}")

is_mean = df["IS_peak_area"].mean()
is_sd   = df["IS_peak_area"].std()
is_cv   = (is_sd / is_mean) * 100

if is_cv < config["is_control"]["cv_warning_pct"]:
    is_status = "OK"
elif is_cv < config["is_control"]["cv_fail_pct"]:
    is_status = "WARNING"
else:
    is_status = "FAIL"

sha256 = hashlib.sha256()

with open(raw_path, "rb") as f:
    for chunk in iter(lambda: f.read(8192), b""):
        sha256.update(chunk)

checksum = sha256.hexdigest()

manifest = {
    "batch_id": batch_id,
    "raw_file": raw_path,
    "rows_loaded": int(len(df)),
    "schema_valid": schema_valid,
    "missing_columns": missing_cols,
    "checksum_sha256": checksum,
    "is_mean": round(float(is_mean), 2),
    "is_sd": round(float(is_sd), 2),
    "is_cv_pct": round(float(is_cv), 2),
    "is_status": is_status,
    "ingested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
}

manifest_path = os.path.join(
    out_dir,
    f"{batch_id}_ingestion_manifest.json"
)

with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Manifest saved: {manifest_path}")
print(f"IS CV%: {is_cv:.2f}%")
print(f"Status: {is_status}")
print("Next: preprocessing.py")