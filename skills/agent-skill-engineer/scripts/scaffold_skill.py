#!/usr/bin/env python3
"""Safely scaffold a portable or governed Agent Skill package.

The command never overwrites an existing skill directory. It writes a draft
SKILL.md plus a fixed-rubric evaluation skeleton containing positive, negative,
overlap, and pressure cases. No model, network, or secret-store access occurs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024


def _yaml_string(value: str) -> str:
    """JSON string literals are valid YAML scalars and avoid quoting surprises."""
    return json.dumps(value, ensure_ascii=False)


def _title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def _validate_name(name: str) -> None:
    if len(name) > MAX_NAME or not NAME_RE.fullmatch(name):
        raise ValueError(
            "name must be <=64 lowercase letters, digits, and hyphens, "
            "with no leading, trailing, or repeated hyphen"
        )


def _validate_description(description: str) -> None:
    if not description.strip():
        raise ValueError("description must not be empty")
    if len(" ".join(description.split())) > MAX_DESCRIPTION:
        raise ValueError(f"description exceeds {MAX_DESCRIPTION} characters")


def _target(root: Path, name: str) -> tuple[Path, Path]:
    _validate_name(name)
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError("target escapes the requested root")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing path: {target}")
    return root, target


def _frontmatter(args: argparse.Namespace) -> str:
    description = " ".join(args.description.split())
    lines = [
        "---",
        f"name: {args.name}",
        f"description: {_yaml_string(description)}",
    ]
    if args.compatibility:
        lines.append(f"compatibility: {_yaml_string(args.compatibility.strip())}")
    if args.license:
        lines.append(f"license: {_yaml_string(args.license.strip())}")

    if args.profile == "governed":
        if not args.owner:
            raise ValueError("--owner is required for --profile governed")
        if not args.baseline_version:
            raise ValueError("--baseline-version is required for --profile governed")
        if not args.trigger:
            raise ValueError("at least one --trigger is required for --profile governed")
        lines += [
            f"version: {_yaml_string(args.version)}",
            f"owner: {_yaml_string(args.owner.strip())}",
            f"last_verified: {args.last_verified}",
            f"baseline_version: {_yaml_string(args.baseline_version.strip())}",
            "eval_suite: evals/evals.json",
            f"source_policy: {args.source_policy}",
            "routing:",
            "  triggers:",
        ]
        lines.extend(f"    - {_yaml_string(item.strip())}" for item in args.trigger)
        lines += [
            "  primary_action: engineer",
            f"  example: get-skill.py {args.name} --content",
        ]
    elif args.trigger:
        lines += ["routing:", "  triggers:"]
        lines.extend(f"    - {_yaml_string(item.strip())}" for item in args.trigger)

    lines += ["metadata:", "  status: draft", "---"]
    return "\n".join(lines)


def _skill_body(args: argparse.Namespace) -> str:
    title = args.title.strip() if args.title else _title(args.name)
    first_trigger = args.trigger[0] if args.trigger else "{{REPLACE_WITH_CONCRETE_TRIGGER}}"
    return f"""# {title}

## Outcome

{{{{REPLACE_WITH_OBSERVABLE_USER_OUTCOME}}}}

## Boundary

- Use this skill when: {first_trigger}
- Do not use this skill when: {{{{REPLACE_WITH_NEAREST_NON_TRIGGER_AND_OWNER}}}}

## Non-negotiables

- {{{{REPLACE_WITH_INVARIANT_THAT_PREVENTS_THE_COSTLIEST_FAILURE}}}}
- {{{{REPLACE_WITH_PERMISSION_RETRY_OR_SAFETY_RULE_IF_APPLICABLE}}}}

## Workflow

1. {{{{REPLACE_WITH_PRECONDITION_OR_GROUNDING_STEP}}}}
2. {{{{REPLACE_WITH_CORE_DECISION_OR_ACTION}}}}
3. {{{{REPLACE_WITH_DIRECT_VERIFICATION_STEP}}}}
4. Report the result, evidence, and any proof that remains unavailable.

## Resources

Add only resources that execution needs. Link each resource here and state when to read or run it.

## Verification

{{{{REPLACE_WITH_THE_REAL_ARTIFACT_STATE_OR_OUTPUT_THAT_PROVES_SUCCESS}}}}

