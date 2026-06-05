#!/usr/bin/env python3
"""Create or update summary.md with missing facts and open questions."""

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


START_MARKER = "<!-- us-tax-return-prep:missing-fields:start -->"
END_MARKER = "<!-- us-tax-return-prep:missing-fields:end -->"
UNKNOWN_VALUES = {None, "", "unknown", "not_inferred", "needs_review"}


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


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


def is_unknown(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in UNKNOWN_VALUES:
        return True
    return False


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def missing_required_facts(data: dict[str, Any]) -> list[str]:
    required_paths = [
        "taxpayer.primary.full_name",
        "taxpayer.primary.ssn",
        "taxpayer.primary.date_of_birth",
        "taxpayer.primary.occupation",
        "taxpayer.address.line1",
        "taxpayer.address.city",
        "taxpayer.address.state",
        "taxpayer.address.zip",
        "taxpayer.filing_status",
    ]
    if get_path(data, "taxpayer.spouse.full_name"):
        required_paths.extend(
            [
                "taxpayer.spouse.ssn",
                "taxpayer.spouse.date_of_birth",
                "taxpayer.spouse.occupation",
            ]
        )
    return [path for path in required_paths if is_unknown(get_path(data, path))]


def validation_missing_paths(validation: dict[str, Any]) -> list[str]:
    paths = []
    for issue in validation.get("issues", []) if isinstance(validation.get("issues"), list) else []:
        if not isinstance(issue, dict):
            continue
        if issue.get("code") == "missing_required_fact" and issue.get("path"):
            paths.append(str(issue["path"]))
    return paths


def review_questions(data: dict[str, Any], validation: dict[str, Any]) -> list[str]:
    questions = []
    for question in data.get("open_questions", []) if isinstance(data.get("open_questions"), list) else []:
        questions.append(str(question))
    for item in get_path(data, "calculated.review_items") or []:
        if isinstance(item, dict):
            topic = item.get("topic", "review")
            message = item.get("message", "")
            questions.append(f"{topic}: {message}")
    for issue in validation.get("issues", []) if isinstance(validation.get("issues"), list) else []:
        if isinstance(issue, dict) and issue.get("severity") in {"warning", "error"}:
            questions.append(f"{issue.get('code', 'validation')}: {issue.get('message', '')}")
    deduped = []
    seen = set()
    for question in questions:
        if question and question not in seen:
            deduped.append(question)
            seen.add(question)
    return deduped


def managed_section(data: dict[str, Any], validation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    missing_paths = sorted(set(missing_required_facts(data) + validation_missing_paths(validation)))
    questions = review_questions(data, validation)
    lines = [
        START_MARKER,
        "",
        "## Missing Tax Summary Fields",
        "",
        "Fill the blank values below in your editor, then ask Codex to re-read `summary.md` and update `tax_forms/extracted_tax_data.yaml`.",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "### Required Facts",
        "",
    ]
    if missing_paths:
        for path in missing_paths:
            lines.append(f"- {path}: ")
    else:
        lines.append("- None detected.")
    lines.extend(["", "### Open Questions", ""])
    if questions:
        for question in questions:
            lines.append(f"- {question}: ")
    else:
        lines.append("- None detected.")
    lines.extend(["", END_MARKER, ""])
    manifest = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "missing_required_facts": missing_paths,
        "open_questions": questions,
    }
    return "\n".join(lines), manifest


def replace_managed_section(existing: str, section: str) -> str:
    if START_MARKER in existing and END_MARKER in existing:
        before = existing.split(START_MARKER, 1)[0].rstrip()
        after = existing.split(END_MARKER, 1)[1].lstrip()
        parts = [before, section.strip(), after]
        return "\n\n".join(part for part in parts if part) + "\n"
    if existing.strip():
        return existing.rstrip() + "\n\n" + section
    return "# Tax Summary\n\n" + section


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update summary.md with missing tax facts.")
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--data", help="Path to extracted_tax_data.yaml.")
    parser.add_argument("--validation-report", help="Path to validation_report.yaml.")
    parser.add_argument("--summary", help="Path to summary.md.")
    parser.add_argument("--manifest", help="Path for summary_missing_fields_manifest.yaml.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    data_path = Path(args.data).expanduser().resolve() if args.data else tax_forms / "extracted_tax_data.yaml"
    validation_path = (
        Path(args.validation_report).expanduser().resolve()
        if args.validation_report
        else tax_forms / "workpapers" / "validation_report.yaml"
    )
    summary_path = Path(args.summary).expanduser().resolve() if args.summary else root / "summary.md"
    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else tax_forms / "workpapers" / "summary_missing_fields_manifest.yaml"
    )

    data = load_yaml(data_path)
    validation = load_yaml(validation_path)
    if not isinstance(data, dict):
        data = {}
    if not isinstance(validation, dict):
        validation = {}

    section, manifest = managed_section(data, validation)
    existing = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(replace_managed_section(existing, section), encoding="utf-8")
    dump_yaml(manifest, manifest_path)
    print(f"Updated {summary_path}")
    print("Open summary.md in your preferred text editor, fill the blank values, then ask Codex to re-read it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
