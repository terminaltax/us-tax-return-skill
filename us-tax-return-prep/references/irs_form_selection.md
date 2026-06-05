# IRS Form Selection

Use this reference when mapping extracted data and document types to federal forms. The rules are conservative prompts for preparation, not substitutes for current IRS instructions.

## Required Forms Plan

Run `scripts/infer_required_irs_forms.py` after extraction. It writes `tax_forms/required_irs_forms.yaml`.

Use these statuses:

- `required`: clearly indicated by the source documents or extracted data.
- `review`: may be needed depending on thresholds, exceptions, current-year instructions, or user elections.
- `not_needed`: explicitly ruled out after review.

## Common Individual Forms

| Trigger | Form to include |
| --- | --- |
| Any individual federal return | Form 1040 |
| Additional income or adjustments that flow through Schedule 1 | Schedule 1 |
| Additional taxes that flow through Schedule 2 | Schedule 2 |
| Nonrefundable credits or other payments that flow through Schedule 3 | Schedule 3 |
| Itemized deductions | Schedule A |
| Interest/dividend reporting above thresholds or foreign account questions | Schedule B |
| Sole proprietor, gig, freelance, or 1099-NEC business activity | Schedule C |
| Net earnings from self-employment | Schedule SE |
| Capital gains/losses, 1099-B, 1099-DA, brokerage trades, crypto sales | Schedule D |
| Transaction-level capital asset reporting | Form 8949 |
| Rental, royalty, partnership, S corporation, estate, or trust income | Schedule E |
| Child tax credit or credit for other dependents | Schedule 8812 |
| Education credits | Form 8863 |
| HSA contributions or distributions | Form 8889 |
| Premium tax credit or 1095-A | Form 8962 |
| Foreign tax credit | Form 1116 or Schedule 3 review |
| Qualified business income deduction | Form 8995 or Form 8995-A review |
| Early retirement distributions or excess contributions | Form 5329 review |
| Nondeductible IRA basis or Roth conversions | Form 8606 review |
| Home office deduction for Schedule C | Form 8829 review |
| Depreciation or amortization | Form 4562 review |

## Stock Trading Example

If a source packet includes a 1099-B or brokerage realized-gain statement, include:

- Schedule D (`f1040sd`) as `required`
- Form 8949 (`f8949`) as `review`, upgraded to `required` when detailed transactions, noncovered basis, adjustments, wash sales, code entries, or transactions not summarized on Schedule D lines 1a or 8a are present

The 2025 Schedule D PDF itself says to use Form 8949 for listed transaction lines, so review that dependency when stock trading data is present.

## Download Plan

The downloader uses IRS PDF filenames, such as:

- `f1040.pdf`
- `f1040sd.pdf`
- `f8949.pdf`

For current IRS forms, use `https://www.irs.gov/pub/irs-pdf/<filename>`. For a specific prior-year archive, use `https://www.irs.gov/pub/irs-prior/<stem>--<tax_year>.pdf` when available.

Always verify that the downloaded PDF is the intended tax year before filling it.
