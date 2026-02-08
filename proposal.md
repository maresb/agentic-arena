# The Agentic Arena Proposal

### Multi-model consensus via Cursor Cloud Agents

---

## 1. Concept

Three frontier models — Claude Opus 4.6, GPT-5.2, Gemini 3 Pro — solve a task through iterative rounds of independent work, anonymized critique, informed revision, and verified consensus. The primary use cases are answering a technical question, or code review and refactoring against a shared codebase.

**The loop:**

1. **Solve.** Each model works independently on its own branch, producing a solution file and an analysis file.
2. **Evaluate.** Each model reads the other two solutions and writes a critique — strengths, weaknesses, errors — without revising its own work yet.
3. **Revise.** Each model reads all three critiques (including critiques of its own work) and produces a revised solution.
4. **Verify.** A rotating judge reads all revised solutions and critiques, enumerates remaining disagreements, and either confirms consensus or sends the loop back to Evaluate.

Agents never see model names — only neutral aliases (Agent A, B, C), randomized per run and shuffled in presentation order per prompt.

The orchestrator is stateless: all state lives in `arena/state.json`, so it can be killed, modified, and restarted at any point without losing progress.

---

## 2. Why Cursor Cloud Agents

Cursor's Cloud Agents API (`api.cursor.com/v0/agents`) provides the ideal backend for the arena. Each API call launches an autonomous agent in an isolated Ubuntu VM that clones a GitHub repo, works on its own branch, and can optionally open a PR when finished. The API supports model selection per agent, follow-up messages, status polling, and structured conversation retrieval.

This eliminates most of the infrastructure complexity that dominated earlier designs:

| Concern | Local (tmux + libtmux) | Cloud Agents API |
|---|---|---|
| Security | Dev container + deny-by-default perms | Cursor's isolated VMs; nothing local |
| Filesystem isolation | Git worktrees | Automatic per-agent branches |
| Completion detection | File-stable + pane-idle heuristics | Poll status until `FINISHED` |
| Content extraction | Terminal scraping or file parsing | `GET /conversation` returns JSON |
| Observability | `tmux attach` for live view | Cursor web UI; conversation API |
| Orchestrator | libtmux + signal handlers + pipe-pane | Python script making HTTP calls |
| Codebase context | RAG indexing from worktree | Same RAG indexing in the cloud VM |

**Trade-offs accepted:**

- **Latency.** Each agent turn is a full autonomous run (minutes, not seconds). A 3-round arena takes ~30-60 minutes rather than ~10-15.
- **Cost.** Cloud agents use Max Mode pricing. Three agents across multiple rounds is nontrivial spend.
- **Observability.** No real-time terminal view. You monitor via status polling and post-hoc conversation retrieval. The Cursor web UI at `cursor.com/agents` provides a manual observation point.

These are acceptable for a code review use case where quality matters more than speed, and where the orchestrator simplicity and security guarantees outweigh the latency and cost.

### Alternatives evaluated and rejected

**Local tmux + libtmux.** Each agent runs as an interactive `cursor-agent` session in a tmux pane. Provides real-time observability and fast conversational turns, but requires terminal scraping, approval handling, dev container sandboxing, worktree management, and fragile completion detection. Appropriate as a fallback if cloud latency or cost is prohibitive.

