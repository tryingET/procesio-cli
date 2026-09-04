"""Shared state and snapshot helpers for the local Gate 5 overnight runner."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

BASELINE_REF = "da12de643c8a2355d019f40515766abf80a819df"
MODEL = "opencode-go/muse-spark-1.3-contributor"
THINKING = "medium"
SUITE_VERSION = 4
RUBRIC_CONTRACT = "fixed-jury-rubric-v2"
INCOMPLETE = 75
PHASES = (
    ("aa", "aa", 20260902),
    ("ab-round-1", "ab", 20260903),
    ("ab-round-2", "ab", 20260904),
)
EVALUATOR_FILES = (
    "pi-eval-preflight.py",
    "pi-skill-eval-runner.py",
    "pi-skill-eval-runner-strict.py",
    "run-skill-behavior-evals.py",
    "verify-skill-eval-series.py",
)
EXPECTED_CANDIDATE = {
    "agent-skill-engineer",
    "procesio-cli",
    "procesio-cli-maintainer",
    "procesio-platform-advisor",
    "sql-server-optimizer",
}
EXPECTED_BASELINE = {"procesio-expert", "sql-server-optimizer"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def rows(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        count += 1
    return count


def command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    binary: bool = False,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=not binary,
    )


def git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    result = command(["git", *args], cwd=repo, binary=binary)
    if result.returncode:
        detail = result.stderr or result.stdout or "git failed"
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        raise RuntimeError(detail.strip())
    return result.stdout if binary else result.stdout.strip()


def resolve_ref(repo: Path, ref: str) -> str:
    result = command(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo)
    if result.returncode:
        fetched = command(["git", "fetch", "--no-tags", "origin", ref], cwd=repo)
        if fetched.returncode:
            raise RuntimeError((fetched.stderr or fetched.stdout).strip())
        result = command(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo
        )
    if result.returncode:
        raise RuntimeError(f"cannot resolve Git ref {ref!r}")
    return result.stdout.strip()


def extract_skills(repo: Path, ref: str, destination: Path) -> Path:
    data = git(repo, "archive", "--format=tar", ref, "skills", binary=True)
    assert isinstance(data, bytes)
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe archive member: {member.name}")
            target = (destination / Path(*pure.parts)).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"archive member escapes destination: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"cannot read archive member: {member.name}")
                target.write_bytes(source.read())
            else:
                raise ValueError(f"unsupported archive member: {member.name}")
    skills = destination / "skills"
    if not skills.is_dir():
        raise RuntimeError("Git archive did not contain skills/")
    return skills


def skill_names(root: Path) -> set[str]:
    names: set[str] = set()
    for skill in root.rglob("SKILL.md"):
        in_frontmatter = False
        for line in skill.read_text(encoding="utf-8").splitlines():
            if line.strip() == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter and line.startswith("name:"):
                names.add(line.split(":", 1)[1].strip().strip("'\""))
                break
    return names


def parse_output(stdout: str) -> dict[str, Any]:
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"raw_output": stdout.strip()[-2000:]}


def retryable(value: Any) -> bool:
    strings: list[str] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"code", "failure_class", "message", "diagnosis"}:
                    strings.append(str(child))
                elif isinstance(child, (dict, list)):
                    stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
    text = " ".join(strings).lower()
    return any(
        token in text
        for token in (
            "quota",
            "rate_limit",
            "rate limit",
            "limit exhausted",
            "too many requests",
            "429",
        )
    )


def prepare(repo: Path, run_root: Path, args: Any) -> dict[str, Any]:
    if not (repo / ".git").exists():
        raise FileNotFoundError(f"not a Git checkout: {repo}")
    dirty = str(git(repo, "status", "--porcelain")).strip()
    if dirty:
        raise RuntimeError("formal evaluation requires a clean checkout:\n" + dirty)

    head = str(git(repo, "rev-parse", "HEAD"))
    baseline = resolve_ref(repo, args.baseline_ref)
    snapshots = run_root / "snapshots"
    candidate = extract_skills(repo, head, snapshots / "candidate")
    control = snapshots / "control" / "skills"
    control.parent.mkdir(parents=True)
    shutil.copytree(candidate, control)
    original = extract_skills(repo, baseline, snapshots / "baseline")

    candidate_names = skill_names(candidate)
    baseline_names = skill_names(original)
    if candidate_names != EXPECTED_CANDIDATE:
        raise RuntimeError(f"unexpected candidate skill set: {sorted(candidate_names)}")
    if baseline_names != EXPECTED_BASELINE:
        raise RuntimeError(f"unexpected baseline skill set: {sorted(baseline_names)}")

    evaluator = run_root / "evaluator"
    evaluator.mkdir()
    for name in EVALUATOR_FILES:
        shutil.copy2(repo / "scripts" / name, evaluator / name)

    suite = load(candidate / "evals" / "behavioral.json")
    thresholds = load(candidate / "evals" / "gate5-thresholds.json")
    if (
        suite.get("suite_version") != SUITE_VERSION
        or suite.get("rubric_contract") != RUBRIC_CONTRACT
    ):
        raise RuntimeError(
            f"candidate is not the frozen suite-v{SUITE_VERSION} {RUBRIC_CONTRACT} corpus"
        )
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("behavioral suite has no cases")
    minimum = int(thresholds.get("minimum_repetitions", 5))
    if args.repetitions < minimum:
        raise RuntimeError(f"formal run requires at least {minimum} repetitions")

    metadata = {
        "schema_version": 1,
        "created_at": now(),
        "repo": str(repo),
        "candidate_commit": head,
        "baseline_commit": baseline,
        "baseline_ref": args.baseline_ref,
        "model": args.model,
        "provider": args.provider,
        "thinking": args.thinking,
        "suite_version": SUITE_VERSION,
        "rubric_contract": RUBRIC_CONTRACT,
        "repetitions": args.repetitions,
        "case_count": len(cases),
        "observations_per_phase": len(cases) * args.repetitions * 2,
    }
    save(run_root / "run-metadata.json", metadata)
    return metadata


def phase_summary(run_root: Path, total: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for phase, _mode, _seed in PHASES:
        directory = run_root / "phases" / phase
        report_path = directory / "report.json"
        report = load(report_path) if report_path.is_file() else None
        complete = rows(directory / "runs.jsonl")
        result[phase] = {
            "completed_observations": complete,
            "remaining_observations": max(0, total - complete),
            "gate": report.get("gate") if report else None,
        }
    return result


def write_status(
    run_root: Path,
    metadata: dict[str, Any],
    *,
    status: str,
    reason: str,
    phase: str | None,
    calls: int,
    cap: int,
    started: str,
    last: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "kind": "gate5-fixed-jury-overnight-status",
        "updated_at": now(),
        "started_at": started,
        "status": status,
        "stop_reason": reason,
        "current_phase": phase,
        "run_root": str(run_root),
        "candidate_commit": metadata["candidate_commit"],
        "baseline_commit": metadata["baseline_commit"],
        "suite_version": metadata["suite_version"],
        "rubric_contract": metadata["rubric_contract"],
        "model": metadata["model"],
        "thinking": metadata["thinking"],
        "model_calls_upper_bound": calls,
        "max_model_calls": cap,
        "phases": phase_summary(run_root, int(metadata["observations_per_phase"])),
        "gate5_evidence": status == "complete" and reason == "all_gate5_rounds_passed",
        "last_result": last,
    }
    save(run_root / "overnight-status.json", payload)
    print(json.dumps(payload, separators=(",", ":")), flush=True)
    return payload
