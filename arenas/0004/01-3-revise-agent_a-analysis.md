# Final Revised: Analysis

## RISKS

### R1. Ollama May Silently Downscale Images

**Highest priority.** The model's default pixel budget (~1M pixels) will downscale a 4K
image (8.3M pixels) by ~8x unless overridden. This is the most likely cause of the
user's previous hallucination problem.

**Mitigation:** Step 0 sanity check. Window-aware cropping as primary defense (crops are
naturally smaller). If Ollama can't be configured, use vllm/llama.cpp directly.

### R2. Hallucination of Screen Content

VLMs hallucinate when text is blurry, partially visible, or contextually expected.

**Mitigation:** Anti-hallucination prompts (`[illegible]`), temperature=0, structured
JSON output, cross-validation with window title metadata, optional secondary OCR.

### R3. Processing Latency

3-5 windows at 10-30s each = 60-150s total. Acceptable for 5-minute sampling; not for
real-time. Mitigate with delta detection, active-window-only sampling, or 7B triage.

### R4. Structured JSON Reliability

LLMs can emit malformed JSON. Use Ollama's `format: "json"` if available, implement
JSON repair (`json-repair` package), retry up to 2 times on parse failure.

---

## OPEN QUESTIONS

### OQ1. Ollama's `max_pixels` Behavior

Does Ollama respect the model's native pixel budget? Can it be overridden? Must be
verified empirically via Step 0 before committing to any pipeline design.

### OQ2. GNOME Extension Window Geometry

Does the user's extension export (x, y, width, height) and z-order? If not, can `gdbus`
query GNOME Shell's `global.get_window_actors()` for `meta_window.get_frame_rect()`?
If geometry is unavailable on Wayland, fall back to grid tiling.

### OQ3. Optimal Quantization

A/B test Q4_K_M vs Q5_K_M on 20+ window crops with known text. Use whichever achieves
>95% character accuracy on 12px+ text.

### OQ4. Newer Models

Check for Qwen3-VL, InternVL3, Llama 4 Vision, or other entrants on Ollama/HuggingFace
before final deployment.

---

## DISAGREEMENTS

None.

All three agents have converged on every substantive decision after two rounds:

| Decision | Consensus |
|---|---|
| Model | Qwen2.5-VL-72B-Instruct |
| Quantization | Q4_K_M (test Q5_K_M) |
| Primary strategy | Window-aware cropping |
| Output format | Structured JSON, semantic regions |
| Fallback | Landscape grid tiling (~4 tiles) |
| Verification | Step 0 empirical sanity check |
| Storage | Delta detection, text-only, SQLite/FTS |
| Anti-hallucination | temperature=0, `[illegible]`, structured prompts |

Remaining differences (tile dimensions, JSON field names, documentation verbosity) are
trivial implementation details with no impact on architectural correctness.
