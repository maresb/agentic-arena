# Desktop Vision Model Analysis: Risks, Edge Cases, and Open Questions

## RISKS

### R1. VRAM Pressure at Full 4K Native Resolution

**Severity: Medium | Likelihood: Medium**

Processing a full 3840x2160 image natively with Qwen2.5-VL-72B-Instruct (Q4_K_M) requires
approximately 71-81 GB of VRAM. On a 96 GB card, this leaves only 15-25 GB of headroom,
which may be insufficient if:

- The Ollama runtime has its own memory overhead (~1-3 GB)
- CUDA context and driver overhead consumes ~1-2 GB
- Other GPU-accelerated processes (GNOME compositor, display server) use VRAM
- The model's actual memory usage exceeds estimates due to implementation details

**Mitigation:** The recommended two-pass approach (global low-res + per-window high-res crops)
avoids this entirely. Each pass uses ~46-52 GB, well within the 96 GB budget. Only resort
to full-4K native processing if you've empirically verified it fits.

### R2. Ollama's Internal Image Preprocessing May Downscale

**Severity: High | Likelihood: Medium**

Ollama may apply its own image preprocessing before passing images to the model, potentially
downscaling high-resolution inputs regardless of the model's native capabilities. This was
likely the cause of the user's previous hallucination issue.

**Evidence:** Ollama's image handling for vision models typically base64-encodes the image
and lets the model's processor handle resizing. However, some model integrations apply
preprocessing that constrains resolution to a default maximum (often 768x768 or 1024x1024).

**Mitigation:**
1. Test with a known screenshot and verify the model can read small text
2. If text is illegible, check Ollama's Modelfile for resolution parameters
3. Use window crops (Phase 2) which are naturally smaller and less likely to be downscaled
4. Consider running the model directly via `transformers` + `vllm` or `llama.cpp` if
   Ollama's preprocessing proves too restrictive
5. Check Ollama release notes for `max_pixels` or resolution control parameters

### R3. Quantization Impact on OCR Accuracy

**Severity: Low-Medium | Likelihood: Low**

Q4_K_M quantization reduces the model from FP16 (144 GB) to ~42 GB. While Q4_K_M is
considered high-quality quantization with minimal perceptible quality loss for general tasks,
OCR accuracy on small text is particularly sensitive to weight precision.

**Evidence from the community:** Benchmarks show Q4_K_M preserves ~97-99% of FP16 performance
on standard VQA benchmarks, but fine-grained OCR accuracy on small text (8-10px) may degrade
by 2-5 percentage points.

**Mitigation:**
- The window-cropping approach naturally increases effective text size in each crop
- If OCR quality is insufficient at Q4, try Q5_K_M (~49 GB) or Q6_K (~58 GB)
- For critical text extraction, consider a dedicated OCR pass with a specialized model
  (e.g., Tesseract, PaddleOCR) as a complement

### R4. Hallucination of Screen Content

**Severity: High | Likelihood: Medium**

Vision-language models can hallucinate content that isn't present, especially when:
- Text is partially visible or blurry
- The model "expects" certain content based on the application type
- Overlap regions in grid chunking cause repeated context that confuses the model

This is the user's primary concern from their previous attempt.

**Mitigation:**
1. **Use explicit anti-hallucination prompts:** Include instructions like *"Only describe
   what you can clearly see. If text is unclear, indicate it as [illegible]. Do not guess
   or infer content that isn't visible."*
2. **Cross-validate with window titles:** If the model claims content inconsistent with
   the window title metadata, flag it
3. **Prefer window crops over grid chunks:** Window-aware cropping provides complete,
   coherent views of each window, reducing ambiguity
4. **Temperature = 0:** Use `temperature: 0` in Ollama API calls for deterministic,
   less creative (and less hallucinatory) output
5. **Structured output:** Request JSON-formatted responses, which constrain the model's
   output space and reduce free-form hallucination

### R5. Processing Latency for Real-Time Monitoring

**Severity: Low | Likelihood: Certain**

The three-phase processing pipeline for a single screenshot with 3-5 windows will take
approximately 60-120 seconds on the RTX PRO 6000 Blackwell. This is acceptable for periodic
sampling (every 5 minutes) but prohibitive for real-time continuous monitoring.

**Mitigation:**
- Sample screenshots at fixed intervals (e.g., every 5 minutes) or on window-focus-change
  events
- Skip processing if the desktop state hasn't changed (compare screenshot hashes)
- Process only the active window (Phase 2) on each sample, and do full desktop scans
  less frequently
- Use the smaller Qwen2.5-VL-7B for quick "has anything changed?" triage, and the 72B
  for detailed extraction only when changes are detected

### R6. Future Monitor Upgrade (Higher Than 4K)

**Severity: Medium | Likelihood: High (user stated intent)**

