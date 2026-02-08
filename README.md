# Agentic Arena

Multi-model consensus via Cursor Cloud Agents.

Three frontier models solve a task through iterative rounds of independent work,
anonymized critique, informed revision, and verified consensus. The orchestrator
is a stateless Python script that communicates with the
[Cursor Cloud Agents API](https://docs.cursor.com) over HTTP -- no tmux, no
terminal scraping, no filesystem polling.

```
solve --> evaluate --> revise --> verify
                                   |-- CONSENSUS (score >= 8) --> done
                                   |-- CONTINUE  (score < 8)  --> evaluate (next round)
                                   '-- max rounds reached     --> done
```

See [`proposal.md`](proposal.md) for the full design rationale.

---

## Getting started

### Prerequisites

- [pixi](https://pixi.sh) for package management (Python 3.13 is installed automatically).
- A **Cursor API key** exported as `CURSOR_API_KEY`.
- A **GitHub repository** connected to your Cursor account.

### Install

```bash
# Install pixi if you don't have it
curl -fsSL https://pixi.sh/install.sh | bash
source ~/.bashrc

# Clone and install dependencies (pixi handles everything)
git clone https://github.com/maresb/cursor-agentic-arena.git
cd cursor-agentic-arena
pixi install
```

All dependencies (Python 3.13, requests, pydantic, typer, pytest, mypy, ruff)
are declared in `pixi.toml` and resolved via conda-forge. No pip, no venv.

### Verify the install

```bash
pixi run test       # 67 unit tests
pixi run lint       # ruff
pixi run typecheck  # mypy
```

---

## Usage

The CLI has three commands: **init**, **run**, and **status**.

### Initialize an arena

```bash
pixi run arena init \
  --task "Review the authentication module for security issues" \
  --repo owner/repo \
  --base-branch main \
  --max-rounds 3
```

This creates `arena/state.json` with a randomized alias-to-model mapping
(Agent A/B/C shuffled across Claude Opus, GPT, Gemini) and sets the phase to
`solve`.

Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--base-branch` | `main` | Branch the agents work from |
| `--max-rounds` | `3` | Cap on evaluate-revise-verify cycles (1-10) |
| `--verify-commands` | none | Comma-separated commands to run on consensus (e.g. `"pixi run pytest,pixi run mypy ."`) |
| `--arena-dir` | `arena` | Directory for state file and output archives |

### Run the orchestrator

```bash
export CURSOR_API_KEY="your-key-here"
pixi run arena run --arena-dir arena
```

The orchestrator loops through phases until consensus is reached or max rounds
are exhausted. It is fully **resumable** -- kill it at any point and restart;
previously completed work is never re-done.

Progress is logged to both stderr and `arena/orchestrator.log`. Add `-v` for
DEBUG-level output.

### Check status

```bash
pixi run arena status --arena-dir arena
```

Shows the current phase, round, alias mapping, agent IDs, and per-agent
progress.

---

## Testing with fewer models

The full arena uses three models in parallel. For incremental validation or to
reduce cost, you can test with one or two models by editing `arena/state.json`
after initialization.

### Single-model smoke test

This validates the end-to-end flow -- API connectivity, agent launch, polling,
conversation retrieval, and XML extraction -- using a single model.

1. Initialize normally:

```bash
pixi run arena init --task "Explain the builder pattern in Python" --repo owner/repo
```

2. Edit `arena/state.json` to keep only one agent. Remove two entries from
   `alias_mapping` and `phase_progress`, leaving e.g.:

```json
{
  "config": { "task": "...", "repo": "...", "max_rounds": 1 },
  "alias_mapping": { "agent_a": "opus" },
  "phase_progress": { "agent_a": "pending" },
  ...
}
```

3. Run the orchestrator. The solve phase will launch one agent. The evaluate
   phase will send a follow-up with an empty solutions list (since there are
   no *other* agents to critique), but the round-trip validates the entire
   pipeline.

```bash
pixi run arena run --arena-dir arena -v
```

4. Inspect the outputs in `arena/round0/` and the conversation in
   `arena/state.json`.

### Two-model test

Same approach, but keep two entries in `alias_mapping`:

```json
{
  "alias_mapping": { "agent_a": "opus", "agent_b": "gpt" },
  "phase_progress": { "agent_a": "pending", "agent_b": "pending" }
}
```

Each agent critiques the one other solution during evaluate. The verify phase
selects a judge from the two. This is a cheaper way to test the full
solve-evaluate-revise-verify loop before committing to a three-model run.

### Running only the unit tests (no API)

The test suite mocks all API calls and validates control flow, state
transitions, extraction logic, and prompt construction:

```bash
pixi run test
```

No `CURSOR_API_KEY` needed. All 67 tests run in under a second.

---

## Project structure

```
arena/
  __init__.py        Package root (version)
  __main__.py        Typer CLI: init, run, status
  api.py             Cursor Cloud Agents HTTP client with retry/backoff
  extraction.py      XML tag parsing, Verdict model, fallback heuristics
  orchestrator.py    Main loop, round archival, report generation
  phases.py          Phase functions: solve, evaluate, revise, verify
  prompts.py         Prompt templates and model name mapping
  state.py           Pydantic models (ArenaConfig, ArenaState), persistence

tests/
  test_cli.py        CLI commands via Typer CliRunner
  test_extraction.py XML parsing, verdict model, fallbacks
  test_orchestrator.py Report generation
  test_phases.py     Phase control flow with mock API
  test_prompts.py    Prompt template content
  test_state.py      Pydantic models, serialization round-trips

pixi.toml            Dependencies and task definitions
proposal.md          Full design document
```

### Key types

| Type | Module | Purpose |
|---|---|---|
| `ArenaConfig` | `state.py` | Frozen config: task, repo, branch, rounds, verify commands |
| `ArenaState` | `state.py` | Full mutable state persisted to `state.json` |
| `Phase` | `state.py` | StrEnum: solve, evaluate, revise, verify, done |
| `ProgressStatus` | `state.py` | StrEnum: pending, sent, done |
| `ModelName` | `state.py` | StrEnum: opus, gpt, gemini |
| `Verdict` | `extraction.py` | Parsed judge verdict with decision, score, etc. |
| `CursorCloudAPI` | `api.py` | HTTP client for the Cursor Cloud Agents endpoints |

---

## Current state

**What works:**

- Full orchestrator implementation covering all four phases (solve, evaluate,
  revise, verify) with parallel agent execution within each phase.
- Resumable state -- the orchestrator can be killed and restarted at any point.
  State is atomically written after every meaningful step.
- Anonymized aliases randomized per run with shuffled presentation order per
  prompt to prevent positional bias.
- Rotating judge selection across verify rounds.
- XML-delimited output protocol with fallback heuristics for extraction
  failures.
- Archival of each round's solutions, analyses, critiques, and verdicts to
  Markdown files on disk.
- Final report generation summarizing the arena run.
- Typer CLI with init, run, and status commands.
- Pydantic-backed config and state with validated serialization.
- 67 unit tests, ruff lint, and mypy type checking all pass.

**What has not been validated:**

- The Cursor Cloud Agents API (`api.cursor.com/v0/agents`) has not been tested
  with live calls. The API wrapper is built from the documented endpoints in
  `proposal.md` -- the actual API may differ in URL structure, authentication
  scheme, request/response shapes, or status values.
- Real multi-agent runs have not been executed. The phase logic is tested with
  mocked API responses only.
- Cloud RAG indexing quality compared to local indexing is unknown.

---

## TODOs

### API validation

- [ ] Confirm the Cursor Cloud Agents API base URL, auth header format, and
      endpoint paths match the real API.
- [ ] Validate the agent lifecycle states (`CREATING`, `RUNNING`, `FINISHED`)
      and adjust `wait_for_agent` if the actual API uses different values.
- [ ] Test `GET /agents/{id}/conversation` response shape -- confirm
      `messages` key exists with `role`/`content` fields.

### Incremental testing (from proposal Section 15)

- [ ] **Single-agent smoke test.** Launch one agent, poll until finished,
      retrieve conversation, confirm XML tags parse correctly.
- [ ] **Three-agent test.** Launch three agents with different models on the
      same repo. Verify separate branches, no interference.
- [ ] **Resilience test.** Run solve phase, kill orchestrator after 2 agents
      finish, restart, verify the third resumes without re-launching the
      finished agents.
- [ ] **Full arena.** Run a task where models are likely to disagree. Inspect
      critiques for genuine engagement and verify verdict for real
      disagreement enumeration.

### Features

- [ ] **Configurable model list.** Allow users to specify which models to use
      and how many agents to run (1-3) without manual state editing.
- [ ] **Context management.** Implement summarization, diff-only views, and
      fresh-agent-per-round strategies for large tasks (proposal Section 8).
- [ ] **Token usage monitoring.** Log approximate token counts per follow-up
      and warn when approaching context limits.
- [ ] **Re-prompt on extraction failure.** When XML tags are missing, send
      `RETRY_PROMPT` as a follow-up and re-extract (the template exists in
      `extraction.py` but is not wired into the phase logic).
- [ ] **Webhook support.** Replace polling with webhooks for agent status
      updates if the API supports them.

### Quality

- [ ] Integration test harness that runs against the live API with a test
      repo.
- [ ] Cost tracking and per-run spend estimation.
- [ ] CI pipeline (GitHub Actions) for lint, typecheck, and unit tests.
