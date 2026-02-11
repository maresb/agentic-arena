# Desktop Vision Model — Final Analysis

## RISKS

### R1. Ollama May Silently Downscale Images

**Highest priority.** Qwen3-VL's default pixel budget will downscale 4K images unless
overridden. Dimensions must be multiples of 32. If using `qwen-vl-utils`, disable
resizing in the processor to avoid double-resizing.

**Mitigation:** Step 0 sanity check. Window-aware cropping. Sub-tile large windows with
32-aligned dimensions. If Ollama can't be configured, use vllm/llama.cpp directly.

### R2. Hallucination of Screen Content

Structurally defended with **dual-model cross-check** on text-heavy windows: GLM-OCR
provides ground-truth text; if Qwen3-VL claims text GLM-OCR doesn't find, mark as low
confidence. Additional: anti-hallucination prompts, temperature=0, structured JSON.

### R3. Processing Latency

With selective OCR, dual-model cost applies only to text-heavy windows. Estimated:
~60-100s for 3-5 windows (vs ~60-125s if OCR runs on all windows).

**Mitigation:** Delta detection, active-window-only sampling, GLM-OCR's tiny size.

### R4. Selective OCR May Miss Text in Unexpected Places

If a "non-text-heavy" app (e.g., file manager, dashboard) has significant visible text
(notifications, labels, error dialogs), GLM-OCR will be skipped and Qwen3-VL's text
extraction may be less reliable.

**Mitigation:** The `is_text_heavy()` heuristic uses a broad set of app keywords. For
unknown apps, default to running OCR (conservative). The user can refine the set over
time based on classification feedback.

### R5. Qwen3-VL Runtime Compatibility

Minimum Ollama version required. Verify before deployment. Step 0 catches issues early.

### R6. JSON Reliability / Wayland Geometry Access

JSON repair + retry for malformed output. `gdbus` into Mutter for window geometry; fall
back to grid tiling if unavailable on Wayland.

---

## OPEN QUESTIONS

### OQ1. Ollama's Pixel Budget for Qwen3-VL

Does Ollama respect `max_pixels`? Can it be overridden in a Modelfile? Does 32-multiple
rounding work? Verify via Step 0.

### OQ2. GLM-OCR Availability and Desktop Screenshot Quality

Is `glm-ocr` in the user's Ollama build? How does it perform on UI screenshots vs
documents? If unavailable, Tesseract/PaddleOCR are alternatives.

### OQ3. GNOME Extension Window Geometry

Does the extension export (x, y, w, h) and z-order? If not, `gdbus` or grid fallback.

### OQ4. Optimal Quantization

Q8_0 should be comfortable on 96 GB. Verify Q8_0 vs Q6_K on 12px+ text empirically.

### OQ5. Zoom Tool Viability

Does Ollama support Qwen3-VL's `image_zoom_in_tool`? Not needed now but determines the
upgrade path from deterministic tiling to model-driven zoom.

### OQ6. Selective OCR Threshold Tuning

What is the optimal set of "text-heavy" app types? Should unknown apps default to
OCR-on or OCR-off? Recommend OCR-on for unknowns, refine with usage data.

---

## DISAGREEMENTS

None.

All three agents converged on every substantive decision:

| Decision | Consensus |
|---|---|
| Primary model | Qwen3-VL-32B Instruct |
| Secondary OCR | GLM-OCR (~0.9B), selective on text-heavy windows |
| Quantization | Q8_0 (32B fits easily in 96 GB) |
| Primary strategy | Window-aware cropping (dual-model for text-heavy) |
| Tile dimensions | 1920×1088, overlap 192×96 (multiples of 32) |
| Output format | Structured JSON, semantic regions |
| Fallback | Landscape grid tiling (~4 tiles) |
| Verification | Step 0 empirical sanity check |
| Storage | Delta detection (pHash), text-only, SQLite/FTS |
| Anti-hallucination | Dual-model cross-check, temperature=0, `[illegible]` |
| JSON reliability | format hints, repair, retries |
| License | Both models Apache-2.0 |
| NixOS config | `OLLAMA_MAX_LOADED_MODELS = "2"` |
