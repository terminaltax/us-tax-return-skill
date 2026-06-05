---
name: regenerate-tax-pdfs
description: Deterministically regenerate filled US tax return PDF drafts from an edited extracted_tax_data.yaml file, required_irs_forms.yaml plan, blank fillable PDFs, and explicit field-map YAML files. Use when the user has already extracted or corrected tax data by hand and wants to recreate filled federal or state tax PDFs without re-running document extraction, form inference, or tax calculations.
---

# Regenerate Tax PDFs

## Overview

Regenerate filled tax PDF drafts from reviewed YAML and field maps. This skill is the standalone form-filling step from `us-tax-return-prep`; it does not extract source documents, infer required forms, calculate tax, download forms, or choose elections.

Use `scripts/regenerate_tax_pdfs.py` for deterministic execution.

## Inputs

Expect a tax packet folder containing:

```text
tax_forms/
  extracted_tax_data.yaml
  required_irs_forms.yaml
  required_state_forms.yaml
  workpapers/
    blank_forms/
      irs/
        f1040.pdf
        f1040se.pdf
        f8582.pdf
      ca/
        2025-540.pdf
    field_maps/
      f1040_field_map.yaml
      f1040se_field_map.yaml
      f8582_field_map.yaml
      ca/
        ca540_field_map.yaml
```

Field maps are required because IRS and state PDF field names are not stable or semantic. Read `references/field_maps.md` before editing or creating a map.

## Workflow

1. Confirm `tax_forms/extracted_tax_data.yaml` is the reviewed data source.
2. Confirm blank fillable PDFs exist under `tax_forms/workpapers/blank_forms/irs/`, `tax_forms/workpapers/blank_forms/ca/`, or provide `--blank-dir`.
3. Confirm each form to fill has a matching field map under `tax_forms/workpapers/field_maps/` or a form-specific directory such as `tax_forms/workpapers/field_maps/ca/`.
4. Run:

```bash
python3 /path/to/regenerate-tax-pdfs/scripts/regenerate_tax_pdfs.py .
```

5. Review `tax_forms/workpapers/filled_pdf_manifest.yaml`.
6. Re-open the generated PDFs and spot-check filled fields against the YAML.

Use `--form f1040` to regenerate only one form. Use `--include-review` to include forms marked `status: review` in `required_irs_forms.yaml`.

Use `--forms-plan tax_forms/required_state_forms.yaml` to regenerate state forms. State plan entries can include `blank_dir` and `field_map_dir`, which the script honors for forms such as California Form 540.

Schedule E can be regenerated when `calculated.form_line_values.f1040se` contains reviewed/calculated Schedule E lines and `tax_forms/workpapers/field_maps/f1040se_field_map.yaml` maps the current IRS `f1040se.pdf` fields. The companion `us-tax-return-prep` skill includes `scripts/calculate_schedule_e.py` and `scripts/generate_schedule_e_field_map.py` for that upstream calculation and map generation.

Form 8582 can be regenerated when `calculated.form_line_values.f8582` contains reviewed/calculated passive-loss limitation lines and `tax_forms/workpapers/field_maps/f8582_field_map.yaml` maps the current IRS `f8582.pdf` fields. The companion `us-tax-return-prep` skill includes `scripts/calculate_form_8582.py` and `scripts/generate_form_8582_field_map.py` for that upstream calculation and map generation.

## Output

The script writes:

- filled PDFs under each form's `output_dir`, usually `tax_forms/federal/` or `tax_forms/state/ca/`
- `tax_forms/workpapers/filled_pdf_manifest.yaml`

If a blank PDF, field map, required value, or PDF field name is missing, the script records the issue in the manifest and exits nonzero unless the relevant `--allow-*` option is used.

## Boundaries

- Do not infer missing values.
- Do not calculate tax.
- Do not alter source documents.
- Do not treat generated PDFs as final filed returns.
- Keep full SSNs and other sensitive identifiers in local files only; do not paste them in chat.
