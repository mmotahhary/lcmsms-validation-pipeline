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
