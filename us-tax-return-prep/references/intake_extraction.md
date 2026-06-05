# Intake And Extraction

Use this reference when classifying documents and extracting values into `extracted_tax_data.yaml`.

## Intake Order

1. Read `summary.md`.
2. Read `itemized/itemized_intake.md` when present.
3. Read `rental/rental_intake.md` when present.
4. Read prior-year returns.
5. Read current-year source forms.
6. Compare current-year forms against prior-year forms to identify missing recurring items.
7. Record extracted values and inferred missing items in YAML.

## `summary.md`

Extract user-provided facts that source forms may not contain:

- taxpayer and spouse names
- SSNs or last four digits
- address
- filing status
- dependents and relationship facts
- state residency and moves
- estimated tax payments
- extension payments
- charitable contributions or itemized deductions not shown on forms
- business, rental, or crypto activity not obvious from source forms
- foreign accounts, foreign tax, or foreign income facts

Mark summary facts as user-provided. If a source form conflicts with `summary.md`, do not silently resolve the conflict.

## `itemized/itemized_intake.md`

Use the root-level itemized intake file at the beginning of extraction to capture the user's deduction choice and Schedule A facts:

- standard, itemized, or unsure deduction choice
- whether to extract itemized documents for comparison or state review even when standard is selected
- unreimbursed medical and dental expenses
- state and local income taxes paid outside withholding, prior-year balance payments, estimated payments, real estate taxes, and personal property taxes
- home mortgage interest, points, mortgage insurance when shown, home equity interest use, and investment interest
- cash and noncash charitable gifts, volunteer expenses, charitable mileage, and charitable carryovers
- casualty or theft losses tied to federally declared disasters
- other Schedule A items, such as gambling losses up to gambling winnings
- California or state-specific deduction differences

Treat the Markdown answers as user-provided facts. Use supporting documents in `itemized/` to source material numbers when available. If the user chooses `standard`, populate `deductions.standard_or_itemized` and skip Schedule A extraction unless comparison or state review is requested. If answers conflict with supporting documents, add a review note instead of silently resolving the conflict.

## `rental/rental_intake.md`

Use the root-level rental intake file for Schedule E facts that are usually not fully captured on tax forms:

- property address, ownership, placed-in-service date, and property type
- rental days, personal-use days, fair-rental days, and vacancy facts
- gross rents, other rental income, and security deposits kept as income
- Schedule E expense categories
- repair versus improvement notes
- depreciation basis, prior depreciation, and current depreciation schedules
- active participation, material participation, and passive-loss carryovers
- document references for property tax, mortgage interest, insurance, HOA, repairs, utilities, lease/rent ledger, depreciation, and closing statements

Treat the Markdown answers as user-provided facts. Use supporting documents in `rental/` to source material numbers when available. Generated extraction notes belong under `tax_forms/workpapers/`.

## Classification Markers

Use document content first, filename second. Add a stable `type` to each source document.

