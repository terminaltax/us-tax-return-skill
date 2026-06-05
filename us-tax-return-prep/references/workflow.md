# Tax Return Preparation Workflow

Use this workflow when turning a local tax packet into reviewable workpapers and draft forms.

## 1. Intake

Start in the folder that contains the user's tax documents. Expect files such as:

- `summary.md`
- `rental/rental_intake.md` and supporting rental documents when rental property income is in scope
- W-2
- 1099-INT, 1099-DIV, 1099-B, 1099-R, 1099-MISC, 1099-NEC, 1099-K, SSA-1099
- 1098, 1098-E, 1098-T
- Schedule K-1
- prior-year federal or state return
- brokerage consolidated statements
- estimated tax payment confirmations
- health insurance marketplace forms such as 1095-A

Read `summary.md` before source forms, then read `rental/rental_intake.md` when it exists. Treat both Markdown files as user-provided facts, not third-party source data. If either conflicts with an official tax form, record the conflict in `review_notes.md` and ask before resolving it.

## 2. Workspace Setup

Run:

```bash
python3 /path/to/us-tax-return-prep/scripts/prepare_tax_workspace.py .
```

Use `--tax-year YYYY` when the tax year is known. The script creates:

- `tax_forms/extracted_tax_data.yaml`
- `tax_forms/required_irs_forms.yaml`
- `tax_forms/required_state_forms.yaml`
- `tax_forms/source_manifest.yaml`
- `tax_forms/review_notes.md`
- `tax_forms/federal/`
- `tax_forms/state/`
- `tax_forms/workpapers/`
- `rental/rental_intake.md`

The root-level `rental/` folder is for user-provided rental facts and source documents. Keep generated extraction notes and calculation workpapers under `tax_forms/workpapers/`.

## 3. Document Classification

Assign each source document a stable id in `extracted_tax_data.yaml`, for example `w2_001`, `1099int_001`, or `prior_return_001`.

For each document, capture:

- file path
- document type
- tax year
- issuer or payer
- taxpayer or recipient
- important identifier last four digits when useful
- extraction method
- confidence

Do not rely on filenames alone. Confirm document type from the document content when possible.

Read `intake_extraction.md` for classification markers and extraction targets.

## 4. Extraction

Extract numbers exactly as printed. Keep box numbers and source line labels. For consolidated brokerage statements, preserve the statement section and page reference when available.

Common extraction targets:

- W-2: boxes 1, 2, 3, 4, 5, 6, 12 codes, 14 labels, state/local wage and withholding boxes.
- 1099-INT: interest, early withdrawal penalty, federal tax withheld, tax-exempt interest, state tax withheld.
- 1099-DIV: ordinary dividends, qualified dividends, capital gain distributions, section 199A dividends, foreign tax paid, exempt-interest dividends.
- 1099-B: proceeds, basis, wash sale disallowed, short-term and long-term subtotals, covered/noncovered status.
- 1099-R: gross distribution, taxable amount, federal withholding, distribution code, IRA/SEP/SIMPLE indicator, state withholding.
- 1099-NEC/MISC/K: nonemployee compensation, rents, royalties, other income, backup withholding.
- 1098: mortgage interest, points, real estate taxes if shown.
- 1098-E/T: student loan interest, tuition, scholarships, adjustments.
- SSA-1099: net benefits, Medicare premiums, federal withholding.
- K-1: entity type, ordinary income/loss, interest, dividends, capital gains, section 199A data, credits, foreign items, state items.
- Rental folder documents: property tax, mortgage interest, insurance, HOA, repair, utility, rent ledger, lease, depreciation schedule, and closing statement facts needed for Schedule E review.

When text extraction is unreliable, mark the item `confidence: low` and add a review note instead of guessing.

## 5. Required Federal Forms

After extraction, infer which IRS forms and schedules are indicated by the data:

```bash
python3 /path/to/us-tax-return-prep/scripts/infer_required_irs_forms.py .
```

The script writes `tax_forms/required_irs_forms.yaml`. Review `irs_form_selection.md` before overriding its output. Examples:

- W-2 wages alone usually require Form 1040.
- 1099-B, 1099-DA, stock trades, crypto sales, or brokerage proceeds indicate Schedule D and usually Form 8949.
- Self-employment income from 1099-NEC, 1099-K, or business receipts indicates Schedule C, Schedule SE, and Schedule 1.
- Rental, royalty, partnership, S corporation, estate, or trust activity usually indicates Schedule E.

Mark conditional forms as `status: review` rather than dropping them.

## 5A. California Resident Forms

When a California state return is in scope, run:

```bash
python3 /path/to/us-tax-return-prep/scripts/infer_ca_state_forms.py .
```

The script writes `tax_forms/required_state_forms.yaml`. The current CA module targets full-year resident Form 540 returns. It infers:

- `ca540` for California resident Form 540 when CA scope and residency are confirmed; otherwise it marks the form for review.
- `ca540ca` for Schedule CA (540) when California/federal adjustments are indicated, and otherwise for review.
- `ca540d` for Schedule D (540) review when capital gain/loss activity is present.

Do not use this module for nonresident or part-year resident returns without a separate Form 540NR workflow. Confirm California residency and the user's request before preparing state PDFs.

## 6. User Review Gate

After extraction and form inference, stop and ask the user to review `tax_forms/extracted_tax_data.yaml`, `tax_forms/required_irs_forms.yaml`, and any `tax_forms/required_state_forms.yaml`. Highlight:

- missing required personal facts
- low-confidence OCR or ambiguous reads
- conflicts between `summary.md`, prior return, and current forms
- missing tax documents inferred from prior-year return
- federal forms inferred from document types
- state forms inferred from residency, state wage/withholding data, and user-provided scope
- choices that require user decision

Do calculations and form filling after the review gate unless the user explicitly asks for a draft before review.

If required facts or open questions remain, generate a user-editable `summary.md` section:

```bash
python3 /path/to/us-tax-return-prep/scripts/generate_summary_template.py .
```

Ask the user to open `summary.md` in their preferred text editor, fill the blank values, and return when done. Then re-read `summary.md` and update `tax_forms/extracted_tax_data.yaml`.

## 7. Blank Form Download

After the user approves or asks for draft forms, download blank official IRS PDFs:

```bash
python3 /path/to/us-tax-return-prep/scripts/download_irs_forms.py .
```

Use `--include-review` to download forms marked `status: review`. Use `--include-instructions` if instructions should also be downloaded for local review.

For California state forms, download blank official FTB PDFs:

```bash
python3 /path/to/us-tax-return-prep/scripts/download_ca_forms.py . --include-review
```

## 8. Calculation And Line Mapping

Use official current-year IRS and state instructions for calculations. Record derived totals under `calculated:` with source links to the input items that fed the calculation.

Do not embed fixed tax-year thresholds, phaseouts, or worksheet formulas in the skill unless they are stored with a tax-year label and official citation. Prefer fetching or reading current official instructions during the task.

The executing agent is responsible for reading current official IRS/state guidance for changing rules and source-document extraction details. Bundled scripts normalize extracted data, call OpenTaxSolver through `tenforty.otslib` for supported federal and California resident math, and leave missing facts or unsupported schedules as review items.

For federal totals, run:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_rental_depreciation.py .
```

Run the rental depreciation calculator before Schedule E when a current-year depreciation amount is not supplied from a prior-year depreciation schedule. It uses the property land/building split, placed-in-service date, straight-line method, and mid-month convention for common residential rental buildings. It records federal and California depreciation values and California rental depreciation addition/subtraction amounts for Schedule CA review. It flags missing building basis, pre-1987 property, bonus depreciation, Section 179, special credits, and accelerated write-offs for review.

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_schedule_e.py .
```

Run the Schedule E calculator before the general federal calculator when rental or royalty activity is present. It calculates Schedule E Part I columns A-C, line 23 summary totals, line 26, line 41, and Schedule 1 line 5 from reviewed `income.rentals_royalties_partnerships` data. When a rental loss exists, run the Form 8582 calculator next before relying on Schedule E line 22.

