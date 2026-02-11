## RISKS — Known risks, edge cases, trade-offs.

1.  **Latency**: Running two models (VLM + OCR) sequentially per window will add significant latency (15-30s per window).
    *   *Mitigation*: Selective execution (skip GLM-OCR on image-heavy windows). Asynchronous processing. Update the semantic description only when window focus changes or on a slow timer. Use delta hashing to skip unchanged windows.
2.  **Ollama Resource Contention**: Loading two large models (32B + 0.9B) might strain system memory or cause thrashing if not configured correctly.
    *   *Mitigation*: Ensure `OLLAMA_MAX_LOADED_MODELS="2"` is set in NixOS config. The 96GB VRAM is ample for both.
3.  **VRAM Overhead**: Qwen3-VL-32B at Q8_0 uses ~34GB, leaving ~62GB. GLM-OCR uses <1GB. This is safe, but watch for KV cache growth with long contexts.
    *   *Mitigation*: Monitor VRAM usage. If OOM occurs, switch Qwen3-VL to Q4_K_M.

## OPEN QUESTIONS — Uncertainties requiring verification.

1.  **Ollama Multi-Model Support**: Does the specific version of Ollama packaged in NixOS support concurrent model loading efficiently?
2.  **GLM-OCR Accuracy**: Is GLM-OCR truly superior to Qwen3-VL's internal OCR for this specific screenshot domain? A/B testing is recommended.

## DISAGREEMENTS — Any remaining substantive disagreements with the other approaches, or "None."

None. All agents have converged on the new **Qwen3-VL-32B + GLM-OCR** architecture, recognizing the paradigm shift from the older Qwen2.5-VL recommendation.
