#!/usr/bin/env python3
"""Inspect fillable PDF fields and generate skeleton field maps."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc

try:
    from pypdf import PdfReader
except ImportError as exc:
    raise SystemExit(
        "pypdf is required. Install it in the local environment with: uv pip install pypdf"
    ) from exc


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


DEFAULT_SEMANTIC_LIBRARY = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "field_maps"
    / "federal"
    / "semantic_field_library.yaml"
)
DEFAULT_CA_SEMANTIC_LIBRARY = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "field_maps"
    / "ca"
    / "semantic_field_library.yaml"
)


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


def field_type_name(raw_type: Any) -> str:
    raw = str(raw_type or "")
    if raw == "/Tx":
        return "text"
    if raw == "/Btn":
        return "button"
    if raw == "/Ch":
        return "choice"
    if raw == "/Sig":
        return "signature"
    return raw.lstrip("/") or "unknown"


def checked_value(field: dict[str, Any]) -> str:
    states = [str(state) for state in field.get("/_States_", [])]
    for state in states:
        if state != "/Off":
            return state
    return "/Yes"


def inspect_pdf(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path))
    fields = reader.get_fields() or {}
    inspected = []
    for raw_name in sorted(fields.keys(), key=str):
        field = fields[raw_name]
        name = str(raw_name)
        field_type = field_type_name(field.get("/FT"))
        item: dict[str, Any] = {
            "name": str(name),
            "field_type": field_type,
        }
        if "/V" in field:
            item["value"] = str(field["/V"])
        if "/_States_" in field:
            item["states"] = [str(state) for state in field["/_States_"]]
        inspected.append(item)
    return {
        "pdf": str(path),
        "page_count": len(reader.pages),
        "field_count": len(inspected),
        "fields": inspected,
    }


def semantic_suggestions(path: Path, form_id: str) -> dict[str, Any]:
    library = load_yaml(path)
    if not isinstance(library, dict):
        return {}
    form = ((library.get("forms") or {}).get(form_id)) if isinstance(library.get("forms"), dict) else None
    if not isinstance(form, dict):
        return {}
    targets = form.get("targets")
    return targets if isinstance(targets, dict) else {}


def default_semantic_library(form_id: str) -> Path:
    return DEFAULT_CA_SEMANTIC_LIBRARY if form_id.lower().startswith("ca") else DEFAULT_SEMANTIC_LIBRARY


def resolve_root_path(root: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else root / path


def skeleton_field_map(
    pdf_path: Path,
    form_id: str,
    tax_year: str | None = None,
    semantic_library: Path | None = DEFAULT_SEMANTIC_LIBRARY,
) -> dict[str, Any]:
    info = inspect_pdf(pdf_path)
    fields: dict[str, dict[str, Any]] = {}
    for field in info["fields"]:
        spec: dict[str, Any] = {
            "path": "TODO",
            "required": False,
        }
        if field["field_type"] == "button":
            spec = {
                "value": False,
                "type": "checkbox",
                "checked_value": checked_value({"/_States_": field.get("states", [])}),
                "unchecked_value": "/Off",
                "required": False,
            }
        fields[field["name"]] = spec

    output_pdf = f"{tax_year}_{form_id}_draft.pdf" if tax_year and tax_year != "unknown" else f"{form_id}_draft.pdf"
    output = {
        "schema_version": "0.1",
        "form_id": form_id,
        "pdf": pdf_path.name,
        "output_pdf": output_pdf,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "field_count": info["field_count"],
        "fields": fields,
    }
    if semantic_library and semantic_library.exists():
        suggestions = semantic_suggestions(semantic_library, form_id)
        if suggestions:
            output["semantic_path_suggestions"] = suggestions
    return output


def plan_forms(plan: dict[str, Any], include_review: bool) -> list[dict[str, Any]]:
    forms = []
    for form in plan.get("forms", []):
        if not isinstance(form, dict):
            continue
        status = form.get("status")
        if status == "required" or (include_review and status == "review"):
            forms.append(form)
    return forms


def write_or_print(data: Any, output: Path | None) -> None:
    if output:
        dump_yaml(data, output)
        print(f"Wrote {output}")
    else:
        print(yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True))


def inspect_single_pdf(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf_or_root).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    form_id = args.form_id or pdf_path.stem
    if args.mode == "fields":
        data = inspect_pdf(pdf_path)
    else:
        semantic_library = (
            Path(args.semantic_library).expanduser().resolve()
            if args.semantic_library
            else default_semantic_library(form_id)
        )
        data = skeleton_field_map(pdf_path, form_id, args.tax_year, semantic_library)
    output = Path(args.output).expanduser().resolve() if args.output else None
    write_or_print(data, output)
    return 0


def inspect_plan(args: argparse.Namespace) -> int:
    root = Path(args.pdf_or_root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    plan_path = Path(args.forms_plan).expanduser().resolve() if args.forms_plan else tax_forms / "required_irs_forms.yaml"
    blank_dir = Path(args.blank_dir).expanduser().resolve() if args.blank_dir else tax_forms / "workpapers" / "blank_forms" / "irs"
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else tax_forms / "workpapers" / "field_maps"
    plan = load_yaml(plan_path)
    if not isinstance(plan, dict) or not plan:
        raise SystemExit(f"Missing or invalid forms plan: {plan_path}")

    tax_year = args.tax_year or str(plan.get("tax_year", "unknown"))
    outputs = []
    for form in plan_forms(plan, args.include_review):
        form_id = str(form.get("form_id") or Path(str(form.get("pdf", ""))).stem)
        pdf_name = form.get("pdf")
        if not pdf_name:
            continue
        form_blank_dir = (
            Path(args.blank_dir).expanduser().resolve()
            if args.blank_dir
            else resolve_root_path(root, form.get("blank_dir")) if form.get("blank_dir") else blank_dir
        )
        form_output_dir = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else resolve_root_path(root, form.get("field_map_dir")) if form.get("field_map_dir") else output_dir
        )
        pdf_path = form_blank_dir / str(pdf_name)
        if not pdf_path.exists():
            print(f"SKIP {form_id}: missing blank PDF {pdf_path}")
            continue
        output_path = form_output_dir / f"{form_id}_field_map.yaml"
        if output_path.exists() and not args.overwrite:
            print(f"SKIP {form_id}: field map exists {output_path}")
            continue
        semantic_library = (
            Path(args.semantic_library).expanduser().resolve()
            if args.semantic_library
            else default_semantic_library(form_id)
        )
        dump_yaml(skeleton_field_map(pdf_path, form_id, tax_year, semantic_library), output_path)
        outputs.append(str(output_path))
        print(f"Wrote {output_path}")

    summary = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_plan": str(plan_path),
        "field_maps": outputs,
    }
    summary_path = output_dir / "inspect_pdf_fields_manifest.yaml"
    dump_yaml(summary, summary_path)
    print(f"Wrote {summary_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect fillable PDF fields or generate skeleton field maps."
    )
    parser.add_argument("pdf_or_root", help="PDF path, or tax packet root when --from-plan is set.")
    parser.add_argument("--from-plan", action="store_true", help="Inspect blank PDFs listed in a federal or state forms plan.")
    parser.add_argument("--forms-plan", help="Path to required_irs_forms.yaml or required_state_forms.yaml.")
    parser.add_argument("--blank-dir", help="Directory containing blank PDFs.")
    parser.add_argument("--output-dir", help="Directory for generated field maps when --from-plan is set.")
    parser.add_argument("--include-review", action="store_true", help="Also generate maps for forms marked status: review.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing generated field maps.")
    parser.add_argument("--form-id", help="Form id for a single PDF, such as f1040.")
    parser.add_argument("--tax-year", help="Tax year for generated output PDF names.")
    parser.add_argument("--output", help="Output YAML path for single-PDF mode.")
    parser.add_argument(
        "--semantic-library",
        help="Path to semantic field target library. Defaults to bundled federal semantic library.",
    )
    parser.add_argument(
        "--mode",
        choices=["field-map", "fields"],
        default="field-map",
        help="Generate a skeleton field map or raw field inventory for a single PDF.",
    )
    args = parser.parse_args()
    if args.from_plan:
        return inspect_plan(args)
    return inspect_single_pdf(args)


if __name__ == "__main__":
    raise SystemExit(main())
