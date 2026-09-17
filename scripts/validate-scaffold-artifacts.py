#!/usr/bin/env python3
"""Validate a target app's .scaffold/*.yaml against the shipped JSON schemas.

Runnable form of the Phase 1 / Phase 2 / Phase 3 transition gates. Run from the
target app root:

    python {instructionsRoot}/scripts/validate-scaffold-artifacts.py --root .

Exit code 0 means every required artifact is present and schema-valid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCAFFOLD_ROOT = Path(__file__).resolve().parent.parent

# (artifact path, schema path, first phase that must produce it)
CONTRACTS: tuple[tuple[str, str, int], ...] = (
    (".scaffold/domain-specification.yaml", "schemas/domain-specification.schema.json", 1),
    (".scaffold/resource-implementation.yaml", "schemas/resource-implementation.schema.json", 2),
)


def error_location(error: object) -> str:
    path = getattr(error, "absolute_path", None)
    if path is None:
        return "<root>"
    return "/".join(str(part) for part in path) or "<root>"


def validate_contract(root: Path, data_rel: str, schema_rel: str, required: bool) -> list[str]:
    import jsonschema  # type: ignore
    import yaml  # type: ignore

    data_path = root / data_rel
    schema_path = SCAFFOLD_ROOT / schema_rel

    if not data_path.is_file():
        if required:
            return [f"{data_rel}: missing - required by this phase gate"]
        return []
    if not schema_path.is_file():
        return [f"{schema_rel}: schema not found under {SCAFFOLD_ROOT}"]

    try:
        data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return [f"{data_rel}: cannot load contract: {exc}"]

    if data is None:
        return [f"{data_rel}: file is empty"]

    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{data_rel}: schema violation at {error_location(error)}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


def validate_scaffold_artifacts(root: Path, phase: int) -> list[str]:
    if not root.is_dir():
        return [f"target root is not a directory: {root}"]
    if not (root / ".scaffold").is_dir():
        return [".scaffold/: directory not found - run the phase that produces it first"]

    try:
        import jsonschema  # type: ignore  # noqa: F401
        import yaml  # type: ignore  # noqa: F401
    except ImportError:
        return ["PyYAML and jsonschema are required; install their latest stable releases"]

    errors: list[str] = []
    for data_rel, schema_rel, produced_in in CONTRACTS:
        errors.extend(validate_contract(root, data_rel, schema_rel, required=phase >= produced_in))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate .scaffold/*.yaml against the scaffold JSON schemas."
    )
    parser.add_argument("--root", default=".", type=Path, help="target app root (default: .)")
    parser.add_argument(
        "--phase",
        default="1",
        choices=["1", "2", "3"],
        help=(
            "gate being run: 1 requires domain-specification.yaml only, 2 and 3 also require "
            "resource-implementation.yaml. An artifact present ahead of its phase is still validated."
        ),
    )
    args = parser.parse_args()

    root = args.root.resolve()
    phase = int(args.phase)
    errors = validate_scaffold_artifacts(root, phase)

    if errors:
        for error in errors:
            print(f"[fail] {error}")
        print(f"\n[fail] phase {phase} artifact validation found {len(errors)} issue(s) in {root}")
        return 1
    print(f"[ok] phase {phase} .scaffold artifacts are schema-valid in {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
