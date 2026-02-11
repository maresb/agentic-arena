## RISKS
- **Ollama downscaling:** Pixel-budget caps may downscale 4K inputs, making text illegible.
- **VRAM pressure:** High-res crops plus large quantization can exceed VRAM with KV cache.
- **Wayland geometry limits:** Window bounds/z-order may be inaccessible; fallback tiling needed.
- **Latency/UI contention:** Multi-window inference can be slow and may impact desktop responsiveness.
- **JSON validity:** Long outputs can break JSON; requires repair/retry logic.
- **Occlusions:** Partially visible windows yield incomplete or conflicting text.
- **Small/low-contrast text:** Thin fonts and low contrast reduce OCR accuracy.

## OPEN QUESTIONS
- What is the effective `max_pixels` behavior in your Ollama build?
- Can your GNOME extension (or `gdbus`) reliably provide window geometry and z-order?
- Which quantization level (Q4/Q5/Q6) yields acceptable OCR on your smallest UI text?
- How many window crops can be batched per request without exceeding context/VRAM limits?
- Do you want a unified global description or only per-window records?
- What change-detection threshold should trigger re-processing (hash delta, focus change)?

## DISAGREEMENTS
None.
