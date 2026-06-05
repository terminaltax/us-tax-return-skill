# Form Filling Guidance

Use this reference when turning reviewed YAML into draft tax form PDFs.

## Official Sources

Use official current-year sources:

- Federal forms and instructions: IRS pages on `irs.gov`
- State forms and instructions: the state's official department of revenue, taxation, or franchise tax board site

Do not use third-party tax summaries as authority for form calculations. They can help locate issues, but official instructions control.

## Form Acquisition

Download blank PDFs into `tax_forms/workpapers/blank_forms/` or use user-provided blank forms. Record source URLs and download dates in `tax_forms/workpapers/form_sources.md`.

Use tax-year-specific forms. For example, a 2025 return should use 2025 Form 1040 and 2025 schedules unless official instructions require otherwise.

## Field Mapping

Before filling a PDF:

1. Inspect fillable field names.
2. Create a field map under `tax_forms/workpapers/field_maps/`, such as `f1040_field_map.yaml` or `2025_f1040_field_map.yaml`.
3. Map each PDF field to a YAML path or calculated form line.
4. Mark unmapped required fields for review.

Keep field maps separate from extracted data. Field names vary across IRS revisions and should not be embedded in `SKILL.md`.

Generate a skeleton field map from a downloaded blank PDF:

```bash
python3 /path/to/us-tax-return-prep/scripts/inspect_pdf_fields.py tax_forms/workpapers/blank_forms/irs/f1040.pdf --form-id f1040 --tax-year 2025 --output tax_forms/workpapers/field_maps/f1040_field_map.yaml
```

The generated skeleton includes `semantic_path_suggestions` from `assets/field_maps/federal/semantic_field_library.yaml` when the form is covered. Use those suggestions to connect current PDF field names to stable YAML paths, then run `validate_tax_data.py`.

For California forms, use the CA semantic library and CA field-map directory. The script chooses `assets/field_maps/ca/semantic_field_library.yaml` automatically for form ids beginning with `ca`:

```bash
python3 /path/to/us-tax-return-prep/scripts/inspect_pdf_fields.py tax_forms/workpapers/blank_forms/ca/2025-540.pdf --form-id ca540 --tax-year 2025 --output tax_forms/workpapers/field_maps/ca/ca540_field_map.yaml
```

Generate skeleton maps for every required form in `required_irs_forms.yaml`:

```bash
python3 /path/to/us-tax-return-prep/scripts/inspect_pdf_fields.py . --from-plan
```

Schedule E has a dedicated default field-map generator for the current fillable IRS `f1040se.pdf` field names:

```bash
python3 /path/to/us-tax-return-prep/scripts/generate_schedule_e_field_map.py . --tax-year 2025
```

This map fills Schedule E Part I property columns, line 23 totals, line 26, and page 2 line 41 from `calculated.form_line_values.f1040se`. Run `validate_tax_data.py` against the downloaded blank PDF after generating it.

Form 8582 also has a dedicated field-map generator for the common direct-rental passive loss path:

```bash
python3 /path/to/us-tax-return-prep/scripts/generate_form_8582_field_map.py . --tax-year 2025
```

This map fills Form 8582 Parts I-IV and VI-VIII from `calculated.form_line_values.f8582`. Parts V and IX remain manual/agent review areas for non-rental passive activities, PTPs, CRD, K-1 activity details, and losses reported on multiple forms.

## Regenerate Tax PDFs

Use `regenerate-tax-pdfs` as a standalone workflow when the user has edited `tax_forms/extracted_tax_data.yaml` by hand and wants PDFs regenerated without re-running extraction or form inference.

Run:

```bash
python3 /path/to/us-tax-return-prep/scripts/regenerate_tax_pdfs.py .
```

The script uses:

- `tax_forms/extracted_tax_data.yaml`
- `tax_forms/required_irs_forms.yaml`
- `tax_forms/required_state_forms.yaml` when `--forms-plan tax_forms/required_state_forms.yaml` is supplied
- `tax_forms/workpapers/blank_forms/irs/*.pdf`
- `tax_forms/workpapers/blank_forms/ca/*.pdf` for California state plans
- `tax_forms/workpapers/field_maps/*_field_map.yaml`
- `tax_forms/workpapers/field_maps/ca/*_field_map.yaml` for California state plans

It writes filled PDFs to each form's `output_dir` and a manifest to `tax_forms/workpapers/filled_pdf_manifest.yaml`.

State form plans can include per-form `blank_dir` and `field_map_dir` values. `regenerate_tax_pdfs.py`, `validate_tax_data.py`, and `inspect_pdf_fields.py --from-plan` honor those values, so a California plan can use `tax_forms/workpapers/blank_forms/ca/` and `tax_forms/workpapers/field_maps/ca/` without changing federal defaults.

## Field Map Schema

Create one field map per PDF. Candidate filenames are checked in this order:

- `<tax_year>_<form_id>_field_map.yaml`
- `<form_id>_field_map.yaml`
- `<tax_year>_<pdf_stem>_field_map.yaml`
- `<pdf_stem>_field_map.yaml`

Example:

```yaml
schema_version: "0.1"
form_id: "f1040"
pdf: "f1040.pdf"
output_pdf: "2025_f1040_draft.pdf"
fields:
  "topmostSubform[0].Page1[0].f1_01[0]":
    path: "taxpayer.primary.full_name"
    required: true
  "topmostSubform[0].Page1[0].f1_02[0]":
    template: "{taxpayer.address.line1}, {taxpayer.address.city}, {taxpayer.address.state} {taxpayer.address.zip}"
  "topmostSubform[0].Page1[0].c1_1[0]":
    path: "taxpayer.filing_status"
    type: "checkbox"
    checked_value: "/1"
    unchecked_value: "/Off"
  "topmostSubform[0].Page1[0].f1_10[0]":
    path: "calculated.form_line_values.f1040.line_1a"
    format: "money_whole_dollars"
```

Supported value specs:

- `path`: resolve a value from `extracted_tax_data.yaml`.
- `value`: constant value.
- `template`: deterministic string interpolation with `{yaml.path}` placeholders.
- `join`: join several YAML paths with a separator.
- `sum`: sum numeric values from paths, including wildcard paths like `income.wages[].wages_box_1`.

Supported formats:

- `text`
- `money`
- `money_whole_dollars`
- `integer`
- `date_mmddyyyy`
- `digits`
- `ssn_last4`

Checkboxes require `type: "checkbox"` or `checkbox: true`. Use the PDF's actual checked export value when known; otherwise the script defaults to `/Yes`.

## Filling Rules

- Fill only from reviewed YAML and documented calculations.
- Preserve money formatting expected by the form.
- Use checkboxes exactly as the PDF expects.
- Leave unknown fields blank and record them in `review_notes.md`.
- Do not flatten PDFs unless the user requests final printable copies.
- Add `_draft` to generated file names.

## Quality Checks

After filling:

- Re-open or inspect the filled PDF fields.
- Compare key totals back to `extracted_tax_data.yaml`.
- Confirm every filled form line has a source or calculation reference.
- Confirm generated PDFs are under `tax_forms/federal/` or `tax_forms/state/`.
- Report unresolved blanks and assumptions.

## Non-Fillable PDFs

If a PDF is not fillable, prefer producing a line-by-line workpaper instead of drawing text overlays. Use overlay-based PDF generation only when the user explicitly wants printable drafts and understands the higher risk of alignment errors.
