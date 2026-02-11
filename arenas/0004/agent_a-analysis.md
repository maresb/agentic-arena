# Desktop Vision Model — Final Analysis

## RISKS

### R1. Ollama May Silently Downscale Images

**Highest priority.** The model's default pixel budget (~1M pixels) will downscale a 4K
image (8.3M pixels) by ~8x unless overridden. This is the most likely cause of the
user's previous hallucination problem.

**Mitigation:** Step 0 sanity check. Window-aware cropping as primary defense. Sub-tile
maximized windows that exceed the pixel budget. If Ollama can't be configured, use
vllm/llama.cpp directly.

### R2. Hallucination of Screen Content

VLMs hallucinate when text is blurry, partially visible, or contextually expected.

**Mitigation:** Anti-hallucination prompts (`[illegible]`), temperature=0, structured
JSON output, cross-validation with window title metadata, optional secondary OCR
(Tesseract/PaddleOCR) as a hallucination detector.

### R3. Processing Latency

3-5 windows at 10-30s each = 60-150s total. Acceptable for 5-minute sampling; not for
real-time. Mitigate with delta detection, active-window-only sampling, or 7B triage.

### R4. Structured JSON Reliability

LLMs can emit malformed JSON. Use Ollama's `format: "json"` if available, implement
JSON repair (`json-repair` package), retry up to 2 times on parse failure.

---

## OPEN QUESTIONS

### OQ1. Ollama's `max_pixels` Behavior

Does Ollama respect the model's native pixel budget? Can it be overridden in a custom
Modelfile? Must be verified empirically via Step 0.

### OQ2. GNOME Extension Window Geometry

Does the user's extension export (x, y, width, height) and z-order? If not, can `gdbus`
query `global.get_window_actors()` for `meta_window.get_frame_rect()`? If unavailable
on Wayland, fall back to grid tiling.

### OQ3. Optimal Quantization

A/B test Q4_K_M vs Q5_K_M on 20+ window crops. Use whichever achieves >95% character
accuracy on 12px+ text.

### OQ4. Newer Models

Check for Qwen3-VL, InternVL3, Llama 4 Vision on Ollama/HuggingFace before deployment.

---

## DISAGREEMENTS

None.

All three agents converged on every substantive decision across three rounds:

| Decision | Consensus |
|---|---|
| Model | Qwen2.5-VL-72B-Instruct |
| Quantization | Q4_K_M (test Q5_K_M) |
| Primary strategy | Window-aware cropping |
| Maximized window | Sub-tile into 2 halves |
| Output format | Structured JSON, semantic regions |
| Fallback | Landscape grid tiling (~4 tiles) |
| Verification | Step 0 empirical sanity check |
| Storage | Delta detection (pHash), text-only, SQLite/FTS |
| Anti-hallucination | temperature=0, `[illegible]`, structured prompts |
| JSON reliability | format hints, repair, retries |

No remaining architectural, correctness, or logic disagreements.
