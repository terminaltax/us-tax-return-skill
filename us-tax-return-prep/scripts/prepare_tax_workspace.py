#!/usr/bin/env python3
"""Create a tax_forms workspace and source manifest for a local tax packet."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "tax_forms"}

RENTAL_INTAKE = """# Rental Income Intake

Use this file for rental property facts that may not appear on tax forms. Leave a value blank or write `unknown` when you are not sure. Put supporting documents in this `rental/` folder, such as property tax bills, mortgage interest statements, insurance bills, HOA statements, repair invoices, rent ledgers, leases, closing statements, and depreciation schedules.

Copy the Rental Property section for each additional property.

## Rental Property 1

### Property And Ownership

- Property nickname:
- Street address:
- City:
- State:
- ZIP:
- Property type:
- Ownership percentage:
- Date placed in service as a rental:
- Date sold or stopped being a rental:

### Rental Use

- Was this rented at fair rental value?:
- Days rented:
- Personal-use days:
- Vacant days available for rent:
- Average rental period:
- Did you materially participate?:
- Did you actively participate?:

### Income

- Gross rents received:
- Other rental income:
- Security deposits kept as income:

### Expenses

- Advertising:
- Auto and travel:
- Cleaning and maintenance:
- Commissions:
- Insurance:
- Legal and professional fees:
- Management fees:
- Mortgage interest:
- Other interest:
- Repairs:
- Supplies:
- Real estate taxes:
- Utilities:
- HOA dues:
- Other expenses:

### Repairs And Improvements

- Repairs paid during the year:
- Improvements or major purchases:
- For each improvement, list description, date placed in service, cost, and whether it replaced part of the property:

### Depreciation And Carryovers

- Original property purchase date:
- Original purchase price:
- If this was converted from personal use, fair market value on the date it became a rental:
- Land value or land percentage:
- Building value or depreciable basis, excluding land:
- Source for land/building split, such as county assessment, appraisal, closing statement, or other method:
- Federal prior depreciation claimed:
- Current depreciation from a prior-year schedule:
- California building basis, if different from federal:
- California prior depreciation, if different from federal:
- California recovery period or method, if different from federal:
- Passive activity loss carryover from prior year:
- Any bonus depreciation, Section 179, special credits, or accelerated write-offs previously claimed:

### Depreciable Improvements And Assets

- List each improvement or depreciable asset separately:
- For each item, include description, date placed in service, cost, land/building/personal-property type, federal depreciation already claimed, and California basis or method if different:

### Documents In This Folder

- Property tax bill:
- Mortgage interest statement or Form 1098:
- Insurance bill:
- HOA statement:
- Rent ledger or lease:
- Repair invoices:
- Utility bills:
- Depreciation schedule:
- Closing or settlement statement:

### Notes And Questions

- Anything unusual, uncertain, or requiring review:
"""

ITEMIZED_INTAKE = """# Itemized Deduction Intake

Use this file at the beginning of the return process to choose standard deduction, itemized deductions, or a compare-both review. Leave values blank or write `unknown` when you are not sure. If you may itemize, put supporting documents in this `itemized/` folder, such as medical receipts, property tax bills, mortgage interest statements, charitable donation receipts, DMV registration bills, state tax payment confirmations, casualty or disaster records, and prior-year charitable carryover schedules.

## Deduction Choice

- Choose one: standard / itemized / unsure:
- If you chose standard, do you still want Codex to extract itemized documents for state or comparison review?:
- If you chose itemized or unsure, fill the sections below and add supporting documents to this folder.
- Any reason you expect itemizing to be better than the standard deduction?:

## Medical And Dental Expenses

- Total unreimbursed medical and dental expenses:
- Health insurance premiums paid after tax:
- Doctor, dentist, hospital, lab, therapy, or prescription costs:
- Medical mileage or transportation:
- Reimbursements, HSA/FSA payments, or insurance reimbursements:
- Supporting documents in this folder:

## Taxes Paid

- State and local income taxes paid during the year, excluding paycheck withholding:
- Prior-year state or local tax balance paid during this tax year:
- State or local estimated tax payments:
- Real estate taxes on your home:
- Personal property taxes, such as the deductible tax portion of vehicle registration:
- Any tax refunds, rebates, or reimbursements received:
- Supporting documents in this folder:

## Interest Paid

- Home mortgage interest from Form 1098:
- Points paid:
- Mortgage insurance premiums, if shown:
- Home equity loan interest, and how the loan proceeds were used:
- Investment interest expense:
- Supporting documents in this folder:

## Gifts To Charity

- Cash, check, credit card, or payroll charitable gifts:
- Noncash donations:
- Charitable mileage or unreimbursed volunteer expenses:
- Charitable carryover from a prior-year return:
- Any goods or services received in exchange for donations:
- Supporting documents in this folder:

## Casualty And Theft

- Federally declared disaster or theft event:
- Date of event:
- Property affected:
- Insurance or other reimbursements:
- FEMA or disaster declaration reference:
- Supporting documents in this folder:

## Other Schedule A Items

- Gambling losses up to gambling winnings:
- Impairment-related work expenses:
- Estate tax on income in respect of a decedent:
- Any other itemized deduction facts:
- Supporting documents in this folder:

## California Or State Differences

- Are you filing a California return?:
- California real estate taxes, mortgage interest, charitable gifts, or other itemized amounts that differ from federal:
- California-specific supporting documents or prior-year schedules:

## Notes And Questions

- Anything unusual, uncertain, or requiring review:
"""

RENTAL_DOCUMENT_TYPE_PATTERNS = [
    ("rental_intake", ["rental-intake.md"]),
    ("rental_property_tax", ["property-tax", "real-estate-tax", "realestate-tax"]),
    ("rental_mortgage_interest", ["mortgage-interest", "form-1098", "1098-mortgage"]),
    ("rental_insurance", ["rental-insurance", "landlord-insurance", "property-insurance", "insurance"]),
    ("rental_hoa", ["hoa", "homeowner-association"]),
    ("rental_repairs", ["repair", "maintenance", "invoice"]),
    ("rental_utilities", ["utility", "utilities", "electric", "water", "gas"]),
    ("rental_lease_or_ledger", ["lease", "rent-ledger", "rental-ledger", "rent-roll"]),
    ("rental_depreciation", ["depreciation", "asset-schedule"]),
    ("rental_closing_statement", ["closing-statement", "settlement-statement", "hud-1", "alta"]),
]

ITEMIZED_DOCUMENT_TYPE_PATTERNS = [
    ("itemized_intake", ["itemized-intake.md"]),
    ("itemized_medical", ["medical", "dental", "doctor", "hospital", "pharmacy", "prescription"]),
    ("itemized_property_tax", ["property-tax", "real-estate-tax", "realestate-tax", "tax-bill"]),
    ("itemized_mortgage_interest", ["mortgage-interest", "form-1098", "1098-mortgage", "points"]),
    ("itemized_charity_noncash", ["goodwill", "salvation-army", "noncash", "donated-goods"]),
    ("itemized_charity_cash", ["charity", "charitable", "donation", "tithe", "church", "nonprofit"]),
    ("itemized_state_tax", ["state-tax", "estimated-tax", "extension-payment", "prior-year-tax", "balance-due"]),
    ("itemized_vehicle_tax", ["dmv", "vehicle-registration", "car-registration", "registration"]),
    ("itemized_casualty", ["casualty", "theft", "disaster", "fema"]),
    ("itemized_investment_interest", ["investment-interest", "margin-interest"]),
]

DOCUMENT_TYPE_PATTERNS = [
    ("summary", ["summary.md"]),
    ("W-2", ["w-2", "w2"]),
    ("1099-INT", ["1099-int", "1099int"]),
    ("1099-DIV", ["1099-div", "1099div"]),
    ("1099-B", ["1099-b", "1099b"]),
    ("1099-DA", ["1099-da", "1099da"]),
    ("1099-R", ["1099-r", "1099r"]),
    ("1099-NEC", ["1099-nec", "1099nec"]),
    ("1099-MISC", ["1099-misc", "1099misc"]),
    ("1099-K", ["1099-k", "1099k"]),
    ("SSA-1099", ["ssa-1099", "ssa1099", "social-security"]),
    ("1098-E", ["1098-e", "1098e"]),
    ("1098-T", ["1098-t", "1098t"]),
    ("1098", ["1098"]),
    ("1095-A", ["1095-a", "1095a"]),
    ("K-1", ["k-1", "k1", "schedule-k-1"]),
    ("brokerage_statement", ["brokerage", "consolidated", "realized-gain", "stock"]),
    ("prior_return", ["prior-return", "last-year", "previous-year", "1040"]),
]


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if any(part.startswith(".") for part in rel_parts):
            continue
        yield path


def infer_document_type(path: Path) -> str:
    normalized = str(path).lower().replace("_", "-").replace(" ", "-")
    filename = path.name.lower().replace("_", "-").replace(" ", "-")
    if filename == "summary.md":
        return "summary"
    if "/rental/" in normalized or normalized.endswith("/rental-intake.md"):
        for document_type, patterns in RENTAL_DOCUMENT_TYPE_PATTERNS:
            if any(pattern in normalized for pattern in patterns):
                return document_type
    if "/itemized/" in normalized or normalized.endswith("/itemized-intake.md"):
        for document_type, patterns in ITEMIZED_DOCUMENT_TYPE_PATTERNS:
            if any(pattern in normalized for pattern in patterns):
                return document_type
    for document_type, patterns in DOCUMENT_TYPE_PATTERNS:
        if any(pattern in normalized for pattern in patterns):
            return document_type
    return "unknown"


def write_manifest(root: Path, output_path: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    lines = [
        'schema_version: "0.1"',
        f"generated_at: {yaml_string(now)}",
        f"root: {yaml_string(str(root))}",
        "documents:",
    ]
    for index, path in enumerate(iter_source_files(root), start=1):
        rel = path.relative_to(root)
        stat = path.stat()
        doc_id = f"doc_{index:03d}"
        lines.extend(
            [
                f"  - id: {yaml_string(doc_id)}",
                f"    path: {yaml_string(str(rel))}",
                f"    extension: {yaml_string(path.suffix.lower())}",
                f"    size_bytes: {stat.st_size}",
                f"    sha256: {yaml_string(sha256_file(path))}",
                f"    document_type: {yaml_string(infer_document_type(path))}",
                "    tax_year: unknown",
                "    notes: []",
            ]
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def initial_tax_data(tax_year: str) -> str:
    return f'''schema_version: "0.1"
tax_year: {yaml_string(tax_year)}
return_scope:
  federal: true
  states: []
  local: []
review_status: "needs_extraction"
required_irs_forms:
  status: "not_inferred"
  file: "tax_forms/required_irs_forms.yaml"
required_state_forms:
  status: "not_inferred"
  file: "tax_forms/required_state_forms.yaml"
filled_pdfs:
  status: "not_generated"
  file: "tax_forms/workpapers/filled_pdf_manifest.yaml"
calculation:
  status: "not_calculated"
  file: "tax_forms/workpapers/calculation_report.yaml"
validation:
  status: "not_validated"
  file: "tax_forms/workpapers/validation_report.yaml"
review_report:
  status: "not_generated"
  file: "tax_forms/review_report.md"

taxpayer:
  primary:
    full_name: unknown
    ssn: unknown
    date_of_birth: unknown
    occupation: unknown
  spouse:
    full_name: null
    ssn: null
    date_of_birth: null
    occupation: null
  address:
    line1: unknown
    line2: null
    city: unknown
    state: unknown
    zip: unknown
  filing_status: unknown
  dependents: []

source_documents: []

income:
  wages: []
  interest: []
  dividends: []
  capital_gains: []
  retirement_distributions: []
  social_security: []
  business_or_1099_income: []
  rentals_royalties_partnerships: []
  other_income: []

adjustments:
  educator_expenses: []
  hsa: []
  self_employed: []
  student_loan_interest: []
  ira_deduction: []
  other: []

deductions:
  standard_or_itemized: unknown
  standard_deduction: unknown
  itemized_deduction_total: unknown
  selected_deduction_amount: unknown
  itemized:
    medical: []
    taxes_paid: []
    interest_paid: []
    gifts_to_charity: []
    casualty_theft: []
    other: []

credits:
  child_and_dependent: []
  education: []
  energy: []
  foreign_tax: []
  retirement_saver: []
  premium_tax_credit: []
  other: []

payments:
  federal_withholding: []
  estimated_tax_payments: []
  extension_payments: []
  refundable_credits: []
  state_withholding: []
  state_estimated_payments: []

state_adjustments:
  ca:
    residency_status: unknown
    reviewed_no_adjustments: false
    subtractions_total: unknown
    additions_total: unknown
    itemized_deduction_total: unknown

carryovers_and_prior_year:
  prior_year_return_documents: []
  capital_loss_carryover: unknown
  charitable_carryover: unknown
  amt_credit_carryover: unknown
  other: []

calculated:
  totals: {{}}
  form_line_values: {{}}
  worksheets: []

open_questions: []
review_notes: []
'''


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create tax_forms output folders, source manifest, and initial extracted_tax_data.yaml."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Folder containing tax documents. Defaults to the current directory.",
    )
    parser.add_argument(
        "--tax-year",
        default="unknown",
        help="Tax year for the initial YAML, such as 2025.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite source_manifest.yaml and extracted_tax_data.yaml if they already exist.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root folder does not exist or is not a directory: {root}")

    output_dir = root / "tax_forms"
    rental_dir = root / "rental"
    rental_dir.mkdir(parents=True, exist_ok=True)
    rental_intake_path = rental_dir / "rental_intake.md"
    if args.overwrite or not rental_intake_path.exists():
        rental_intake_path.write_text(RENTAL_INTAKE, encoding="utf-8")
    itemized_dir = root / "itemized"
    itemized_dir.mkdir(parents=True, exist_ok=True)
    itemized_intake_path = itemized_dir / "itemized_intake.md"
    if args.overwrite or not itemized_intake_path.exists():
        itemized_intake_path.write_text(ITEMIZED_INTAKE, encoding="utf-8")

    for child in [
        "federal",
        "state",
        "workpapers",
        "workpapers/blank_forms/irs",
        "workpapers/blank_forms/ca",
        "workpapers/field_maps",
        "workpapers/field_maps/ca",
    ]:
        (output_dir / child).mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "source_manifest.yaml"
    if args.overwrite or not manifest_path.exists():
        write_manifest(root, manifest_path)

    data_path = output_dir / "extracted_tax_data.yaml"
    if args.overwrite or not data_path.exists():
        data_path.write_text(initial_tax_data(args.tax_year), encoding="utf-8")

    required_forms_path = output_dir / "required_irs_forms.yaml"
    if args.overwrite or not required_forms_path.exists():
        required_forms_path.write_text(
            "\n".join(
                [
                    'schema_version: "0.1"',
                    f"tax_year: {yaml_string(args.tax_year)}",
                    'status: "not_inferred"',
                    'generated_from: "tax_forms/extracted_tax_data.yaml"',
                    "forms: []",
                    "open_questions: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    required_state_forms_path = output_dir / "required_state_forms.yaml"
    if args.overwrite or not required_state_forms_path.exists():
        required_state_forms_path.write_text(
            "\n".join(
                [
                    'schema_version: "0.1"',
                    f"tax_year: {yaml_string(args.tax_year)}",
                    'status: "not_inferred"',
                    'generated_from: "tax_forms/extracted_tax_data.yaml"',
                    "states: []",
                    "forms: []",
                    "open_questions: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    notes_path = output_dir / "review_notes.md"
    if args.overwrite or not notes_path.exists():
        notes_path.write_text(
            "# Review Notes\n\n- Initial workspace created. Add extraction notes here.\n",
            encoding="utf-8",
        )

    print(f"Created workspace: {output_dir}")
    print(f"Manifest: {manifest_path}")
    print(f"Tax data: {data_path}")
    print(f"Required IRS forms: {required_forms_path}")
    print(f"Required state forms: {required_state_forms_path}")
    print(f"Rental intake: {rental_intake_path}")
    print(f"Itemized intake: {itemized_intake_path}")
    print(f"Review notes: {notes_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
