# Revised: Desktop Vision Model Analysis

*Updated based on cross-agent critique feedback. Reduced from 10 risks to the 7 most
substantive, consolidated open questions, and added explicit disagreements section.*

## RISKS

### R1. Ollama's Image Preprocessing May Silently Downscale

**Severity: High | Likelihood: Medium**

This is the highest-priority risk and the likely cause of the user's previous
hallucination problem. All three agents flagged this independently.

Ollama may apply resolution constraints before passing images to the model's vision
encoder. The Qwen2.5-VL model has a default `max_pixels` of ~1,003,520 (~1001x1001),
which would downscale a 4K image (8.3M pixels) by ~8x. Even if the model supports
higher resolutions, Ollama's integration layer may impose its own caps.

**Mitigation (consensus across all agents):**
1. Run Step 0 empirical verification: send a 4K screenshot with known small text and
   check if the model can read it.
2. If downscaled: check `ollama show qwen2.5-vl:72b --modelfile` for resolution settings.
3. Use window-aware cropping (Phase 2) as the primary defense — individual window crops
   are naturally smaller and less likely to trigger downscaling.
4. If Ollama cannot be configured: consider running the model via `vllm`, `llama.cpp`,
   or `transformers` directly, which offer explicit `max_pixels` control.

### R2. Hallucination of Screen Content

**Severity: High | Likelihood: Medium**

Vision-language models can hallucinate content, especially when text is partially visible,
blurry, or when the model "expects" certain content based on context.

**Mitigation (refined with cross-agent input):**
1. Anti-hallucination prompts: instruct the model to use `[illegible]` for unclear text
   and not to guess or infer.
2. Temperature = 0 for deterministic output.
3. Structured JSON output constrains the model's output space.
4. Cross-validate with window title metadata.
5. Optional secondary OCR (Tesseract/PaddleOCR) as a hallucination detector — if the
   VLM's text and the OCR output diverge significantly, flag for review.

### R3. VRAM Pressure with High-Precision Quantization

**Severity: Medium | Likelihood: Medium**

Agent C recommended Q8_0 (~72-77 GB weights). For per-window crops (typically
1000-2000 visual tokens), Q8_0 is feasible on 96 GB. For full 4K native processing
(~10,500 visual tokens), Q8_0 weights + KV cache may exceed 96 GB.

**Revised guidance:**
- **Q4_K_M for the global layout scan** (Phase 1, full screenshot — needs headroom).
- **Q5_K_M or Q6_K for per-window crops** (Phase 2, smaller images — can afford higher
  precision). Note: switching quantization mid-pipeline requires loading two model
  instances or reloading, which is impractical. In practice, use a single quantization
  level — Q4_K_M is the safe default, Q5_K_M if empirically verified to fit.
- Q8_0 is not recommended as the general-purpose quantization for this workflow.

### R4. Processing Latency

**Severity: Low-Medium | Likelihood: Certain**

Serial processing of N windows at 10-30 seconds each means a 3-5 window desktop takes
60-150 seconds total. This is acceptable for periodic sampling (every 5 minutes) but
prohibitive for real-time monitoring.

**Mitigation:**
- Process only the active window on each sample; full desktop scans less frequently.
- Use delta detection (screenshot hashing) to skip unchanged frames.
- Consider Qwen2.5-VL-7B for fast triage, 72B for detailed extraction on demand.
- Defer processing to idle periods if desktop UI lag is observed during inference.

### R5. Future Resolution Upgrades (5K, 8K)

**Severity: Medium | Likelihood: High**

Window-aware cropping scales gracefully — individual windows remain similar in pixel
size regardless of total screen resolution. Grid tiling would need to increase from
2x2 to 3x2 or 4x3.

No action needed now; the architecture handles this naturally.

### R6. NixOS + Wayland Screenshot Capture

**Severity: Low-Medium | Likelihood: Medium**

`gnome-screenshot` may be deprecated on GNOME Wayland in favor of the D-Bus screenshot
portal. Python libraries like `mss` may not work on Wayland.

**Mitigation:** Test `gnome-screenshot --file=/tmp/test.png` first. If unavailable, use
the GNOME Shell screenshot D-Bus API. Verify captured images are full resolution.

### R7. Structured JSON Output Reliability

**Severity: Medium | Likelihood: Medium**

LLMs sometimes produce malformed JSON, especially for long outputs. This is more
important now that the revised pipeline relies on structured JSON.

