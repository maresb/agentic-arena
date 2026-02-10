## RISKS
- **Ollama downscaling:** The runtime may enforce a pixel budget and downscale 4K images, causing illegible text and hallucinations.
- **VRAM pressure at high resolution:** Full 4K + large quantization (Q8) can exceed available VRAM once visual KV cache is included.
- **Window geometry access:** GNOME extensions may not expose window bounds reliably under Wayland; without geometry, tiling is required.
- **Latency:** Multi-window processing is slow; long-running inference may impact desktop responsiveness.
- **Structured output drift:** Even with JSON prompts, models can occasionally emit invalid JSON; robust parsing or retries are needed.
- **Small/low-contrast text:** UI themes and thin fonts reduce OCR accuracy; some text may remain unreadable without extra zooming.
- **Overlapping windows:** Occlusions can cause incomplete descriptions for partially visible windows.

## OPEN QUESTIONS
- What is the effective **max_pixels** behavior in your Ollama build for Qwen2.5-VL?
- How many window crops can be batched per request before context or VRAM limits are hit?
- Does your GNOME extension (or Mutter via gdbus) provide **reliable window geometry**?
- What quantization level (Q4/Q5/Q6/Q8) yields acceptable OCR accuracy on your smallest UI text?
- Do you prefer per-window storage only, or also a unified global summary?

## DISAGREEMENTS
- **“No chunking needed for 4K”**: This is unsafe without verifying the runtime’s pixel budget; window crops/tiling remain necessary safeguards.
- **Q8_0 as the default**: It is not universally safe for full 4K; Q4/Q5 is the conservative starting point unless you confirm VRAM headroom.
