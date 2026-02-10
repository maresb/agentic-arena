# Round 00 Evaluate — Agent A Critique

## Agent C — Critique

### Strengths
1. **Concise and well-structured.** Agent C delivers a clear, readable recommendation
   without unnecessary padding. The PLAN section is easy to follow.
2. **Correctly identifies dynamic resolution as the critical feature.** The emphasis on
   "Naive Dynamic Resolution" as the key differentiator is spot-on.
3. **Pragmatic "try native first" approach.** Suggesting that Qwen2.5-VL can process
   full 4K without chunking as the *first* attempt is a reasonable starting point, with
   the 2x2 quadrant fallback if it fails.
4. **Good prompt engineering advice.** Injecting the active window title into the prompt
   to ground the model is a practical and effective technique.
5. **Storage reduction math.** The ~5MB → ~2KB per screenshot figure effectively
   communicates the data reduction benefit.

### Weaknesses
1. **Insufficient VRAM accounting.** Agent C claims Q8_0 (~77 GB weights) "fits entirely
   in VRAM" on 96 GB, but does not account for KV cache required by visual tokens. A 4K
   image at native resolution generates ~10,500 visual tokens, each requiring KV cache
   across 80 layers. This adds 20-26 GB, which would push Q8_0 total VRAM to 97-103 GB —
   exceeding the 96 GB card. The claim that Q8_0 is the recommended quantization for full
   4K processing is incorrect without either reducing image resolution or using Q4/Q5.
