# Agentic Arena

Multi-model consensus via Cursor Cloud Agents.

Frontier models solve a task through iterative rounds of independent work,
anonymized critique, and verified consensus. The orchestrator is a Python CLI
that communicates with the
[Cursor Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints)
over HTTP.

```
generate --> evaluate
               |-- CONSENSUS (score >= 8) --> done
               |-- CONTINUE  (score < 8)  --> generate (next round)
               '-- max rounds reached     --> done
```

---

## Design

### Why Cursor Cloud Agents

Each API call launches an autonomous agent in an isolated Ubuntu VM that
clones a GitHub repo, works on its own branch, and can open a PR when
finished. This eliminates most infrastructure complexity:

| Concern | Local (tmux + libtmux) | Cloud Agents API |
|---|---|---|
| Security | Dev container + deny-by-default perms | Cursor's isolated VMs |
| Filesystem isolation | Git worktrees | Automatic per-agent branches |
| Completion detection | File-stable + pane-idle heuristics | Poll status until `FINISHED` |
| Content extraction | Terminal scraping or file parsing | `GET /conversation` returns JSON |
| Observability | `tmux attach` for live view | Cursor web UI; conversation API |
| Orchestrator | libtmux + signal handlers + pipe-pane | Python script making HTTP calls |

**Trade-offs accepted:**

- **Latency.** Each agent turn is a full autonomous run (minutes, not
  seconds). A 2-round arena takes ~20-40 minutes.
- **Cost.** Cloud agents use Max Mode pricing. Three agents across multiple
  rounds is nontrivial spend.
- **Observability.** No real-time terminal view. You monitor via status
  polling and post-hoc conversation retrieval.

### Anonymization

The orchestrator maintains a mapping randomized per run:

```python
alias_mapping = {"agent_a": "opus", "agent_b": "gemini", "agent_c": "gpt"}
```

All prompts, filenames, and cross-references use aliases. Agents see
"Agent A's solution" and "Agent B's critique," never model names.
Presentation order is shuffled per prompt to prevent positional bias.

### Non-goals

- **Real-time interaction.** The arena is a batch process.
- **Truth guarantees.** Consensus among models does not guarantee
  correctness. The arena improves quality through structured critique,
  not epistemic certification.
- **Collusion prevention.** Models may recognize each other's stylistic
  fingerprints despite anonymization. Aliases mitigate casual bias, not
  adversarial identification.
- **General-purpose agent framework.** This is a single-purpose orchestrator
  for multi-model debate, not a reusable agent platform.

### Known risks

| Risk | Severity | Mitigation |
|---|---|---|
| Agent produces unstructured response (no XML tags) | High | Fallback heuristics; re-prompt with format reminder |
| Consensus regression to the mean | High | Separate critique before revision; verify prompt classifies disagreements |
| Cloud agent latency (minutes per turn) | Medium | Parallel execution within phases |
| Context window accumulation across rounds | Medium | Summarization, diff-only views, or fresh agents per round |
| API rate limits / transient failures | Medium | Retry with exponential backoff and jitter |
| Judge bias toward own solution | Medium | Anonymized aliases; anti-bias instruction; judge rotation |
| State file corruption on crash | Low | Atomic write via temp-file-then-rename |

---

## Getting started

### Prerequisites

