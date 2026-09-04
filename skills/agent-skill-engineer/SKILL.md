---
name: agent-skill-engineer
description: >-
  Design, create, refactor, audit, and evaluate Agent Skills and SKILL.md packages.
  Use when turning a repeated workflow into a skill, optimizing skill descriptions or
  routing boundaries, splitting instructions into progressive references/scripts/assets,
  building fixed-rubric tests and old/no-skill baselines, measuring A/A or A/B behavior,
  or proving a skill on the real artifact. Do not use for ordinary repository
  implementation unless the primary deliverable is an Agent Skill.
version: 1.0.0
compatibility: Agent Skills compatible clients; Python 3.11+ for bundled helpers.
owner: procesio-cli maintainers
last_verified: 2026-09-04
baseline_version: aa9f94d385e211aab6e1491bcbcc9bdef701e5a2
eval_suite: evals/evals.json
source_policy: timestamped
routing:
  triggers:
    - create, update, split, merge, refactor, or audit an Agent Skill or SKILL.md package
    - optimize skill descriptions, routing boundaries, progressive disclosure, context cost, or safety
    - design fixed-rubric skill evaluations, baselines, A/A noise checks, A/B comparisons, or field trials
  primary_action: engineer
  example: get-skill.py agent-skill-engineer --content
---

# Engineer Agent Skills

Create the smallest skill package that reliably changes agent behavior and proves the change. Treat a skill as executable decision infrastructure, not as a persuasive document or an expert persona.

## Boundary

- Use this skill when the primary artifact is an Agent Skill, its routing contract, its resources, or its evaluation system.
- Use `procesio-cli-maintainer` when the primary work is repository code, manifests, MCP, CI, or generated integration; return here for the skill-specific design and evidence.
- Use the domain skill when the user wants the domain task performed rather than encoded for reuse.
- Do not create a skill for a one-off answer, volatile facts, or behavior that a type, API, lint, test, script, or permission boundary can enforce more reliably.

## Non-negotiables

1. **Evidence before prose.** Start from observed failures, repeated work, or concrete examples. Do not invent a problem merely to justify a skill.
2. **One intent, one owner.** Give every trigger region a clear owner and explicit non-trigger neighbors. Avoid universal skills and duplicate workflows.
3. **Context is a budget.** Put only routing and core decisions in `SKILL.md`; load detailed references only when needed and move deterministic repetition into scripts.
4. **Match freedom to fragility.** Use judgment for open-ended work, structured templates for preferred patterns, and executable helpers for narrow error-prone operations.
5. **Freeze evaluation before results.** Give every juror the same ordered atomic criteria and pass conditions. Jurors return criterion booleans; host code computes the aggregate verdict.
6. **Compare against the right baseline.** New skill: no-skill baseline. Existing skill: immutable old-skill snapshot. Description change: include positive, negative, overlap, and pressure routing cases.
7. **Prove the real outcome.** Static validity and fluent output are proxies. Exercise the real user path when the skill controls an executable or externally observable workflow.
8. **Encode recurring lessons structurally.** A repeated correction belongs in a validator, script, schema, test, or runtime guard before it becomes another paragraph.
9. **Never claim production readiness without evidence.** Label unexecuted work as a draft and name the missing proof.

## Select the mode

- **Create:** qualify a repeatable capability, define its boundary, then build a new package.
- **Improve:** snapshot the old skill, reproduce a concrete failure, and change the smallest causal instruction or resource.
- **Description tune:** preserve body behavior; optimize only discovery using a routing corpus and collision checks.
- **Audit:** inspect structure, routing, safety, portability, evaluation quality, and real-proof coverage without rewriting by default.
- **Portfolio design:** split, merge, retire, or compose skills so each user intent has one bounded owner.

## Read only what the current mode needs

- Read `references/decision-framework.md` before deciding whether a skill should exist or how a portfolio should be divided.
- Read `references/authoring-standard.md` before drafting or restructuring a skill package.
- Read `references/evaluation-standard.md` before writing tests, juries, baselines, or performance claims.
- Read `references/review-standard.md` before approval, publication, or a production-ready claim.
- Read `references/expert-lenses.md` for non-trivial or high-consequence cross-domain review.
- Read `references/portability-standard.md` when the skill must work across clients, operating systems, or repositories.

Use the bundled [scaffold helper](scripts/scaffold_skill.py) and [audit helper](scripts/audit_skill.py) when appropriate:

```bash
python skills/agent-skill-engineer/scripts/scaffold_skill.py <name> \
  --root skills --description "<capability and trigger boundary>"

python skills/agent-skill-engineer/scripts/audit_skill.py \
  skills/<name> --strict
```

The scaffold never overwrites an existing path. The audit is deterministic and makes no model or network calls.

## Workflow