**Mitigation:**
1. Use Ollama's `format: "json"` parameter if available.
2. Implement JSON repair (e.g., `json-repair` Python package) as a fallback.
3. Implement retry logic (up to 2 retries) on parse failure.
4. For critical reliability, extract fields in separate smaller queries rather than
   one large JSON response.

---

## OPEN QUESTIONS

### OQ1. Ollama's Actual `max_pixels` Behavior

**Highest priority. Must be verified empirically before committing to any pipeline design.**

- Does Ollama respect Qwen2.5-VL's native `max_pixels` configuration?
- Can it be overridden in a custom Modelfile or via API parameters?
- What resolution does the model actually "see" after Ollama's preprocessing?

Verification: Step 0 in the solution above.

### OQ2. GNOME Extension Window Geometry Export

**Required for the window-aware cropping approach (consensus primary strategy).**

- Does the user's current GNOME extension export window geometry (x, y, width, height)?
- If not, can `gdbus` call into GNOME Shell's `global.get_window_actors()` to retrieve
  `meta_window.get_frame_rect()` for all visible windows?
- On GNOME Wayland, what APIs are available for window enumeration?

### OQ3. Optimal Quantization for OCR Quality

**Should be resolved through empirical A/B testing.**

- Compare Q4_K_M vs Q5_K_M on a reference set of 20+ window crops with known text.
- Measure character-level accuracy.
- If Q5_K_M is significantly better (>3% accuracy improvement), use it as the default.

### OQ4. Newer Models (post-training-cutoff)

As of February 2026, check for:
- Qwen3-VL (if released, likely supersedes Qwen2.5-VL)
- InternVL3
- Llama 4 Vision
- Other new entrants on Ollama or Hugging Face

### OQ5. 7B vs 72B Cost-Benefit for Daily Use

For routine periodic sampling with window crops, the 7B model may produce
"good enough" descriptions at 5-10x lower latency. Worth evaluating on real data.

---

## DISAGREEMENTS

### D1. "Manual chunking is largely obsolete" (Agent C) — I still disagree.

Agent C maintains that Qwen2.5-VL can process full 4K natively without chunking. While
the model architecture supports dynamic resolution, the practical reality is:

1. The default `max_pixels` (~1M pixels) **will** downscale a 4K image (8.3M pixels).
2. Ollama may impose additional resolution constraints.
3. The user's previous hallucination problem was almost certainly caused by this exact
   downscaling.

Agent C's revised position (adopting window-aware cropping) effectively acknowledges
that some form of image subdivision is needed. The remaining disagreement is mostly
rhetorical — we now agree on the practice (crop windows) even if Agent C frames the
model as "not needing chunking" while I frame window cropping as a form of chunking.

**Status: Effectively resolved in practice. Theoretical framing differs.**

### D2. Q8_0 vs Q4_K_M as default quantization (Agent C vs Agents A and B)

Agent C's revised position still recommends "attempting Q8_0 (or at least Q5/Q6) first."
I agree that Q5_K_M is worth testing for per-window crops, but Q8_0 as the default is
risky because:

1. Q8_0 weights (~72-77 GB) leave only ~19-24 GB for KV cache, activations, and overhead.
2. If any window crop generates a large number of visual tokens (e.g., a maximized
   window at native resolution), the KV cache could exceed the remaining VRAM.
3. Q4_K_M preserves ~97-99% of FP16 quality on standard benchmarks. The marginal quality
   gain of Q8_0 is unlikely to be noticeable for this use case.

**Status: Minor disagreement. Resolvable by empirical testing.**

### D3. Square tiles vs landscape tiles (Agent B) — Minor, largely moot.

Agent B uses 1344x1344 square tiles (8 tiles for 4K). I prefer 1920x1080 landscape tiles
(4 tiles for 4K). Since all agents now agree that window-aware cropping is the primary
strategy and grid tiling is only a fallback, this disagreement is largely academic.

If grid tiling is needed, landscape tiles are more efficient for 16:9 desktops, but
square tiles work fine — it's a throughput trade-off (4 tiles vs 8) not a quality issue.

**Status: Moot. Window-aware cropping is the consensus primary strategy.**

### D4. Pixel-level bboxes from VLMs (Agent B)

Agent B's structured output schema includes pixel-accurate bounding boxes for text blocks
and UI elements. I remain skeptical that VLMs produce reliable pixel coordinates.
However, this is a minor implementation detail — the schema can use semantic region labels
(header, body, sidebar, etc.) instead of pixel coordinates, as in my revised schema.
Agent B's IoU-based deduplication can be replaced with text-similarity-based deduplication.

**Status: Implementation detail. Semantic regions are more reliable than pixel bboxes;
both approaches work for downstream classification.**
