# Extracted Tax Data YAML Schema

Use this schema for `tax_forms/extracted_tax_data.yaml`. Keep it readable and reviewable. Add sections as needed, but preserve the top-level shape so later scripts and agents can consume it.

## Conventions

- Use decimal strings for money: `"1234.56"`.
- Use ISO dates: `YYYY-MM-DD`.
- Use `unknown` instead of guessing.
- Use full SSNs only when needed for form filling and only in local files.
- Include `source_refs` for material numbers.
- Use `needs_review: true` for uncertain or user-confirmed facts.

## Top-Level Template

```yaml
schema_version: "0.1"
tax_year: unknown
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
  engine_version: null
  generated_at: null
  scope: null
  totals: {}
  form_line_values: {}
  worksheets: []
  review_items: []

open_questions: []
review_notes: []
```

## Calculated Lines

Run `scripts/calculate_schedule_a.py` before the general federal calculator when itemized deductions are selected or comparison is needed:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_schedule_a.py .
```

The Schedule A script updates `deductions.itemized_deduction_total`, `deductions.selected_deduction_amount`, `calculated.form_line_values.f1040sa`, and writes `tax_forms/workpapers/schedule_a_report.yaml`.

Important Schedule A calculated paths include:

```yaml
deductions:
  standard_or_itemized: "itemized"
  standard_deduction: "31500.00"
  itemized_deduction_total: "52000.00"
  selected_deduction_amount: "52000.00"
calculated:
  form_line_values:
    f1040sa:
      line_1_medical_and_dental_expenses: "12000.00"
      line_2_adjusted_gross_income: "100000.00"
      line_3_medical_threshold_7_5_percent: "7500.00"
      line_4_medical_deduction: "4500.00"
      line_5d_total_taxes_before_limit: "45000.00"
      line_5e_state_and_local_tax_deduction: "40000.00"
      line_8a_home_mortgage_interest_form_1098: "6000.00"
      line_10_total_interest: "6000.00"
      line_14_total_gifts_to_charity: "1500.00"
      line_17_total_itemized_deductions: "52000.00"
```

The Schedule A script covers common 2025 medical, taxes, interest, gifts, casualty, and other itemized lines. It adds review items for mortgage debt limits, Form 4952 investment interest, charitable contribution limit classes/carryovers, Form 4684 casualty calculations, and state differences when reviewed allowable amounts are not supplied.

Run `scripts/calculate_rental_depreciation.py` before Schedule E when current-year depreciation is not already supplied from a prior-year depreciation schedule:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_rental_depreciation.py .
```

The rental depreciation script updates each rental property's `depreciation` block, writes `tax_forms/workpapers/rental_depreciation_report.yaml`, and records California depreciation adjustment amounts under `state_adjustments.ca`.

Important rental depreciation paths include:

```yaml
income:
  rentals_royalties_partnerships:
    - depreciation:
        land_value: "200000.00"
        building_basis: "500000.00"
        placed_in_service_date: "2020-06-01"
        federal_recovery_period_years: "27.50"
        federal_method: "straight_line"
        federal_convention: "mid_month"
        federal_current_depreciation: "18181.82"
        current_depreciation: "18181.82"
        ca_building_basis: "500000.00"
        ca_recovery_period_years: "27.50"
        ca_current_depreciation: "18181.82"
state_adjustments:
  ca:
    rental_depreciation_federal_total: "18181.82"
    rental_depreciation_ca_total: "18181.82"
    rental_depreciation_adjustment_total: "0.00"
    rental_depreciation_addition: "0.00"
    rental_depreciation_subtraction: "0.00"
```

Run `scripts/calculate_schedule_e.py` before the general federal calculator when rental or royalty activity is present:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_schedule_e.py .
```

The Schedule E script updates `calculated.form_line_values.f1040se`, writes `tax_forms/workpapers/schedule_e_report.yaml`, and carries Schedule E line 26 to `calculated.form_line_values.f1040s1.line_5_rental_royalty_partnerships_estates_trusts`.

Important Schedule E calculated paths include:

```yaml
calculated:
  form_line_values:
    f1040se:
      part_i:
        properties:
          a:
            line_1a_physical_address: "1 Rental St, Sacramento, CA 95814"
            line_1b_type_of_property: "1"
            line_2_fair_rental_days: "365"
            line_2_personal_use_days: "0"
            line_3_rents_received: "24000.00"
            line_20_total_expenses: "12000.00"
            line_21_income_or_loss: "12000.00"
            line_22_deductible_rental_real_estate_loss_after_limitation: "0.00"
        line_23a_total_rents: "24000.00"
        line_23e_total_expenses: "12000.00"
        line_26_total_rental_real_estate_and_royalty_income_or_loss: "12000.00"
      line_41_total_income_or_loss: "12000.00"
