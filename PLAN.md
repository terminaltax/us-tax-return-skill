# Rental Intake UX Plan

## Summary

Add a root-level `rental/` intake area created during workspace setup. It contains `rental_intake.md`, a user-editable Schedule E-ready questionnaire. Users can also place supporting rental documents in `rental/`, such as property tax bills, mortgage interest statements, insurance bills, HOA statements, repair invoices, lease records, and depreciation records.

Extraction remains agent-assisted for v1: Codex reads `rental/rental_intake.md` plus supporting docs, then updates `tax_forms/extracted_tax_data.yaml` with rental data and source references.

## Tracker

- [x] Confirm current repo has no `PLAN.md`.
- [x] Confirm current workspace setup skips `tax_forms/` but will include root `rental/` docs.
- [x] Choose root `rental/` folder.
- [x] Choose one repeatable `rental/rental_intake.md` template.
- [x] Choose Schedule E-ready question depth.
- [x] Choose agent-assisted extraction instead of deterministic Markdown parser for v1.
- [x] Create `PLAN.md` with this tracker.
- [x] Update workspace setup to create `rental/` and `rental/rental_intake.md`.
- [x] Update source document classification for common rental documents.
- [x] Extend schema/docs for rental properties and supporting source refs.
- [x] Add validation/review checks for incomplete rental data.
- [x] Add tests for setup, manifest inclusion, rental doc classification, and rental extraction guidance.
- [ ] Implement deterministic Schedule E calculations.
- [ ] Implement deterministic Markdown-to-YAML parsing if agent-assisted extraction proves too manual.

## Key Changes

- `prepare_tax_workspace.py` creates `rental/` and `rental/rental_intake.md`.
- `rental/rental_intake.md` asks Schedule E-ready questions for each property: address, ownership, rental use, income, expenses, repairs vs improvements, depreciation, passive activity, carryovers, documents, and open questions.
- User-provided rental source documents live in `rental/`; generated extraction notes stay under `tax_forms/workpapers/`.
- The source manifest recognizes common rental documents only when they are in the rental intake area.
- `tax_data_schema.md` documents one YAML entry per rental property under `income.rentals_royalties_partnerships[]`.
- `validate_tax_data.py` warns when rental entries are missing core Schedule E facts or source references.

## UX Behavior

- After setup, the user sees `rental/rental_intake.md` immediately, even if they may not have rental income.
- The template tells users to leave unknown fields blank or write `unknown`.
- Users can add more property sections by copying the provided Rental Property block.
- Codex reads `summary.md` first, then `rental/rental_intake.md`, then supporting docs in `rental/`.
- If questionnaire answers conflict with source docs, Codex records a review note instead of silently resolving the conflict.
- If rental activity is detected but rental facts are incomplete, validation flags the missing facts before Schedule E can be trusted.

## Test Plan

- Workspace setup creates `rental/` and `rental/rental_intake.md`.
- Files under root `rental/` are included in `tax_forms/source_manifest.yaml`.
- Rental source filenames classify as property tax, mortgage interest, insurance, HOA, repairs, utilities, lease/rent ledger, depreciation schedule, or closing statement.
- Schema/reference docs include the rental property YAML shape.
- Validation warns when a rental entry is missing core Schedule E facts.
- Existing tests continue to pass.

## Assumptions

- v1 does not include a deterministic Markdown parser.
- v1 supports agent-assisted extraction into YAML with source references.
- The folder is named exactly `rental/`, singular, at the tax packet root.
- The questionnaire file is named exactly `rental/rental_intake.md`.

# Itemized Deduction Intake UX Plan

## Summary

Add a root-level `itemized/` intake area created during workspace setup. It contains `itemized_intake.md`, a user-editable beginning-of-workflow questionnaire where the user chooses `standard`, `itemized`, or `unsure`. If the user itemizes or wants a comparison, they can fill Schedule A-ready questions and place supporting documents in `itemized/`.

Extraction remains agent-assisted for v1: Codex reads `summary.md`, then `itemized/itemized_intake.md`, then supporting itemized deduction documents, and updates `tax_forms/extracted_tax_data.yaml` with deduction choice, Schedule A categories, source references, and review notes.

## Tracker

- [x] Add root `itemized/` folder creation.
- [x] Add `itemized/itemized_intake.md` questionnaire.
- [x] Ask for standard / itemized / unsure at the beginning of the questionnaire.
- [x] Allow users to leave Schedule A sections blank when standard is selected.
- [x] Add common itemized deduction document classification.
- [x] Extend skill and intake extraction guidance.
- [x] Extend schema docs for itemized deduction shape and California review.
- [x] Add validation warning for missing deduction choice or incomplete itemized data.
- [x] Add tests for setup, manifest inclusion, classification, schema docs, and validation.
- [x] Add deterministic Schedule A calculations and PDF filling when that scope is prioritized.

## Key Changes

- `prepare_tax_workspace.py` creates `itemized/` and `itemized/itemized_intake.md`.
- The questionnaire collects medical, tax, mortgage interest, charitable, casualty/theft, other Schedule A, and California/state difference facts.
- User-provided itemized deduction source documents live in `itemized/`; generated extraction notes stay under `tax_forms/workpapers/`.
- The source manifest recognizes common itemized documents only when they are in the itemized intake area.
- `validate_tax_data.py` flags an unknown deduction choice and selected-but-empty itemized data.

## UX Behavior

- After setup, the user sees `itemized/itemized_intake.md` immediately.
- The first actionable choice is `standard`, `itemized`, or `unsure`.
- If standard is selected, Codex can skip Schedule A extraction unless comparison or state review is requested.
- If itemized or unsure is selected, Codex extracts from the questionnaire and supporting docs in `itemized/`.
- If questionnaire answers conflict with source docs, Codex records a review note instead of silently resolving the conflict.

## Test Plan

- Workspace setup creates `itemized/` and `itemized/itemized_intake.md`.
- Files under root `itemized/` are included in `tax_forms/source_manifest.yaml`.
- Itemized source filenames classify as medical, property tax, mortgage interest, cash charity, noncash charity, state tax, vehicle tax, casualty, or investment interest.
- Schema/reference docs include the itemized deduction YAML shape.
- Validation warns when itemized is selected but no Schedule A facts are populated.
