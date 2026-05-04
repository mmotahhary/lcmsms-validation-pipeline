"""
main_pipeline.py
Runs the full LC-MS/MS bioanalytical validation pipeline in sequence.
Each step must pass before the next begins.

Usage:
    python main_pipeline.py
"""

import subprocess
import sys
import os
from datetime import datetime

ROOT    = os.path.dirname(os.path.abspath(__file__))
PYTHON  = sys.executable

steps = [
    ("generate_batch.py",  "Generating synthetic batch data"),
    ("preprocessing.py",   "IS normalization and flag checks"),
    ("calibration.py",     "Weighted linear regression and back-calculation"),
    ("qc.py",              "QC accuracy, precision, ICH M10 acceptance"),
    ("decision.py",        "Batch verdict and unknown quantification"),
    ("audit.py",           "ALCOA+ audit trail"),
    ("reporting.py",       "PDF batch report generation"),
]

print("=" * 60)
print("  LC-MS/MS BIOANALYTICAL VALIDATION PIPELINE")
print(f"  Start : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

for script, description in steps:
    script_path = os.path.join(ROOT, script)
    print(f"\n[{description}]")
    print(f"  Running: {script}")

    result = subprocess.run(
        [PYTHON, script_path],
        capture_output=False,
        text=True,
    )

    if result.returncode != 0:
        print(f"\n  PIPELINE HALTED — {script} exited with error.")
        print(f"  Check output above for details.")
        sys.exit(1)

    print(f"  Done.")

print("\n" + "=" * 60)
print("  PIPELINE COMPLETE")
print(f"  End : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)