**Cursor headless mode (`--print`).** Ideal in principle (`--output-format stream-json` gives structured output), but lifecycle bugs (process hangs, doesn't exit) make it unreliable as of January 2026. Worth revisiting when stabilized.

**Direct API calls (Anthropic + OpenAI + Google).** Clean structured responses, but three integrations, three billing relationships, and no codebase indexing.

---

## 3. Architecture

```
 ┌──────────────────────────────────────────────────────┐
 │                  Python Orchestrator                  │
 │                    (stateless)                        │
 │                                                      │
 │  Reads:  arena/state.json                            │
 │  Calls:  Cursor Cloud Agents API                     │
 │  Writes: state.json after every step                 │
 │                                                      │
 │  Kill → change code → restart → resumes cleanly      │
 └───────────┬──────────────┬──────────────┬────────────┘
             │              │              │
        POST /v0/agents  POST /v0/agents  POST /v0/agents
        model=opus-4.6   model=gpt-5.2   model=gemini-3-pro
             │              │              │
     ┌───────▼──┐    ┌─────▼────┐   ┌─────▼──────┐
     │ Agent A  │    │ Agent B  │   │ Agent C    │
     │ (cloud)  │    │ (cloud)  │   │ (cloud)    │
     │ own VM   │    │ own VM   │   │ own VM     │
     │ own branch    │ own branch   │ own branch │
     └──────────┘    └──────────┘   └────────────┘
             │              │              │
             └──────────────┴──────────────┘
                     GitHub repo
```

The orchestrator is a Python script that communicates exclusively via HTTP. No tmux, no terminal scraping, no filesystem polling. Agent IDs and conversation content are the only state.

---

## 4. The Two-File Output Protocol

Each agent produces two files per phase:

- **`solution.md`** — the core proposal (plan + changes). Kept together for coherence.
- **`analysis.md`** — the meta-analysis (risks, open questions, disagreements). Routed separately during the loop.

This split enables selective information sharing: agents read each other's solutions during evaluation but only the judge reads the analysis files. It avoids fragmenting the agent's thinking (five separate files) while still allowing the orchestrator to control what each participant sees.

In cloud mode, agents write these files to their branch. The orchestrator retrieves them via the GitHub API or the conversation history, then references them in follow-up prompts. For the evaluate and revise phases, the orchestrator pastes the relevant content into follow-ups rather than asking agents to cross-reference branches — this is more reliable than instructing agents to `git fetch` from sibling branches.

### File naming convention

```
arena/round00/a_solution_f7a3.md     arena/round00/a_analysis_f7a3.md
arena/round00/b_solution_2c8e.md     arena/round00/b_analysis_2c8e.md
arena/round00/c_solution_91d0.md     arena/round00/c_analysis_91d0.md
arena/round01/a_critique_b4f2.md     # Evaluate phase — critique only
arena/round01/b_critique_8a1c.md
arena/round01/c_critique_e3d7.md
arena/round01/a_solution_d4e5.md     arena/round01/a_analysis_d4e5.md  # Revised
arena/round01/b_solution_7f21.md     arena/round01/b_analysis_7f21.md
arena/round01/c_solution_a3b9.md     arena/round01/c_analysis_a3b9.md
arena/round01/verify_c_e8f1.md       # Verification verdict
```

The 4-character hash (UUID prefix) prevents stale-file collisions across rounds.

---

## 5. Anonymization

The orchestrator maintains a mapping randomized per run:

```python
# Example — shuffled each run
alias_mapping = {"agent_a": "opus", "agent_b": "gemini", "agent_c": "gpt"}
```

All prompts, filenames, and cross-references use aliases. Agents see "Agent A's solution" and "Agent B's critique," never model names. Presentation order is also shuffled per prompt to prevent positional bias. The mapping is recorded in `state.json` for the human and the final report.

---

## 6. The Consensus Loop

### Phase 1: Solve (parallel)

Launch three cloud agents simultaneously, each with a different model, pointed at the same repo:

```python
def step_solve(state, api):
    agents_launched = {}
    for alias, model in state["alias_mapping"].items():
        if state["phase_progress"].get(alias) == "done":
            continue
        agent = api.launch(
            prompt=solve_prompt(state["task"]),
            repo=state["repo"],
            ref=state["base_branch"],
            model=MODELS[model],
        )
        agents_launched[alias] = agent["id"]
        state["agent_ids"][alias] = agent["id"]
        save_state(state)

    # Poll until all finish
    for alias, agent_id in agents_launched.items():
        wait_for_agent(api, agent_id)
        conversation = api.get_conversation(agent_id)
        state["solutions"][alias] = extract_solution(conversation)
        state["analyses"][alias] = extract_analysis(conversation)
        state["phase_progress"][alias] = "done"
        save_state(state)

    state["phase"] = "evaluate"
    state["round"] += 1
    state["phase_progress"] = {a: "pending" for a in state["alias_mapping"]}
```

**Solve prompt:**
```
[task description]

Write your solution as two Markdown sections in your response:

SOLUTION:
## PLAN — Numbered key decisions with rationale.
## CHANGES — Unified diff or precise change descriptions.

ANALYSIS:
## RISKS — Known risks, edge cases, trade-offs.
## OPEN QUESTIONS — Uncertainties requiring verification.
```

Because we're using the conversation API (not file-based output), agents write their response as structured text in the conversation. The orchestrator parses the `SOLUTION:` and `ANALYSIS:` sections from the conversation JSON. This avoids reliance on agents writing files to specific paths — the conversation is the source of truth.

### Phase 2: Evaluate (parallel)

Each agent receives the other two agents' solution sections (not analyses) and writes a critique-only response. No revision yet.

```python
def step_evaluate(state, api):
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue

        others = [(k, v) for k, v in state["solutions"].items() if k != alias]
        random.shuffle(others)  # Presentation-order neutrality

        api.followup(
            agent_id=state["agent_ids"][alias],
            prompt=evaluate_prompt(others),
        )
        wait_for_agent(api, state["agent_ids"][alias])
        conversation = api.get_conversation(state["agent_ids"][alias])
        state["critiques"][alias] = extract_latest_message(conversation)
        state["phase_progress"][alias] = "done"
        save_state(state)

    state["phase"] = "revise"
    state["phase_progress"] = {a: "pending" for a in state["alias_mapping"]}
```

**Evaluate prompt:**
```
Read these solutions from other agents:

=== AGENT [X] ===
[solution content]

=== AGENT [Y] ===
[solution content]

Write a critique of each. DO NOT revise your own solution yet.

For each agent's solution:
- Strengths: what they do well.
- Weaknesses: what's wrong or suboptimal.
- Errors: anything factually incorrect.

Then state your position:
- What you're keeping from your original approach and why.
- What you'd adopt from others and why.
- What you still disagree on and why.
```

This separation forces genuine engagement. The model must articulate what's good and bad about each solution before it's allowed to change anything.

### Phase 3: Revise (parallel)

Each agent reads all three critiques — including criticism of its own work — and produces a revised solution.

```python
def step_revise(state, api):
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue

        all_critiques = [(k, v) for k, v in state["critiques"].items()]
        random.shuffle(all_critiques)

        api.followup(
            agent_id=state["agent_ids"][alias],
            prompt=revise_prompt(all_critiques),
        )
        wait_for_agent(api, state["agent_ids"][alias])
        conversation = api.get_conversation(state["agent_ids"][alias])
        state["solutions"][alias] = extract_solution_from_latest(conversation)
        state["analyses"][alias] = extract_analysis_from_latest(conversation)
        state["phase_progress"][alias] = "done"
        save_state(state)

    state["phase"] = "verify"
    state["phase_progress"] = {"verify": "pending"}
```

**Revise prompt:**
```
Here is how all three agents (including you) were critiqued:

=== CRITIQUE BY AGENT [X] ===
[critique content]

=== CRITIQUE BY AGENT [Y] ===
[critique content]

=== CRITIQUE BY AGENT [Z] ===
[critique content]

Produce your REVISED solution, incorporating the strongest elements.
Use the same format: SOLUTION (PLAN + CHANGES) and ANALYSIS (RISKS + QUESTIONS).

In your ANALYSIS, include a DISAGREEMENTS section listing any remaining
substantive disagreements with the other approaches, or "None."
```

The agent now knows exactly what was criticized about its work — not just what others proposed, but why others think its approach is wrong. This produces more thoughtful revisions than the prior design where evaluation and revision were combined.

### Phase 4: Verify

A rotating judge reads all revised solutions and all analyses (including disagreement sections). The judge is selected to avoid repeating the same agent.

```python
def step_verify(state, api):
    # Select judge — rotate through aliases
    used = state.get("judge_history", [])
    available = [a for a in state["alias_mapping"] if a not in used] or list(state["alias_mapping"])
    judge = available[0]
    state["judge_history"].append(judge)

    # Collect inputs
    solutions = [(k, v) for k, v in state["solutions"].items()]
    analyses = [(k, v) for k, v in state["analyses"].items()]
    random.shuffle(solutions)

    api.followup(
        agent_id=state["agent_ids"][judge],
        prompt=verify_prompt(solutions, analyses),
    )
    wait_for_agent(api, state["agent_ids"][judge])
    conversation = api.get_conversation(state["agent_ids"][judge])
    verdict = extract_latest_message(conversation)

    if "CONSENSUS" in verdict.split("\n")[0]:
        state["phase"] = "done"
        state["completed"] = True
        state["final_verdict"] = verdict
    elif state["round"] >= state["max_rounds"]:
        state["phase"] = "done"
        state["completed"] = True
    else:
        state["phase"] = "evaluate"
        state["phase_progress"] = {a: "pending" for a in state["alias_mapping"]}

    save_state(state)
```

**Verify prompt:**
```
You are the consensus judge. Read these revised solutions:

=== AGENT [X] SOLUTION ===
[solution content]

=== AGENT [Y] SOLUTION ===
[solution content]

=== AGENT [Z] SOLUTION ===
[solution content]

And these self-reported analyses (including any remaining disagreements):

=== AGENT [X] ANALYSIS ===
[analysis content]

=== AGENT [Y] ANALYSIS ===
[analysis content]

=== AGENT [Z] ANALYSIS ===
[analysis content]

Perform this analysis in order:

AGREEMENT POINTS — Specific points where all three converge.

DISAGREEMENT POINTS — Every remaining difference. For each:
state which approach is correct and why.

MOST SIGNIFICANT DIFFERENCE — Identify the single biggest remaining
difference. Is it trivial (style/naming) or substantive (logic/architecture)?

CONVERGENCE SCORE — 1-10. Score 8+ only if all differences are trivial.

VERDICT — First line must be exactly CONSENSUS or CONTINUE.
If CONSENSUS: provide the best merged solution.
If CONTINUE: describe the substantive disagreements that need resolution.
```

The verify prompt incorporates the challenge mechanism (identifying the most significant difference and classifying it as trivial or substantive) directly, eliminating the need for a separate challenge phase. The agents' own disagreement sections provide the advocate signal — if an agent lists disagreements, they're visible to the judge without a separate prompt.

### Phase transitions

```
solve → evaluate → revise → verify
                                 ├─ CONSENSUS → done
                                 ├─ CONTINUE  → evaluate (next round)
                                 └─ max rounds → done
```

Four phases, 10 prompts per round (3 + 3 + 3 + 1). No remedial phases needed.

---

## 7. Orchestrator Implementation

### API wrapper

```python
import requests
import time

class CursorCloudAPI:
    BASE = "https://api.cursor.com/v0"

    def __init__(self, api_key: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def launch(self, prompt: str, repo: str, ref: str, model: str = None) -> dict:
        body = {
            "prompt": {"text": prompt},
            "source": {"repository": repo, "ref": ref},
        }
        if model:
            body["model"] = model
        r = requests.post(f"{self.BASE}/agents", json=body, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def followup(self, agent_id: str, prompt: str) -> dict:
        r = requests.post(
            f"{self.BASE}/agents/{agent_id}/followup",
            json={"prompt": {"text": prompt}},
            headers=self.headers,
        )
        r.raise_for_status()
        return r.json()

    def status(self, agent_id: str) -> dict:
        r = requests.get(f"{self.BASE}/agents/{agent_id}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    def get_conversation(self, agent_id: str) -> list[dict]:
        r = requests.get(
            f"{self.BASE}/agents/{agent_id}/conversation",
            headers=self.headers,
        )
        r.raise_for_status()
        return r.json().get("messages", [])


def wait_for_agent(api: CursorCloudAPI, agent_id: str,
                   timeout=600, poll_interval=10) -> str:
    start = time.time()
    while time.time() - start < timeout:
        info = api.status(agent_id)
        if info["status"] == "FINISHED":
            return info["status"]
        if info["status"] not in ("CREATING", "RUNNING"):
            raise RuntimeError(f"Agent {agent_id} in unexpected state: {info['status']}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Agent {agent_id} did not finish within {timeout}s")
```

### State management

```python
import json, os

def load_state(path="arena/state.json") -> dict | None:
    if os.path.exists(path):
        return json.load(open(path))
    return None

def save_state(state: dict, path="arena/state.json"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(state, open(path, "w"), indent=2)

def init_state(task, repo, base_branch="main", max_rounds=3) -> dict:
    models = ["opus", "gpt", "gemini"]
    random.shuffle(models)
    aliases = ["agent_a", "agent_b", "agent_c"]
    return {
        "task": task,
        "repo": repo,
        "base_branch": base_branch,
        "max_rounds": max_rounds,
        "alias_mapping": dict(zip(aliases, models)),
        "agent_ids": {},
        "round": 0,
        "phase": "solve",
        "phase_progress": {a: "pending" for a in aliases},
        "solutions": {},
        "analyses": {},
        "critiques": {},
        "judge_history": [],
        "completed": False,
        "final_verdict": None,
    }
```

### Main loop

```python
def run_orchestrator(arena_dir="arena"):
    state = load_state(f"{arena_dir}/state.json")
    api = CursorCloudAPI(os.environ["CURSOR_API_KEY"])

    while not state["completed"]:
        phase = state["phase"]
        if phase == "solve":     step_solve(state, api)
        elif phase == "evaluate": step_evaluate(state, api)
        elif phase == "revise":  step_revise(state, api)
        elif phase == "verify":  step_verify(state, api)
        save_state(state, f"{arena_dir}/state.json")

    print(f"Arena complete. Rounds: {state['round']}.")
    print(f"Verdict: {'Consensus' if state['final_verdict'] else 'No consensus'}")
    print(f"Alias mapping: {state['alias_mapping']}")
```

---

## 8. Observability

**During runs:** Poll agent status via the API. The Cursor web UI at `cursor.com/agents` shows all active agents, their progress, and allows manual "enter the machine" for inspection.

**Post-hoc:** `GET /v0/agents/{id}/conversation` returns the complete message history as structured JSON for any agent. All conversations are preserved until the agent is deleted.

**Logging:** The orchestrator logs every API call, state transition, and extracted content to `arena/orchestrator.log`. The state file is a complete, human-readable record of the arena's progression.

**Manual intervention:** Send a follow-up to any agent via the API or the Cursor web UI at any time. The orchestrator will pick up the new conversation content on its next poll. To pause the orchestrator, kill it; to resume, restart it — the state file ensures continuity.

---

## 9. Why This Phase Design

Earlier iterations used a five-phase loop: solve → review → judge → challenge → advocate. This was revised for three reasons:

**Evaluation and revision were conflated.** The old "review" phase asked agents to critique other solutions and produce a revised solution in one step. This let models skip genuine evaluation and jump to synthesis, causing regression-to-the-mean. Splitting into evaluate (critique only) → revise (informed by all critiques) forces genuine engagement before any revision occurs.

**Challenge and advocate were remedial.** They existed to patch problems with the judge — premature consensus and outlier suppression. With explicit disagreement tracking (agents self-report remaining disagreements in their analysis files) and a more rigorous verify prompt (that incorporates the challenge question directly), these separate phases are unnecessary.

**Fewer sequential steps means faster wall-clock time.** With cloud agents, each phase is a full agent run. Four phases (solve → evaluate → revise → verify) with parallelism within each phase is faster than five phases with less parallelism. Solve, evaluate, and revise all run three agents in parallel.

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Agent produces unstructured response (no SOLUTION/ANALYSIS sections) | **High** | Parse best-effort; re-prompt via follow-up with explicit format reminder |
| Consensus regression to the mean | **High** | Evaluate/revise split forces genuine critique; verify prompt requires classifying disagreements as trivial or substantive |
| Cloud agent latency (minutes per turn) | **Medium** | Parallel execution within phases; accept ~30-60 min per run |
| Max Mode cost | **Medium** | Limit rounds (default 3); use cheaper models for verify if available |
| Cross-agent content bloat in follow-ups | **Medium** | Share only solution sections during evaluate; full analyses only to judge |
| API rate limits (beta) | **Medium** | Configurable delays between launches; retry with backoff |
| Agent goes off-task during autonomous run | **Medium** | Post-hoc conversation review; follow-up to course-correct |
| Model bias from alias ordering | **Low** | Aliases randomized per run; presentation order shuffled per prompt |
| Orchestrator crash | **Low** | Stateless design; state.json saved after every step |

---

## 11. Fallback: Local tmux Architecture

If cloud agent latency or cost is prohibitive, the arena can run locally using tmux + libtmux. The key differences:

- Agents run as interactive `cursor-agent` sessions in tmux panes (one per model, each in its own git worktree).
- The orchestrator sends prompts via `pane.send_keys()` and instructs agents to write output to Markdown files.
- Completion requires both file stability (size unchanged) and pane idle (terminal content unchanged).
- Approval handling via `capture_pane()` regex detection.
- A dev container provides sandboxing (deny-by-default permissions, isolated filesystem).
- Human observer attaches via `tmux attach -t arena` (or `byobu attach`) for real-time visibility.

The consensus loop, phase structure, anonymization, and stateless orchestrator design are identical — only the transport layer changes.

---

## 12. Getting Started

1. **Get a Cursor API key** from your dashboard. Ensure your GitHub repo is connected.
2. **Single-agent test.** Launch one cloud agent with a simple task. Poll until finished. Retrieve the conversation. Verify structured content is extractable.
3. **Three-agent test.** Launch three agents with different models on the same repo. Verify they create separate branches and don't interfere with each other.
4. **Run the solve phase.** Initialize state, run `step_solve`. Kill the orchestrator after 2 agents finish. Restart. Verify the third resumes correctly.
5. **Full arena.** Run a task where models are likely to disagree. Inspect the evaluate-phase critiques to verify genuine engagement. Inspect the verify verdict to confirm the judge enumerates real disagreements rather than rubber-stamping.
6. **Review the alias mapping** in the final state file. Check whether the "best" solution correlates with a specific model, or whether consensus genuinely synthesized from all three.
