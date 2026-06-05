# Field Maps

Create one field map per fillable PDF. The script checks candidate filenames in this order:

- `<tax_year>_<form_id>_field_map.yaml`
- `<form_id>_field_map.yaml`
- `<tax_year>_<pdf_stem>_field_map.yaml`
- `<pdf_stem>_field_map.yaml`

Federal field maps usually live in `tax_forms/workpapers/field_maps/`. State plans may use form-specific directories such as `tax_forms/workpapers/field_maps/ca/`; `regenerate_tax_pdfs.py` honors a form plan entry's `field_map_dir` and `blank_dir` when present.

## Example

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
    value: true
    type: "checkbox"
    checked_value: "/1"
    unchecked_value: "/Off"
  "topmostSubform[0].Page1[0].f1_10[0]":
    sum:
      - "income.wages[].wages_box_1"
    format: "money_whole_dollars"
```

## Value Specs

- `path`: resolve a value from `extracted_tax_data.yaml`.
- `value`: constant value.
- `template`: deterministic string interpolation with `{yaml.path}` placeholders.
- `join`: join several YAML paths with a separator.
- `sum`: sum numeric values from paths, including wildcard paths such as `income.wages[].wages_box_1`.

## Formats

- `text`
- `money`
- `money_whole_dollars`
- `integer`
- `date_mmddyyyy`
- `digits`
- `ssn_last4`

Checkboxes require `type: "checkbox"` or `checkbox: true`. Use the PDF's actual checked export value when known; otherwise the script defaults to `/Yes`.
