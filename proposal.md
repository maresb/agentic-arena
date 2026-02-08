# The Agentic Arena Proposal

### Multi-model consensus via Cursor Cloud Agents

---

## 1. Concept

Three frontier models — Claude Opus 4.6, GPT-5.2, Gemini 3 Pro — solve a task through iterative rounds of independent work, anonymized critique, informed revision, and verified consensus. The primary use cases are answering a technical question, or code review and refactoring against a shared codebase.

**The loop:**

1. **Solve.** Each model works independently on its own branch, producing a solution and an analysis.
2. **Evaluate.** Each model reads the other two solutions and writes a critique — strengths, weaknesses, errors — without revising its own work yet.
3. **Revise.** Each model reads all three critiques (including critiques of its own work) and produces a revised solution.
4. **Verify.** A rotating judge reads all revised solutions and critiques, enumerates remaining disagreements, and either confirms consensus or sends the loop back to Evaluate.

Agents never see model names — only neutral aliases (Agent A, B, C), randomized per run and shuffled in presentation order per prompt.

The orchestrator is stateless: all state lives in `arena/state.json`, so it can be killed, modified, and restarted at any point without losing progress.

### Non-goals

- **Real-time interaction.** The arena is a batch process. Optimizing for sub-second latency is out of scope.
- **Truth guarantees.** Consensus among models does not guarantee correctness. The arena improves quality through structured critique, not epistemic certification.
- **Collusion prevention.** Models may recognize each other's stylistic fingerprints despite anonymization. The aliases mitigate casual bias, not adversarial identification.
- **General-purpose agent framework.** This is a single-purpose orchestrator for multi-model debate, not a reusable agent platform.

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
| Codebase context | Local RAG indexing from worktree | Cloud RAG indexing (expected parity; validate during single-agent test) |

**Trade-offs accepted:**

- **Latency.** Each agent turn is a full autonomous run (minutes, not seconds). A 3-round arena takes ~30-60 minutes rather than ~10-15.
- **Cost.** Cloud agents use Max Mode pricing. Three agents across multiple rounds is nontrivial spend (see Section 11 for estimates).
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

## 4. Output Protocol

### Source of truth: conversations

Each agent produces its output as structured text in the conversation. The orchestrator parses responses to extract solution and analysis sections. The conversation API (`GET /v0/agents/{id}/conversation`) is the canonical source of truth — the orchestrator never relies on agents writing files to specific paths.

Agents are prompted to delimit their output with XML tags for robust parsing:

```
<solution>
## PLAN — Numbered key decisions with rationale.
## CHANGES — Unified diff or precise change descriptions.
</solution>

<analysis>
## RISKS — Known risks, edge cases, trade-offs.
## OPEN QUESTIONS — Uncertainties requiring verification.
</analysis>
```

XML tags are more reliably preserved by LLMs than uppercase headers or custom delimiters, and they are unambiguous to parse even when the model produces preamble text.

### Archival file export

After extracting content from conversations, the orchestrator archives each round's outputs to files on disk. This provides a human-readable audit trail and enables post-hoc analysis:

```
arena/round0/a_solution_f7a3bc12.md     arena/round0/a_analysis_f7a3bc12.md
arena/round0/b_solution_2c8e91d0.md     arena/round0/b_analysis_2c8e91d0.md
arena/round0/c_solution_91d04a7b.md     arena/round0/c_analysis_91d04a7b.md
arena/round1/a_critique_b4f2e8c1.md     # Evaluate phase — critique only
arena/round1/b_critique_8a1cd3f9.md
arena/round1/c_critique_e3d76b2a.md
arena/round1/a_solution_d4e5f012.md     arena/round1/a_analysis_d4e5f012.md
arena/round1/b_solution_7f21a3b9.md     arena/round1/b_analysis_7f21a3b9.md
arena/round1/c_solution_a3b9c4d5.md     arena/round1/c_analysis_a3b9c4d5.md
arena/round1/verify_c_e8f10a2b.md       # Verification verdict
```

The 8-character hash (UUID prefix) prevents stale-file collisions across runs. Round numbering: round 0 is the initial solve, round N is the Nth evaluate→revise→verify cycle.

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

