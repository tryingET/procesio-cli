# Skill authoring contract

## RED

Record realistic prompts and the current selected skill/output before editing. Include positive, negative, overlap, missing-context, and pressure cases. If the baseline does not exhibit the claimed problem, do not add prose to solve it.

## GREEN

Write the minimum instruction that changes the observed decision:

- description: capability plus concrete trigger conditions, no workflow summary;
- SKILL.md: core decisions and sequence, normally under 250 lines;
- references: one level deep, loaded only when relevant;
- scripts: deterministic repeated operations;
- assets: output templates/media, not instructions.

Point to another skill by name instead of copying its workflow. Point to manifests/registry for volatile mechanics.

## REFACTOR

Run multiple fresh-context comparisons against the previous skill. Track routing, task success, safety, verification, tokens, duration, and variance. Keep a change only when it beats the noise floor or fixes a hard integrity defect.

Run the repository skill validator; a parseable but broken skill is not ready.