- [pixi](https://pixi.sh) for package management (Python 3.13 is installed automatically).
- A **Cursor API key** (see below).
- A **GitHub repository** connected to your Cursor account.

### Obtaining a Cursor API key

The arena uses the [Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints)
to launch and manage agents. You need a **User API key** (not a BYOK key for
third-party providers).

1. Sign in at [cursor.com/dashboard](https://cursor.com/dashboard).
2. Go to the **Integrations** tab
   ([direct link](https://cursor.com/dashboard?tab=integrations)).
3. Click **Create New API Key**, give it a name, and copy the generated key.
   You will not be able to see the key again after leaving the page.
4. Export the key in your shell **or** put it in a `.env` file at the project
   root (already gitignored):

```bash
# Option A: environment variable
export CURSOR_API_KEY="key_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Option B: .env file
echo 'CURSOR_API_KEY=key_xxx...' > .env
```

> **Note:** Free-plan API keys do **not** support the Cloud Agents API. You
> need a paid Cursor plan (Pro, Business, or Enterprise).

### Install

```bash
# Install pixi if you don't have it
curl -fsSL https://pixi.sh/install.sh | bash
source ~/.bashrc

# Clone and install dependencies (pixi handles everything)
git clone https://github.com/maresb/agentic-arena.git
cd agentic-arena
pixi install
```

All dependencies (Python 3.13, requests, pydantic, typer, pytest, mypy, ruff)
are declared in `pixi.toml` and resolved via conda-forge. The project is also
installed as an editable package via `pyproject.toml`, which provides an `arena`
console entrypoint.

### Verify the install

```bash
pixi run test       # unit tests
pixi run lint       # ruff
pixi run format     # ruff format
pixi run typecheck  # mypy
```

---

## Usage

The CLI has five commands: **init**, **run**, **step**, **status**, and
**add-comment**.

### Initialize an arena

```bash
pixi run arena init \
  --task "Review the authentication module for security issues" \
  --repo owner/repo \
  --base-branch main \
  --max-rounds 3
```

This creates `arenas/0001/state.yaml` with a randomized alias-to-model mapping
and sets the phase to `generate`. By default all three models (Claude Opus, GPT,
Gemini) are used; use `--models` to select a subset.

#### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--task` | placeholder | Task description for the agents to solve (edit `state.yaml` before running) |
| `--repo` | git remote | GitHub repository (`owner/repo` format); auto-detected from `origin` |
| `--base-branch` | `main` | Branch the agents work from |
| `--max-rounds` | `3` | Cap on generate-evaluate cycles (1-10) |
| `--models` | all | Comma-separated model list (e.g. `opus,gpt`) |
| `--verify-commands` | none | Comma-separated commands to run on consensus (e.g. `"pixi run pytest,pixi run mypy ."`) |
| `--verify-mode` | `advisory` | `advisory` (log failures) or `gating` (override consensus on failure) |
| `--arena-dir` | auto | Next sequentially-numbered directory under `arenas/` |

### Run the orchestrator

```bash
export CURSOR_API_KEY="your-key-here"
pixi run arena run
```

The orchestrator loops through phases until consensus is reached or max rounds
are exhausted. It is fully **resumable** -- kill it at any point and restart;
previously completed work is never re-done.

Progress is logged to both stderr and `arenas/NNNN/orchestrator.log`. Add `-v`
for DEBUG-level output.

During polling, the orchestrator prints dots (`.`) to stderr so you know it is
still working. These dots are suppressed when verbose logging is enabled.

### Single-step mode

```bash
pixi run arena step
```

Executes exactly one phase transition (e.g. generate → evaluate) and exits.
Useful for debugging or running phases manually.

### Check status

```bash
pixi run arena status
```

Shows the current phase, round, alias mapping, agent IDs, and per-agent
progress.

---

## Configuration

### Model selection

By default, the arena uses all three models: `opus`, `gpt`, and `gemini`. Use
`--models` to select a subset:

```bash
# Two-model arena
pixi run arena init --task "..." --repo owner/repo --models opus,gpt

# Single-model smoke test
pixi run arena init --task "..." --repo owner/repo --models opus --max-rounds 1
```

The alias list (agent_a, agent_b, ...) is automatically sized to match the
number of models.

### Verify commands

Verify commands run after the judge declares consensus. They let you gate
consensus on passing tests:

```bash
pixi run arena init \
  --task "Fix the login bug" \
  --repo owner/repo \
  --verify-commands "pixi run pytest,pixi run mypy ." \
  --verify-mode gating
```

- **advisory** (default): Log verify failures but accept the consensus.
- **gating**: Override consensus to CONTINUE if any verify command fails,
  forcing another generate-evaluate round.

### Inject operator comments

Use `add-comment` to inject a message into running agent conversations:

```bash
# Interactive mode (walks through delivery, targets, framing)
pixi run arena add-comment

# Non-interactive: deliver immediately to all agents
pixi run arena add-comment --message "Focus on error handling" --immediate

# Queue for next phase start
pixi run arena add-comment --message "Ignore the failing lint rule" --queue
```

Comments can target specific agents with `--targets agent_a,agent_b` and can
include file contents via `--file path/to/context.md`.

---

## Crash recovery and restart semantics

The orchestrator is designed to survive crashes at any point:

- **Atomic state writes.** State is written to a temp file and renamed, so a
  crash during write never leaves a corrupt `state.yaml`.
- **Idempotent phases.** Each agent's progress is tracked individually
  (pending → sent → done). On restart, only unfinished agents are re-processed.
- **Crash-safe follow-ups.** Before sending a follow-up, the message count is
  persisted. On restart, the orchestrator compares the current message count to
  the saved count to detect whether the follow-up was actually delivered,
  preventing duplicate prompts.
- **Judge selection is persisted.** The verify phase saves the selected judge
  before sending the verdict prompt, so a crash won't re-select a different
  judge on restart.

To resume after a crash, simply re-run the same command:

```bash
pixi run arena run
```

---

## Output layout

Each arena run produces:

```
arenas/0001/
  state.yaml                  Main state file (file: references to artifacts)
  orchestrator.log            Full debug log
  report.md                   Rolling summary report (updated each phase)
  winning-solution.md         Winner's final solution (on completion)
  artifacts/                  Externalized large text from state
    solutions_agent_a.md
    critiques_agent_a.md
    final_verdict.md
    ...
  00-1-generate-opus-solution-a1b2c3.md   Round 0, generate phase archive
  00-2-evaluate-gpt-critique-d4e5f6.md    Round 0, evaluate phase archive
  00-2-evaluate-gpt-verdict-789abc.json   Round 0, verdict archive
  ...
```

**Archive naming:** `{round:02d}-{phase_num}-{phase}-{model}-{artifact}-{uid}.{ext}`
where `uid` is a content-addressed SHA-256 prefix. Files are deduplicated --
restarting the orchestrator does not create duplicate archives.

**Artifact externalization:** Large text fields (solutions, critiques,
verify results, final verdict) are stored as separate `.md` files under
`artifacts/`. The YAML state file stores `file:` references that are resolved
transparently on load. Old inline state files (without `file:` references)
are still loaded correctly.

---

## Project structure

```
arena/
  __init__.py        Package root (version)
  __main__.py        Typer CLI: init, run, step, status, add-comment
  api.py             Cursor Cloud Agents HTTP client with retry/backoff
  extraction.py      XML tag parsing, Verdict model, fallback heuristics
  git.py             Git remote URL parsing
  orchestrator.py    Main loop, round archival, report generation
  phases.py          Phase functions: generate, evaluate
  prompts.py         Prompt templates, model name mapping, branch hints
  state.py           Pydantic models (ArenaConfig, ArenaState), persistence

tests/
  test_api.py          API client tests
  test_cli.py          CLI commands via Typer CliRunner
  test_extraction.py   XML parsing, verdict model, fallbacks
  test_git.py          Git remote URL parsing tests
  test_integration.py  Live API tests (requires CURSOR_API_KEY)
  test_orchestrator.py Report generation, archive deduplication
  test_phases.py       Phase control flow with mock API
  test_prompts.py      Prompt template content, branch hints
  test_state.py        Pydantic models, serialization, externalization

.github/workflows/ci.yml  CI pipeline: test, lint, format, typecheck
pyproject.toml             Package metadata, console_scripts entrypoint
pixi.toml                  Dependencies and task definitions
```

### Key types

| Type | Module | Purpose |
|---|---|---|
| `ArenaConfig` | `state.py` | Frozen config: task, repo, branch, rounds, models, verify |
| `ArenaState` | `state.py` | Full mutable state persisted to `state.yaml` |
| `Phase` | `state.py` | StrEnum: generate, evaluate, done |
| `ProgressStatus` | `state.py` | StrEnum: pending, sent, done |
| `DEFAULT_MODELS` | `state.py` | Default model short names: opus, gpt, gemini |
| `Verdict` | `extraction.py` | Parsed judge verdict with decision, score, etc. |
| `CursorCloudAPI` | `api.py` | HTTP client for the Cursor Cloud Agents endpoints |

---

## Testing

### Unit tests (no API key needed)

The test suite mocks all API calls and validates control flow, state
transitions, extraction logic, prompt construction, and serialization:

```bash
pixi run test        # 227 tests
```

### Integration tests (requires API key)

Live API tests are in `tests/test_integration.py`. They are skipped by default
and only run when `CURSOR_API_KEY` is set:

```bash
CURSOR_API_KEY=... pixi run pytest tests/test_integration.py -v
```

These tests verify authentication, model listing, repository listing, and
agent launch/stop against the real Cursor Cloud API.

### CI

The GitHub Actions pipeline (`.github/workflows/ci.yml`) runs on every push
and PR to `main`:

- `pixi run test` — unit tests
- `pixi run lint` — ruff linter
- `pixi run format-check` — ruff format check
- `pixi run typecheck` — mypy

---

## Troubleshooting

### `CURSOR_API_KEY environment variable is not set`

Export your key or create a `.env` file. See [Obtaining a Cursor API
key](#obtaining-a-cursor-api-key).

### Agent stuck in `RUNNING` / `CREATING`

The orchestrator polls agents with exponential backoff. If an agent appears
stuck, check the Cursor dashboard for the agent's status. The orchestrator
will wait indefinitely by default; kill and restart it if needed — it will
resume from where it left off.

### `No arena state found`

Run `pixi run arena init ...` first to create the state file.

### Verify commands fail in gating mode

In `--verify-mode gating`, failing verify commands override consensus and force
another round. Check the verify command output in the report or in
`arenas/NNNN/artifacts/verify_results_*.md`. Common causes:

- Tests that depend on the local environment (missing dependencies, wrong
  Python version).
- Tests that are unrelated to the task and were already failing before the
  arena run.

### Rate limiting on `/repositories` endpoint

The Cursor API may rate-limit repository listing requests. The API client
retries with exponential backoff (up to 5 attempts). If you hit persistent
rate limits, wait a few minutes before retrying.

### Extraction failures (no `<solution>` tag)

When an agent's response lacks the expected `<solution>` XML tag, the
orchestrator sends a re-prompt asking the agent to reformat. If the retry also
fails, the full response is used as the solution (with a warning logged).

---

## TODOs

- [ ] **Webhook support.** Replace polling with webhooks for agent status
      updates if the API supports them.
- [ ] **Context management strategies.** Implement `diff` and `fresh` context
      modes for large tasks (infrastructure is in place, strategies not yet
      wired).
