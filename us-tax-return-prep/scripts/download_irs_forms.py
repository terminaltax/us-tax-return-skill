#!/usr/bin/env python3
"""Download blank IRS PDF forms listed in required_irs_forms.yaml."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required. Install it in the local environment with: uv pip install pyyaml"
    ) from exc


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


IRS_CURRENT_BASE = "https://www.irs.gov/pub/irs-pdf"
IRS_PRIOR_BASE = "https://www.irs.gov/pub/irs-prior"


def load_yaml(path: Path):
    if not path.exists():
        raise SystemExit(f"Required forms plan not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return loaded


def dump_yaml(data, path: Path) -> None:
    path.write_text(
        yaml.dump(data, Dumper=NoAliasDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def irs_url(filename: str, tax_year: str | None, prior_year_archive: bool) -> str:
    if prior_year_archive:
        if not tax_year or not tax_year.isdigit():
            raise SystemExit("--prior-year-archive requires a numeric --tax-year or plan tax_year.")
        stem = Path(filename).stem
        return f"{IRS_PRIOR_BASE}/{stem}--{tax_year}.pdf"
    return f"{IRS_CURRENT_BASE}/{filename}"


def download_pdf(url: str, output_path: Path, overwrite: bool) -> int:
    if output_path.exists() and not overwrite:
        return output_path.stat().st_size
    request = Request(url, headers={"User-Agent": "us-tax-return-prep/0.1"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded content is not a PDF: {url}")
    output_path.write_bytes(body)
    return len(body)


def selected_forms(plan: dict, include_review: bool) -> list[dict]:
    forms = []
    for form in plan.get("forms", []):
        if not isinstance(form, dict):
            continue
        status = form.get("status")
        if status == "required" or (include_review and status == "review"):
            forms.append(form)
    return forms


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download blank IRS PDF forms from tax_forms/required_irs_forms.yaml."
    )
    parser.add_argument("root", nargs="?", default=".", help="Tax packet root folder.")
    parser.add_argument("--plan", help="Path to required_irs_forms.yaml.")
    parser.add_argument(
        "--output-dir",
        help="Directory for blank IRS PDFs. Defaults to tax_forms/workpapers/blank_forms/irs.",
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="Also download forms marked status: review.",
    )
    parser.add_argument(
        "--include-instructions",
        action="store_true",
        help="Also download instruction PDFs listed in the plan.",
    )
    parser.add_argument(
        "--prior-year-archive",
        action="store_true",
        help="Use IRS prior-year archive URLs like irs-prior/f1040--2025.pdf.",
    )
    parser.add_argument("--tax-year", help="Tax year for prior-year archive URLs.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing downloads.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned downloads without network access.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    tax_forms = root / "tax_forms"
    plan_path = Path(args.plan).expanduser().resolve() if args.plan else tax_forms / "required_irs_forms.yaml"
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else tax_forms / "workpapers" / "blank_forms" / "irs"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = load_yaml(plan_path)
    tax_year = args.tax_year or str(plan.get("tax_year", ""))
    downloads = []
    for form in selected_forms(plan, args.include_review):
        pdf = form.get("pdf")
        if pdf:
            downloads.append((form, "form", pdf))
        if args.include_instructions and form.get("instruction_pdf"):
            downloads.append((form, "instructions", form["instruction_pdf"]))

    results = []
    for form, kind, filename in downloads:
        url = irs_url(filename, tax_year, args.prior_year_archive)
        output_path = output_dir / filename
        record = {
            "form_id": form.get("form_id"),
            "title": form.get("title"),
            "kind": kind,
            "status": form.get("status"),
            "url": url,
            "path": str(output_path.relative_to(root)) if output_path.is_relative_to(root) else str(output_path),
        }
        if args.dry_run:
            record["downloaded"] = False
            record["dry_run"] = True
            print(f"{filename}: {url}")
        else:
            try:
                size = download_pdf(url, output_path, args.overwrite)
            except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
                record["downloaded"] = False
                record["error"] = str(exc)
                print(f"FAILED {filename}: {exc}")
            else:
                record["downloaded"] = True
                record["size_bytes"] = size
                print(f"Downloaded {filename} -> {output_path}")
        results.append(record)

    manifest = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_plan": str(plan_path.relative_to(root)) if plan_path.is_relative_to(root) else str(plan_path),
        "downloads": results,
    }
    manifest_path = output_dir / "download_manifest.yaml"
    dump_yaml(manifest, manifest_path)
    print(f"Wrote {manifest_path}")

    failures = [result for result in results if not result.get("downloaded") and not args.dry_run]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
