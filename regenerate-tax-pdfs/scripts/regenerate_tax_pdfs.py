#!/usr/bin/env python3
"""Regenerate filled tax PDFs deterministically from YAML, field maps, and blank PDFs."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import BooleanObject, NameObject
except ImportError as exc:
    raise SystemExit(
        "pypdf is required. Install it in the local environment with: uv pip install pypdf"
    ) from exc


UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"YAML file not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if loaded is not None else {}


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def is_unknown(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in UNKNOWN_VALUES:
        return True
    return False


def path_tokens(path: str) -> list[str | int | None]:
    tokens: list[str | int | None] = []
    for part in path.split("."):
        if not part:
            continue
        match = re.match(r"^([^\[]+)", part)
        if match:
            tokens.append(match.group(1))
        for bracket in re.findall(r"\[([^\]]*)\]", part):
            if bracket == "":
                tokens.append(None)
            else:
                try:
                    tokens.append(int(bracket))
                except ValueError:
                    tokens.append(bracket)
    return tokens


def resolve_tokens(current: Any, tokens: list[str | int | None]) -> list[Any]:
    if not tokens:
        return [current]
    token = tokens[0]
    rest = tokens[1:]
    if token is None:
        if not isinstance(current, list):
            return []
        values: list[Any] = []
        for item in current:
            values.extend(resolve_tokens(item, rest))
        return values
    if isinstance(token, int):
        if not isinstance(current, list) or token >= len(current):
            return []
        return resolve_tokens(current[token], rest)
    if isinstance(current, dict) and token in current:
        return resolve_tokens(current[token], rest)
    return []


def resolve_path(data: dict[str, Any], path: str) -> Any:
    values = resolve_tokens(data, path_tokens(path))
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values


def decimal_value(value: Any) -> Decimal:
    if is_unknown(value):
        return Decimal("0")
    text = str(value).replace("$", "").replace(",", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def truthy(value: Any) -> bool:
    if is_unknown(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "checked", "x", "on"}


def format_value(value: Any, spec: dict[str, Any]) -> str:
    if is_unknown(value):
        value = spec.get("default", "")
    fmt = spec.get("format", "text")
    if fmt == "text":
        output = "" if is_unknown(value) else str(value)
    elif fmt == "money":
        output = f"{decimal_value(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
    elif fmt == "money_whole_dollars":
        output = f"{decimal_value(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}"
    elif fmt == "integer":
        output = f"{decimal_value(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}"
    elif fmt == "date_mmddyyyy":
        text = "" if is_unknown(value) else str(value)
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        output = f"{match.group(2)}/{match.group(3)}/{match.group(1)}" if match else text
    elif fmt == "digits":
        output = re.sub(r"\D", "", "" if is_unknown(value) else str(value))
    elif fmt == "ssn_last4":
        output = re.sub(r"\D", "", "" if is_unknown(value) else str(value))[-4:]
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    if spec.get("uppercase"):
        output = output.upper()
    return f"{spec.get('prefix', '')}{output}{spec.get('suffix', '')}"


def render_template(template: str, data: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = resolve_path(data, match.group(1).strip())
        return "" if is_unknown(value) else str(value)

    return re.sub(r"\{([^{}]+)\}", replace, template)


def resolve_value(spec: Any, data: dict[str, Any]) -> Any:
    if not isinstance(spec, dict):
        return spec
    if "value" in spec:
        return spec["value"]
    if "path" in spec:
        return resolve_path(data, str(spec["path"]))
    if "template" in spec:
        return render_template(str(spec["template"]), data)
    if "join" in spec:
        join_spec = spec["join"] or {}
        paths = join_spec.get("paths", [])
        separator = join_spec.get("separator", " ")
        values = []
        for path in paths:
            value = resolve_path(data, str(path))
            if isinstance(value, list):
                values.extend(str(item) for item in value if not is_unknown(item))
            elif not is_unknown(value):
                values.append(str(value))
        return separator.join(values)
    if "sum" in spec:
        total = Decimal("0")
        for path in spec["sum"] or []:
            value = resolve_path(data, str(path))
            values = value if isinstance(value, list) else [value]
            total += sum(decimal_value(item) for item in values)
        return total
    return None


def is_checkbox_spec(spec: Any) -> bool:
    return isinstance(spec, dict) and (
        spec.get("type") == "checkbox" or spec.get("checkbox") is True
    )


def checkbox_value(value: Any, spec: dict[str, Any]) -> str:
    if truthy(value):
        return str(spec.get("checked_value", "/Yes"))
    return str(spec.get("unchecked_value", "/Off"))


def map_fields(field_map: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    fields = field_map.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("Field map must contain a 'fields' mapping.")
    values: dict[str, str] = {}
    issues: list[dict[str, Any]] = []
    for pdf_field, spec in fields.items():
        try:
            raw_value = resolve_value(spec, data)
            if is_checkbox_spec(spec):
                values[str(pdf_field)] = checkbox_value(raw_value, spec)
            else:
                values[str(pdf_field)] = format_value(raw_value, spec if isinstance(spec, dict) else {})
            if isinstance(spec, dict) and spec.get("required") and is_unknown(raw_value):
                issues.append({"field": str(pdf_field), "severity": "error", "message": "Required value is missing."})
        except Exception as exc:
            issues.append({"field": str(pdf_field), "severity": "error", "message": str(exc)})
    return values, issues


def set_need_appearances(writer: PdfWriter) -> None:
    catalog = writer._root_object
    if "/AcroForm" not in catalog:
        return
    acro_form = catalog["/AcroForm"]
    if hasattr(acro_form, "get_object"):
        acro_form = acro_form.get_object()
    acro_form.update({NameObject("/NeedAppearances"): BooleanObject(True)})


def fill_pdf(blank_pdf: Path, output_pdf: Path, values: dict[str, str]) -> dict[str, Any]:
    reader = PdfReader(str(blank_pdf))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    set_need_appearances(writer)

    available_fields = set((reader.get_fields() or {}).keys())
    mapped_fields = set(values.keys())
    missing_pdf_fields = sorted(mapped_fields - available_fields) if available_fields else []
    for page in writer.pages:
        writer.update_page_form_field_values(page, values)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as handle:
        writer.write(handle)

    return {
        "available_field_count": len(available_fields),
        "filled_field_count": len(values),
        "missing_pdf_fields": missing_pdf_fields,
    }


def selected_forms(plan: dict[str, Any], include_review: bool, requested_forms: set[str]) -> list[dict[str, Any]]:
    forms = []
    for form in plan.get("forms", []):
        if not isinstance(form, dict):
            continue
        form_id = str(form.get("form_id", ""))
        if requested_forms and form_id not in requested_forms:
            continue
        status = form.get("status")
        if status == "required" or (include_review and status == "review") or requested_forms:
            forms.append(form)
    return forms


def candidate_field_maps(field_map_dir: Path, form: dict[str, Any], tax_year: str) -> list[Path]:
    form_id = str(form.get("form_id", ""))
    pdf_stem = Path(str(form.get("pdf", form_id))).stem
    candidates = [
        field_map_dir / f"{tax_year}_{form_id}_field_map.yaml",
        field_map_dir / f"{form_id}_field_map.yaml",
        field_map_dir / f"{tax_year}_{pdf_stem}_field_map.yaml",
        field_map_dir / f"{pdf_stem}_field_map.yaml",
    ]
    seen = set()
    unique = []
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def find_first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def resolve_root_path(root: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else root / path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate filled tax PDFs from extracted_tax_data.yaml, field maps, and blank PDFs."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--forms-plan", help="Path to required_irs_forms.yaml or required_state_forms.yaml.")
    parser.add_argument("--blank-dir", help="Directory containing blank PDFs.")
    parser.add_argument("--field-map-dir", help="Directory containing *_field_map.yaml files.")
    parser.add_argument("--manifest", help="Path for filled PDF manifest.")
    parser.add_argument("--include-review", action="store_true", help="Also fill forms marked status: review.")
    parser.add_argument("--form", action="append", default=[], help="Only fill a specific form_id. Repeatable.")
    parser.add_argument("--allow-missing-maps", action="store_true", help="Skip forms without field maps instead of failing.")
    parser.add_argument("--allow-unmapped-fields", action="store_true", help="Do not fail if a field map references fields absent from the PDF.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite generated PDFs.")
    parser.add_argument("--suffix", default="_draft", help="Suffix for generated PDFs when output_pdf is absent from the field map.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    forms_plan_path = (
        Path(args.forms_plan).expanduser().resolve()
        if args.forms_plan
        else tax_forms / "required_irs_forms.yaml"
    )
    blank_dir = (
        Path(args.blank_dir).expanduser().resolve()
        if args.blank_dir
        else tax_forms / "workpapers" / "blank_forms" / "irs"
    )
    field_map_dir = (
        Path(args.field_map_dir).expanduser().resolve()
        if args.field_map_dir
        else tax_forms / "workpapers" / "field_maps"
    )
    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else tax_forms / "workpapers" / "filled_pdf_manifest.yaml"
    )

    data = load_yaml(data_path)
    plan = load_yaml(forms_plan_path)
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {data_path}")
    if not isinstance(plan, dict):
        raise SystemExit(f"Expected a YAML mapping in {forms_plan_path}")

    tax_year = str(data.get("tax_year") or plan.get("tax_year") or "unknown")
    requested_forms = set(args.form)
    results: list[dict[str, Any]] = []
    had_errors = False

    for form in selected_forms(plan, args.include_review, requested_forms):
        form_id = str(form.get("form_id", "unknown"))
        pdf_name = form.get("pdf")
        if not pdf_name:
            results.append({"form_id": form_id, "status": "error", "errors": ["Missing pdf in form plan."]})
            had_errors = True
            continue

        form_blank_dir = resolve_root_path(root, form.get("blank_dir")) if form.get("blank_dir") else blank_dir
        form_field_map_dir = resolve_root_path(root, form.get("field_map_dir")) if form.get("field_map_dir") else field_map_dir
        blank_pdf = form_blank_dir / str(pdf_name)
        field_map_path = find_first_existing(candidate_field_maps(form_field_map_dir, form, tax_year))
        output_dir = root / str(form.get("output_dir") or "tax_forms/federal")
        default_output_name = f"{tax_year}_{form_id}{args.suffix}.pdf"

        result: dict[str, Any] = {
            "form_id": form_id,
            "title": form.get("title"),
            "blank_pdf": relative_to_root(blank_pdf, root),
            "field_map": relative_to_root(field_map_path, root) if field_map_path else None,
        }

        if not blank_pdf.exists():
            result["status"] = "error"
            result["errors"] = [f"Blank PDF not found: {blank_pdf}"]
            results.append(result)
            had_errors = True
            continue
        if not field_map_path:
            result["status"] = "skipped" if args.allow_missing_maps else "error"
            result["errors"] = ["No field map found."]
            result["candidate_field_maps"] = [
                relative_to_root(path, root) for path in candidate_field_maps(form_field_map_dir, form, tax_year)
            ]
            results.append(result)
            had_errors = had_errors or not args.allow_missing_maps
            continue

        field_map = load_yaml(field_map_path)
        if not isinstance(field_map, dict):
            result["status"] = "error"
            result["errors"] = [f"Expected field map YAML mapping: {field_map_path}"]
            results.append(result)
            had_errors = True
            continue

        output_name = field_map.get("output_pdf", default_output_name)
        output_pdf = output_dir / str(output_name)
        result["output_pdf"] = relative_to_root(output_pdf, root)
        if output_pdf.exists() and not args.overwrite:
            result["status"] = "error"
            result["errors"] = [f"Output PDF already exists: {output_pdf}"]
            results.append(result)
            had_errors = True
            continue

        values, mapping_issues = map_fields(field_map, data)
        pdf_result = fill_pdf(blank_pdf, output_pdf, values)
        missing_pdf_fields = pdf_result["missing_pdf_fields"]
        errors = [issue["message"] for issue in mapping_issues if issue.get("severity") == "error"]
        if missing_pdf_fields and not args.allow_unmapped_fields:
            errors.append(f"Field map references PDF fields not present in blank PDF: {', '.join(missing_pdf_fields)}")

        result.update(pdf_result)
        result["mapping_issues"] = mapping_issues
        result["status"] = "error" if errors else "filled"
        if errors:
            result["errors"] = errors
            had_errors = True
        results.append(result)
        print(f"{result['status'].upper()} {form_id}: {output_pdf}")

    manifest = {
        "schema_version": "0.1",
        "workflow": "regenerate-tax-pdfs",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "data": relative_to_root(data_path, root),
        "forms_plan": relative_to_root(forms_plan_path, root),
        "blank_dir": relative_to_root(blank_dir, root),
        "field_map_dir": relative_to_root(field_map_dir, root),
        "results": results,
    }
    dump_yaml(manifest, manifest_path)
    print(f"Wrote {manifest_path}")
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