### Round semantics

A **round** counts completed evaluate→revise→verify cycles. Round 0 is the initial solve. `state["round"]` increments after each verify phase, and `max_rounds` caps the total number of verify cycles (default: 3). File naming and state references both use this numbering.

### Phase 1: Solve (parallel)

Launch three cloud agents simultaneously, each with a different model, pointed at the same repo:

```python
def step_solve(state: dict, api: CursorCloudAPI) -> None:
    # Launch agents that haven't started yet
    for alias, model in state["alias_mapping"].items():
        if state["phase_progress"].get(alias) == "done":
            continue
        if alias not in state["agent_ids"]:
            agent = api.launch(
                prompt=solve_prompt(state["task"]),
                repo=state["repo"],
                ref=state["base_branch"],
                model=MODELS[model],
            )
            state["agent_ids"][alias] = agent["id"]
            save_state(state)

    # Poll all pending agents until finished (truly parallel)
    pending = {
        alias: state["agent_ids"][alias]
        for alias in state["alias_mapping"]
        if state["phase_progress"].get(alias) != "done"
    }
    wait_for_all_agents(api, pending)

    # Extract content from all finished agents
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue
        conversation = api.get_conversation(state["agent_ids"][alias])
        solution, analysis = extract_solution_and_analysis(conversation)
        state["solutions"][alias] = solution
        state["analyses"][alias] = analysis
        state["phase_progress"][alias] = "done"
        save_state(state)

    state["phase"] = "evaluate"
    state["phase_progress"] = {a: "pending" for a in state["alias_mapping"]}
    save_state(state)
```

**Solve prompt:**
```
[task description]

Write your response with these XML-delimited sections:

<solution>
## PLAN — Numbered key decisions with rationale.
## CHANGES — Unified diff or precise change descriptions.
</solution>

<analysis>
## RISKS — Known risks, edge cases, trade-offs.
## OPEN QUESTIONS — Uncertainties requiring verification.
</analysis>
```

### Phase 2: Evaluate (parallel)

Each agent receives the other two agents' solution sections (not analyses) and writes a critique-only response. No revision yet. All follow-ups are sent before any polling begins, so agents work concurrently.

```python
def step_evaluate(state: dict, api: CursorCloudAPI) -> None:
    # Send all follow-ups first (parallel launch)
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue

        others = [(k, v) for k, v in state["solutions"].items() if k != alias]
        random.shuffle(others)  # Presentation-order neutrality

        api.followup(
            agent_id=state["agent_ids"][alias],
            prompt=evaluate_prompt(others),
        )

    # Poll all agents until finished (truly parallel)
    pending = {
        alias: state["agent_ids"][alias]
        for alias in state["alias_mapping"]
        if state["phase_progress"].get(alias) != "done"
    }
    wait_for_all_agents(api, pending)

    # Extract critiques
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue
        conversation = api.get_conversation(state["agent_ids"][alias])
        state["critiques"][alias] = extract_latest_response(conversation)
        state["phase_progress"][alias] = "done"
        save_state(state)

    state["phase"] = "revise"
    state["phase_progress"] = {a: "pending" for a in state["alias_mapping"]}
    save_state(state)
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

Each agent reads all three critiques — including criticism of its own work — and produces a revised solution. Same parallel pattern: send all follow-ups, then poll.

```python
def step_revise(state: dict, api: CursorCloudAPI) -> None:
    # Send all follow-ups first
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue

        all_critiques = [(k, v) for k, v in state["critiques"].items()]
        random.shuffle(all_critiques)

        api.followup(
            agent_id=state["agent_ids"][alias],
            prompt=revise_prompt(all_critiques),
        )

    # Poll all agents until finished
    pending = {
        alias: state["agent_ids"][alias]
        for alias in state["alias_mapping"]
        if state["phase_progress"].get(alias) != "done"
    }
    wait_for_all_agents(api, pending)

    # Extract revised solutions
    for alias in state["alias_mapping"]:
        if state["phase_progress"].get(alias) == "done":
            continue
        conversation = api.get_conversation(state["agent_ids"][alias])
        solution, analysis = extract_solution_and_analysis_from_latest(conversation)
        state["solutions"][alias] = solution
        state["analyses"][alias] = analysis
        state["phase_progress"][alias] = "done"
        save_state(state)

    state["phase"] = "verify"
    state["phase_progress"] = {"verify": "pending"}
    save_state(state)
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
Use the same XML-delimited format:

<solution>
## PLAN and ## CHANGES as before.
</solution>

<analysis>
## RISKS, ## OPEN QUESTIONS as before.
## DISAGREEMENTS — Any remaining substantive disagreements
with the other approaches, or "None."
</analysis>
```

The agent now knows exactly what was criticized about its work — not just what others proposed, but why others think its approach is wrong. This produces more thoughtful revisions than a design where evaluation and revision are combined.

### Phase 4: Verify

A rotating judge reads all revised solutions and all analyses (including disagreement sections). The judge is selected randomly from agents that haven't judged yet in this run.

```python
def step_verify(state: dict, api: CursorCloudAPI) -> None:
    # Select judge — rotate through aliases, randomize within available
    used = state.get("judge_history", [])
    available = [a for a in state["alias_mapping"] if a not in used]
    if not available:
        available = list(state["alias_mapping"])
    judge = random.choice(available)
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
    verdict_text = extract_latest_response(conversation)

    verdict = parse_verdict(verdict_text)

    if verdict["decision"] == "CONSENSUS":
        state["phase"] = "done"
        state["completed"] = True
        state["final_verdict"] = verdict_text
    elif state["round"] >= state["max_rounds"]:
        state["phase"] = "done"
        state["completed"] = True
        state["final_verdict"] = verdict_text
        state["consensus_reached"] = False
    else:
        state["round"] += 1
        state["phase"] = "evaluate"
        state["phase_progress"] = {a: "pending" for a in state["alias_mapping"]}

    save_state(state)
```

**Verify prompt:**
```
You are the consensus judge. You are one of the three contributors,
but you do not know which alias is yours. Judge each solution purely
on its technical merit, not on stylistic familiarity.

Read these revised solutions:

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

CONVERGENCE SCORE — 1-10. Score 8+ only if all remaining differences
are trivial (style, naming, formatting). Any substantive disagreement
on logic, architecture, or correctness caps the score at 7.

Wrap your structured verdict in XML:

<verdict>
decision: CONSENSUS or CONTINUE
convergence_score: [1-10]
remaining_disagreements: [count]
base_solution: [alias of best solution to use as base, or "merged"]
modifications: [list of specific changes to apply from other solutions]
</verdict>

If CONSENSUS (score >= 8): identify the best base solution by alias
and enumerate specific modifications to incorporate from the others.
Do NOT regenerate the full solution from scratch.

If CONTINUE (score < 8): describe the substantive disagreements
that need resolution in the next round.
```

The verify prompt explicitly instructs the judge to be unbiased toward its own work. It requires a structured verdict block for machine parsing, uses an operational definition of consensus (convergence score >= 8 with only trivial disagreements), and asks the judge to select a winner with modifications rather than regenerating the solution — avoiding truncation and hallucination risks.

### Phase transitions

```
solve → evaluate → revise → verify
                                 ├─ CONSENSUS (score >= 8) → done
                                 ├─ CONTINUE  (score < 8)  → evaluate (next round)
                                 └─ max rounds reached     → done
```

Four phases, 10 prompts per round (3 + 3 + 3 + 1). No remedial phases needed.

### Verification hooks for code tasks

When the arena task involves code changes, the verify phase can optionally include automated validation. The orchestrator can launch a dedicated agent (or instruct the judge) to run test commands against the winning solution's branch:

```python
if state.get("verify_commands"):
    for cmd in state["verify_commands"]:  # e.g. ["pixi run pytest", "pixi run mypy ."]
        api.followup(agent_id=state["agent_ids"][judge],
                     prompt=f"Run this command and report the result: {cmd}")
        wait_for_agent(api, state["agent_ids"][judge])
