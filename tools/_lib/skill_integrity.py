"""Cheap runtime integrity checks for registered Agent Skills.

The full authoring validator remains ``scripts/validate-skills.py``. These checks
cover the subset the live registry needs before advertising or loading a skill.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_RESOURCE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:references|scripts|assets)/[A-Za-z0-9][A-Za-z0-9._/-]*)"
)
_RESOURCE_DIRS = {"references", "scripts", "assets"}


def _inside(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def _resource_refs(root: Path) -> set[str]:
    refs: set[str] = set()
    for source in sorted(path for path in root.rglob("*.md") if path.is_file()):
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        refs.update(match.group(1).rstrip(".,:;)")
                    for match in _RESOURCE_REF_RE.finditer(text))
    return refs


def skill_integrity_errors(manifest: Any, skill_md: Path) -> list[str]:
    """Return stable errors that make a skill unsafe to advertise or load."""
    errors: list[str] = []
    root = skill_md.parent.resolve()
    name = str(getattr(manifest, "name", "") or "")
    description = " ".join(str(getattr(manifest, "description", "") or "").split())

    if not _NAME_RE.fullmatch(name) or len(name) > 64:
        errors.append("invalid skill name")
    if root.name != name:
        errors.append(f"folder '{root.name}' does not match skill name '{name}'")
    if not description:
        errors.append("description is empty")
    elif len(description) > 1024:
        errors.append("description exceeds 1024 characters")
    try:
        line_count = len(skill_md.read_text(encoding="utf-8").splitlines())
        if line_count > 525:  # frontmatter allowance + 500-line body ceiling
            errors.append(f"SKILL.md is too long ({line_count} lines)")
    except (OSError, UnicodeError) as exc:
        errors.append(f"SKILL.md is unreadable: {exc}")

    eval_suite = str(getattr(manifest, "eval_suite", "") or "").strip()
    if eval_suite:
        rel = PurePosixPath(eval_suite.replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts:
            errors.append(f"eval_suite escapes the skill root: {eval_suite}")
        else:
            candidate = root.joinpath(*rel.parts)
            try:
                resolved = candidate.resolve(strict=True)
            except (FileNotFoundError, OSError):
                errors.append(f"eval_suite does not exist: {eval_suite}")
            else:
                if not _inside(root, resolved) or not resolved.is_file():
                    errors.append(f"eval_suite is outside the skill root: {eval_suite}")

    for raw in sorted(_resource_refs(root)):
        rel = PurePosixPath(raw)
        if rel.is_absolute() or ".." in rel.parts or rel.parts[0] not in _RESOURCE_DIRS:
            errors.append(f"invalid resource reference: {raw}")
            continue
        # A path such as scripts/run-tool.py may name a repository command, not
        # a bundled skill resource. Validate it here only when the skill actually
        # owns that resource category; the full authoring validator resolves both.
        if not (root / rel.parts[0]).is_dir():
            continue
        candidate = root.joinpath(*rel.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError):
            errors.append(f"resource does not exist: {raw}")
            continue
        if not _inside(root, resolved) or not resolved.is_file():
            errors.append(f"resource is outside the skill root: {raw}")

    for category in sorted(_RESOURCE_DIRS):
        folder = root / category
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if len(rel.parts) > 2:
                errors.append(f"nested bundled resource: {rel.as_posix()}")
            try:
                resolved = path.resolve(strict=True)
            except (FileNotFoundError, OSError):
                errors.append(f"unreadable bundled resource: {rel.as_posix()}")
                continue
            if not _inside(root, resolved):
                errors.append(f"bundled resource escapes the skill root: {rel.as_posix()}")

    return sorted(set(errors))
