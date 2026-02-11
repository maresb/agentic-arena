## RISKS — Known risks, edge cases, trade-offs.
- **Silent downscaling:** If max pixel budgets are not enforced explicitly, 4K crops can be downscaled, recreating hallucination risk.
- **Dimension rounding:** Qwen3-VL expects resized dimensions in multiples of 32; incorrect rounding can misalign coordinates and degrade OCR.
- **VRAM pressure:** Large crops and higher precision can exceed VRAM once visual KV cache is included.
- **Wayland geometry limits:** Window bounds/z-order may be inaccessible; fallback tiling required.
- **Latency/UI contention:** Multi-window inference plus OCR passes can be slow and impact desktop responsiveness.
- **JSON validity:** Long outputs can break JSON; requires repair/retry logic.
- **OCR disagreement:** GLM-OCR and Qwen3-VL may disagree; requires conflict-resolution rules.
- **OCR over-trust:** OCR can misread UI chrome (icons, small labels); avoid replacing semantically important UI labels without confidence checks.

## OPEN QUESTIONS — Uncertainties requiring verification.
- What is the effective `max_pixels`/resize behavior in your Ollama build for Qwen3-VL?
- Can your GNOME extension (or `gdbus`) reliably provide window geometry and z-order?
- Which pixel budget (2.1 MP vs 4.2 MP) yields acceptable OCR for your smallest UI text?
- How many window crops can be batched per request without exceeding context/VRAM limits?
- Do you want a unified global description or only per-window records?
- What change-detection threshold should trigger re-processing (hash delta, focus change)?
- How accurate is GLM-OCR on UI screenshots (not just documents), and where should it override Qwen3-VL?

## DISAGREEMENTS — Any remaining substantive disagreements with other approaches, or "None."
None.
