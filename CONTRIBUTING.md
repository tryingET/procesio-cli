# Contributing to procesio-cli

Thanks for helping improve the toolkit. You don't need any permission on this
repository to suggest a change. Everything below works from a normal GitHub
account.

## Ways to suggest an update

Pick the lightest one that fits.

| You want to | Do this |
| --- | --- |
| Fix a typo or a wrong sentence in a file | Open the file on GitHub and click the pencil icon. GitHub forks the repository for you and opens a pull request. |
| Report something that doesn't work | Open a [bug report](../../issues/new/choose). |
| Ask for a tool, an action, or a behavior | Open a [feature request](../../issues/new/choose). |
| Ask a question, or float an idea that isn't a request yet | Start a [discussion](../../discussions). |
| Change code | Fork the repository, push a branch, and open a pull request. |
| Report a security problem | Don't open an issue. See [SECURITY.md](SECURITY.md). |

For a change larger than a few lines, open an issue first. A maintainer tells
you whether the idea fits before you write the code.

## Open a pull request

1. Fork the repository and clone your fork.
2. Create a branch: `git checkout -b fix-form-dto-parsing`.
3. Install the dependencies: `uv sync --all-extras`.
4. Make your change, and add a test that fails without it.
5. Run the focused tests, then the complete gate set below.
6. Push the branch and open a pull request against `main`.

CI runs:

```bash
uv run pytest tools agents dashboard webplatform skills -q
uv run python scripts/evaluate-skills.py \
  --catalog skills/evals/baseline-catalog.json \
  --verify-baseline skills/evals/baseline.json
uv run python scripts/evaluate-skill-routing.py \
  --catalog skills/evals/baseline-catalog.json \
  --verify skills/evals/baseline-routing-v2.json
uv run python scripts/evaluate-skill-routing.py \
  --min-accuracy 0.95 --max-collision-rate 0
uv run python scripts/validate-skills.py --strict-warnings
uv run python scripts/check-skill-governance.py
uv run python scripts/secret_scan.py
uv run python scripts/build-router.py --check
```

Leave **Allow edits by maintainers** checked. A maintainer can then push a small
correction to your branch instead of asking you for another round.

Every pull request lands as a single squashed commit, so you don't need to tidy
your history.

## What a maintainer looks for

- **One concern per pull request.** A refactor mixed into a bug fix takes far
  longer to review.
- **A test.** For a platform behavior, a test that captures the behavior is worth
  more than the fix itself.
- **Existing paths.** See the next section.
- **No new dependencies** without a reason in the pull request description. A
  package imported at module level has to be a base dependency; one imported
  inside a function may be an extra. CI checks that, and so does the export.
- **The manifest changes with the code.** `tool.yaml` declares a tool's actions,
  arguments and secrets, and it is what an assistant reads before running
  anything. A new argument that exists only in the handler is a bug, and the
  tests say so. After a manifest change, regenerate what is generated:
  `python scripts/build-tool-skill.py <tool>` and `python scripts/build-router.py`.
- **One JSON object on stdout, and nothing else.** Progress goes to stderr;
  failures print `{"error": {"code", "message", "details"}}` and exit non-zero.
  Callers parse that.
- **Evidence matches the claim.** Static validation proves structure; it does not
  prove runtime behavior. A successful API request proves transport; it does not
  necessarily prove the intended platform state or output.

## Contributing an Agent Skill

Use `agent-skill-engineer` when the primary deliverable is a new or changed
Agent Skill. Use `procesio-cli-maintainer` afterward for repository-specific
integration, generated routing, translations, CI, and release controls.

Start by loading the engineering skill and its relevant references:

```bash
python scripts/get-skill.py agent-skill-engineer --content
python scripts/get-skill.py agent-skill-engineer \
  --resource references/authoring-standard.md
python scripts/get-skill.py agent-skill-engineer \
  --resource references/evaluation-standard.md
```

A skill contribution must have:

- one observable primary outcome and a bounded trigger/non-trigger region;
- a description that can be distinguished from every neighboring skill before
  the body loads;
- only always-needed decisions in `SKILL.md`, with conditional detail under
  directly linked `references/`, deterministic work under `scripts/`, and output
  materials under `assets/`;
- positive, negative, nearest-overlap, and unsafe-pressure cases;
- a no-skill baseline for a new capability or an immutable old-skill snapshot
  for an improvement;
- ordered atomic jury criteria with exact IDs, binary pass descriptions, and
  required flags; every juror receives the same rubric and host code computes
  the aggregate verdict;
- direct field proof when the skill controls a tool, platform, mutation, or other
  externally observable workflow;
- version, owner, last verification date, source policy, evaluation path, and
  curated routing triggers.

Scaffold and audit helpers are available:

```bash
python skills/agent-skill-engineer/scripts/scaffold_skill.py <name> \
  --root skills \
  --description "<capability>. Use when <concrete trigger>."

python skills/agent-skill-engineer/scripts/audit_skill.py \
  skills/<name> --strict
```

The scaffolder refuses to overwrite an existing path. The audit is deterministic
and makes no model or network calls. It does not replace the repository validator,
portfolio-wide routing test, behavioral comparison, or controlled field proof.

Do not call a skill production-ready because it is eloquent, because one model
liked it, or because a static check passed. Record missing evidence explicitly.
A change to the skill corpus, evaluation rubric, judge contract, model contract,
or field workflow invalidates earlier formal evidence for that changed contract.

## Rules that come from how this repository is built

This repository is generated from an internal monorepo, not developed here
directly. An export tool copies files byte for byte, at identical paths. A
maintainer ports your merged pull request upstream by mapping its path, and it
comes back here verbatim on the next publish.

That gives you three rules:

- **Don't move or rename files.** A patch applies in both directions by path
  alone. A move breaks that, and the change has to be ported by hand.
- **Don't restructure a file to reformat it.** Same reason.
- **Expect small gaps.** A few upstream files carry marked regions that the
  export drops, so a sentence here can refer to something that is not in this
  tree. If a document points at something you can't find, that's why. Say so in
  an issue and a maintainer fixes the reference.

## Never commit these

The export refuses to publish a tree that contains any of them, and so does CI.

- `.procesio` platform export files. A platform export serializes Call API
  credentials inline. Treat every `.procesio` file as a secret, even one from a
  demo environment.
- Credentials, tokens, connection strings, and API keys, including in tests and
  fixtures. Read credentials through the credential store instead.
- Real workspace GUIDs, environment names, tenant names, or profile names.
- Personal names and email addresses, including in code comments.
- Anything identifying a customer: process names, notification bodies, sample
  payloads taken from a live system.

For an example, invent one. `contoso-demo`, `00000000-0000-0000-0000-000000000000`,
and `user@example.com` are all fine.

## Licensing

By opening a pull request, you agree that your contribution is licensed under
the same license as this repository, Apache 2.0, under the terms in section 5 of
the license. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
