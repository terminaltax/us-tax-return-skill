#!/usr/bin/env python3
"""Infer federal IRS forms indicated by extracted tax data."""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


FORM_ORDER = [
    "f1040",
    "f1040s1",
    "f1040s2",
    "f1040s3",
    "f1040sa",
    "f1040sb",
    "f1040sc",
    "f1040sse",
    "f1040sd",
    "f8949",
    "f1040se",
    "f8582",
    "f1040s8",
    "f2441",
    "f8863",
    "f8889",
    "f8962",
    "f1116",
    "f8995",
    "f8995a",
    "f5329",
    "f8606",
    "f8829",
    "f4562",
]

FORM_CATALOG = {
    "f1040": ("Form 1040", "f1040.pdf", "i1040gi.pdf"),
    "f1040s1": ("Schedule 1 (Form 1040)", "f1040s1.pdf", "i1040gi.pdf"),
    "f1040s2": ("Schedule 2 (Form 1040)", "f1040s2.pdf", "i1040gi.pdf"),
    "f1040s3": ("Schedule 3 (Form 1040)", "f1040s3.pdf", "i1040gi.pdf"),
    "f1040sa": ("Schedule A (Form 1040)", "f1040sa.pdf", None),
    "f1040sb": ("Schedule B (Form 1040)", "f1040sb.pdf", None),
    "f1040sc": ("Schedule C (Form 1040)", "f1040sc.pdf", None),
    "f1040sse": ("Schedule SE (Form 1040)", "f1040sse.pdf", "i1040sse.pdf"),
    "f1040sd": ("Schedule D (Form 1040)", "f1040sd.pdf", "i1040sd.pdf"),
    "f8949": ("Form 8949", "f8949.pdf", "i8949.pdf"),
    "f1040se": ("Schedule E (Form 1040)", "f1040se.pdf", None),
    "f8582": ("Form 8582", "f8582.pdf", "i8582.pdf"),
    "f1040s8": ("Schedule 8812 (Form 1040)", "f1040s8.pdf", "i1040s8.pdf"),
    "f2441": ("Form 2441", "f2441.pdf", "i2441.pdf"),
    "f8863": ("Form 8863", "f8863.pdf", "i8863.pdf"),
    "f8889": ("Form 8889", "f8889.pdf", "i8889.pdf"),
    "f8962": ("Form 8962", "f8962.pdf", "i8962.pdf"),
    "f1116": ("Form 1116", "f1116.pdf", "i1116.pdf"),
    "f8995": ("Form 8995", "f8995.pdf", None),
    "f8995a": ("Form 8995-A", "f8995a.pdf", None),
    "f5329": ("Form 5329", "f5329.pdf", "i5329.pdf"),
    "f8606": ("Form 8606", "f8606.pdf", "i8606.pdf"),
    "f8829": ("Form 8829", "f8829.pdf", "i8829.pdf"),
    "f4562": ("Form 4562", "f4562.pdf", "i4562.pdf"),
}

REQUIRED_RANK = {"not_needed": 0, "review": 1, "required": 2}


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if loaded is not None else {}


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def meaningful(value: Any) -> bool:
    if value in (None, "", "unknown", "not_inferred"):
        return False
    if isinstance(value, list):
        return any(meaningful(item) for item in value)
    if isinstance(value, dict):
        return any(meaningful(item) for item in value.values())
    return True


def has_entries(data: Any, dotted_path: str) -> bool:
    return meaningful(get_path(data, dotted_path))


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "unknown"):
        return []
    return [value]