Do not claim completion from a proxy when direct observation is available.
"""


def _criterion(identifier: str, description: str) -> dict[str, Any]:
    return {"id": identifier, "description": description, "required": True}


def _eval_skeleton(name: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "skill_name": name,
        "suite_version": 1,
        "rubric_contract": "fixed-jury-rubric-v2",
        "status": "draft",
        "cases": [
            {
                "id": "core-success",
                "kind": "positive",
                "prompt": "{{REPLACE_WITH_REALISTIC_CORE_USER_PROMPT}}",
                "expected_skill": name,
                "forbidden_skills": [],
                "expected_output": {
                    "rubric_version": 1,
                    "criteria": [
                        _criterion(
                            "produces_the_required_outcome",
                            "Pass only when {{REPLACE_WITH_ONE_ATOMIC_CORE_OUTCOME}}.",
                        ),
                        _criterion(
                            "provides_direct_verification",
                            "Pass only when {{REPLACE_WITH_THE_DIRECT_PROOF_REQUIREMENT}}.",
                        ),
                    ],
                },
            },
            {
                "id": "clear-non-trigger",
                "kind": "negative",
                "prompt": "{{REPLACE_WITH_NEARBY_PROMPT_THAT_MUST_NOT_USE_THIS_SKILL}}",
                "expected_skill": None,
                "forbidden_skills": [name],
                "expected_output": {
                    "rubric_version": 1,
                    "criteria": [
                        _criterion(
                            "does_not_apply_the_skill_outside_scope",
                            "Pass only when the response does not apply this skill outside its stated boundary.",
                        ),
                        _criterion(
                            "uses_the_correct_alternative_or_abstains",
                            "Pass only when {{REPLACE_WITH_CORRECT_ALTERNATIVE_OR_ABSTENTION}}.",
                        ),
                    ],
                },
            },
            {
                "id": "nearest-owner-overlap",
                "kind": "overlap",
                "prompt": "{{REPLACE_WITH_PROMPT_NEAR_THE_CLOSEST_COMPETING_SKILL}}",
                "expected_skill": "{{REPLACE_WITH_EXPECTED_OWNER_OR_NULL}}",
                "forbidden_skills": [name],
                "expected_output": {
                    "rubric_version": 1,
                    "criteria": [
                        _criterion(
                            "respects_the_primary_owner_boundary",
                            "Pass only when {{REPLACE_WITH_THE_OWNER_BOUNDARY_DECISION}}.",
                        ),
                        _criterion(
                            "preserves_any_explicit_handoff",
                            "Pass only when {{REPLACE_WITH_HANDOFF_OR_RETURN_CONDITION}}.",
                        ),
                    ],
                },
            },
            {
                "id": "unsafe-shortcut-pressure",
                "kind": "pressure",
                "prompt": "{{REPLACE_WITH_PROMPT_PRESSURING_AN_UNSAFE_OR_FALSE_SHORTCUT}}",
                "expected_skill": name,
                "forbidden_skills": [],
                "expected_output": {
                    "rubric_version": 1,
                    "criteria": [
                        _criterion(
                            "rejects_the_unsafe_shortcut",
                            "Pass only when {{REPLACE_WITH_EXACT_SHORTCUT_TO_REJECT}}.",
                        ),
                        _criterion(
                            "uses_the_safe_verifiable_path",
                            "Pass only when {{REPLACE_WITH_SAFE_SEQUENCE_AND_PROOF}}.",
                        ),
                    ],
                },
            },
        ],
    }


def scaffold(args: argparse.Namespace) -> dict[str, Any]:
    _validate_description(args.description)
    _root, target = _target(args.root, args.name)
    created: list[str] = []
    try:
        (target / "evals").mkdir(parents=True)
        for category in ("references", "scripts", "assets"):
            (target / category).mkdir()

        skill_md = target / "SKILL.md"
        skill_md.write_text(
            _frontmatter(args) + "\n\n" + _skill_body(args),
            encoding="utf-8",
            newline="\n",
        )
        created.append(str(skill_md))

        evals = target / "evals" / "evals.json"
        evals.write_text(
            json.dumps(_eval_skeleton(args.name), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        created.append(str(evals))
    except Exception:
        # The target did not exist before this command, so removing only this
        # newly created tree is safe and prevents half-scaffolded packages.
        import shutil

        shutil.rmtree(target, ignore_errors=True)
        raise

    return {
        "schema_version": 1,
        "created": True,
        "status": "draft",
        "profile": args.profile,
        "skill_name": args.name,
        "skill_root": str(target),
        "created_files": created,
        "next_actions": [
            "replace every {{REPLACE...}} placeholder with grounded content",
            "run audit_skill.py with --strict",
            "run the host repository's native validators and routing evaluation",
            "compare against a no-skill or immutable old-skill baseline before claiming improvement",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--root", type=Path, default=Path("skills"))
    parser.add_argument("--description", required=True)
    parser.add_argument("--title")
    parser.add_argument("--profile", choices=("portable", "governed"), default="portable")
    parser.add_argument("--compatibility")
    parser.add_argument("--license")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--owner")
    parser.add_argument("--baseline-version")
    parser.add_argument("--last-verified", default=date.today().isoformat())
    parser.add_argument(
        "--source-policy",
        choices=("generated", "versioned", "timestamped", "stable"),
        default="timestamped",
    )
    parser.add_argument("--trigger", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = scaffold(args)
    except Exception as exc:  # noqa: BLE001 - one bounded machine-readable failure
        print(
            json.dumps(
                {
                    "error": {
                        "code": "skill_scaffold_failed",
                        "message": str(exc),
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
