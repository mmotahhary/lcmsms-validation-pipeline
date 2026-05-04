# LC-MS/MS Bioanalytical Validation Pipeline

An end-to-end regulated bioanalytical data pipeline in Python, simulating how LC-MS/MS batch data flows from raw instrument output through calibration, QC, batch acceptance, and LIMS-ready reporting — following ICH M10 guidelines and ALCOA+ data integrity principles.

Built as a portfolio project to demonstrate applied bioanalytical automation and Python development for regulated CRO/pharma environments.

---

## Background

In a regulated CRO or pharmaceutical lab, every LC-MS/MS analytical batch goes through a defined sequence: raw data is ingested and locked, internal standard normalization is applied, a weighted calibration curve is fitted, QC samples are evaluated against ICH M10 acceptance criteria, a batch verdict is issued, and a batch record is generated for regulatory documentation.

This project simulates that entire workflow in Python. Each script corresponds to a real step in the process, using the same logic, acceptance criteria, and data integrity patterns found in production bioanalytical environments.

The default assay is **25-OH Vitamin D3** in human plasma — a clinically relevant analyte with well-established LC-MS/MS methodology. All calibration concentrations, QC levels, and acceptance criteria are based on published literature and ICH M10 guidance.

---

## Pipeline Overview

```
generate_batch.py    →  Synthetic batch dataset (raw, immutable)
preprocessing.py     →  IS normalization, area ratio verification, flag checks
calibration.py       →  Weighted linear regression (1/x²), back-calculation
qc.py                →  Accuracy (%bias), precision (%CV), ICH M10 acceptance
decision.py          →  Batch verdict (PASS / FAIL / REVIEW), unknown quantification
audit.py             →  ALCOA+ audit trail, raw file integrity check (SHA-256)
reporting.py         →  Regulatory-style PDF batch record (ReportLab)
main_pipeline.py     →  Orchestrates all steps in sequence
```

---

## Scripts

| Script | Real-lab equivalent | Output |
|---|---|---|
| `generate_batch.py` | Instrument data export | `data/raw/<batch_id>_raw.csv` |
| `preprocessing.py` | Data review / IS check | `data/processed/<batch_id>_preprocessed.csv` |
| `calibration.py` | Weighted regression in Watson LIMS / Analyst | `calibration_results.csv`, `calibration_summary.json` |
| `qc.py` | QC review table | `qc_results.csv`, `qc_summary.json` |
| `decision.py` | Batch acceptance decision | `unknown_results.csv`, `batch_decision.json` |
| `audit.py` | Electronic batch record / audit trail | `logs/<batch_id>_audit_trail.csv` |
| `reporting.py` | PDF batch report | `reports/<batch_id>_batch_report.pdf` |

---

## Technical Highlights

**Weighted linear regression from scratch** — implements 1/x and 1/x² weighting using NumPy matrix algebra rather than a black-box library call. Weighting scheme is configurable via `settings.json`. Weighted R² is computed explicitly, consistent with how Watson LIMS and Analyst software handle calibration.

**ICH M10 QC acceptance logic** — accuracy (±15%, ±20% at LLOQ) and precision (≤15% CV, ≤20% at LLOQ) evaluated per replicate and per level. Batch acceptance requires at least 2/3 replicates per level and at least 3/4 QC levels to pass — matching ICH M10 Section 7.1.

**ALCOA+ audit trail** — every pipeline action is logged with timestamp, module, operator, and outcome. Raw file SHA-256 checksum is computed at generation and re-verified at audit to confirm the original data has not been modified.

**Instrument realism** — synthetic data includes peak area variability (5% CV), IS fluctuation (4% CV), RT drift (±0.05 min SD), and random outliers (ion suppression or carryover). Response factor and IS baseline area reflect realistic TSQ Altis / API 5000 sensitivity for 25-OH VitD3.

**Config-driven** — all acceptance thresholds, concentrations, and instrument parameters live in `config/settings.json`. The pipeline is analyte-agnostic — change the config to run a different assay without touching any script.

**Failure logic** — calibration rejection raises a `RuntimeError` and halts the pipeline. QC failure propagates to the batch verdict. FAIL batches mark all unknowns as NOT_REPORTABLE. `main_pipeline.py` catches non-zero exit codes and stops execution.

---

## Assay Reference

| Parameter | Value |
|---|---|
| Analyte | 25-OH Vitamin D3 |
| Internal Standard | d6-25-OH Vitamin D3 |
| Matrix | Human Plasma |
| Calibration range | 2.5 – 100 ng/mL (7 levels) |
| LLOQ | 2.5 ng/mL |
| ULOQ | 100 ng/mL |
| Chromatography | C18, ~2.8 min RT |
| Ionization | ESI positive |
| Quantitation | MRM (peak area ratio) |
| Weighting | 1/x² |
| Accuracy threshold | ±15% (±20% at LLOQ) |
| Precision threshold | ≤15% CV (≤20% at LLOQ) |

---

## Project Structure

```
LC-MSMS_Project/
├── config/
│   └── settings.json
├── data/
│   ├── raw/
│   ├── processed/
│   └── output/
├── logs/
├── reports/
├── generate_batch.py
├── preprocessing.py
├── calibration.py
├── qc.py
├── decision.py
├── audit.py
├── reporting.py
└── main_pipeline.py
```

---

## Setup

**Requirements**

```
Python 3.8+
pandas
numpy
reportlab
```

Install:

```bash
pip install -r requirements.txt
```

**Configuration**

Copy `config/settings.example.json` to `config/settings.json`.

**Run**

```bash
python main_pipeline.py
```

Or step by step in order from `generate_batch.py` to `reporting.py`.

---

## Related Project

[ELISA Automation Pipeline](https://github.com/mmotahhary/elisa-automation-pipeline)

---

## Author

M. Motahhary  
LC-MS/MS Scientist | Bioanalytical Automation  
Calgary, AB, Canada