```

When a direct rental has a loss or prior-year unallowed passive loss, run `scripts/calculate_form_8582.py` after Schedule E:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_form_8582.py .
```

The Form 8582 script updates `calculated.form_line_values.f8582`, writes `tax_forms/workpapers/form_8582_report.yaml`, updates Schedule E line 22, and carries the allowed rental result to Schedule 1 line 5.

Important Form 8582 calculated paths include:

```yaml
calculated:
  form_line_values:
    f8582:
      part_i:
        line_1b_active_rental_net_loss: "31000.00"
        line_1d_active_rental_combined: "-31000.00"
        line_3_total_passive_activity_loss: "-31000.00"
      part_ii:
        line_5_phaseout_base: "150000.00"
        line_6_modified_adjusted_gross_income: "120000.00"
        line_8_special_allowance_limit: "15000.00"
        line_9_special_allowance: "15000.00"
      part_iii:
        line_11_total_losses_allowed: "15000.00"
      part_viii:
        activities:
          - name: "rental_001"
            loss: "31000.00"
            unallowed_loss: "16000.00"
            allowed_loss: "15000.00"
```

The Form 8582 script covers the common direct rental real estate active-participation path. PTPs, CRD, passive credits, K-1 activity details, married filing separately with spouse cohabitation, and losses reported on multiple forms remain review/manual workflows.

Run `scripts/calculate_tax_lines.py` after extraction and review:

```bash
python3 /path/to/us-tax-return-prep/scripts/calculate_tax_lines.py .
```

The script updates `calculated.form_line_values` and writes `tax_forms/workpapers/calculation_report.yaml`.

The engine scope is `federal_common_lines_with_ots` when OpenTaxSolver succeeds. The script normalizes extracted wages, interest, dividends, capital gains/losses, withholding, payments, deductions, and selected Schedule 1/Schedule 3 inputs, then writes OTS-derived form-line values and `math_engine` metadata. It still writes review items for missing facts, unsupported schedules, and user decisions.

Run `scripts/calculate_ca_lines.py` after federal calculations when a California resident return is in scope. It writes OTS-backed CA values under `calculated.form_line_values.ca540`, `calculated.form_line_values.ca540ca`, and `calculated.state.ca`. It still requires review for AMT, Behavioral Health Services Tax inputs, use tax, special credits, penalties, and residency allocation unless explicit reviewed values are supplied.

## Itemized Deduction Example

Read `summary.md` first, then `itemized/itemized_intake.md`, then supporting documents in `itemized/`. The intake file is where the user chooses `standard`, `itemized`, or `unsure`. If standard is selected, the remaining Schedule A sections can stay blank unless the user wants comparison or state review. If itemized or unsure is selected, extract source-backed Schedule A facts into `deductions.itemized`.

```yaml
deductions:
  standard_or_itemized: "itemized"
  standard_deduction: unknown
  itemized_deduction_total: unknown
  selected_deduction_amount: unknown
  itemized:
    medical:
      - description: "Unreimbursed medical and dental expenses"
        amount: "3500.00"
        reimbursed_amount: "0.00"
        source_refs:
          - document_id: "itemized_medical_001"
            label: "Medical receipts"
    taxes_paid:
      - type: "real_estate_tax"
        description: "Main home property tax"
        amount: "7200.00"
        source_refs:
          - document_id: "itemized_property_tax_001"
            label: "County property tax bill"
      - type: "state_income_tax_estimated_payment"
        amount: "1000.00"
        payment_date: "2025-06-15"
    interest_paid:
      - type: "home_mortgage_interest"
        payer_name: "Example Bank"
        amount: "18000.00"
        form_1098: true
        points: "0.00"
        source_refs:
          - document_id: "itemized_mortgage_interest_001"
            label: "Form 1098 mortgage interest"
    gifts_to_charity:
      - type: "cash"
        donee: "Example Charity"
        amount: "1200.00"
        goods_or_services_received: "0.00"
      - type: "noncash"
        donee: "Example Thrift"
        amount: "450.00"
        description: "Household goods"
    casualty_theft: []
    other:
      - type: "gambling_losses"
        amount: "500.00"
        limited_to_gambling_winnings: true
  source_refs:
    - document_id: "itemized_intake_001"
      label: "Deduction choice and Schedule A intake"
review_notes:
  - severity: "question"
    topic: "itemized_vs_standard"
    message: "User selected itemized, but the final choice should be reviewed after current-year standard deduction and Schedule A limits are applied."
```