| Type | Markers |
| --- | --- |
| `summary` | file named `summary.md` |
| `W-2` | "Wage and Tax Statement", "Form W-2", boxes 1 through 20 |
| `1099-INT` | "Interest Income", "Form 1099-INT" |
| `1099-DIV` | "Dividends and Distributions", "Form 1099-DIV" |
| `1099-B` | "Proceeds From Broker", "Form 1099-B", "covered securities", "wash sale" |
| `1099-DA` | "Digital Asset", "Form 1099-DA" |
| `1099-R` | "Distributions From Pensions", "Form 1099-R" |
| `1099-NEC` | "Nonemployee Compensation", "Form 1099-NEC" |
| `1099-MISC` | "Miscellaneous Information", rents, royalties, other income |
| `1099-K` | "Payment Card and Third Party Network Transactions" |
| `SSA-1099` | "Social Security Benefit Statement" |
| `1098` | "Mortgage Interest Statement" |
| `1098-E` | "Student Loan Interest Statement" |
| `1098-T` | "Tuition Statement" |
| `1095-A` | "Health Insurance Marketplace Statement" |
| `K-1` | "Schedule K-1", partnership, S corporation, estate, or trust |
| `brokerage_statement` | consolidated tax statement, realized gain/loss, 1099 composite |
| `prior_return` | prior-year Form 1040, state return, tax return transcript |
| `itemized_intake` | `itemized/itemized_intake.md` |
| `itemized_medical` | itemized folder medical, dental, doctor, hospital, pharmacy, or prescription records |
| `itemized_property_tax` | itemized folder property tax or real estate tax bill |
| `itemized_mortgage_interest` | itemized folder mortgage interest, Form 1098, or points |
| `itemized_charity_cash` | itemized folder cash/check/card/payroll charitable donation receipt |
| `itemized_charity_noncash` | itemized folder noncash donation receipt or donated goods record |
| `itemized_state_tax` | itemized folder state tax, estimated tax, extension, or prior-year balance payment |
| `itemized_vehicle_tax` | itemized folder DMV or vehicle registration bill with deductible tax portion |
| `itemized_casualty` | itemized folder casualty, theft, FEMA, or federally declared disaster record |
| `itemized_investment_interest` | itemized folder investment or margin interest expense |
| `rental_intake` | `rental/rental_intake.md` |
| `rental_property_tax` | rental folder property tax or real estate tax bill |
| `rental_mortgage_interest` | rental folder mortgage interest or Form 1098 |
| `rental_insurance` | rental folder landlord/property insurance |
| `rental_hoa` | rental folder HOA or homeowner association statement |
| `rental_repairs` | rental folder repair, maintenance, or invoice |
| `rental_utilities` | rental folder utility, electric, water, or gas bill |
| `rental_lease_or_ledger` | rental folder lease, rent ledger, rent roll |
| `rental_depreciation` | rental folder depreciation or asset schedule |
| `rental_closing_statement` | rental folder closing, settlement, HUD-1, or ALTA statement |

## Extraction Workpapers

For each nontrivial source document, place supporting extracted text or notes under `tax_forms/workpapers/`, named with the document id. Keep snippets short and relevant.

## Stock Trading And Capital Assets

When a packet includes 1099-B, 1099-DA, brokerage realized gain/loss statements, stock sale summaries, crypto sales, or capital gain/loss carryovers:

- populate `income.capital_gains`
- preserve short-term vs long-term classification
- preserve covered vs noncovered status when shown
- preserve proceeds, cost basis, wash-sale adjustments, and other adjustment codes
- infer Schedule D
- infer Form 8949 as `required` or `review` depending on whether transaction-level reporting appears necessary

Do not net capital transactions without preserving source subtotals.

## Prior-Year Return Comparison

Use prior-year returns to identify likely missing current-year documents:

- Schedule B last year but no current interest/dividend forms
- Schedule D last year but no current brokerage or 1099-B documents
- Schedule C/E/F last year but no current business, rental, farm, or K-1 materials
- Form 8889 last year but no current HSA forms
- Form 8962 last year but no current 1095-A

Add missing items to `open_questions` rather than assuming they continued.

## Prior-Year Rental Passive Loss Carryovers

When a complete prior-year return is available, use it to extract passive-loss carryovers for rental properties. Do this before asking the user for a manually entered carryover.

Read prior-year documents in this order:

1. Prior-year Form 8582.
2. Form 8582 activity worksheets or statements.
3. Prior-year Schedule E.
4. Prior-year depreciation schedules or Form 4562.
5. Prior-year state passive-loss or depreciation schedules, when state return preparation is in scope.

Extraction rules:

- Extract activity-level carryovers, not just the total Form 8582 loss.
- Match prior-year activities to current-year rentals by property address first, then property nickname/activity name, Schedule E property column, and ownership facts.
- Store the matched federal carryover at `income.rentals_royalties_partnerships[].passive_activity.prior_year_unallowed_loss`.
- Store a state-specific California carryover at `income.rentals_royalties_partnerships[].passive_activity.ca_prior_year_unallowed_loss` when a California schedule or worksheet shows a different amount.
- Attach `source_refs` to the prior-year Form 8582 line, worksheet row, or passive-activity statement that supports the number.
- If Form 8582 shows an aggregate total but no activity-level worksheet, do not allocate by assumption. Add a review note.
- If only Schedule E is available, do not treat its prior-year loss as the carryover. Schedule E identifies rental loss/income, but Form 8582 or a passive-loss worksheet is needed to identify the suspended loss carried forward.
- If the property was sold, converted, newly acquired, or no longer matches the current rental facts, add a review note before using the carryover.
