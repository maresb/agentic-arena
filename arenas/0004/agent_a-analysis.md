# Desktop Vision Model — Final Analysis

## RISKS

### R1. Ollama May Silently Downscale Images

**Highest priority.** Qwen3-VL continues the `min_pixels` / `max_pixels` pattern. The
default pixel budget will downscale 4K images unless overridden. Qwen3-VL additionally
supports explicit `resized_height` / `resized_width` (rounded to multiples of 32).

**Critical detail:** If using `qwen-vl-utils` for resizing, disable resizing in the
processor to avoid double-resizing.

**Mitigation:** Step 0 sanity check. Window-aware cropping as primary defense (crops
are naturally smaller). Sub-tile large windows with 32-aligned dimensions. If Ollama
can't be configured, use vllm/llama.cpp with explicit pixel budget controls.

### R2. Hallucination of Screen Content

Now structurally defended with the **dual-model cross-check:** GLM-OCR provides
ground-truth text extraction; if Qwen3-VL claims text that GLM-OCR does not find,
mark as low confidence.

Additional mitigations: anti-hallucination prompts (`[illegible]`), temperature=0,
structured JSON, window title grounding.

### R3. Processing Latency (dual-model overhead)

Dual-model processing per window: Qwen3-VL (~10-20s) + GLM-OCR (~2-5s). Total for
3-5 windows: ~60-125s. The 32B Qwen3-VL is faster than the old 72B recommendation,
partially offsetting the added OCR pass.

**Mitigation:** Delta detection skips unchanged frames. Active-window-only sampling for
routine captures. GLM-OCR is tiny and adds minimal latency. For higher throughput,
run GLM-OCR only on text-heavy windows (terminals, editors, browsers) and skip it on
image-heavy windows (viewers, dashboards).

### R4. Qwen3-VL Runtime Compatibility

Practitioners report accuracy depends on correct image resizing and coordinate
conventions. The Ollama model card indicates a minimum Ollama version for Qwen3-VL.

**Mitigation:** Verify Ollama version compatibility. Test with Step 0 before building
the full pipeline.

### R5. Structured JSON Reliability

LLMs can emit malformed JSON. Use Ollama's `format: "json"` if available, `json-repair`
package, retry up to 2 times on parse failure.

### R6. GNOME Wayland Window Geometry Access

GNOME extensions on Wayland have restricted access to global window geometry. If
geometry is unavailable, must fall back to landscape grid tiling (2x2).

**Mitigation:** Test `gdbus` query into Mutter. If unavailable, the grid fallback
produces acceptable results with slightly more compute.

---

## OPEN QUESTIONS

### OQ1. Ollama's Pixel Budget for Qwen3-VL

Does Ollama respect Qwen3-VL's `max_pixels` configuration? Can it be overridden in a
Modelfile? Does the 32-multiple rounding work correctly? Must verify via Step 0.

### OQ2. GLM-OCR Availability and Quality on Desktop Screenshots

Is `glm-ocr` available in the user's Ollama build? How does it perform on desktop
screenshots (vs documents)? Test on representative window crops. If unavailable or
underperforming, Tesseract/PaddleOCR serve as OCR cross-check alternatives.

### OQ3. GNOME Extension Window Geometry Export

Does the user's extension export (x, y, width, height) and z-order? If not, can `gdbus`
query `global.get_window_actors()` for `meta_window.get_frame_rect()`?

### OQ4. Optimal Quantization for Qwen3-VL-32B

With 96 GB and a 32B model, Q8_0 should be comfortable. Verify empirically: does Q8_0
vs Q6_K/Q4_K_M produce measurably better OCR on 12px+ text? The cost is higher latency;
the benefit is higher precision.

### OQ5. Zoom Tool Viability

Does the current Ollama build support Qwen3-VL's `image_zoom_in_tool`? Not needed for
the initial prototype but determines the upgrade path from deterministic tiling to
hybrid model-driven zoom.

---

## DISAGREEMENTS

None.

All three agents converged after receiving the updated model guidance. The consensus
now covers all substantive decisions:

| Decision | Consensus |
|---|---|
| Primary model | Qwen3-VL-32B Instruct |
| Secondary OCR | GLM-OCR (~0.9B) |
| Quantization | Q8_0 (32B fits easily in 96 GB) |
| Primary strategy | Window-aware cropping (dual-model) |
| Maximized window | Sub-tile into 32-aligned tiles |
| Tile dimensions | 1920x1088, overlap 192x96 |
| Output format | Structured JSON, semantic regions |
| Fallback | Landscape grid tiling (~4 tiles) |
| Verification | Step 0 empirical sanity check |
| Storage | Delta detection (pHash), text-only, SQLite/FTS |
| Anti-hallucination | Dual-model cross-check, temperature=0, `[illegible]` |
| JSON reliability | format hints, repair, retries |
| License | Both models Apache-2.0 |