When a California return is in scope and the user itemizes federally or wants a state comparison, populate or review `state_adjustments.ca.itemized_deduction_total` because California itemized deduction rules can differ from federal rules.

## Required IRS Forms Plan

Write inferred federal forms to `tax_forms/required_irs_forms.yaml`, not just to free-text notes.

```yaml
schema_version: "0.1"
tax_year: "2025"
generated_from: "tax_forms/extracted_tax_data.yaml"
forms:
  - form_id: "f1040"
    title: "Form 1040"
    status: "required"
    pdf: "f1040.pdf"
    instruction_pdf: "i1040gi.pdf"
    output_dir: "tax_forms/federal"
    reasons:
      - "Base individual income tax return."
    source_refs: []
  - form_id: "f1040sd"
    title: "Schedule D (Form 1040)"
    status: "required"
    pdf: "f1040sd.pdf"
    instruction_pdf: "i1040sd.pdf"
    output_dir: "tax_forms/federal"
    reasons:
      - "1099-B or brokerage stock trading data is present."
    source_refs:
      - document_id: "1099b_001"
        label: "Form 1099-B"
  - form_id: "f8949"
    title: "Form 8949"
    status: "review"
    pdf: "f8949.pdf"
    instruction_pdf: "i8949.pdf"
    output_dir: "tax_forms/federal"
    reasons:
      - "Capital asset transactions may need transaction-level reporting."
    source_refs:
      - document_id: "1099b_001"
        label: "Form 1099-B"
open_questions: []
```

## Required State Forms Plan

Write inferred state forms to `tax_forms/required_state_forms.yaml`.

```yaml
schema_version: "0.1"
tax_year: "2025"
status: "needs_review"
generated_from: "tax_forms/extracted_tax_data.yaml"
states:
  - state: "CA"
    module: "california_resident"
forms:
  - form_id: "ca540"
    jurisdiction: "CA"
    agency: "California Franchise Tax Board"
    title: "California Form 540"
    status: "required"
    pdf: "2025-540.pdf"
    url: "https://www.ftb.ca.gov/forms/2025/2025-540.pdf"
    instruction_url: "https://www.ftb.ca.gov/forms/2025/2025-540-booklet.html"
    output_dir: "tax_forms/state/ca"
    blank_dir: "tax_forms/workpapers/blank_forms/ca"
    field_map_dir: "tax_forms/workpapers/field_maps/ca"
    reasons:
      - "California indicators are present; Form 540 is used for California full-year resident individual returns."
    source_refs: []
open_questions:
  - "Confirm California residency status."
```

Use `status: required` when the form is clearly indicated. Use `status: review` when the form depends on thresholds, exceptions, or user elections.

## Source Document Entry

```yaml
- id: "w2_001"
  type: "W-2"
  file: "Acme_W2_2025.pdf"
  tax_year: "2025"
  issuer: "Acme Inc."
  recipient: "Taxpayer Name"
  extraction_method: "pdf_text"
  confidence: "medium"
  notes: []
```

## Source Reference

Use source references anywhere a number is extracted or calculated.

```yaml
source_refs:
  - document_id: "w2_001"
    label: "Box 1"
    page: 1
    extracted_text: "Wages, tips, other compensation 12345.67"
```

Keep `extracted_text` short. Do not duplicate entire documents.

## W-2 Example

