---
name: procesio-cli-maintainer
description: >-
  Change or review procesio-cli source and integration code. Use when adding CLI
  actions, tools, manifests, registry or MCP behavior, agents, generated routing, CI,
  tests, credentials, JSON contracts, or reversibility controls, and when wiring an
  already-designed Agent Skill into repository generation or governance. Use
  agent-skill-engineer when the primary deliverable is an Agent Skill; do not use for
  workspace operations.
version: 1.1.0
owner: procesio-cli maintainers
last_verified: 2026-09-04
baseline_version: aa9f94d385e211aab6e1491bcbcc9bdef701e5a2
eval_suite: evals/evals.json
source_policy: generated
routing:
  triggers:
    - change or review the procesio-cli repository source, manifests, tools, agents, MCP, registry, CI, or tests
    - add an action or capability while preserving JSON, credentials, routing, generation, and reversibility contracts
    - integrate an already-designed Agent Skill into repository generation, translations, governance, or release controls
  primary_action: maintain
  example: get-skill.py procesio-cli-maintainer --content
---

# Maintain procesio-cli

Treat tools, agents, skills, generated documentation, and tests as one versioned contract. Make the smallest independently verifiable change that preserves existing clients.

## Boundary

- Using the repository to operate a workspace belongs to `procesio-cli`.
- Product advice belongs to `procesio-platform-advisor`.
- Optimizing a user's SQL belongs to `sql-server-optimizer`.
- Creating, refactoring, auditing, or behaviorally evaluating an Agent Skill as the primary artifact belongs to `agent-skill-engineer`. Return here for repository-specific integration, generation, CI, translations, or release controls.

## Sources of truth

- A tool or agent manifest defines its executable public surface.
- The registry discovers manifests; avoid hardcoded capability inventories.
- Generated router/manual files must be reproducible from structural sources.
- A skill's frontmatter defines discovery; its body defines the decision workflow; references hold detail; scripts enforce deterministic work.
- Runtime behavior and stable JSON output are stronger evidence than prose.

Read `references/change-contract.md` before changing a capability, `references/mcp-compatibility.md` before changing MCP, and `references/skill-authoring.md` when integrating an already-designed skill into this repository. Load `agent-skill-engineer` for the skill-specific design and evaluation method.

## Change loop

1. **Reproduce or record the baseline.** Add a failing test or evaluation before changing behavior. For code, exercise the real contract boundary. For a skill integration, preserve the immutable skill baseline and evidence supplied by `agent-skill-engineer`.
2. **Trace ownership.** Identify manifest, dispatcher, implementation, generated outputs, callers, safety classification, tests, translations, and documentation affected by the change.
3. **Design the public shape first.** Set action name, typed arguments, output/error shape, mutability, idempotency, and verification path before implementation.
4. **Implement one verifiable unit.** Avoid unrelated cleanup and broad renames.
5. **Regenerate structural outputs.** Never hand-edit generated action manuals or router blocks as the sole source of change.
6. **Run focused tests, then the full suite.** Include platform-neutral tests; credentials and live infrastructure must not be required for unit tests.
7. **Verify the actual surface.** Invoke the command or MCP operation through the same path a client uses and inspect its JSON, stderr, exit code, and side effects.
8. **Review security and compatibility.** Check secret handling, path confinement, irreversible-action classification, retry behavior, and old client calls.
9. **Commit only a green unit.** State evidence and any live check that remains unavailable.

## Repository gates

```bash
uv run pytest tools agents dashboard webplatform skills -q
uv run python scripts/validate-skills.py --strict-warnings
uv run python scripts/evaluate-skills.py --catalog skills/evals/baseline-catalog.json --verify-baseline skills/evals/baseline.json
uv run python scripts/evaluate-skill-routing.py --min-accuracy 0.95 --max-collision-rate 0
uv run python scripts/check-skill-governance.py
uv run python scripts/secret_scan.py
uv run python scripts/build-router.py --check
```

Run generators appropriate to the changed manifest before `--check`.

## Completion rules

- No new action without manifest arguments, stable output/error behavior, tests, discoverability, and reversibility classification.
- No skill integration without the fixed-rubric and baseline evidence required by `agent-skill-engineer`.
- No reference-heavy skill unless CLI and MCP can retrieve the referenced resource safely.
- No mutation workflow that ends without direct state verification.
- No “CI is green” claim unless the actual workflow run or full local command set was observed.
