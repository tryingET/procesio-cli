# Field gate and remediation standard

Use this reference when an Agent Skill controls a real tool, platform, browser,
database, filesystem, or other externally observable system. It governs field
acceptance and remediation; it is not a substitute for the domain playbook.

## 1. Freeze the field contract before mutation

A field trial needs the same discipline as a fixed jury. Before any mutation, lock:

- target, scope, stable resource identities, and expected end state;
- exact agent/model/tool settings and a fingerprint of the complete skill package,
  including `SKILL.md`, references, scripts, and assets—not only the entrypoint;
- ordered required check IDs with binary pass conditions;
- direct proof source for each check;
- explicitly permitted degraded modes, fallbacks, or gaps;
- resource, write, submission, launch, and execution budgets;
- cleanup and rollback obligations;
- unknown-outcome and retry policy;
- promotion rule and the host component that computes the verdict.

A prose goal plus an agent-authored report is not a fixed field contract. The acting
agent must not get to redefine success after seeing platform behavior.

## 2. Enforce the verdict outside the acting agent

The execution agent may collect evidence and return each fixed check, but a controller
or deterministic reviewer should validate:

- every required check ID is present exactly once and in the registered order;
- every required value is a real Boolean and is true for a pass;
- no unexpected check silently replaces a required one;
- no unknown mutation or run outcome remains;
- every allowed mutation and resource count stayed within scope;
- temporary resources were reconciled and cleaned up;
- the claimed evidence comes from the required observation boundary;
- the report's gap status is permitted by the frozen contract.

The host computes the aggregate verdict. An agent-written `passed` or
`passed_with_gap` field is evidence to validate, not authority.

## 3. Count the complete causal execution tree

Budget the real side effects, not only top-level commands. One form submission,
webhook launch, schedule occurrence, or parent-process run may create several process
instances through awaited subprocesses or nested normalizers.

Record separately:

- external submissions or trigger deliveries;
- top-level process instances;
- child and nested process instances;
- data writes and affected business keys;
- created, edited, enabled, disabled, and deleted resources;
- generated files, notifications, and external calls.

A budget that says “one run” while ignoring its child instances is ambiguous and
cannot support a reliable cost or safety claim.

## 4. Treat gaps as predeclared design choices

A required outcome that fails is not converted into a gap merely because adjacent
behavior worked or the platform limitation is understandable.

A field phase may pass with a gap only when all of the following were registered
before execution:

1. the specific degraded mode is permitted;
2. the permitted fallback is bounded;
3. the fallback proves the user-relevant outcome at the same observation boundary;
4. safety and cleanup constraints still pass;
5. the final report names the missing native capability without implying it worked.

Otherwise the phase is blocked or failed. Discovery of a platform limitation is
valuable evidence, but it is not completion of the missing acceptance criterion.

## 5. Remediate without rewriting history

When a field gate misses a required outcome:

1. preserve the original report, logs, IDs, screenshots, and before/after evidence;
2. classify the cause: domain assumption, skill instruction, source-owned reference,
   tool/runtime, platform capability, observation method, or field-contract defect;
3. write a versioned remediation contract with fresh approval and a narrower mutation
   and execution budget;
4. generate stable non-secret business keys before any retryable operation;
5. re-read current state and save pre-edit snapshots;
6. repair the smallest responsible layer;
7. rerun only the missing acceptance claim, never a successful destructive claim for
   cosmetic extra evidence;
8. reconcile unknown outcomes before another submit, launch, write, or run;
9. let deterministic host code validate remediation reports and promote the original
   phase only after all required checks pass;
10. archive the pre-remediation report and disclose the additional cost and mutations.

Never edit the old report in place to pretend the first attempt passed. Promotion is a
new, attributable result built on preserved evidence.

## 6. Route each lesson to the correct reusable layer

Do not turn every field incident into more top-level skill prose.

| Signal | Durable home |
|---|---|
| Stable platform/API semantic | Source-owned tool description or domain reference |
| Repeated deterministic construction error | Builder, schema, validator, lint, or script |
| General operational decision | Domain skill core or progressive reference |
| Evaluation/field-gate integrity defect | Meta-skill standard and controller test |
| Project-specific ID, title, payload, or workaround | Versioned field contract/evidence only |
| One unexplained observation | Preserve as provisional evidence; do not generalize yet |

Prefer a source-owned correction over duplication. Link to it from the skill when the
agent must change a decision, but do not copy volatile schemas into several places.

## 7. Avoid case-specific overfitting

Before changing a reusable skill, ask:

- Is the observation supported by a live schema, source, repeated trajectory, or a
  controlled counterexample?
- Does the proposed instruction change a recurring decision rather than narrate one
  project's history?
- Is this actually a skill issue, or can a tool/schema/controller enforce it better?
- Can the rule be stated without workspace IDs, project titles, one-off evidence keys,
  or exact remediation filenames?
- Which baseline success could the new rule break?
- What targeted regression case will prove the rule without making the full skill more
  specific to this incident?

A useful field lesson should become a small invariant, validator, or source-owned
reference. The detailed incident remains in evidence, not in the always-loaded skill.

## 8. Minimum field release record

Record:

- frozen contract/version and required check IDs;
- complete skill-package fingerprint plus model/tool settings;
- target and stable IDs, with secrets removed;
- model/client/tool versions when they affect execution;
- permitted gaps and actual gaps;
- exact mutation and full causal execution counts;
- direct proof per required check;
- unknown outcomes and reconciliation evidence;
- temporary-resource cleanup;
- original and remediated reports when remediation occurred;
- source-owned documentation or code changes derived from the field evidence;
- residual limits and claims deliberately not made.