```

This grounds the consensus verdict in runtime evidence rather than purely rhetorical agreement. Configure `verify_commands` in the initial state to enable this.

---

## 7. Orchestrator Implementation

### API wrapper

```python
import requests
import time
import random
import logging

logger = logging.getLogger("arena")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
BASE_BACKOFF = 2.0  # seconds


class CursorCloudAPI:
    BASE = "https://api.cursor.com/v0"

    def __init__(self, api_key: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """HTTP request with retry and exponential backoff."""
        for attempt in range(MAX_RETRIES):
            r = requests.request(method, url, headers=self.headers, **kwargs)
            if r.status_code not in RETRYABLE_STATUS_CODES:
                r.raise_for_status()
                return r
            wait = BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                "Retryable %d from %s (attempt %d/%d), waiting %.1fs",
                r.status_code, url, attempt + 1, MAX_RETRIES, wait,
            )
            time.sleep(wait)
        r.raise_for_status()  # Final attempt failed — raise
        return r  # unreachable, but satisfies type checker

    def launch(self, prompt: str, repo: str, ref: str, model: str | None = None) -> dict:
        body: dict = {
            "prompt": {"text": prompt},
            "source": {"repository": repo, "ref": ref},
        }
        if model:
            body["model"] = model
        return self._request("POST", f"{self.BASE}/agents", json=body).json()

    def followup(self, agent_id: str, prompt: str) -> dict:
        return self._request(
            "POST",
            f"{self.BASE}/agents/{agent_id}/followup",
            json={"prompt": {"text": prompt}},
        ).json()

    def status(self, agent_id: str) -> dict:
        return self._request("GET", f"{self.BASE}/agents/{agent_id}").json()

    def get_conversation(self, agent_id: str) -> list[dict]:
        r = self._request("GET", f"{self.BASE}/agents/{agent_id}/conversation")
        return r.json().get("messages", [])


def wait_for_agent(api: CursorCloudAPI, agent_id: str,
                   timeout: int = 600, poll_interval: int = 10) -> str:
    """Poll a single agent until FINISHED."""
    start = time.time()
    while time.time() - start < timeout:
        info = api.status(agent_id)
        if info["status"] == "FINISHED":
            return info["status"]
        if info["status"] not in ("CREATING", "RUNNING"):
            raise RuntimeError(f"Agent {agent_id} in unexpected state: {info['status']}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Agent {agent_id} did not finish within {timeout}s")


def wait_for_all_agents(api: CursorCloudAPI, agents: dict[str, str],
                        timeout: int = 600, poll_interval: int = 10) -> None:
    """Poll multiple agents concurrently until all are FINISHED."""
    start = time.time()
    remaining = dict(agents)
    while remaining and time.time() - start < timeout:
        for alias, agent_id in list(remaining.items()):
            info = api.status(agent_id)
            if info["status"] == "FINISHED":
                remaining.pop(alias)
                logger.info("Agent %s (%s) finished", alias, agent_id)
            elif info["status"] not in ("CREATING", "RUNNING"):
                raise RuntimeError(f"Agent {agent_id} in unexpected state: {info['status']}")
        if remaining:
            time.sleep(poll_interval)
    if remaining:
        raise TimeoutError(f"Agents {list(remaining)} did not finish within {timeout}s")
```

### Content extraction

These functions are the most failure-prone part of the system. They use XML tag parsing with fallback heuristics:

```python
import re

def extract_xml_section(text: str, tag: str) -> str | None:
    """Extract content between <tag>...</tag>. Returns None if not found."""
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else None


def extract_solution_and_analysis(conversation: list[dict]) -> tuple[str, str]:
    """Extract solution and analysis from the latest assistant message."""
    text = _get_latest_assistant_message(conversation)
    solution = extract_xml_section(text, "solution")
    analysis = extract_xml_section(text, "analysis")

    if solution is None:
        logger.warning("No <solution> tag found; using full response as solution")
        solution = text
    if analysis is None:
        logger.warning("No <analysis> tag found; analysis will be empty")
        analysis = ""

    return solution, analysis