2. **"Manual chunking is largely obsolete" is misleading.** The default `max_pixels` for
   Qwen2.5-VL is ~1,003,520 pixels (~1001×1001). A 4K screenshot has 8.3M pixels. Unless
   `max_pixels` is explicitly increased (which Agent C doesn't mention), the model *will*
   downscale the image significantly — exactly the problem the user experienced before.
3. **No merge/synthesis strategy.** For the 2x2 quadrant fallback, Agent C says "concatenate
   the descriptions" but provides no deduplication or synthesis mechanism. Raw concatenation
   of overlapping tile descriptions will produce redundant and incoherent output.
4. **Missing VRAM budget table.** No breakdown of where the 96 GB goes (weights, KV cache,
   activations, overhead). This makes the quantization recommendation ungrounded.
5. **Light on alternatives.** Only mentions Qwen2.5-VL. No comparison table or discussion
   of InternVL2.5, DeepSeek-VL2, or other contenders.

### Errors
1. **Q8_0 VRAM claim.** Q8_0 at ~72-77 GB weights + KV cache for 10K+ visual tokens does
   not fit in 96 GB for full 4K native processing. This is a factual error.
2. **"Manual chunking is largely obsolete."** This is incorrect for the default Ollama
   configuration of Qwen2.5-VL, which has a pixel budget that will downscale 4K images.
   The user's prior hallucination problem was likely caused by exactly this default behavior.

---

## Agent B — Critique

### Strengths
1. **Most practical tiling strategy.** The stride-based tiling math (tile=1344, overlap=12%,
   stride=1182) with concrete tile counts for both 4K and 5K is immediately implementable.
   This is the most actionable tiling guidance of all three agents.
2. **Structured JSON output per tile.** The schema with `tile_bbox`, `text_blocks` (with
   per-block confidence and bbox), `ui_elements`, and `summary` is excellent for downstream
   classification. This structured approach is superior to free-text descriptions for
   automated processing.
3. **Deduplication strategy.** IoU-based bbox overlap + normalized Levenshtein similarity
   for text deduplication in overlap regions is a well-thought-out merge algorithm.
4. **Delta storage.** Storing only text/layout diffs between consecutive frames is a smart
   optimization that reduces storage and improves classification signal-to-noise ratio.
5. **Alternative model discussion.** Mentioning InternVL2.5-76B and LLaVA-OneVision-72B
   with guidance on when to choose them is helpful for the user.
6. **Supplementary tools.** Recommending pyvips for memory-efficient tiling and secondary
   OCR cross-checking (Tesseract/RapidOCR) shows practical experience.
7. **Architectural advice for classification.** Session segmentation, hierarchical labeling,
   human-in-the-loop review, and privacy considerations are all valuable for the future
   classification pipeline.

### Weaknesses
1. **Square tiles (1344×1344) are suboptimal for desktop screenshots.** Desktop layouts
   are landscape (16:9). Square tiles waste coverage efficiency — you get 8 tiles for 4K
   instead of 4 landscape tiles (1920×1080). The extra tiles double processing time.
2. **No window-aware cropping.** Agent B uses purely geometric tiling and doesn't leverage
   the GNOME extension's window geometry data, which the user explicitly mentioned having.
   Window-aware cropping is more semantically meaningful and avoids splitting windows
   across tile boundaries.
3. **Structured bbox output may be unreliable.** Asking a VLM to produce pixel-accurate
   bounding boxes for text blocks is ambitious. VLMs are notoriously imprecise at spatial
   localization. The confidence scores and bbox coordinates may be hallucinated or
   inaccurate, undermining the deduplication algorithm.
4. **Missing global layout pass detail.** The two-pass strategy mentions a "high-level
   layout summary" in the global pass but doesn't specify the prompt or expected output
   format in as much detail as the tile pass.
5. **InternVL2.5 parameter count.** Cited as "76B" — typically reported as 78B in the
   literature. Minor but worth noting.

### Errors
1. **InternVL2.5-76B → 78B.** The model is generally cited as InternVL2.5-78B. This is
   a minor factual inaccuracy.

---

## Agent A (self) — Critique

### Strengths
1. **Most detailed VRAM budget analysis.** The component-level breakdown (weights, visual
   KV cache, text KV cache, activations) with concrete GB estimates is the most thorough
   of all three agents, and correctly identifies the tight fit for full 4K native processing.
2. **Three-phase processing is the most robust approach.** Global layout scan → window-aware
   detailed extraction → text-only synthesis provides redundancy and semantic coherence.
3. **Window-aware cropping as primary strategy.** Leveraging GNOME window geometry data
   instead of arbitrary grid tiles is more semantically meaningful and produces cleaner
   per-window descriptions.
4. **Most comprehensive risk assessment.** 10 detailed risks with severity/likelihood
   ratings and mitigations cover the full deployment landscape.
5. **NixOS-specific guidance.** Configuration.nix snippets for Ollama with CUDA are
   directly useful for the user's environment.
6. **Full pseudocode pipeline.** Ready-to-adapt Python implementation with Ollama API
   integration.

### Weaknesses
1. **Possibly over-engineered.** The three-phase approach with a separate synthesis LLM
   pass may be overkill for many screenshots. A simpler single-pass on window crops might
   suffice in practice.
2. **Pseudocode bug.** `query_vision("", synthesis_prompt)` in Phase 3 won't work — the
   Ollama API requires either an images array with content or no images field at all. An
   empty string is not a valid base64 image.
3. **Speculative accuracy estimates.** The text accuracy table (95-98% for large text,
   80-90% for small text, etc.) is reasonable but unsourced. These should be presented as
   rough expectations to be verified empirically.
4. **Missing structured output format.** Unlike Agent B, my solution uses free-text
   descriptions without specifying a JSON schema for per-window output. This makes
   downstream classification harder.
5. **No delta storage concept.** Each screenshot is processed independently with no
   optimization for consecutive frames that are largely identical.

### Errors
1. **Pseudocode `query_vision("", synthesis_prompt)` is broken.** The empty string for
   image_b64 will cause an API error or malformed request.

---

## My Position

### What I'm keeping from my original approach and why

1. **Three-phase processing (global → window crops → synthesis).** This remains the most
   robust architecture. The global pass provides spatial context that pure tiling lacks,
   and the synthesis pass produces coherent unified descriptions. All three agents agree
   on multi-pass; my version is the most structured.

2. **Window-aware cropping as the primary strategy.** The user explicitly has a GNOME
   extension for window title polling. Extending this to window geometry (via `gdbus` or
   Mutter's API) is a natural and superior alternative to arbitrary grid tiling. Windows
   are the semantic units of a desktop — cropping by window produces descriptions that
   map directly to activities.

3. **Q4_K_M as the recommended starting quantization.** Agent C's Q8_0 recommendation
   doesn't account for KV cache. Q4_K_M at ~42 GB leaves ample room. Q5_K_M is a
   reasonable upgrade if quality demands it.

4. **Comprehensive risk analysis.** The 10 risks and 10 open questions provide the user
   with a complete picture of what to verify before committing to this architecture.

5. **NixOS-specific guidance.** None of the other agents provided `configuration.nix`
   snippets or addressed NixOS-specific Ollama/CUDA setup.

### What I'd adopt from others and why

1. **From Agent B: Structured JSON output schema.** Agent B's per-tile JSON schema with
   `text_blocks`, `ui_elements`, and `summary` is superior to my free-text approach for
   downstream classification. I'd adapt this for per-window output instead of per-tile.

2. **From Agent B: Delta storage between consecutive frames.** Storing only diffs when
   the desktop state hasn't changed significantly is a smart optimization I overlooked.
   Combined with screenshot hashing (which I mentioned in risks), this reduces storage
   and improves classification signal.

3. **From Agent B: Secondary OCR cross-checking.** The suggestion to use Tesseract or
   RapidOCR as a cross-check for critical text is a practical hedge against VLM
   hallucination that I mentioned as an open question (OQ10) but should promote to a
   recommended practice.

4. **From Agent C: "Try native resolution first" as step 0.** Before implementing the
   full three-phase pipeline, a simple test of feeding the full 4K image to the model
   (with increased `max_pixels`) would quickly reveal whether the multi-pass complexity
   is even needed. This is a good empirical-first approach.

5. **From Agent B: pyvips for image processing.** More memory-efficient than Pillow for
   large images. Worth recommending for the tiling/cropping pipeline.

### What I still disagree on and why

1. **Agent C: "Manual chunking is largely obsolete."** This is dangerously misleading.
   The default `max_pixels` in Qwen2.5-VL *will* downscale 4K images unless explicitly
   overridden, and Ollama may apply its own resolution constraints on top. The user's
   previous failure was likely caused by exactly this assumption. Chunking/cropping is
   not obsolete — it's the primary defense against downscaling-induced hallucination.

2. **Agent C: Q8_0 as the recommended quantization.** Without accounting for KV cache,
   Q8_0 cannot safely process full 4K images on 96 GB. Q4_K_M or Q5_K_M is the correct
   recommendation for comfortable operation with high-resolution inputs.

3. **Agent B: Square tiles (1344×1344) as the default tiling approach.** Desktop
   screenshots are 16:9 landscape. Square tiles produce 8 tiles for 4K coverage vs. 4
   landscape tiles (1920×1080). The doubled tile count doubles inference time with no
   benefit. Landscape tiles or window-aware crops are more efficient.

4. **Agent B: Pixel-accurate bboxes from VLMs.** Expecting the model to produce reliable
   pixel-level bounding boxes for text blocks and UI elements is optimistic. VLMs are
   weak at precise spatial localization. The deduplication algorithm built on IoU of
   potentially hallucinated bboxes may be unreliable. A simpler text-similarity-based
   deduplication (without spatial coordinates) would be more robust.
