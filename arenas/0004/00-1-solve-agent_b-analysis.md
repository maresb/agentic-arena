## RISKS — Known risks, edge cases, trade-offs.
- **Model availability in Ollama:** Qwen2.5-VL-72B may not be packaged; you may need to use Qwen2-VL or another model.
- **Downscaling hallucinations:** If tiles are too large or downscaling is aggressive, OCR accuracy drops and hallucinations reappear.
- **Latency and throughput:** Multi-tile processing is slow; batching tiles can hit context limits and raise VRAM usage.
- **UI theme variability:** Low-contrast themes and thin fonts reduce OCR accuracy.
- **Small text and icons:** Very small UI text or icon-only controls can be missed without higher zoom tiles.
- **Merge errors:** Deduplication may accidentally drop or conflate similar text in overlapping regions.
- **Prompt sensitivity:** OCR detail varies significantly with prompt wording and output format constraints.

## OPEN QUESTIONS — Uncertainties requiring verification.
- Is Qwen2.5-VL-72B directly available in your Ollama build, or do you need a custom gguf?
- What is the actual max image resolution supported by your chosen model/runtime before it auto-downscales?
- How many tiles can you safely batch per request without exceeding context or VRAM limits?
- Do you prefer a single global description or a structured per-window record for storage?
- Will your GNOME extension expose window geometry so tiles can align to window bounds?