def extract_solution_and_analysis_from_latest(conversation: list[dict]) -> tuple[str, str]:
    """Same as above but for revised responses (later in conversation)."""
    return extract_solution_and_analysis(conversation)


def extract_latest_response(conversation: list[dict]) -> str:
    """Extract the most recent assistant message."""
    return _get_latest_assistant_message(conversation)


def _get_latest_assistant_message(conversation: list[dict]) -> str:
    """Find the last assistant message in a conversation."""
    for msg in reversed(conversation):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    raise ValueError("No assistant message found in conversation")


def parse_verdict(text: str) -> dict:
    """Parse the structured verdict from the judge's response."""
    verdict_xml = extract_xml_section(text, "verdict")
    if verdict_xml is None:
        # Fallback: scan for CONSENSUS or CONTINUE anywhere in text
        logger.warning("No <verdict> tag found; falling back to keyword scan")
        if re.search(r"\bCONSENSUS\b", text):
            return {"decision": "CONSENSUS", "convergence_score": None}
        return {"decision": "CONTINUE", "convergence_score": None}

    result: dict[str, str | int | None] = {"decision": "CONTINUE", "convergence_score": None}
    for line in verdict_xml.splitlines():
        line = line.strip()
        if line.startswith("decision:"):
            value = line.split(":", 1)[1].strip().upper()
            if "CONSENSUS" in value:
                result["decision"] = "CONSENSUS"
        elif line.startswith("convergence_score:"):
            try:
                result["convergence_score"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return result
```

When extraction fails (no XML tags, malformed response), the orchestrator can send a follow-up with an explicit format reminder:

```python
RETRY_PROMPT = """Your previous response could not be parsed.
Please reformat using the required XML tags:

<solution>
[your solution content]
</solution>

<analysis>
[your analysis content]
</analysis>
"""
```

### State management

```python
import json
import os
import tempfile

def load_state(path: str = "arena/state.json") -> dict | None:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def save_state(state: dict, path: str = "arena/state.json") -> None:
    """Atomic write: write to temp file then rename to prevent corruption."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise

def init_state(task: str, repo: str, base_branch: str = "main",
               max_rounds: int = 3, verify_commands: list[str] | None = None) -> dict:
    models = ["opus", "gpt", "gemini"]
    random.shuffle(models)
    aliases = ["agent_a", "agent_b", "agent_c"]
    return {
        "task": task,
        "repo": repo,
        "base_branch": base_branch,
        "max_rounds": max_rounds,
        "verify_commands": verify_commands or [],
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
        "consensus_reached": None,
        "final_verdict": None,
    }
```

### Main loop

```python
def run_orchestrator(arena_dir: str = "arena") -> None:
    state = load_state(f"{arena_dir}/state.json")
    if state is None:
        raise FileNotFoundError(f"No state file found at {arena_dir}/state.json")
    api = CursorCloudAPI(os.environ["CURSOR_API_KEY"])

    while not state["completed"]:
        phase = state["phase"]
        if phase == "solve":
            step_solve(state, api)
        elif phase == "evaluate":
            step_evaluate(state, api)
        elif phase == "revise":
            step_revise(state, api)
        elif phase == "verify":
            step_verify(state, api)
        save_state(state, f"{arena_dir}/state.json")

    generate_final_report(state, arena_dir)

    print(f"Arena complete. Rounds: {state['round']}.")
    consensus = state.get("consensus_reached", state.get("final_verdict") is not None)
    print(f"Verdict: {'Consensus reached' if consensus else 'No consensus (max rounds)'}")
    print(f"Alias mapping: {state['alias_mapping']}")
```

---

## 8. Context Management

By using follow-ups to the same agent conversation, each phase appends to a growing context window. By round 3, a single agent's conversation includes the original solve prompt and response, pasted solutions from other agents, critiques, and revised solutions. For complex code review tasks with large diffs, this can approach context limits and degrade reasoning quality.

**Mitigation strategies (configurable per run):**

- **Summarization.** For evaluate and revise prompts, summarize large solutions instead of pasting them verbatim. The orchestrator can use a lightweight summarization step (or truncate to diffs only) before injecting content into follow-ups.
- **Diff-only views.** For code tasks, share only the diff between the base branch and each agent's changes rather than the full solution files.
- **Fresh agents per round.** If context accumulation becomes problematic, launch new agent sessions for each round instead of using follow-ups. This costs more (new VMs) but resets the context window. The orchestrator design supports this — just call `api.launch()` instead of `api.followup()` and pass the full relevant context in the initial prompt.
- **Monitor token counts.** Log approximate token counts per follow-up. If a follow-up exceeds a configurable threshold (e.g., 50k tokens), automatically switch to fresh agents or summarized views for subsequent rounds.

For most tasks (focused code review, technical questions), the default follow-up approach will stay within context limits. The fresh-agent strategy is a safety valve for unusually large tasks.

---

## 9. Final Report

When the arena completes, the orchestrator generates a structured report:

```python
def generate_final_report(state: dict, arena_dir: str) -> None:
    """Generate a final Markdown report summarizing the arena run."""
    report_lines = [
        "# Arena Report",
        f"**Task:** {state['task']}",
        f"**Rounds:** {state['round']}",
        f"**Consensus:** {'Yes' if state.get('consensus_reached', True) else 'No'}",
        f"**Alias mapping:** {state['alias_mapping']}",
        "",
        "## Final Verdict",
        state.get("final_verdict", "N/A"),
        "",
        "## Final Solutions",
    ]
    for alias, solution in state.get("solutions", {}).items():
        model = state["alias_mapping"].get(alias, "unknown")
        report_lines.append(f"### {alias} ({model})")
        report_lines.append(solution)
        report_lines.append("")

    report_path = os.path.join(arena_dir, "report.md")
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    logger.info("Final report written to %s", report_path)
```

For code review tasks, the report identifies the winning base solution and the specific modifications to apply, providing an actionable deliverable rather than just a summary.

---

## 10. Observability

**During runs:** Poll agent status via the API. The Cursor web UI at `cursor.com/agents` shows all active agents, their progress, and allows manual "enter the machine" for inspection. Future optimization: the Cursor API supports webhooks for agent status updates, which would eliminate polling overhead for a system where each step takes minutes.

**Post-hoc:** `GET /v0/agents/{id}/conversation` returns the complete message history as structured JSON for any agent. All conversations are preserved until the agent is deleted.

**Logging:** The orchestrator logs every API call, state transition, and extracted content to `arena/orchestrator.log`. The state file is a complete, human-readable record of the arena's progression.

**Manual intervention:** Send a follow-up to any agent via the API or the Cursor web UI at any time. The orchestrator will pick up the new conversation content on its next poll. To pause the orchestrator, kill it; to resume, restart it — the state file ensures continuity.

---

## 11. Cost Estimation

Cloud agents use Max Mode pricing. The cost depends on tokens processed per agent session:

| Scenario | Agent invocations | Estimated tokens per agent | Notes |
|---|---|---|---|
| 1-round (consensus on first verify) | 3 sessions, ~4 messages each | ~20-30k tokens | Best case |
| 3-round (max rounds) | 3 sessions, ~10 messages each | ~50-80k tokens | Worst case |

**Per-run estimate framework:**

- **Solve phase:** 3 parallel agents, each processing ~2-4k prompt + ~2-4k response ≈ 12-24k tokens total.
- **Each evaluate→revise→verify cycle:** 3 agents receive pasted solutions (~4-8k each) plus critiques (~4-8k each), plus one judge prompt. Roughly 30-50k tokens per cycle across all agents.
- **3-round maximum:** ~100-170k tokens total across all agent sessions.

Exact costs depend on Cursor's Max Mode pricing tier. For routine use, limit `max_rounds` to 2 and reserve 3-round runs for high-stakes reviews. Monitor actual token usage during the single-agent and three-agent test phases to calibrate expectations.

---

## 12. Why This Phase Design

Earlier iterations used a five-phase loop: solve → review → judge → challenge → advocate. This was revised for three reasons:

**Evaluation and revision were conflated.** The old "review" phase asked agents to critique other solutions and produce a revised solution in one step. This let models skip genuine evaluation and jump to synthesis, causing regression-to-the-mean. Splitting into evaluate (critique only) → revise (informed by all critiques) forces genuine engagement before any revision occurs.

**Challenge and advocate were remedial.** They existed to patch problems with the judge — premature consensus and outlier suppression. With explicit disagreement tracking (agents self-report remaining disagreements in their analysis sections) and a more rigorous verify prompt (that incorporates the challenge question directly), these separate phases are unnecessary.

**Fewer sequential steps means faster wall-clock time.** With cloud agents, each phase is a full agent run. Four phases (solve → evaluate → revise → verify) with parallelism within each phase is faster than five phases with less parallelism. Solve, evaluate, and revise all run three agents in parallel.

---

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Agent produces unstructured response (no XML tags) | **High** | Parse best-effort with fallback heuristics; re-prompt via follow-up with explicit format reminder (see extraction code) |
| Consensus regression to the mean | **High** | Evaluate/revise split forces genuine critique; verify prompt requires classifying disagreements as trivial or substantive |
| Cloud agent latency (minutes per turn) | **Medium** | True parallel execution within phases; accept ~30-60 min per run |
| Max Mode cost | **Medium** | Limit rounds (default 3); see cost estimates in Section 11 |
| Context window accumulation across rounds | **Medium** | Summarization, diff-only views, or fresh agents per round (see Section 8) |
| Cross-agent content bloat in follow-ups | **Medium** | Share only solution sections during evaluate; full analyses only to judge |
| API rate limits / transient failures | **Medium** | Retry with exponential backoff and jitter (see API wrapper) |
| Agent goes off-task during autonomous run | **Medium** | Post-hoc conversation review; follow-up to course-correct |
| Judge bias toward own solution | **Medium** | Anonymized aliases; explicit anti-bias instruction in verify prompt; judge rotation |
| State file corruption on crash | **Low** | Atomic write via temp-file-then-rename |
| Model bias from alias ordering | **Low** | Aliases randomized per run; presentation order shuffled per prompt |

---

## 14. Fallback: Local tmux Architecture

If cloud agent latency or cost is prohibitive, the arena can run locally using tmux + libtmux. The key differences:

- Agents run as interactive `cursor-agent` sessions in tmux panes (one per model, each in its own git worktree).
- The orchestrator sends prompts via `pane.send_keys()` and instructs agents to write output to Markdown files.
- Completion requires both file stability (size unchanged) and pane idle (terminal content unchanged).
- Approval handling via `capture_pane()` regex detection.
- A dev container provides sandboxing (deny-by-default permissions, isolated filesystem).
- Human observer attaches via `tmux attach -t arena` (or `byobu attach`) for real-time visibility.

The consensus loop, phase structure, anonymization, and stateless orchestrator design are identical — only the transport layer changes.

---

## 15. Getting Started

### Prerequisites

- **Python 3.13+** with `pixi` for package management.
- **Dependencies:** `requests` (HTTP client), `logging` (stdlib).
- **Setup:** `pixi init && pixi add requests` in the project root.
- **Cursor API key** from your dashboard. Export as `CURSOR_API_KEY`.
- **GitHub repo** connected to your Cursor account.

### Incremental validation

1. **Single-agent test.** Launch one cloud agent with a simple task. Poll until finished. Retrieve the conversation. Verify structured content is extractable — confirm the XML tags parse correctly.
2. **Three-agent test.** Launch three agents with different models on the same repo. Verify they create separate branches and don't interfere with each other. Validate that cloud RAG indexing produces results comparable to local indexing.
3. **Run the solve phase.** Initialize state, run `step_solve`. Kill the orchestrator after 2 agents finish. Restart. Verify the third resumes correctly and previously finished agents are not re-launched.
4. **Full arena.** Run a task where models are likely to disagree. Inspect the evaluate-phase critiques to verify genuine engagement. Inspect the verify verdict to confirm the judge enumerates real disagreements rather than rubber-stamping.
5. **Review the alias mapping** in the final state file and `arena/report.md`. Check whether the "best" solution correlates with a specific model, or whether consensus genuinely synthesized from all three.
