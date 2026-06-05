# US Tax Skill

This workspace contains two Codex skills:

- `us-tax-return-prep`: end-to-end draft US individual tax return preparation from a folder of tax documents.
- `regenerate-tax-pdfs`: standalone deterministic PDF regeneration from an edited `extracted_tax_data.yaml`, blank PDFs, and field maps.

These skills create draft preparation artifacts for review. They do not file, sign, mail, e-file, or certify a tax return.

## Install

Install the skills by copying the skill folders into your Codex skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R us-tax-return-prep regenerate-tax-pdfs "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Restart Codex after copying so the skills are rediscovered.

## Dependencies

Create a local virtual environment and install runtime/test dependencies:

```bash
uv venv .venv
uv pip install --python .venv/bin/python pyyaml pypdf reportlab pytest tenforty "polars[rtcompat]"
```

Use the venv interpreter when running scripts directly:

```bash
.venv/bin/python -B us-tax-return-prep/scripts/prepare_tax_workspace.py --help
```

## End-To-End Use

Start in a folder containing tax documents such as W-2s, 1099s, prior-year returns, and `summary.md`.

```bash
cd /path/to/tax-packet
```

Create the workspace:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/prepare_tax_workspace.py . \
  --tax-year 2025
```

This creates:

```text
itemized/
  itemized_intake.md
rental/
  rental_intake.md
tax_forms/
  extracted_tax_data.yaml
  required_irs_forms.yaml
  required_state_forms.yaml
  source_manifest.yaml
  review_notes.md
  federal/
  state/
  workpapers/
    blank_forms/irs/
    blank_forms/ca/
    field_maps/
    field_maps/ca/
```

Use `$us-tax-return-prep` in Codex to classify documents, extract values into `tax_forms/extracted_tax_data.yaml`, and record review notes.

At the beginning of the workflow, fill `itemized/itemized_intake.md` to choose `standard`, `itemized`, or `unsure`. If you choose standard, you can leave the rest blank unless you want a state or comparison review. If you choose itemized or unsure, fill the Schedule A sections and place supporting itemized deduction documents in `itemized/`, such as medical receipts, property tax bills, Form 1098 mortgage interest statements, charitable receipts, DMV registration bills, and state tax payment confirmations. Codex uses that file and the supporting documents to update `deductions.standard_or_itemized`, `deductions.itemized`, `deductions.itemized_deduction_total`, and California itemized deduction review fields when applicable.

If rental income is in scope, fill `rental/rental_intake.md` and place supporting rental documents in `rental/`, such as property tax bills, mortgage interest statements, insurance bills, HOA statements, repair invoices, rent ledgers, leases, closing statements, and depreciation schedules. Codex uses that file and the supporting documents to update `income.rentals_royalties_partnerships` with source-backed Schedule E facts.

Infer required IRS forms:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/infer_required_irs_forms.py .
```

Calculate federal line values with OpenTaxSolver through `tenforty.otslib`:

For itemized deductions or standard-versus-itemized comparison, calculate Schedule A after AGI is known or supplied. If AGI is not available yet, run `calculate_tax_lines.py` once to populate Form 1040 line 11, then run Schedule A and rerun `calculate_tax_lines.py` for final taxable income:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/calculate_schedule_a.py .
```

This writes `tax_forms/workpapers/schedule_a_report.yaml`, updates `calculated.form_line_values.f1040sa`, sets `deductions.itemized_deduction_total`, and chooses `deductions.selected_deduction_amount` when the user selected `unsure`. It covers common Schedule A lines and flags complex mortgage interest, investment interest, charitable limit, casualty, and state differences for review.

For rental property depreciation, calculate the building depreciation first when the current-year amount is not already supplied by a prior-year depreciation schedule:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/calculate_rental_depreciation.py .
```

This writes `tax_forms/workpapers/rental_depreciation_report.yaml`, updates each rental property's `depreciation.current_depreciation`, records federal and California depreciation values, and prepares California rental depreciation addition/subtraction amounts for Schedule CA review.

For rental or royalty activity, calculate Schedule E Part I next:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/calculate_schedule_e.py .
```

This writes `tax_forms/workpapers/schedule_e_report.yaml` and updates `calculated.form_line_values.f1040se` plus Schedule 1 line 5. If a rental has a loss, run the Form 8582 calculator before relying on Schedule E line 22.

When a direct rental has a loss or prior-year unallowed passive loss, calculate Form 8582 next:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/calculate_form_8582.py .
```

This writes `tax_forms/workpapers/form_8582_report.yaml`, computes the common active-participation rental real estate passive-loss limit, updates Schedule E line 22, and carries the allowed rental result to Schedule 1 line 5.

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/calculate_tax_lines.py .
```

Infer California resident state forms when a CA return is in scope:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/infer_ca_state_forms.py .
```

This writes `tax_forms/required_state_forms.yaml`. The first state module targets California full-year resident Form 540 returns and marks residency, Schedule CA adjustments, AMT, use tax, special credits, and other user-specific items for review when needed.

Calculate California resident line values with OpenTaxSolver:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/calculate_ca_lines.py .
```

This writes `tax_forms/workpapers/ca_calculation_report.yaml` and updates `calculated.form_line_values.ca540` and `ca540ca`.

Validate the packet:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/validate_tax_data.py .
```

