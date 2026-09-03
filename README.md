# PROCESIO CLI + Agents

Command-line tooling, executable agents, and evaluated Agent Skills for the PROCESIO automation platform. Use it to drive processes, forms, documents, custom actions, schedules, credentials, and supporting systems from a terminal or an AI coding assistant.

Everything talks to a PROCESIO installation through its public API. Workspace-specific credentials stay in the operating system's secret store rather than in this repository.

- Platform: https://procesio.app
- Documentation: https://docs.procesio.com
- Product site: https://procesio.com

## Install

Python 3.11 or newer is required. `uv` is the quickest route, but a normal virtual environment works too.

```bash
git clone https://github.com/tryingET/procesio-cli.git
cd procesio-cli
uv sync
```

Heavy dependencies remain optional:

```bash
uv sync --extra browser      # Playwright form testing; then install Chromium
uv sync --extra excel        # read .xlsx workbooks
uv sync --extra databases    # SQL Server / MySQL verification
uv sync --all-extras
```

For browser testing, also run:

```bash
uv run playwright install chromium
```

## Connect a PROCESIO workspace

PROCESIO supports user/password sessions and workspace-scoped API keys. Store either as a named profile:

```bash
# Full account reach; preferred for day-to-day building across workspaces.
python scripts/run-tool.py procesio add-credential \
  --name account --type userpass --username you@example.com --make-default

# Deliberately narrow, workspace-scoped access; useful for CI or one environment.
python scripts/run-tool.py procesio add-credential \
  --name qa --type apikey --workspace-id <workspace-guid>

python scripts/run-tool.py procesio check-auth
```

Omit secret-valued flags such as `--password`, `--key`, or `--value` to enter them through a non-echoing prompt. Secrets are stored under `agents-and-tools:procesio:<secret>` in Windows Credential Manager, the macOS login Keychain, or the Linux desktop keyring.

On a headless machine, select a backend explicitly:

```bash
export AAT_CREDS_BACKEND=encrypted-file
export AAT_SECRETS_PASSPHRASE='...'
```

`AAT_CREDS_BACKEND=file` and `AAT_CREDS_BACKEND=env` are read-only adapters for host-managed secrets. See `tools/_lib/README.md` for the complete storage contract.

## First commands

```bash
python scripts/list-tools.py
python scripts/list-skills.py
python scripts/run-tool.py procesio --help
python scripts/run-tool.py procesio list-processes
python scripts/run-tool.py procesio run-process --id <process-id> --payload '{}'
```

Every executable capability prints exactly one JSON object on stdout. Progress and diagnostics go to stderr. Failures use a stable error envelope and exit non-zero:

```json
{"error": {"code": "...", "message": "...", "details": {}}}
```

## Use it from an AI assistant

The repository is designed for progressive discovery rather than memorization:

1. `CLAUDE.md` contains a generated capability router.
2. Tool and agent manifests define exact actions and typed arguments.
3. Four bounded Agent Skills route operational, advisory, SQL, and repository-maintenance work.
4. Each skill loads detailed references only for the current workflow.
5. Mutations cross an explicit approval boundary and must end in direct verification.

### The four skills

| Skill | Use it for |
|---|---|
| `procesio-cli` | Operate or troubleshoot a real PROCESIO workspace. Its nine playbooks cover processes, debugging, forms, connectors, transport, triggers, documents, data verification, and credentials/admin. |
| `procesio-platform-advisor` | Product fit, feasibility, architecture, sizing, pricing, comparisons, compliance evidence, deployment, RPA strategy, and automation prioritization. |
| `sql-server-optimizer` | Evidence-driven SQL Server optimization, including PROCESIO SQL actions and safe native parameter mapping. It never adds `NOLOCK` or `READ UNCOMMITTED` as a blanket tuning rule. |
| `procesio-cli-maintainer` | Change this repository's manifests, tools, agents, MCP surface, generated router, CI, tests, or skills without breaking the framework contracts. |

Load a skill and then only the required resource:

```bash
python scripts/get-skill.py procesio-cli --content
python scripts/get-skill.py procesio-cli --resource references/process-lifecycle.md
```

### MCP, without shell quoting

`webplatform/aat_mcp/` exposes six generic MCP tools over stdio:

| MCP tool | Purpose |
|---|---|
| `capabilities` | List capabilities, inspect one exact schema, or perform bounded search across capability/action metadata. |
| `run_tool` | Run a reversible/read tool action with structured JSON arguments. |
| `run_agent` | Run a reversible agent action. |
| `run_tool_confirmed` | Run an operator-approved irreversible tool action. |
| `run_agent_confirmed` | Run an operator-approved irreversible agent action. |
| `get_skill` | Fetch a skill plus its resource index, or one path-confined `references/`, `scripts/`, or `assets/` resource. |

Configure an MCP client with an absolute interpreter path:

```json
{
  "mcpServers": {
    "procesio": {
      "command": "/abs/path/to/procesio-cli/.venv/bin/python",
      "args": ["/abs/path/to/procesio-cli/webplatform/aat_mcp/server.py"]
    }
  }
}
```

On Windows, the interpreter is `.venv\\Scripts\\python.exe`. An HTTP transport is also available:

```bash
python webplatform/aat_mcp/http_server.py \
  --host 127.0.0.1 --port 8901 --token <secret>
```

Do not bind it beyond loopback without a token.

### Safety gate

The plain MCP execution operations reject actions classified as irreversible and return `approval_required`, naming the corresponding confirmed operation. In headless runs, `AAT_MCP_DENY_IRREVERSIBLE=1` refuses even confirmed writes.