When direct rental real estate has a loss or prior-year unallowed passive loss, run:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_form_8582.py .
```

The Form 8582 calculator covers the common active-participation rental real estate path for individuals. It computes the special allowance phaseout, allocates allowed and unallowed losses, updates Schedule E line 22, and carries the allowed rental result to Schedule 1 line 5. It flags PTPs, passive credits, CRD, K-1 activity details, married filing separately with spouse cohabitation, and losses reported on multiple forms for review.

Then run:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_tax_lines.py .
```

This writes `calculated.form_line_values` and `tax_forms/workpapers/calculation_report.yaml`. Reports include `math_engine` metadata and the OTS input/output keys used.

For California resident Form 540 math after federal calculations, run:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_ca_lines.py .
```

This writes `tax_forms/workpapers/ca_calculation_report.yaml` and updates `calculated.form_line_values.ca540` and `calculated.form_line_values.ca540ca`. OTS computes resident Form 540 tax and exemption-credit math from reviewed inputs; AMT, Behavioral Health Services Tax inputs, use tax, special credits, penalties, and residency allocation still require review unless explicit values are supplied.

Validate the packet:

```bash
python3 /path/to/us-tax-return-prep/scripts/validate_tax_data.py .
```

This writes `tax_forms/workpapers/validation_report.yaml`.

## 9. Regenerate Tax PDFs

Use the standalone workflow name `regenerate-tax-pdfs` when the user has already edited `tax_forms/extracted_tax_data.yaml` or field maps and wants only to regenerate PDFs.

Run:

```bash
python3 /path/to/us-tax-return-prep/scripts/regenerate_tax_pdfs.py .
```

Inputs:

- `tax_forms/extracted_tax_data.yaml`
- `tax_forms/required_irs_forms.yaml`
- `tax_forms/required_state_forms.yaml` when regenerating state forms
- blank PDFs under `tax_forms/workpapers/blank_forms/irs/` or `tax_forms/workpapers/blank_forms/ca/`
- field maps under `tax_forms/workpapers/field_maps/` or `tax_forms/workpapers/field_maps/ca/`

Outputs:

- filled draft PDFs under each form's `output_dir`, usually `tax_forms/federal/`
- `tax_forms/workpapers/filled_pdf_manifest.yaml`

The script is deterministic. It does not infer missing values, calculate tax, or choose forms. Missing field maps, missing PDFs, missing required values, and field-name mismatches are reported in the manifest.

If a field map is missing, generate a skeleton map from the blank PDF:

```bash
python3 /path/to/us-tax-return-prep/scripts/inspect_pdf_fields.py tax_forms/workpapers/blank_forms/irs/f1040.pdf --form-id f1040 --tax-year 2025 --output tax_forms/workpapers/field_maps/f1040_field_map.yaml
```

For Schedule E, generate the default field map for the current IRS fillable PDF names:

```bash
python3 /path/to/us-tax-return-prep/scripts/generate_schedule_e_field_map.py . --tax-year 2025
```

Validate after downloading `f1040se.pdf`, because IRS field names can change by form revision.

For Form 8582, generate the default field map for the common direct-rental path:

```bash
python3 /path/to/us-tax-return-prep/scripts/generate_form_8582_field_map.py . --tax-year 2025
```

Validate after downloading `f8582.pdf`, because IRS field names can change by form revision.

For California forms, inspect FTB PDFs under the CA blank-form directory:

```bash
python3 /path/to/us-tax-return-prep/scripts/inspect_pdf_fields.py tax_forms/workpapers/blank_forms/ca/2025-540.pdf --form-id ca540 --tax-year 2025 --output tax_forms/workpapers/field_maps/ca/ca540_field_map.yaml
```

## 10. Draft Forms

Write completed forms under:

- `tax_forms/federal/`
- `tax_forms/state/`

Keep intermediate field maps, calculation notes, and extracted text snippets under `tax_forms/workpapers/`.

Name generated PDFs with tax year and form name, for example `2025_f1040_draft.pdf`.

## 11. Final Response

Generate a review report first:

```bash
python3 /path/to/us-tax-return-prep/scripts/generate_review_report.py .
```

Report only:

- files created or updated
- unresolved questions
- low-confidence areas
- validation checks performed

Do not paste full SSNs, full account numbers, or full employer/payor TINs into chat.