Generate missing fields into `summary.md` when the packet needs user-provided facts:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/generate_summary_template.py .
```

Open `summary.md` in your preferred text editor, fill the blank values, then ask Codex to re-read it and update `tax_forms/extracted_tax_data.yaml`.

Download blank IRS PDFs from the inferred form plan:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/download_irs_forms.py . \
  --include-review
```

Download blank California FTB PDFs from the inferred state plan:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/download_ca_forms.py . \
  --include-review
```

Create or edit field maps under:

```text
tax_forms/workpapers/field_maps/
```

To generate a skeleton field map from a blank fillable PDF:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/inspect_pdf_fields.py \
  tax_forms/workpapers/blank_forms/irs/f1040.pdf \
  --form-id f1040 \
  --tax-year 2025 \
  --output tax_forms/workpapers/field_maps/f1040_field_map.yaml
```

Skeleton maps include semantic suggestions from `us-tax-return-prep/assets/field_maps/federal/semantic_field_library.yaml` for covered federal forms. The executing agent still needs to connect those suggestions to the current PDF's physical field names and validate the result.

For California forms, use the CA blank-form directory and field-map directory:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/inspect_pdf_fields.py \
  tax_forms/workpapers/blank_forms/ca/2025-540.pdf \
  --form-id ca540 \
  --tax-year 2025 \
  --output tax_forms/workpapers/field_maps/ca/ca540_field_map.yaml
```

Covered California forms use semantic suggestions from `us-tax-return-prep/assets/field_maps/ca/semantic_field_library.yaml`.

For Schedule E, generate the default current IRS field map:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/generate_schedule_e_field_map.py . \
  --tax-year 2025
```

Then run validation after `f1040se.pdf` is downloaded so any IRS field-name revision is caught before filling.

For Schedule A, generate the default current IRS field map:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/generate_schedule_a_field_map.py . \
  --tax-year 2025
```

Then run validation after `f1040sa.pdf` is downloaded so any IRS field-name revision is caught before filling.

For Form 8582, generate the default current IRS field map:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/generate_form_8582_field_map.py . \
  --tax-year 2025
```

Then regenerate filled PDFs:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/regenerate_tax_pdfs.py . \
  --overwrite
```

Generated PDFs go under each form's `output_dir`, usually `tax_forms/federal/`. The fill manifest is written to:

```text
tax_forms/workpapers/filled_pdf_manifest.yaml
```

To regenerate only California state forms, pass the state plan. Per-form `blank_dir` and `field_map_dir` entries in `required_state_forms.yaml` point to the CA folders:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/regenerate_tax_pdfs.py . \
  --forms-plan tax_forms/required_state_forms.yaml \
  --overwrite
```

Generate a human-readable review report:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/us-tax-return-prep/scripts/generate_review_report.py .
```

## Standalone PDF Regeneration

If you manually correct `tax_forms/extracted_tax_data.yaml` and only need to regenerate PDFs, use the standalone skill:

```text
$regenerate-tax-pdfs
```

Or run the script directly:

```bash
/path/to/us-tax-skill/.venv/bin/python -B \
  /path/to/us-tax-skill/regenerate-tax-pdfs/scripts/regenerate_tax_pdfs.py . \
  --overwrite
```

The standalone script expects:

- `tax_forms/extracted_tax_data.yaml`
- `tax_forms/required_irs_forms.yaml`
- `tax_forms/required_state_forms.yaml` when regenerating state forms
- blank PDFs in `tax_forms/workpapers/blank_forms/irs/`
- state blank PDFs in `tax_forms/workpapers/blank_forms/ca/`
- field maps in `tax_forms/workpapers/field_maps/` or `tax_forms/workpapers/field_maps/ca/`

## Tests

Run the unit tests from this workspace:

```bash
.venv/bin/python -B -m pytest -q
```

The test suite covers:

- workspace setup
- required IRS form inference
- California resident form inference
- IRS PDF download with mocked network access
- California FTB PDF download with mocked network access
- federal line calculation
- California resident line calculation
- validation reports
- missing-field `summary.md` generation
- PDF field inspection and skeleton field maps
- deterministic PDF regeneration for both skills
- state form PDF regeneration using per-form blank and field-map directories
- rental intake workspace creation, rental document classification, and incomplete rental validation warnings
- rental depreciation calculation and California depreciation adjustment tracking
- Schedule E and Form 8582 rental loss calculations, field maps, and PDF filling

## Important Limits

- Federal and California math uses OpenTaxSolver through `tenforty.otslib` for supported tax years. The scripts still emit review items when required facts, elections, or unsupported schedules are missing.
- Rental depreciation support covers the common residential rental building path using straight-line depreciation and the mid-month convention. Improvements, personal property, cost segregation, property sales, and Form 4562 PDF completion remain review/manual workflows.
- Form 8582 support covers the common direct rental real estate active-participation path. PTPs, CRD, passive credits, K-1 activity details, married filing separately with spouse cohabitation, and losses reported on multiple forms remain review/manual workflows.
- The California module covers full-year resident Form 540 only. It does not prepare Form 540NR and still requires review for AMT, Behavioral Health Services Tax inputs, use tax, special credits, penalties, residency allocation, and Schedule CA differences unless explicit reviewed values are supplied.
- Field maps are required because IRS and state PDF field names vary by form revision.
- Outputs are draft workpapers and PDFs for human review, not filed returns.
- Keep sensitive data local and do not paste full SSNs or full TINs into chat.