If the user upgrades to 5K (5120x2880), 6K, or 8K resolution:
- Full-image visual tokens increase quadratically with resolution
- A 5K image would produce ~19,000 visual tokens at native resolution
- An 8K image would produce ~42,000 visual tokens — far exceeding practical limits

**Mitigation:**
- The window-aware cropping approach scales gracefully: individual windows remain
  similar in pixel size regardless of total screen resolution
- Grid chunking scales linearly: use a 3x2 or 4x3 grid instead of 2x2
- Future models (Qwen3-VL, etc.) will likely support larger visual token budgets

### R7. Multi-Monitor Setups

**Severity: Low | Likelihood: Medium**

If the user connects multiple monitors, each screenshot would be even larger, or they'd
need to capture each monitor separately.

**Mitigation:**
- Capture each monitor as a separate screenshot
- GNOME's screenshot tool supports per-monitor capture
- Process each monitor independently, then merge descriptions

### R8. Window Overlap and Z-Order Complexity

**Severity: Low-Medium | Likelihood: Medium**

On a busy desktop, windows may overlap. The GNOME extension provides the active window
title, but occluded windows may be partially visible.

**Mitigation:**
- GNOME window geometry data typically includes z-order; crop only fully visible portions
- The global layout scan (Phase 1) captures the visual state as-is, including overlaps
- Accept that partially occluded windows will have incomplete descriptions — this is
  acceptable for the classification use case

### R9. NixOS-Specific Challenges

**Severity: Low | Likelihood: Medium**

- Ollama CUDA support on NixOS requires proper NVIDIA driver configuration
- The `nixos-hardware` and `nvidia` modules must be correctly configured
- Ollama's sandboxed execution may need adjustments for GPU access

**Mitigation:**
- Use `hardware.nvidia.modesetting.enable = true;` and appropriate driver packages
- Ensure `services.ollama.acceleration = "cuda";` is set
- Test GPU access with `ollama run qwen2.5-vl:7b` (smaller model) before pulling the 72B

### R10. Data Retention and Storage Costs

**Severity: Low | Likelihood: Certain**

Each screenshot description will be approximately 2-10 KB of text. At one sample every
5 minutes during an 8-hour workday: ~96 samples/day × ~5 KB = ~480 KB/day = ~10 MB/month.
This is negligible.

However, if raw screenshots are retained temporarily for quality validation, 4K PNG
screenshots are ~15-25 MB each: 96/day × 20 MB = ~1.9 GB/day.

**Mitigation:**
- Delete raw screenshots after successful processing and validation
- Keep a rolling buffer of the last N screenshots for debugging
- Store only text descriptions long-term

---

## OPEN QUESTIONS

### OQ1. Ollama's Actual Resolution Handling for Qwen2.5-VL

**Critical to verify before implementation.**

How does Ollama preprocess images before passing them to Qwen2.5-VL? Specifically:
- Does it respect the model's native `max_pixels` configuration?
- Can `max_pixels` be overridden in the Modelfile or via API parameters?
- At what resolution does the model actually "see" the image?

**Verification steps:**
1. Pull `qwen2.5-vl:72b` and send a 4K screenshot with known small text
2. Ask the model to read specific small text — if it can, resolution is preserved
3. If it can't, check `ollama show qwen2.5-vl:72b --modelfile` for resolution settings
4. Experiment with custom Modelfiles that set higher resolution parameters

### OQ2. Optimal Quantization Level for OCR Tasks

**Important for quality tuning.**

What is the empirical OCR accuracy difference between Q4_K_M, Q5_K_M, and Q6_K for
Qwen2.5-VL-72B on desktop screenshot text?

**Verification steps:**
1. Capture a reference screenshot with text at various sizes
2. Process with Q4_K_M, measure character accuracy against ground truth
3. If accuracy is insufficient, try Q5_K_M or Q6_K
4. Find the quantization level that achieves >95% character accuracy on 12px+ text

### OQ3. Newer Models Released After Training Cutoff

**Should be checked before final deployment.**

As of February 2026, there may be newer vision models not in this analysis:
- **Qwen3-VL** — If released, likely surpasses Qwen2.5-VL across all metrics
- **Llama 4 Vision** — Meta's next-generation multimodal model
- **InternVL3** — Potential successor to InternVL2.5
- **Gemma 3 or 4 with enhanced vision** — Google's updated models

**Verification steps:**
1. Check Ollama model library: `ollama list` and the Ollama website
2. Check Hugging Face Open LLM Leaderboard for vision models
3. Search for "best local vision model 2026" on Reddit r/LocalLLaMA
4. Compare any new models' DocVQA, OCRBench, TextVQA scores against Qwen2.5-VL-72B

### OQ4. GNOME Extension Compatibility and Window Geometry Data

**Required for the window-aware cropping approach.**