The classifier is a guardrail, not a sandbox. It uses action and argument semantics; extend `agents/_lib/reversibility.py` when a new mutation verb or blast class is introduced. A read result never grants permission for a later write.

## The rules that are not obvious

Read `tools/procesio/PROCESIO-USAGE-GUIDE.md` before building. It indexes platform behavior that can look like success while producing no intended effect—for example, source-text substitution in scripting actions, Python output semantics, or typed form controls receiving empty values.

The guide is generated from the tool's durable notes. The rule and source link appear once; detailed reasoning stays in the owning note.

## Executable agents

An agent carries an executable method rather than API mechanics.

### Process build, verification, and audit

```bash
python scripts/run-agent.py procesio guidance
python scripts/run-agent.py procesio checklist
python scripts/run-agent.py procesio verify --process-id <id> --run --payload '{}'
python scripts/run-agent.py procesio audit --process-id <id>
```

A process that validates is not necessarily a process that runs. The verification path compares designer/runtime state, launches a representative input, and reads the resulting instance.

### Connector build → test → improve

```bash
python scripts/run-agent.py connector-builder next-step --build-id <id>
```

The connector agent drives API-document analysis, planning, generation, compilation, package download, PROCESIO installation, controlled live testing, and improvement from concrete feedback.

## Local setup console

```bash
python dashboard/serve.py
```

The dashboard binds to loopback. It reads the live registry, shows readiness and missing setup, stores credentials through the configured secret backend, validates configuration schemas, and can run capabilities without sending user data elsewhere.

## Real-browser form verification

```bash
python scripts/run-tool.py web save-session \
  --name mine --url https://forms.procesio.app

python scripts/run-tool.py web run \
  --session mine --url <form-url> --steps @steps.json
```

A screenshot is not sufficient proof. The result includes console output, page errors, failed requests, and bad responses. A changed form is complete only after its user path, triggered process, and relevant side effects are exercised successfully.

## Repository inventory

The live registry is authoritative; run `python scripts/list-tools.py --json` and `python scripts/list-skills.py --json` for the current machine-readable inventory.

### Tools

| Tool | Actions | Purpose |
|---|---:|---|
| `procesio` | 379 | PROCESIO API, DTO builders, processes, forms, documents, custom actions, environments, credentials, schedules, transport, flow inspection, and layout. |
| `connector-builder` | 54 | Generate compiled PROCESIO custom-action packages from API documentation. |
| `mysql` | 9 | Verify MySQL/MariaDB state affected by a process. |
| `sqlserver` | 9 | Verify and inspect SQL Server state and metadata. |
| `web` | 7 | Drive a real browser and collect runtime diagnostics. |
| `xlsx` | 3 | Inspect generated or source workbooks. |
| `framework-map` | 2 | Render the installed tool/agent/skill map. |

### Agents

| Agent | Actions | Purpose |
|---|---:|---|
| `procesio` | 5 | Process guidance, checklist, live verification, and static audit. |
| `connector-builder` | 4 | End-to-end connector orchestration and improvement. |

### Skills

```text
skills/
├── procesio-cli/                 operational router + nine playbooks
├── procesio-platform-advisor/    product and solution-architecture decisions
├── sql-server-optimizer/         measured SQL Server optimization
├── procesio-cli-maintainer/      repository change discipline
└── evals/                        baselines, thresholds, gate ledger, dogfood
```

## Skill quality gates

Skills are treated as executable behavior, not untested prose.

```bash
# Structural references, layout, and command/action validity
uv run python scripts/validate-skills.py --strict-warnings

# Frozen old baseline and current description-routing regression check
uv run python scripts/evaluate-skills.py \
  --catalog skills/evals/baseline-catalog.json \
  --verify-baseline skills/evals/baseline.json
uv run python scripts/evaluate-skill-routing.py \
  --min-accuracy 0.95 --max-collision-rate 0

# Ownership, freshness, eval-suite, and release-ledger checks
uv run python scripts/check-skill-governance.py
```

The provider-neutral behavioral runner lives at `scripts/run-skill-behavior-evals.py`. It performs randomized, blinded candidate/baseline runs through an external fresh-context model command. `scripts/verify-skill-eval-series.py` requires two consecutive clean reports.

Current status is recorded in `skills/evals/gates.json`. Gates 0–4 and Gate 6 have green cross-platform CI evidence. Gate 5 remains pending until repeated blinded model A/B runs clear the pre-registered bar, so this fork intentionally has no skill-release tag yet.

GitHub Actions is active for this fork. The scheduled/manual workflow is `.github/workflows/skill-evals.yml`; configure `SKILL_EVAL_RUNNER` plus its provider secret before dispatching the behavioral job.

## Layout

```text
tools/procesio/      API client, DTOs, flow model, layout, handlers, durable notes
agents/procesio/     executable build-and-test method
tools/_lib/          credentials, manifests, JSON I/O, skill/resource integrity
skills/              bounded workflows and progressively loaded references
webplatform/aat_mcp/ generic MCP bridge and safety gate
dashboard/           local setup console
scripts/             runners, generators, validators, and evaluation harnesses
registry.py          manifest/skill discovery; no hardcoded capability list
```

A tool is a directory with a `tool.yaml`, entry point, and README. A skill is a directory with `SKILL.md` frontmatter and only the references, scripts, assets, and evaluations it needs. Generated files must be regenerated from manifests rather than edited as an independent source of truth.

## Contributing

See `CONTRIBUTING.md`. Never commit a `.procesio` export or a credential. This public repository is generated from an internal monorepo, so merged upstream changes may return in later publication batches.

Report security issues through `SECURITY.md`, not a public issue.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