### 1. Ground the need

Inspect the repository, artifacts, transcripts, tool schemas, and current skill behavior before asking the user for information already present. Collect realistic examples in these classes:

- clear positive trigger;
- clear negative or abstention;
- nearest overlap with another skill;
- missing-context case;
- pressure case that invites an unsafe shortcut or false completion;
- representative successful outcome.

Record what happens without the proposed change. For an existing skill, preserve an immutable snapshot before editing.

### 2. Freeze the contract

Write a short skill brief before drafting instructions:

- user outcome and observable proof;
- trigger and explicit non-trigger boundary;
- inputs, outputs, dependencies, permissions, and side effects;
- invariants and irreversible failure modes;
- source ownership and freshness policy;
- evidence tier and acceptance criteria.

Turn acceptance criteria into ordered atomic IDs with binary pass descriptions. Keep routing selection separate from behavioral quality. Do not expose hidden grading guidance to the response-producing candidate.

### 3. Explore the design space

For non-trivial skills, produce at least two structurally distinct designs from the same brief. Vary the package boundary, degree of freedom, and resource split—not just wording. Score each design against the frozen criteria, context cost, portability, safety, extension cost, and likely failure modes. Pick one coherent base, graft only compatible strengths, and record rejected alternatives.

If the candidates diverge wildly, the brief is underspecified. Re-ground instead of averaging incompatible designs.

### 4. Build the package

Create only files that improve execution:

- `SKILL.md`: metadata, boundary, core decisions, workflow, resource router, completion contract;
- `references/`: stable domain detail or variant-specific guidance loaded on demand;
- `scripts/`: deterministic, repeated, or fragile operations with bounded inputs and machine-readable failures;
- `assets/`: templates or media copied into outputs, never hidden instructions;
- `evals/`: realistic cases with fixed rubrics and baseline intent.

Target fewer than 250 body lines and treat 500 as a hard ceiling. Remove generic advice the model already knows, duplicated reference text, research diaries, decorative personas, and instructions that cannot affect a decision.

### 5. Prove structure and routing

Run the local audit and the host repository's native validator. Resolve every reference, validate frontmatter and resource confinement, scan for secrets and placeholders, and verify scripts on supported platforms. Then run routing cases against the full skill portfolio, not the new skill in isolation. Zero forbidden collisions is the default bar.

### 6. Prove behavior

Run paired fresh-context cases against the selected baseline. Use the same prompt, files, model, settings, and fixed rubric for both variants. Randomize opaque labels. First establish A/A noise on byte-identical corpora; then run A/B only if the evaluator is stable enough to detect the registered minimum effect. Preserve raw observations, timing, token counts when available, and qualitative artifacts.

Do not let jurors invent criteria, rename IDs, or choose the aggregate verdict. Do not revise thresholds after seeing formal results. Diagnose failures by layer before editing the skill: routing, instruction, tool, environment, observation, or jury.

### 7. Prove the field outcome

For operational skills, run at least one controlled end-to-end task through the same surface a real agent uses. Preview mutations, obtain approval, execute once, observe the actual resulting state or output, and clean up only after successful verification. Preserve safe evidence. A screenshot, HTTP success, compile, lint, or self-report is insufficient when a stronger direct observation exists.

For subjective skills, use blinded human comparison and concrete preference evidence instead of fabricating objective assertions.

### 8. Refactor and ship

Keep a change only when it fixes a demonstrated integrity defect or improves the registered outcome beyond measured noise without unacceptable regressions. Update version, ownership, freshness, routing corpus, fixed-rubric evaluations, generated indexes, translations, and governance records as required by the host repository. Re-run focused checks, then the complete suite and target-client smoke tests.

## Failure attribution

Before changing instructions, classify the failure:

| Layer | Typical evidence | Correct response |
|---|---|---|
| Routing | wrong skill or no skill selected | tune descriptions or portfolio boundary |
| Instruction | right skill, wrong decision or sequence | change the smallest causal instruction |
| Resource | missing/stale reference, helper, or template | repair source ownership or resource routing |
| Tool/runtime | command, API, auth, or environment failure | fix the executable system, not the skill prose |
| Observation | proxy proof disagrees with real state | strengthen direct verification |
| Jury | identical evidence receives inconsistent criteria or aggregation | freeze rubric IDs and deterministic host scoring |

## Verification and completion report

Return:

- mode and skill boundary;
- baseline and reproduced failure or leverage case;
- files created, changed, retired, or deliberately omitted;
- routing, structural, behavioral, and field evidence;
- fixed rubric version or qualitative review method;
- measured regressions, residual risk, and unavailable proof;
- exact commands or artifacts a maintainer can rerun.

A draft with honest missing evidence is acceptable. An unverified “exceptional” skill is not.