```yaml
income:
  wages:
    - source_document_id: "w2_001"
      employer_name: "Acme Inc."
      employer_ein: "12-3456789"
      wages_box_1: "12345.67"
      federal_income_tax_withheld_box_2: "1234.56"
      social_security_wages_box_3: "12345.67"
      social_security_tax_withheld_box_4: "765.43"
      medicare_wages_box_5: "12345.67"
      medicare_tax_withheld_box_6: "178.90"
      box_12:
        - code: "D"
          amount: "500.00"
      box_14:
        - label: "CASDI"
          amount: "123.45"
      state_items:
        - state: "CA"
          employer_state_id: "123-4567-8"
          state_wages_box_16: "12345.67"
          state_income_tax_box_17: "456.78"
      source_refs:
        - document_id: "w2_001"
          label: "Boxes 1-6"
          page: 1
```

## 1099 Example

```yaml
income:
  interest:
    - source_document_id: "1099int_001"
      payer_name: "Example Bank"
      interest_income_box_1: "25.00"
      federal_income_tax_withheld_box_4: "0.00"
      tax_exempt_interest_box_8: "0.00"
      source_refs:
        - document_id: "1099int_001"
          label: "1099-INT boxes 1, 4, 8"
          page: 1
```

## Rental Property Example

Use one `income.rentals_royalties_partnerships` entry per rental property. Read `summary.md` first, then `rental/rental_intake.md`, then supporting documents in `rental/`. Generated extraction notes belong under `tax_forms/workpapers/`, not in `rental/`.

```yaml
income:
  rentals_royalties_partnerships:
    - activity_type: "rental"
      property_id: "rental_001"
      property_description: "Single family home"
      property_address:
        line1: "1 Rental St"
        city: "Sacramento"
        state: "CA"
        zip: "95814"
      ownership_percentage: "100"
      placed_in_service_date: "2020-06-01"
      days_rented: "365"
      personal_use_days: "0"
      fair_rental_days: "365"
      active_participation: true
      material_participation: false
      gross_rents: "24000.00"
      other_rental_income: "0.00"
      expenses:
        advertising: "0.00"
        auto_and_travel: "0.00"
        cleaning_and_maintenance: "1200.00"
        commissions: "0.00"
        insurance: "900.00"
        legal_and_professional: "0.00"
        management_fees: "1800.00"
        mortgage_interest: "8000.00"
        other_interest: "0.00"
        repairs: "1500.00"
        supplies: "250.00"
        real_estate_taxes: "3600.00"
        utilities: "600.00"
        hoa_dues: "1200.00"
        other: []
      depreciation:
        original_purchase_date: "2020-05-15"
        original_purchase_price: "700000.00"
        fair_market_value_at_conversion: unknown
        land_value: "200000.00"
        building_basis: "500000.00"
        land_building_split_source: "county assessment"
        federal_recovery_period_years: "27.5"
        federal_method: "straight_line"
        federal_convention: "mid_month"
        prior_depreciation: "45000.00"
        federal_current_depreciation: unknown
        current_depreciation: unknown
        ca_building_basis: unknown
        ca_prior_depreciation: unknown
        ca_recovery_period_years: unknown
        ca_current_depreciation: unknown
        assets: []
      passive_activity:
        active_participation: true
        prior_year_unallowed_loss: unknown
        prior_year_unallowed_loss_source: "prior-year Form 8582 activity worksheet"
        ca_prior_year_unallowed_loss: unknown
        current_year_allowed_loss: unknown
        current_year_unallowed_loss: unknown
      income_loss: unknown
      confidence: "medium"
      source_refs:
        - document_id: "rental_intake_001"
          label: "Rental intake property facts"
        - document_id: "rental_property_tax_001"
          label: "Real estate taxes"
        - document_id: "prior_return_2024"
          label: "Prior-year Form 8582 activity worksheet suspended loss"
```

Core Schedule E facts are property address, gross rents, rental/personal-use days, expenses or a reviewed net income/loss amount, depreciation facts when applicable, passive-activity facts when losses may be limited, and source references for material numbers.

When extracting `passive_activity.prior_year_unallowed_loss`, prefer prior-year Form 8582 activity worksheets or passive-loss statements. Do not use a prior-year Schedule E loss as the carryover unless a Form 8582 worksheet or equivalent preparer statement shows that the amount was suspended and carried forward for the matched rental activity.

## Review Notes

Use structured review notes for anything blocking confidence:

```yaml
review_notes:
  - severity: "question"
    topic: "filing_status"
    message: "summary.md says Head of Household, prior-year return used Single."
    source_refs:
      - document_id: "summary"
        label: "filing status"
      - document_id: "prior_return_001"
        label: "Form 1040 filing status"
```
