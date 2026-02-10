## RISKS
- **Ollama downscaling:** The runtime may cap pixel budget and downscale 4K inputs, causing illegible text and hallucinations.
- **VRAM pressure:** Full-resolution crops plus large quantization (Q8) can exceed VRAM once visual KV cache is included.
- **Wayland geometry limits:** Window bounds or z-order may be inaccessible; without geometry, you must fall back to grid tiling.
- **Latency and UI contention:** Multi-window inference can be slow and may impact desktop responsiveness.
- **JSON validity:** Long outputs can break JSON; parsing/repair logic is required.
- **Occlusion/overlap:** Partially visible windows lead to incomplete or contradictory text.
- **Small/low-contrast text:** Thin fonts or dark themes reduce OCR accuracy.

## OPEN QUESTIONS
- What is the effective `max_pixels` behavior in your Ollama build for Qwen2.5-VL?
- Can your GNOME extension (or `gdbus`) reliably provide window geometry and z-order?
- What quantization level (Q4/Q5/Q6) yields acceptable OCR on your smallest UI text?
- How many window crops can be batched per request without exceeding context/VRAM limits?
- Do you want a single unified description per screenshot or per-window records only?
- What change-detection threshold should trigger re-processing (hash delta, focus change)?

## DISAGREEMENTS
- **Q8_0 as default:** I still recommend Q4/Q5 as the safe baseline; Q8 should be tested only for smaller crops.
- **Benchmark figures without sources:** Avoid quoting specific scores unless verified.
