# Desktop Vision Model — Revised Analysis

*Major revision incorporating arena operator's correction: Qwen3-VL exists (Sep-Oct 2025)
and is the proper recommendation for Feb 2026, not the year-old Qwen2.5-VL.*

## RISKS

### R1. Ollama May Silently Downscale Images

**Still the highest-priority risk.** Qwen3-VL continues the `min_pixels` / `max_pixels`
pattern from earlier Qwen VL models. The default pixel budget will downscale 4K images
unless overridden. Qwen3-VL additionally supports explicit `resized_height` /
`resized_width` (rounded to multiples of 32).

**Critical detail:** If using `qwen-vl-utils` for resizing, disable resizing in the
processor to avoid double-resizing.

**Mitigation:** Step 0 sanity check. Window-aware cropping. Sub-tile large windows with
32-aligned dimensions. If Ollama can't be configured, use vllm/llama.cpp with explicit
pixel budget controls.

### R2. Hallucination of Screen Content

Now addressed with a **dual-model cross-check:** run GLM-OCR on the same crop as
Qwen3-VL. If the VLM claims text that the OCR specialist does not find, mark the block
as low confidence. This is a structural defense, not just a prompt-level mitigation.

Additional mitigations: anti-hallucination prompts (`[illegible]`), temperature=0,
structured JSON output, cross-validation with window title metadata.

### R3. Processing Latency (increased with dual-model)

The dual-model approach doubles per-window inference: Qwen3-VL (~10-20s per crop) +
GLM-OCR (~2-5s per crop, being much smaller). Total for 3-5 windows: ~60-125s.

**Mitigation:** GLM-OCR is tiny (~0.9B) and adds minimal latency. Delta detection
skips unchanged frames. Active-window-only sampling for routine captures. The 32B
Qwen3-VL model is faster than the old 72B recommendation.

### R4. Qwen3-VL Runtime Compatibility

Practitioners report that accuracy depends on correct image resizing and coordinate
conventions in local runtimes. The Ollama model card indicates a minimum Ollama version
is required for the Qwen3-VL family.

**Mitigation:** Verify Ollama version compatibility before pulling the model. Test with
Step 0 before building the full pipeline.

### R5. Structured JSON Reliability

Unchanged. Use Ollama's `format: "json"` if available, JSON repair, retry logic.

---

## OPEN QUESTIONS

### OQ1. Ollama's Pixel Budget for Qwen3-VL

Does Ollama respect Qwen3-VL's `max_pixels` configuration? Can it be overridden in a
Modelfile? Does the 32-multiple rounding work correctly in the Ollama integration?
Must be verified via Step 0.

### OQ2. GLM-OCR Availability and Quality

Is `glm-ocr` available in the user's Ollama build? How does its accuracy compare to
Tesseract/PaddleOCR on actual desktop screenshots (vs documents)? Test on representative
window crops before committing to the dual-model pipeline.

### OQ3. GNOME Extension Window Geometry

Does the user's extension export (x, y, width, height) and z-order? If not, can `gdbus`
query GNOME Shell? If unavailable on Wayland, fall back to grid tiling.

### OQ4. Optimal Quantization for Qwen3-VL-32B

With 96 GB VRAM and a 32B model, Q8_0 should be comfortable. But verify empirically:
does Q8_0 vs Q4_K_M produce measurably better OCR on 12px+ text? The cost of Q8_0 is
higher latency; the benefit is higher precision.

### OQ5. Zoom Tool Viability in Ollama

Does the current Ollama build support Qwen3-VL's `image_zoom_in_tool` for model-driven
zoom? This is not needed for the initial prototype but determines whether the upgrade
path from deterministic tiling to hybrid zoom is practical.

---

## DISAGREEMENTS

### D1. Previous consensus on Qwen2.5-VL-72B was outdated.

The arena operator's correction is valid. All three agents (including myself) recommended
a year-old model. **Qwen3-VL-32B is the correct recommendation for February 2026.**

Key reasons this was missed:
- Training data cutoff may not have included Qwen3-VL's release (Sep-Oct 2025).
- The convergence process amplified the initial consensus rather than challenging it.

### D2. Dual-model approach (new, not yet evaluated by other agents)

The hybrid Qwen3-VL + GLM-OCR stack is a new recommendation from the operator context.
The other agents have not yet evaluated this approach. The rationale is strong:
- Qwen3-VL for scene understanding (what apps, what layout, what UI elements).
- GLM-OCR for faithful text extraction (what does the text actually say).
- Cross-check for hallucination detection.

This is architecturally sound and addresses the user's core failure mode directly.
However, it adds pipeline complexity and should be validated empirically before
committing.

### D3. Quantization: Q8_0 is now viable as default.

With the 32B model (~34 GB at Q8_0), there is abundant VRAM headroom on 96 GB.
The previous Q4_K_M recommendation was driven by the 72B model's size. Q8_0 provides
near-lossless quality and is the correct default for the smaller model.