def money(value: Any) -> Decimal:
    if value in (None, "", "unknown"):
        return Decimal("0")
    text = str(value).replace(",", "").replace("$", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def total_money(items: list[Any], candidate_keys: list[str]) -> Decimal:
    total = Decimal("0")
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in candidate_keys:
            if key in item:
                total += money(item.get(key))
                break
    return total


def collect_documents(data: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for doc in as_list(manifest.get("documents")):
        if isinstance(doc, dict):
            docs.append(doc)
    for doc in as_list(data.get("source_documents")):
        if isinstance(doc, dict):
            docs.append(doc)
    return docs


def doc_text(doc: dict[str, Any]) -> str:
    fields = [
        doc.get("id"),
        doc.get("type"),
        doc.get("document_type"),
        doc.get("file"),
        doc.get("path"),
        doc.get("issuer"),
        doc.get("notes"),
    ]
    return " ".join(str(field).lower() for field in fields if field)


def matching_docs(docs: list[dict[str, Any]], *needles: str) -> list[dict[str, Any]]:
    lowered = [needle.lower() for needle in needles]
    return [doc for doc in docs if any(needle in doc_text(doc) for needle in lowered)]


def source_refs_for(docs: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    refs = []
    for doc in docs:
        doc_id = doc.get("id") or doc.get("path") or doc.get("file")
        if doc_id:
            refs.append({"document_id": str(doc_id), "label": label})
    return refs


def merge_refs(existing: list[dict[str, Any]], new_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {(ref.get("document_id"), ref.get("label")) for ref in existing}
    for ref in new_refs:
        key = (ref.get("document_id"), ref.get("label"))
        if key not in seen:
            existing.append(ref)
            seen.add(key)
    return existing


class FormPlan:
    def __init__(self) -> None:
        self.forms: dict[str, dict[str, Any]] = {}

    def add(
        self,
        form_id: str,
        status: str,
        reason: str,
        source_refs: list[dict[str, Any]] | None = None,
    ) -> None:
        title, pdf, instruction_pdf = FORM_CATALOG[form_id]
        existing = self.forms.get(form_id)
        if not existing:
            existing = {
                "form_id": form_id,
                "title": title,
                "status": status,
                "pdf": pdf,
                "instruction_pdf": instruction_pdf,
                "output_dir": "tax_forms/federal",
                "reasons": [],
                "source_refs": [],
            }
            self.forms[form_id] = existing
        if REQUIRED_RANK[status] > REQUIRED_RANK[existing["status"]]:
            existing["status"] = status
        if reason not in existing["reasons"]:
            existing["reasons"].append(reason)
        if source_refs:
            existing["source_refs"] = merge_refs(existing["source_refs"], source_refs)

    def ordered(self) -> list[dict[str, Any]]:
        order = {form_id: index for index, form_id in enumerate(FORM_ORDER)}
        return sorted(self.forms.values(), key=lambda form: order.get(form["form_id"], 999))


def infer_forms(data: dict[str, Any], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    docs = collect_documents(data, manifest)
    plan = FormPlan()
    open_questions: list[str] = []

    plan.add("f1040", "required", "Base individual income tax return.")

    interest_items = as_list(get_path(data, "income.interest"))
    dividend_items = as_list(get_path(data, "income.dividends"))
    interest_dividend_total = total_money(
        interest_items,
        ["interest_income_box_1", "taxable_interest", "amount"],
    ) + total_money(
        dividend_items,
        ["ordinary_dividends_box_1a", "ordinary_dividends", "amount"],
    )
    if interest_items or dividend_items:
        status = "required" if interest_dividend_total > Decimal("1500") else "review"
        plan.add(
            "f1040sb",
            status,
            "Interest or dividend income is present; Schedule B depends on totals and foreign account questions.",
            source_refs_for(matching_docs(docs, "1099-int", "1099-div"), "interest/dividend source"),
        )

    capital_docs = matching_docs(
        docs,
        "1099-b",
        "1099-da",
        "brokerage",
        "stock",
        "crypto",
        "realized-gain",
        "capital gain",
    )
    capital_items = as_list(get_path(data, "income.capital_gains"))
    if capital_items or capital_docs:
        refs = source_refs_for(capital_docs, "capital asset source")
        plan.add(
            "f1040sd",
            "required",
            "Capital gains/losses, 1099-B, digital asset, brokerage, stock trading, or crypto sale data is present.",
            refs,
        )
        form_8949_status = "review"
        for item in capital_items:
            if not isinstance(item, dict):
                continue
            if any(key in item for key in ["transactions", "wash_sale_disallowed", "adjustment_code", "basis_reported_to_irs"]):
                form_8949_status = "required"
        if matching_docs(capital_docs, "1099-b", "1099-da", "wash", "noncovered"):
            form_8949_status = "required"
        plan.add(
            "f8949",
            form_8949_status,
            "Capital asset transactions may need transaction-level reporting.",
            refs,
        )

    business_docs = matching_docs(docs, "1099-nec", "1099-k", "business", "gig", "freelance")
    if has_entries(data, "income.business_or_1099_income") or business_docs:
        status = "required" if matching_docs(business_docs, "1099-nec", "business") else "review"
        refs = source_refs_for(business_docs, "business income source")
        plan.add("f1040s1", "required", "Business or self-employment income generally flows through Schedule 1.", refs)
        plan.add("f1040sc", status, "Sole proprietor, gig, freelance, or 1099 business activity is present.", refs)
        plan.add("f1040sse", "review", "Net earnings from self-employment may require Schedule SE.", refs)
        plan.add("f8995", "review", "Business income may indicate qualified business income deduction review.", refs)

    if has_entries(data, "income.rentals_royalties_partnerships") or matching_docs(docs, "k-1", "partnership", "s corporation", "estate", "trust", "rental", "royalty"):
        refs = source_refs_for(matching_docs(docs, "k-1", "partnership", "s corporation", "estate", "trust", "rental", "royalty"), "pass-through or rental source")
        plan.add("f1040s1", "required", "Rental, royalty, partnership, S corporation, estate, or trust activity may flow through Schedule 1.", refs)
        plan.add("f1040se", "required", "Rental, royalty, partnership, S corporation, estate, or trust activity is present.", refs)
        plan.add("f8995", "review", "Pass-through or rental activity may indicate qualified business income deduction review.", refs)
        rental_loss_or_carryover = False
        for item in as_list(get_path(data, "income.rentals_royalties_partnerships")):
            if not isinstance(item, dict):
                continue
            passive = item.get("passive_activity") if isinstance(item.get("passive_activity"), dict) else {}
            if (
                money(item.get("income_loss")) < 0
                or money(item.get("net_income_loss")) < 0
                or money(item.get("rental_real_estate_income_loss")) < 0
                or money(passive.get("prior_year_unallowed_loss")) > 0
                or money(passive.get("prior_year_unallowed_passive_loss")) > 0
            ):
                rental_loss_or_carryover = True
        if rental_loss_or_carryover or matching_docs(docs, "8582", "passive loss", "unallowed loss"):
            plan.add(
                "f8582",
                "review",
                "Rental loss or prior-year unallowed passive loss may require Form 8582 passive activity loss limitation calculations.",
                refs,
            )
        if has_entries(data, "income.rentals_royalties_partnerships") and any(
            isinstance(item, dict) and meaningful(item.get("depreciation"))
            for item in as_list(get_path(data, "income.rentals_royalties_partnerships"))
        ):
            plan.add(
                "f4562",
                "review",
                "Rental depreciation data is present. Form 4562 may be needed for newly placed-in-service property or depreciation detail.",
                refs,
            )

    if has_entries(data, "income.other_income") or has_entries(data, "adjustments"):
        plan.add("f1040s1", "required", "Other income or adjustments are present.")

    deduction_method = str(get_path(data, "deductions.standard_or_itemized") or "").lower()
    if deduction_method == "itemized":
        plan.add("f1040sa", "required", "Itemized deductions are selected.")
    elif has_entries(data, "deductions.itemized") or deduction_method == "unsure":
        plan.add("f1040sa", "review", "Itemized deduction data is present or standard-vs-itemized comparison is needed.")

    if has_entries(data, "credits.child_and_dependent"):
        plan.add("f1040s3", "review", "Dependent-related credits may flow through Schedule 3.")
        plan.add("f1040s8", "review", "Child tax credit or credit for other dependents may require Schedule 8812.")
        plan.add("f2441", "review", "Child and dependent care expenses may require Form 2441.")

    if has_entries(data, "credits.education"):
        plan.add("f1040s3", "required", "Education credits generally flow through Schedule 3.")
        plan.add("f8863", "required", "Education credit data is present.")

    if has_entries(data, "adjustments.hsa"):
        plan.add("f8889", "required", "HSA contribution or distribution data is present.")

    if has_entries(data, "credits.premium_tax_credit") or matching_docs(docs, "1095-a", "marketplace"):
        plan.add(
            "f8962",
            "required",
            "Premium tax credit or Form 1095-A marketplace coverage data is present.",
            source_refs_for(matching_docs(docs, "1095-a", "marketplace"), "marketplace coverage source"),
        )
        plan.add("f1040s3", "required", "Premium tax credit reconciliations can flow through Schedule 3.")

    if has_entries(data, "credits.foreign_tax") or matching_docs(docs, "foreign tax", "form 1116"):
        plan.add("f1040s3", "required", "Foreign tax credit can flow through Schedule 3.")
        plan.add("f1116", "review", "Foreign tax credit may require Form 1116 depending on exceptions and amounts.")

    retirement_docs = matching_docs(docs, "1099-r", "ira", "pension")
    if has_entries(data, "income.retirement_distributions") or retirement_docs:
        plan.add(
            "f5329",
            "review",
            "Retirement distributions may require Form 5329 for early distributions or excess contribution issues.",
            source_refs_for(retirement_docs, "retirement distribution source"),
        )
        plan.add("f8606", "review", "IRA basis, nondeductible IRA contributions, or Roth conversions may require Form 8606.")

    if not docs and not data.get("source_documents"):
        open_questions.append("No source documents are recorded. Populate source_documents before relying on form inference.")

    return plan.ordered(), open_questions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Infer required and review-needed IRS forms from extracted_tax_data.yaml."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--manifest", help="Path to source_manifest.yaml.")
    parser.add_argument("--output", help="Path for required_irs_forms.yaml.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    manifest_path = Path(args.manifest).expanduser().resolve() if args.manifest else tax_forms / "source_manifest.yaml"
    output_path = Path(args.output).expanduser().resolve() if args.output else tax_forms / "required_irs_forms.yaml"

    data = load_yaml(data_path)
    manifest = load_yaml(manifest_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")
    if not isinstance(manifest, dict):
        manifest = {}

    forms, open_questions = infer_forms(data, manifest)
    result = {
        "schema_version": "0.1",
        "tax_year": data.get("tax_year", "unknown"),
        "status": "needs_review",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generated_from": str(data_path.relative_to(root)) if data_path.is_relative_to(root) else str(data_path),
        "forms": forms,
        "open_questions": open_questions,
    }
    dump_yaml(result, output_path)

    data.setdefault("required_irs_forms", {})
    data["required_irs_forms"] = {
        "status": "needs_review",
        "file": str(output_path.relative_to(root)) if output_path.is_relative_to(root) else str(output_path),
    }
    dump_yaml(data, data_path)

    required_count = sum(1 for form in forms if form["status"] == "required")
    review_count = sum(1 for form in forms if form["status"] == "review")
    print(f"Wrote {output_path}")
    print(f"Forms: {required_count} required, {review_count} review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