- Which GNOME extension does the user currently use for window title polling?
- Does it also export window geometry (x, y, width, height)?
- If not, can `xdotool` (X11) or `wlr-randr`/`hyprctl` (Wayland) provide this data?
- On GNOME Wayland, does `gdbus` expose window geometry via the Mutter interface?

**Verification steps:**
1. Check the GNOME extension's capabilities and output format
2. Test `gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell --method org.gnome.Shell.Eval 'global.get_window_actors().map(a => ({title: a.meta_window.get_title(), rect: a.meta_window.get_frame_rect()}))'` to get window geometry from GNOME Shell
3. If geometry is unavailable, fall back to grid-based chunking

### OQ5. Screenshot Capture on Wayland

**NixOS + GNOME defaults to Wayland.**

- `gnome-screenshot` works on Wayland but may be deprecated in favor of the GNOME
  Screenshot portal
- `grim` is the standard Wayland screenshot tool (for wlroots compositors, not GNOME)
- For GNOME Wayland: `dbus-send` to the GNOME Screenshot portal or use `gnome-screenshot`
- Python libraries like `mss` may not work on Wayland

**Verification steps:**
1. Test `gnome-screenshot --file=/tmp/test.png` on your system
2. If deprecated, use the D-Bus screenshot portal:
   `gdbus call --session --dest org.gnome.Shell.Screenshot --object-path /org/gnome/Shell/Screenshot --method org.gnome.Shell.Screenshot.Screenshot false true '/tmp/test.png'`
3. Verify the captured image is full resolution (3840x2160)

### OQ6. Structured Output Reliability

**Affects downstream classification pipeline.**

Can Qwen2.5-VL-72B reliably produce structured JSON output when prompted? LLMs sometimes
break JSON formatting, especially in long outputs.

**Verification steps:**
1. Test with a structured output prompt and validate JSON parsing
2. Consider using Ollama's `format: "json"` parameter if available
3. Implement a JSON repair/retry mechanism in the processing pipeline
4. Alternatively, use a more structured approach: extract specific fields in separate
   queries rather than one large JSON response

### OQ7. Throughput Under Concurrent GNOME Desktop Use

**Practical concern for user experience.**

Running a 72B model inference on the GPU while using it for GNOME desktop rendering:
- Will there be noticeable UI lag during model inference?
- Does Ollama properly yield GPU resources when idle?
- Should model inference be deferred to idle periods?

**Verification steps:**
1. Run `ollama run qwen2.5-vl:72b` with a test image while using the desktop
2. Monitor GPU utilization with `nvidia-smi` during inference
3. Check for UI stuttering, especially in GPU-accelerated applications
4. If lag is unacceptable, schedule inference during idle periods or cap GPU utilization

### OQ8. Client Confidentiality in Description Text

**Important for the consulting use case.**

The generated descriptions will contain verbatim text from client work. Considerations:
- Are descriptions stored in an encrypted database?
- Is there any risk of descriptions leaking between client contexts?
- Should descriptions be encrypted per-client or stored in client-specific databases?

**This is not a model selection issue but an architectural concern for the classification
system that should be addressed before deployment.**

### OQ9. Baseline Comparison: Qwen2.5-VL-72B vs. Qwen2.5-VL-7B

**Cost-benefit analysis for daily use.**

The 7B model is dramatically faster (~5-10x) and uses much less VRAM (~5 GB). For the
window-cropping approach, where each crop is relatively small and high-contrast:
- Is the 72B model's accuracy advantage worth the latency and resource cost?
- Could the 7B model produce "good enough" descriptions for classification purposes?

**Verification steps:**
1. Process the same set of 20+ screenshots with both 7B and 72B
2. Compare description quality, especially text accuracy and completeness
3. If the 7B is >90% as good, it may be the better daily driver
4. Consider using 7B for routine sampling and 72B for detailed analysis on demand

### OQ10. Alternative Approach: Dedicated OCR + Vision Description

**Potentially more accurate for text-heavy workflows.**

Instead of relying solely on the vision-language model for both OCR and scene understanding,
a hybrid approach could be:
1. **PaddleOCR or Tesseract** for precise text extraction (fast, deterministic, no hallucination)
2. **Qwen2.5-VL** for visual scene understanding (layout, images, charts, UI state)
3. Merge OCR text + visual description for the final output

**Trade-off:** More complex pipeline, but potentially more accurate text extraction with
fewer hallucinations. Worth evaluating if the vision model's OCR proves insufficient.

**Verification steps:**
1. Run PaddleOCR on a 4K screenshot crop and measure accuracy
2. Compare with Qwen2.5-VL's text extraction on the same crop
3. If PaddleOCR is significantly better at text, implement the hybrid approach
4. Consider PaddleOCR v4 or newer for best accuracy
